"""
Reading a dbt project's artifacts.

The dbt import reads files only; it never runs dbt or connects to a warehouse:

- ``manifest.json`` (required): models, sources, seeds, snapshots, project
  macros and lineage. Only schema **v12** is accepted (dbt Core 1.8 and later,
  dbt Cloud, dbt Fusion).
- ``catalog.json`` (optional): the column data types the warehouse reports.
- ``dbt_project.yml`` (optional): ``vars`` (the manifest has none) and the
  project's folder settings.
- ``packages.yml`` / ``dependencies.yml`` / ``package-lock.yml`` (optional):
  the project's packages (a suggested project setting) and the datavault4dbt
  version, for the report.

``profiles.yml`` is never read: it holds credentials.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.services.imports.errors import Code, PipelineAbort, make_issue
from engine.services.imports.types import IssueLocation

SUPPORTED_MANIFEST_VERSION = "v12"
# Artifacts bigger than this are refused before parsing (bytes).
MAX_ARTIFACT_SIZE = 512 * 1024 * 1024

_DV_PACKAGE_NAMES = ("datavault4dbt", "datavault4dbt_premium_package")


@dataclass(frozen=True)
class DbtArtifactPaths:
    """Where the artifacts of one dbt project are."""

    manifest: Path
    catalog: Path | None = None
    dbt_project: Path | None = None
    packages: tuple[Path, ...] = ()

    @classmethod
    def locate(
        cls,
        path: Path,
        *,
        catalog: Path | None = None,
        dbt_project: Path | None = None,
        packages: Path | None = None,
    ) -> DbtArtifactPaths:
        """Find the artifacts from a manifest file or a project directory.

        A directory may be the dbt project (``target/manifest.json``,
        ``dbt_project.yml``) or a folder holding the artifacts directly. A
        manifest file finds the catalog beside it, and the project files in
        its folder, or one level up when it sits in ``target/``. Paths given
        explicitly win over the ones found. The manifest path is where it was
        looked for: it may not exist.
        """
        path = Path(path)
        if path.is_dir():
            manifest = _first_file(
                path / "target" / "manifest.json", path / "manifest.json"
            ) or (path / "target" / "manifest.json")
            artifact_dirs = (path / "target", path)
            project_dir = path
        else:
            manifest = path
            artifact_dirs = (path.parent,)
            project_dir = (
                path.parent.parent if path.parent.name == "target" else path.parent
            )
        found_catalog = _first_file(*(d / "catalog.json" for d in artifact_dirs))
        found_project = _first_file(project_dir / "dbt_project.yml")
        found_packages = tuple(
            candidate
            for candidate in (
                project_dir / "packages.yml",
                project_dir / "dependencies.yml",
                project_dir / "package-lock.yml",
            )
            if candidate.is_file()
        )
        return cls(
            manifest=manifest,
            catalog=catalog or found_catalog,
            dbt_project=dbt_project or found_project,
            packages=(packages,) if packages else found_packages,
        )


def _first_file(*candidates: Path) -> Path | None:
    """The first candidate that is a file, or None."""
    return next((c for c in candidates if c.is_file()), None)


@dataclass
class DbtArtifacts:
    """The parts of a dbt project's artifacts the import uses."""

    manifest: dict[str, Any]
    catalog: dict[str, Any] | None = None
    dbt_project: dict[str, Any] | None = None
    packages: list[dict[str, Any]] = field(default_factory=list)
    paths: DbtArtifactPaths | None = None

    # -- metadata -------------------------------------------------------------

    @property
    def metadata(self) -> dict[str, Any]:
        return self.manifest.get("metadata") or {}

    @property
    def project_name(self) -> str:
        """The root project, whose models are imported."""
        name = self.metadata.get("project_name")
        if name:
            return str(name)
        if self.dbt_project and self.dbt_project.get("name"):
            return str(self.dbt_project["name"])
        # Older manifests: the package that owns most models.
        packages = [
            node.get("package_name")
            for node in self.manifest.get("nodes", {}).values()
            if node.get("resource_type") == "model"
        ]
        return max(set(packages), key=packages.count) if packages else ""

    @property
    def adapter_type(self) -> str:
        return str(self.metadata.get("adapter_type") or "")

    @property
    def dbt_version(self) -> str:
        return str(self.metadata.get("dbt_version") or "")

    @property
    def project_vars(self) -> dict[str, Any]:
        """``vars`` of ``dbt_project.yml``: global ones and the root project's."""
        raw = (self.dbt_project or {}).get("vars") or {}
        if not isinstance(raw, dict):
            return {}
        merged = {
            key: value for key, value in raw.items() if not isinstance(value, dict)
        }
        # Package-scoped vars (`vars: {my_project: {...}}`) apply to that package.
        for scope in (self.project_name, *_DV_PACKAGE_NAMES):
            scoped = raw.get(scope)
            if isinstance(scoped, dict):
                merged.update(scoped)
        # datavault4dbt's own settings are written as 'datavault4dbt.x' keys.
        merged.update(
            {
                key: value
                for key, value in raw.items()
                if "." in str(key) and not isinstance(value, dict)
            }
        )
        return merged

    @property
    def datavault4dbt_version(self) -> str | None:
        """The datavault4dbt version from the package files, if they name one."""
        for document in self.packages:
            for package in document.get("packages") or []:
                if not isinstance(package, dict):
                    continue
                name = str(package.get("package") or package.get("git") or "")
                if "datavault4dbt" in name.lower() and "premium" not in name.lower():
                    version = package.get("version") or package.get("revision")
                    if isinstance(version, list):
                        version = " ".join(map(str, version))
                    return str(version) if version is not None else None
        return None

    @property
    def package_entries(self) -> list[dict[str, Any]]:
        """The project's packages, as its package files list them (spec D28).

        ``packages.yml`` or ``dependencies.yml``; without them the pinned
        versions of ``package-lock.yml``.
        """
        names = [path.name for path in self.paths.packages] if self.paths else []
        documents = list(
            zip(names or [""] * len(self.packages), self.packages, strict=False)
        )
        for lock in (False, True):
            for name, document in documents:
                if (name == "package-lock.yml") != lock or not isinstance(
                    document, dict
                ):
                    continue
                entries = [
                    dict(entry)
                    for entry in document.get("packages") or []
                    if isinstance(entry, dict)
                ]
                if entries:
                    # The lock file names each package; packages.yml doesn't
                    return [
                        (
                            {
                                key: value
                                for key, value in entry.items()
                                if key != "name"
                            }
                            if lock
                            else entry
                        )
                        for entry in entries
                    ]
        return []

    # -- nodes ----------------------------------------------------------------

    @property
    def nodes(self) -> dict[str, dict[str, Any]]:
        return self.manifest.get("nodes") or {}

    @property
    def sources(self) -> dict[str, dict[str, Any]]:
        return self.manifest.get("sources") or {}

    @property
    def parent_map(self) -> dict[str, list[str]]:
        return self.manifest.get("parent_map") or {}

    @property
    def child_map(self) -> dict[str, list[str]]:
        return self.manifest.get("child_map") or {}

    def models(self) -> dict[str, dict[str, Any]]:
        """The root project's models (SQL and Python), by unique id."""
        return {
            unique_id: node
            for unique_id, node in self.nodes.items()
            if node.get("resource_type") == "model"
            and node.get("package_name") == self.project_name
        }

    def project_macros(self) -> dict[str, str]:
        """The root project's macros: name -> SQL (for wrapper macros)."""
        return {
            macro["name"]: macro.get("macro_sql") or ""
            for macro in (self.manifest.get("macros") or {}).values()
            if macro.get("package_name") == self.project_name and macro.get("name")
        }

    def node(self, unique_id: str) -> dict[str, Any] | None:
        return self.nodes.get(unique_id) or self.sources.get(unique_id)

    def resource_counts(self) -> dict[str, int]:
        """Nodes per resource type (all packages), for the report."""
        counts: dict[str, int] = {}
        for node in self.nodes.values():
            resource_type = node.get("resource_type", "unknown")
            counts[resource_type] = counts.get(resource_type, 0) + 1
        if self.sources:
            counts["source"] = len(self.sources)
        return counts

    # -- catalog --------------------------------------------------------------

    def catalog_columns(self, unique_id: str) -> dict[str, str] | None:
        """Column name -> data type of a node or source, as the catalog has it.

        None when there is no catalog or it doesn't know the node. Names keep
        the catalog's spelling; ordered by the column index.
        """
        if not self.catalog:
            return None
        entry = (self.catalog.get("nodes") or {}).get(unique_id) or (
            self.catalog.get("sources") or {}
        ).get(unique_id)
        if not entry:
            return None
        columns = sorted(
            (entry.get("columns") or {}).values(),
            key=lambda column: column.get("index") or 0,
        )
        return {
            str(column.get("name")): str(column.get("type") or "") for column in columns
        }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _abort(
    code: str, message: str, path: Path | None, suggestion: str | None = None
) -> PipelineAbort:
    return PipelineAbort(
        make_issue(
            severity="error",
            code=code,
            stage="parse",
            message=message,
            location=IssueLocation(file=str(path)) if path else None,
            suggestion=suggestion,
        )
    )


def _read_json(path: Path, what: str) -> dict[str, Any]:
    if not path.is_file():
        raise _abort(Code.SOURCE_UNREADABLE, f"{what} not found: {path}", path)
    if path.stat().st_size > MAX_ARTIFACT_SIZE:
        raise _abort(
            Code.DBT_ARTIFACT_TOO_LARGE,
            f"{what} is larger than {MAX_ARTIFACT_SIZE // (1024 * 1024)} MB: {path}",
            path,
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise _abort(
            Code.SOURCE_UNREADABLE, f"Could not read {what}: {exc}", path
        ) from exc
    except json.JSONDecodeError as exc:
        raise _abort(
            Code.SOURCE_INVALID_JSON, f"{what} is not valid JSON: {exc}", path
        ) from exc
    if not isinstance(data, dict):
        raise _abort(Code.SOURCE_INVALID_JSON, f"{what} is not a JSON object", path)
    return data


def _read_yaml(path: Path, what: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise _abort(
            Code.SOURCE_UNREADABLE, f"Could not read {what}: {exc}", path
        ) from exc
    return data if isinstance(data, dict) else {}


_SCHEMA_VERSION = re.compile(r"/manifest/(v\d+)\.json$")


def manifest_schema_version(manifest: dict[str, Any]) -> str | None:
    """'v12' for a manifest of schema v12, else what it says (or None)."""
    url = str((manifest.get("metadata") or {}).get("dbt_schema_version") or "")
    match = _SCHEMA_VERSION.search(url)
    return match.group(1) if match else None


def is_dbt_manifest(path: Path) -> bool:
    """Whether ``path`` is a dbt manifest, read from its first kilobytes.

    Used to tell a manifest from a TurboVault JSON export without loading the
    whole file.
    """
    try:
        with Path(path).open(encoding="utf-8") as handle:
            head = handle.read(8192)
    except (OSError, UnicodeDecodeError):
        return False
    return '"dbt_schema_version"' in head and "/manifest/" in head


def load_artifacts(paths: DbtArtifactPaths) -> DbtArtifacts:
    """Read and check the artifacts. Raises ``PipelineAbort`` when unusable."""
    manifest = _read_json(paths.manifest, "manifest.json")
    version = manifest_schema_version(manifest)
    if version != SUPPORTED_MANIFEST_VERSION:
        raise _abort(
            Code.DBT_UNSUPPORTED_MANIFEST_VERSION,
            f"manifest.json has schema {version or 'unknown'}; the import reads "
            f"schema {SUPPORTED_MANIFEST_VERSION} (dbt 1.8 or later, dbt Cloud, dbt Fusion)",
            paths.manifest,
            suggestion="Regenerate the manifest with a current dbt version (dbt parse).",
        )
    catalog = _read_json(paths.catalog, "catalog.json") if paths.catalog else None
    dbt_project = (
        _read_yaml(paths.dbt_project, "dbt_project.yml") if paths.dbt_project else None
    )
    packages = [_read_yaml(path, path.name) for path in paths.packages]
    return DbtArtifacts(
        manifest=manifest,
        catalog=catalog,
        dbt_project=dbt_project,
        packages=packages,
        paths=paths,
    )
