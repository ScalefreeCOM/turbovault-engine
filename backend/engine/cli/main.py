#!/usr/bin/env python
"""
TurboVault Engine CLI - Modern Data Vault automation tool.

A powerful command-line interface for Data Vault modeling and dbt project generation.
"""
import os
import sys
from pathlib import Path

import typer
from typing_extensions import Annotated

# Add backend directory to path to ensure Django can be imported
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from engine.cli.utils.console import console, print_banner
from engine.cli.commands import init_cmd, run_cmd, serve_cmd, reset_cmd, generate_cmd


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
) -> None:
    """
    TurboVault Engine - Data Vault Automation Tool.

    Use the commands below to initialize projects, generate dbt code,
    and manage your Data Vault implementation.
    """
    if version:
        console.print("[bold]TurboVault Engine[/bold] version 0.1.0")
        raise typer.Exit()

    # Setup Django for CLI context (only if not showing help/version)
    if ctx.invoked_subcommand:
        _setup_django()


def _setup_django() -> None:
    """Initialize Django for CLI context."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")

    # Suppress Django checks output for cleaner CLI
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")

    try:
        import django

        django.setup()

        # Check and run migrations if needed
        from engine.cli.utils.db_utils import ensure_database_ready

        ensure_database_ready()

    except Exception as e:
        console.print(f"[error]Failed to initialize Django: {e}[/error]")
        console.print(
            "\n[warning]Make sure you're running from the correct directory[/warning]"
        )
        raise typer.Exit(1)


# Register commands
app.command(name="init", help="Initialize a new TurboVault project")(init_cmd.init)
app.command(name="run", help="Export Data Vault model to JSON")(run_cmd.run)
app.command(name="generate", help="Generate dbt project from Data Vault model")(
    generate_cmd.generate
)
app.command(name="serve", help="Start Django admin server")(serve_cmd.serve)
app.command(name="reset", help="Reset the Django database")(reset_cmd.reset)


# Main entry point
if __name__ == "__main__":
    app()
