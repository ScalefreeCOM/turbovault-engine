"""
Which columns a SQL expression reads.

Derived columns and column transformations are free SQL. To tell datavault4dbt
which source columns an expression needs (``src_cols_required``), and to show
users what a derived column is built from, we look for identifiers that name a
known column. This is deliberately a scan, not a parser: it only needs to skip
string literals and comments and compare identifiers against a known list, and
it has to work for every SQL dialect the generated project may target.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# One alternation, tried left to right at each position:
#   string literal  '...' with '' as an escaped quote
#   line comment    -- ... end of line
#   block comment   /* ... */
#   quoted ident    "..."  `...`  [...]
#   bare ident
_TOKEN = re.compile(
    r"""
      (?P<string>'(?:[^']|'')*'?)
    | (?P<line_comment>--[^\n]*)
    | (?P<block_comment>/\*.*?(?:\*/|\Z))
    | "(?P<double>(?:[^"]|"")*)"?
    | `(?P<backtick>[^`]*)`?
    | \[(?P<bracket>[^\]]*)\]?
    | (?P<bare>[A-Za-z_][A-Za-z0-9_$]*)
    """,
    re.VERBOSE | re.DOTALL,
)


def referenced_columns(expression: str | None, columns: Iterable[str]) -> list[str]:
    """Columns from ``columns`` that ``expression`` refers to.

    Matching is case-insensitive, as unquoted identifiers are in most
    warehouses. The result keeps the spelling from ``columns`` and the order of
    first appearance in the expression, without duplicates. Placeholders such
    as ``[[source_column]]`` must be resolved before calling this.
    """
    if not expression:
        return []
    known = {column.lower(): column for column in columns}
    if not known:
        return []

    found: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN.finditer(expression):
        name = next(
            (
                match.group(group)
                for group in ("double", "backtick", "bracket", "bare")
                if match.group(group) is not None
            ),
            None,
        )
        if name is None:
            continue  # a string literal or a comment
        if match.group("double") is not None:
            name = name.replace('""', '"')
        key = name.lower()
        if key in known and key not in seen:
            seen.add(key)
            found.append(known[key])
    return found
