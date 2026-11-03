"""
Python-literal formatting for generated SQLMesh model files.

SQLMesh models are Python files calling datavault4sqlmesh factories, so
template values must be written as Python literals. These helpers produce the
exact formatting the generated files use and are registered as Jinja filters
(``py``, ``py_dict``, ``py_hashed_columns``, ``py_source_models``) by
``build_jinja_environment``.

The filters return ``Markup``: templates compiled from strings (DB templates,
per-run overrides) are autoescaped, which would otherwise turn the quotes of a
Python string literal into ``&#39;``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from markupsafe import Markup


class _StageSource(Protocol):
    """Anything with a ``stage_name`` (hub / link source infos)."""

    stage_name: str


def py_literal(value: Any) -> Markup:
    """Return *value* as a Python literal (``repr``)."""
    return Markup(repr(value))


def format_dict(mapping: Mapping[str, Any]) -> str:
    """Format a flat str→value dict for Python source — multi-line."""
    if not mapping:
        return "{}"
    lines = ["{"]
    for key, value in mapping.items():
        lines.append(f"        {key!r}: {value!r},")
    lines.append("    }")
    return "\n".join(lines)


def format_hashed_columns(hashed_columns: Mapping[str, Any]) -> str:
    """Format a stage's hashed_columns dict for Python source — multi-line.

    Hash keys map to a list of columns; hash diffs to a dict with
    ``is_hashdiff`` and ``columns``.
    """
    lines = ["{"]
    for key, value in hashed_columns.items():
        if isinstance(value, list):
            inner = ", ".join(repr(v) for v in value)
            lines.append(f"        {key!r}: [{inner}],")
        elif isinstance(value, dict):
            inner_lines = ["{"]
            for inner_key, inner_value in value.items():
                if isinstance(inner_value, list):
                    value_str = "[" + ", ".join(repr(v) for v in inner_value) + "]"
                else:
                    value_str = repr(inner_value)
                inner_lines.append(f"            {inner_key!r}: {value_str},")
            inner_lines.append("        }")
            lines.append(f"        {key!r}: " + "\n".join(inner_lines) + ",")
        else:
            lines.append(f"        {key!r}: {value!r},")
    lines.append("    }")
    return "\n".join(lines)


def format_source_models(sources: Iterable[_StageSource], stage_schema: str) -> str:
    """Format a list of ``SourceModel(...)`` calls for Python source."""
    items = [
        f"SourceModel(schema_name={stage_schema!r}, table_name={src.stage_name!r})"
        for src in sources
    ]
    if not items:
        return "[]"
    if len(items) == 1:
        return f"[{items[0]}]"
    inner = ",\n        ".join(items)
    return f"[\n        {inner},\n    ]"


def py_dict_filter(mapping: Mapping[str, Any]) -> Markup:
    """Jinja filter: ``format_dict`` as safe markup."""
    return Markup(format_dict(mapping))


def py_hashed_columns_filter(hashed_columns: Mapping[str, Any]) -> Markup:
    """Jinja filter: ``format_hashed_columns`` as safe markup."""
    return Markup(format_hashed_columns(hashed_columns))


def py_source_models_filter(
    sources: Iterable[_StageSource], stage_schema: str
) -> Markup:
    """Jinja filter: ``format_source_models`` as safe markup."""
    return Markup(format_source_models(sources, stage_schema))
