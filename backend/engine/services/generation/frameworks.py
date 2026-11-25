"""
What only the dbt output applies: entity fields and project settings.

TurboVault generates dbt projects (datavault4dbt) and SQLMesh projects
(datavault4sqlmesh). Many settings are datavault4dbt parameters or dbt
concepts that the SQLMesh output has no counterpart for. This module lists
them, so that:

- callers such as Studio mark them as dbt settings from one list instead of
  reading the renderers;
- the SQLMesh output names the ones a model it renders sets, rather than
  dropping them silently (``render.sqlmesh.settings_ignored``, see
  ``sqlmesh_ignored_settings``).

The lists cover the settings and fields whose SQLMesh support is decided per
field. Entity types the SQLMesh output doesn't render at all (PITs, reference
tables, snapshot controls, reference hubs, non-historized links, satellites
other than standard ones, pre-stages) are warned about by the SQLMesh renderer
and not repeated here; a caller marks such an entity as a whole. Model
outputs (``ModelOutput``) are kept per framework (``ModelOutput.framework``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.services.export.models import (
        HubDefinition,
        LinkDefinition,
        SatelliteDefinition,
        StageDefinition,
    )


@dataclass(frozen=True)
class DbtOnlyField:
    """An entity field only the dbt output applies."""

    # The Django model's class name, e.g. "Satellite"
    model: str
    field: str
    # A choice field where only this value is dbt-only (e.g. a hub column's
    # type "additional_column"); None: the field itself
    value: str | None = None


DBT_ONLY_FIELDS: tuple[DbtOnlyField, ...] = (
    # Stage options (datavault4dbt stage parameters) and delivery method
    DbtOnlyField("SourceSystem", "include_source_columns"),
    DbtOnlyField("SourceSystem", "enable_ghost_records"),
    DbtOnlyField("SourceSystem", "delivery_method"),
    DbtOnlyField("SourceTable", "include_source_columns"),
    DbtOnlyField("SourceTable", "enable_ghost_records"),
    DbtOnlyField("SourceTable", "delivery_method"),
    DbtOnlyField("SourceTable", "sequence_column"),
    DbtOnlyField("SourceColumn", "is_missing"),
    # Hubs and links: loading, additional columns, role-playing hash keys,
    # effectivity and record-tracking satellites
    DbtOnlyField("Hub", "disable_hwm"),
    DbtOnlyField("Hub", "create_effectivity_satellite"),
    DbtOnlyField("Hub", "create_record_tracking_satellite"),
    DbtOnlyField("Hub", "effectivity_is_active_alias"),
    DbtOnlyField("Hub", "effectivity_disable_hwm"),
    DbtOnlyField("Hub", "effectivity_additional_columns"),
    DbtOnlyField("HubColumn", "column_type", "additional_column"),
    DbtOnlyField("HubSourceMapping", "stage_hashkey_name"),
    DbtOnlyField("Link", "disable_hwm"),
    DbtOnlyField("Link", "create_effectivity_satellite"),
    DbtOnlyField("Link", "create_record_tracking_satellite"),
    DbtOnlyField("Link", "effectivity_is_active_alias"),
    DbtOnlyField("Link", "effectivity_disable_hwm"),
    DbtOnlyField("Link", "effectivity_additional_columns"),
    DbtOnlyField("Link", "union_strategy"),
    DbtOnlyField("LinkColumn", "column_type", "additional_column"),
    # Satellites: the hash diff's alias, loading, the v1 view's options
    DbtOnlyField("Satellite", "hashdiff_alias"),
    DbtOnlyField("Satellite", "disable_hwm"),
    DbtOnlyField("Satellite", "v1_ledts_alias"),
    DbtOnlyField("Satellite", "v1_add_is_current_flag"),
    DbtOnlyField("Satellite", "v1_include_payload"),
)
"""Entity fields only the dbt output applies. Not listed (both outputs apply
them): ``Satellite.hashdiff_name`` and ``Satellite.create_v1_view``."""


DBT_ONLY_SETTINGS: frozenset[str] = frozenset(
    {
        # dbt project files and profile
        "dbt_project_name",
        "profile_name",
        "dbt_project_models",
        "dbt_project_settings",
        "dbt_packages",
        # Where models go and how dbt builds them
        "folders",
        "use_model_folders",
        "add_default_tags",
        "control_materialization",
        "staging_materialization",
        "raw_vault_materialization",
        "business_vault_materialization",
        "model_materializations",
        "model_specific_materializations",
        # Stage options and delivery method (datavault4dbt parameters)
        "include_source_columns",
        "enable_ghost_records",
        "use_delivery_method",
        "delivery_method",
        # Names of models only the dbt output generates
        "prestage_naming",
        "effectivity_satellite_naming",
        "record_tracking_satellite_naming",
    }
)
"""``EngineRuntimeConfig`` fields only the dbt output applies."""


DBT_ONLY_BY_MODEL: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        model: frozenset(
            entry.field
            for entry in DBT_ONLY_FIELDS
            if entry.model == model and entry.value is None
        )
        for model in {entry.model for entry in DBT_ONLY_FIELDS}
    }
)
"""The whole fields of ``DBT_ONLY_FIELDS`` by model (without the choice
values)."""


def is_dbt_only(model: str, field: str, value: str | None = None) -> bool:
    """Whether only the dbt output applies ``model.field`` (set to ``value``)."""
    return any(
        entry.model == model
        and entry.field == field
        and (entry.value is None or entry.value == value)
        for entry in DBT_ONLY_FIELDS
    )


# ---------------------------------------------------------------------------
# What a model the SQLMesh output renders sets of them
# ---------------------------------------------------------------------------


def stage_settings(stage: StageDefinition) -> list[str]:
    """The dbt-only settings ``stage`` sets, as the SQLMesh warning names them."""
    settings = []
    if not stage.include_source_columns:
        settings.append("include source columns off")
    if not stage.enable_ghost_records:
        settings.append("ghost records off")
    if stage.sequence_column:
        settings.append("sequence column")
    if stage.missing_columns:
        names = ", ".join(column.column_name for column in stage.missing_columns)
        settings.append(f"columns missing in the source ({names})")
    return settings


def hub_settings(hub: HubDefinition) -> list[str]:
    """The dbt-only settings ``hub`` sets."""
    settings = _loading(hub.disable_hwm, hub.additional_columns)
    if any(source.hk_column for source in hub.source_tables):
        settings.append("sources loading another hash key (role-playing)")
    # A hub's or link's delivery method only reaches its effectivity
    # satellite, named below
    settings.extend(
        _tracking_satellites(
            hub.create_effectivity_satellite, hub.create_record_tracking_satellite
        )
    )
    return settings


def link_settings(link: LinkDefinition) -> list[str]:
    """The dbt-only settings ``link`` sets."""
    settings = _loading(link.disable_hwm, link.additional_columns)
    settings.extend(
        _tracking_satellites(
            link.create_effectivity_satellite, link.create_record_tracking_satellite
        )
    )
    return settings


def satellite_settings(satellite: SatelliteDefinition, *, v1_view: bool) -> list[str]:
    """The dbt-only settings ``satellite`` sets; its v1 view's options only
    when the output renders one (``v1_view``)."""
    settings = []
    if satellite.hashdiff_alias:
        settings.append("hash diff alias")
    if satellite.disable_hwm:
        settings.append("high-water mark off")
    if satellite.source_is_single_batch:
        settings.append("single-batch delivery")
    if v1_view:
        if satellite.v1_ledts_alias:
            settings.append("v1 view's load end date alias")
        if not satellite.v1_add_is_current_flag:
            settings.append("v1 view without is_current flag")
        if not satellite.v1_include_payload:
            settings.append("v1 view without payload")
    return settings


def _loading(disable_hwm: bool, additional_columns: list[str]) -> list[str]:
    settings = []
    if disable_hwm:
        settings.append("high-water mark off")
    if additional_columns:
        settings.append(f"additional columns ({', '.join(additional_columns)})")
    return settings


def _tracking_satellites(effectivity: bool, record_tracking: bool) -> list[str]:
    settings = []
    if effectivity:
        settings.append("effectivity satellite")
    if record_tracking:
        settings.append("record-tracking satellite")
    return settings
