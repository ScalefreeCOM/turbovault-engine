"""
Reusable Engine workflows for CLI and embedded callers.

These functions keep command-line concerns out of callers such as Turbovault
Studio. They assume Django has already been configured by the host process.
"""

from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from django.db import transaction

from engine.models import Project
from engine.services.export.builder import ModelBuilder
from engine.services.export.exporters.dbml_exporter import DBMLExporter
from engine.services.export.exporters.json_exporter import JSONExporter
from engine.services.generation import (
    DbtProjectGenerator,
    GenerationConfig,
    TemplateResolver,
    validate_export,
)
from engine.services.runtime_config import (
    EngineRuntimeConfig,
    resolve_runtime_config,
)

if TYPE_CHECKING:
    from engine.services.export.models import ProjectExport
    from engine.services.generation.report import GenerationReport
    from engine.services.generation.validators import ValidationResult


class EngineWorkflowError(Exception):
    """Raised when a reusable Engine workflow cannot complete."""

    def __init__(
        self,
        message: str,
        *,
        validation_result: ValidationResult | None = None,
    ) -> None:
        super().__init__(message)
        self.validation_result = validation_result


def create_project(
    *,
    name: str,
    description: str = "",
    runtime_config: EngineRuntimeConfig | None = None,
) -> Project:
    """Create an Engine project without creating any workspace folders."""
    project_name = runtime_config.project_name if runtime_config else name
    project_description = (
        runtime_config.project_description if runtime_config else description
    )
    return Project.objects.create(
        name=project_name or name,
        description=project_description or "",
    )


def import_metadata(
    *,
    project: Project,
    source_type: str,
    path: str | Path,
    skip_snapshots: bool = True,
) -> Project:
    """Import Excel, SQLite, or JSON metadata into an existing Engine project."""
    source_path = Path(path)
    normalized_type = source_type.lower()

    with transaction.atomic():
        if normalized_type == "excel":
            from engine.services.excel_sqlite_adapter import ExcelImport

            service = ExcelImport(str(source_path))
            return service.import_metadata(
                project=project, skip_snapshots=skip_snapshots
            )

        if normalized_type == "sqlite":
            from engine.services.sqlite_import import SqliteImportService

            conn = sqlite3.connect(str(source_path))
            try:
                service = SqliteImportService(conn)
                return service.import_metadata(
                    project=project, skip_snapshots=skip_snapshots
                )
            finally:
                conn.close()

        if normalized_type == "json":
            from engine.services.json_import import JsonImportService

            service = JsonImportService(source_path)
            return service.import_metadata(project=project)

    raise EngineWorkflowError(f"Unsupported metadata source type: {source_type}")


def build_project_export(
    *,
    project: Project,
    runtime_config: EngineRuntimeConfig | None = None,
    export_sources: bool | None = None,
    generate_tests: bool | None = None,
    generate_dbml: bool | None = None,
) -> ProjectExport:
    """Build the target-agnostic Engine export model for a project."""
    resolved_config = resolve_runtime_config(project, runtime_config)
    builder = ModelBuilder(project, runtime_config=resolved_config)
    return builder.build(
        export_sources=(
            resolved_config.export_sources
            if export_sources is None
            else export_sources
        ),
        generate_tests=(
            resolved_config.generate_tests if generate_tests is None else generate_tests
        ),
        generate_dbml=(
            resolved_config.generate_dbml if generate_dbml is None else generate_dbml
        ),
    )


def validate_project_export(project_export: ProjectExport) -> ValidationResult:
    """Validate a project export before generation."""
    return validate_export(project_export)


def generation_config_from_runtime(
    runtime_config: EngineRuntimeConfig,
    *,
    mode: Literal["strict", "lenient"] = "strict",
    skip_validation: bool = False,
) -> GenerationConfig:
    """Convert runtime project settings into the dbt generator config."""
    project_name = runtime_config.dbt_project_name or runtime_config.project_name
    return GenerationConfig(
        project_name=(project_name or "turbovault_project").lower().replace(" ", "_"),
        profile_name="default",
        mode=mode,
        generate_satellite_v1_views=runtime_config.generate_satellite_v1_views,
        satellite_v0_naming=runtime_config.satellite_v0_naming,
        satellite_v1_naming=runtime_config.satellite_v1_naming,
        skip_validation=skip_validation,
        create_zip=runtime_config.create_zip,
        stage_schema=runtime_config.stage_schema,
        rdv_schema=runtime_config.rdv_schema,
        bdv_schema=runtime_config.bdv_schema,
    )


def generate_dbt_project(
    *,
    project_export: ProjectExport,
    runtime_config: EngineRuntimeConfig,
    output_path: str | Path,
    mode: Literal["strict", "lenient"] = "strict",
    skip_validation: bool = False,
    use_db_templates: bool = False,
) -> GenerationReport:
    """Generate a dbt project to ``output_path`` from an export model."""
    if not skip_validation:
        validation_result = validate_project_export(project_export)
        if not validation_result.is_valid and mode == "strict":
            raise EngineWorkflowError(
                "Project export validation failed",
                validation_result=validation_result,
            )

    generator = DbtProjectGenerator(
        output_path=Path(output_path),
        config=generation_config_from_runtime(
            runtime_config, mode=mode, skip_validation=skip_validation
        ),
        template_resolver=TemplateResolver(use_db_templates=use_db_templates),
    )
    return generator.generate(project_export)


def export_json(project_export: ProjectExport, *, indent: int | None = 2) -> str:
    """Render a project export as TurboVault JSON."""
    return JSONExporter(indent=indent).export(project_export)


def export_dbml(project_export: ProjectExport) -> str:
    """Render a project export as DBML."""
    return DBMLExporter().export(project_export)


def create_zip_archive(output_path: str | Path) -> Path:
    """Create a ZIP archive beside a generated dbt project directory."""
    output_dir = Path(output_path)
    zip_path = output_dir.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file in output_dir.rglob("*"):
            if file.is_file():
                zipf.write(file, file.relative_to(output_dir.parent))
    return zip_path
