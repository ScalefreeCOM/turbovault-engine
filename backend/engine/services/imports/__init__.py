"""
Public entry point for the metadata import pipeline.

Single function `import_metadata` runs the pipeline and returns a structured
`ImportReport`. All other types in this module are stable contracts the CLI
and Studio depend on; everything else is internal.

Usage (CLI / Studio / tests):

    from engine.services.imports import (
        import_metadata,
        ExcelSource,
        ImportOptions,
    )

    report = import_metadata(
        project=project,
        source=ExcelSource(path=Path("metadata.xlsx")),
        options=ImportOptions(conflict_strategy="merge", dry_run=False),
    )
    if report.has_errors:
        ...
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from pathlib import Path

from engine.models import Project
from engine.services.imports.domain import DomainModel
from engine.services.imports.errors import Code, PipelineAbort, make_issue
from engine.services.imports.executor import execute_plan
from engine.services.imports.ir import IRDocument
from engine.services.imports.parsers.excel import parse_excel
from engine.services.imports.parsers.iris import parse_iris
from engine.services.imports.parsers.json_parser import parse_json
from engine.services.imports.parsers.source_metadata import (
    parse_source_metadata,
)
from engine.services.imports.parsers.sqlite import parse_sqlite
from engine.services.imports.planner import build_plan
from engine.services.imports.progress import emit
from engine.services.imports.reporting import (
    build_report,
    now_utc,
    persist_import_run,
)
from engine.services.imports.types import (
    ConflictStrategy,
    EntityRef,
    ErrorStrategy,
    ExcelSource,
    ImportOptions,
    ImportPlan,
    ImportReport,
    IrisSource,
    Issue,
    IssueLocation,
    JsonSource,
    ProgressEvent,
    SourceInput,
    SourceMetadataSource,
    SqliteSource,
)
from engine.services.imports.validation.resolver import resolve
from engine.services.imports.validation.schema_validator import validate_schema

__all__ = [
    "import_metadata",
    "ExcelSource",
    "SqliteSource",
    "JsonSource",
    "SourceMetadataSource",
    "IrisSource",
    "SourceInput",
    "ImportOptions",
    "ImportReport",
    "ImportPlan",
    "Issue",
    "IssueLocation",
    "EntityRef",
    "ProgressEvent",
    "ConflictStrategy",
    "ErrorStrategy",
]


ProgressCallback = Callable[[ProgressEvent], None]


def import_metadata(
    *,
    project: Project,
    source: SourceInput,
    options: ImportOptions | None = None,
    progress: ProgressCallback | None = None,
) -> ImportReport:
    """Run the import pipeline against `project`.

    Always returns an ImportReport. Persists an ImportRun row regardless of
    outcome (including dry-run and validation-failed cases) so the CLI and
    Studio can show history.

    The only path that does NOT return is a programming bug — those become
    `internal.bug` issues in the report.
    """
    options = options or ImportOptions()
    started_at = now_utc()
    timings: dict[str, int] = {}
    issues: list[Issue] = []
    plan_for_report = ImportPlan()
    executor_committed = False

    # Run id is generated up front so progress events can reference it.
    run_id = uuid.uuid4()

    emit(
        progress,
        stage="parse",
        status="started",
        message=f"Parsing {source.type} source",
    )

    try:
        # ----------------------- 1. Parse -----------------------
        t0 = time.perf_counter()
        domain: DomainModel
        had_ir = False
        ir_doc = None

        try:
            if isinstance(source, ExcelSource):
                ir_doc = parse_excel(Path(source.path))
                had_ir = True
            elif isinstance(source, SqliteSource):
                ir_doc = parse_sqlite(Path(source.path))
                had_ir = True
            elif isinstance(source, JsonSource):
                domain = parse_json(Path(source.path))
            elif isinstance(source, SourceMetadataSource):
                domain = parse_source_metadata(Path(source.path))
            elif isinstance(source, IrisSource):
                domain = parse_iris(Path(source.path))
            else:
                raise PipelineAbort(
                    make_issue(
                        severity="error",
                        code=Code.SOURCE_UNSUPPORTED_FORMAT,
                        stage="parse",
                        message=f"Unsupported source type: {getattr(source, 'type', '?')}",
                    )
                )
        except PipelineAbort as abort:
            issues.append(abort.issue)
            timings["parse"] = _ms(t0)
            return _finalize(
                project=project,
                source=source,
                options=options,
                plan=plan_for_report,
                issues=issues,
                started_at=started_at,
                timings=timings,
                run_id=run_id,
                executor_committed=False,
                progress=progress,
            )

        timings["parse"] = _ms(t0)
        emit(progress, stage="parse", status="done", message="Parse complete")

        # ----------------------- 2/3. Validate + Resolve -----------------
        emit(progress, stage="validate", status="started", message="Validating schema")
        t0 = time.perf_counter()

        if had_ir:
            schema_issues = validate_schema(ir_doc, options)
            issues.extend(schema_issues)

            schema_errors = [i for i in schema_issues if i.severity == "error"]

            if schema_errors and options.error_strategy == "fail_fast":
                # Strict mode: any header-level problem aborts the run.
                timings["validate"] = _ms(t0)
                return _finalize(
                    project=project,
                    source=source,
                    options=options,
                    plan=plan_for_report,
                    issues=issues,
                    started_at=started_at,
                    timings=timings,
                    run_id=run_id,
                    executor_committed=False,
                    progress=progress,
                )

            # Best-effort: drop sheets that have header-level schema errors so
            # the resolver doesn't synthesize half-broken entities from them.
            # Other sheets continue normally.
            ir_doc = _filter_bad_sheets(ir_doc, schema_errors)

            domain, resolve_issues = resolve(ir_doc)
            issues.extend(resolve_issues)

            resolve_errors = [i for i in resolve_issues if i.severity == "error"]
            if resolve_errors and options.error_strategy == "fail_fast":
                timings["validate"] = _ms(t0)
                return _finalize(
                    project=project,
                    source=source,
                    options=options,
                    plan=plan_for_report,
                    issues=issues,
                    started_at=started_at,
                    timings=timings,
                    run_id=run_id,
                    executor_committed=False,
                    progress=progress,
                )
        # else: JSON path — domain is already populated; minimal validation.

        timings["validate"] = _ms(t0)
        emit(progress, stage="validate", status="done", message="Validation complete")

        # ----------------------- 4. Plan -----------------------
        emit(progress, stage="plan", status="started", message="Computing diff")
        t0 = time.perf_counter()
        exec_plan, public_plan = build_plan(
            project=project,
            domain=domain,
            strategy=options.conflict_strategy,
        )
        plan_for_report = public_plan
        timings["plan"] = _ms(t0)
        emit(progress, stage="plan", status="done", message="Plan ready")

        # ----------------------- 5. Execute -----------------------
        if options.dry_run:
            emit(
                progress,
                stage="execute",
                status="done",
                message="Dry run: skipping execute stage",
            )
            timings["execute"] = 0
        else:
            emit(
                progress,
                stage="execute",
                status="started",
                message="Applying plan to database",
            )
            t0 = time.perf_counter()
            try:
                exec_issues = execute_plan(
                    project=project,
                    domain=domain,
                    plan=exec_plan,
                    error_strategy=options.error_strategy,
                    skip_snapshots=options.skip_snapshots,
                )
                issues.extend(exec_issues)
                # We reached the end of execute_plan without PipelineAbort:
                # the transaction committed (with whatever per-entity errors
                # were recorded in best_effort).
                executor_committed = True
            except PipelineAbort as abort:
                issues.append(abort.issue)
            timings["execute"] = _ms(t0)
            emit(progress, stage="execute", status="done", message="Execute complete")

    except PipelineAbort as abort:
        # Catch-all for stages that throw PipelineAbort after the parse stage.
        if abort.issue not in issues:
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
        source=source,
        options=options,
        plan=plan_for_report,
        issues=issues,
        started_at=started_at,
        timings=timings,
        run_id=run_id,
        executor_committed=executor_committed,
        progress=progress,
    )


def _finalize(
    *,
    project: Project,
    source: SourceInput,
    options: ImportOptions,
    plan: ImportPlan,
    issues: list[Issue],
    started_at,
    timings: dict[str, int],
    run_id,
    executor_committed: bool,
    progress: ProgressCallback | None,
) -> ImportReport:
    finished_at = now_utc()
    report = build_report(
        import_run_id=run_id,
        project=project,
        source=source,
        options=options,
        plan=plan,
        issues=issues,
        started_at=started_at,
        finished_at=finished_at,
        timings_ms=timings,
        executor_committed=executor_committed,
    )

    try:
        persist_import_run(project=project, report=report)
    except Exception:
        # Persisting the audit row must never break the user-facing report.
        # We don't add an issue here because it would lie about the import.
        pass

    emit(
        progress,
        stage="report",
        status="done",
        message=f"Import {report.status}",
    )
    return report


def _ms(start_perf: float) -> int:
    return int((time.perf_counter() - start_perf) * 1000)


def _filter_bad_sheets(
    doc: IRDocument, schema_errors: list[Issue]
) -> IRDocument:
    """Return a copy of `doc` with sheets affected by header-level schema
    errors removed.

    Row-level errors (e.g. a missing required cell) are NOT a reason to drop
    the whole sheet — only header-level errors (`schema.missing_column`,
    `schema.missing_sheet`) are. With those, the sheet's structure is
    fundamentally wrong and we can't reliably resolve rows from it.
    """
    sheet_killers = {Code.SCHEMA_MISSING_COLUMN}
    bad_sheets = {
        issue.location.sheet
        for issue in schema_errors
        if issue.code in sheet_killers
        and issue.location is not None
        and issue.location.sheet
    }
    if not bad_sheets:
        return doc
    filtered = IRDocument(source_name=doc.source_name)
    for name, sheet in doc.sheets.items():
        if name in bad_sheets:
            continue
        filtered.sheets[name] = sheet
    return filtered
