#!/usr/bin/env python3
"""Prototype: capture the datavault4dbt calls of a dbt project's models.

Usage:
    python scripts/dbt_import/capture_calls.py PROJECT_DIR --out FILE.json [--vars dbt_project.yml]

Renders every model's ``raw_code`` (from ``PROJECT_DIR/manifest.json``) in a
sandboxed Jinja environment that imitates dbt at parse time. Calls to package
macros (``datavault4dbt.hub(...)``, ...) only record their arguments. The
``yaml_metadata`` argument is resolved the way datavault4dbt's
``yaml_metadata_parser`` does it: a parameter in the YAML wins over one passed
separately, and a separate parameter (or ``false``) applies otherwise.

This covers every way of writing the metadata with one mechanism: a
``yaml_metadata`` block passed as a whole, a YAML or JSON block parsed with
``fromyaml`` / ``fromjson`` and passed parameter by parameter, ``set``
variables, and literals in the call.

Prototype for the importer (see the dbt import spec); not used by the engine.
Manifests are untrusted: the sandbox gives templates no file, network or
environment access, and ``env_var`` never reads the real environment.
"""

from __future__ import annotations

import argparse
import datetime
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from jinja2 import ChainableUndefined, Undefined
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment

DV_PACKAGES = (
    "datavault4dbt",
    "datavault4dbt_premium_package",
    "automate_dv",
    "dbtvault",
)


class CaptureError(Exception):
    """A model raised a compiler error, or could not be rendered."""


# ---------------------------------------------------------------------------
# Placeholders for what a model reads
# ---------------------------------------------------------------------------


class Ref(str):
    """``ref('model')``: renders like the relation, remembers what it is."""

    def __new__(cls, name: str, package: str | None = None) -> Ref:
        obj = super().__new__(cls, name)
        obj.ref_name, obj.package = name, package
        return obj


class Source(str):
    def __new__(cls, source_name: str, table: str) -> Source:
        obj = super().__new__(cls, f"{source_name}.{table}")
        obj.source_name, obj.table = source_name, table
        return obj


class Unresolved(str):
    """A value the import can't know, e.g. ``var('x')`` without a value."""

    def __new__(cls, what: str) -> Unresolved:
        obj = super().__new__(cls, f"<unresolved {what}>")
        obj.what = what
        return obj


class _Namespace:
    """``datavault4dbt`` and other packages: calls are recorded, not run."""

    def __init__(self, package: str, recorder: Recorder) -> None:
        self._package, self._recorder = package, recorder

    def __getattr__(self, macro: str):
        def call(*args: Any, **kwargs: Any) -> str:
            self._recorder.record(self._package, macro, args, kwargs)
            return ""

        return call


class _Stub:
    """``adapter``, ``this``, ``target``, ``exceptions``: inert objects."""

    def __init__(self, label: str, **attrs: Any) -> None:
        self._label = label
        self.__dict__.update(attrs)

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None

    def __str__(self) -> str:
        return self._label


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.config: dict[str, Any] = {}
        self.unresolved: list[str] = []

    def record(self, package: str, macro: str, args: tuple, kwargs: dict) -> None:
        self.calls.append(
            {
                "package": package,
                "macro": macro,
                "args": [_plain(arg) for arg in args],
                "kwargs": {key: _plain(value) for key, value in kwargs.items()},
            }
        )


def _plain(value: Any) -> Any:
    """Rendered values as plain data: Undefined -> None, markers -> dicts."""
    if isinstance(value, Undefined):
        return None
    if isinstance(value, Ref):
        return {"__ref__": value.ref_name, "package": value.package}
    if isinstance(value, Source):
        return {"__source__": [value.source_name, value.table]}
    if isinstance(value, Unresolved):
        return {"__unresolved__": value.what}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, str):
        return str(value)
    return value


# ---------------------------------------------------------------------------
# The dbt-like context
# ---------------------------------------------------------------------------


def _context(
    recorder: Recorder, project_vars: dict[str, Any], adapter_type: str
) -> dict:
    def config(*args: Any, **kwargs: Any) -> str:
        recorder.config.update(kwargs)
        return ""

    config.get = lambda key, default=None: recorder.config.get(key, default)  # type: ignore[attr-defined]

    def ref(*args: Any, **kwargs: Any) -> Ref:
        if len(args) >= 2:
            return Ref(str(args[1]), package=str(args[0]))
        return Ref(str(args[0]))

    def var(name: str, default: Any = None) -> Any:
        if name in project_vars:
            return project_vars[name]
        if default is not None:
            return default
        recorder.unresolved.append(f"var('{name}')")
        return Unresolved(f"var('{name}')")

    def env_var(name: str, default: Any = None) -> Any:
        # Never the real environment: the manifest is untrusted input.
        if default is not None:
            return default
        recorder.unresolved.append(f"env_var('{name}')")
        return Unresolved(f"env_var('{name}')")

    def raise_compiler_error(message: str = "") -> None:
        raise CaptureError(f"raise_compiler_error: {message}")

    context: dict[str, Any] = {
        "config": config,
        "ref": ref,
        "source": lambda source_name, table: Source(str(source_name), str(table)),
        "var": var,
        "env_var": env_var,
        "fromyaml": lambda text, default=None: (
            yaml.safe_load(text) if text else default
        ),
        "toyaml": lambda value, *a, **k: yaml.safe_dump(value),
        "fromjson": lambda text, default=None: json.loads(text) if text else default,
        "tojson": lambda value, *a, **k: json.dumps(value),
        "is_incremental": lambda: False,
        "execute": False,
        "flags": _Stub("flags", FULL_REFRESH=False, WHICH="parse"),
        "this": _Stub("this", database="", schema="", identifier="this", name="this"),
        "target": _Stub(
            "target", name="import", schema="", database="", type=adapter_type
        ),
        "adapter": _Stub("adapter"),
        "exceptions": _Stub(
            "exceptions",
            raise_compiler_error=raise_compiler_error,
            warn=lambda *a, **k: "",
        ),
        "log": lambda *args, **kwargs: "",
        "print": lambda *args, **kwargs: "",
        "run_query": lambda *args, **kwargs: None,
        "modules": {"datetime": datetime},
        "zip": zip,
        "set": set,
        "return": lambda value=None: value,
    }
    for package in DV_PACKAGES:
        context[package] = _Namespace(package, recorder)
    return context


def build_environment() -> SandboxedEnvironment:
    return SandboxedEnvironment(
        undefined=ChainableUndefined,
        extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"],
    )


# ---------------------------------------------------------------------------
# Resolving yaml_metadata like datavault4dbt
# ---------------------------------------------------------------------------


def resolve_params(kwargs: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The parameters a datavault4dbt macro ends up with, and notes.

    A parameter in ``yaml_metadata`` wins; a separate one applies otherwise
    (``false`` counts, None doesn't), as in ``yaml_metadata_parser``.
    """
    notes: list[str] = []
    separate = {key: value for key, value in kwargs.items() if key != "yaml_metadata"}
    metadata_text = kwargs.get("yaml_metadata")
    from_yaml: dict[str, Any] = {}
    if isinstance(metadata_text, str) and metadata_text.strip():
        loaded = yaml.safe_load(metadata_text)
        if isinstance(loaded, dict):
            from_yaml = loaded
        else:
            notes.append(f"yaml_metadata is not a mapping ({type(loaded).__name__})")
    params = dict(from_yaml)
    for key, value in separate.items():
        if key in from_yaml:
            if value is not None:
                notes.append(f"'{key}' given twice; the yaml_metadata value wins")
            continue
        if value is not None:
            params[key] = value
    return params, notes


def capture_model(
    raw_code: str, project_vars: dict[str, Any], adapter_type: str
) -> dict[str, Any]:
    recorder = Recorder()
    environment = build_environment()
    try:
        environment.from_string(raw_code).render(
            _context(recorder, project_vars, adapter_type)
        )
    except (TemplateError, CaptureError, yaml.YAMLError, ValueError, TypeError) as exc:
        return {
            "error": f"{type(exc).__name__}: {exc}"[:300],
            "config": recorder.config,
        }
    calls = []
    for call in recorder.calls:
        if call["package"] in DV_PACKAGES:
            try:
                params, notes = resolve_params(call["kwargs"])
            except yaml.YAMLError as exc:
                params, notes = {}, [f"yaml_metadata is not valid YAML: {exc}"[:200]]
            call = {**call, "params": params, "notes": notes}
        calls.append(call)
    return {
        "calls": calls,
        "config": recorder.config,
        "unresolved": recorder.unresolved,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--vars", type=Path, help="dbt_project.yml, for var() values")
    args = parser.parse_args()

    manifest = json.loads((args.project / "manifest.json").read_text(encoding="utf-8"))
    root = manifest["metadata"].get("project_name")
    adapter_type = manifest["metadata"].get("adapter_type") or ""
    project_vars: dict[str, Any] = {}
    if args.vars and args.vars.exists():
        project_vars = (
            yaml.safe_load(args.vars.read_text(encoding="utf-8")) or {}
        ).get("vars") or {}

    results = {}
    outcome = Counter()
    for unique_id, node in manifest["nodes"].items():
        if node["resource_type"] != "model" or node.get("package_name") != root:
            continue
        if node.get("language", "sql") != "sql":
            results[unique_id] = {"error": f"language {node['language']}"}
            outcome["skipped: not SQL"] += 1
            continue
        captured = capture_model(node.get("raw_code") or "", project_vars, adapter_type)
        captured["name"] = node["name"]
        captured["path"] = node.get("original_file_path")
        results[unique_id] = captured
        if "error" in captured:
            outcome["render error"] += 1
        elif any(call["package"] in DV_PACKAGES for call in captured["calls"]):
            outcome["datavault4dbt call captured"] += 1
        else:
            outcome["no package call"] += 1
    args.out.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"{root}: {dict(outcome)}")


if __name__ == "__main__":
    main()
