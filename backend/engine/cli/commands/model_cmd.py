"""
Model management commands for TurboVault CLI.

Provides 'turbovault model' subcommands for creating and inspecting
Data Vault entities (hubs, links, satellites, PITs) and for importing
a full model proposal from JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from engine.cli.utils.console import (
    console,
    print_error,
    print_info,
    print_success,
    print_warning,
)

model_app = typer.Typer(
    name="model",
    help="Create and manage Data Vault model entities",
    no_args_is_help=True,
)


# ─── helpers ─────────────────────────────────────────────────────────────────


def _require_workspace_and_project(project_name: str | None):
    """Return the Project instance or exit with an error."""
    from engine.models import Project
    from engine.services.app_config_loader import (
        WorkspaceNotFoundError,
        require_workspace,
    )

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
        names = ", ".join(p.name for p in projects)
        print_error(f"Multiple projects found — specify one with --project. Available: {names}")
        raise typer.Exit(1)

    project = Project.objects.filter(name=project_name).first()
    if not project:
        print_error(f"Project '{project_name}' not found")
        raise typer.Exit(1)
    return project


# ─── create-hub ──────────────────────────────────────────────────────────────


def create_hub(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    name: Annotated[str, typer.Option("--name", "-n", help="Hub physical name")] = ...,
    business_keys: Annotated[
        str | None,
        typer.Option(
            "--business-keys",
            help="Comma-separated business key column names",
        ),
    ] = None,
    hashkey: Annotated[
        str | None,
        typer.Option("--hashkey", help="Hashkey column name (auto-derived if omitted)"),
    ] = None,
    hub_type: Annotated[
        str,
        typer.Option("--type", help="Hub type: 'standard' or 'reference'"),
    ] = "standard",
    group: Annotated[
        str | None, typer.Option("--group", help="Group name (optional)")
    ] = None,
) -> None:
    """Create a new hub in the project."""
    from engine.models import Group, Hub, HubColumn

    project = _require_workspace_and_project(project_name)

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
    for key in bk_list:
        if key:
            HubColumn.objects.create(hub=hub, column_name=key, column_type="business_key")

    print_success(
        f"Hub '{hub.hub_physical_name}' created"
        + (f" (hashkey: {hub.hub_hashkey_name})" if hub.hub_hashkey_name else "")
        + (f" with business keys: {', '.join(bk_list)}" if bk_list else "")
    )


# ─── create-link ─────────────────────────────────────────────────────────────


def create_link(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    name: Annotated[str, typer.Option("--name", "-n", help="Link physical name")] = ...,
    hubs: Annotated[
        str | None,
        typer.Option("--hubs", help="Comma-separated hub physical names to reference"),
    ] = None,
    hashkey: Annotated[
        str | None,
        typer.Option("--hashkey", help="Hashkey column name (auto-derived if omitted)"),
    ] = None,
    link_type: Annotated[
        str,
        typer.Option("--type", help="Link type: 'standard' or 'non_historized'"),
    ] = "standard",
    group: Annotated[
        str | None, typer.Option("--group", help="Group name (optional)")
    ] = None,
) -> None:
    """Create a new link in the project."""
    from engine.models import Group, Hub, Link, LinkHubReference

    project = _require_workspace_and_project(project_name)

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

    print_success(
        f"Link '{link.link_physical_name}' created"
        + (f" (hashkey: {link.link_hashkey_name})" if link.link_hashkey_name else "")
        + (f" referencing: {', '.join(hub_names)}" if hub_names else "")
    )


# ─── create-satellite ────────────────────────────────────────────────────────


def create_satellite(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    name: Annotated[
        str, typer.Option("--name", "-n", help="Satellite physical name")
    ] = ...,
    parent_hub: Annotated[
        str | None,
        typer.Option("--parent-hub", help="Parent hub physical name (XOR with --parent-link)"),
    ] = None,
    parent_link: Annotated[
        str | None,
        typer.Option("--parent-link", help="Parent link physical name (XOR with --parent-hub)"),
    ] = None,
    sat_type: Annotated[
        str,
        typer.Option(
            "--type",
            help="Satellite type: standard, non_historized, multi_active, reference",
        ),
    ] = "standard",
    group: Annotated[
        str | None, typer.Option("--group", help="Group name (optional)")
    ] = None,
) -> None:
    """Create a new satellite in the project."""
    from engine.models import Group, Hub, Link, Satellite

    if not parent_hub and not parent_link:
        print_error("Provide either --parent-hub or --parent-link")
        raise typer.Exit(1)
    if parent_hub and parent_link:
        print_error("--parent-hub and --parent-link are mutually exclusive")
        raise typer.Exit(1)

    project = _require_workspace_and_project(project_name)

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

    Satellite.objects.create(
        project=project,
        satellite_physical_name=name,
        satellite_type=sat_type,
        parent_hub=hub_obj,
        parent_link=link_obj,
        group=grp,
    )

    parent_label = f"hub '{parent_hub}'" if parent_hub else f"link '{parent_link}'"
    print_success(f"Satellite '{name}' ({sat_type}) created on {parent_label}")


# ─── create-pit ──────────────────────────────────────────────────────────────


def create_pit(
    project_name: Annotated[
        str | None, typer.Option("--project", "-p", help="Project name")
    ] = None,
    name: Annotated[str, typer.Option("--name", "-n", help="PIT physical name")] = ...,
    hub: Annotated[
        str | None,
        typer.Option("--hub", help="Hub to track (XOR with --link)"),
    ] = None,
    link: Annotated[
        str | None,
        typer.Option("--link", help="Link to track (XOR with --hub)"),
    ] = None,
    snapshot_table: Annotated[
        str,
        typer.Option("--snapshot-table", help="Snapshot control table name"),
    ] = ...,
    snapshot_logic: Annotated[
        str,
        typer.Option("--snapshot-logic", help="Snapshot control logic name"),
    ] = ...,
    satellites: Annotated[
        str | None,
        typer.Option("--satellites", help="Comma-separated satellite names to include"),
    ] = None,
) -> None:
    """Create a new PIT (Point-in-Time) structure in the project."""
    from engine.models import Hub, Link, PIT, Satellite, SnapshotControlLogic, SnapshotControlTable

    if not hub and not link:
        print_error("Provide either --hub or --link")
        raise typer.Exit(1)
    if hub and link:
        print_error("--hub and --link are mutually exclusive")
        raise typer.Exit(1)

    project = _require_workspace_and_project(project_name)

    if PIT.objects.filter(project=project, pit_physical_name=name).exists():
        print_error(f"PIT '{name}' already exists in project '{project.name}'")
        raise typer.Exit(1)

    snap_table = SnapshotControlTable.objects.filter(
        project=project, snapshot_control_table_name=snapshot_table
    ).first()
    if not snap_table:
        print_error(
            f"Snapshot control table '{snapshot_table}' not found. "
            "Create it via Django Admin first: turbovault serve"
        )
        raise typer.Exit(1)

    snap_logic = SnapshotControlLogic.objects.filter(
        snapshot_control_table=snap_table, snapshot_logic_column_name=snapshot_logic
    ).first()
    if not snap_logic:
        print_error(
            f"Snapshot control logic '{snapshot_logic}' not found under table '{snapshot_table}'. "
            "Create it via Django Admin first: turbovault serve"
        )
        raise typer.Exit(1)

    tracked_hub = None
    tracked_link = None
    entity_type = ""

    if hub:
        tracked_hub = Hub.objects.filter(project=project, hub_physical_name=hub).first()
        if not tracked_hub:
            print_error(f"Hub '{hub}' not found in project '{project.name}'")
            raise typer.Exit(1)
        entity_type = "hub"

    if link:
        tracked_link = Link.objects.filter(project=project, link_physical_name=link).first()
        if not tracked_link:
            print_error(f"Link '{link}' not found in project '{project.name}'")
            raise typer.Exit(1)
        entity_type = "link"

    pit = PIT.objects.create(
        project=project,
        pit_physical_name=name,
        tracked_entity_type=entity_type,
        tracked_hub=tracked_hub,
        tracked_link=tracked_link,
        snapshot_control_table=snap_table,
        snapshot_control_logic=snap_logic,
    )

    if satellites:
        sat_names = [s.strip() for s in satellites.split(",")]
        missing = []
        for sat_name in sat_names:
            if not sat_name:
                continue
            sat = Satellite.objects.filter(
                project=project, satellite_physical_name=sat_name
            ).first()
            if sat:
                pit.satellites.add(sat)
            else:
                missing.append(sat_name)
        if missing:
            print_warning(f"Satellites not found (skipped): {', '.join(missing)}")

    tracked_label = hub or link
    print_success(f"PIT '{name}' created tracking {entity_type} '{tracked_label}'")


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
            help="Entity type: hubs, links, satellites, pits, or all",
        ),
    ] = "all",
) -> None:
    """List Data Vault entities in a project."""
    from rich.table import Table

    from engine.models import Hub, Link, PIT, Satellite

    project = _require_workspace_and_project(project_name)
    show_all = entity_type == "all"

    if show_all or entity_type == "hubs":
        hubs = Hub.objects.filter(project=project).order_by("hub_physical_name")
        table = Table(title=f"Hubs — {project.name}", header_style="bold cyan")
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("Hashkey")
        table.add_column("Business Keys")
        for h in hubs:
            bk_cols = h.columns.filter(column_type="business_key").values_list(
                "column_name", flat=True
            )
            table.add_row(
                h.hub_physical_name,
                h.hub_type,
                h.hub_hashkey_name or "[dim]—[/dim]",
                ", ".join(bk_cols) or "[dim]—[/dim]",
            )
        console.print(table)

    if show_all or entity_type == "links":
        links = Link.objects.filter(project=project).order_by("link_physical_name")
        table = Table(title=f"Links — {project.name}", header_style="bold cyan")
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("Hashkey")
        table.add_column("Referenced Hubs")
        for lnk in links:
            hub_names = lnk.hub_references.values_list("hub__hub_physical_name", flat=True)
            table.add_row(
                lnk.link_physical_name,
                lnk.link_type,
                lnk.link_hashkey_name or "[dim]—[/dim]",
                ", ".join(hub_names) or "[dim]—[/dim]",
            )
        console.print(table)

    if show_all or entity_type == "satellites":
        sats = Satellite.objects.filter(project=project).order_by("satellite_physical_name")
        table = Table(title=f"Satellites — {project.name}", header_style="bold cyan")
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("Parent Hub")
        table.add_column("Parent Link")
        for sat in sats:
            table.add_row(
                sat.satellite_physical_name,
                sat.satellite_type,
                sat.parent_hub.hub_physical_name if sat.parent_hub else "[dim]—[/dim]",
                sat.parent_link.link_physical_name if sat.parent_link else "[dim]—[/dim]",
            )
        console.print(table)

    if show_all or entity_type == "pits":
        pits = PIT.objects.filter(project=project).order_by("pit_physical_name")
        table = Table(title=f"PITs — {project.name}", header_style="bold cyan")
        table.add_column("Name")
        table.add_column("Tracked Type")
        table.add_column("Tracked Entity")
        table.add_column("Satellites")
        for pit in pits:
            entity_name = (
                pit.tracked_hub.hub_physical_name
                if pit.tracked_hub
                else (pit.tracked_link.link_physical_name if pit.tracked_link else "—")
            )
            sat_names = pit.satellites.values_list("satellite_physical_name", flat=True)
            table.add_row(
                pit.pit_physical_name,
                pit.tracked_entity_type,
                entity_name,
                ", ".join(sat_names) or "[dim]—[/dim]",
            )
        console.print(table)


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
    from engine.models import Project
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
                {"code": e.code, "entity_type": e.entity_type, "entity": e.entity_name, "message": e.message}
                for e in result.errors
            ],
            "warnings": [
                {"code": w.code, "entity_type": w.entity_type, "entity": w.entity_name, "message": w.message}
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
                console.print(f"  [red]✗[/red] {err}")
        if result.warnings:
            print_warning(f"{len(result.warnings)} warning(s):")
            for warn in result.warnings:
                console.print(f"  [yellow]⚠[/yellow] {warn}")
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
            console.print(f"  [red]✗[/red] {err}")
        print_error("Import completed with errors")
        raise typer.Exit(1)

    if result.skipped:
        for msg in result.skipped:
            console.print(f"  [yellow]⚠[/yellow] {msg}")

    print_success(
        f"Import complete — "
        f"{result.hubs_created} hub(s), "
        f"{result.links_created} link(s), "
        f"{result.satellites_created} satellite(s) created"
    )


# ─── register commands ────────────────────────────────────────────────────────

model_app.command(name="create-hub", help="Create a new hub")(create_hub)
model_app.command(name="create-link", help="Create a new link")(create_link)
model_app.command(name="create-satellite", help="Create a new satellite")(create_satellite)
model_app.command(name="create-pit", help="Create a new PIT (Point-in-Time) structure")(create_pit)
model_app.command(name="list", help="List Data Vault entities in a project")(list_entities)
model_app.command(name="validate", help="Validate the Data Vault model for a project")(validate)
model_app.command(name="import-json", help="Import a model proposal from JSON")(import_json)
