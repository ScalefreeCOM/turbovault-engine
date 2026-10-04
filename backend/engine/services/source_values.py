"""
Record Source and Load Date values, read the way datavault4dbt reads them.

A Source Table's record source and load date become the ``rsrc`` and ``ldts``
of its stage model, and datavault4dbt decides what the text means
(``is_attribute`` / ``is_expression`` / ``as_constant`` in its helpers):

- text starting with ``!`` is fixed text: the ``!`` is dropped and the rest is
  written as a string literal (``!CRM`` -> ``'CRM'``);
- text that reads as SQL - wrapped in single quotes, or containing ``(`` and
  ``)``, ``::`` or ``||`` - is used as it is (``sysdate()``);
- anything else is the name of a column of the source table.

Keep :func:`classify` in step with those rules: it is how users are told what
a value will do.

A table that sets no value inherits one: from its source system, then the
project, then the engine's defaults (:func:`resolve_source_values`). Values
may hold ``[[ source_system ]]`` and ``[[ source_table ]]``, filled in per
table, so one inherited value can still name each table (``![[ source_system
]].[[ source_table ]]`` -> ``!CRM.CUSTOMER``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.models import SourceSystem, SourceTable
    from engine.services.runtime_config import EngineRuntimeConfig

FIXED_TEXT_PREFIX = "!"

# Used when nothing gives a Load Date: the time the stage reads the row.
DEFAULT_LOAD_DATE = "sysdate()"

# Bare keywords datavault4dbt reads as SQL, but only on Trino; elsewhere they
# are column names (so ``CURRENT_TIMESTAMP`` needs its brackets).
_TRINO_SQL_KEYWORDS = frozenset(
    {"current_timestamp", "current_date", "current_time", "localtime", "localtimestamp"}
)

# Tolerant of spacing, like the naming-pattern placeholders.
_SOURCE_SYSTEM_TOKEN = re.compile(r"\[\[\s*source_system\s*\]\]")
_SOURCE_TABLE_TOKEN = re.compile(r"\[\[\s*source_table\s*\]\]")


class ValueKind(StrEnum):
    """What datavault4dbt makes of a Record Source or Load Date value."""

    COLUMN = "column"
    FIXED_TEXT = "fixed_text"
    SQL = "sql"


class ValueOrigin(StrEnum):
    """Where a table's effective value comes from."""

    TABLE = "table"
    SOURCE_SYSTEM = "source_system"
    PROJECT = "project"
    # The engine's own default: nothing set a value.
    DEFAULT = "default"


def classify(value: str, *, target_type: str | None = None) -> ValueKind:
    """How datavault4dbt reads ``value`` as ``rsrc`` or ``ldts``.

    ``target_type`` is the dbt adapter (``snowflake``, ``trino``, ...), when
    known; it only matters for Trino's bare SQL keywords.
    """
    if value.startswith(FIXED_TEXT_PREFIX):
        return ValueKind.FIXED_TEXT
    if _reads_as_sql(value, target_type=target_type):
        return ValueKind.SQL
    return ValueKind.COLUMN


def _reads_as_sql(value: str, *, target_type: str | None) -> bool:
    if value.startswith("'") and value.endswith("'"):
        return True
    if ("(" in value and ")" in value) or "::" in value or "||" in value:
        return True
    return target_type == "trino" and value.lower() in _TRINO_SQL_KEYWORDS


def fixed_text(text: str) -> str:
    """``text`` as a fixed-text value: written as it is into every row."""
    return f"{FIXED_TEXT_PREFIX}{text}"


def default_record_source(source_system_name: str) -> str:
    """The Record Source of a table when nothing sets one.

    The Source System's name, as fixed text. Without the ``!`` datavault4dbt
    would look for a column of that name, and the stage would fail.
    """
    return fixed_text(source_system_name)


def fill_placeholders(
    value: str, *, source_system_name: str, source_table_name: str
) -> str:
    """``value`` with ``[[ source_system ]]`` and ``[[ source_table ]]`` filled in."""
    value = _SOURCE_SYSTEM_TOKEN.sub(lambda _: source_system_name, value)
    return _SOURCE_TABLE_TOKEN.sub(lambda _: source_table_name, value)


@dataclass(frozen=True)
class SourceValues:
    """The values one level (table, source system or project) sets.

    ``None`` or blank means the level sets nothing and the next one decides.
    """

    record_source: str | None = None
    static_part: str | None = None
    load_date: str | None = None


@dataclass(frozen=True)
class ResolvedValue:
    """A table's effective value and where it comes from."""

    # Placeholders filled in; None only for a static part nothing sets.
    value: str | None
    origin: ValueOrigin | None
    # As written at ``origin``, placeholders and all.
    written: str | None = None


@dataclass(frozen=True)
class ResolvedSourceValues:
    record_source: ResolvedValue
    static_part: ResolvedValue
    load_date: ResolvedValue


def written_value(value: str | None) -> str | None:
    """``value`` as stored: trimmed, and None when blank (which inherits)."""
    if value is None:
        return None
    return value.strip() or None


def _first_set(
    levels: tuple[tuple[ValueOrigin, str | None], ...],
) -> tuple[ValueOrigin, str] | None:
    for origin, value in levels:
        cleaned = written_value(value)
        if cleaned is not None:
            return origin, cleaned
    return None


def resolve_source_values(
    *,
    source_system_name: str,
    source_table_name: str,
    table: SourceValues,
    source_system: SourceValues | None = None,
    project: SourceValues | None = None,
) -> ResolvedSourceValues:
    """The record source, static part and load date a table's stage uses.

    Each value is the table's own, else its source system's, else the
    project's, else the engine's default. The static part has no default:
    setting one turns on datavault4dbt's per-source high-water mark in the
    hubs and links the table loads, so it is only ever what a user set.
    """
    source_system = source_system or SourceValues()
    project = project or SourceValues()

    def fill(value: str) -> str:
        return fill_placeholders(
            value,
            source_system_name=source_system_name,
            source_table_name=source_table_name,
        )

    def chain(attribute: str) -> tuple[tuple[ValueOrigin, str | None], ...]:
        return (
            (ValueOrigin.TABLE, getattr(table, attribute)),
            (ValueOrigin.SOURCE_SYSTEM, getattr(source_system, attribute)),
            (ValueOrigin.PROJECT, getattr(project, attribute)),
        )

    found = _first_set(chain("record_source"))
    if found is None:
        written = default_record_source(source_system_name)
        record_source = ResolvedValue(written, ValueOrigin.DEFAULT, written)
    else:
        origin, written = found
        record_source = ResolvedValue(fill(written), origin, written)

    found = _first_set(chain("load_date"))
    if found is None:
        load_date = ResolvedValue(
            DEFAULT_LOAD_DATE, ValueOrigin.DEFAULT, DEFAULT_LOAD_DATE
        )
    else:
        origin, written = found
        load_date = ResolvedValue(fill(written), origin, written)

    found = _first_set(chain("static_part"))
    if found is None:
        static_part = ResolvedValue(None, None, None)
    else:
        origin, written = found
        static_part = ResolvedValue(fill(written), origin, written)

    return ResolvedSourceValues(
        record_source=record_source, static_part=static_part, load_date=load_date
    )


def project_source_values(runtime_config: EngineRuntimeConfig | None) -> SourceValues:
    """The project-level values in ``runtime_config``."""
    if runtime_config is None:
        return SourceValues()
    return SourceValues(
        record_source=runtime_config.default_record_source_value,
        static_part=runtime_config.default_static_part_of_record_source,
        load_date=runtime_config.default_load_date_value,
    )


def source_system_values(source_system: SourceSystem) -> SourceValues:
    """The values a source system sets for its tables."""
    return SourceValues(
        record_source=source_system.record_source_value,
        static_part=source_system.static_part_of_record_source,
        load_date=source_system.load_date_value,
    )


def source_table_values(table: SourceTable) -> SourceValues:
    """The values a source table sets itself."""
    return SourceValues(
        record_source=table.record_source_value,
        static_part=table.static_part_of_record_source,
        load_date=table.load_date_value,
    )


def resolve_table_values(
    table: SourceTable, *, runtime_config: EngineRuntimeConfig | None = None
) -> ResolvedSourceValues:
    """The effective values of a stored source table (see
    :func:`resolve_source_values`); ``runtime_config`` gives the project's."""
    system = table.source_system
    return resolve_source_values(
        source_system_name=system.name,
        source_table_name=table.physical_table_name,
        table=source_table_values(table),
        source_system=source_system_values(system),
        project=project_source_values(runtime_config),
    )
