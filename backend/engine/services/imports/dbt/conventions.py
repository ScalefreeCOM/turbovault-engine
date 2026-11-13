"""
What TurboVault's own templates write, so an import can tell it apart.

A model TurboVault generated carries its default tags (``['hub',
'raw_vault', <group>]``) and sits in its layer's folder, per group
(``models/30_raw_vault/<group>/``). Knowing these defaults lets the import
find a model's group and store only the settings that differ from them.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

# The tags each model's templates write, before the group (by macro). A
# model's tags are the union of its SQL's and its YAML's: the standard
# satellite's YAML adds its type.
DEFAULT_TAGS: dict[str, tuple[str, ...]] = {
    "hub": ("hub", "raw_vault"),
    "ref_hub": ("hub", "reference", "raw_vault"),
    "link": ("link", "raw_vault"),
    "nh_link": ("link", "non_historized", "raw_vault"),
    "sat_v0": ("satellite", "standard", "raw_vault"),
    "ma_sat_v0": ("satellite", "multi_active", "raw_vault"),
    "nh_sat": ("satellite", "non_historized", "raw_vault"),
    "ref_sat_v0": ("satellite", "reference", "raw_vault"),
    "sat_v1": ("satellite", "v1", "raw_vault"),
    "ma_sat_v1": ("satellite", "v1", "raw_vault"),
    "ref_sat_v1": ("satellite", "v1", "raw_vault"),
    "eff_sat_v0": ("satellite", "effectivity", "raw_vault"),
    "rec_track_sat": ("satellite", "record_tracking", "raw_vault"),
    "pit": ("pit", "business_vault"),
    "ref_table": ("reference_table", "raw_vault"),
    "control_snap_v0": ("snapshot_control", "control"),
    "control_snap_v1": ("snapshot_control", "control"),
    "stage": ("staging",),
}

# Macros whose templates add the entity's group to the tags.
GROUP_TAGGED = frozenset(
    {
        "hub",
        "ref_hub",
        "link",
        "nh_link",
        "sat_v0",
        "ma_sat_v0",
        "nh_sat",
        "ref_sat_v0",
        "sat_v1",
        "ma_sat_v1",
        "ref_sat_v1",
        "eff_sat_v0",
        "rec_track_sat",
    }
)

# TurboVault's layer folders, current (30_raw_vault) and before D12 (03_).
_LAYER_FOLDER = re.compile(r"\d\d_(raw_vault|business_vault)")


def model_tags(node: dict) -> list[str]:
    """A model's tags as dbt resolved them (folder-level and its own)."""
    config = node.get("config") or {}
    tags = config.get("tags", node.get("tags"))
    if isinstance(tags, str):
        tags = [tags]
    return [str(tag) for tag in tags or []]


def group_folder(path: str) -> str | None:
    """The group folder of a model in TurboVault's folder structure, if any.

    ``models/30_raw_vault/customers/customer_h.sql`` -> ``customers``;
    business vault models sit one folder deeper
    (``models/40_business_vault/pits/customers/``).
    """
    parts = PurePosixPath(path).parent.parts
    if len(parts) < 3 or parts[0] != "models":
        return None
    match = _LAYER_FOLDER.fullmatch(parts[1])
    if match is None:
        return None
    rest = parts[2:]
    if match.group(1) == "business_vault" and rest and rest[0] == "pits":
        rest = rest[1:]
    return rest[0] if rest else None


# Tags that name a model's layer or kind, not a subject area.
_KIND_TAGS = frozenset(
    {
        "hub",
        "hubs",
        "link",
        "links",
        "satellite",
        "satellites",
        "sat",
        "sats",
        "raw_vault",
        "rdv",
        "business_vault",
        "bdv",
        "staging",
        "stage",
        "stages",
        "pit",
        "pits",
        "control",
        "snapshot_control",
        "reference",
        "reference_table",
        "ref_table",
        "ref_hub",
        "ref_sat",
        "non_historized",
        "non_historized_link",
        "non_historized_satellite",
        "nh_link",
        "nh_sat",
        "multi_active",
        "ma_sat",
        "effectivity",
        "eff_sat",
        "record_tracking",
        "rec_track_sat",
        "v0",
        "v1",
        "datavault",
        "data_vault",
        "dv",
    }
)


def group_candidates(macro: str, tags: list[str]) -> list[str]:
    """The tags of a model that may name its group: not its template's
    defaults, nor a tag naming a layer or a kind of model."""
    defaults = {tag.lower() for tag in DEFAULT_TAGS.get(macro, ())}
    return [
        tag
        for tag in tags
        if tag.lower() not in defaults and tag.lower() not in _KIND_TAGS
    ]
