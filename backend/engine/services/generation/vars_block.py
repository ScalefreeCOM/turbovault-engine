"""
Serialize a caller-supplied mapping of datavault4dbt global variables into a
top-level ``vars:`` block for ``dbt_project.yml``.

The engine stays agnostic about *which* vars exist; it just serializes whatever
mapping the caller supplies. Curation, defaults, and validation of the
datavault4dbt key list are owned by the consumer (Studio).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml


def render_vars_block(global_vars: Mapping[str, Any] | None) -> str:
    """Render a datavault4dbt-style top-level ``vars:`` block.

    Returns ``""`` when the mapping is empty, so callers splicing the result into
    a template produce output that is byte-identical to having no vars at all.
    Otherwise returns::

        vars:
          <key>: <value>
          ...

    followed by a single trailing blank line, so the block can be spliced
    directly before ``models:``. Keys keep their insertion order. Values are
    typed and quoted by PyYAML (strings, booleans, ints, timestamp-like strings).

    Raises:
        ValueError: if ``global_vars`` is not a mapping, has a non-string key, or
            contains a value PyYAML cannot serialize.
    """
    if global_vars is None:
        return ""
    if not isinstance(global_vars, Mapping):
        raise ValueError("global_vars must be a mapping")
    if not global_vars:
        return ""
    if any(not isinstance(key, str) for key in global_vars):
        raise ValueError("global_vars keys must be strings")
    try:
        body = yaml.safe_dump(
            {"vars": dict(global_vars)},
            sort_keys=False,  # preserve caller insertion order
            default_flow_style=False,
            allow_unicode=True,
        )
    except yaml.YAMLError as exc:  # e.g. RepresenterError for unsupported types
        raise ValueError(
            f"global_vars contains a non-serializable value: {exc}"
        ) from exc
    # safe_dump emits `vars:\n  k: v\n`; add one blank line so `models:` is
    # separated when this block is spliced into the template.
    return body.rstrip("\n") + "\n\n"
