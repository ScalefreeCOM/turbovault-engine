"""
The settings an imported model keeps (spec D20, D25).

A model's dbt settings come from its folder (the ``models:`` block of
``dbt_project.yml``) and from itself (``config()``, YAML properties). The
manifest merges both (``unrendered_config``), so with ``dbt_project.yml`` the
import resolves the folder-level settings along the model's ``fqn`` and keeps
the model's own. The folder-level block becomes a project setting, written
into the generated ``dbt_project.yml`` again.

A model stores only what TurboVault wouldn't generate by itself: a setting
equal to its template's default (or, unset there, to what its folder gives
it) isn't stored. Tags add up in dbt (folder and model), so a model stores
its own tags when its folder's and its template's tags don't make them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from engine.services.generation.project_yml import (
    IGNORED_SETTINGS,
    Settings,
    folder_settings,  # noqa: F401 (re-exported)
    settings_key,
    tag_list,
)

# Settings with a field of their own on a model output.
FIELD_KEYS = {
    "materialized": "materialized",
    "alias": "alias",
    "schema": "schema_name",
    "database": "database_name",
}


def model_settings(node: Mapping[str, Any]) -> Settings:
    """A model's settings as written: its folder's and its own (merged).

    Tags are the effective ones, which also count its YAML properties'.
    """
    raw = node.get("unrendered_config") or {}
    values = {
        settings_key(name): value
        for name, value in raw.items()
        if settings_key(name) not in ("tags", *IGNORED_SETTINGS)
    }
    config = node.get("config") or {}
    tags = tag_list(config.get("tags", raw.get("tags", node.get("tags"))))
    return Settings(values=values, tags=tags)


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.strip() == b.strip()
    if isinstance(a, list) and len(a) == 1 and not isinstance(b, list):
        return _same(a[0], b)
    if isinstance(b, list) and len(b) == 1 and not isinstance(a, list):
        return _same(a, b[0])
    return a == b


def stored_settings(
    *,
    effective: Settings,
    folder: Settings,
    template_defaults: Mapping[str, Any],
    template_tags: list[str],
    regenerated_folder: Settings | None = None,
) -> dict[str, Any]:
    """What a model output stores so the model comes back as it was.

    ``effective``: the model's settings (folder's and its own); ``folder``:
    its folder's; ``template_defaults`` and ``template_tags``: what
    TurboVault's template writes into the model; ``regenerated_folder``: what
    the generated project's folder gives it (default: ``folder``). Returns the
    output's fields: materialized, alias, schema_name, database_name, tags,
    config.
    """
    regenerated = regenerated_folder or folder
    own = {
        key: value
        for key, value in effective.values.items()
        if key not in folder.values or not _same(folder.values[key], value)
    }
    result: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key in {*own, *template_defaults}:
        target = own.get(key, folder.values.get(key))
        default = (
            template_defaults[key]
            if template_defaults.get(key) is not None
            else regenerated.values.get(key)
        )
        if key == "materialized":
            # Nothing set is dbt's default
            target, default = target or "view", default or "view"
        if target is None or _same(target, default):
            continue
        if key in FIELD_KEYS:
            result[FIELD_KEYS[key]] = str(target)
        else:
            extra[key] = target
    if extra:
        result["config"] = extra

    own_tags = list(dict.fromkeys(t for t in effective.tags if t not in folder.tags))
    generated = {tag.lower() for tag in [*regenerated.tags, *template_tags] if tag}
    if {tag.lower() for tag in effective.tags} != generated:
        result["tags"] = own_tags
    return result
