#!/usr/bin/env python3
"""Profile a dbt project's artifacts for the TurboVault dbt project import.

Usage:
    python scripts/dbt_import/profile_manifest.py PROJECT_DIR [PROJECT_DIR ...] --out DIR

Each PROJECT_DIR holds a ``manifest.json`` (required) and optionally a
``catalog.json``. For every project the profiler writes ``<out>/<name>.md``
(readable report) and ``<out>/<name>.json`` (raw findings) and prints a short
summary.

It answers what an importer has to handle:

- artifact versions and which node fields are present;
- every datavault4dbt call: the macro, how its metadata is written (a
  ``yaml_metadata`` block, YAML or JSON parsed into separate parameters,
  ``set`` variables, literals in the call) and which parameters it uses;
- naming patterns (hash keys, hash diffs, v0/v1 satellites, stages);
- folders, materializations, schemas, tags and other configs per macro;
- the models that call no datavault4dbt macro, by lineage: upstream of a
  stage, downstream of the Data Vault, or neither;
- what the stages read (sources, models, seeds, snapshots, other projects);
- catalog coverage.

This is an analysis aid: it classifies with patterns, not by rendering the
Jinja the way the importer will. Only the Python standard library and PyYAML
are needed. Artifacts are only read.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

PACKAGES = ("datavault4dbt", "datavault4dbt_premium_package", "automate_dv", "dbtvault")

# datavault4dbt macros that build a model, and what they build.
ENTITY_MACROS = {
    "stage": "stage",
    "hub": "hub",
    "ref_hub": "reference hub",
    "link": "link",
    "nh_link": "non-historized link",
    "sat_v0": "satellite v0",
    "sat_v1": "satellite v1",
    "ma_sat_v0": "multi-active satellite v0",
    "ma_sat_v1": "multi-active satellite v1",
    "nh_sat": "non-historized satellite",
    "ref_sat_v0": "reference satellite v0",
    "ref_sat_v1": "reference satellite v1",
    "eff_sat_v0": "effectivity satellite",
    "rec_track_sat": "record-tracking satellite",
    "ref_table": "reference table",
    "pit": "PIT",
    "control_snap_v0": "snapshot control v0",
    "control_snap_v1": "snapshot control v1",
}

_SET_BLOCK = re.compile(
    r"\{%-?\s*set\s+(\w+)\s*-?%\}(.*?)\{%-?\s*endset\s*-?%\}", re.DOTALL
)
_INLINE_SET = re.compile(r"\{%-?\s*set\s+(\w+)\s*=", re.DOTALL)
_JINJA_EXPR = re.compile(r"\{\{.*?\}\}", re.DOTALL)
_JINJA_STMT = re.compile(r"\{%.*?%\}", re.DOTALL)
_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
_VAR_CALL = re.compile(r"\bvar\(\s*['\"]([^'\"]+)['\"]")
_CALL_START = re.compile(r"\b(" + "|".join(PACKAGES) + r")\.(\w+)\s*\(")


# ---------------------------------------------------------------------------
# Small parsing helpers
# ---------------------------------------------------------------------------


def _balanced(text: str, open_index: int) -> str | None:
    """Text inside the parentheses that open at ``open_index``."""
    depth, quote = 0, None
    for index in range(open_index, len(text)):
        char = text[index]
        if quote:
            if char == quote and text[index - 1] != "\\":
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : index]
    return None


def _split_top_level(args: str) -> list[str]:
    parts, depth, quote, current = [], 0, None, []
    for index, char in enumerate(args):
        if quote:
            current.append(char)
            if char == quote and args[index - 1] != "\\":
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if "".join(current).strip():
        parts.append("".join(current).strip())
    return parts


def _jinja_free(text: str) -> str:
    """YAML/JSON text with Jinja replaced, so it can be loaded for its shape."""
    text = _JINJA_COMMENT.sub("", text)
    text = _JINJA_EXPR.sub("JINJA_EXPR", text)
    return "\n".join(line for line in text.splitlines() if not _JINJA_STMT.search(line))


def _load_block(text: str) -> tuple[str, Any]:
    """('yaml' | 'json' | 'unparsable', value) for a set block's content."""
    stripped = _jinja_free(text).strip()
    if not stripped:
        return "empty", None
    if stripped[0] in "{[":
        try:
            return "json", json.loads(stripped)
        except ValueError:
            pass
    try:
        return "yaml", yaml.safe_load(stripped)
    except yaml.YAMLError:
        return "unparsable", None


def _literal(value: str) -> Any:
    """A literal argument's value (best effort), else a marker."""
    candidate = value.strip()
    jinja_to_json = (
        candidate.replace("True", "true")
        .replace("False", "false")
        .replace("None", "null")
    )
    for loader in (json.loads, yaml.safe_load):
        try:
            loaded = loader(jinja_to_json)
        except Exception:  # noqa: BLE001 - best effort
            continue
        if isinstance(loaded, (dict, list, int, float, bool)) or (
            isinstance(loaded, str) and candidate[:1] in "'\""
        ):
            return loaded
    return "<expression>"


def _shape(value: Any) -> str:
    if isinstance(value, dict):
        return "dict(" + ",".join(sorted(map(str, value))[:8]) + ")"
    if isinstance(value, list):
        inner = {_shape(item).split("(")[0] for item in value}
        return "list[" + "|".join(sorted(inner)) + "]"
    return type(value).__name__


# ---------------------------------------------------------------------------
# Per-model analysis
# ---------------------------------------------------------------------------


def analyse_calls(raw_code: str) -> list[dict[str, Any]]:
    """Every package macro call in ``raw_code`` with its notation and params."""
    blocks = {name: _load_block(body) for name, body in _SET_BLOCK.findall(raw_code)}
    inline_sets = set(_INLINE_SET.findall(raw_code))
    uses_fromyaml = "fromyaml(" in raw_code
    uses_fromjson = "fromjson(" in raw_code

    calls = []
    for match in _CALL_START.finditer(raw_code):
        package, macro = match.group(1), match.group(2)
        args_text = _balanced(raw_code, match.end() - 1)
        if args_text is None:
            continue
        kwargs: dict[str, str] = {}
        positional = 0
        for part in _split_top_level(args_text):
            key, sep, value = part.partition("=")
            if sep and re.fullmatch(r"\s*\w+\s*", key) and not value.startswith("="):
                kwargs[key.strip()] = value.strip()
            else:
                positional += 1

        notations: list[str] = []
        params: dict[str, Any] = {}
        metadata_var = kwargs.get("yaml_metadata")
        if metadata_var is not None:
            block = blocks.get(metadata_var.strip())
            if block is None:
                notations.append("yaml_metadata (from expression)")
            else:
                kind, value = block
                notations.append(f"yaml_metadata block ({kind})")
                if isinstance(value, dict):
                    params.update(value)
        other_kwargs = {k: v for k, v in kwargs.items() if k != "yaml_metadata"}
        if other_kwargs:
            parsed_block = (uses_fromyaml or uses_fromjson) and any(
                re.search(r"\w+\s*(\[|\.get\(|\.)", value)
                for value in other_kwargs.values()
            )
            if parsed_block:
                notations.append(
                    "block parsed with "
                    + ("fromjson" if uses_fromjson else "fromyaml")
                    + ", parameters passed one by one"
                )
                for _kind, value in blocks.values():
                    if isinstance(value, dict):
                        params.update(value)
            literal_values = {
                k: _literal(v)
                for k, v in other_kwargs.items()
                if v.strip()[:1] in "'\"[{0123456789-"
                or v.strip() in ("true", "false", "True", "False", "none", "None")
            }
            variable_values = [
                k for k, v in other_kwargs.items() if v.strip() in inline_sets
            ]
            if literal_values:
                notations.append("literals in the call")
                params.update(literal_values)
            if variable_values:
                notations.append("set variables passed to the call")
            for key in other_kwargs:
                params.setdefault(key, "<expression>")
        if positional:
            notations.append(f"{positional} positional argument(s)")
        if not notations:
            notations.append("call without arguments")
        calls.append(
            {
                "package": package,
                "macro": macro,
                "notations": notations,
                "kwargs": sorted(kwargs),
                "params": params,
            }
        )
    return calls


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _name_pattern(name: str, other: str | None) -> str | None:
    """How ``other`` (a hash key, say) is formed from ``name``."""
    if not other:
        return None
    lower_name, lower_other = name.lower(), other.lower()
    if lower_name in lower_other:
        return lower_other.replace(lower_name, "{name}")
    for affix in (
        "_h",
        "_l",
        "_s",
        "_v0",
        "_v1",
        "hub_",
        "link_",
        "lnk_",
        "sat_",
        "h_",
        "l_",
        "s_",
    ):
        core = (
            lower_name.removesuffix(affix)
            if affix.startswith("_")
            else lower_name.removeprefix(affix)
        )
        if core != lower_name and core in lower_other:
            return (
                lower_other.replace(core, "{core}")
                + f"   (core = name without '{affix}')"
            )
    return "(unrelated) " + lower_other


def _affix_pattern(name: str) -> str:
    lower = name.lower()
    prefix = lower.split("_", 1)[0] + "_" if "_" in lower else ""
    suffix = "_" + lower.rsplit("_", 1)[-1] if "_" in lower else ""
    return f"prefix '{prefix}' / suffix '{suffix}'"


# ---------------------------------------------------------------------------
# Project analysis
# ---------------------------------------------------------------------------


def profile(project_dir: Path) -> dict[str, Any]:
    manifest = json.loads((project_dir / "manifest.json").read_text(encoding="utf-8"))
    catalog_path = project_dir / "catalog.json"
    catalog = (
        json.loads(catalog_path.read_text(encoding="utf-8"))
        if catalog_path.exists()
        else None
    )
    meta = manifest["metadata"]
    root = meta.get("project_name") or project_dir.name
    nodes = manifest["nodes"]
    parent_map: dict[str, list[str]] = manifest.get("parent_map") or {}
    child_map: dict[str, list[str]] = manifest.get("child_map") or {}

    result: dict[str, Any] = {
        "project": root,
        "artifacts": {
            "manifest_schema": meta.get("dbt_schema_version", "").rsplit("/", 1)[-1],
            "dbt_version": meta.get("dbt_version"),
            "adapter_type": meta.get("adapter_type"),
            "dbt_cloud": any(
                key.startswith("DBT_CLOUD") for key in (meta.get("env") or {})
            ),
            "metadata_keys": sorted(meta),
            "catalog": bool(catalog),
            "top_level_keys": sorted(manifest),
        },
    }

    resource_counts = Counter(
        (node["resource_type"], node.get("package_name")) for node in nodes.values()
    )
    result["node_counts"] = {
        f"{rtype} ({package})": count
        for (rtype, package), count in sorted(resource_counts.items())
    }
    result["sources"] = len(manifest.get("sources", {}))

    models = {
        uid: node
        for uid, node in nodes.items()
        if node["resource_type"] == "model" and node.get("package_name") == root
    }
    field_presence = Counter()
    for node in models.values():
        for field in (
            "raw_code",
            "unrendered_config",
            "original_file_path",
            "patch_path",
            "columns",
            "description",
        ):
            if node.get(field):
                field_presence[field] += 1
        if node.get("language") and node["language"] != "sql":
            field_presence["language=" + node["language"]] += 1
    result["model_fields_present"] = {
        "models": len(models),
        **dict(field_presence),
    }

    # --- package calls --------------------------------------------------
    dv_models: dict[str, dict[str, Any]] = {}
    notation_by_macro: dict[str, Counter] = defaultdict(Counter)
    params_by_macro: dict[str, Counter] = defaultdict(Counter)
    shapes_by_param: dict[str, Counter] = defaultdict(Counter)
    other_macros_in_dv: Counter = Counter()
    var_calls: Counter = Counter()
    multi_call_models = []
    for uid, node in models.items():
        raw = node.get("raw_code") or ""
        calls = [
            c
            for c in analyse_calls(raw)
            if c["macro"] in ENTITY_MACROS or c["package"] != "datavault4dbt"
        ]
        entity_calls = [c for c in calls if c["macro"] in ENTITY_MACROS]
        macros_used = node.get("depends_on", {}).get("macros", [])
        dv_dep = [m for m in macros_used if m.split(".")[1] in PACKAGES]
        if not entity_calls and not dv_dep:
            continue
        if len(entity_calls) > 1:
            multi_call_models.append(node["name"])
        call = entity_calls[0] if entity_calls else None
        macro = (
            call["macro"]
            if call
            else "(unparsed: "
            + ",".join(sorted({m.split(".")[-1] for m in dv_dep}))
            + ")"
        )
        key = f"{call['package']}.{macro}" if call else macro
        dv_models[uid] = {
            "name": node["name"],
            "macro": macro,
            "call": call,
            "node": node,
        }
        if call:
            for notation in call["notations"]:
                notation_by_macro[key][notation] += 1
            for param, value in call["params"].items():
                params_by_macro[key][param] += 1
                shapes_by_param[f"{key}.{param}"][_shape(value)] += 1
        for used in macros_used:
            package = used.split(".")[1]
            if package != "datavault4dbt":
                other_macros_in_dv[used] += 1
        for var_name in _VAR_CALL.findall(raw):
            var_calls[var_name] += 1

    result["dv_models"] = Counter(info["macro"] for info in dv_models.values())
    result["notations"] = {
        macro: dict(counter) for macro, counter in sorted(notation_by_macro.items())
    }
    result["params"] = {
        macro: dict(counter.most_common())
        for macro, counter in sorted(params_by_macro.items())
    }
    result["param_shapes"] = {
        param: dict(counter)
        for param, counter in sorted(shapes_by_param.items())
        if len(counter) > 1 or "source_model" in param
    }
    result["non_core_macros_in_dv_models"] = dict(other_macros_in_dv.most_common(25))
    result["var_calls"] = dict(var_calls.most_common())
    result["models_with_several_calls"] = multi_call_models[:20]

    # --- naming ------------------------------------------------------------
    naming: dict[str, Counter] = defaultdict(Counter)
    samples: dict[str, list[str]] = defaultdict(list)
    sat_v0_names = {
        info["name"]
        for info in dv_models.values()
        if info["macro"] in ("sat_v0", "ma_sat_v0", "ref_sat_v0")
    }
    for info in dv_models.values():
        name, macro, params = (
            info["name"],
            info["macro"],
            (info["call"] or {}).get("params", {}),
        )
        naming[f"{macro} model names"][_affix_pattern(name)] += 1
        if macro in ("hub", "ref_hub"):
            pattern = _name_pattern(name, _string(params.get("hashkey")))
            if pattern:
                naming["hub hashkey vs hub name"][pattern] += 1
        if macro in ("link", "nh_link"):
            pattern = _name_pattern(name, _string(params.get("link_hashkey")))
            if pattern:
                naming["link hashkey vs link name"][pattern] += 1
        if macro in ("sat_v0", "ma_sat_v0", "nh_sat"):
            pattern = _name_pattern(name, _string(params.get("src_hashdiff")))
            if pattern:
                naming["hashdiff vs satellite name"][pattern] += 1
        if macro in ("sat_v1", "ma_sat_v1", "ref_sat_v1"):
            v0 = _string(params.get("sat_v0") or params.get("ref_sat_v0"))
            if v0:
                naming["v1 name vs its v0 name"][_name_pattern(v0, name) or "?"] += 1
                if v0 not in sat_v0_names:
                    naming["v1 name vs its v0 name"]["(v0 not found in project)"] += 1
        if len(samples[macro]) < 4:
            samples[macro].append(name)
    result["naming"] = {
        key: dict(counter.most_common(6)) for key, counter in naming.items()
    }
    result["name_samples"] = dict(samples)

    # --- structure ---------------------------------------------------------
    structure: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    unrendered_keys: Counter = Counter()
    for info in dv_models.values():
        node, macro = info["node"], info["macro"]
        folder = str(Path(node.get("original_file_path", "")).parent)
        parts = folder.split("/")
        structure[macro]["folder (2 levels)"]["/".join(parts[:3])] += 1
        structure[macro]["materialized"][
            node.get("config", {}).get("materialized")
        ] += 1
        structure[macro]["schema"][node.get("schema")] += 1
        if node.get("alias") and node["alias"] != node["name"]:
            structure[macro]["alias differs"]["yes"] += 1
        for tag in node.get("tags", [])[:3]:
            structure[macro]["tags"][tag] += 1
        for key in node.get("unrendered_config") or {}:
            unrendered_keys[key] += 1
    result["structure"] = {
        macro: {
            aspect: dict(counter.most_common(5)) for aspect, counter in aspects.items()
        }
        for macro, aspects in sorted(structure.items())
    }
    result["unrendered_config_keys"] = dict(unrendered_keys.most_common())

    # --- lineage of models without a package call ---------------------------
    stage_ids = {uid for uid, info in dv_models.items() if info["macro"] == "stage"}
    vault_ids = set(dv_models) - stage_ids

    def walk(start: set[str], graph: dict[str, list[str]]) -> set[str]:
        seen, todo = set(), list(start)
        while todo:
            current = todo.pop()
            for nxt in graph.get(current, []):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        return seen

    upstream_of_stages = walk(stage_ids, parent_map)
    downstream_of_vault = walk(vault_ids | stage_ids, child_map)
    other_models = [uid for uid in models if uid not in dv_models]
    lineage = Counter()
    other_samples: dict[str, list[str]] = defaultdict(list)
    upstream_materialized = Counter()
    for uid in other_models:
        if uid in upstream_of_stages:
            kind = "upstream of a stage (pre-stage candidate)"
            upstream_materialized[nodes[uid].get("config", {}).get("materialized")] += 1
        elif uid in downstream_of_vault:
            kind = "downstream of the Data Vault (custom model candidate)"
        else:
            kind = "unrelated to the Data Vault"
        lineage[kind] += 1
        if len(other_samples[kind]) < 5:
            other_samples[kind].append(nodes[uid].get("original_file_path"))
    result["other_models"] = dict(lineage)
    result["other_model_samples"] = dict(other_samples)
    result["upstream_materialized"] = dict(upstream_materialized)

    stage_inputs = Counter()
    for uid in stage_ids:
        for parent in parent_map.get(uid, []):
            rtype, package = parent.split(".")[0], parent.split(".")[1]
            if rtype == "model":
                kind = (
                    "model ("
                    + ("this project" if package == root else "other project/package")
                    + ")"
                )
                if parent in dv_models:
                    kind += " with a datavault4dbt call"
            else:
                kind = rtype
            stage_inputs[kind] += 1
    result["stage_inputs"] = dict(stage_inputs)

    # --- catalog --------------------------------------------------------------
    if catalog:
        cat_nodes, cat_sources = catalog.get("nodes", {}), catalog.get("sources", {})
        types = Counter()
        for entry in list(cat_nodes.values()) + list(cat_sources.values()):
            for column in entry.get("columns", {}).values():
                types[re.sub(r"\(.*", "", str(column.get("type", "")).upper())] += 1
        result["catalog"] = {
            "sources with columns": f"{len(cat_sources)} of {result['sources']}",
            "models with columns": f"{sum(1 for k in cat_nodes if k.startswith('model.'))} of {len(models)}",
            "data types": dict(types.most_common(12)),
        }

    result["other_resources"] = {
        rtype: sum(1 for n in nodes.values() if n["resource_type"] == rtype)
        for rtype in (
            "seed",
            "snapshot",
            "test",
            "analysis",
            "operation",
            "sql_operation",
        )
        if any(n["resource_type"] == rtype for n in nodes.values())
    }
    result["disabled"] = len(manifest.get("disabled") or {})
    return result


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _section(lines: list[str], title: str, data: Any) -> None:
    lines.append(f"\n## {title}\n")
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                lines.append(f"- **{key}**")
                for inner_key, inner_value in value.items():
                    lines.append(f"  - {inner_key}: {inner_value}")
            else:
                lines.append(f"- {key}: {value}")
    else:
        lines.append(str(data))


def write_report(result: dict[str, Any], out: Path) -> None:
    name = result["project"]
    (out / f"{name}.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    lines = [f"# Profile: {name}"]
    for title, key in (
        ("Artifacts", "artifacts"),
        ("Node counts", "node_counts"),
        ("Model fields present", "model_fields_present"),
        ("Data Vault models by macro", "dv_models"),
        ("Notations per macro", "notations"),
        ("Parameters per macro", "params"),
        ("Parameter shapes that vary", "param_shapes"),
        ("Other macros used by Data Vault models", "non_core_macros_in_dv_models"),
        ("var() calls", "var_calls"),
        ("Naming", "naming"),
        ("Name samples", "name_samples"),
        ("Structure per macro", "structure"),
        ("unrendered_config keys", "unrendered_config_keys"),
        ("Models without a package call", "other_models"),
        ("Samples of those", "other_model_samples"),
        ("Materialization of pre-stage candidates", "upstream_materialized"),
        ("What the stages read", "stage_inputs"),
        ("Catalog", "catalog"),
        ("Other resources", "other_resources"),
    ):
        if key in result:
            _section(lines, title, result[key])
    (out / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("projects", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for project_dir in args.projects:
        result = profile(project_dir)
        write_report(result, args.out)
        print(
            f"{result['project']}: {sum(result['dv_models'].values())} Data Vault models, "
            f"{sum(result['other_models'].values())} others -> {args.out / (result['project'] + '.md')}"
        )


if __name__ == "__main__":
    main()
