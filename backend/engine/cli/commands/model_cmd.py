"""
Model management commands for TurboVault CLI.

Provides 'turbovault model' subcommands for managing source metadata and
creating Data Vault entities (hubs, links, satellites, PITs). All create
commands support a --interactive flag for guided prompting. When a source
table or source system is required but missing, commands offer to create
them inline (cascading).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from engine.cli.utils.console import (
    console,
    print_error,
    print_info,
    print_success,
    print_warning,
)

if TYPE_CHECKING:
    from engine.models import SourceSystem, SourceTable

model_app = typer.Typer(
    name="model",
    help="Create and manage Data Vault model entities",
    no_args_is_help=True,
)


# ─── prompt helpers ───────────────────────────────────────────────────────────


def _ask(prompt: str, default: str = "") -> str:
    import questionary
    result = questionary.text(prompt, default=default).ask()
    if result is None:
        raise typer.Exit(0)
    return result.strip()


def _ask_required(prompt: str) -> str:
    import questionary
    while True:
        result = questionary.text(prompt).ask()
        if result is None:
            raise typer.Exit(0)
        result = result.strip()
        if result:
            return result
        console.print("[yellow]This field is required.[/yellow]")


def _ask_choice(prompt: str, choices: list[str], default: str | None = None) -> str:
    import questionary
    result = questionary.select(prompt, choices=choices, default=default).ask()
    if result is None:
        raise typer.Exit(0)
    return result


def _ask_confirm(prompt: str, default: bool = False) -> bool:
    import questionary
    result = questionary.confirm(prompt, default=default).ask()
    if result is None:
        raise typer.Exit(0)
    return result


# ─── workspace / project helpers ─────────────────────────────────────────────


def _require_workspace_and_project(project_name: str | None):
    """Return the Project instance, prompting interactively when ambiguous."""
    from engine.models import Project
    from engine.services.app_config_loader import WorkspaceNotFoundError, require_workspace

    try:
        require_workspace()
    except WorkspaceNotFoundError as e:
        print_error(str(e))
        raise typer.Exit(1)

    if not project_name:
        projects = list(Project.objects.all().order_by("name"))
        if not projects:
            print_error("No projects found. Run: turbovault project init")
            raise typer.Exit(1)
        if len(projects) == 1:
            print_info(f"Using project: {projects[0].name}")
            return projects[0]
        project_name = _ask_choice("Select a project:", [p.name for p in projects])

    project = Project.objects.filter(name=project_name).first()
    if not project:
        print_error(f"Project '{project_name}' not found")
        raise typer.Exit(1)
    return project


# ─── source creation helpers (cascade) ───────────────────────────────────────


def _create_source_system_interactively(project) -> "SourceSystem":
    """Prompt for and create a new SourceSystem. Always returns a saved instance."""
    from engine.models import SourceSystem

    console.print("\n[bold]Creating source system...[/bold]")
    name = _ask_required("Source system name:")
    schema_name = _ask_required("Schema name:")
    db_val = _ask("Database name (leave blank to skip):")

    ss, created = SourceSystem.objects.get_or_create(
        project=project,
        name=name,
        defaults={"schema_name": schema_name, "database_name": db_val or ""},
    )
    if created:
        print_success(f"Source system '{ss.name}' created (schema: {ss.schema_name})")
    else:
        print_info(f"Using existing source system '{ss.name}'")
    return ss


def _create_source_table_interactively(project, suggested_name: str = "") -> "SourceTable | None":
    """
    Prompt for and create a new SourceTable, cascading to source system creation
    when no system exists yet. Returns the created/found instance, or None if
    the user cancels.
    """
    from engine.models import SourceSystem, SourceTable

    console.print("\n[bold]Creating source table...[/bold]")

    # Resolve source system — cascade if missing
    systems = list(SourceSystem.objects.filter(project=project).order_by("name"))
    if not systems:
        print_info("No source systems found.")
        if not _ask_confirm("Create a source system first?", default=True):
            return None
        ss = _create_source_system_interactively(project)
    elif len(systems) == 1:
        ss = systems[0]
        print_info(f"Using source system: {ss.name}")
    else:
        choices = ["(create new)"] + [s.name for s in systems]
        chosen = _ask_choice("Select source system:", choices)
        ss = (
            _create_source_system_interactively(project)
            if chosen == "(create new)"
            else next(s for s in systems if s.name == chosen)
        )

    physical_name = _ask_required(
        f"Physical table name{f' [{suggested_name}]' if suggested_name else ''}:"
    ) or suggested_name
    record_source = _ask_required("Record source expression (e.g. 'CRM.customers'):")
    load_date = _ask_required("Load date column or expression (e.g. 'LOAD_DATE'):")
    alias_val = _ask("Table alias (leave blank to skip):")

    existing = SourceTable.objects.filter(
        project=project, source_system=ss, physical_table_name=physical_name
    ).first()
    if existing:
        print_info(f"Source table '{physical_name}' already exists under '{ss.name}'. Using it.")
        return existing

    tbl = SourceTable.objects.create(
        project=project,
        source_system=ss,
        physical_table_name=physical_name,
        record_source_value=record_source,
        load_date_value=load_date,
        alias=alias_val or "",
    )
    print_success(f"Source table '{tbl.physical_table_name}' created under '{ss.name}'")
    return tbl


def _resolve_source_table(project, table_name: str) -> "SourceTable | None":
    """Look up SourceTable by physical name within the project."""
    from engine.models import SourceTable
    return SourceTable.objects.filter(
        project=project, physical_table_name__iexact=table_name
    ).first()


def _pick_or_create_source_table(
    project,
    given_name: str | None,
    interactive: bool,
) -> "SourceTable | None":
    """
    Central resolver used by create-hub and create-satellite:

    - If a name was given (flag or prior prompt) and found → return it.
    - If a name was given but NOT found → warn, offer to create inline (cascade).
    - If no name and interactive → show picker with existing tables + '(create new)'.
    - If no name and not interactive → return None silently.
    """
    from engine.models import SourceTable

    if given_name:
        tbl = _resolve_source_table(project, given_name)
        if tbl:
            return tbl
        print_warning(f"Source table '{given_name}' not found.")
        if _ask_confirm("Create it now?", default=True):
            return _create_source_table_interactively(project, suggested_name=given_name)
        return None

    if interactive:
        tables = list(SourceTable.objects.filter(project=project).order_by("physical_table_name"))
        choices = ["(skip)"] + [t.physical_table_name for t in tables] + ["(create new)"]
        chosen = _ask_choice("Source table for column mapping:", choices)
        if chosen == "(skip)":
            return None
        if chosen == "(create new)":
            return _create_source_table_interactively(project)
        return next(t for t in tables if t.physical_table_name == chosen)

    return None


def _get_or_create_staging_column(project, source_table, column_name: str):
    """
    Find SourceColumn by name in source_table and create StagingColumn if needed.
    Returns (staging_column, created) or (None, False) if column not found.
    """
    from engine.models import SourceColumn, StagingColumn

    src_col = SourceColumn.objects.filter(
        source_table=source_table,
        source_column_physical_name__iexact=column_name,
    ).first()
    if not src_col:
        return None, False

    staging_col, created = StagingColumn.objects.get_or_create(
        project=project,
        source_table=source_table,
        source_column=src_col,
    )
    return staging_col, created


def _resolve_or_create_staging_column(
    project,
    source_table,
    column_name: str,
    interactive: bool,
    force: bool,
) -> "tuple[object | None, str]":
    """
    Ensure a StagingColumn exists for column_name in source_table.

    Resolution order:
    1. Column found by name → return existing StagingColumn.
    2. force=True → auto-create SourceColumn (VARCHAR) + StagingColumn, log it.
    3. interactive=True → prompt: create / map to existing / skip.
    4. Otherwise → return (None, column_name) so the caller can warn.

    Returns (staging_column_or_None, resolved_column_name).
    """
    from engine.models import SourceColumn, StagingColumn

    # Happy path — column already exists
    staging, _ = _get_or_create_staging_column(project, source_table, column_name)
    if staging:
        return staging, column_name

    table_name = source_table.physical_table_name

    # --force: auto-create as VARCHAR
    if force:
        src_col = SourceColumn.objects.create(
            source_table=source_table,
            source_column_physical_name=column_name,
            source_column_datatype="VARCHAR",
        )
        staging, _ = StagingColumn.objects.get_or_create(
            project=project,
            source_table=source_table,
            source_column=src_col,
        )
        print_info(f"Auto-created source column '{column_name}' (VARCHAR) in '{table_name}'")
        return staging, column_name

    # Interactive: offer create / map / skip
    if interactive:
        action = _ask_choice(
            f"Source column '{column_name}' not found in '{table_name}'. What would you like to do?",
            [
                f"Create source column '{column_name}'",
                f"Map to an existing column in '{table_name}'",
                "Skip",
            ],
        )

        if action.startswith("Create"):
            datatype = _ask(f"Data type for '{column_name}' (default: VARCHAR):") or "VARCHAR"
            src_col = SourceColumn.objects.create(
                source_table=source_table,
                source_column_physical_name=column_name,
                source_column_datatype=datatype.strip().upper(),
            )
            staging, _ = StagingColumn.objects.get_or_create(
                project=project,
                source_table=source_table,
                source_column=src_col,
            )
            print_success(f"Source column '{column_name}' ({src_col.source_column_datatype}) created")
            return staging, column_name

        if action.startswith("Map"):
            existing = list(
                SourceColumn.objects.filter(source_table=source_table).order_by(
                    "source_column_physical_name"
                )
            )
            if not existing:
                print_warning(f"No columns in '{table_name}' yet — skipping.")
                return None, column_name
            chosen = _ask_choice(
                f"Select existing column to use as '{column_name}':",
                [c.source_column_physical_name for c in existing],
            )
            src_col = next(
                c for c in existing if c.source_column_physical_name == chosen
            )
            staging, _ = StagingColumn.objects.get_or_create(
                project=project,
                source_table=source_table,
                source_column=src_col,
            )
            return staging, chosen

        # "Skip"
        return None, column_name

    return None, column_name


# ─── create-source-system ────────────────────────────────────────────────────


def create_source_system(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    name: Annotated[
        str | None, typer.Option("--name", "-n", help="Source system name")
    ] = None,
    schema_name: Annotated[
        str | None, typer.Option("--schema", help="Database schema name")
    ] = None,
    database_name: Annotated[
        str | None, typer.Option("--database", help="Database name (optional)")
    ] = None,
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Prompt for all values interactively")
    ] = False,
) -> None:
    """Create a new source system (schema/database) in the project."""
    from engine.models import SourceSystem

    project = _require_workspace_and_project(project_name)

    if interactive or not name:
        name = name or _ask_required("Source system name:")
    if interactive or not schema_name:
        schema_name = schema_name or _ask_required("Schema name:")
    if interactive and database_name is None:
        val = _ask("Database name (leave blank to skip):")
        database_name = val or None

    if SourceSystem.objects.filter(project=project, name=name).exists():
        print_error(f"Source system '{name}' already exists in project '{project.name}'")
        raise typer.Exit(1)

    ss = SourceSystem.objects.create(
        project=project,
        name=name,
        schema_name=schema_name,
        database_name=database_name or "",
    )
    print_success(f"Source system '{ss.name}' created (schema: {ss.schema_name})")


# ─── create-source-table ─────────────────────────────────────────────────────


def create_source_table(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    source_system: Annotated[
        str | None, typer.Option("--source-system", "-s", help="Source system name")
    ] = None,
    physical_name: Annotated[
        str | None, typer.Option("--name", "-n", help="Physical table name")
    ] = None,
    record_source: Annotated[
        str | None,
        typer.Option("--record-source", help="Record source expression (e.g. 'CRM.customers')"),
    ] = None,
    load_date: Annotated[
        str | None,
        typer.Option("--load-date", help="Load date column or expression (e.g. 'LOAD_DATE')"),
    ] = None,
    alias: Annotated[
        str | None, typer.Option("--alias", help="Table alias (optional)")
    ] = None,
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Prompt for all values interactively")
    ] = False,
) -> None:
    """Create a new source table under a source system."""
    from engine.models import SourceSystem, SourceTable

    project = _require_workspace_and_project(project_name)

    # Resolve source system — cascade to creation when missing
    if interactive or not source_system:
        systems = list(SourceSystem.objects.filter(project=project).order_by("name"))
        if not systems:
            print_info("No source systems found.")
            if not _ask_confirm("Create a source system first?", default=True):
                raise typer.Exit(0)
            ss = _create_source_system_interactively(project)
        elif len(systems) == 1 and not interactive:
            ss = systems[0]
            print_info(f"Using source system: {ss.name}")
        else:
            choices = ["(create new)"] + [s.name for s in systems]
            chosen = _ask_choice("Select source system:", choices)
            ss = (
                _create_source_system_interactively(project)
                if chosen == "(create new)"
                else next(s for s in systems if s.name == chosen)
            )
    else:
        ss = SourceSystem.objects.filter(project=project, name=source_system).first()
        if not ss:
            print_error(f"Source system '{source_system}' not found in project '{project.name}'")
            if _ask_confirm("Create it now?", default=True):
                ss = _create_source_system_interactively(project)
            else:
                raise typer.Exit(1)

    if interactive or not physical_name:
        physical_name = physical_name or _ask_required("Physical table name:")
    if interactive or not record_source:
        record_source = record_source or _ask_required(
            "Record source expression (e.g. 'CRM.customers'):"
        )
    if interactive or not load_date:
        load_date = load_date or _ask_required(
            "Load date column or expression (e.g. 'LOAD_DATE'):"
        )
    if interactive and alias is None:
        val = _ask("Table alias (leave blank to skip):")
        alias = val or None

    if SourceTable.objects.filter(
        project=project, source_system=ss, physical_table_name=physical_name
    ).exists():
        print_error(
            f"Source table '{physical_name}' already exists under '{ss.name}'"
        )
        raise typer.Exit(1)

    tbl = SourceTable.objects.create(
        project=project,
        source_system=ss,
        physical_table_name=physical_name,
        record_source_value=record_source,
        load_date_value=load_date,
        alias=alias or "",
    )
    print_success(
        f"Source table '{tbl.physical_table_name}' created under source system '{ss.name}'"
    )


# ─── create-source-column ────────────────────────────────────────────────────


def create_source_column(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    source_table: Annotated[
        str | None,
        typer.Option("--source-table", "-t", help="Physical table name"),
    ] = None,
    column_name: Annotated[
        str | None, typer.Option("--name", "-n", help="Column physical name")
    ] = None,
    datatype: Annotated[
        str | None,
        typer.Option("--datatype", "-d", help="Column data type (e.g. VARCHAR, INTEGER)"),
    ] = None,
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Prompt for all values interactively")
    ] = False,
) -> None:
    """Add a source column to an existing source table."""
    from engine.models import SourceColumn, SourceTable

    project = _require_workspace_and_project(project_name)

    # Resolve source table — cascade to creation when missing
    if interactive or not source_table:
        tables = list(SourceTable.objects.filter(project=project).order_by("physical_table_name"))
        if not tables:
            print_info("No source tables found.")
            if not _ask_confirm("Create a source table first?", default=True):
                raise typer.Exit(0)
            tbl = _create_source_table_interactively(project)
            if not tbl:
                raise typer.Exit(0)
        elif len(tables) == 1 and not interactive:
            tbl = tables[0]
            print_info(f"Using source table: {tbl.physical_table_name}")
        else:
            choices = ["(create new)"] + [t.physical_table_name for t in tables]
            chosen = _ask_choice("Select source table:", choices)
            if chosen == "(create new)":
                tbl = _create_source_table_interactively(project)
                if not tbl:
                    raise typer.Exit(0)
            else:
                tbl = next(t for t in tables if t.physical_table_name == chosen)
    else:
        tbl = SourceTable.objects.filter(
            project=project, physical_table_name__iexact=source_table
        ).first()
        if not tbl:
            print_error(f"Source table '{source_table}' not found in project '{project.name}'")
            if _ask_confirm("Create it now?", default=True):
                tbl = _create_source_table_interactively(project, suggested_name=source_table)
                if not tbl:
                    raise typer.Exit(1)
            else:
                raise typer.Exit(1)

    if interactive or not column_name:
        column_name = column_name or _ask_required("Column physical name:")
    if interactive or not datatype:
        datatype = datatype or _ask_required("Data type (e.g. VARCHAR, INTEGER, TIMESTAMP):")

    if SourceColumn.objects.filter(
        source_table=tbl, source_column_physical_name__iexact=column_name
    ).exists():
        print_error(
            f"Column '{column_name}' already exists in table '{tbl.physical_table_name}'"
        )
        raise typer.Exit(1)

    col = SourceColumn.objects.create(
        source_table=tbl,
        source_column_physical_name=column_name,
        source_column_datatype=datatype,
    )
    print_success(
        f"Column '{col.source_column_physical_name}' ({col.source_column_datatype}) "
        f"added to '{tbl.physical_table_name}'"
    )


# ─── create-hub ──────────────────────────────────────────────────────────────


def create_hub(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    name: Annotated[
        str | None, typer.Option("--name", "-n", help="Hub physical name")
    ] = None,
    business_keys: Annotated[
        str | None,
        typer.Option("--business-keys", help="Comma-separated business key column names"),
    ] = None,
    hashkey: Annotated[
        str | None,
        typer.Option("--hashkey", help="Hashkey column name (auto-derived if omitted)"),
    ] = None,
    hub_type: Annotated[
        str | None,
        typer.Option("--type", help="Hub type: 'standard' or 'reference'"),
    ] = None,
    source_table: Annotated[
        str | None,
        typer.Option(
            "--source-table",
            help="Physical source table name — creates staging column mappings for business keys",
        ),
    ] = None,
    group: Annotated[
        str | None, typer.Option("--group", help="Group name (optional)")
    ] = None,
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Prompt for all values interactively")
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Auto-create any missing source columns as VARCHAR (non-interactive scripting)",
        ),
    ] = False,
) -> None:
    """Create a new hub in the project."""
    from engine.models import Group, Hub, HubColumn, HubSourceMapping

    project = _require_workspace_and_project(project_name)

    if interactive or not name:
        name = name or _ask_required("Hub physical name (e.g. HUB_CUSTOMER):")
    if interactive and hub_type is None:
        hub_type = _ask_choice("Hub type:", ["standard", "reference"], default="standard")
    hub_type = hub_type or "standard"
    if interactive and not business_keys:
        business_keys = _ask("Business key column names (comma-separated, e.g. CUSTOMER_ID):")
    if interactive and not hashkey:
        hashkey = _ask("Hashkey column name (leave blank to auto-derive):") or None
    if interactive and not group:
        val = _ask("Group name (leave blank to skip):")
        group = val or None

    # Resolve source table before creating the hub (cascade if missing)
    src_tbl = _pick_or_create_source_table(project, source_table, interactive)

    if Hub.objects.filter(project=project, hub_physical_name=name).exists():
        print_error(f"Hub '{name}' already exists in project '{project.name}'")
        raise typer.Exit(1)

    grp = None
    if group:
        grp, _ = Group.objects.get_or_create(project=project, group_name=group)

    hub = Hub.objects.create(
        project=project,
        hub_physical_name=name,
        hub_type=hub_type,
        hub_hashkey_name=hashkey or "",
        group=grp,
    )

    bk_list = [k.strip() for k in business_keys.split(",")] if business_keys else []
    hub_columns: list[HubColumn] = []
    for key in bk_list:
        if key:
            col = HubColumn.objects.create(hub=hub, column_name=key, column_type="business_key")
            hub_columns.append(col)

    msg = f"Hub '{hub.hub_physical_name}' created"
    if hub.hub_hashkey_name:
        msg += f" (hashkey: {hub.hub_hashkey_name})"
    if bk_list:
        msg += f" with business keys: {', '.join(bk_list)}"
    print_success(msg)

    # Source column mappings
    mapped: list[str] = []
    unmapped: list[str] = []
    if src_tbl:
        for hub_col in hub_columns:
            staging_col, resolved_name = _resolve_or_create_staging_column(
                project, src_tbl, hub_col.column_name, interactive, force
            )
            if staging_col:
                HubSourceMapping.objects.get_or_create(
                    hub_column=hub_col,
                    staging_column=staging_col,
                    defaults={"is_primary_source": True},
                )
                mapped.append(resolved_name)
            else:
                unmapped.append(hub_col.column_name)

    if mapped:
        print_info(f"Source mappings created: {', '.join(mapped)}")
    if unmapped:
        print_warning(
            f"Source columns not mapped for: {', '.join(unmapped)} "
            f"— run 'turbovault model create-source-column' or re-run with --force"
        )


# ─── create-link ─────────────────────────────────────────────────────────────


def create_link(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    name: Annotated[
        str | None, typer.Option("--name", "-n", help="Link physical name")
    ] = None,
    hubs: Annotated[
        str | None,
        typer.Option("--hubs", help="Comma-separated hub physical names to reference"),
    ] = None,
    hashkey: Annotated[
        str | None,
        typer.Option("--hashkey", help="Hashkey column name (auto-derived if omitted)"),
    ] = None,
    link_type: Annotated[
        str | None,
        typer.Option("--type", help="Link type: 'standard' or 'non_historized'"),
    ] = None,
    group: Annotated[
        str | None, typer.Option("--group", help="Group name (optional)")
    ] = None,
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Prompt for all values interactively")
    ] = False,
) -> None:
    """Create a new link connecting two or more hubs."""
    from engine.models import Group, Hub, Link, LinkHubReference

    project = _require_workspace_and_project(project_name)

    if interactive or not name:
        name = name or _ask_required("Link physical name (e.g. LNK_ORDER_CUSTOMER):")
    if interactive and link_type is None:
        link_type = _ask_choice(
            "Link type:", ["standard", "non_historized"], default="standard"
        )
    link_type = link_type or "standard"

    if interactive and not hubs:
        existing_hubs = list(Hub.objects.filter(project=project).order_by("hub_physical_name"))
        if existing_hubs:
            import questionary
            chosen = questionary.checkbox(
                "Select hubs to reference (space to toggle):",
                choices=[h.hub_physical_name for h in existing_hubs],
            ).ask()
            if chosen is None:
                raise typer.Exit(0)
            hubs = ",".join(chosen) if chosen else None
        else:
            hubs = _ask("Hub names to reference (comma-separated):")

    if interactive and not hashkey:
        hashkey = _ask("Hashkey column name (leave blank to auto-derive):") or None
    if interactive and not group:
        val = _ask("Group name (leave blank to skip):")
        group = val or None

    if Link.objects.filter(project=project, link_physical_name=name).exists():
        print_error(f"Link '{name}' already exists in project '{project.name}'")
        raise typer.Exit(1)

    grp = None
    if group:
        grp, _ = Group.objects.get_or_create(project=project, group_name=group)

    link = Link.objects.create(
        project=project,
        link_physical_name=name,
        link_type=link_type,
        link_hashkey_name=hashkey or "",
        group=grp,
    )

    hub_names = [h.strip() for h in hubs.split(",")] if hubs else []
    missing = []
    for hub_name in hub_names:
        if not hub_name:
            continue
        hub = Hub.objects.filter(project=project, hub_physical_name=hub_name).first()
        if hub:
            LinkHubReference.objects.create(link=link, hub=hub)
        else:
            missing.append(hub_name)

    if missing:
        print_warning(f"Hubs not found (references skipped): {', '.join(missing)}")

    msg = f"Link '{link.link_physical_name}' created"
    if link.link_hashkey_name:
        msg += f" (hashkey: {link.link_hashkey_name})"
    if hub_names:
        msg += f" referencing: {', '.join(h for h in hub_names if h not in missing)}"
    print_success(msg)


# ─── create-satellite ────────────────────────────────────────────────────────


def create_satellite(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    name: Annotated[
        str | None, typer.Option("--name", "-n", help="Satellite physical name")
    ] = None,
    parent_hub: Annotated[
        str | None,
        typer.Option("--parent-hub", help="Parent hub physical name (XOR with --parent-link)"),
    ] = None,
    parent_link: Annotated[
        str | None,
        typer.Option("--parent-link", help="Parent link physical name (XOR with --parent-hub)"),
    ] = None,
    sat_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            help="Satellite type: standard, non_historized, multi_active, effectivity, reference",
        ),
    ] = None,
    source_table: Annotated[
        str | None,
        typer.Option(
            "--source-table",
            help="Physical source table name — required for column mappings",
        ),
    ] = None,
    columns: Annotated[
        str | None,
        typer.Option(
            "--columns",
            help="Comma-separated source column names to map as satellite columns",
        ),
    ] = None,
    group: Annotated[
        str | None, typer.Option("--group", help="Group name (optional)")
    ] = None,
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Prompt for all values interactively")
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Auto-create any missing source columns as VARCHAR (non-interactive scripting)",
        ),
    ] = False,
) -> None:
    """Create a new satellite attached to a hub or link."""
    from engine.models import Group, Hub, Link, Satellite, SatelliteColumn

    project = _require_workspace_and_project(project_name)

    if interactive or not name:
        name = name or _ask_required("Satellite physical name (e.g. SAT_CUSTOMER_DETAILS):")

    # Interactive parent selection
    if interactive and not parent_hub and not parent_link:
        parent_type = _ask_choice("Parent entity type:", ["hub", "link"])
        if parent_type == "hub":
            hub_list = list(Hub.objects.filter(project=project).order_by("hub_physical_name"))
            if not hub_list:
                print_error("No hubs found. Create one first.")
                raise typer.Exit(1)
            parent_hub = _ask_choice(
                "Select parent hub:", [h.hub_physical_name for h in hub_list]
            )
        else:
            link_list = list(Link.objects.filter(project=project).order_by("link_physical_name"))
            if not link_list:
                print_error("No links found. Create one first.")
                raise typer.Exit(1)
            parent_link = _ask_choice(
                "Select parent link:", [lnk.link_physical_name for lnk in link_list]
            )

    if not parent_hub and not parent_link:
        print_error("Provide either --parent-hub or --parent-link")
        raise typer.Exit(1)
    if parent_hub and parent_link:
        print_error("--parent-hub and --parent-link are mutually exclusive")
        raise typer.Exit(1)

    if interactive and sat_type is None:
        sat_type = _ask_choice(
            "Satellite type:",
            ["standard", "non_historized", "multi_active", "effectivity", "reference"],
            default="standard",
        )
    sat_type = sat_type or "standard"

    if interactive and not group:
        val = _ask("Group name (leave blank to skip):")
        group = val or None

    # Resolve source table — cascade if missing (before satellite is created)
    src_tbl = _pick_or_create_source_table(project, source_table, interactive)

    # Prompt columns once we know the source table
    if interactive and not columns and src_tbl:
        from engine.models import SourceColumn
        src_cols = list(
            SourceColumn.objects.filter(source_table=src_tbl).order_by(
                "source_column_physical_name"
            )
        )
        if src_cols:
            import questionary
            chosen = questionary.checkbox(
                f"Select columns from '{src_tbl.physical_table_name}' to map (space to toggle):",
                choices=[c.source_column_physical_name for c in src_cols],
            ).ask()
            if chosen is None:
                raise typer.Exit(0)
            columns = ",".join(chosen) if chosen else None
        else:
            columns = _ask(
                f"Column names from '{src_tbl.physical_table_name}' to map (comma-separated, blank to skip):"
            ) or None

    if Satellite.objects.filter(project=project, satellite_physical_name=name).exists():
        print_error(f"Satellite '{name}' already exists in project '{project.name}'")
        raise typer.Exit(1)

    grp = None
    if group:
        grp, _ = Group.objects.get_or_create(project=project, group_name=group)

    hub_obj = None
    link_obj = None
    if parent_hub:
        hub_obj = Hub.objects.filter(project=project, hub_physical_name=parent_hub).first()
        if not hub_obj:
            print_error(f"Hub '{parent_hub}' not found in project '{project.name}'")
            raise typer.Exit(1)
    if parent_link:
        link_obj = Link.objects.filter(project=project, link_physical_name=parent_link).first()
        if not link_obj:
            print_error(f"Link '{parent_link}' not found in project '{project.name}'")
            raise typer.Exit(1)

    sat = Satellite.objects.create(
        project=project,
        satellite_physical_name=name,
        satellite_type=sat_type,
        parent_hub=hub_obj,
        parent_link=link_obj,
        source_table=src_tbl,
        group=grp,
    )

    parent_label = f"hub '{parent_hub}'" if parent_hub else f"link '{parent_link}'"
    print_success(f"Satellite '{name}' ({sat_type}) created on {parent_label}")
    if src_tbl:
        print_info(f"Source table: {src_tbl.physical_table_name}")

    # Create satellite column mappings
    mapped: list[str] = []
    unmapped: list[str] = []
    if src_tbl and columns:
        col_names = [c.strip() for c in columns.split(",") if c.strip()]
        for col_name in col_names:
            staging_col, resolved_name = _resolve_or_create_staging_column(
                project, src_tbl, col_name, interactive, force
            )
            if staging_col:
                SatelliteColumn.objects.get_or_create(
                    satellite=sat,
                    staging_column=staging_col,
                    defaults={"include_in_delta_detection": True},
                )
                mapped.append(resolved_name)
            else:
                unmapped.append(col_name)

    if mapped:
        print_info(f"Column mappings created: {', '.join(mapped)}")
    if unmapped:
        print_warning(
            f"Source columns not mapped for: {', '.join(unmapped)} "
            f"— run 'turbovault model create-source-column' or re-run with --force"
        )


# ─── create-pit ──────────────────────────────────────────────────────────────


def create_pit(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    name: Annotated[
        str | None, typer.Option("--name", "-n", help="PIT physical name")
    ] = None,
    hub: Annotated[
        str | None,
        typer.Option("--hub", help="Hub to track (XOR with --link)"),
    ] = None,
    link: Annotated[
        str | None,
        typer.Option("--link", help="Link to track (XOR with --hub)"),
    ] = None,
    snapshot_table: Annotated[
        str | None,
        typer.Option("--snapshot-table", help="Snapshot control table name"),
    ] = None,
    snapshot_logic: Annotated[
        str | None,
        typer.Option("--snapshot-logic", help="Snapshot control logic name"),
    ] = None,
    satellites: Annotated[
        str | None,
        typer.Option("--satellites", help="Comma-separated satellite names to include"),
    ] = None,
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Prompt for all values interactively")
    ] = False,
) -> None:
    """Create a new PIT (Point-in-Time) structure in the project."""
    from engine.models import Hub, Link, PIT, Satellite, SnapshotControlLogic, SnapshotControlTable

    project = _require_workspace_and_project(project_name)

    if interactive or not name:
        name = name or _ask_required("PIT physical name (e.g. PIT_CUSTOMER):")

    if interactive and not hub and not link:
        entity_type = _ask_choice("Track a hub or link?", ["hub", "link"])
        if entity_type == "hub":
            hubs = list(Hub.objects.filter(project=project).order_by("hub_physical_name"))
            if not hubs:
                print_error("No hubs found.")
                raise typer.Exit(1)
            hub = _ask_choice("Select hub:", [h.hub_physical_name for h in hubs])
        else:
            links = list(Link.objects.filter(project=project).order_by("link_physical_name"))
            if not links:
                print_error("No links found.")
                raise typer.Exit(1)
            link = _ask_choice("Select link:", [lnk.link_physical_name for lnk in links])

    if not hub and not link:
        print_error("Provide either --hub or --link")
        raise typer.Exit(1)
    if hub and link:
        print_error("--hub and --link are mutually exclusive")
        raise typer.Exit(1)

    if PIT.objects.filter(project=project, pit_physical_name=name).exists():
        print_error(f"PIT '{name}' already exists in project '{project.name}'")
        raise typer.Exit(1)

    snap_tables = list(
        SnapshotControlTable.objects.filter(project=project).order_by(
            "snapshot_control_table_name"
        )
    )
    if not snap_tables:
        print_error(
            "No snapshot control tables found. "
            "Create one via Django Admin first: turbovault serve"
        )
        raise typer.Exit(1)

    if interactive or not snapshot_table:
        chosen_table = _ask_choice(
            "Select snapshot control table:",
            [t.snapshot_control_table_name for t in snap_tables],
        )
        snap_tbl = next(
            t for t in snap_tables if t.snapshot_control_table_name == chosen_table
        )
    else:
        snap_tbl = SnapshotControlTable.objects.filter(
            project=project, snapshot_control_table_name=snapshot_table
        ).first()
        if not snap_tbl:
            print_error(
                f"Snapshot control table '{snapshot_table}' not found. "
                "Create it via Django Admin first: turbovault serve"
            )
            raise typer.Exit(1)

    snap_logics = list(
        SnapshotControlLogic.objects.filter(snapshot_control_table=snap_tbl).order_by(
            "snapshot_logic_column_name"
        )
    )
    if not snap_logics:
        print_error(
            f"No snapshot control logic entries under '{snap_tbl.snapshot_control_table_name}'. "
            "Create them via Django Admin first: turbovault serve"
        )
        raise typer.Exit(1)

    if interactive or not snapshot_logic:
        chosen_logic = _ask_choice(
            "Select snapshot control logic:",
            [lc.snapshot_logic_column_name for lc in snap_logics],
        )
        snap_logic_obj = next(
            lc for lc in snap_logics if lc.snapshot_logic_column_name == chosen_logic
        )
    else:
        snap_logic_obj = SnapshotControlLogic.objects.filter(
            snapshot_control_table=snap_tbl, snapshot_logic_column_name=snapshot_logic
        ).first()
        if not snap_logic_obj:
            print_error(
                f"Snapshot control logic '{snapshot_logic}' not found under "
                f"'{snap_tbl.snapshot_control_table_name}'. "
                "Create it via Django Admin first: turbovault serve"
            )
            raise typer.Exit(1)

    if interactive and not satellites:
        avail = list(
            Satellite.objects.filter(project=project).order_by("satellite_physical_name")
        )
        if avail:
            import questionary
            chosen = questionary.checkbox(
                "Select satellites to include (space to toggle):",
                choices=[s.satellite_physical_name for s in avail],
            ).ask()
            if chosen:
                satellites = ",".join(chosen)

    tracked_hub = None
    tracked_link = None
    entity_type_str = ""

    if hub:
        tracked_hub = Hub.objects.filter(project=project, hub_physical_name=hub).first()
        if not tracked_hub:
            print_error(f"Hub '{hub}' not found in project '{project.name}'")
            raise typer.Exit(1)
        entity_type_str = "hub"

    if link:
        tracked_link = Link.objects.filter(project=project, link_physical_name=link).first()
        if not tracked_link:
            print_error(f"Link '{link}' not found in project '{project.name}'")
            raise typer.Exit(1)
        entity_type_str = "link"

    pit = PIT.objects.create(
        project=project,
        pit_physical_name=name,
        tracked_entity_type=entity_type_str,
        tracked_hub=tracked_hub,
        tracked_link=tracked_link,
        snapshot_control_table=snap_tbl,
        snapshot_control_logic=snap_logic_obj,
    )

    if satellites:
        sat_names = [s.strip() for s in satellites.split(",")]
        missing_sats = []
        for sat_name in sat_names:
            if not sat_name:
                continue
            sat = Satellite.objects.filter(
                project=project, satellite_physical_name=sat_name
            ).first()
            if sat:
                pit.satellites.add(sat)
            else:
                missing_sats.append(sat_name)
        if missing_sats:
            print_warning(f"Satellites not found (skipped): {', '.join(missing_sats)}")

    tracked_label = hub or link
    print_success(f"PIT '{name}' created tracking {entity_type_str} '{tracked_label}'")


# ─── list ─────────────────────────────────────────────────────────────────────


def list_entities(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    entity_type: Annotated[
        str,
        typer.Option(
            "--type",
            "-t",
            help="Entity type: sources, hubs, links, satellites, pits, or all",
        ),
    ] = "all",
) -> None:
    """List Data Vault entities and source metadata in a project."""
    from rich.table import Table

    from engine.models import Hub, Link, PIT, Satellite, SourceSystem, SourceTable

    project = _require_workspace_and_project(project_name)
    show_all = entity_type == "all"

    if show_all or entity_type == "sources":
        systems = SourceSystem.objects.filter(project=project).order_by("name")
        tbl = Table(title=f"Source Systems — {project.name}", header_style="bold cyan")
        tbl.add_column("Name")
        tbl.add_column("Schema")
        tbl.add_column("Database")
        tbl.add_column("Tables")
        for ss in systems:
            tbl.add_row(
                ss.name,
                ss.schema_name,
                ss.database_name or "[dim]—[/dim]",
                str(ss.tables.count()),
            )
        console.print(tbl)

        tables = SourceTable.objects.filter(project=project).order_by("physical_table_name")
        tbl2 = Table(title=f"Source Tables — {project.name}", header_style="bold cyan")
        tbl2.add_column("Physical Name")
        tbl2.add_column("Source System")
        tbl2.add_column("Record Source")
        tbl2.add_column("Load Date")
        tbl2.add_column("Columns")
        for t in tables:
            tbl2.add_row(
                t.physical_table_name,
                t.source_system.name,
                t.record_source_value,
                t.load_date_value,
                str(t.columns.count()),
            )
        console.print(tbl2)

    if show_all or entity_type == "hubs":
        hubs = Hub.objects.filter(project=project).order_by("hub_physical_name")
        tbl = Table(title=f"Hubs — {project.name}", header_style="bold cyan")
        tbl.add_column("Name")
        tbl.add_column("Type")
        tbl.add_column("Hashkey")
        tbl.add_column("Business Keys")
        for h in hubs:
            bk_cols = h.columns.filter(column_type="business_key").values_list(
                "column_name", flat=True
            )
            tbl.add_row(
                h.hub_physical_name,
                h.hub_type,
                h.hub_hashkey_name or "[dim]—[/dim]",
                ", ".join(bk_cols) or "[dim]—[/dim]",
            )
        console.print(tbl)

    if show_all or entity_type == "links":
        links = Link.objects.filter(project=project).order_by("link_physical_name")
        tbl = Table(title=f"Links — {project.name}", header_style="bold cyan")
        tbl.add_column("Name")
        tbl.add_column("Type")
        tbl.add_column("Hashkey")
        tbl.add_column("Referenced Hubs")
        for lnk in links:
            hub_names = lnk.hub_references.values_list("hub__hub_physical_name", flat=True)
            tbl.add_row(
                lnk.link_physical_name,
                lnk.link_type,
                lnk.link_hashkey_name or "[dim]—[/dim]",
                ", ".join(hub_names) or "[dim]—[/dim]",
            )
        console.print(tbl)

    if show_all or entity_type == "satellites":
        sats = Satellite.objects.filter(project=project).order_by("satellite_physical_name")
        tbl = Table(title=f"Satellites — {project.name}", header_style="bold cyan")
        tbl.add_column("Name")
        tbl.add_column("Type")
        tbl.add_column("Parent Hub")
        tbl.add_column("Parent Link")
        tbl.add_column("Source Table")
        tbl.add_column("Columns")
        for sat in sats:
            tbl.add_row(
                sat.satellite_physical_name,
                sat.satellite_type,
                sat.parent_hub.hub_physical_name if sat.parent_hub else "[dim]—[/dim]",
                sat.parent_link.link_physical_name if sat.parent_link else "[dim]—[/dim]",
                sat.source_table.physical_table_name if sat.source_table else "[dim]—[/dim]",
                str(sat.columns.count()),
            )
        console.print(tbl)

    if show_all or entity_type == "pits":
        pits = PIT.objects.filter(project=project).order_by("pit_physical_name")
        tbl = Table(title=f"PITs — {project.name}", header_style="bold cyan")
        tbl.add_column("Name")
        tbl.add_column("Tracked Type")
        tbl.add_column("Tracked Entity")
        tbl.add_column("Satellites")
        for pit in pits:
            entity_name = (
                pit.tracked_hub.hub_physical_name
                if pit.tracked_hub
                else (pit.tracked_link.link_physical_name if pit.tracked_link else "—")
            )
            sat_names = pit.satellites.values_list("satellite_physical_name", flat=True)
            tbl.add_row(
                pit.pit_physical_name,
                pit.tracked_entity_type,
                entity_name,
                ", ".join(sat_names) or "[dim]—[/dim]",
            )
        console.print(tbl)


# ─── validate ─────────────────────────────────────────────────────────────────


def validate(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output validation results as JSON"),
    ] = False,
) -> None:
    """Validate Data Vault model entities for the project."""
    from engine.services.export.builder import ModelBuilder
    from engine.services.generation.validators import validate_export

    project = _require_workspace_and_project(project_name)

    try:
        builder = ModelBuilder(project)
        project_export = builder.build()
    except Exception as e:
        print_error(f"Failed to build export for validation: {e}")
        raise typer.Exit(1)

    result = validate_export(project_export)

    if output_json:
        payload = {
            "project": project.name,
            "valid": result.is_valid,
            "errors": [
                {
                    "code": e.code,
                    "entity_type": e.entity_type,
                    "entity": e.entity_name,
                    "message": e.message,
                }
                for e in result.errors
            ],
            "warnings": [
                {
                    "code": w.code,
                    "entity_type": w.entity_type,
                    "entity": w.entity_name,
                    "message": w.message,
                }
                for w in result.warnings
            ],
        }
        console.print_json(json.dumps(payload))
        raise typer.Exit(0 if result.is_valid else 1)

    if result.is_valid and not result.warnings:
        print_success(f"Project '{project.name}' is valid — no issues found")
    else:
        if result.errors:
            print_error(f"{len(result.errors)} error(s):")
            for err in result.errors:
                console.print(f"  [red]x[/red] {err}")
        if result.warnings:
            print_warning(f"{len(result.warnings)} warning(s):")
            for warn in result.warnings:
                console.print(f"  [yellow]![/yellow] {warn}")
        if result.is_valid:
            print_success("No errors — project is valid (warnings noted above)")

    raise typer.Exit(0 if result.is_valid else 1)


# ─── import-json ──────────────────────────────────────────────────────────────


def import_json(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    file: Annotated[
        Path,
        typer.Option("--file", "-f", help="Path to model proposal JSON file"),
    ] = ...,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate the JSON without writing to the database"),
    ] = False,
) -> None:
    """
    Import a Data Vault model from a proposal JSON file.

    Accepts the schema produced by the MCP server's propose_model_from_source
    tool. Creates Hub, HubColumn, Link, LinkHubReference, and Satellite records.
    Skips entities that already exist (idempotent).
    """
    from pydantic import ValidationError

    from engine.services.model_import_schema import ModelImportSchema
    from engine.services.model_import_service import import_model

    if not file.exists():
        print_error(f"File not found: {file}")
        raise typer.Exit(1)

    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print_error(f"Invalid JSON: {e}")
        raise typer.Exit(1)

    try:
        schema = ModelImportSchema.model_validate(raw)
    except ValidationError as e:
        print_error(f"Schema validation failed:\n{e}")
        raise typer.Exit(1)

    if dry_run:
        print_info("Dry run — schema is valid, no changes written")
        console.print(
            f"  [cyan]Hubs:[/cyan]       {len(schema.hubs)}\n"
            f"  [cyan]Links:[/cyan]      {len(schema.links)}\n"
            f"  [cyan]Satellites:[/cyan] {len(schema.satellites)}"
        )
        raise typer.Exit(0)

    project = _require_workspace_and_project(project_name)

    result = import_model(project.name, schema)

    if result.errors:
        for err in result.errors:
            console.print(f"  [red]x[/red] {err}")
        print_error("Import completed with errors")
        raise typer.Exit(1)

    if result.skipped:
        for msg in result.skipped:
            console.print(f"  [yellow]![/yellow] {msg}")

    print_success(
        f"Import complete — "
        f"{result.hubs_created} hub(s), "
        f"{result.links_created} link(s), "
        f"{result.satellites_created} satellite(s) created"
    )


# ─── register commands ────────────────────────────────────────────────────────

model_app.command(name="create-source-system", help="Create a new source system")(
    create_source_system
)
model_app.command(name="create-source-table", help="Create a new source table")(
    create_source_table
)
model_app.command(name="create-source-column", help="Add a column to a source table")(
    create_source_column
)
model_app.command(name="create-hub", help="Create a new hub")(create_hub)
model_app.command(name="create-link", help="Create a new link")(create_link)
model_app.command(name="create-satellite", help="Create a new satellite")(create_satellite)
model_app.command(name="create-pit", help="Create a new PIT (Point-in-Time) structure")(
    create_pit
)
model_app.command(name="list", help="List entities in a project")(list_entities)
model_app.command(name="validate", help="Validate the Data Vault model for a project")(validate)
model_app.command(name="import-json", help="Import a model proposal from JSON")(import_json)
