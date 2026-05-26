"""
Public entry point for the generation pipeline.

Single function `generate()` runs the build → validate → plan → render →
write → report pipeline and returns a structured `GenerationReport`.
All other types in this module are stable contracts the CLI and Studio
depend on; everything else is internal.

Usage (CLI / Studio / tests):

    from engine.services.generation import (
        generate,
        GenerationOptions,
        EntitySelection,
        EntityRef,
    )

    report = generate(
        project=project,
        output_type="dbt",
        output_path=Path("./out"),
        options=GenerationOptions(
            error_strategy="best_effort",
            generate_satellite_v1_views=True,
        ),
    )
    if report.has_errors:
        ...
"""

from __future__ import annotations

from pathlib import Path

from engine.models import Project
from engine.services.generation.folder_config import FolderConfig, GenerationConfig
from engine.services.generation.generator import DbtProjectGenerator
from engine.services.generation.pipeline import run_pipeline
from engine.services.generation.progress import ProgressCallback
from engine.services.generation.template_resolver import TemplateResolver
from engine.services.generation.types import (
    ArtifactKind,
    EntityRef,
    EntitySelection,
    ErrorStrategy,
    GeneratedArtifact,
    GenerationOptions,
    GenerationPlan,
    GenerationReport,
    GenerationStatus,
    Issue,
    IssueLocation,
    OutputType,
    PipelineStage,
    ProgressEvent,
)
from engine.services.runtime_config import EngineRuntimeConfig

__all__ = [
    "generate",
    "GenerationOptions",
    "GenerationReport",
    "GenerationPlan",
    "GenerationStatus",
    "GeneratedArtifact",
    "ArtifactKind",
    "EntityRef",
    "EntitySelection",
    "ErrorStrategy",
    "Issue",
    "IssueLocation",
    "OutputType",
    "PipelineStage",
    "ProgressEvent",
    # Internal building blocks — kept importable so existing tests that
    # construct the legacy generator directly keep working. Production
    # callers should use `generate()` instead.
    "FolderConfig",
    "GenerationConfig",
    "DbtProjectGenerator",
    "TemplateResolver",
]


def generate(
    *,
    project: Project,
    output_type: OutputType,
    output_path: Path | None = None,
    runtime_config: EngineRuntimeConfig | None = None,
    options: GenerationOptions | None = None,
    progress: ProgressCallback | None = None,
) -> GenerationReport:
    """Run the generation pipeline against `project`.

    Always returns a `GenerationReport`. Persists a `GenerationRun` row
    regardless of outcome (including dry-run and validation-failed cases)
    so the CLI and Studio can show history.

    `output_path` is required for a real run (dry-run ignores it).
    `runtime_config` is resolved from the project's stored config when
    not supplied. `options` defaults to `GenerationOptions()`
    (`error_strategy="best_effort"`, no dry-run, no selection).
    """
    return run_pipeline(
        project=project,
        output_type=output_type,
        output_path=output_path,
        runtime_config=runtime_config,
        options=options,
        progress=progress,
    )
