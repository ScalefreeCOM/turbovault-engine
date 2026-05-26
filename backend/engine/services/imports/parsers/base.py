"""Shared helpers used by tabular parsers."""

from __future__ import annotations

from typing import Any


def is_empty(val: Any) -> bool:
    """True if a cell is None or a stringified null marker."""
    if val is None:
        return True
    s = str(val).strip().lower()
    return s in ("", "nan", "none", "null")


def clean(val: Any) -> str | None:
    """Strip and normalize a cell; return None if empty."""
    if is_empty(val):
        return None
    return str(val).strip()


def truthy(val: Any) -> bool:
    """Permissive boolean coercion for Excel/SQLite values."""
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("true", "yes", "y", "1", "t")
