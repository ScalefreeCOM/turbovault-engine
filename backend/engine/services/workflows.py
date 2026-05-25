"""
Reusable Engine workflows for CLI and embedded callers.

After the import / generation pipeline rewrites, this module is a very
thin layer. Imports flow through `engine.services.imports.import_metadata`
(re-exported here as `import_metadata` for legacy compatibility);
generations flow through `engine.services.generation.generate` and have
no shim — call that function directly.
"""

from __future__ import annotations

from pathlib import Path

from engine.models import Project
from engine.services.imports import (
    ExcelSource,
    ImportOptions,
    ImportReport,
    JsonSource,
    SourceInput,
    SqliteSource,
)
from engine.services.imports import import_metadata as _run_import
from engine.services.runtime_config import EngineRuntimeConfig


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
    conflict_strategy: str = "merge",
    error_strategy: str = "best_effort",
    dry_run: bool = False,
) -> ImportReport:
    """Import metadata into an existing Engine project.

    Thin wrapper around `engine.services.imports.import_metadata`. Returns
    the structured report so callers can render plan/issues. Use the
    package-level function directly for new code — this shim only stays
    for callers (CLI, Studio) that already type-import from `workflows`.
    """
    source_path = Path(path)
    normalized_type = source_type.lower()

    source: SourceInput
    if normalized_type == "excel":
        source = ExcelSource(path=source_path)
    elif normalized_type == "sqlite":
        source = SqliteSource(path=source_path)
    elif normalized_type == "json":
        source = JsonSource(path=source_path)
    else:
        raise ValueError(f"Unsupported metadata source type: {source_type}")

    options = ImportOptions(
        conflict_strategy=conflict_strategy,  # type: ignore[arg-type]
        error_strategy=error_strategy,  # type: ignore[arg-type]
        dry_run=dry_run,
        skip_snapshots=skip_snapshots,
    )

    return _run_import(project=project, source=source, options=options)
