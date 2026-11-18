"""
The folder a dbt project is generated into (spec D17, §9.7).

Generating into an empty folder writes a complete dbt project. A folder with
a ``dbt_project.yml`` TurboVault didn't write is an existing dbt project
(e.g. the one a project was imported from, whose pre-stage models stay
there): TurboVault writes its models and sources into it but keeps the
project's ``dbt_project.yml`` and ``packages.yml``, and reports what its
models need from them. Its models then get their layer's settings from their
own ``config()`` wherever the project's folders don't give them.

TurboVault records the files it writes (``.turbovault/generated.json``,
paths and checksums). The record tells its own ``dbt_project.yml`` from a
project's, and the files it no longer generates: reported, and deleted only
on request and only while unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RECORD = ".turbovault/generated.json"
PROJECT_FILES = ("dbt_project.yml", "packages.yml")


def checksum(content: str | bytes) -> str:
    data = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(data).hexdigest()


def read_record(root: Path) -> dict[str, str]:
    """The files TurboVault wrote into ``root`` last time: path -> checksum."""
    path = root / RECORD
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = data.get("files") if isinstance(data, dict) else None
    return {str(k): str(v) for k, v in files.items()} if isinstance(files, dict) else {}


def project_files_kept(root: Path) -> bool:
    """Whether the last generation into ``root`` kept the dbt project's own
    ``dbt_project.yml`` and ``packages.yml`` (recorded, so the CLI doesn't
    ask again)."""
    try:
        data = json.loads((root / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("project_files") == "kept"


def write_record(
    root: Path, files: dict[str, str], *, project_files_kept: bool = False
) -> None:
    """Record the files TurboVault wrote into ``root``, and whether it kept the
    dbt project's own project files."""
    path = root / RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict = {
        "generator": "TurboVault Engine",
        "note": "The files TurboVault generated here; it reports those "
        "it no longer generates.",
    }
    if project_files_kept:
        record["project_files"] = "kept"
    record["files"] = dict(sorted(files.items()))
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def _yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class DbtTarget:
    """What generation needs to know about its output folder."""

    root: Path | None = None
    # The files TurboVault wrote there last time (path -> checksum)
    recorded: dict[str, str] = field(default_factory=dict)
    # The dbt project's own dbt_project.yml, when TurboVault keeps it
    project_yml: dict[str, Any] | None = None
    # Its packages (packages.yml, else dependencies.yml), when kept
    packages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def keeps_project_files(self) -> bool:
        return self.project_yml is not None

    def models_block(self) -> dict[str, Any]:
        """The project's entry of its models: block (its folder settings)."""
        models = (self.project_yml or {}).get("models")
        name = (self.project_yml or {}).get("name")
        block = models.get(name) if isinstance(models, dict) and name else None
        return dict(block) if isinstance(block, dict) else {}

    def resources(self) -> frozenset[str]:
        """The names of the project's models, seeds and snapshots (what a
        pre-stage's ref() may read), from its files."""
        if self.root is None:
            return frozenset()
        names: set[str] = set()
        project = self.project_yml or {}

        def paths(key: str, default: str) -> list[Path]:
            value = project.get(key) or [default]
            value = [value] if isinstance(value, str) else value
            return [self.root / str(p) for p in value if (self.root / str(p)).is_dir()]

        names.update(
            p.stem for p in _files(paths("model-paths", "models"), ".sql", ".py")
        )
        names.update(p.stem for p in _files(paths("seed-paths", "seeds"), ".csv"))
        for path in _files(paths("snapshot-paths", "snapshots"), ".sql"):
            text = path.read_text(encoding="utf-8", errors="replace")
            names.update(_SNAPSHOT_BLOCK.findall(text) or [path.stem])
        return frozenset(names)

    def variables(self) -> dict[str, Any]:
        """The project's vars: global ones and its own scope's."""
        raw = (self.project_yml or {}).get("vars")
        if not isinstance(raw, dict):
            return {}
        merged = {k: v for k, v in raw.items() if not isinstance(v, dict)}
        scoped = raw.get((self.project_yml or {}).get("name"))
        if isinstance(scoped, dict):
            merged.update(scoped)
        return merged


def inspect_target(root: Path | None, *, write_project_files: bool | None) -> DbtTarget:
    """Inspect the folder a dbt project is generated into.

    ``write_project_files``: True writes dbt_project.yml and packages.yml in
    any case, False never; None (auto) keeps a dbt_project.yml TurboVault
    didn't write.
    """
    if root is None:
        return DbtTarget()
    recorded = read_record(root)
    project_file = root / "dbt_project.yml"
    if write_project_files is None:
        keep = project_file.is_file() and "dbt_project.yml" not in recorded
    else:
        keep = not write_project_files
    if not keep:
        return DbtTarget(root=root, recorded=recorded)
    packages: list[dict[str, Any]] = []
    for name in ("packages.yml", "dependencies.yml"):
        entries = _yaml(root / name).get("packages")
        if isinstance(entries, list):
            packages = [dict(e) for e in entries if isinstance(e, dict)]
            break
    return DbtTarget(
        root=root,
        recorded=recorded,
        project_yml=_yaml(project_file) if project_file.is_file() else {},
        packages=packages,
    )


# ---------------------------------------------------------------------------
# Models and sources defined twice
# ---------------------------------------------------------------------------

_IGNORED_FOLDERS = frozenset({"target", "dbt_packages", "logs", ".turbovault"})
_SNAPSHOT_BLOCK = re.compile(r"\{%-?\s*snapshot\s+(\w+)\s*-?%\}")


def _entries(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """A YAML file's list of properties (models:, sources:, tables:)."""
    value = data.get(key)
    return [e for e in value if isinstance(e, dict)] if isinstance(value, list) else []


def _model_paths(root: Path) -> list[Path]:
    paths = _yaml(root / "dbt_project.yml").get("model-paths") or ["models"]
    if isinstance(paths, str):
        paths = [paths]
    return [root / str(p) for p in paths if (root / str(p)).is_dir()]


def _files(folders: list[Path], *suffixes: str) -> list[Path]:
    found = []
    for folder in folders:
        for path in folder.rglob("*"):
            if (
                path.is_file()
                and path.suffix in suffixes
                and not _IGNORED_FOLDERS & set(path.relative_to(folder).parts)
            ):
                found.append(path)
    return sorted(found)


def kept_sources(old_text: str, new_text: str) -> dict[str, Any] | None:
    """What a dbt project's sources file declares that TurboVault's
    replacement doesn't: the source tables only the project's own models
    read (a pre-stage's, spec D16). None when there are none.

    dbt reads a source's tables from any number of files, so they can stay
    in a file of their own.
    """
    try:
        old = yaml.safe_load(old_text)
        new = yaml.safe_load(new_text)
    except yaml.YAMLError:
        return None
    if not isinstance(old, dict) or not isinstance(new, dict):
        return None
    generated = {
        (str(source.get("name")), str(table.get("name")))
        for source in _entries(new, "sources")
        for table in _entries(source, "tables")
    }
    kept = []
    for source in _entries(old, "sources"):
        tables = [
            table
            for table in _entries(source, "tables")
            if (str(source.get("name")), str(table.get("name"))) not in generated
        ]
        if tables:
            kept.append({**source, "tables": tables})
    return {"version": 2, "sources": kept} if kept else None


def defined_twice(root: Path, written: set[str]) -> list[tuple[str, str, str]]:
    """Models and sources TurboVault wrote that the project defines elsewhere.

    ``written``: the files this run wrote, relative to ``root``. Returns
    (kind, name, the other file) for each: ``model`` (another model file of
    that name), ``model_yaml`` (another YAML describing the model) and
    ``source`` (another YAML defining that source table).
    """
    folders = _model_paths(root)
    ours = {root / path for path in written}
    models = {Path(p).stem for p in written if p.endswith(".sql")}
    sources: set[tuple[str, str]] = set()
    described: set[str] = set()
    for path in ours:
        if path.suffix in (".yml", ".yaml"):
            data = _yaml(path)
            for source in _entries(data, "sources"):
                for table in _entries(source, "tables"):
                    sources.add((str(source.get("name")), str(table.get("name"))))
            described.update(str(m.get("name")) for m in _entries(data, "models"))
    found: list[tuple[str, str, str]] = []
    for path in _files(folders, ".sql", ".py"):
        if path not in ours and path.stem in models:
            found.append(("model", path.stem, path.relative_to(root).as_posix()))
    for path in _files(folders, ".yml", ".yaml"):
        if path in ours:
            continue
        data = _yaml(path)
        relative = path.relative_to(root).as_posix()
        for model in _entries(data, "models"):
            name = str(model.get("name"))
            if name in described:
                found.append(("model_yaml", name, relative))
        for source in _entries(data, "sources"):
            for table in _entries(source, "tables"):
                key = (str(source.get("name")), str(table.get("name")))
                if key in sources:
                    found.append(("source", ".".join(key), relative))
    return found
