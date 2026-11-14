"""
`turbovault import` — run the metadata import pipeline standalone.

Supports merge / replace_all / update_only modes, fail-fast / best-effort
error handling, and --dry-run for validate-only execution. Output is a
Rich summary table of plan counts plus a colored issue table.

Sources: Excel, SQLite, a TurboVault JSON export, an IRiS export folder, or a
dbt project (its folder, or its manifest.json). The format follows from the
path unless --format names it. A dbt project folder is searched for its
manifest, catalog, dbt_project.yml and package files; what is missing is
reported, and --dbt-parse creates a missing manifest with `dbt parse`.

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
from rich.markup import escape
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
                "a directory holding an IRiS three-file export, or a dbt "
                "project (its folder or its manifest.json). Default for dbt: "
                "the project's configured dbt_project.path"
            ),
            exists=True,
        ),
    ] = None,
    source_format: Annotated[
        str | None,
        typer.Option(
            "--format",
            "-f",
            help="Source format: excel | sqlite | json | iris | dbt (default: from the path)",
        ),
    ] = None,
    catalog: Annotated[
        Path | None,
        typer.Option(
            "--catalog",
            help="dbt: catalog.json (default: found next to the manifest)",
            exists=True,
        ),
    ] = None,
    dbt_project_file: Annotated[
        Path | None,
        typer.Option(
            "--dbt-project",
            help="dbt: dbt_project.yml (default: found in the project folder)",
            exists=True,
        ),
    ] = None,
    dbt_parse: Annotated[
        bool,
        typer.Option(
            "--dbt-parse",
            help=(
                "dbt: run `dbt parse` first when the project folder has no "
                "manifest (needs dbt, the project's adapter and its packages)"
            ),
        ),
    ] = False,
    no_descriptions: Annotated[
        bool,
        typer.Option("--no-descriptions", help="dbt: don't import descriptions"),
    ] = False,
    no_tags: Annotated[
        bool,
        typer.Option("--no-tags", help="dbt: don't import the models' tags"),
    ] = False,
    apply_settings: Annotated[
        bool | None,
        typer.Option(
            "--apply-settings/--keep-settings",
            help=(
                "dbt: write the settings the dbt project suggests (naming "
                "patterns, its dbt_project.yml) into the project's config.yml "
                "before importing, or keep the project's (default: ask)"
            ),
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
        turbovault import --project my_project --source ../analytics_dbt
        turbovault import --project my_project --format dbt   # configured folder

    Interactive (no flags, or explicit --interactive):
        turbovault import
        turbovault import --interactive
    """
    # The wizard shows a dbt project's files (and runs dbt parse) itself
    dbt_files_shown = False
    # If the user asked for interactive mode explicitly, OR they didn't pass
    # the essential arguments (--project + --source), drop into the wizard.
    if interactive or (project_name is None and source is None):
        params = _run_interactive_import()
        if params is None:
            console.print("Import cancelled.", style="warning")
            raise typer.Exit(0)
        project_name = params["project_name"]
        source = params["source"]
        source_format = params["format"]
        mode = params["mode"]
        on_error = params["on_error"]
        dry_run = params["dry_run"]
        skip_snapshots = params["skip_snapshots"]
        no_descriptions = not params["import_descriptions"]
        no_tags = not params["import_tags"]
        dbt_files_shown = source_format == "dbt"
    else:
        # Without a source, a project with a configured dbt project imports
        # from it (unless another format is asked for).
        if source is None and project_name and source_format in (None, "dbt"):
            configured = _configured_dbt_project(project_name)
            if configured is not None:
                source, source_format = configured, "dbt"
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
        source_format=source_format,
        mode=mode,
        on_error=on_error,
        dry_run=dry_run,
        skip_snapshots=skip_snapshots,
        catalog=catalog,
        dbt_project_file=dbt_project_file,
        dbt_parse=dbt_parse,
        import_descriptions=not no_descriptions,
        import_tags=not no_tags,
        apply_settings=apply_settings,
        dbt_files_shown=dbt_files_shown,
    )


def _run_import(
    *,
    project_name: str,
    source: Path,
    mode: str,
    on_error: str,
    dry_run: bool,
    skip_snapshots: bool,
    source_format: str | None = None,
    catalog: Path | None = None,
    dbt_project_file: Path | None = None,
    dbt_parse: bool = False,
    import_descriptions: bool = True,
    import_tags: bool = True,
    apply_settings: bool | None = None,
    dbt_files_shown: bool = False,
) -> None:
    """Shared execution path used by both flag-driven and interactive modes.

    ``dbt_files_shown``: the wizard has shown the dbt project's files (and
    created a missing manifest) already.
    """
    # Deferred: requires Django setup.
    from engine.models import Project
    from engine.services.imports import DbtSource, ImportOptions, import_metadata

    project = Project.objects.filter(name=project_name).first()
    if project is None:
        print_error(f"Project '{project_name}' not found.")
        raise typer.Exit(2)

    fmt = _normalize_format(source_format) if source_format else None
    src = _build_source(
        source,
        fmt,
        catalog=catalog,
        dbt_project=dbt_project_file,
        import_descriptions=import_descriptions,
        import_tags=import_tags,
    )
    if src is None:
        print_error(
            f"Cannot determine the source format of {source}. Use a .xlsx, "
            ".db/.sqlite or .json file, a directory of IRiS files, or a dbt "
            "project (or name the format with --format)."
        )
        raise typer.Exit(2)

    if (
        isinstance(src, DbtSource)
        and not dbt_files_shown
        and not _prepare_dbt_source(src, run_parse=dbt_parse)
    ):
        raise typer.Exit(2)

    options = ImportOptions(
        conflict_strategy=_normalize_mode(mode),
        error_strategy=_normalize_error(on_error),
        dry_run=dry_run,
        skip_snapshots=skip_snapshots,
    )

    if dry_run:
        print_info(
            f"Dry run: importing {source.name} into '{project.name}' and rolling it "
            "back (nothing is kept)."
        )
    else:
        print_info(
            f"Importing {source.name} into '{project.name}' "
            f"(mode={options.conflict_strategy}, on_error={options.error_strategy})."
        )

    if isinstance(src, DbtSource) and not dry_run:
        _offer_project_settings(project, src, options, apply_settings)

    report = import_metadata(project=project, source=src, options=options)
    _render_report(report)
    if dry_run and report.project_settings and not report.project_settings.is_empty():
        _show_project_settings(report.project_settings)

    if report.status == "success":
        raise typer.Exit(0)
    if report.status == "partial_success":
        raise typer.Exit(1)
    raise typer.Exit(2)


def _offer_project_settings(
    project: Any, source: Any, options: Any, apply_settings: bool | None
) -> None:
    """Show the settings a dbt project suggests; write them into config.yml.

    A dry run finds them (spec D22, D28): the naming patterns, schemas,
    folders and defaults its models follow, and its dbt_project.yml and
    packages. Applied before the import, what follows them isn't stored on
    the models.
    """
    from engine.services.imports import import_metadata

    if not project.project_directory:
        return
    preview = import_metadata(
        project=project,
        source=source,
        options=options.model_copy(update={"dry_run": True}),
    )
    settings = preview.project_settings
    if settings is None or settings.is_empty():
        return
    _show_project_settings(settings)
    if apply_settings is None:
        if not console.is_terminal:
            print_info(
                "Keeping the project's settings (--apply-settings writes these "
                "into config.yml)."
            )
            return
        apply_settings = questionary.confirm(
            "Write these settings into the project's config.yml before importing?",
            default=True,
        ).ask()
    if not apply_settings:
        return
    try:
        path = _apply_project_settings(project, settings)
    except Exception as exc:  # an invalid config.yml stays as it is
        print_warning(f"config.yml wasn't updated: {exc}")
        return
    print_success(f"Settings written to {path}")


def _shown_setting(value: Any) -> str:
    """A suggested setting's value, short enough for a table cell."""
    from engine.services.generation.project_yml import package_source

    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        return ", ".join(keys[:6]) + (", ..." if len(keys) > 6 else "")
    if isinstance(value, list):
        names = [
            package_source(entry) if isinstance(entry, dict) else str(entry)
            for entry in value
        ]
        return ", ".join(names[:4]) + (", ..." if len(names) > 4 else "")
    return str(value)


def _show_project_settings(settings: Any) -> None:
    table = Table(
        title="Settings the dbt project suggests",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Setting", style="bold")
    table.add_column("Suggested")
    for key, suggestion in settings.suggestions.items():
        share = (
            f"  [dim]({suggestion.matching} of {suggestion.total} follow it)[/dim]"
            if suggestion.total
            else "  [dim](from the dbt project)[/dim]"
        )
        table.add_row(key, escape(_shown_setting(suggestion.value)) + share)
    console.print(table)


def _apply_project_settings(project: Any, settings: Any) -> Path:
    """Write suggested settings into the project's config.yml; return its path."""
    from engine.services.project_config import apply_settings

    path = project.get_config_path()
    apply_settings(
        path, {key: item.value for key, item in settings.suggestions.items()}
    )
    return path


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

    configured = _configured_dbt_project(project_name)
    source_str = questionary.path(
        "Path to metadata file (.xlsx, .db/.sqlite, or .json), a directory of "
        "IRiS files, or a dbt project (folder or manifest.json):",
        default=str(configured) if configured else "",
    ).ask()
    if not source_str:
        return None
    source = Path(source_str).expanduser()
    if not source.exists():
        print_error(f"File not found: {source}")
        return None
    source_format = _detect_format(source)
    if source_format is None:
        print_error(
            f"Unsupported file type '{source.suffix}'. Use .xlsx, .db/.sqlite, "
            ".json, a directory of IRiS files, or a dbt project."
        )
        return None

    import_descriptions = import_tags = True
    if source_format == "dbt":
        from engine.services.imports import DbtSource

        if not _prepare_dbt_source(DbtSource(path=source), run_parse=None):
            return None
        import_descriptions = questionary.confirm(
            "Import the descriptions of models and columns?", default=True
        ).ask()
        if import_descriptions is None:
            return None
        import_tags = questionary.confirm(
            "Import the models' tags?", default=True
        ).ask()
        if import_tags is None:
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
        # For a dbt project it leaves out the project's own controls and PITs
        (
            "Leave the dbt project's snapshot controls and PITs out?"
            if source_format == "dbt"
            else "Skip creating a default snapshot control table?"
        ),
        default=False,
    ).ask()
    if skip_snapshots is None:
        return None

    return {
        "project_name": project_name,
        "source": source,
        "format": source_format,
        "mode": mode,
        "on_error": on_error,
        "dry_run": dry_run,
        "skip_snapshots": skip_snapshots,
        "import_descriptions": import_descriptions,
        "import_tags": import_tags,
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


_FORMATS = ("excel", "sqlite", "json", "iris", "dbt")


def _normalize_format(value: str) -> str:
    fmt = value.strip().lower()
    if fmt not in _FORMATS:
        raise typer.BadParameter(
            f"Unknown format '{value}'. Use one of: {', '.join(_FORMATS)}."
        )
    return fmt


def _detect_format(path: Path) -> str | None:
    """The source format a path holds, or None.

    A directory is a dbt project when it has a dbt_project.yml or a dbt
    manifest, else an IRiS three-file export. A .json file is a dbt manifest
    or a TurboVault export, told apart by its content.
    """
    from engine.services.imports.dbt.artifacts import is_dbt_manifest

    if path.is_dir():
        manifests = (path / "target" / "manifest.json", path / "manifest.json")
        if (path / "dbt_project.yml").is_file() or any(
            candidate.is_file() and is_dbt_manifest(candidate)
            for candidate in manifests
        ):
            return "dbt"
        return "iris"
    ext = path.suffix.lower()
    if ext == ".xlsx":
        return "excel"
    if ext in (".db", ".sqlite", ".sqlite3"):
        return "sqlite"
    if ext == ".json":
        return "dbt" if is_dbt_manifest(path) else "json"
    return None


def _build_source(
    path: Path,
    fmt: str | None = None,
    *,
    catalog: Path | None = None,
    dbt_project: Path | None = None,
    import_descriptions: bool = True,
    import_tags: bool = True,
) -> Any | None:
    """Build the right SourceInput subtype from the path (and --format).

    The engine.services.imports import is deferred to keep this file safe
    to import before Django is configured.
    """
    from engine.services.imports import (
        DbtSource,
        ExcelSource,
        IrisSource,
        JsonSource,
        SqliteSource,
    )

    fmt = fmt or _detect_format(path)
    if fmt == "dbt":
        return DbtSource(
            path=path,
            catalog=catalog,
            dbt_project=dbt_project,
            import_descriptions=import_descriptions,
            import_tags=import_tags,
        )
    sources = {
        "excel": ExcelSource,
        "sqlite": SqliteSource,
        "json": JsonSource,
        "iris": IrisSource,
    }
    return sources[fmt](path=path) if fmt in sources else None


def _configured_dbt_project(project_name: str) -> Path | None:
    """The dbt project folder in the project's config.yml, if it has one."""
    from engine.models import Project

    project = Project.objects.filter(name=project_name).first()
    if project is None or not project.project_directory:
        return None
    try:
        config = project.load_config()
    except Exception:  # no config.yml, or an invalid one: no default
        return None
    if config.dbt_project is None or config.dbt_project.path is None:
        return None
    return Path(config.dbt_project.path).expanduser()


def _prepare_dbt_source(source: Any, *, run_parse: bool | None) -> bool:
    """Show which artifacts the dbt project has; create a missing manifest.

    ``run_parse``: True runs `dbt parse` when the manifest is missing, False
    doesn't, None asks (interactive mode). Returns whether to go on.
    """
    from engine.services.imports.dbt.dbt_cli import find_dbt, run_dbt_parse
    from engine.services.imports.dbt.parser import locate

    paths = locate(source)
    table = Table(title="dbt project", show_header=True, header_style="bold cyan")
    table.add_column("File")
    table.add_column("Status")
    rows = [
        (
            "manifest.json",
            paths.manifest if paths.manifest.is_file() else None,
            "required",
        ),
        ("catalog.json", paths.catalog, "column types from the YAML only"),
        (
            "dbt_project.yml",
            paths.dbt_project,
            "var() defaults; folder settings unknown",
        ),
        (
            "packages",
            paths.packages[0] if paths.packages else None,
            "datavault4dbt version unknown",
        ),
    ]
    for name, found, without in rows:
        status = (
            f"[green]found[/green] {found}"
            if found
            else (
                "[red]missing[/red]"
                if without == "required"
                else f"[yellow]missing[/yellow]: {without}"
            )
        )
        table.add_row(name, status)
    console.print(table)

    if paths.manifest.is_file():
        return True

    project_dir = Path(source.path)
    if not project_dir.is_dir():
        print_error(f"No manifest at {paths.manifest}.")
        return False
    if run_parse is None:
        if find_dbt() is None:
            print_error(
                "No manifest, and dbt isn't installed here. Run `dbt parse` in "
                f"{project_dir} (no warehouse connection needed), then import again."
            )
            return False
        run_parse = questionary.confirm(
            "No manifest yet. Run `dbt parse` to create it? (renders the "
            "project's models; doesn't connect to the warehouse)",
            default=True,
        ).ask()
    if not run_parse:
        print_error(
            "No manifest. Run `dbt parse` in the dbt project (or pass --dbt-parse), "
            "then import again."
        )
        return False

    print_info(f"Running `dbt parse` in {project_dir} ...")
    result = run_dbt_parse(project_dir)
    if not result.ok:
        print_error("`dbt parse` didn't create a manifest:")
        console.print(result.output, markup=False, highlight=False)
        return False
    print_success("Created target/manifest.json.")
    return True


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
    summary = Table(title="Import Plan", show_header=True, header_style="bold cyan")
    summary.add_column("Entity", style="bold")
    columns = ("create", "update", "unchanged", "delete", "skip")
    for action in columns:
        summary.add_column(action.capitalize(), justify="right")

    for entity_type, counts in sorted(report.plan.counts.by_entity_type.items()):
        summary.add_row(
            entity_type, *(str(counts.get(action, 0)) for action in columns)
        )
    totals = report.plan.counts.totals
    summary.add_row(
        "[bold]Total[/bold]",
        *(f"[bold]{totals.get(action, 0)}[/bold]" for action in columns),
    )
    console.print(summary)

    # What changed on the entities that already existed
    updated = [entity for entity in report.plan.entities if entity.action == "update"]
    if updated:
        changes_table = Table(
            title=f"Changed ({len(updated)})",
            show_header=True,
            header_style="bold cyan",
        )
        changes_table.add_column("Entity", style="bold")
        changes_table.add_column("Name")
        changes_table.add_column("Changes")
        for entity in updated:
            fields = [change.field for change in entity.changes]
            shown = ", ".join(fields[:3]) + (
                f" (+{len(fields) - 3} more)" if len(fields) > 3 else ""
            )
            changes_table.add_row(entity.ref.type, entity.ref.name, shown)
        console.print(changes_table)

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
                if issue.location.node_id:
                    loc_parts.append(issue.location.node_id)
                if issue.location.parameter:
                    loc_parts.append(f"param '{issue.location.parameter}'")
                if issue.location.sheet:
                    loc_parts.append(issue.location.sheet)
                if issue.location.row:
                    loc_parts.append(f"row {issue.location.row}")
                if issue.location.column:
                    loc_parts.append(f"col '{issue.location.column}'")
            if issue.entity:
                loc_parts.append(f"<{issue.entity.type} {issue.entity.name}>")
            location_str = " ".join(loc_parts) or "—"

            issues_table.add_row(sev_style, issue.code, location_str, issue.message)
        console.print(issues_table)
    else:
        console.print("[green]No issues.[/green]")

    # Status line
    console.print()
    totals = report.plan.counts.totals
    outcome = (
        f"created {totals.get('create', 0)}, updated {totals.get('update', 0)}, "
        f"deleted {totals.get('delete', 0)}, unchanged {totals.get('unchanged', 0)}"
    )
    if report.status == "success":
        if report.is_dry_run:
            print_success(
                f"Dry run completed successfully: it would have {outcome}. "
                "Nothing was written."
            )
        else:
            print_success(f"Import completed successfully: {outcome}.")
    elif report.status == "partial_success":
        print_warning(
            f"Import partially succeeded: {outcome}, "
            f"skipped {totals.get('skip', 0)}, with "
            f"{report.error_count} error(s) and {report.warning_count} warning(s). "
            "See the Issues table above for details on each skipped item."
        )
    elif report.status == "validation_failed":
        print_error(f"Import aborted at validation: {report.error_count} error(s).")
    else:
        print_error(f"Import failed with {report.error_count} error(s).")

    console.print(f"[dim]Import run ID: {report.import_run_id}[/dim]")
