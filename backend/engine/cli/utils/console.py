"""
Console utilities for TurboVault CLI.

Provides Rich-based console output with custom theme and helper functions.
"""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

# Custom theme for TurboVault
custom_theme = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "bold green",
        "highlight": "bold magenta",
    }
)

# Global console instance
console = Console(theme=custom_theme)


def print_banner() -> None:
    """Display TurboVault banner."""
    banner = Text()
    banner.append("╔═══════════════════════════════════════╗\n", style="bold cyan")
    banner.append("║   ", style="bold cyan")
    banner.append("TurboVault Engine", style="bold magenta")
    banner.append("             ║\n", style="bold cyan")
    banner.append("║   ", style="bold cyan")
    banner.append("Data Vault Automation Tool", style="cyan")
    banner.append("    ║\n", style="bold cyan")
    banner.append("╚═══════════════════════════════════════╝", style="bold cyan")

    console.print(banner)
    console.print()


def print_success(message: str) -> None:
    """Print success message with check mark."""
    console.print(f"✓ {message}", style="success")


def print_error(message: str) -> None:
    """Print error message with X mark."""
    console.print(f"✗ {message}", style="error")


def print_info(message: str) -> None:
    """Print info message with info icon."""
    console.print(f"ℹ {message}", style="info")


def print_warning(message: str) -> None:
    """Print warning message with warning icon."""
    console.print(f"⚠ {message}", style="warning")


def print_panel(title: str, content: str, style: str = "info") -> None:
    """Print content in a Rich panel."""
    console.print(Panel(content, title=title, border_style=style))


def print_step(step_number: int, total_steps: int, message: str) -> None:
    """Print a step in a multi-step process."""
    console.print(f"[{step_number}/{total_steps}] {message}", style="highlight")
