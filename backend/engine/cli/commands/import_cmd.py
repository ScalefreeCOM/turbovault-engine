"""
`turbovault import` — run the metadata import pipeline standalone.

Supports merge / replace_all / update_only modes, fail-fast / best-effort
error handling, and --dry-run for validate-only execution. Output is a
Rich summary table of plan counts plus a colored issue table.

Exit codes:
  0 — success (no errors)
  1 — partial_success (best-effort; some entities skipped)
  2 — validation_failed or failed
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import questionary
import typer
from rich.table import Table

from engine.cli.utils.console import (
    console,
    print_error,
    print_info,
    print_success,
    print_warning,
)

# The engine.services.imports package eagerly imports engine.models, which
# requires Django settings to already be configured. The CLI's main callback
# runs `_setup_django()` AFTER all command modules are imported, so any
# imports from engine.services.imports or engine.models MUST be deferred
# into the command function body.

if TYPE_CHECKING:
    from engine.services.imports import ImportReport


def import_metadata_cmd(
    source: Annotated[
        Path | None,
        typer.Option(
            "--source",
            "-s",
            help=(
                "Path to source metadata file (.xlsx, .db/.sqlite, or .json), "
                "or a directory holding an IRiS three-file export"
            ),
            exists=True,
        ),
    ] = None,
    project_name: Annotated[
        str | None,
        typer.Option("--project", "-p", help="Target project name"),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Conflict strategy: merge | replace-all | update-only",
        ),
    ] = "merge",
    on_error: Annotated[
        str,
        typer.Option(
            "--on-error",
            help=(
                "Error strategy: best-effort (default; import what's valid, "
                "skip the rest) | fail-fast (abort on first error)"
            ),
        ),
    ] = "best-effort",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate and plan only; do not write to DB"),
    ] = False,
    skip_snapshots: Annotated[
        bool,
        typer.Option("--skip-snapshots", help="Skip creating default snapshot control"),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", help="Run interactive import wizard"),
    ] = False,
) -> None:
    """Import metadata into an existing project.

    With flags:
        turbovault import --project my_project --source ./metadata.xlsx

    Interactive (no flags, or explicit --interactive):
        turbovault import
        turbovault import --interactive
    """
    # If the user asked for interactive mode explicitly, OR they didn't pass
    # the essential arguments (--project + --source), drop into the wizard.
    if interactive or (project_name is None and source is None):
        params = _run_interactive_import()
        if params is None:
            console.print("Import cancelled.", style="warning")
            raise typer.Exit(0)
        project_name = params["project_name"]
        source = params["source"]
        mode = params["mode"]
        on_error = params["on_error"]
        dry_run = params["dry_run"]
        skip_snapshots = params["skip_snapshots"]
    else:
        # Partial-flag invocation: complain clearly rather than running half-blind.
        missing: list[str] = []
        if project_name is None:
            missing.append("--project")
        if source is None:
            missing.append("--source")
        if missing:
            print_error(
                f"Missing required option(s): {', '.join(missing)}. "
                "Use `turbovault import --interactive` to choose interactively."
            )
            raise typer.Exit(2)

    _run_import(
        project_name=project_name,
        source=source,
        mode=mode,
        on_error=on_error,
        dry_run=dry_run,
        skip_snapshots=skip_snapshots,
    )


def _run_import(
    *,
    project_name: str,
    source: Path,
    mode: str,
    on_error: str,
    dry_run: bool,
    skip_snapshots: bool,
) -> None:
    """Shared execution path used by both flag-driven and interactive modes."""
    # Deferred: requires Django setup.
    from engine.models import Project
    from engine.services.imports import ImportOptions, import_metadata

    project = Project.objects.filter(name=project_name).first()
    if project is None:
        print_error(f"Project '{project_name}' not found.")
        raise typer.Exit(2)

    src = _build_source(source)
    if src is None:
        print_error(
            f"Cannot determine source type from extension: {source.suffix}. "
            "Use a .xlsx, .db/.sqlite, or .json file, or a directory of "
            "IRiS files."
        )
        raise typer.Exit(2)

    options = ImportOptions(
        conflict_strategy=_normalize_mode(mode),
        error_strategy=_normalize_error(on_error),
        dry_run=dry_run,
        skip_snapshots=skip_snapshots,
    )

    if dry_run:
        print_info(f"Dry run: importing {source.name} into '{project.name}' (no DB writes).")
    else:
        print_info(
            f"Importing {source.name} into '{project.name}' "
            f"(mode={options.conflict_strategy}, on_error={options.error_strategy})."
        )

    report = import_metadata(project=project, source=src, options=options)
    _render_report(report)

    if report.status == "success":
        raise typer.Exit(0)
    if report.status == "partial_success":
        raise typer.Exit(1)
    raise typer.Exit(2)


def _run_interactive_import() -> dict | None:
    """Interactive wizard. Returns the collected parameters, or None if the
    user cancelled (Ctrl-C, escape, empty answer)."""
    from engine.models import Project

    console.print("\n[bold magenta]TurboVault Import Wizard[/bold magenta]\n")

    projects = list(Project.objects.order_by("name"))
    if not projects:
        print_error(
            "No projects exist in this workspace. "
            "Create one first with `turbovault project init`."
        )
        return None

    project_name = questionary.select(
        "Which project should receive the import?",
        choices=[p.name for p in projects],
    ).ask()
    if not project_name:
        return None

    source_str = questionary.path(
        "Path to metadata file (.xlsx, .db/.sqlite, or .json), "
        "or a directory of IRiS files:",
    ).ask()
    if not source_str:
        return None
    source = Path(source_str).expanduser()
    if not source.exists():
        print_error(f"File not found: {source}")
        return None
    if (
        not source.is_dir()
        and source.suffix.lower()
        not in (".xlsx", ".db", ".sqlite", ".sqlite3", ".json")
    ):
        print_error(
            f"Unsupported file type '{source.suffix}'. "
            "Use .xlsx, .db/.sqlite, .json, or a directory of IRiS files."
        )
        return None

    mode = questionary.select(
        "Conflict strategy: how should existing entities be handled?",
        choices=[
            questionary.Choice(
                "merge — add/update from file, leave others untouched (recommended)",
                value="merge",
            ),
            questionary.Choice(
                "replace-all — drop everything not in the file",
                value="replace-all",
            ),
            questionary.Choice(
                "update-only — only update existing entities, never create",
                value="update-only",
            ),
        ],
        default="merge",
    ).ask()
    if mode is None:
        return None

    on_error = questionary.select(
        "Error strategy: what should happen when some rows are invalid?",
        choices=[
            questionary.Choice(
                "best-effort — import what's valid, skip the rest (recommended)",
                value="best-effort",
            ),
            questionary.Choice(
                "fail-fast — abort on the first error, no DB writes",
                value="fail-fast",
            ),
        ],
        default="best-effort",
    ).ask()
    if on_error is None:
        return None

    dry_run = questionary.confirm(
        "Dry run? (validate and show a plan, but don't write to the database)",
        default=False,
    ).ask()
    if dry_run is None:
        return None

    skip_snapshots = questionary.confirm(
        "Skip creating a default snapshot control table?",
        default=False,
    ).ask()
    if skip_snapshots is None:
        return None

    return {
        "project_name": project_name,
        "source": source,
        "mode": mode,
        "on_error": on_error,
        "dry_run": dry_run,
        "skip_snapshots": skip_snapshots,
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _build_source(path: Path) -> Any | None:
    """Build the right SourceInput subtype from the path.

    A directory is taken to be an IRiS three-file export (Source / DataVault /
    Mappings workbooks); otherwise the file extension selects the format.

    The engine.services.imports import is deferred to keep this file safe
    to import before Django is configured.
    """
    from engine.services.imports import (
        ExcelSource,
        IrisSource,
        JsonSource,
        SqliteSource,
    )

    if path.is_dir():
        return IrisSource(path=path)

    ext = path.suffix.lower()
    if ext == ".xlsx":
        return ExcelSource(path=path)
    if ext in (".db", ".sqlite", ".sqlite3"):
        return SqliteSource(path=path)
    if ext == ".json":
        return JsonSource(path=path)
    return None


_MODE_MAP = {
    "merge": "merge",
    "replace-all": "replace_all",
    "replace_all": "replace_all",
    "update-only": "update_only",
    "update_only": "update_only",
}


def _normalize_mode(value: str) -> str:
    mapped = _MODE_MAP.get(value.lower())
    if mapped is None:
        raise typer.BadParameter(
            f"Unknown mode '{value}'. Use one of: merge, replace-all, update-only."
        )
    return mapped


_ERROR_MAP = {
    "fail-fast": "fail_fast",
    "fail_fast": "fail_fast",
    "best-effort": "best_effort",
    "best_effort": "best_effort",
}


def _normalize_error(value: str) -> str:
    mapped = _ERROR_MAP.get(value.lower())
    if mapped is None:
        raise typer.BadParameter(
            f"Unknown error strategy '{value}'. Use fail-fast or best-effort."
        )
    return mapped


def _render_report(report: ImportReport) -> None:
    console.print()

    # Plan summary
    summary = Table(
        title="Import Plan", show_header=True, header_style="bold cyan"
    )
    summary.add_column("Entity", style="bold")
    summary.add_column("Create", justify="right")
    summary.add_column("Update", justify="right")
    summary.add_column("Delete", justify="right")
    summary.add_column("Skip", justify="right")

    for entity_type, counts in sorted(report.plan.counts.by_entity_type.items()):
        summary.add_row(
            entity_type,
            str(counts.get("create", 0)),
            str(counts.get("update", 0)),
            str(counts.get("delete", 0)),
            str(counts.get("skip", 0)),
        )
    totals = report.plan.counts.totals
    summary.add_row(
        "[bold]Total[/bold]",
        f"[bold]{totals.get('create', 0)}[/bold]",
        f"[bold]{totals.get('update', 0)}[/bold]",
        f"[bold]{totals.get('delete', 0)}[/bold]",
        f"[bold]{totals.get('skip', 0)}[/bold]",
    )
    console.print(summary)

    # Issues
    if report.issues:
        issues_table = Table(
            title=f"Issues ({len(report.issues)})",
            show_header=True,
            header_style="bold cyan",
        )
        issues_table.add_column("Severity")
        issues_table.add_column("Code")
        issues_table.add_column("Location")
        issues_table.add_column("Message")

        for issue in report.issues:
            sev_style = {
                "error": "[red]ERROR[/red]",
                "warning": "[yellow]WARN[/yellow]",
                "info": "[cyan]INFO[/cyan]",
            }[issue.severity]
            loc_parts = []
            if issue.location:
                if issue.location.sheet:
                    loc_parts.append(issue.location.sheet)
                if issue.location.row:
                    loc_parts.append(f"row {issue.location.row}")
                if issue.location.column:
                    loc_parts.append(f"col '{issue.location.column}'")
            if issue.entity:
                loc_parts.append(f"<{issue.entity.type} {issue.entity.name}>")
            location_str = " ".join(loc_parts) or "—"

            issues_table.add_row(
                sev_style, issue.code, location_str, issue.message
            )
        console.print(issues_table)
    else:
        console.print("[green]No issues.[/green]")

    # Status line
    console.print()
    totals = report.plan.counts.totals
    if report.status == "success":
        verb = "Dry run completed" if report.is_dry_run else "Import completed"
        print_success(f"{verb} successfully.")
    elif report.status == "partial_success":
        wrote = totals.get("create", 0) + totals.get("update", 0)
        skipped = totals.get("skip", 0)
        print_warning(
            f"Import partially succeeded: wrote {wrote} entit{'y' if wrote == 1 else 'ies'}, "
            f"skipped {skipped + report.error_count} due to "
            f"{report.error_count} error(s) and {report.warning_count} warning(s). "
            "See the Issues table above for details on each skipped item."
        )
    elif report.status == "validation_failed":
        print_error(
            f"Import aborted at validation: {report.error_count} error(s)."
        )
    else:
        print_error(f"Import failed with {report.error_count} error(s).")

    console.print(f"[dim]Import run ID: {report.import_run_id}[/dim]")
