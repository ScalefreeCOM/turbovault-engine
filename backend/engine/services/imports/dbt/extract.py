"""
Capturing the package macro calls of a dbt model.

A model's ``raw_code`` is rendered in a sandboxed Jinja environment that
imitates dbt at parse time. Calls to Data Vault packages
(``datavault4dbt.hub(...)``, ...) don't run: they record their arguments. That
covers every way of writing the metadata with one mechanism:

- a ``yaml_metadata`` block passed as a whole;
- a YAML or JSON block parsed with ``fromyaml`` / ``fromjson`` and passed
  parameter by parameter (undefined keys of the block become "not set");
- ``set`` variables, loops, and literals in the call.

Other dbt functions are inert stand-ins: ``ref()`` and ``source()`` return
markers naming what they read, ``var()`` reads the project's vars, and an
unknown function or ``env_var()`` without a default gives an *unresolved*
marker instead of failing. Project macros that wrap a datavault4dbt call can
be loaded into the sandbox (``project_macros``).

Manifests are untrusted input: the sandbox blocks unsafe attribute access,
templates get no loader and no file, network or environment access, and YAML
is loaded with ``safe_load``.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from typing import Any

import yaml
from jinja2 import ChainableUndefined, Undefined
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment

# Packages whose macro calls are recorded.
CAPTURED_PACKAGES = (
    "datavault4dbt",
    "datavault4dbt_premium_package",
    "automate_dv",
    "dbtvault",
)


class _RenderFailedError(Exception):
    """The model raised a compiler error while rendering."""


# ---------------------------------------------------------------------------
# What a model reads
# ---------------------------------------------------------------------------


class Ref(str):
    """``ref('model')``: renders like the model's name, remembers it."""

    model: str
    package: str | None

    def __new__(cls, model: str, package: str | None = None) -> Ref:
        obj = super().__new__(cls, model)
        obj.model, obj.package = model, package
        return obj


class SourceRef(str):
    """``source('source', 'table')``."""

    source_name: str
    table: str

    def __new__(cls, source_name: str, table: str) -> SourceRef:
        obj = super().__new__(cls, f"{source_name}.{table}")
        obj.source_name, obj.table = source_name, table
        return obj


class Unresolved(str):
    """A value the import can't know: ``var('x')`` without a value, an
    ``env_var()``, a function it doesn't know."""

    what: str

    def __new__(cls, what: str) -> Unresolved:
        obj = super().__new__(cls, f"<unresolved: {what}>")
        obj.what = what
        return obj


# ---------------------------------------------------------------------------
# Captured output
# ---------------------------------------------------------------------------


@dataclass
class CapturedCall:
    """One package macro call, with its arguments as plain data.

    Refs become ``{"__ref__": model, "package": ...}``, sources
    ``{"__source__": [source, table]}``, unresolved values
    ``{"__unresolved__": what}``, undefined values None.
    """

    package: str
    macro: str
    args: list[Any]
    kwargs: dict[str, Any]


@dataclass
class ModelCapture:
    calls: list[CapturedCall] = field(default_factory=list)
    # The model's own config() arguments.
    config: dict[str, Any] = field(default_factory=dict)
    # Names whose value the import couldn't know (var, env_var, functions).
    unresolved: list[str] = field(default_factory=list)
    # Set when the model couldn't be rendered.
    error: str | None = None

    @property
    def package_calls(self) -> list[CapturedCall]:
        return [call for call in self.calls if call.package in CAPTURED_PACKAGES]


def _plain(value: Any) -> Any:
    if isinstance(value, Undefined):
        return None
    if isinstance(value, Ref):
        return {"__ref__": value.model, "package": value.package}
    if isinstance(value, SourceRef):
        return {"__source__": [value.source_name, value.table]}
    if isinstance(value, Unresolved):
        return {"__unresolved__": value.what}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    if isinstance(value, str):
        return str(value)
    return value


def is_unresolved(value: Any) -> bool:
    return isinstance(value, dict) and "__unresolved__" in value


def ref_name(value: Any) -> str | None:
    """The model a captured ``ref()`` names, else None."""
    if isinstance(value, dict) and "__ref__" in value:
        return str(value["__ref__"])
    return None


def source_pair(value: Any) -> tuple[str, str] | None:
    """(source, table) of a captured ``source()``, else None."""
    if isinstance(value, dict) and "__source__" in value:
        source_name, table = value["__source__"]
        return str(source_name), str(table)
    return None


# ---------------------------------------------------------------------------
# The sandbox
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.capture = ModelCapture()

    def record(self, package: str, macro: str, args: tuple, kwargs: dict) -> str:
        self.capture.calls.append(
            CapturedCall(
                package=package,
                macro=macro,
                args=[_plain(arg) for arg in args],
                kwargs={key: _plain(value) for key, value in kwargs.items()},
            )
        )
        return ""

    def unresolved(self, what: str) -> Unresolved:
        if what not in self.capture.unresolved:
            self.capture.unresolved.append(what)
        return Unresolved(what)


class _Namespace:
    """A package: every macro call is recorded and renders as nothing."""

    def __init__(self, package: str, recorder: _Recorder) -> None:
        self._package = package
        self._recorder = recorder

    def __getattr__(self, macro: str):
        def call(*args: Any, **kwargs: Any) -> str:
            return self._recorder.record(self._package, macro, args, kwargs)

        return call


class _Inert:
    """``adapter``, ``this``, ``target``, ``flags``: attributes as given,
    method calls do nothing."""

    def __init__(self, label: str, **attrs: Any) -> None:
        self._label = label
        self.__dict__.update(attrs)

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None

    def __str__(self) -> str:
        return self._label


def _undefined_class(recorder: _Recorder) -> type[Undefined]:
    """Undefined names that can be called: unknown functions give a marker."""

    class LenientUndefined(ChainableUndefined):
        def __call__(self, *args: Any, **kwargs: Any) -> Unresolved:  # type: ignore[override]
            return recorder.unresolved(f"{self._undefined_name}()")

    return LenientUndefined


def _context(
    recorder: _Recorder, project_vars: dict[str, Any], adapter_type: str
) -> dict[str, Any]:
    def config(*args: Any, **kwargs: Any) -> str:
        recorder.capture.config.update(
            {key: _plain(value) for key, value in kwargs.items()}
        )
        return ""

    config.get = lambda key, default=None: recorder.capture.config.get(key, default)  # type: ignore[attr-defined]

    def ref(*args: Any, **kwargs: Any) -> Ref:
        if len(args) >= 2:
            return Ref(str(args[1]), package=str(args[0]))
        return Ref(str(args[0]) if args else "")

    def var(name: str, default: Any = None) -> Any:
        if name in project_vars:
            return project_vars[name]
        if default is not None:
            return default
        return recorder.unresolved(f"var('{name}')")

    def env_var(name: str, default: Any = None) -> Any:
        # Never the real environment: the manifest is untrusted input.
        if default is not None:
            return default
        return recorder.unresolved(f"env_var('{name}')")

    def raise_compiler_error(message: str = "") -> None:
        raise _RenderFailedError(f"the model raises a compiler error: {message}")

    context: dict[str, Any] = {
        "config": config,
        "ref": ref,
        "source": lambda source_name, table: SourceRef(str(source_name), str(table)),
        "var": var,
        "env_var": env_var,
        "fromyaml": lambda text, default=None: (
            yaml.safe_load(text) if text else default
        ),
        "toyaml": lambda value, *args, **kwargs: yaml.safe_dump(value),
        "fromjson": lambda text, default=None: json.loads(text) if text else default,
        "tojson": lambda value, *args, **kwargs: json.dumps(value),
        "is_incremental": lambda: False,
        "should_full_refresh": lambda: False,
        "execute": False,
        "flags": _Inert("flags", FULL_REFRESH=False, WHICH="parse"),
        "this": _Inert("this", database="", schema="", identifier="this", name="this"),
        "target": _Inert(
            "target", name="import", schema="", database="", type=adapter_type
        ),
        "adapter": _Inert("adapter"),
        "exceptions": _Inert(
            "exceptions",
            raise_compiler_error=raise_compiler_error,
            warn=lambda *args, **kwargs: "",
        ),
        "log": lambda *args, **kwargs: "",
        "print": lambda *args, **kwargs: "",
        "run_query": lambda *args, **kwargs: None,
        "modules": {"datetime": datetime},
        "zip": zip,
        "set": set,
        "return": lambda value=None: value,
    }
    for package in CAPTURED_PACKAGES:
        context[package] = _Namespace(package, recorder)
    return context


def capture_model(
    raw_code: str,
    *,
    project_vars: dict[str, Any] | None = None,
    adapter_type: str = "",
    project_macros: dict[str, str] | None = None,
) -> ModelCapture:
    """Render ``raw_code`` in the sandbox and return what it called.

    ``project_macros`` (name -> SQL) are defined before the model, so a
    project macro wrapping a datavault4dbt call is followed into the call.
    """
    recorder = _Recorder()
    environment = SandboxedEnvironment(
        undefined=_undefined_class(recorder),
        extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"],
    )
    source = raw_code or ""
    if project_macros:
        source = "\n".join(project_macros.values()) + "\n" + source
    try:
        environment.from_string(source).render(
            _context(recorder, project_vars or {}, adapter_type)
        )
    except (
        TemplateError,
        _RenderFailedError,
        yaml.YAMLError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        recorder.capture.error = f"{type(exc).__name__}: {exc}"[:500]
    except RecursionError:
        recorder.capture.error = "the model's Jinja recurses too deeply"
    return recorder.capture
