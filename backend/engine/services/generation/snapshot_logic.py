"""
A snapshot control's logic, as datavault4dbt's ``control_snap_v1`` reads it.

``log_logic`` names intervals: ``daily``, ``weekly``, ``monthly`` and
``yearly``, each with a duration and unit or ``forever``. datavault4dbt
computes them from the snapshot's day: the day itself, the beginning of its
week, month or year. Written as one mapping, the intervals make one logic
column, named by the ``datavault4dbt.snapshot_trigger_column`` variable
(default ``is_active``); written as a list of ``{column: {...}}`` entries,
they make a column each.

TurboVault stores one logic rule per column and component. Four components
are datavault4dbt intervals; the others (the end of a week, month, quarter or
year, the beginning of a quarter) have no interval and can't be generated.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# TurboVault's components that are datavault4dbt intervals.
COMPONENT_INTERVALS = {
    "daily": "daily",
    "beginning_of_week": "weekly",
    "beginning_of_month": "monthly",
    "beginning_of_year": "yearly",
}

DEFAULT_TRIGGER_COLUMN = "is_active"


@dataclass(frozen=True)
class LogicInterval:
    name: str
    duration: int | None = None
    unit: str | None = None
    forever: bool = False


@dataclass
class LogicColumn:
    name: str
    intervals: list[LogicInterval] = field(default_factory=list)


@dataclass
class LogLogic:
    """What a control_snap_v1 model writes."""

    columns: list[LogicColumn]
    # One column named like the trigger column variable: written as a mapping
    # (every datavault4dbt version reads it); else as a list of columns.
    as_mapping: bool
    # (column, component) pairs datavault4dbt can't compute: left out.
    unsupported: list[tuple[str, str]]


def trigger_column(global_vars: Mapping[str, Any] | None) -> str:
    """The column a log_logic mapping computes (the variable, else is_active)."""
    value = (global_vars or {}).get("datavault4dbt.snapshot_trigger_column")
    return str(value) if value else DEFAULT_TRIGGER_COLUMN


def log_logic(patterns: Iterable[Any], trigger: str) -> LogLogic:
    """Group a control's logic rules into datavault4dbt's log_logic.

    ``patterns`` have ``column_name``, ``component``, ``duration``, ``unit``
    and ``forever`` (export ``SnapshotLogicPattern`` or the model's rows).
    """
    columns: dict[str, LogicColumn] = {}
    unsupported: list[tuple[str, str]] = []
    for pattern in patterns:
        column_name = str(pattern.column_name)
        component = str(pattern.component)
        interval = COMPONENT_INTERVALS.get(component)
        if interval is None:
            unsupported.append((column_name, component))
            continue
        column = columns.setdefault(column_name.lower(), LogicColumn(column_name))
        if any(existing.name == interval for existing in column.intervals):
            unsupported.append((column_name, component))
            continue
        column.intervals.append(
            LogicInterval(
                name=interval,
                duration=None if pattern.forever else pattern.duration,
                unit=None if pattern.forever else pattern.unit,
                forever=bool(pattern.forever),
            )
        )
    result = [column for column in columns.values() if column.intervals]
    as_mapping = len(result) == 1 and result[0].name.lower() == trigger.lower()
    return LogLogic(columns=result, as_mapping=as_mapping, unsupported=unsupported)
