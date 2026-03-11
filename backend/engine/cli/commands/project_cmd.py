"""
Project management commands for TurboVault CLI.

Provides 'turbovault project init' and 'turbovault project list'.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from engine.cli.utils.console import console

project_app = typer.Typer(
    name="project",
    help="Manage TurboVault projects within a workspace",
    no_args_is_help=True,
)


def project_init(
    # Project identity
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", help="Project name"),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", help="Project description"),
    ] = None,
    # Source metadata
    source: Annotated[
        str | None,
        typer.Option("--source", "-s", help="Path to source file (.xlsx or .db)"),
    ] = None,
    # Schemas
    stage_schema: Annotated[
        str | None,
        typer.Option("--stage-schema", help="Stage schema name (default: stage)"),
    ] = None,
    rdv_schema: Annotated[
        str | None,
        typer.Option("--rdv-schema", help="RDV schema name (default: rdv)"),
    ] = None,
    bdv_schema: Annotated[
        str | None,
        typer.Option("--bdv-schema", help="BDV schema name (default: bdv)"),
    ] = None,
    stage_database: Annotated[
        str | None,
        typer.Option("--stage-database", help="Stage database name (optional)"),
    ] = None,
    rdv_database: Annotated[
        str | None,
        typer.Option("--rdv-database", help="RDV database name (optional)"),
    ] = None,
    bdv_database: Annotated[
        str | None,
        typer.Option("--bdv-database", help="BDV database name (optional)"),
    ] = None,
    # Naming patterns
    hashdiff_naming: Annotated[
        str | None,
        typer.Option("--hashdiff-naming", help="Hashdiff naming pattern"),
    ] = None,
    hashkey_naming: Annotated[
        str | None,
        typer.Option("--hashkey-naming", help="Hashkey naming pattern"),
    ] = None,
    satellite_v0_naming: Annotated[
        str | None,
        typer.Option("--satellite-v0-naming", help="Satellite v0 naming pattern"),
    ] = None,
    satellite_v1_naming: Annotated[
        str | None,
        typer.Option("--satellite-v1-naming", help="Satellite v1 naming pattern"),
    ] = None,
    # Options
    zip_output: Annotated[
        bool,
        typer.Option("--zip", help="Create ZIP archive of generated dbt project"),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite", help="Overwrite existing project with the same name"
        ),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", help="Use interactive prompts"),
    ] = False,
    config: Annotated[
        str | None,
        typer.Option(
            "--config", "-c", help="Path to a config.yml to import project from"
        ),
    ] = None,
) -> None:
    """
    Create a new Data Vault project in the current workspace.

    Requires a workspace to be initialised first ('turbovault workspace init').
    """
    from engine.services.app_config_loader import (
        WorkspaceNotFoundError,
        require_workspace,
    )

    try:
        require_workspace()
    except WorkspaceNotFoundError as e:
        console.print(f"\n[red]✗ {e}[/red]\n")
        raise typer.Exit(1)

    # Delegate to init_cmd's logic
    from engine.cli.commands.init_cmd import init

    init(
        name=name,
        description=description,
        source_path=Path(source) if source else None,
        stage_schema=stage_schema or "stage",
        rdv_schema=rdv_schema or "rdv",
        bdv_schema=bdv_schema or "bdv",
        stage_database=stage_database,
        rdv_database=rdv_database,
        bdv_database=bdv_database,
        create_zip=zip_output,
        hashdiff_naming=hashdiff_naming,
        hashkey_naming=hashkey_naming,
        overwrite=overwrite,
        interactive=interactive,
        config=Path(config) if config else None,
    )


def project_list() -> None:
    """
    List all projects in the current workspace.
    """
    from engine.services.app_config_loader import (
        WorkspaceNotFoundError,
        require_workspace,
    )

    try:
        require_workspace()
    except WorkspaceNotFoundError as e:
        console.print(f"\n[red]✗ {e}[/red]\n")
        raise typer.Exit(1)

    from rich.table import Table

    from engine.models import Project

    projects = Project.objects.all().order_by("name")

    if not projects.exists():
        console.print("[yellow]No projects found in this workspace.[/yellow]")
        console.print(
            "[dim]Run 'turbovault project init --name <name>' to create one.[/dim]"
        )
        return

    table = Table(title="Projects", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="bold")
    table.add_column("Description")
    table.add_column("Directory")

    for project in projects:
        table.add_row(
            project.name,
            project.description or "[dim]—[/dim]",
            project.project_directory or "[dim]—[/dim]",
        )

    console.print(table)
