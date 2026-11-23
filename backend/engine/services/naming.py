"""
Naming rules for names the Engine writes into generated output.

The rule classes follow TurboVault Studio's naming rules (#451); keep them in
sync:

- **A. Data Vault names** — hubs, links, satellites, PITs, reference tables,
  the snapshot control table, hash keys, hashdiffs, business key / alias
  columns, derived columns, table aliases and the stage / raw vault schemas.
  The Engine creates these objects, so they must be plain identifiers
  (``^[A-Za-z_][A-Za-z0-9_]*$``) and unique ignoring case: most warehouses
  fold unquoted identifiers to one case, and dbt names a model after its
  file, which case-insensitive file systems can't tell apart. SQL reserved
  words and names over ``MAX_IDENTIFIER_LENGTH`` characters are warned about.
- **B. Source names** — physical source schemas, databases, tables and
  columns. They already exist in the source database, so spaces, hyphens and
  mixed case are accepted (names that only work quoted are warned about).
  Only control characters, leading or trailing whitespace and the quote
  characters ``"`` and `````` are rejected: no quoting can carry them.
- **C. Display names that feed generated code** — source system and subject
  area names: letters, digits, spaces, ``-``, ``_`` and ``.``. Studio rejects
  anything else; the Engine only warns, as ``technical_name`` turns any
  display name into a safe technical name.

Technical names derived from display names (source system, subject area,
project name) all go through ``technical_name`` so one display name gives the
same folder, dbt source name, stage prefix and tag everywhere.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable

# A Data Vault name: letter or underscore first, then letters, digits, _.
DV_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

DV_NAME_RULE = "must start with a letter or _ and contain only letters, digits and _"

# Postgres truncates identifiers longer than this (NAMEDATALEN - 1); other
# warehouses allow more. Longer names are a warning, not an error.
MAX_IDENTIFIER_LENGTH = 63

# Quote characters of the supported platforms: no quoting can carry them.
SOURCE_QUOTE_CHARACTERS = ('"', "`")

DISPLAY_NAME_RULE = "should contain only letters, digits, spaces, -, _ and ."

# Rule C: besides letters and digits (any script), only these characters.
_DISPLAY_NAME_EXTRA_CHARACTERS = frozenset(" -_.")

# Common reserved words of the SQL standard and the warehouses datavault4dbt
# supports. A source name in this list works only when quoted. Not exhaustive:
# it is used for warnings, never to reject a name.
SQL_RESERVED_WORDS: frozenset[str] = frozenset(
    {
        "all", "alter", "and", "any", "as", "asc", "between", "by", "case",
        "cast", "check", "column", "constraint", "create", "cross", "current",
        "current_date", "current_time", "current_timestamp", "current_user",
        "default", "delete", "desc", "distinct", "drop", "else", "end",
        "except", "exists", "false", "fetch", "for", "foreign", "from", "full",
        "grant", "group", "having", "in", "inner", "insert", "intersect",
        "into", "is", "join", "lateral", "left", "like", "limit", "natural",
        "not", "null", "of", "offset", "on", "or", "order", "outer", "primary",
        "qualify", "references", "right", "select", "session_user", "set",
        "some", "table", "then", "to", "true", "union", "unique", "update",
        "user", "using", "values", "when", "where", "window", "with",
    }
)  # fmt: skip

# Fallback when a display name has no character usable in a technical name.
_EMPTY_TECHNICAL_NAME = "unnamed"

# German letters get their conventional spelling instead of losing the
# umlaut (``ü`` → ``ue``, not ``u``); ``ß`` has no decomposition at all and
# would otherwise be dropped. Applied after lowercasing, so ``Ä``/``ẞ`` too.
_TRANSLITERATIONS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def is_dv_name(name: object) -> bool:
    """Whether ``name`` is a valid Data Vault name (a plain identifier).

    Uses ``fullmatch``: ``$`` in ``re.match`` would also accept a trailing
    newline, which breaks the generated YAML and SQL.
    """
    return isinstance(name, str) and DV_NAME_PATTERN.fullmatch(name) is not None


def is_reserved_word(name: str) -> bool:
    """Whether ``name`` is a common SQL reserved word (any case)."""
    return name.lower() in SQL_RESERVED_WORDS


def is_too_long(name: str) -> bool:
    """Whether ``name`` is longer than the warehouses reliably keep."""
    return len(name) > MAX_IDENTIFIER_LENGTH


def invalid_source_name_reason(name: str) -> str | None:
    """Why a source schema, database, table or column name can't be used, or None.

    Rule B: anything that exists in the source is accepted except what no
    quoting can carry — control characters, leading or trailing whitespace
    and the platforms' quote characters.
    """
    if any(unicodedata.category(char) == "Cc" for char in name):
        return "contains a control character"
    if name != name.strip():
        return "starts or ends with whitespace"
    if any(quote in name for quote in SOURCE_QUOTE_CHARACTERS):
        return 'contains a quote character (" or `)'
    return None


def is_display_name(name: str) -> bool:
    """Whether a source system or subject area name follows rule C.

    Letters and digits of any script count (``Müller`` is fine: the technical
    name spells it out), plus spaces, ``-``, ``_`` and ``.``.
    """
    return bool(name.strip()) and all(
        char.isalnum() or char in _DISPLAY_NAME_EXTRA_CHARACTERS for char in name
    )


def source_name_quoting_reason(name: str) -> str | None:
    """Why a source table or column name needs quoting in SQL, or None.

    Names with spaces, hyphens or other special characters, reserved words
    and mixed-case names (folded to one case unless quoted) all need quoting.
    """
    if not is_dv_name(name):
        return "contains characters other than letters, digits and _"
    if is_reserved_word(name):
        return "is an SQL reserved word"
    if name != name.lower() and name != name.upper():
        return "mixes upper and lower case"
    return None


def needs_identifier_quoting(name: str) -> bool:
    """Whether a source name only works quoted, whatever the warehouse.

    Narrower than ``source_name_quoting_reason``: reserved words and mixed case
    depend on how the warehouse folds case, so dbt's own quoting settings are
    left in charge of them.
    """
    return not is_dv_name(name)


def technical_name(display_name: str | None) -> str:
    """The technical name derived from a display name.

    Used for every name the Engine derives: folders, dbt source names, stage
    and pre-stage prefixes, subject-area tags. The name is lowercased, German
    letters are spelled out (``Müller Straße`` → ``mueller_strasse``), other
    accents are dropped (``Café`` → ``cafe``) and every run of other
    characters becomes one ``_``: ``SAP-ERP`` → ``sap_erp``,
    ``Sales & Ops`` → ``sales_ops``. The result can never hold a path
    separator or ``..``, so it is safe as a folder or file name.
    """
    spelled_out = (display_name or "").lower().translate(_TRANSLITERATIONS)
    ascii_name = (
        unicodedata.normalize("NFKD", spelled_out)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    collapsed = re.sub(r"[^a-z0-9_]+", "_", ascii_name)
    if not collapsed.strip("_"):
        return _EMPTY_TECHNICAL_NAME
    return collapsed


def dbt_project_name(
    display_name: str | None, default: str = "turbovault_project"
) -> str:
    """The dbt project name derived from a project's display name.

    dbt requires a project name that starts with a letter, so a name starting
    with a digit or ``_`` gets a ``project_`` prefix.
    """
    if not display_name or not display_name.strip():
        return default
    name = technical_name(display_name)
    if not name[0].isalpha():
        name = f"project_{name.lstrip('_')}"
    return name


def case_insensitive_collisions(names: Iterable[str]) -> list[list[str]]:
    """Groups of distinct names that are equal ignoring case.

    ``["hub_Customer", "HUB_CUSTOMER", "hub_order"]`` gives
    ``[["hub_Customer", "HUB_CUSTOMER"]]``. Exact duplicates are not reported
    here; they are caught where the names are defined.
    """
    by_folded: dict[str, list[str]] = defaultdict(list)
    for name in names:
        spellings = by_folded[name.casefold()]
        if name not in spellings:
            spellings.append(name)
    return [spellings for spellings in by_folded.values() if len(spellings) > 1]
