"""
Serve command for TurboVault CLI.

Start Django development server with admin interface.
"""

import subprocess
import sys
from pathlib import Path

import typer
from rich.panel import Panel
from rich.text import Text

from engine.cli.utils.console import console, print_info, print_success


def serve(
    port: int = typer.Option(8000, "--port", "-p", help="Port to run the server on"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
) -> None:
    """
    Start Django development server with admin interface.

    This starts the Django runserver so you can access the admin
    interface to manage your Data Vault model.
    """

    # Display startup banner
    banner = Text()
    banner.append("🚀 Starting TurboVault Server\n\n", style="bold cyan")
    banner.append(f"Server: ", style="bold")
    banner.append(f"http://{host}:{port}/\n", style="cyan underline")
    banner.append(f"Admin:  ", style="bold")
    banner.append(f"http://{host}:{port}/admin/\n\n", style="cyan underline")
    banner.append("Press CTRL+C to stop the server", style="dim")

    console.print(
        Panel(banner, border_style="green", title="[bold]Server Starting[/bold]")
    )
    console.print()

    # Get path to manage.py
    backend_dir = Path(__file__).parent.parent.parent.parent
    manage_py = backend_dir / "manage.py"

    if not manage_py.exists():
        console.print("[error]Error: manage.py not found![/error]")
        console.print(f"Expected location: {manage_py}")
        raise typer.Exit(1)

    # Run Django runserver
    try:
        cmd = [sys.executable, str(manage_py), "runserver", f"{host}:{port}"]

        subprocess.run(cmd, cwd=str(backend_dir))

    except KeyboardInterrupt:
        console.print("\n\n[warning]Server stopped by user[/warning]")
    except Exception as e:
        console.print(f"[error]Failed to start server: {e}[/error]")
        raise typer.Exit(1)
