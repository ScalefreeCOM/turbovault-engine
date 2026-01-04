"""
Reset command for TurboVault CLI.

Reset the Django database by removing and recreating it.
"""


import typer
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from engine.cli.utils.console import console, print_error, print_success, print_warning


def reset(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """
    Reset the Django database.

    This will flush all data from the database and run fresh migrations.
    All data will be lost. Use with caution.
    """

    # Display warning banner
    banner = Text()
    banner.append("⚠️  Database Reset\n\n", style="bold yellow")
    banner.append("This will:\n", style="bold")
    banner.append("  • Flush all database tables\n", style="yellow")
    banner.append("  • Remove all data\n", style="yellow")
    banner.append("  • Run fresh migrations\n\n", style="yellow")
    banner.append("This action cannot be undone!", style="bold red")

    console.print(Panel(banner, border_style="yellow", title="[bold]⚠️  Warning[/bold]"))
    console.print()

    # Confirm with user unless --force is used
    if not force:
        confirmed = Confirm.ask(
            "[bold yellow]Are you sure you want to reset the database?[/bold yellow]",
            default=False,
        )

        if not confirmed:
            print_warning("Database reset cancelled")
            raise typer.Exit(0)

    console.print("\n[bold]Flushing database...[/bold]")

    # Use Django management commands to flush and migrate
    from io import StringIO

    from django.core.management import call_command

    try:
        # Flush the database (delete all data)
        out = StringIO()
        call_command("flush", "--noinput", stdout=out)
        console.print(out.getvalue())
        print_success("✓ Database flushed")

        # Run migrations to ensure schema is up to date
        console.print("\n[bold]Running migrations...[/bold]")
        out = StringIO()
        call_command("migrate", "--noinput", stdout=out)
        console.print(out.getvalue())

        print_success("✓ Database reset complete!")
        console.print("\n[dim]The database has been reset with fresh migrations.[/dim]")

    except Exception as e:
        print_error(f"Failed to reset database: {e}")
        import traceback

        console.print(traceback.format_exc())
        raise typer.Exit(1)
