"""
dbt_project.yml settings beyond TurboVault's own (spec D20, D25).

A project imported from a dbt project keeps that project's ``dbt_project.yml``
settings: the ``models:`` block of the project (folder-level materializations,
schemas, tags, hooks, ...) and every other top-level setting (``seeds:``,
``snapshots:``, ``on-run-start``, ``dispatch``, paths, ...). Generation
writes them back next to what TurboVault needs: its layer folders' settings
win for those folders, and its model paths are added to the project's.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

# Keys the dbt_project.yml template writes itself (name and profile come from
# the project's settings; vars from its variables).
TEMPLATE_KEYS = frozenset(
    {
        "name",
        "version",
        "config-version",
        "profile",
        "model-paths",
        "analysis-paths",
        "test-paths",
        "seed-paths",
        "macro-paths",
        "snapshot-paths",
        "clean-targets",
        "vars",
        "models",
    }
)
# Keys whose imported value replaces the template's default.
_HEADER_KEYS = (
    "version",
    "analysis-paths",
    "test-paths",
    "seed-paths",
    "macro-paths",
    "snapshot-paths",
    "clean-targets",
)


def header_values(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Template variables for the keys an imported dbt_project.yml sets.

    ``version`` becomes ``project_version``; the paths and clean-targets keep
    their names with ``_`` for ``-`` (``analysis_paths``, ...).
    """
    values: dict[str, Any] = {}
    for key in _HEADER_KEYS:
        value = (settings or {}).get(key)
        if value is None:
            continue
        name = "project_version" if key == "version" else key.replace("-", "_")
        if key != "version" and not isinstance(value, list):
            value = [value]
        values[name] = (
            [str(v) for v in value] if isinstance(value, list) else str(value)
        )
    return values


def model_paths(own: list[str], settings: Mapping[str, Any] | None) -> list[str]:
    """The imported project's model paths, plus the ones TurboVault needs."""
    imported = (settings or {}).get("model-paths")
    if isinstance(imported, str):
        imported = [imported]
    paths = [str(p) for p in imported or []]
    for path in own:
        if path not in paths:
            paths.append(path)
    return paths or ["models"]


# The layers dbt_project.yml configures, in the order the template writes them.
BLOCK_LAYERS = ("control", "prestaging", "staging", "raw_vault", "business_vault")


def layer_roots(
    layer_folders: Mapping[str, str], *, prestaging: bool
) -> dict[str, tuple[str, ...]]:
    """Where dbt_project.yml configures each layer: its key path below the project.

    ``layer_folders`` are the fixed parts of the layers' folder patterns
    (``models/30_raw_vault`` -> ``("30_raw_vault",)``: dbt's config paths are
    relative to the model path). A layer whose folder is a model path itself,
    or shares its key path with another layer, gets no block: its models carry
    the layer's settings in their own config().
    """
    roots: dict[str, tuple[str, ...]] = {}
    for layer in BLOCK_LAYERS:
        if layer == "prestaging" and not prestaging:
            continue
        parts = tuple(part for part in layer_folders[layer].split("/") if part)
        if len(parts) >= 2:
            roots[layer] = parts[1:]
    counts: dict[tuple[str, ...], int] = {}
    for key in roots.values():
        counts[key] = counts.get(key, 0) + 1
    return {layer: key for layer, key in roots.items() if counts[key] == 1}


def layer_values(schema: str | None, materialized: str | None) -> dict[str, Any]:
    """A layer block's settings; no ``+schema`` for a layer without one."""
    values: dict[str, Any] = {}
    if schema is not None:
        values["+schema"] = schema
    if materialized:
        values["+materialized"] = materialized
    return values


def layer_tree(
    roots: Mapping[str, tuple[str, ...]], values: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """The layers' blocks, nested along their key paths."""
    tree: dict[str, Any] = {}
    for layer, key in roots.items():
        node = tree
        for part in key:
            node = node.setdefault(part, {})
        node.update(values[layer])
    return tree


# The schema setting of each layer and its default name (the pre-stages share
# the staging one).
SCHEMA_SETTINGS: dict[str, tuple[str, str]] = {
    "control": ("control_schema", "control"),
    "prestaging": ("stage_schema", "stage"),
    "staging": ("stage_schema", "stage"),
    "raw_vault": ("rdv_schema", "rdv"),
    "business_vault": ("bdv_schema", "bdv"),
}


def layer_schema(config: Any, layer: str) -> str | None:
    """A layer's schema: None for no custom schema (the target's); an empty
    setting is TurboVault's default name."""
    field_name, default = SCHEMA_SETTINGS[layer]
    value = getattr(config, field_name)
    if value is None:
        return None
    return value or default


def layer_materialization(config: Any, layer: str) -> str:
    """A layer's materialization. The pre-stages take the staging layer's,
    but as views where it is ephemeral: a stage reads a pre-stage's columns
    from the database."""
    if layer == "prestaging":
        value = config.staging_materialization
        return "view" if value == "ephemeral" else value
    return getattr(config, f"{layer}_materialization")


def layers_tree(config: Any, folders: Any, *, prestaging: bool) -> dict[str, Any]:
    """The layer blocks TurboVault writes into the models: block for a config
    (layer schemas and materializations) and its folders (``FolderConfig``)."""
    roots = layer_roots(
        {layer: folders.layer_folder(layer) for layer in BLOCK_LAYERS},
        prestaging=prestaging,
    )
    return layer_tree(
        roots,
        {
            layer: layer_values(
                layer_schema(config, layer), layer_materialization(config, layer)
            )
            for layer in roots
        },
    )


def without_layers(
    models_block: Mapping[str, Any], layers: Mapping[str, Any]
) -> dict[str, Any]:
    """An imported models: block without the layer settings TurboVault writes
    anyway (``layers_tree``); folders left without settings are dropped."""
    result = copy.deepcopy(dict(models_block))

    def strip(node: dict[str, Any], tree: Mapping[str, Any]) -> None:
        for key, value in tree.items():
            if key.startswith("+"):
                if key in node and node[key] == value:
                    del node[key]
            elif isinstance(value, Mapping) and isinstance(node.get(key), dict):
                strip(node[key], value)
                if not node[key]:
                    del node[key]

    strip(result, layers)
    return result


# What the template writes for the header keys of an imported dbt_project.yml
# without them.
TEMPLATE_DEFAULTS: dict[str, Any] = {
    "version": "1.0.0",
    "analysis-paths": ["analyses"],
    "test-paths": ["tests"],
    "seed-paths": ["seeds"],
    "macro-paths": ["macros"],
    "snapshot-paths": ["snapshots"],
    "clean-targets": ["target", "dbt_packages"],
}


def without_defaults(
    settings: Mapping[str, Any], *, own_model_paths: list[str]
) -> dict[str, Any]:
    """An imported dbt_project.yml's other settings without the ones TurboVault
    writes the same anyway (``own_model_paths``: the model paths it needs)."""

    def as_list(value: Any) -> list[str]:
        return [str(v) for v in value] if isinstance(value, list) else [str(value)]

    result: dict[str, Any] = {}
    for key, value in settings.items():
        default = TEMPLATE_DEFAULTS.get(key)
        if default is not None and (
            as_list(value) == as_list(default)
            if isinstance(default, list)
            else str(value) == default
        ):
            continue
        if key == "model-paths" and model_paths(own_model_paths, {key: value}) == (
            own_model_paths or ["models"]
        ):
            continue
        result[key] = value
    return result


def root_level(models_block: Mapping[str, Any] | None) -> dict[str, Any]:
    """The settings of a models: block that apply to every model (no folders)."""
    return {
        name: value
        for name, value in (models_block or {}).items()
        if _is_setting(str(name), value)
    }


def _merge(base: dict[str, Any], tree: Mapping[str, Any]) -> None:
    """Merge *tree* into *base*; the tree's settings win."""
    for name, value in tree.items():
        if isinstance(value, Mapping) and not _is_setting(str(name), value):
            node = base.get(name)
            if not isinstance(node, dict):
                node = {}
                base[name] = node
            _merge(node, value)
        else:
            base[name] = copy.deepcopy(value)


def models_block(
    project_name: str,
    layers: Mapping[str, Any],
    imported: Mapping[str, Any] | None,
    settings: Mapping[str, Any] | None,
) -> str:
    """The ``models:`` block: the imported one with TurboVault's layers merged in.

    ``layers`` is the nested layer tree (``layer_tree``); its settings win for
    the layers' folders. Other packages' entries of the imported ``models:``
    block (``settings["models"]``) stay.
    """
    other = (settings or {}).get("models")
    other = dict(other) if isinstance(other, Mapping) else {}
    project = copy.deepcopy(dict(imported or {}))
    _merge(project, layers)
    other.pop(project_name, None)
    return yaml.safe_dump(
        {"models": {**other, project_name: project}},
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def extra_block(settings: Mapping[str, Any] | None) -> str:
    """The imported top-level settings the template doesn't write, or ""."""
    extra = {
        key: value
        for key, value in (settings or {}).items()
        if key not in TEMPLATE_KEYS
    }
    if not extra:
        return ""
    return "\n" + yaml.safe_dump(
        extra, sort_keys=False, default_flow_style=False, allow_unicode=True
    )


# TurboVault's package (the packages.yml template writes it too).
DATAVAULT4DBT_PACKAGE: dict[str, Any] = {
    "package": "ScalefreeCOM/datavault4dbt",
    "version": [">=1.0.0", "<3.0.0"],
}


def package_source(entry: Mapping[str, Any]) -> str:
    """Where a packages.yml entry comes from (hub name, git URL, path)."""
    for key in ("package", "git", "private", "local", "tarball"):
        if entry.get(key):
            return str(entry[key])
    return ""


def packages_block(packages: list[Mapping[str, Any]] | None) -> str:
    """An imported dbt project's packages as packages.yml's list (spec D28),
    or "" for TurboVault's own. datavault4dbt is added when no package is it
    (its premium package brings it along)."""
    if not packages:
        return ""
    entries = [dict(entry) for entry in packages]
    if not any("datavault4dbt" in package_source(e).lower() for e in entries):
        entries.insert(0, copy.deepcopy(DATAVAULT4DBT_PACKAGE))
    text = yaml.safe_dump(
        entries, sort_keys=False, default_flow_style=False, allow_unicode=True
    )
    return "\n".join(f"  {line}" if line else line for line in text.splitlines())


# ---------------------------------------------------------------------------
# Resolving the models: block
# ---------------------------------------------------------------------------

# Settings whose value is a mapping (not a subfolder) in the models: block.
_MAPPING_SETTINGS = frozenset(
    {
        "persist_docs",
        "docs",
        "grants",
        "contract",
        "meta",
        "labels",
        "partition_by",
        "column_types",
        "quoting",
        "access",
        "snowflake_warehouse",
        "query_tag",
        "cluster_by",
    }
)
# Settings a model's config has that aren't stored (they decide whether it
# exists or are dbt's own bookkeeping).
IGNORED_SETTINGS = frozenset({"enabled", "packages"})


def settings_key(name: str) -> str:
    """A settings key as dbt reads it: without '+', hooks with '-'."""
    key = str(name).lstrip("+")
    return {"pre_hook": "pre-hook", "post_hook": "post-hook"}.get(key, key)


def tag_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(tag) for tag in value]


@dataclass
class Settings:
    """Settings with tags kept apart (they add up instead of replacing)."""

    values: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


def _is_setting(name: str, value: Any) -> bool:
    """Whether a models: block entry is a setting (else a subfolder)."""
    return name.startswith("+") or (
        not isinstance(value, Mapping) or settings_key(name) in _MAPPING_SETTINGS
    )


def folder_settings(models_block: Mapping[str, Any] | None, fqn: list[str]) -> Settings:
    """The settings a project's models: block gives a model at ``fqn``.

    ``models_block`` is the project's entry (without its name). Walks the
    model's folders (``fqn`` between the project and the model's name); the
    most specific value wins, tags accumulate.
    """
    result = Settings()
    if not models_block:
        return result
    level: Any = models_block
    folders = list(fqn[1:-1]) if len(fqn) > 2 else []
    for depth in range(len(folders) + 1):
        if not isinstance(level, Mapping):
            break
        for name, value in level.items():
            name = str(name)
            if not _is_setting(name, value):
                continue
            key = settings_key(name)
            if key == "tags":
                result.tags.extend(t for t in tag_list(value) if t not in result.tags)
            else:
                result.values[key] = value
        if depth < len(folders):
            level = level.get(folders[depth]) if isinstance(level, Mapping) else None
    return result


def covers(models_block: Mapping[str, Any] | None, folder: str) -> bool:
    """Whether the models: block gives a model in ``folder`` any settings.

    ``folder`` is relative to the dbt project (``models/raw_vault/hubs``):
    its first part is the model path, the rest the folders dbt walks.
    """
    parts = list(PurePosixPath(folder).parts[1:])
    found = folder_settings(models_block, ["project", *parts, "model"])
    return bool(found.values or found.tags)
