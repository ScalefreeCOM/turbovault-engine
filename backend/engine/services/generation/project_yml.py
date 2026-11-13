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


def layer_settings(
    *,
    control_schema: str,
    control_materialization: str,
    stage_schema: str,
    staging_materialization: str,
    rdv_schema: str,
    raw_vault_materialization: str,
    bdv_schema: str,
    business_vault_materialization: str,
    prestaging_materialization: str | None,
) -> dict[str, dict[str, Any]]:
    """TurboVault's layer folders and their settings, as the template writes them."""
    layers: dict[str, dict[str, Any]] = {
        "00_control": {
            "+schema": control_schema or "control",
            "+materialized": control_materialization or "table",
        }
    }
    if prestaging_materialization:
        layers["15_prestaging"] = {
            "+schema": stage_schema or "stage",
            "+materialized": prestaging_materialization,
        }
    layers["20_staging"] = {
        "+schema": stage_schema or "stage",
        "+materialized": staging_materialization or "view",
    }
    layers["30_raw_vault"] = {
        "+schema": rdv_schema or "rdv",
        "+materialized": raw_vault_materialization or "incremental",
    }
    layers["40_business_vault"] = {
        "+schema": bdv_schema or "bdv",
        "+materialized": business_vault_materialization or "table",
    }
    return layers


def models_block(
    project_name: str,
    layers: Mapping[str, Mapping[str, Any]],
    imported: Mapping[str, Any] | None,
    settings: Mapping[str, Any] | None,
) -> str:
    """The ``models:`` block with the imported folders' settings, or "".

    The project's imported subtree comes first; TurboVault's layer folders are
    merged in, their settings winning for those folders. Other packages'
    entries of the imported ``models:`` block (``settings["models"]``) stay.
    Empty when nothing was imported: the template writes its own block.
    """
    other = (settings or {}).get("models")
    other = dict(other) if isinstance(other, Mapping) else {}
    if not imported and not other:
        return ""
    project = copy.deepcopy(dict(imported or {}))
    for folder, values in layers.items():
        merged = (
            dict(project.get(folder) or {})
            if isinstance(project.get(folder), Mapping)
            else {}
        )
        merged.update(values)
        project[folder] = merged
    other.pop(project_name, None)
    body = yaml.safe_dump(
        {"models": {**other, project_name: project}},
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    return body


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
