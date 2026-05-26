"""
Pipeline orchestrator for the generation pipeline.

Glues the six stages together, owns error-strategy / dry-run semantics,
emits progress events, captures per-stage timings, and persists a
`GenerationRun` audit row. Public callers should use the
`generate()` function exported from `engine.services.generation`
rather than calling this directly.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from engine.models import GenerationRun, Project
from engine.services.generation.errors import Code, PipelineAbort, make_issue
from engine.services.generation.progress import ProgressCallback, emit
from engine.services.generation.stages.build import build_export
from engine.services.generation.stages.plan import build_plan
from engine.services.generation.stages.render import render
from engine.services.generation.stages.validate import validate
from engine.services.generation.stages.write import write_artifacts
from engine.services.generation.types import (
    GeneratedArtifact,
    GenerationOptions,
    GenerationPlan,
    GenerationReport,
    GenerationStatus,
    Issue,
    OutputType,
)
from engine.services.runtime_config import EngineRuntimeConfig, resolve_runtime_config


def run_pipeline(
    *,
    project: Project,
    output_type: OutputType,
    output_path: Path | None,
    runtime_config: EngineRuntimeConfig | None,
    options: GenerationOptions | None,
    progress: ProgressCallback | None,
) -> GenerationReport:
    """Execute the full pipeline and always return a structured report.

    The function never raises (modulo programming bugs that route into
    an `internal.bug` issue). Callers inspect `report.status` /
    `report.issues` to decide what to do next.
    """
    options = options or GenerationOptions()
    runtime_config = resolve_runtime_config(project, runtime_config)
    started_at = _now()
    timings: dict[str, int] = {}
    issues: list[Issue] = []
    artifacts: list[GeneratedArtifact] = []
    plan_for_report = GenerationPlan(output_type=output_type, files_planned=0)
    run_id = uuid.uuid4()

    try:
        # -------------------- 1. Build --------------------
        emit(progress, stage="build", status="started",
             message="Building project export")
        t0 = time.perf_counter()
        project_export = build_export(
            project=project, runtime_config=runtime_config, options=options
        )
        timings["build"] = _ms(t0)
        emit(progress, stage="build", status="done", message="Build complete")

        # -------------------- 2. Validate --------------------
        emit(progress, stage="validate", status="started",
             message="Validating model")
        t0 = time.perf_counter()
        validate_issues = validate(project_export=project_export, options=options)
        issues.extend(validate_issues)
        timings["validate"] = _ms(t0)
        emit(progress, stage="validate", status="done", message="Validation complete")

        if (
            options.error_strategy == "fail_fast"
            and any(i.severity == "error" for i in validate_issues)
        ):
            return _finalize(
                project=project,
                output_type=output_type,
                output_path=output_path,
                options=options,
                plan=plan_for_report,
                artifacts=[],
                issues=issues,
                started_at=started_at,
                timings=timings,
                run_id=run_id,
                progress=progress,
            )

        # -------------------- 3. Plan --------------------
        emit(progress, stage="plan", status="started", message="Building plan")
        t0 = time.perf_counter()
        plan, filtered_export, plan_issues = build_plan(
            project_export=project_export,
            output_type=output_type,
            options=options,
        )
        plan_for_report = plan
        issues.extend(plan_issues)
        timings["plan"] = _ms(t0)
        emit(progress, stage="plan", status="done", message="Plan ready")

        if (
            options.error_strategy == "fail_fast"
            and any(i.severity == "error" for i in plan_issues)
        ):
            return _finalize(
                project=project,
                output_type=output_type,
                output_path=output_path,
                options=options,
                plan=plan_for_report,
                artifacts=[],
                issues=issues,
                started_at=started_at,
                timings=timings,
                run_id=run_id,
                progress=progress,
            )

        # -------------------- 4. Render --------------------
        emit(progress, stage="render", status="started",
             message=f"Rendering {output_type}")
        t0 = time.perf_counter()
        rendered, render_issues = render(
            project_export=filtered_export,
            output_type=output_type,
            runtime_config=runtime_config,
            options=options,
        )
        artifacts = rendered
        issues.extend(render_issues)
        timings["render"] = _ms(t0)
        emit(progress, stage="render", status="done", message="Render complete")

        if (
            options.error_strategy == "fail_fast"
            and any(i.severity == "error" for i in render_issues)
        ):
            return _finalize(
                project=project,
                output_type=output_type,
                output_path=output_path,
                options=options,
                plan=plan_for_report,
                artifacts=[],
                issues=issues,
                started_at=started_at,
                timings=timings,
                run_id=run_id,
                progress=progress,
            )

        # -------------------- 5. Write --------------------
        emit(progress, stage="write", status="started",
             message="Dry run: skipping write" if options.dry_run else "Writing files")
        t0 = time.perf_counter()
        artifacts, write_issues = write_artifacts(
            artifacts=artifacts,
            output_type=output_type,
            output_path=output_path,
            options=options,
        )
        issues.extend(write_issues)
        timings["write"] = _ms(t0)
        emit(progress, stage="write", status="done", message="Write complete")

    except PipelineAbort as abort:
        issues.append(abort.issue)
    except Exception as exc:  # pragma: no cover - last-resort safety net
        issues.append(
            make_issue(
                severity="error",
                code=Code.INTERNAL_BUG,
                stage="report",
                message=f"Unhandled internal error: {exc.__class__.__name__}: {exc}",
            )
        )

    return _finalize(
        project=project,
        output_type=output_type,
        output_path=output_path,
        options=options,
        plan=plan_for_report,
        artifacts=artifacts,
        issues=issues,
        started_at=started_at,
        timings=timings,
        run_id=run_id,
        progress=progress,
    )


# ---------------------------------------------------------------------------
# Finalization
# ---------------------------------------------------------------------------


def _finalize(
    *,
    project: Project,
    output_type: OutputType,
    output_path: Path | None,
    options: GenerationOptions,
    plan: GenerationPlan,
    artifacts: list[GeneratedArtifact],
    issues: list[Issue],
    started_at: datetime,
    timings: dict[str, int],
    run_id,
    progress: ProgressCallback | None,
) -> GenerationReport:
    finished_at = _now()
    status = _determine_status(
        is_dry_run=options.dry_run, issues=issues, artifacts=artifacts
    )
    report = GenerationReport(
        generation_run_id=run_id,
        project_id=project.project_id,
        output_type=output_type,
        status=status,
        is_dry_run=options.dry_run,
        started_at=started_at,
        finished_at=finished_at,
        timings_ms=timings,
        options=options,
        plan=plan,
        artifacts=artifacts,
        issues=issues,
    )

    try:
        _persist_run(project=project, report=report, output_path=output_path)
    except Exception:
        # Audit row persistence must never alter the user-facing report.
        pass

    emit(progress, stage="report", status="done", message=f"Generation {status}")
    return report


def _determine_status(
    *,
    is_dry_run: bool,
    issues: list[Issue],
    artifacts: list[GeneratedArtifact],
) -> GenerationStatus:
    has_errors = any(i.severity == "error" for i in issues)
    if not has_errors:
        return "success"
    if is_dry_run:
        return "validation_failed"
    files_written = any(a.path for a in artifacts)
    if files_written:
        return "partial_success"
    return "validation_failed"


def _persist_run(
    *, project: Project, report: GenerationReport, output_path: Path | None
) -> None:
    GenerationRun.objects.create(
        generation_run_id=report.generation_run_id,
        project=project,
        status=report.status,
        is_dry_run=report.is_dry_run,
        output_type=report.output_type,
        output_path=str(output_path) if output_path else "",
        error_strategy=report.options.error_strategy,
        report=report.model_dump(mode="json"),
        error_count=report.error_count,
        warning_count=report.warning_count,
        files_generated=report.files_generated,
        started_at=report.started_at,
        finished_at=report.finished_at,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ms(start_perf: float) -> int:
    return int((time.perf_counter() - start_perf) * 1000)
