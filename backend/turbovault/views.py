import json
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
    """
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

    try:
        # Extract basic project info
        name = request.POST.get("name")
        description = request.POST.get("description", "")
        
        if not name:
            return JsonResponse({"status": "error", "message": "Project name is required"}, status=400)

        # Extract config values
        stage_schema = request.POST.get("stage_schema", "stage")
        rdv_schema = request.POST.get("rdv_schema", "rdv")
        
        # Naming standards
        naming_config = {}
        if request.POST.get("modify_defaults") == "true":
            naming_config["hashdiff_naming"] = request.POST.get("hashdiff_naming", "hd_[[ satellite_name ]]")
            naming_config["hashkey_naming"] = request.POST.get("hashkey_naming", "hk_[[ entity_name ]]")
            naming_config["satellite_v0_naming"] = request.POST.get("satellite_v0_naming", "[[ satellite_name ]]_v0")
            naming_config["satellite_v1_naming"] = request.POST.get("satellite_v1_naming", "[[ satellite_name ]]_v1")

        # Handle file upload if metadata import is requested
        import_metadata = request.POST.get("import_metadata") == "true"
        source_file = request.FILES.get("source_file")
        source_type = request.POST.get("source_type")

        # Check if project already exists
        if Project.objects.filter(name=name).exists():
            return JsonResponse({"status": "error", "message": f"Project '{name}' already exists"}, status=400)

        # Create project
        project = Project.objects.create(
            name=name,
            description=description,
            config={
                "stage_schema": stage_schema,
                "rdv_schema": rdv_schema,
                **naming_config,
            }
        )

        # Create default snapshot controls FIRST (if fresh)
        # or ensure import handles it. CLI uses skip_snapshots=False.
        from engine.cli.utils.db_utils import create_default_snapshot_controls, ensure_templates_populated
        create_default_snapshot_controls(project)
        ensure_templates_populated()

        # Import metadata if requested
        if import_metadata and source_file:
            _handle_metadata_import(project, source_file, source_type)

        return JsonResponse({
            "status": "success", 
            "message": f"Project '{name}' created successfully",
            "project_id": str(project.project_id)
        })

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


def _handle_metadata_import(project: Project, source_file: UploadedFile, source_type: str) -> None:
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
