"""
Workspace management commands for TurboVault CLI.

Provides 'turbovault workspace init' and 'turbovault workspace status'.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from engine.cli.utils.console import console

workspace_app = typer.Typer(
    name="workspace",
    help="Manage TurboVault workspaces",
    no_args_is_help=True,
)

# ─────────────────────────────────────────────
# workspace init
# ─────────────────────────────────────────────

_DB_ENGINE_CHOICES = ["sqlite3", "postgresql", "mysql", "mssql", "snowflake"]


def workspace_init(  # noqa: PLR0913
    # Database
    db_engine: Annotated[
        str,
        typer.Option(
            "--db-engine",
            help=f"Database backend. Choices: {', '.join(_DB_ENGINE_CHOICES)}",
        ),
    ] = "",
    db_name: Annotated[
        str,
        typer.Option("--db-name", help="Database name or SQLite file path"),
    ] = "",
    db_host: Annotated[
        str | None,
        typer.Option("--db-host", help="Database host (non-SQLite only)"),
    ] = None,
    db_port: Annotated[
        int | None,
        typer.Option("--db-port", help="Database port (non-SQLite only)"),
    ] = None,
    db_user: Annotated[
        str | None,
        typer.Option("--db-user", help="Database user (non-SQLite only)"),
    ] = None,
    db_password: Annotated[
        str | None,
        typer.Option("--db-password", help="Database password (non-SQLite only)"),
    ] = None,
    # Schemas
    stage_schema: Annotated[
        str,
        typer.Option("--stage-schema", help="Default staging schema name"),
    ] = "",
    rdv_schema: Annotated[
        str,
        typer.Option("--rdv-schema", help="Default RDV schema name"),
    ] = "",
    bdv_schema: Annotated[
        str,
        typer.Option("--bdv-schema", help="Default BDV schema name"),
    ] = "",
    # Admin user
    admin_username: Annotated[
        str | None,
        typer.Option("--admin-username", help="Admin username (skips prompt)"),
    ] = None,
    admin_email: Annotated[
        str | None,
        typer.Option("--admin-email", help="Admin email (skips prompt)"),
    ] = None,
    admin_password: Annotated[
        str | None,
        typer.Option("--admin-password", help="Admin password (skips prompt)"),
    ] = None,
    skip_admin: Annotated[
        bool,
        typer.Option("--skip-admin", help="Skip admin user creation entirely"),
    ] = False,
    # Overwrite
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Overwrite existing turbovault.yml"),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", help="Use interactive prompts"),
    ] = False,
) -> None:
    """
    Initialise the current directory as a TurboVault workspace.

    Creates turbovault.yml with database and schema settings, initialises
    the database, populates templates, and optionally creates an admin user.

    Run this once per workspace before creating any projects.
    """
    is_non_interactive = bool(db_engine or db_name or stage_schema or rdv_schema or bdv_schema)

    if is_non_interactive and not interactive:
        _init_from_flags(
            db_engine=db_engine or "sqlite3",
            db_name=db_name or "db.sqlite3",
            db_host=db_host,
            db_port=db_port,
            db_user=db_user,
            db_password=db_password,
            stage_schema=stage_schema or "stage",
            rdv_schema=rdv_schema or "rdv",
            bdv_schema=bdv_schema or "bdv",
            admin_username=admin_username,
            admin_email=admin_email,
            admin_password=admin_password,
            skip_admin=skip_admin,
            overwrite=overwrite,
        )
    else:
        _init_interactive(
            overwrite=overwrite,
            admin_username=admin_username,
            admin_email=admin_email,
            admin_password=admin_password,
            skip_admin=skip_admin,
        )


def _init_from_flags(
    *,
    db_engine: str,
    db_name: str,
    db_host: str | None,
    db_port: int | None,
    db_user: str | None,
    db_password: str | None,
    stage_schema: str,
    rdv_schema: str,
    bdv_schema: str,
    admin_username: str | None,
    admin_email: str | None,
    admin_password: str | None,
    skip_admin: bool,
    overwrite: bool,
) -> None:
    """Run non-interactive workspace initialisation from CLI flags."""
    from engine.services.app_config_loader import (
        AppConfigError,
        create_workspace_config,
    )

    console.print("\n[bold cyan][1/3] Creating turbovault.yml...[/bold cyan]")

    try:
        config_path = create_workspace_config(
            db_engine=db_engine,
            db_name=db_name,
            db_host=db_host,
            db_port=db_port,
            db_user=db_user,
            db_password=db_password,
            stage_schema=stage_schema,
            rdv_schema=rdv_schema,
            bdv_schema=bdv_schema,
            overwrite=overwrite,
        )
        console.print(f"[green]✓ Created turbovault.yml at {config_path}[/green]")
    except AppConfigError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)

    _init_database(
        admin_username=admin_username,
        admin_email=admin_email,
        admin_password=admin_password,
        skip_admin=skip_admin,
    )

    _print_workspace_summary(
        db_engine=db_engine,
        db_name=db_name,
        stage_schema=stage_schema,
        rdv_schema=rdv_schema,
        bdv_schema=bdv_schema,
    )


def _init_interactive(
    *,
    overwrite: bool,
    admin_username: str | None,
    admin_email: str | None,
    admin_password: str | None,
    skip_admin: bool,
) -> None:
    """Run interactive workspace initialisation wizard."""
    import questionary

    console.print("\n[bold magenta]TurboVault Workspace Setup[/bold magenta]\n")

    from engine.services.app_config_loader import (
        AppConfigError,
        create_workspace_config,
    )

    # Check if workspace already exists
    existing = (Path.cwd() / "turbovault.yml").exists()
    if existing and not overwrite:
        overwrite = questionary.confirm(
            "turbovault.yml already exists. Overwrite?", default=False
        ).ask()
        if not overwrite:
            console.print("[yellow]Workspace init cancelled.[/yellow]")
            raise typer.Exit(0)

    # Database engine
    db_engine_choice = questionary.select(
        "Database engine:",
        choices=[
            questionary.Choice("SQLite (local file)", value="sqlite3"),
            questionary.Choice("PostgreSQL", value="postgresql"),
            questionary.Choice("MySQL / MariaDB", value="mysql"),
            questionary.Choice("MS SQL Server", value="mssql"),
            questionary.Choice("Snowflake", value="snowflake"),
        ],
    ).ask()
    if not db_engine_choice:
        raise typer.Exit(0)

    db_name = "db.sqlite3"
    db_host = db_port = db_user = db_password = None

    if db_engine_choice == "sqlite3":
        db_name = (
            questionary.text("SQLite file name:", default="db.sqlite3").ask()
            or "db.sqlite3"
        )
    else:
        db_name = questionary.text("Database name:").ask() or ""
        db_host = questionary.text("Host:", default="localhost").ask()
        db_port_str = questionary.text("Port:", default="5432").ask()
        db_port = int(db_port_str) if db_port_str and db_port_str.isdigit() else None
        db_user = questionary.text("Username:").ask()
        db_password = questionary.password("Password:").ask()

    # Schema defaults
    modify_schemas = questionary.confirm(
        "Customize default schema names?", default=False
    ).ask()
    stage_schema = "stage"
    rdv_schema = "rdv"
    bdv_schema = "bdv"
    if modify_schemas:
        stage_schema = (
            questionary.text("Stage schema:", default="stage").ask() or "stage"
        )
        rdv_schema = questionary.text("RDV schema:", default="rdv").ask() or "rdv"
        bdv_schema = questionary.text("BDV schema:", default="bdv").ask() or "bdv"

    # Create turbovault.yml
    console.print("\n[bold cyan][1/3] Creating turbovault.yml...[/bold cyan]")
    try:
        config_path = create_workspace_config(
            db_engine=db_engine_choice,
            db_name=db_name,
            db_host=db_host,
            db_port=db_port,
            db_user=db_user,
            db_password=db_password,
            stage_schema=stage_schema,
            rdv_schema=rdv_schema,
            bdv_schema=bdv_schema,
            overwrite=overwrite,
        )
        console.print(f"[green]✓ Created {config_path}[/green]")
    except AppConfigError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)

    # Admin user
    if not skip_admin and not admin_username:
        create_admin = questionary.confirm(
            "Create an admin user now?", default=True
        ).ask()
        if not create_admin:
            skip_admin = True
        elif not admin_username:

            # We'll let initialise_workspace_db handle the interactive prompt
            pass

    _init_database(
        admin_username=admin_username,
        admin_email=admin_email,
        admin_password=admin_password,
        skip_admin=skip_admin,
    )

    _print_workspace_summary(
        db_engine=db_engine_choice,
        db_name=db_name,
        stage_schema=stage_schema,
        rdv_schema=rdv_schema,
        bdv_schema=bdv_schema,
    )


def _init_database(
    *,
    admin_username: str | None,
    admin_email: str | None,
    admin_password: str | None,
    skip_admin: bool,
) -> None:
    """Reload Django settings and run workspace DB setup."""
    import importlib

    import django
    from django.conf import settings as django_settings

    # Re-configure Django so it picks up the freshly written turbovault.yml
    django_settings.DATABASES = _reload_database_config()
    importlib.reload(django)  # reset connection pool

    console.print("\n[bold cyan][2/3] Initialising database...[/bold cyan]")

    from engine.cli.utils.db_utils import initialise_workspace_db

    initialise_workspace_db(
        admin_username=admin_username if not skip_admin else None,
        admin_email=admin_email if not skip_admin else None,
        admin_password=admin_password if not skip_admin else None,
        prompt_admin=not skip_admin,
    )


def _reload_database_config() -> dict:
    """Force-reload database settings from the newly created turbovault.yml."""
    from engine.services.app_config_loader import load_application_config

    app_config = load_application_config()
    if app_config.database:
        return {"default": app_config.database.to_django_config(Path.cwd())}
    from engine.services.config_schema import DatabaseConfig, DatabaseEngine

    return {
        "default": DatabaseConfig(
            engine=DatabaseEngine.SQLITE, name="db.sqlite3"
        ).to_django_config(Path.cwd())
    }


def _print_workspace_summary(
    *,
    db_engine: str,
    db_name: str,
    stage_schema: str,
    rdv_schema: str,
    bdv_schema: str,
) -> None:
    """Print a summary panel after successful workspace initialisation."""
    from rich.panel import Panel

    cwd = Path.cwd()
    summary_lines = [
        f"[bold]Location:[/bold]     {cwd}",
        f"[bold]Database:[/bold]     {db_engine} / {db_name}",
        f"[bold]Stage schema:[/bold] {stage_schema}",
        f"[bold]RDV schema:[/bold]   {rdv_schema}",
        f"[bold]BDV schema:[/bold]   {bdv_schema}",
        "",
        "[dim]Next step: [bold]turbovault project init --name <name>[/bold][/dim]",
    ]

    console.print(
        Panel(
            "\n".join(summary_lines),
            title="[3/3] Workspace Ready",
            border_style="green",
        )
    )


# ─────────────────────────────────────────────
# workspace status
# ─────────────────────────────────────────────


def workspace_status() -> None:
    """
    Show the status of the current TurboVault workspace.

    Displays database connection, project count, and pending migration status.
    """
    from engine.services.app_config_loader import (
        WorkspaceNotFoundError,
        require_workspace,
    )

    try:
        config_path = require_workspace()
    except WorkspaceNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)

    from engine.services.app_config_loader import load_application_config

    app_config = load_application_config()

    # Project count from DB (may fail if DB not set up)
    project_count: int | None = None
    pending_migrations: bool | None = None
    db_ok = False

    try:
        from engine.cli.utils.db_utils import (
            _has_pending_migrations,
            check_database_connection,
        )

        db_ok = check_database_connection()
        if db_ok:
            from engine.models import Project

            project_count = Project.objects.count()
            pending_migrations = _has_pending_migrations()
    except Exception:
        pass

    from rich.panel import Panel
    from rich.table import Table

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()

    table.add_row("Config file:", str(config_path))

    if app_config.database:
        db = app_config.database
        table.add_row("Database engine:", db.engine.value)
        db_display = db.name
        if db.host:
            db_display = f"{db.host}:{db.port}/{db.name}"
        table.add_row("Database:", db_display)

    db_status = (
        "[green]Connected[/green]"
        if db_ok
        else "[red]Not connected / not initialised[/red]"
    )
    table.add_row("DB status:", db_status)

    if project_count is not None:
        table.add_row("Projects:", str(project_count))

    if pending_migrations is not None:
        mig_status = (
            "[yellow]Pending migrations![/yellow]"
            if pending_migrations
            else "[green]Up to date[/green]"
        )
        table.add_row("Migrations:", mig_status)

    console.print(Panel(table, title="Workspace Status", border_style="cyan"))
