"""
Stage 4 — Render.

Produces `GeneratedArtifact` objects in memory for each output type.
None of these artifacts have a `path` yet; the write stage decides what
to do with them (write to disk for a real run, discard for a dry-run).

For dbt: invokes the existing `DbtProjectGenerator` against a temporary
working directory, reads every emitted file back into memory, then
discards the temp tree. This keeps the dbt renderer un-refactored while
still giving us in-memory artifacts to ship through the report.

For json/dbml: calls the existing exporters and wraps their string
output in a single artifact.

Errors during render (template not found, render failure on one entity,
etc.) become `render.*` Issues. In `best_effort` mode the entity is
skipped and the pipeline continues; in `fail_fast` the runner aborts.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from engine.services.export.exporters.dbml_exporter import DBMLExporter
from engine.services.export.exporters.json_exporter import JSONExporter
from engine.services.export.models import ProjectExport
from engine.services.generation.errors import Code, make_issue
from engine.services.generation.folder_config import GenerationConfig
from engine.services.generation.generator import DbtProjectGenerator
from engine.services.generation.template_resolver import TemplateResolver
from engine.services.generation.types import (
    ArtifactKind,
    EntityRef,
    GeneratedArtifact,
    GenerationOptions,
    Issue,
    OutputType,
)
from engine.services.runtime_config import EngineRuntimeConfig

logger = logging.getLogger(__name__)


def render(
    *,
    project_export: ProjectExport,
    output_type: OutputType,
    runtime_config: EngineRuntimeConfig,
    options: GenerationOptions,
) -> tuple[list[GeneratedArtifact], list[Issue]]:
    """Produce artifacts (in memory) and any render-stage issues."""
    if output_type == "dbt":
        return _render_dbt(project_export, runtime_config, options)
    if output_type == "json":
        return _render_json(project_export, options)
    if output_type == "dbml":
        return _render_dbml(project_export, options)
    # Defensive: plan stage already rejects unsupported types.
    return (
        [],
        [
            make_issue(
                severity="error",
                code=Code.PLAN_UNSUPPORTED_OUTPUT_TYPE,
                stage="render",
                message=f"Unsupported output_type: {output_type}",
            )
        ],
    )


# ---------------------------------------------------------------------------
# dbt
# ---------------------------------------------------------------------------


def _render_dbt(
    project_export: ProjectExport,
    runtime_config: EngineRuntimeConfig,
    options: GenerationOptions,
) -> tuple[list[GeneratedArtifact], list[Issue]]:
    config = _build_dbt_config(runtime_config, options)
    template_resolver = TemplateResolver(use_db_templates=options.use_db_templates)

    # We always render into a temp tree so dry-runs cost no real-disk IO
    # past the temp directory, and so the write stage owns the final
    # placement. The DbtProjectGenerator writes files inline; we read them
    # back from the temp tree into in-memory artifacts here.
    with tempfile.TemporaryDirectory(prefix="turbovault-render-") as temp_dir:
        temp_root = Path(temp_dir)
        generator = DbtProjectGenerator(
            output_path=temp_root,
            config=config,
            template_resolver=template_resolver,
        )
        legacy_report = generator.generate(project_export)

        artifacts = _collect_dbt_artifacts(temp_root, legacy_report)
        issues = _translate_dbt_issues(legacy_report)
        return artifacts, issues


def _build_dbt_config(
    runtime_config: EngineRuntimeConfig, options: GenerationOptions
) -> GenerationConfig:
    """Translate runtime config + options into the legacy GenerationConfig
    the existing renderer still expects."""
    project_name = (
        runtime_config.dbt_project_name or runtime_config.project_name or "turbovault_project"
    )
    return GenerationConfig(
        project_name=(project_name or "turbovault_project").lower().replace(" ", "_"),
        profile_name="default",
        generate_satellite_v1_views=options.generate_satellite_v1_views,
        satellite_v0_naming=runtime_config.satellite_v0_naming,
        satellite_v1_naming=runtime_config.satellite_v1_naming,
        record_tracking_satellite_naming=runtime_config.record_tracking_satellite_naming,
        effectivity_satellite_naming=runtime_config.effectivity_satellite_naming,
        create_zip=options.create_zip,
        stage_schema=runtime_config.stage_schema,
        rdv_schema=runtime_config.rdv_schema,
        bdv_schema=runtime_config.bdv_schema,
    )


# Map (entity_type, file extension) → ArtifactKind. The dbt generator's
# `GeneratedFile.entity_type` uses values like "hub", "link", "satellite",
# "satellite_view" (v1), "pit", "reference_table", "snapshot_control",
# "stage", "source", "project". Everything else falls through to
# "sql_model" / "yaml_schema" based on the file extension.
_PROJECT_KIND_BY_FILENAME: dict[str, ArtifactKind] = {
    "dbt_project.yml": "project_yml",
    "packages.yml": "packages_yml",
    "sources.yml": "sources_yml",
    "profiles.yml": "dbt_profiles",
}


def _collect_dbt_artifacts(
    temp_root: Path, legacy_report
) -> list[GeneratedArtifact]:
    """Read each file the legacy generator wrote back into a GeneratedArtifact."""
    artifacts: list[GeneratedArtifact] = []
    for gf in legacy_report.files:
        try:
            content = gf.path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read rendered file %s: %s", gf.path, exc)
            content = ""
        relative = str(gf.path.relative_to(temp_root)).replace("\\", "/")
        kind = _kind_for_file(gf)
        artifacts.append(
            GeneratedArtifact(
                kind=kind,
                entity_type=gf.entity_type or None,
                entity_name=gf.entity_name or None,
                # `path` here is a RELATIVE path; the write stage will
                # rebase it under output_path (or null it out for dry-run).
                path=relative,
                size_bytes=len(content.encode("utf-8")),
                content=content,
            )
        )
    return artifacts


def _kind_for_file(gf) -> ArtifactKind:
    filename = gf.path.name
    if filename in _PROJECT_KIND_BY_FILENAME:
        return _PROJECT_KIND_BY_FILENAME[filename]
    if gf.file_type == "yaml":
        return "yaml_schema"
    return "sql_model"


def _translate_dbt_issues(legacy_report) -> list[Issue]:
    """Convert legacy GenerationError/Warning into structured render issues."""
    issues: list[Issue] = []
    for err in legacy_report.errors:
        issues.append(
            make_issue(
                severity="error",
                code=Code.RENDER_TEMPLATE_RENDER_FAILED,
                stage="render",
                message=err.message,
                entity=_entity_ref_or_none(err.entity_type, err.entity_name),
            )
        )
    for warn in legacy_report.warnings:
        # YML_001 ("SQL but no YAML") is the only legacy warning code worth
        # surfacing; everything else maps to render.entity_skipped (info).
        is_yaml_missing = warn.code == "YML_001"
        issues.append(
            make_issue(
                severity="warning" if is_yaml_missing else "info",
                code=Code.RENDER_TEMPLATE_NOT_FOUND if is_yaml_missing else Code.RENDER_ENTITY_SKIPPED,
                stage="render",
                message=warn.message,
                entity=_entity_ref_or_none(warn.entity_type, warn.entity_name),
            )
        )
    for skipped in legacy_report.skipped:
        issues.append(
            make_issue(
                severity="info",
                code=Code.RENDER_ENTITY_SKIPPED,
                stage="render",
                message=f"Skipped: {skipped.reason}",
                entity=_entity_ref_or_none(skipped.entity_type, skipped.entity_name),
            )
        )
    return issues


def _entity_ref_or_none(entity_type: str, entity_name: str) -> EntityRef | None:
    if not entity_type or not entity_name:
        return None
    return EntityRef(type=entity_type, name=entity_name)


# ---------------------------------------------------------------------------
# JSON / DBML
# ---------------------------------------------------------------------------


def _render_json(
    project_export: ProjectExport, options: GenerationOptions
) -> tuple[list[GeneratedArtifact], list[Issue]]:
    try:
        content = JSONExporter(indent=2).export(project_export)
    except Exception as exc:
        return (
            [],
            [
                make_issue(
                    severity="error",
                    code=Code.RENDER_TEMPLATE_RENDER_FAILED,
                    stage="render",
                    message=f"JSON export failed: {exc}",
                )
            ],
        )
    return (
        [
            GeneratedArtifact(
                kind="json_export",
                path=None,
                size_bytes=len(content.encode("utf-8")),
                content=content,
            )
        ],
        [],
    )


def _render_dbml(
    project_export: ProjectExport, options: GenerationOptions
) -> tuple[list[GeneratedArtifact], list[Issue]]:
    try:
        content = DBMLExporter().export(project_export)
    except Exception as exc:
        return (
            [],
            [
                make_issue(
                    severity="error",
                    code=Code.RENDER_TEMPLATE_RENDER_FAILED,
                    stage="render",
                    message=f"DBML export failed: {exc}",
                )
            ],
        )
    return (
        [
            GeneratedArtifact(
                kind="dbml_export",
                path=None,
                size_bytes=len(content.encode("utf-8")),
                content=content,
            )
        ],
        [],
    )
