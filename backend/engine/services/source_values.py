"""
Record Source and Load Date values, read the way datavault4dbt reads them.

A Source Table's ``record_source_value`` and ``load_date_value`` become the
``rsrc`` and ``ldts`` of its stage model, and datavault4dbt decides what the
text means (``is_attribute`` / ``is_expression`` / ``as_constant`` in its
helpers):

- text starting with ``!`` is fixed text: the ``!`` is dropped and the rest is
  written as a string literal (``!CRM`` -> ``'CRM'``);
- text that reads as SQL - wrapped in single quotes, or containing ``(`` and
  ``)``, ``::`` or ``||`` - is used as it is (``sysdate()``);
- anything else is the name of a column of the source table.

Keep :func:`classify` in step with those rules: it is how users are told what
a value will do.
"""

from __future__ import annotations

from enum import StrEnum

FIXED_TEXT_PREFIX = "!"

# Used when a source gives no Load Date: the time the stage reads the row.
DEFAULT_LOAD_DATE = "sysdate()"

# Bare keywords datavault4dbt reads as SQL, but only on Trino; elsewhere they
# are column names (so ``CURRENT_TIMESTAMP`` needs its brackets).
_TRINO_SQL_KEYWORDS = frozenset(
    {"current_timestamp", "current_date", "current_time", "localtime", "localtimestamp"}
)


class ValueKind(StrEnum):
    """What datavault4dbt makes of a Record Source or Load Date value."""

    COLUMN = "column"
    FIXED_TEXT = "fixed_text"
    SQL = "sql"


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
    """The Record Source of a table whose source gives none.

    The Source System's name, as fixed text. Without the ``!`` datavault4dbt
    would look for a column of that name, and the stage would fail.
    """
    return fixed_text(source_system_name)


def effective_record_source(value: str | None, *, source_system_name: str) -> str:
    """The Record Source a stage is generated with: ``value``, or the default."""
    cleaned = (value or "").strip()
    return cleaned or default_record_source(source_system_name)


def effective_load_date(value: str | None) -> str:
    """The Load Date a stage is generated with: ``value``, or the default."""
    cleaned = (value or "").strip()
    return cleaned or DEFAULT_LOAD_DATE
