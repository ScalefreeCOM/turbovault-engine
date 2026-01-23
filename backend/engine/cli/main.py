#!/usr/bin/env python
"""
TurboVault Engine CLI - Modern Data Vault automation tool.

A powerful command-line interface for Data Vault modeling and dbt project generation.
"""
import os
import sys
from pathlib import Path
from typing import Annotated

import typer

# Add backend directory to path to ensure Django can be imported
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from engine.cli.commands import generate_cmd, init_cmd, reset_cmd, serve_cmd
from engine.cli.utils.console import console
from engine.cli.utils.debug import debug_print, set_debug_mode

# Create Typer app
app = typer.Typer(
    name="turbovault",
    help="TurboVault Engine - Data Vault modeling and dbt generation",
    add_completion=True,
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool, typer.Option("--version", "-v", help="Show version and exit")
    ] = False,
    debug: Annotated[
        bool, typer.Option("--debug", "-d", help="Enable debug output")
    ] = False,
) -> None:
    """
    TurboVault Engine - Data Vault Automation Tool.

    Use the commands below to initialize projects, generate dbt code,
    and manage your Data Vault implementation.
    """
    debug_print("Main callback invoked")

    # Enable debug mode if requested
    if debug:
        set_debug_mode(True)
        debug_print("Debug mode enabled")

    if version:
        console.print("[bold]TurboVault Engine[/bold] version 0.1.0")
        raise typer.Exit()

    # Display ASCII art banner when a command is invoked
    if ctx.invoked_subcommand:
        debug_print(f"Subcommand invoked: {ctx.invoked_subcommand}")
        _print_banner()

        # Skip Django setup for help commands
        if "--help" not in sys.argv and "-h" not in sys.argv:
            debug_print("Setting up Django...")
            # Only check migrations for init command
            check_migrations = ctx.invoked_subcommand == "init"
            _setup_django(check_migrations=check_migrations)
            debug_print("Django setup complete, proceeding to command")
        else:
            debug_print("Skipping Django setup for help command")


def _print_banner() -> None:
    """Display TurboVault ASCII art banner."""
    # fmt: off
    # ruff: noqa: W291, W293
    banner = """
  _______         _                           _ _
 |__   __|       | |                         | | |
    | |_   _ _ __| |__   _____   ____ _ _   _| | |_
    | | | | | '__| '_ \\ / _ \\ \\ / / _` | | | | | __|
    | | |_| | |  | |_) | (_) \\ V / (_| | |_| | | |_
    |_|\\__,_|_|  |_.__/ \\___/ \\_/ \\__,_|\\__,_|_|\\__|

"""
    # fmt: on
    console.print(f"[bold cyan]{banner}[/bold cyan]")


def _setup_django(check_migrations: bool = False) -> None:
    """Initialize Django for CLI context.

    Args:
        check_migrations: If True, check for and apply pending migrations
    """
    from engine.cli.utils.debug import debug_print

    debug_print("_setup_django() called")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")

    try:
        debug_print("Importing Django...")
        import django

        debug_print("Calling django.setup()...")
        django.setup()
        debug_print("django.setup() completed")

    except Exception as e:
        console.print(f"[red]✗ Failed to initialize Django: {e}[/red]")
        console.print(
            "\n[yellow]Make sure you're running from the correct directory[/yellow]"
        )
        import traceback

        traceback.print_exc()
        raise typer.Exit(1)

    # Check and run migrations if needed (only for init command)
    if check_migrations:
        try:
            debug_print("Importing ensure_database_ready...")
            from engine.cli.utils.db_utils import ensure_database_ready

            debug_print("Calling ensure_database_ready()...")
            ensure_database_ready()
            debug_print("ensure_database_ready() completed")
        except Exception as e:
            console.print(f"[red]✗ Database setup failed: {e}[/red]")
            import traceback

            traceback.print_exc()
            raise typer.Exit(1)
    else:
        debug_print("Skipping migration checks (not init command)")

    debug_print("_setup_django() returning")


# Register commands
app.command(name="init", help="Initialize a new TurboVault project")(init_cmd.init)
app.command(
    name="generate", help="Generate dbt project and/or export Data Vault model to JSON"
)(generate_cmd.generate)
app.command(name="serve", help="Start Django admin server")(serve_cmd.serve)
app.command(name="reset", help="Reset the Django database")(reset_cmd.reset)


# Main entry point
if __name__ == "__main__":
    app()
