"""Stage 6: assemble the final ImportReport and persist the ImportRun row."""

from __future__ import annotations

from datetime import datetime, timezone

from engine.models import Project
from engine.models.import_run import ImportRun
from engine.services.imports.types import (
    ImportOptions,
    ImportPlan,
    ImportReport,
    ImportStatus,
    Issue,
    SourceInput,
)


def determine_status(
    *,
    is_dry_run: bool,
    issues: list[Issue],
    plan: ImportPlan,
    executor_committed: bool,
) -> ImportStatus:
    """Decide the terminal status from the report's contents.

    - `success`           : no error-severity issues.
    - `validation_failed` : errors recorded AND nothing was actually written
                            (dry-run, or executor never ran, or the plan
                            ended up empty after filtering bad sheets).
    - `partial_success`   : errors recorded BUT the executor committed
                            at least one create/update. This is the typical
                            best-effort outcome: some entities written,
                            others skipped with documented reasons.
    """
    error_issues = [i for i in issues if i.severity == "error"]
    if not error_issues:
        return "success"

    if is_dry_run:
        return "validation_failed"

    writes_planned = plan.counts.totals.get("create", 0) + plan.counts.totals.get(
        "update", 0
    )
    if executor_committed and writes_planned > 0:
        return "partial_success"
    return "validation_failed"


def persist_import_run(
    *,
    project: Project,
    report: ImportReport,
) -> None:
    """Save the ImportReport to an ImportRun row.

    Run inside or outside the executor's transaction depending on caller.
    For dry runs we still persist a row so users can find the result in
    `turbovault project history`.
    """
    ImportRun.objects.create(
        import_run_id=report.import_run_id,
        project=project,
        status=report.status,
        is_dry_run=report.is_dry_run,
        source_type=report.source_type,
        source_name=report.source_name,
        conflict_strategy=report.options.conflict_strategy,
        error_strategy=report.options.error_strategy,
        report=report.model_dump(mode="json"),
        error_count=report.error_count,
        warning_count=report.warning_count,
        started_at=report.started_at,
        finished_at=report.finished_at,
    )


def build_report(
    *,
    import_run_id,
    project: Project,
    source: SourceInput,
    options: ImportOptions,
    plan: ImportPlan,
    issues: list[Issue],
    started_at: datetime,
    finished_at: datetime,
    timings_ms: dict[str, int],
    executor_committed: bool,
) -> ImportReport:
    status = determine_status(
        is_dry_run=options.dry_run,
        issues=issues,
        plan=plan,
        executor_committed=executor_committed,
    )
    source_name = source.display_name or source.path.name
    return ImportReport(
        import_run_id=import_run_id,
        project_id=project.project_id,
        status=status,
        is_dry_run=options.dry_run,
        started_at=started_at,
        finished_at=finished_at,
        timings_ms=timings_ms,
        options=options,
        source_type=source.type,
        source_name=source_name,
        plan=plan,
        issues=issues,
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
