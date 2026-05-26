"""
`turbovault generate` — run the new generation pipeline.

Supports dbt / json / dbml output types, merge of strict/lenient
validation with best-effort/fail-fast error handling, `--dry-run` for
preview, and selective generation via `--include-type` / `--exclude-type`
/ `--include-group` / `--exclude-group` / `--only TYPE:NAME`.

Exit codes:
  0 — success (no errors)
  1 — partial_success (best-effort; some entities skipped)
  2 — validation_failed or failed
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

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

# Engine imports are deferred to the command body because the CLI module
# is imported before Django setup. Type-only imports stay at module level.
if TYPE_CHECKING:
    from engine.services.generation import GenerationReport


SUPPORTED_TYPES = ("dbt", "json", "dbml", "iris")


def generate(
    project_name: Annotated[
        str | None,
        typer.Option(
            "--project", "-p", help="Project name (interactive picker if omitted)"
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o",
            help="Output directory for dbt, or output file for json/dbml",
        ),
    ] = None,
    type: Annotated[
        str | None,
        typer.Option(
            "--type", "-t",
            help="Export type: dbt | json | dbml (interactive if omitted)",
        ),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode", "-m",
            help="Error strategy: strict (fail_fast) or lenient (best_effort)",
        ),
    ] = "strict",
    skip_validation: Annotated[
        bool,
        typer.Option("--skip-validation", help="Skip pre-generation validation"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Validate, plan, and render without writing files",
        ),
    ] = False,
    create_zip: Annotated[
        bool,
        typer.Option("--zip", "-z", help="Create a ZIP archive after dbt generation"),
    ] = False,
    no_v1_satellites: Annotated[
        bool,
        typer.Option("--no-v1-satellites", help="Skip generating satellite _v1 views"),
    ] = False,
    json_output: Annotated[
        Path | None,
        typer.Option("--json-output", help="Alias for --output when type=json"),
    ] = None,
    dbml_output: Annotated[
        Path | None,
        typer.Option("--dbml-output", help="Alias for --output when type=dbml"),
    ] = None,
    iris_output: Annotated[
        Path | None,
        typer.Option(
            "--iris-output",
            help="Output directory for IRiS Excel files (only for type=iris)",
        ),
    ] = None,
    include_type: Annotated[
        list[str] | None,
        typer.Option(
            "--include-type",
            help="Only emit these entity types (e.g. hub, link, satellite, pit)",
        ),
    ] = None,
    exclude_type: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-type",
            help="Skip these entity types (e.g. satellite)",
        ),
    ] = None,
    include_group: Annotated[
        list[str] | None,
        typer.Option("--include-group", help="Only emit entities in these groups"),
    ] = None,
    exclude_group: Annotated[
        list[str] | None,
        typer.Option("--exclude-group", help="Skip entities in these groups"),
    ] = None,
    only: Annotated[
        list[str] | None,
        typer.Option(
            "--only",
            help="Allowlist of TYPE:NAME pairs (e.g. hub:hub_customer); overrides include/exclude",
        ),
    ] = None,
) -> None:
    """Generate a dbt project, JSON export, or DBML diagram."""
    from engine.cli.utils.debug import debug_print
    from engine.services.app_config_loader import (
        WorkspaceNotFoundError,
        require_workspace,
    )

    try:
        require_workspace()
    except WorkspaceNotFoundError as exc:
        print_error(str(exc))
        raise typer.Exit(2) from None

    # Deferred to keep this module importable before django.setup().
    from engine.models import Project
    from engine.services.generation import (
        EntityRef,
        EntitySelection,
        GenerationOptions,
        generate as run_generate,
    )

    debug_print("CLI imports complete")

    project = _resolve_project(project_name)
    output_type = _resolve_output_type(type)

    # IRiS doesn't go through the dbt/json/dbml pipeline (it emits a
    # directory of Excel files via its own exporter). Handle it here.
    if output_type == "iris":
        _export_iris(project=project, iris_output=iris_output, dry_run=dry_run)
        return

    output_path = _resolve_output_path(
        output_type=output_type,
        output=output,
        json_output=json_output,
        dbml_output=dbml_output,
        project=project,
        dry_run=dry_run,
    )

    options = GenerationOptions(
        error_strategy="fail_fast" if mode == "strict" else "best_effort",
        dry_run=dry_run,
        skip_validation=skip_validation,
        create_zip=create_zip,
        generate_satellite_v1_views=not no_v1_satellites,
        entity_selection=_build_selection(
            include_type=include_type,
            exclude_type=exclude_type,
            include_group=include_group,
            exclude_group=exclude_group,
            only=only,
            entity_ref_cls=EntityRef,
            selection_cls=EntitySelection,
        ),
    )

    _announce(project=project, output_type=output_type, options=options, output_path=output_path)

    report = run_generate(
        project=project,
        output_type=output_type,
        output_path=output_path,
        options=options,
    )

    _render_report(report)

    if report.status == "success":
        raise typer.Exit(0)
    if report.status == "partial_success":
        raise typer.Exit(1)
    raise typer.Exit(2)


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def _resolve_project(project_name: str | None):
    from engine.models import Project

    if project_name:
        project = Project.objects.filter(name=project_name).first()
        if project is None:
            print_error(f"Project '{project_name}' not found.")
            raise typer.Exit(2)
        return project

    projects = list(Project.objects.order_by("name"))
    if not projects:
        print_error("No projects exist. Create one with `turbovault project init`.")
        raise typer.Exit(2)
    if len(projects) == 1:
        return projects[0]

    chosen = questionary.select(
        "Select a project:", choices=[p.name for p in projects]
    ).ask()
    if not chosen:
        raise typer.Exit(0)
    return next(p for p in projects if p.name == chosen)


def _resolve_output_type(requested: str | None) -> str:
    if requested:
        if requested not in SUPPORTED_TYPES:
            print_error(
                f"Unknown --type '{requested}'. Use one of: {', '.join(SUPPORTED_TYPES)}."
            )
            raise typer.Exit(2)
        return requested
    chosen = questionary.select(
        "Select export type:",
        choices=[
            questionary.Choice("dbt — Generate dbt project", value="dbt"),
            questionary.Choice("json — Export model as JSON", value="json"),
            questionary.Choice("dbml — Export model as DBML diagram", value="dbml"),
            questionary.Choice("iris — Export model to IRiS Excel templates", value="iris"),
        ],
        default="dbt",
    ).ask()
    if not chosen:
        raise typer.Exit(0)
    return chosen


def _resolve_output_path(
    *,
    output_type: str,
    output: Path | None,
    json_output: Path | None,
    dbml_output: Path | None,
    project,
    dry_run: bool,
) -> Path | None:
    """Pick the target path for the artifact.

    Priority order:
      1. Type-specific override flags (`--json-output`, `--dbml-output`).
      2. Generic `--output` / `-o`.
      3. Workspace convention: `<project_dir>/exports/{dbt_project | <name>.json | <name>.dbml}`.
      4. Fallback `./output/<slug>` when the project has no `project_directory`
         set (ad-hoc / test projects).
    """
    if dry_run:
        return None

    if output_type == "json" and json_output:
        return json_output
    if output_type == "dbml" and dbml_output:
        return dbml_output
    if output:
        return output

    slug = project.name.lower().replace(" ", "_")
    exports_dir = _project_exports_dir(project)
    if exports_dir is None:
        # No project_directory configured — fall back to cwd-relative output.
        if output_type == "dbt":
            return Path(f"./output/{slug}")
        if output_type == "json":
            return Path(f"./output/{slug}.json")
        return Path(f"./output/{slug}.dbml")

    if output_type == "dbt":
        return exports_dir / "dbt_project"
    if output_type == "json":
        return exports_dir / f"{slug}.json"
    return exports_dir / f"{slug}.dbml"


def _project_exports_dir(project) -> Path | None:
    """Return `<workspace>/projects/<project>/exports`, or None if unknown."""
    project_directory = getattr(project, "project_directory", None)
    if not project_directory:
        return None
    from engine.services.app_config_loader import resolve_project_path

    try:
        return resolve_project_path(project_directory) / "exports"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# IRiS export (handled outside the dbt/json/dbml pipeline)
# ---------------------------------------------------------------------------


def _resolve_iris_output_dir(project, iris_output: Path | None) -> Path:
    if iris_output:
        return iris_output
    exports_dir = _project_exports_dir(project)
    if exports_dir is not None:
        return exports_dir / "iris"
    slug = project.name.lower().replace(" ", "_")
    return Path(f"./output/{slug}_iris")


def _export_iris(*, project, iris_output: Path | None, dry_run: bool) -> None:
    """Export the model to the three IRiS Excel templates.

    Builds the `ProjectExport` directly and calls `IrisExporter`, since
    IRiS writes a directory of workbooks rather than a single pipeline
    artifact. Exits with 0 on success, 2 on failure.
    """
    from engine.services.export.builder import ModelBuilder
    from engine.services.export.exporters.iris_exporter import IrisExporter
    from engine.services.runtime_config import resolve_runtime_config

    runtime_config = resolve_runtime_config(project)
    project_export = ModelBuilder(project, runtime_config=runtime_config).build(
        export_sources=runtime_config.export_sources,
        generate_tests=runtime_config.generate_tests,
        generate_dbml=runtime_config.generate_dbml,
    )

    output_dir = _resolve_iris_output_dir(project, iris_output)

    if dry_run:
        print_warning("Dry run: no IRiS files written.")
        raise typer.Exit(0)

    result = IrisExporter().export(
        project_export, output_dir, project_name=project.name
    )

    for warning in result.warnings:
        print_warning(warning)
    for skipped in result.skipped:
        print_info(f"Skipped: {skipped}")

    if result.success:
        for file_path in result.files:
            print_success(f"IRiS file: {file_path}")
        raise typer.Exit(0)

    for error in result.errors:
        print_error(error)
    raise typer.Exit(2)


def _build_selection(
    *,
    include_type: list[str] | None,
    exclude_type: list[str] | None,
    include_group: list[str] | None,
    exclude_group: list[str] | None,
    only: list[str] | None,
    entity_ref_cls,
    selection_cls,
):
    if not any((include_type, exclude_type, include_group, exclude_group, only)):
        return None
    only_refs = None
    if only:
        only_refs = []
        for spec in only:
            if ":" not in spec:
                print_error(f"--only expects TYPE:NAME, got '{spec}'")
                raise typer.Exit(2)
            type_, name = spec.split(":", 1)
            only_refs.append(entity_ref_cls(type=type_.strip(), name=name.strip()))
    return selection_cls(
        include_entity_types=set(include_type) if include_type else None,
        exclude_entity_types=set(exclude_type) if exclude_type else None,
        include_groups=set(include_group) if include_group else None,
        exclude_groups=set(exclude_group) if exclude_group else None,
        only_entities=only_refs,
    )


# ---------------------------------------------------------------------------
# Announcement + reporting
# ---------------------------------------------------------------------------


def _announce(*, project, output_type, options, output_path) -> None:
    verb = "Dry run" if options.dry_run else "Generation"
    target = f" → {output_path}" if output_path else " (no files will be written)"
    print_info(
        f"{verb}: {output_type} for project '{project.name}'{target} "
        f"(error_strategy={options.error_strategy})"
    )


def _render_report(report) -> None:
    console.print()
    _render_plan_table(report)
    _render_issues_table(report)
    _render_status_line(report)


def _render_plan_table(report) -> None:
    plan = report.plan
    table = Table(title="Plan", show_header=True, header_style="bold cyan")
    table.add_column("Entity type", style="bold")
    table.add_column("Files", justify="right")

    for entity_type, count in sorted(plan.by_entity_type.items()):
        table.add_row(entity_type, str(count))
    table.add_row(
        "[bold]Total files planned[/bold]", f"[bold]{plan.files_planned}[/bold]"
    )
    console.print(table)


def _render_issues_table(report) -> None:
    if not report.issues:
        console.print("[green]No issues.[/green]")
        return
    table = Table(
        title=f"Issues ({len(report.issues)})",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Severity")
    table.add_column("Stage")
    table.add_column("Code")
    table.add_column("Entity")
    table.add_column("Message")

    for issue in report.issues:
        sev_style = {
            "error": "[red]ERROR[/red]",
            "warning": "[yellow]WARN[/yellow]",
            "info": "[cyan]INFO[/cyan]",
        }[issue.severity]
        entity = (
            f"{issue.entity.type}:{issue.entity.name}" if issue.entity else "—"
        )
        table.add_row(sev_style, issue.stage, issue.code, entity, issue.message)
    console.print(table)


def _render_status_line(report) -> None:
    console.print()
    files = report.files_generated
    if report.status == "success":
        verb = "Dry run completed" if report.is_dry_run else "Generation completed"
        print_success(f"{verb} successfully. {files} file(s) written.")
    elif report.status == "partial_success":
        print_warning(
            f"Generation partially succeeded: {files} file(s) written, "
            f"{report.error_count} error(s), {report.warning_count} warning(s)."
        )
    elif report.status == "validation_failed":
        print_error(
            f"Generation aborted at validation: {report.error_count} error(s). "
            "No files were written."
        )
    else:
        print_error(f"Generation failed: {report.error_count} error(s).")

    console.print(f"[dim]Run ID: {report.generation_run_id}[/dim]")
