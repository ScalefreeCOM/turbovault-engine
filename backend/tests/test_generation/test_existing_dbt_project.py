"""Generating into an existing dbt project (spec D17, §9.7).

An empty folder gets a complete dbt project. A folder holding a dbt project
whose dbt_project.yml TurboVault didn't write keeps its dbt_project.yml and
packages.yml: its folder settings apply, models carry their layer's settings
where those give them none, and the report lists what the models need.
TurboVault records the files it writes; those it no longer generates are
reported and deleted only on request, and models or sources the project
defines twice are reported.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import yaml

from tests.test_generation.test_model_outputs import (
    _generate,
    _issues,
    _read,
    build_project,
)

pytestmark = pytest.mark.django_db

PROJECT_YML = textwrap.dedent(
    """
    name: outputs
    version: '2.0.0'
    profile: warehouse
    # Their own comment
    vars:
      their_var: 1
    models:
      outputs:
        30_raw_vault:
          +schema: edw
          +materialized: incremental
    """
).lstrip()


@pytest.fixture
def project(django_setup, db):
    return build_project()


def _dbt(tmp_path: Path) -> Path:
    return tmp_path / "dbt"


def _existing_project(tmp_path: Path, *, packages: str | None = None) -> Path:
    root = _dbt(tmp_path)
    root.mkdir()
    (root / "dbt_project.yml").write_text(PROJECT_YML, encoding="utf-8")
    (root / "packages.yml").write_text(
        packages
        or "packages:\n  - package: ScalefreeCOM/datavault4dbt\n    version: 1.9.3\n",
        encoding="utf-8",
    )
    return root


def _record(tmp_path: Path) -> dict[str, str]:
    path = _dbt(tmp_path) / ".turbovault" / "generated.json"
    return json.loads(path.read_text(encoding="utf-8"))["files"]


def _config_block(path: Path) -> str:
    return _read(path).split("{%- set yaml_metadata")[0]


def test_an_empty_folder_gets_a_complete_project_and_a_record(project, tmp_path):
    report = _generate(project, tmp_path)

    assert report.status == "success", report.issues
    record = _record(tmp_path)
    assert {"dbt_project.yml", "packages.yml"} <= set(record)
    assert "models/30_raw_vault/CUSTOMER_H.sql" in record

    # Its own files: generated again
    again = _generate(project, tmp_path)
    assert not _issues(again, "render.project_files_kept")


def test_an_existing_dbt_project_keeps_its_project_files(project, tmp_path):
    root = _existing_project(tmp_path)

    report = _generate(project, tmp_path)

    assert report.status == "success", report.issues
    assert _read(root / "dbt_project.yml") == PROJECT_YML
    assert "1.9.3" in _read(root / "packages.yml")
    (kept,) = _issues(report, "render.project_files_kept")
    assert kept.severity == "info"
    assert not _issues(report, "render.project_needs_package")
    record = _record(tmp_path)
    assert "dbt_project.yml" not in record
    # Its folder settings apply: the raw vault's give the hub its settings
    assert "schema=" not in _config_block(root / "models/30_raw_vault/CUSTOMER_H.sql")
    # Where they give none, a model carries its layer's
    (stage,) = root.rglob("stg__crm__customer.sql")
    block = _config_block(stage)
    assert "schema='stage'" in block
    assert "materialized='view'" in block


def test_the_report_lists_what_the_models_need(project, tmp_path):
    from engine.services.runtime_config import EngineRuntimeConfig

    _existing_project(tmp_path, packages="packages:\n  - package: dbt-labs/dbt_utils\n")
    config = EngineRuntimeConfig(
        project_name="outputs", global_vars={"datavault4dbt.hash": "SHA2"}
    )

    report = _generate(project, tmp_path, runtime_config=config)

    (package,) = _issues(report, "render.project_needs_package")
    assert "ScalefreeCOM/datavault4dbt" in package.message
    (variables,) = _issues(report, "render.project_needs_vars")
    assert "datavault4dbt.hash: SHA2" in variables.message


def test_the_project_files_may_be_written_anyway(project, tmp_path):
    root = _existing_project(tmp_path)

    _generate(project, tmp_path, write_project_files=True)

    data = yaml.safe_load(_read(root / "dbt_project.yml"))
    assert data["models"]["outputs"]["30_raw_vault"]["+schema"] == "rdv"
    assert "dbt_project.yml" in _record(tmp_path)


def _rename_hub(new_name: str) -> None:
    from engine.models import Hub

    Hub.objects.filter(hub_physical_name="CUSTOMER_H").update(
        hub_physical_name=new_name
    )


def test_files_turbovault_no_longer_generates_are_reported(project, tmp_path):
    _generate(project, tmp_path)
    old = _dbt(tmp_path) / "models/30_raw_vault/CUSTOMER_H.sql"
    _rename_hub("CLIENT_H")

    report = _generate(project, tmp_path)

    stale = {i.message.split(":")[0] for i in _issues(report, "write.stale_file")}
    assert "models/30_raw_vault/CUSTOMER_H.sql" in stale
    assert old.is_file()

    # On request: deleted
    report = _generate(project, tmp_path, remove_stale_files=True)

    assert _issues(report, "write.stale_file_removed")
    assert not old.exists()
    assert not _issues(_generate(project, tmp_path), "write.stale_file")


def test_a_changed_stale_file_stays(project, tmp_path):
    _generate(project, tmp_path)
    old = _dbt(tmp_path) / "models/30_raw_vault/CUSTOMER_H.sql"
    old.write_text("-- edited\n", encoding="utf-8")
    _rename_hub("CLIENT_H")

    report = _generate(project, tmp_path, remove_stale_files=True)

    assert _issues(report, "write.stale_file_changed")
    assert old.is_file()
    # It is the project's now: not reported again
    assert not _issues(_generate(project, tmp_path), "write.stale_file_changed")


def test_models_and_sources_defined_twice_are_reported(project, tmp_path):
    root = _existing_project(tmp_path)
    legacy = root / "models" / "legacy"
    legacy.mkdir(parents=True)
    (legacy / "CUSTOMER_H.sql").write_text("select 1\n", encoding="utf-8")
    (legacy / "_models.yml").write_text(
        "version: 2\nmodels:\n  - name: CUSTOMER_S_v0\n", encoding="utf-8"
    )
    (legacy / "_sources.yml").write_text(
        "version: 2\nsources:\n  - name: crm\n    tables:\n      - name: CUSTOMER\n",
        encoding="utf-8",
    )

    report = _generate(project, tmp_path)

    twice = [i.message for i in _issues(report, "write.model_defined_twice")]
    assert any(
        "'CUSTOMER_H'" in m and "models/legacy/CUSTOMER_H.sql" in m for m in twice
    )
    assert any("'CUSTOMER_S_v0'" in m and "_models.yml" in m for m in twice)
    (source,) = _issues(report, "write.source_defined_twice")
    assert "crm.CUSTOMER" in source.message


def test_replacing_the_projects_own_files_is_reported(project, tmp_path):
    root = _existing_project(tmp_path)
    hub = root / "models/30_raw_vault/CUSTOMER_H.sql"
    hub.parent.mkdir(parents=True)
    hub.write_text("-- the project's version\n", encoding="utf-8")

    report = _generate(project, tmp_path)

    (replaced,) = _issues(report, "write.files_replaced")
    assert "models/30_raw_vault/CUSTOMER_H.sql" in replaced.message
    # TurboVault's file now, recorded: not reported again
    assert not _issues(_generate(project, tmp_path), "write.files_replaced")
