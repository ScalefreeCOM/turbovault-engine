"""Per-model output attributes (issue #442).

An entity's ``generation_config.dbt.<output kind>`` sets the model name, file
path and config() of a generated dbt model, so a project imported from an
existing dbt repository regenerates with its original structure. Every
reference to a model follows its resolved name, including those that used to
hard-code the ``_v0`` / ``_v1`` suffixes.
"""

from __future__ import annotations

import re
from pathlib import Path

import jinja2
import pytest
import yaml


@pytest.fixture
def full_export(project_export):
    """The shared export plus a reference hub with a reference satellite, a
    reference table, a snapshot control and a PIT."""
    from engine.services.export.models import (
        HubDefinition,
        PITDefinition,
        ReferenceTableDefinition,
        ReferenceTableSatelliteAssignment,
        SatelliteDefinition,
        SnapshotControlDefinition,
        SnapshotLogicPattern,
    )

    project_export.hubs.append(
        HubDefinition(
            hub_name="nation_rh",
            hub_type="reference",
            reference_key_columns=["n_nationkey"],
        )
    )
    project_export.satellites.append(
        SatelliteDefinition(
            satellite_name="nation_rs",
            satellite_type="reference",
            parent_entity="nation_rh",
            parent_entity_type="hub",
            parent_hashkey="",
            parent_business_keys=["n_nationkey"],
            source_table="customer",
            source_system="crm",
            stage_name="stg__crm__customer",
            hashdiff_name="hd_nation_rs",
        )
    )
    project_export.reference_tables.append(
        ReferenceTableDefinition(
            table_name="nation_r",
            reference_hub_name="nation_rh",
            historization_type="latest",
            satellites=[ReferenceTableSatelliteAssignment(satellite_name="nation_rs")],
        )
    )
    project_export.snapshot_controls.append(
        SnapshotControlDefinition(
            name="control_snap",
            start_date="2020-01-01",
            end_date="2030-12-31",
            daily_time="08:00:00",
            logic_patterns=[
                SnapshotLogicPattern(column_name="is_active", component="daily")
            ],
        )
    )
    project_export.pits.append(
        PITDefinition(
            pit_name="customer_bp",
            tracked_entity_type="hub",
            tracked_entity_name="hub_customer",
            tracked_hashkey="hk_customer",
            satellites=["sat_customer_details"],
            snapshot_control_name="control_snap_v1",
            snapshot_logic_column="is_active",
        )
    )
    return project_export


def _generate(export, tmp_path: Path, **config_kwargs):
    from engine.services.generation import DbtProjectGenerator, GenerationConfig
    from engine.services.generation.template_resolver import TemplateResolver

    generator = DbtProjectGenerator(
        output_path=tmp_path / "project",
        config=GenerationConfig(**config_kwargs),
        template_resolver=TemplateResolver(use_db_templates=False, framework="dbt"),
    )
    return generator.generate(export)


def _models(report) -> dict[str, Path]:
    """Generated SQL files by path relative to models/."""
    root = report.project_path / "models"
    return {
        f.path.relative_to(root).as_posix(): f.path
        for f in report.files
        if f.file_type == "sql"
    }


def _metadata(sql: str) -> dict:
    start = sql.index("{%- set yaml_metadata -%}") + len("{%- set yaml_metadata -%}")
    return yaml.safe_load(sql[start : sql.index("{%- endset -%}", start)])


def _config(sql: str) -> str:
    return sql[sql.index("{{ config(") : sql.index(") }}") + 4]


def _assert_jinja_parses(sql: str) -> None:
    # dbt renders the generated files with standard Jinja delimiters.
    jinja2.Environment().parse(sql)


def test_without_attributes_the_layout_is_unchanged(full_export, tmp_path):
    report = _generate(full_export, tmp_path)

    assert not report.errors
    assert set(_models(report)) == {
        "00_control/control_snap_v0.sql",
        "00_control/control_snap_v1.sql",
        "02_staging/crm/stg__crm__customer.sql",
        "03_raw_vault/sales/hub_customer.sql",
        "03_raw_vault/sales/hub_customer_es.sql",
        "03_raw_vault/nation_rh.sql",
        "03_raw_vault/sales/lnk_customer_order.sql",
        "03_raw_vault/sales/sat_customer_details_v0.sql",
        "03_raw_vault/sales/sat_customer_details_v1.sql",
        "03_raw_vault/nation_rs_v0.sql",
        "03_raw_vault/nation_rs_v1.sql",
        "03_raw_vault/nation_r.sql",
        "04_business_vault/pits/customer_bp.sql",
    }
    hub_sql = _models(report)["03_raw_vault/sales/hub_customer.sql"].read_text()
    assert "materialized" not in _config(hub_sql)
    assert "tags=['hub', 'raw_vault', 'sales']" in hub_sql


def test_attributes_set_path_name_config_and_references(full_export, tmp_path):
    stage = full_export.stages[0]
    stage.generation_config = {
        "dbt": {"stage": {"file_path": "staging/crm/stg_customer.sql"}}
    }
    hub = full_export.hubs[0]
    hub.generation_config = {
        "dbt": {
            "hub": {
                "model_name": "customer_h",
                "file_path": "raw_vault/hubs/customer_h.sql",
                "alias": "customer_hub",
                "schema": "rdv_core",
                "database": "dwh",
                "materialized": "incremental",
                "tags": ["hub", "core"],
                "custom_config_json": {
                    "unique_key": "hk_customer",
                    "full_refresh": False,
                },
            }
        }
    }
    full_export.satellites[0].generation_config = {
        "dbt": {
            "satellite_v0": {"model_name": "customer_details_s"},
            "satellite_v1": {"model_name": "customer_details_vs"},
        }
    }

    report = _generate(full_export, tmp_path)

    assert not report.errors
    models = _models(report)
    assert "staging/crm/stg_customer.sql" in models
    assert "raw_vault/hubs/customer_h.sql" in models
    assert "03_raw_vault/sales/customer_details_s.sql" in models
    assert "03_raw_vault/sales/customer_details_vs.sql" in models

    hub_sql = models["raw_vault/hubs/customer_h.sql"].read_text()
    _assert_jinja_parses(hub_sql)
    config = _config(hub_sql)
    assert "materialized='incremental'" in config
    assert "alias='customer_hub'" in config
    assert "schema='rdv_core'" in config
    assert "database='dwh'" in config
    assert "unique_key='hk_customer'" in config
    assert "full_refresh=False" in config
    assert "tags=['hub', 'core']" in config
    # Every model that reads the stage refers to its new name.
    assert _metadata(hub_sql)["source_models"][0]["name"] == "stg_customer"
    link_sql = models["03_raw_vault/sales/lnk_customer_order.sql"].read_text()
    assert _metadata(link_sql)["source_models"][0]["name"] == "stg_customer"
    sat_sql = models["03_raw_vault/sales/customer_details_s.sql"].read_text()
    assert _metadata(sat_sql)["source_model"] == "stg_customer"
    v1_sql = models["03_raw_vault/sales/customer_details_vs.sql"].read_text()
    assert _metadata(v1_sql)["sat_v0"] == "customer_details_s"
    pit_sql = models["04_business_vault/pits/customer_bp.sql"].read_text()
    assert _metadata(pit_sql)["sat_names"] == ["customer_details_s"]
    assert _metadata(pit_sql)["tracked_entity"] == "customer_h"

    # The stage left its layer folder, so it gets the layer's settings itself.
    stage_sql = models["staging/crm/stg_customer.sql"].read_text()
    _assert_jinja_parses(stage_sql)
    assert "materialized='view'" in stage_sql
    assert "schema='stage'" in stage_sql

    # The YAML names the model and carries the same tags.
    hub_yml = yaml.safe_load(
        (tmp_path / "project/models/raw_vault/hubs/customer_h.yml").read_text()
    )
    assert hub_yml["models"][0]["name"] == "customer_h"
    assert hub_yml["models"][0]["config"]["tags"] == ["hub", "core"]
    v1_yml = yaml.safe_load(
        (
            tmp_path / "project/models/03_raw_vault/sales/customer_details_vs.yml"
        ).read_text()
    )
    assert v1_yml["models"][0]["name"] == "customer_details_vs"


def test_references_follow_non_default_naming_patterns(full_export, tmp_path):
    full_export.snapshot_controls[0].generation_config = {
        "dbt": {
            "snapshot_control_v0": {"model_name": "snap_base"},
            "snapshot_control_v1": {"model_name": "snap_logic"},
        }
    }
    report = _generate(
        full_export,
        tmp_path,
        satellite_v0_naming="[[ satellite_name ]]_hist",
        satellite_v1_naming="[[ satellite_name ]]_cur",
    )

    assert not report.errors
    models = _models(report)
    v1_sql = models["03_raw_vault/sales/sat_customer_details_cur.sql"].read_text()
    assert _metadata(v1_sql)["sat_v0"] == "sat_customer_details_hist"
    ref_v1_sql = models["03_raw_vault/nation_rs_cur.sql"].read_text()
    assert _metadata(ref_v1_sql)["ref_sat_v0"] == "nation_rs_hist"
    ref_table_sql = models["03_raw_vault/nation_r.sql"].read_text()
    assert list(_metadata(ref_table_sql)["ref_satellites"]) == ["nation_rs_cur"]
    pit_sql = models["04_business_vault/pits/customer_bp.sql"].read_text()
    assert _metadata(pit_sql)["sat_names"] == ["sat_customer_details_hist"]
    assert _metadata(pit_sql)["snapshot_relation"] == "snap_logic"
    snap_v1_sql = models["00_control/snap_logic.sql"].read_text()
    assert _metadata(snap_v1_sql)["control_snap_v0"] == "snap_base"

    for name in ("sat_customer_details_cur", "nation_rs_cur"):
        yml = yaml.safe_load(
            next(p for p in models.values() if p.stem == name)
            .with_suffix(".yml")
            .read_text()
        )
        assert yml["models"][0]["name"] == name
    snap_yml = yaml.safe_load(
        (tmp_path / "project/models/00_control/snap_base.yml").read_text()
    )
    assert snap_yml["models"][0]["name"] == "snap_base"


@pytest.mark.parametrize(
    "hub_attributes",
    [
        # Same model name as the satellite's v0.
        {"model_name": "sat_customer_details_v0"},
        # Same file path as the link.
        {"file_path": "03_raw_vault/sales/lnk_customer_order.sql"},
    ],
)
def test_colliding_models_fail_before_anything_is_written(
    full_export, tmp_path, hub_attributes
):
    full_export.hubs[0].generation_config = {"dbt": {"hub": hub_attributes}}

    report = _generate(full_export, tmp_path)

    assert [e.code for e in report.errors] == ["COL_001"]
    assert not report.files
    assert not (tmp_path / "project").exists()


@pytest.mark.parametrize(
    "generation_config",
    [
        {"dbt": {"hub": {"file_path": "../outside/hub_customer.sql"}}},
        {"dbt": {"hub": {"file_path": "/abs/hub_customer.sql"}}},
        {"dbt": {"hub": {"file_path": "raw_vault/hub_customer.yml"}}},
        {"dbt": {"hub": {"model_name": "a", "file_path": "x/b.sql"}}},
        {"dbt": {"hub": {"model_name": "bad name"}}},
        {"dbt": {"hub": {"tags": ["it's"]}}},
        {"dbt": {"hub": {"custom_config_json": {"alias": "x"}}}},
        {"dbt": {"hub": {"unknown": "x"}}},
        {"dbt": {"hubs": {}}},
    ],
)
def test_invalid_attributes_are_rejected(full_export, tmp_path, generation_config):
    full_export.hubs[0].generation_config = generation_config

    report = _generate(full_export, tmp_path)

    assert [e.code for e in report.errors] == ["ATTR_001"]
    assert not (tmp_path / "project").exists()


def test_use_original_paths_off_gives_the_standard_layout(full_export, tmp_path):
    full_export.hubs[0].generation_config = {
        "dbt": {"hub": {"file_path": "raw_vault/hubs/customer_h.sql", "tags": ["x"]}}
    }
    full_export.stages[0].generation_config = {
        "dbt": {"stage": {"model_name": "stg_customer"}}
    }

    report = _generate(full_export, tmp_path, use_original_paths=False)

    assert not report.errors
    models = _models(report)
    assert "03_raw_vault/sales/hub_customer.sql" in models
    hub_sql = models["03_raw_vault/sales/hub_customer.sql"].read_text()
    assert _metadata(hub_sql)["source_models"][0]["name"] == "stg__crm__customer"
    assert "tags=['hub', 'raw_vault', 'sales']" in hub_sql


def test_pipeline_reports_collisions_as_write_path_collision(full_export):
    from engine.services.generation.stages.render import render
    from engine.services.generation.types import GenerationOptions
    from engine.services.runtime_config import EngineRuntimeConfig

    full_export.hubs[0].generation_config = {
        "dbt": {"hub": {"model_name": "lnk_customer_order"}}
    }

    artifacts, issues = render(
        project_export=full_export,
        output_type="dbt",
        runtime_config=EngineRuntimeConfig(),
        options=GenerationOptions(),
    )

    assert not artifacts
    assert [i.code for i in issues if i.severity == "error"] == ["write.path_collision"]
    assert re.search(
        r"lnk_customer_order\.sql as hub 'hub_customer'", issues[0].message
    )
