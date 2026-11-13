"""
What a pre-stage's SQL reads, and how it is materialized.

A pre-stage is a dbt model that prepares a table's data (parses JSON, pivots,
...) before the stage reads it. Its SQL is stored and written as it is: the
engine doesn't parse it, since it may use any dialect and any dbt Jinja. It
only scans it for the few things generation needs to know:

- the sources and models it reads (``source('crm', 'CUSTOMER')``,
  ``ref('pstg__crm__orders')``), so a table that only feeds pre-stages gets no
  stage of its own, and a misspelled source is reported before dbt runs;
- the materialization its ``config()`` sets. The stage reads the pre-stage's
  columns from the database, and an ephemeral model has none there.

Like ``sql_columns``, this is a scan, not a parser. It only recognizes calls
whose arguments are string literals, and skips Jinja comments (``{# #}``).
SQL comments are scanned like the rest: dbt renders Jinja inside them too.
"""

from __future__ import annotations

import re

_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)

# A string literal argument: 'crm' or "crm".
_STRING_ARG = r"""\s*(?:'([^'\n]*)'|"([^"\n]*)")\s*"""

_SOURCE_CALL = re.compile(r"\bsource\s*\(" + _STRING_ARG + "," + _STRING_ARG + r"\)")
# ref('model') or ref('package', 'model').
_REF_CALL = re.compile(r"\bref\s*\(" + _STRING_ARG + r"(?:," + _STRING_ARG + r")?\)")
_MATERIALIZED = re.compile(r"""\bmaterialized\s*=\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]""")


def dbt_source_name(source_system_name: str) -> str:
    """The name a source system has in generated dbt code.

    It names the system's source in ``sources.yml`` and is the middle part of
    its stage and pre-stage names (``stg__crm__customer``).
    """
    return source_system_name.lower().replace(" ", "_")


def _scannable(sql: str | None) -> str:
    return _JINJA_COMMENT.sub(" ", sql or "")


def _argument(match: re.Match[str], position: int) -> str | None:
    """The string literal argument at ``position`` (1-based), if present."""
    single, double = match.group(2 * position - 1), match.group(2 * position)
    return single if single is not None else double


def referenced_sources(sql: str | None) -> list[tuple[str, str]]:
    """The ``(source, table)`` pairs ``sql`` reads with ``source()``.

    In order of first appearance, without duplicates, spelled as written.
    """
    found: list[tuple[str, str]] = []
    for match in _SOURCE_CALL.finditer(_scannable(sql)):
        pair = (_argument(match, 1) or "", _argument(match, 2) or "")
        if pair not in found:
            found.append(pair)
    return found


def referenced_models(sql: str | None) -> list[str]:
    """The models ``sql`` reads with ``ref()``.

    For ``ref('package', 'model')`` that is the model. In order of first
    appearance, without duplicates, spelled as written.
    """
    found: list[str] = []
    for match in _REF_CALL.finditer(_scannable(sql)):
        model = _argument(match, 2) or _argument(match, 1) or ""
        if model not in found:
            found.append(model)
    return found


def configured_materialization(sql: str | None) -> str | None:
    """The materialization ``sql`` sets in a ``config()`` call, if any.

    The last one wins, as in dbt. A materialization set elsewhere (the layer
    in ``dbt_project.yml``) isn't seen here.
    """
    matches = _MATERIALIZED.findall(_scannable(sql))
    return matches[-1] if matches else None
