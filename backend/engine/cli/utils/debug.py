"""
Debug utilities for TurboVault CLI.
"""

import os

from rich.console import Console

console = Console()

# Global debug flag
_DEBUG_ENABLED = False


def set_debug_mode(enabled: bool) -> None:
    """Enable or disable debug mode globally."""
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = enabled
    if enabled:
        os.environ["TURBOVAULT_DEBUG"] = "1"


def is_debug_enabled() -> bool:
    """Check if debug mode is enabled."""
    return _DEBUG_ENABLED or os.environ.get("TURBOVAULT_DEBUG", "").lower() in (
        "1",
        "true",
        "yes",
    )


def debug_print(message: str) -> None:
    """Print a debug message if debug mode is enabled."""
    if is_debug_enabled():
        console.print(f"[dim cyan]DEBUG:[/dim cyan] [dim]{message}[/dim]")
