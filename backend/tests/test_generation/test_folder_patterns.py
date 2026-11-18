"""Where generated models go: folder patterns and the folder setting (D27).

A project's folders are patterns per layer and kind of model, with the
entity's group and source system as placeholders; dbt_project.yml
configures each layer on the fixed part of its pattern. Models outside their
layer's configured folder carry the layer's settings themselves. With
use_model_folders off, models go to the patterns instead of the folders stored
for them, keeping the settings their original folders gave them. A layer
without a schema builds into the target's schema.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.test_generation.test_model_outputs import (
    _generate,
    _get,
    _read,
    _store,
    build_project,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(django_setup, db):
    return build_project()


def _config(**values):
    from engine.services.runtime_config import EngineRuntimeConfig

    return EngineRuntimeConfig(project_name="outputs", **values)


def _project_yml(tmp_path: Path) -> dict:
    return yaml.safe_load(_read(tmp_path / "dbt" / "dbt_project.yml"))


def _files(tmp_path: Path) -> set[str]:
    root = tmp_path / "dbt"
    return {path.relative_to(root).as_posix() for path in root.rglob("*.sql")}


def _config_block(sql: str) -> str:
    return sql.split("{%- set yaml_metadata")[0]


def test_patterns_place_the_models_and_configure_their_layers(project, tmp_path):
    from engine.models import PIT, Hub, Satellite

    Hub.objects.filter(hub_physical_name="CUSTOMER_H").update(
        group=_group(project, "Sales")
    )
    Satellite.objects.filter(satellite_physical_name="CUSTOMER_S").update(
        group=_group(project, "Sales")
    )
    PIT.objects.update(group=_group(project, "Sales"))
    folders = {
        "staging": "models/stage/[[ source_system ]]",
        "raw_vault": "models/dv/[[ group_name ]]",
        "satellite": "models/dv/[[ group_name ]]/satellites",
        "pit": "marts/pits",
        "control": "models/ctl",
    }

    report = _generate(project, tmp_path, runtime_config=_config(folders=folders))

    assert report.status == "success", report.issues
    files = _files(tmp_path)
    assert "models/stage/crm/stg__crm__customer.sql" in files
    assert "models/dv/Sales/CUSTOMER_H.sql" in files
    assert "models/dv/Sales/satellites/CUSTOMER_S_v0.sql" in files
    # The v1 view follows its v0; an entity without group drops the folder
    assert "models/dv/Sales/satellites/CUSTOMER_S_v1.sql" in files
    assert "models/dv/NATION_RH.sql" in files
    assert "marts/pits/CUSTOMER_PIT.sql" in files
    assert "models/ctl/control_snap_v0.sql" in files

    data = _project_yml(tmp_path)
    assert data["model-paths"] == ["models", "marts"]
    layers = data["models"]["outputs"]
    assert layers["stage"] == {"+schema": "stage", "+materialized": "view"}
    assert layers["dv"] == {"+schema": "rdv", "+materialized": "incremental"}
    assert layers["ctl"] == {"+schema": "control", "+materialized": "table"}
    assert "40_business_vault" in layers  # the layer's own folder
    # Inside a configured layer folder: nothing to repeat
    hub_sql = _read(tmp_path / "dbt" / "models" / "dv" / "Sales" / "CUSTOMER_H.sql")
    assert "schema=" not in _config_block(hub_sql)
    # Outside: the PIT carries its layer's settings
    pit_sql = _read(tmp_path / "dbt" / "marts" / "pits" / "CUSTOMER_PIT.sql")
    assert "schema='bdv'" in _config_block(pit_sql)


def _group(project, name):
    from engine.models import Group

    return Group.objects.get_or_create(project=project, group_name=name)[0]


def test_vault_folders_may_name_the_entitys_source_system(project, tmp_path):
    folders = {
        "raw_vault": "models/rdv/[[ source_system ]]",
        "pit": "models/bdv/[[ source_system_name ]]/pits",
    }

    report = _generate(project, tmp_path, runtime_config=_config(folders=folders))

    assert report.status == "success", report.issues
    files = _files(tmp_path)
    # Hubs: their primary source's system; satellites: their table's
    assert "models/rdv/crm/CUSTOMER_H.sql" in files
    assert "models/rdv/crm/CUSTOMER_S_v0.sql" in files
    assert "models/rdv/crm/CUSTOMER_S_v1.sql" in files
    # Reference tables and PITs: their Hub's
    assert "models/rdv/crm/NATION_R.sql" in files
    assert "models/bdv/CRM/pits/CUSTOMER_PIT.sql" in files


def test_an_entitys_source_system_is_its_most_common():
    from engine.services.generation.folder_config import main_source_system

    assert main_source_system(["crm", "erp", "crm"]) == "crm"
    assert main_source_system(["erp", "crm"]) == "crm"  # a tie: first by name
    assert main_source_system([None]) is None


def test_invalid_patterns_are_rejected():
    from engine.services.config_schema import TurboVaultConfig

    for folders, message in (
        ({"vault": "models/dv"}, "Unknown folders"),
        ({"raw_vault": "models/[[ entity ]]"}, "unknown placeholders"),
        ({"raw_vault": "../dv"}, "inside the dbt project"),
        ({"raw_vault": "/abs/dv"}, "relative"),
        ({"raw_vault": "models"}, "model path and a folder"),
    ):
        with pytest.raises(ValueError, match=message):
            TurboVaultConfig(project={"name": "p"}, configuration={"folders": folders})


def test_a_layer_without_schema_builds_into_the_targets(project, tmp_path):
    report = _generate(project, tmp_path, runtime_config=_config(rdv_schema=None))

    assert report.status == "success", report.issues
    layers = _project_yml(tmp_path)["models"]["outputs"]
    assert layers["30_raw_vault"] == {"+materialized": "incremental"}
    assert layers["20_staging"]["+schema"] == "stage"


def test_turbovaults_structure_keeps_the_original_folder_settings(project, tmp_path):
    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    _store("hub", hub, folder="models/vault/hubs")
    imported = {
        "+persist_docs": {"relation": True},
        "vault": {
            "+schema": "edw",
            "+materialized": "incremental",
            "hubs": {"+tags": ["hubs"], "+on_schema_change": "fail"},
        },
    }

    stored = _generate(
        project,
        tmp_path / "stored",
        runtime_config=_config(dbt_project_models=imported),
    )
    standard = _generate(
        project,
        tmp_path / "standard",
        runtime_config=_config(dbt_project_models=imported, use_model_folders=False),
    )

    assert stored.status == standard.status == "success"
    # Stored folders: the imported block configures the hub's folder
    assert "models/vault/hubs/CUSTOMER_H.sql" in _files(tmp_path / "stored")
    stored_sql = _read(tmp_path / "stored" / "dbt" / "models/vault/hubs/CUSTOMER_H.sql")
    assert "on_schema_change" not in _config_block(stored_sql)
    # TurboVault's structure: the hub keeps what its folder gave it
    assert "models/30_raw_vault/CUSTOMER_H.sql" in _files(tmp_path / "standard")
    sql = _config_block(
        _read(tmp_path / "standard" / "dbt" / "models/30_raw_vault/CUSTOMER_H.sql")
    )
    assert "schema='edw'" in sql
    assert "on_schema_change='fail'" in sql
    assert "'hubs'" in sql  # its folder's tag
    assert "materialized" not in sql  # the layer gives incremental too
    project_models = _project_yml(tmp_path / "standard")["models"]["outputs"]
    assert "vault" not in project_models
    assert project_models["+persist_docs"] == {"relation": True}


def test_the_folder_setting_is_a_project_setting(project, tmp_path):
    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    _store("hub", hub, folder="models/vault")

    _generate(project, tmp_path / "a", runtime_config=_config(use_model_folders=False))
    _generate(
        project,
        tmp_path / "b",
        runtime_config=_config(use_model_folders=False),
        use_model_folders=True,
    )

    assert "models/30_raw_vault/CUSTOMER_H.sql" in _files(tmp_path / "a")
    # A run's option wins over the project's setting
    assert "models/vault/CUSTOMER_H.sql" in _files(tmp_path / "b")


def test_config_yml_keeps_the_folder_settings(tmp_path):
    from engine.services.config_schema import TurboVaultConfig
    from engine.services.project_config import write_project_config
    from engine.services.runtime_config import EngineRuntimeConfig

    config = TurboVaultConfig(
        project={"name": "shop"},
        configuration={
            "folders": {"raw_vault": "models/rdv/[[ group ]]"},
            "use_model_folders": False,
            "rdv_schema": None,
        },
    )
    path = tmp_path / "config.yml"
    write_project_config(path, config)

    reloaded = TurboVaultConfig(**yaml.safe_load(path.read_text(encoding="utf-8")))
    runtime = EngineRuntimeConfig.from_turbovault_config(reloaded)
    assert runtime.folders == {"raw_vault": "models/rdv/[[ group ]]"}
    assert runtime.use_model_folders is False
    assert runtime.rdv_schema is None
