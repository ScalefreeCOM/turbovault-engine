"""
The models of a dbt project, with the datavault4dbt call each one makes.

Every model of the root project is rendered once in the sandbox
(``extract.capture_model``). A model whose first Data Vault macro call is one
the import knows (``datavault4dbt.SIGNATURES``) becomes a ``DbtModel`` with
that call interpreted (``datavault4dbt.interpret``); the mapping works from
these. Models without a call are kept too: a stage may read them (pre-stages),
and the report lists the ones nothing maps.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from engine.services.imports.dbt.artifacts import DbtArtifacts
from engine.services.imports.dbt.datavault4dbt import (
    ENTITY_MACROS,
    DvCall,
    interpret,
)
from engine.services.imports.dbt.extract import (
    CAPTURED_PACKAGES,
    ModelCapture,
    capture_model,
)
from engine.services.imports.errors import Code, make_issue
from engine.services.imports.types import Issue, IssueLocation

# Data Vault macros of datavault4dbt the import doesn't map.
UNSUPPORTED_MACROS = frozenset({"xts"})

# Resource types a stage can read with ref().
_REFERABLE = frozenset({"model", "seed", "snapshot"})

_MACRO_DEFINITION = re.compile(r"\s*\{%-?\s*macro\b")


def _calls_package(sql: str) -> bool:
    return any(f"{package}." in sql for package in CAPTURED_PACKAGES)


def _wrapper_macros(macros: dict[str, str]) -> dict[str, str]:
    """The project's macros that call a Data Vault package (wrappers).

    Only macro definitions: generic tests, materializations and docs blocks
    aren't loaded into the sandbox.
    """
    return {
        name: sql
        for name, sql in macros.items()
        if _MACRO_DEFINITION.match(sql) and _calls_package(sql)
    }


@dataclass
class DbtModel:
    """A model of the root project and the Data Vault call it makes."""

    unique_id: str
    node: dict[str, Any]
    capture: ModelCapture | None = None
    call: DvCall | None = None

    @property
    def name(self) -> str:
        return str(self.node.get("name") or "")

    @property
    def path(self) -> str:
        return str(self.node.get("original_file_path") or self.node.get("path") or "")

    @property
    def macro(self) -> str | None:
        return self.call.macro if self.call else None

    @property
    def description(self) -> str | None:
        return str(self.node.get("description") or "").strip() or None

    def yaml_columns(self) -> dict[str, dict[str, Any]]:
        """The columns its YAML describes, by lowercased name."""
        return {
            str(name).lower(): column
            for name, column in (self.node.get("columns") or {}).items()
            if isinstance(column, dict)
        }

    def location(self, parameter: str | None = None) -> IssueLocation:
        return IssueLocation(
            file=self.path, node_id=self.unique_id, parameter=parameter
        )


class ProjectIndex:
    """The root project's models, sources and the nodes stages can read."""

    def __init__(self, artifacts: DbtArtifacts) -> None:
        self.artifacts = artifacts
        self.issues: list[Issue] = []
        self.models: dict[str, DbtModel] = {}
        self.by_name: dict[str, DbtModel] = {}
        # Nodes a ref() can name, by name: the root project's first.
        self._referable: dict[str, list[dict[str, Any]]] = {}
        root = artifacts.project_name
        for unique_id, node in artifacts.nodes.items():
            if node.get("resource_type") not in _REFERABLE:
                continue
            candidates = self._referable.setdefault(str(node.get("name") or ""), [])
            if node.get("package_name") == root:
                candidates.insert(0, {**node, "unique_id": unique_id})
            else:
                candidates.append({**node, "unique_id": unique_id})
        self._sources: dict[tuple[str, str], dict[str, Any]] = {}
        for unique_id, node in artifacts.sources.items():
            key = (str(node.get("source_name") or ""), str(node.get("name") or ""))
            # The root project's sources win over a package's of the same name
            if key not in self._sources or node.get("package_name") == root:
                self._sources[key] = {**node, "unique_id": unique_id}

    # -- capturing ------------------------------------------------------------

    def capture(self) -> None:
        """Render every model of the root project and interpret its call."""
        artifacts = self.artifacts
        project_vars = artifacts.project_vars
        wrappers = _wrapper_macros(artifacts.project_macros())
        for unique_id, node in sorted(artifacts.models().items()):
            model = DbtModel(unique_id=unique_id, node=node)
            self.models[unique_id] = model
            self.by_name.setdefault(model.name, model)
            if node.get("language", "sql") != "sql":
                continue
            raw_code = str(node.get("raw_code") or "")
            called = {
                name: sql
                for name, sql in wrappers.items()
                if re.search(rf"\b{re.escape(name)}\s*\(", raw_code)
            }
            if not called and not _calls_package(raw_code):
                continue  # no Data Vault call written in it: not rendered
            model.capture = capture_model(
                raw_code,
                project_vars=project_vars,
                adapter_type=artifacts.adapter_type,
                project_macros=called,
            )
            self._interpret(model)

    def _interpret(self, model: DbtModel) -> None:
        capture = model.capture
        assert capture is not None
        calls = capture.package_calls
        if capture.error and not calls:
            self._issue(
                model,
                "error",
                Code.DBT_MODEL_RENDER_FAILED,
                f"Model '{model.name}' can't be read: {capture.error}",
                suggestion=(
                    "Check that the model's Jinja parses with dbt; macros of "
                    "other packages and var() calls without a value are the "
                    "usual causes."
                ),
            )
            return
        entity_calls = [
            call
            for call in calls
            if call.package == "datavault4dbt" and call.macro in ENTITY_MACROS
        ]
        if not entity_calls:
            unsupported = [
                call
                for call in calls
                if call.package != "datavault4dbt" or call.macro in UNSUPPORTED_MACROS
            ]
            if unsupported:
                call = unsupported[0]
                self._issue(
                    model,
                    "error",
                    Code.DBT_MACRO_UNSUPPORTED,
                    f"Model '{model.name}' calls {call.package}.{call.macro}(), "
                    "which the import doesn't support: it stays in the dbt project",
                )
            return
        if len(entity_calls) > 1:
            self._issue(
                model,
                "warning",
                Code.DBT_PARAMETER_UNSUPPORTED,
                f"Model '{model.name}' makes {len(entity_calls)} Data Vault calls; "
                f"only the first, {entity_calls[0].macro}(), is imported",
            )
        model.call = interpret(entity_calls[0])
        for note in model.call.notes:
            self._issue(
                model,
                note.severity,
                note.code,
                f"{model.name}: {note.message}",
                parameter=note.parameter,
            )

    # -- lookups --------------------------------------------------------------

    def referable(self, name: str, package: str | None = None) -> dict[str, Any] | None:
        """The node ``ref(package, name)`` reads: a model, seed or snapshot."""
        candidates = self._referable.get(name) or []
        if package:
            candidates = [c for c in candidates if c.get("package_name") == package]
        return candidates[0] if candidates else None

    def source(self, source_name: str, table: str) -> dict[str, Any] | None:
        """The source table ``source(source_name, table)`` reads."""
        found = self._sources.get((source_name, table))
        if found is not None:
            return found
        lowered = (source_name.lower(), table.lower())
        return next(
            (
                node
                for (name, tbl), node in self._sources.items()
                if (name.lower(), tbl.lower()) == lowered
            ),
            None,
        )

    def upstream_sources(self, unique_id: str) -> list[dict[str, Any]]:
        """The source tables a node reads, directly or through other nodes.

        Nearest first (breadth-first along the parent map).
        """
        parent_map = self.artifacts.parent_map
        seen = {unique_id}
        queue = [unique_id]
        found: list[dict[str, Any]] = []
        while queue:
            current = queue.pop(0)
            for parent in parent_map.get(current) or []:
                if parent in seen:
                    continue
                seen.add(parent)
                if parent.startswith("source."):
                    node = self.artifacts.sources.get(parent)
                    if node is not None:
                        found.append({**node, "unique_id": parent})
                else:
                    queue.append(parent)
        return found

    def models_with(self, *macros: str) -> list[DbtModel]:
        """The models calling one of ``macros``, in a stable order."""
        return [
            model
            for model in self.models.values()
            if model.call is not None and model.call.macro in macros
        ]

    def target_database(self) -> str | None:
        """The database most models build into: the target's."""
        counts = Counter(
            node.get("database")
            for node in self.artifacts.models().values()
            if node.get("database")
        )
        return counts.most_common(1)[0][0] if counts else None

    @staticmethod
    def folder_of(node: dict[str, Any]) -> str:
        """The folder of a node's file, relative to the project."""
        path = str(node.get("original_file_path") or node.get("path") or "")
        return str(PurePosixPath(path).parent) if path else ""

    # -- issues ---------------------------------------------------------------

    def _issue(
        self,
        model: DbtModel,
        severity: str,
        code: str,
        message: str,
        *,
        parameter: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        self.issues.append(
            make_issue(
                severity=severity,  # type: ignore[arg-type]
                code=code,
                stage="parse",
                message=message,
                location=model.location(parameter),
                suggestion=suggestion,
            )
        )
