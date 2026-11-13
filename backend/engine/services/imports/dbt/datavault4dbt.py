"""
Interpreting captured datavault4dbt calls.

A captured call (``extract.CapturedCall``) holds the arguments as the model
wrote them. This module turns them into what the macro works with:

- ``yaml_metadata`` is resolved like datavault4dbt's ``yaml_metadata_parser``:
  a parameter in the YAML wins over one passed separately; a separate value
  (``false`` included) applies otherwise.
- Parameters a macro doesn't know are dropped and reported: datavault4dbt
  ignores them as well (e.g. ``ldts`` on a Hub, whose parameter is
  ``src_ldts``, or a YAML line that is an SQL comment).
- Argument shapes are normalized the way the macros normalize them
  (``source_model_processing``, ``process_prejoined_columns``, ...), so the
  mapping sees one shape per parameter whatever version or notation the
  project uses.

The signatures are the union of datavault4dbt 1.0.0, 1.18.3 and 2.3.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

from engine.services.imports.dbt.extract import CapturedCall, is_unresolved

# Parameters per macro (without yaml_metadata), all supported versions.
SIGNATURES: dict[str, frozenset[str]] = {
    "stage": frozenset(
        {
            "ldts",
            "rsrc",
            "source_model",
            "include_source_columns",
            "hashed_columns",
            "derived_columns",
            "sequence",
            "prejoined_columns",
            "missing_columns",
            "multi_active_config",
            "enable_ghost_records",
        }
    ),
    "hub": frozenset(
        {
            "hashkey",
            "business_keys",
            "source_models",
            "src_ldts",
            "src_rsrc",
            "disable_hwm",
            "additional_columns",
        }
    ),
    "ref_hub": frozenset(
        {"ref_keys", "source_models", "src_ldts", "src_rsrc", "additional_columns"}
    ),
    "link": frozenset(
        {
            "link_hashkey",
            "foreign_hashkeys",
            "source_models",
            "src_ldts",
            "src_rsrc",
            "disable_hwm",
            "additional_columns",
        }
    ),
    "nh_link": frozenset(
        {
            "link_hashkey",
            "payload",
            "source_models",
            "foreign_hashkeys",
            "src_ldts",
            "src_rsrc",
            "disable_hwm",
            "source_is_single_batch",
            "union_strategy",
            "additional_columns",
        }
    ),
    "sat_v0": frozenset(
        {
            "parent_hashkey",
            "src_hashdiff",
            "src_payload",
            "source_model",
            "src_ldts",
            "src_rsrc",
            "disable_hwm",
            "source_is_single_batch",
            "additional_columns",
        }
    ),
    "sat_v1": frozenset(
        {
            "sat_v0",
            "hashkey",
            "hashdiff",
            "src_ldts",
            "src_rsrc",
            "ledts_alias",
            "add_is_current_flag",
            "include_payload",
        }
    ),
    "ma_sat_v0": frozenset(
        {
            "parent_hashkey",
            "src_hashdiff",
            "src_ma_key",
            "src_payload",
            "source_model",
            "src_ldts",
            "src_rsrc",
            "additional_columns",
            "disable_hwm",
            "source_is_single_batch",
        }
    ),
    "ma_sat_v1": frozenset(
        {
            "sat_v0",
            "hashkey",
            "hashdiff",
            "ma_attribute",
            "src_ldts",
            "src_rsrc",
            "ledts_alias",
            "add_is_current_flag",
        }
    ),
    "nh_sat": frozenset(
        {
            "parent_hashkey",
            "src_payload",
            "source_model",
            "src_ldts",
            "src_rsrc",
            "source_is_single_batch",
            "additional_columns",
        }
    ),
    "ref_sat_v0": frozenset(
        {
            "parent_ref_keys",
            "src_hashdiff",
            "src_payload",
            "source_model",
            "src_ldts",
            "src_rsrc",
            "disable_hwm",
            "source_is_single_batch",
            "additional_columns",
        }
    ),
    "ref_sat_v1": frozenset(
        {
            "ref_sat_v0",
            "ref_keys",
            "hashdiff",
            "src_ldts",
            "src_rsrc",
            "ledts_alias",
            "add_is_current_flag",
        }
    ),
    "eff_sat_v0": frozenset(
        {
            "source_model",
            "tracked_hashkey",
            "src_ldts",
            "src_rsrc",
            "is_active_alias",
            "source_is_single_batch",
            "disable_hwm",
            "additional_columns",
        }
    ),
    "rec_track_sat": frozenset(
        {
            "tracked_hashkey",
            "source_models",
            "src_ldts",
            "src_rsrc",
            "src_stg",
            "disable_hwm",
            "additional_columns",
        }
    ),
    "ref_table": frozenset(
        {
            "ref_hub",
            "ref_satellites",
            "src_ldts",
            "src_rsrc",
            "historized",
            "snapshot_relation",
            "snapshot_trigger_column",
        }
    ),
    "pit": frozenset(
        {
            "tracked_entity",
            "hashkey",
            "sat_names",
            "snapshot_relation",
            "dimension_key",
            "snapshot_trigger_column",
            "ldts",
            "custom_rsrc",
            "ledts",
            "sdts",
            "pit_type",
            "refer_to_ghost_records",
            "snapshot_optimization",
            "mandatory_strategy",
        }
    ),
    "control_snap_v0": frozenset(
        {"start_date", "daily_snapshot_time", "sdts_alias", "end_date"}
    ),
    "control_snap_v1": frozenset({"control_snap_v0", "log_logic", "sdts_alias"}),
}

ENTITY_MACROS = frozenset(SIGNATURES)


@dataclass(frozen=True)
class ParameterNote:
    """Something to report about one parameter of a call."""

    severity: str  # "error" | "warning" | "info"
    code: str
    parameter: str | None
    message: str


@dataclass
class DvCall:
    """A datavault4dbt call with the parameters the macro ends up with."""

    macro: str
    params: dict[str, Any]
    notes: list[ParameterNote] = field(default_factory=list)

    def get(self, name: str, default: Any = None) -> Any:
        value = self.params.get(name)
        return default if value is None else value


def interpret(call: CapturedCall) -> DvCall:
    """Resolve ``yaml_metadata``, drop unknown parameters, note what to report."""
    from engine.services.imports.errors import Code

    notes: list[ParameterNote] = []
    known = SIGNATURES.get(call.macro, frozenset())

    if call.args:
        notes.append(
            ParameterNote(
                "warning",
                Code.DBT_PARAMETER_UNSUPPORTED,
                None,
                f"{len(call.args)} positional argument(s) to {call.macro}() are not read; "
                "pass parameters by name or in yaml_metadata",
            )
        )

    from_yaml: dict[str, Any] = {}
    metadata = call.kwargs.get("yaml_metadata")
    if isinstance(metadata, str) and metadata.strip():
        try:
            loaded = yaml.safe_load(metadata)
        except yaml.YAMLError as exc:
            loaded = None
            notes.append(
                ParameterNote(
                    "error",
                    Code.DBT_VALUE_INVALID,
                    "yaml_metadata",
                    f"yaml_metadata is not valid YAML: {str(exc)[:200]}",
                )
            )
        if isinstance(loaded, dict):
            from_yaml = {str(key): value for key, value in loaded.items()}
        elif loaded is not None:
            notes.append(
                ParameterNote(
                    "error",
                    Code.DBT_VALUE_INVALID,
                    "yaml_metadata",
                    f"yaml_metadata is a {type(loaded).__name__}, not a mapping",
                )
            )

    params: dict[str, Any] = dict(from_yaml)
    for key, value in call.kwargs.items():
        if key == "yaml_metadata":
            continue
        if key in from_yaml:
            if value is not None:
                notes.append(
                    ParameterNote(
                        "info",
                        Code.DBT_PARAMETER_GIVEN_TWICE,
                        key,
                        f"'{key}' is given in yaml_metadata and separately; "
                        "the yaml_metadata value applies",
                    )
                )
            continue
        if value is not None:
            params[key] = value

    for key in list(params):
        if key not in known:
            notes.append(
                ParameterNote(
                    "info",
                    Code.DBT_PARAMETER_IGNORED,
                    key,
                    f"{call.macro}() has no parameter '{key}': datavault4dbt ignores it",
                )
            )
            del params[key]
        elif _has_unresolved(params[key]):
            notes.append(
                ParameterNote(
                    "warning",
                    Code.DBT_VALUE_UNRESOLVED,
                    key,
                    f"'{key}' depends on a value the import can't know "
                    f"({_unresolved_names(params[key])})",
                )
            )
    return DvCall(macro=call.macro, params=params, notes=notes)


def _has_unresolved(value: Any) -> bool:
    if is_unresolved(value):
        return True
    if isinstance(value, dict):
        return any(_has_unresolved(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_unresolved(item) for item in value)
    return False


def _unresolved_names(value: Any) -> str:
    found: list[str] = []

    def walk(item: Any) -> None:
        if is_unresolved(item):
            found.append(item["__unresolved__"])
        elif isinstance(item, dict):
            for inner in item.values():
                walk(inner)
        elif isinstance(item, list):
            for inner in item:
                walk(inner)

    walk(value)
    return ", ".join(dict.fromkeys(found))


# ---------------------------------------------------------------------------
# Argument shapes
# ---------------------------------------------------------------------------


def as_list(value: Any) -> list[Any]:
    """A string or a list as a list (None: empty). Nested lists are flattened."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        result: list[Any] = []
        for item in value:
            result.extend(as_list(item) if isinstance(item, (list, tuple)) else [item])
        return result
    return [value]


def as_bool(value: Any, default: bool) -> bool:
    """A YAML/Jinja boolean, also when written as a string ('true')."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0"):
            return False
    return default


def normalize_source_models(
    value: Any, defaults: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """``source_models`` of a Hub, Link, record-tracking Satellite, ... as a list.

    Ports datavault4dbt's ``source_model_processing``: a name becomes one
    source; a mapping's keys are source names; per source, missing keys take
    the entity-level defaults (``hk_column`` / ``bk_columns`` for Hubs,
    ``link_hk`` / ``fk_columns`` / ``payload`` for Links). Column parameters
    become lists, and ``rsrc_static`` a list of patterns.
    """
    defaults = defaults or {}
    if value is None:
        sources: list[dict[str, Any]] = []
    elif isinstance(value, dict):
        sources = [
            {**(spec if isinstance(spec, dict) else {}), "name": name}
            for name, spec in value.items()
        ]
    elif isinstance(value, (list, tuple)):
        sources = [
            dict(item) if isinstance(item, dict) else {"name": item} for item in value
        ]
    else:
        sources = [{"name": value}]

    result = []
    for source in sources:
        normalized = dict(source)
        for key, default in defaults.items():
            if normalized.get(key) is None and default is not None:
                normalized[key] = default
        for key in ("bk_columns", "fk_columns", "payload", "ref_keys"):
            if key in normalized:
                normalized[key] = as_list(normalized[key])
        if normalized.get("rsrc_static") is not None:
            normalized["rsrc_static"] = as_list(normalized["rsrc_static"])
        if isinstance(normalized.get("name"), dict) and "__ref__" in normalized["name"]:
            normalized["name"] = normalized["name"]["__ref__"]
        normalized["name"] = str(normalized.get("name") or "")
        result.append(normalized)
    return result


def stage_source(value: Any) -> tuple[str, Any] | None:
    """What a stage reads: ('source', (source, table)) or ('model', name)."""
    if isinstance(value, dict) and "__source__" in value:
        source_name, table = value["__source__"]
        return "source", (str(source_name), str(table))
    if isinstance(value, dict) and "__ref__" in value:
        return "model", str(value["__ref__"])
    if isinstance(value, dict) and len(value) == 1:
        ((source_name, table),) = value.items()
        return "source", (str(source_name), str(table))
    if isinstance(value, str) and value:
        return "model", value
    return None


def normalize_hashed_columns(
    value: Any,
) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
    """``hashed_columns`` as (hash keys: name -> columns, hash diffs: name -> spec).

    A hash diff spec has ``columns`` (list) and ``exclude_columns`` (bool).
    """
    hashkeys: dict[str, list[str]] = {}
    hashdiffs: dict[str, dict[str, Any]] = {}
    for name, spec in (value or {}).items() if isinstance(value, dict) else []:
        if isinstance(spec, dict) and as_bool(spec.get("is_hashdiff"), False):
            hashdiffs[str(name)] = {
                "columns": [str(column) for column in as_list(spec.get("columns"))],
                "exclude_columns": as_bool(spec.get("exclude_columns"), False),
            }
        elif isinstance(spec, dict):
            hashkeys[str(name)] = [
                str(column) for column in as_list(spec.get("columns"))
            ]
        else:
            hashkeys[str(name)] = [str(column) for column in as_list(spec)]
    return hashkeys, hashdiffs


def normalize_derived_columns(value: Any) -> dict[str, dict[str, Any]]:
    """``derived_columns`` as name -> {value, datatype, src_cols_required}."""
    result: dict[str, dict[str, Any]] = {}
    for name, spec in (value or {}).items() if isinstance(value, dict) else []:
        if isinstance(spec, dict):
            result[str(name)] = {
                "value": spec.get("value"),
                "datatype": spec.get("datatype"),
                "src_cols_required": [
                    str(c) for c in as_list(spec.get("src_cols_required"))
                ],
            }
        else:
            result[str(name)] = {
                "value": spec,
                "datatype": None,
                "src_cols_required": [],
            }
    return result


def normalize_prejoins(value: Any) -> list[dict[str, Any]]:
    """``prejoined_columns`` in the list notation.

    Ports ``process_prejoined_columns``: the dictionary notation (one entry per
    extracted column: ``{alias: {src_name/src_table or ref_model, bk,
    this_column_name, ref_column_name, operator}}``) is grouped into list
    entries with ``extract_columns`` and ``aliases``.
    """
    if not value:
        return []
    if isinstance(value, list):
        entries = []
        for item in value:
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            entry["extract_columns"] = [
                str(c) for c in as_list(entry.get("extract_columns"))
            ]
            aliases = as_list(entry.get("aliases"))
            entry["aliases"] = [str(a) for a in aliases] or list(
                entry["extract_columns"]
            )
            entry["this_column_name"] = [
                str(c) for c in as_list(entry.get("this_column_name"))
            ]
            entry["ref_column_name"] = [
                str(c) for c in as_list(entry.get("ref_column_name"))
            ]
            entry.setdefault("operator", "AND")
            entries.append(entry)
        return entries
    if not isinstance(value, dict):
        return []
    grouped: list[dict[str, Any]] = []
    for alias, spec in value.items():
        if not isinstance(spec, dict):
            continue
        key = {
            "ref_model": spec.get("ref_model"),
            "src_name": spec.get("src_name"),
            "src_table": spec.get("src_table"),
            "this_column_name": [str(c) for c in as_list(spec.get("this_column_name"))],
            "ref_column_name": [str(c) for c in as_list(spec.get("ref_column_name"))],
            "operator": spec.get("operator") or "AND",
            "join_type": spec.get("join_type") or "left",
        }
        match = next(
            (
                entry
                for entry in grouped
                if all(entry.get(k) == v for k, v in key.items())
            ),
            None,
        )
        if match is None:
            match = {
                **{k: v for k, v in key.items() if v is not None},
                "extract_columns": [],
                "aliases": [],
            }
            grouped.append(match)
        match["extract_columns"].append(str(spec.get("bk")))
        match["aliases"].append(str(alias))
    return grouped


def normalize_hashdiff(value: Any) -> tuple[str | None, str | None]:
    """``src_hashdiff``: (stage column, alias in the Satellite or None)."""
    if isinstance(value, dict):
        source_column = value.get("source_column")
        alias = value.get("alias")
        return (
            str(source_column) if source_column else None,
            str(alias) if alias and alias != source_column else None,
        )
    if value:
        return str(value), None
    return None, None


def normalize_payload(value: Any) -> list[dict[str, str]]:
    """``src_payload`` / ``payload`` as [{column, alias}] (alias may equal column)."""
    result = []
    for item in as_list(value):
        if isinstance(item, dict):
            column = str(item.get("source_column") or item.get("name") or "")
            alias = str(item.get("alias") or column)
        else:
            column = alias = str(item)
        if column:
            result.append({"column": column, "alias": alias})
    return result


def normalize_sat_names(value: Any) -> list[str]:
    """PIT ``sat_names`` as v1 model names (per-satellite flags dropped)."""
    names = []
    for item in as_list(value):
        if isinstance(item, dict):
            name = item.get("name") or item.get("sat_name")
            if name:
                names.append(str(name))
        elif item:
            names.append(str(item))
    return names


def normalize_ref_satellites(value: Any) -> dict[str, dict[str, list[str]]]:
    """``ref_satellites`` as v1 name -> {include: [...], exclude: [...]}."""
    result: dict[str, dict[str, list[str]]] = {}
    if isinstance(value, dict):
        for name, spec in value.items():
            spec = spec if isinstance(spec, dict) else {}
            result[str(name)] = {
                "include": [str(c) for c in as_list(spec.get("include"))],
                "exclude": [str(c) for c in as_list(spec.get("exclude"))],
            }
    else:
        for name in as_list(value):
            result[str(name)] = {"include": [], "exclude": []}
    return result
