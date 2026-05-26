"""
Stage 1 — Build.

Reads the Django ORM into a `ProjectExport` (target-agnostic Pydantic
model). Wraps the existing `ModelBuilder`; any failure here is fatal —
nothing downstream can do anything without an export — and surfaces as
`build.project_load_failed` or `build.export_inconsistent`.
"""

from __future__ import annotations

from engine.models import Project
from engine.services.export.builder import ModelBuilder
from engine.services.export.models import ProjectExport
from engine.services.generation.errors import Code, PipelineAbort, make_issue
from engine.services.generation.types import GenerationOptions, IssueLocation
from engine.services.runtime_config import EngineRuntimeConfig


def build_export(
    *,
    project: Project,
    runtime_config: EngineRuntimeConfig,
    options: GenerationOptions,
) -> ProjectExport:
    """Assemble the `ProjectExport` for `project`.

    Raises `PipelineAbort` on any failure so the runner can finalize the
    report cleanly. The pipeline cannot recover from a missing export, so
    even `best_effort` mode aborts at this stage.
    """
    builder = ModelBuilder(project, runtime_config=runtime_config)
    try:
        return builder.build(
            export_sources=runtime_config.export_sources,
            generate_tests=runtime_config.generate_tests,
            generate_dbml=runtime_config.generate_dbml,
        )
    except Exception as exc:
        raise PipelineAbort(
            make_issue(
                severity="error",
                code=Code.BUILD_EXPORT_INCONSISTENT,
                stage="build",
                message=f"Could not assemble project export: {exc}",
                location=IssueLocation(),
                suggestion=(
                    "Open the project in the metadata editor and check that "
                    "every hub/link/satellite is fully wired (parent set, "
                    "source mappings present, hashkey naming resolvable)."
                ),
            )
        ) from exc
