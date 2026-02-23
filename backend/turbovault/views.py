import os
import sqlite3
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import UploadedFile
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from engine.models import Project


def home(request: HttpRequest) -> HttpResponse:
    """
    Render the TurboVault Engine landing page.
    """
    return render(request, "home.html")


def init_wizard(request: HttpRequest) -> HttpResponse:
    """
    Render the TurboVault Project Initialization Wizard.
    """
    return render(request, "init_wizard.html")


def check_project_name(request: HttpRequest) -> HttpResponse:
    """
    Check if a project name already exists.
    """
    name = request.GET.get("name", "").strip()
    exists = Project.objects.filter(name=name).exists() if name else False
    return JsonResponse({"exists": exists})


@csrf_exempt
def create_project(request: HttpRequest) -> HttpResponse:
    """
    Handle project creation from the web wizard.

    Mirrors the CLI 'turbovault project init' flow:
      1. Build a TurboVaultConfig from the submitted form data
      2. Create the Project DB record
      3. Initialize project folder + config.yml on disk
      4. Create default snapshot controls
      5. Optionally import metadata from an uploaded file
    """
    if request.method != "POST":
        return JsonResponse(
            {"status": "error", "message": "Method not allowed"}, status=405
        )

    try:
        # ── Extract form values ───────────────────────────────────────────────
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()

        if not name:
            return JsonResponse(
                {"status": "error", "message": "Project name is required"}, status=400
            )

        stage_schema = request.POST.get("stage_schema", "stage").strip() or "stage"
        rdv_schema = request.POST.get("rdv_schema", "rdv").strip() or "rdv"

        # Optional naming standards
        config_section: dict = {}
        if request.POST.get("modify_defaults") == "true":
            for key in (
                "hashdiff_naming",
                "hashkey_naming",
                "satellite_v0_naming",
                "satellite_v1_naming",
            ):
                value = request.POST.get(key)
                if value:
                    config_section[key] = value

        # ── Duplicate name check ──────────────────────────────────────────────
        if Project.objects.filter(name=name).exists():
            return JsonResponse(
                {"status": "error", "message": f"Project '{name}' already exists"},
                status=400,
            )

        # ── Build TurboVaultConfig (same shape as config.yml) ────────────────
        from engine.services.config_loader import load_config_from_dict

        config_dict: dict = {
            "project": {"name": name, "description": description},
            "configuration": {
                "stage_schema": stage_schema,
                "rdv_schema": rdv_schema,
                **config_section,
            },
            "output": {
                "create_zip": False,
                "export_sources": True,
            },
        }
        config = load_config_from_dict(config_dict)

        # ── Create Project DB record ──────────────────────────────────────────
        project = Project.objects.create(name=name, description=description)

        # ── Initialize project folder + config.yml on disk ───────────────────
        from engine.services.project_config import initialize_project_folder

        initialize_project_folder(project, config)

        # ── Default snapshot controls ─────────────────────────────────────────
        from engine.cli.utils.db_utils import (
            create_default_snapshot_controls,
            ensure_templates_populated,
        )

        create_default_snapshot_controls(project)
        ensure_templates_populated()

        # ── Optional metadata import ──────────────────────────────────────────
        import_metadata = request.POST.get("import_metadata") == "true"
        source_file = request.FILES.get("source_file")
        source_type = request.POST.get("source_type")

        if import_metadata and source_file:
            _handle_metadata_import(project, source_file, source_type)

        return JsonResponse(
            {
                "status": "success",
                "message": f"Project '{name}' created successfully",
                "project_id": str(project.project_id),
            }
        )

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


def _handle_metadata_import(
    project: Project, source_file: UploadedFile, source_type: str
) -> None:
    """Helper to handle metadata import from uploaded file."""
    # Use the original file extension to ensure compatibility with import services
    suffix = Path(source_file.name).suffix

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in source_file.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        if source_type == "excel":
            from engine.services.excel_sqlite_adapter import ExcelImport

            service = ExcelImport(tmp_path)
            # Use skip_snapshots=False to match CLI interactive behavior
            service.import_metadata(project=project, skip_snapshots=False)
        elif source_type == "sqlite":
            conn = sqlite3.connect(tmp_path)
            from engine.services.sqlite_import import SqliteImportService

            service = SqliteImportService(conn)
            # Use skip_snapshots=False to match CLI interactive behavior
            service.import_metadata(project=project, skip_snapshots=False)
            conn.close()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
