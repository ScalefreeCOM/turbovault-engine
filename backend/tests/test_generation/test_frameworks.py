"""What only the dbt output applies (generation/frameworks.py).

The lists name real fields and settings, and the SQLMesh output names the ones
a model it renders sets instead of dropping them silently.
"""

from __future__ import annotations

import dataclasses

import pytest

pytestmark = pytest.mark.usefixtures("django_setup")


def _render(export, **options):
    from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh
    from engine.services.generation.types import GenerationOptions
    from engine.services.runtime_config import EngineRuntimeConfig

    _artifacts, issues = render_sqlmesh(
        export, EngineRuntimeConfig(), GenerationOptions(**options)
    )
    return [i for i in issues if i.code == "render.sqlmesh.settings_ignored"]


def _hub(**fields):
    from engine.services.export.models import (
        HashkeyDefinition,
        HubColumnMapping,
        HubDefinition,
        HubSourceInfo,
    )

    source = fields.pop("source", {})
    defaults = {
        "hub_name": "hub_customer",
        "hub_type": "standard",
        "hashkey": HashkeyDefinition(
            hashkey_name="hk_customer", business_keys=["c_id"]
        ),
        "business_key_columns": ["c_id"],
        "create_effectivity_satellite": False,
        "source_tables": [
            HubSourceInfo(
                source_table="customer",
                source_system="crm",
                stage_name="stg__crm__customer",
                business_key_columns=["c_id"],
                column_mappings=[
                    HubColumnMapping(hub_column="c_id", source_column="c_id")
                ],
                **source,
            )
        ],
    }
    return HubDefinition(**{**defaults, **fields})


def _satellite(**fields):
    from engine.services.export.models import SatelliteColumnDef, SatelliteDefinition

    return SatelliteDefinition(
        satellite_name="customer_s",
        satellite_type="standard",
        parent_entity="hub_customer",
        parent_entity_type="hub",
        parent_hashkey="hk_customer",
        source_table="customer",
        source_system="crm",
        stage_name="stg__crm__customer",
        hashdiff_name="hd_customer_s",
        columns=[SatelliteColumnDef(source_column="c_name")],
        **fields,
    )


def _stage(**fields):
    from engine.services.export.models import SourceColumnDef, StageDefinition

    return StageDefinition(
        stage_name="stg__crm__customer",
        source_table="customer",
        source_schema="crm_raw",
        source_system="crm",
        hashkeys=[],
        hashdiffs=[],
        columns=[SourceColumnDef(column_name="c_id", datatype="STRING")],
        **fields,
    )


# ---------------------------------------------------------------------------
# The lists
# ---------------------------------------------------------------------------


def test_every_listed_field_is_a_field_of_its_model():
    from django.apps import apps
    from engine.services.generation.frameworks import DBT_ONLY_FIELDS

    for entry in DBT_ONLY_FIELDS:
        field = apps.get_model("engine", entry.model)._meta.get_field(entry.field)
        if entry.value is not None:
            assert entry.value in {value for value, _label in field.choices}, entry


def test_every_listed_setting_is_a_runtime_setting():
    from engine.services.generation.frameworks import DBT_ONLY_SETTINGS
    from engine.services.runtime_config import EngineRuntimeConfig

    names = {f.name for f in dataclasses.fields(EngineRuntimeConfig)}

    assert DBT_ONLY_SETTINGS <= names


def test_what_both_outputs_apply_is_not_listed():
    from engine.services.generation.frameworks import DBT_ONLY_SETTINGS, is_dbt_only

    assert not is_dbt_only("Satellite", "hashdiff_name")
    assert not is_dbt_only("Satellite", "create_v1_view")
    assert not is_dbt_only("HubColumn", "column_type", "business_key")
    assert is_dbt_only("HubColumn", "column_type", "additional_column")
    assert "stage_naming" not in DBT_ONLY_SETTINGS
    assert "rdv_schema" not in DBT_ONLY_SETTINGS


# ---------------------------------------------------------------------------
# The SQLMesh output names them
# ---------------------------------------------------------------------------


def test_models_without_dbt_settings_get_no_warning():
    from engine.services.export.models import ProjectExport

    export = ProjectExport(
        project_name="test",
        hubs=[_hub()],
        satellites=[_satellite()],
        stages=[_stage()],
    )

    assert _render(export) == []


def test_a_hub_names_what_sqlmesh_drops():
    from engine.services.export.models import ProjectExport

    export = ProjectExport(
        project_name="test",
        hubs=[
            _hub(
                disable_hwm=True,
                additional_columns=["c_region"],
                create_effectivity_satellite=True,
                source={"hk_column": "hk_customer_buyer"},
            )
        ],
    )

    (issue,) = _render(export)

    assert issue.severity == "warning"
    assert issue.entity.type == "hub" and issue.entity.name == "hub_customer"
    assert issue.message == (
        "Hub 'hub_customer' sets what the SQLMesh output doesn't apply: "
        "high-water mark off, additional columns (c_region), sources loading "
        "another hash key (role-playing), effectivity satellite."
    )


def test_a_satellites_v1_options_count_only_with_a_v1_view():
    from engine.services.export.models import ProjectExport

    export = ProjectExport(
        project_name="test",
        hubs=[_hub()],
        satellites=[_satellite(v1_include_payload=False, hashdiff_alias="hashdiff")],
    )

    (with_view,) = _render(export)
    (without_view,) = _render(export, generate_satellite_v1_views=False)

    assert "hash diff alias, v1 view without payload" in with_view.message
    assert "v1 view" not in without_view.message


def test_a_stage_names_its_missing_columns():
    from engine.services.export.models import ProjectExport, SourceColumnDef

    export = ProjectExport(
        project_name="test",
        stages=[
            _stage(
                enable_ghost_records=False,
                missing_columns=[
                    SourceColumnDef(column_name="c_fax", datatype="STRING")
                ],
            )
        ],
    )

    (issue,) = _render(export)

    assert issue.message == (
        "Stage 'stg__crm__customer' sets what the SQLMesh output doesn't apply: "
        "ghost records off, columns missing in the source (c_fax)."
    )


def test_skipped_models_are_not_named_twice():
    from engine.services.export.models import ProjectExport

    export = ProjectExport(
        project_name="test",
        hubs=[_hub(hub_type="reference", disable_hwm=True)],
    )

    assert _render(export) == []
