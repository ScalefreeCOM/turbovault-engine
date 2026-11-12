"""Stored output attributes (generation_config, issue #442) through JSON.

A JSON export must import back with every entity's generation_config intact,
and an export written before the field existed must leave the project's alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine.models import (
    Hub,
    HubColumn,
    HubSourceMapping,
    Link,
    LinkHubReference,
    Project,
    Satellite,
    SatelliteColumn,
    SourceColumn,
    SourceSystem,
    SourceTable,
)
from engine.services.export.builder import ModelBuilder
from engine.services.imports import ImportOptions, JsonSource, import_metadata
from engine.services.staging_service import get_or_create_staging_column

pytestmark = pytest.mark.django_db

STAGE_CONFIG = {"dbt": {"stage": {"file_path": "staging/crm/stg_customer.sql"}}}
HUB_CONFIG = {
    "dbt": {
        "hub": {
            "model_name": "customer_h",
            "file_path": "raw_vault/hubs/customer_h.sql",
            "schema": "rdv_core",
            "tags": ["hub"],
            "custom_config_json": {"unique_key": "hk_customer_h"},
        },
        "effectivity_satellite": {"model_name": "customer_eff"},
    }
}
LINK_CONFIG = {"dbt": {"link": {"alias": "customer_self_link"}}}
SAT_CONFIG = {
    "dbt": {
        "satellite_v0": {"model_name": "customer_s"},
        "satellite_v1": {"materialized": "view"},
    }
}


def _build(name: str) -> Project:
    project = Project.objects.create(name=name)
    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM", database_name="ops"
    )
    customer = SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="customer",
        record_source_value="CRM.customer",
        load_date_value="LOAD_DATE",
        generation_config=STAGE_CONFIG,
    )
    for column in ("C_CUSTKEY", "C_NAME"):
        SourceColumn.objects.create(
            source_table=customer,
            source_column_physical_name=column,
            source_column_datatype="VARCHAR",
        )
    hub = Hub.objects.create(
        project=project,
        hub_physical_name="CUSTOMER_H",
        hub_hashkey_name="hk_customer_h",
        generation_config=HUB_CONFIG,
    )
    key = HubColumn.objects.create(hub=hub, column_name="C_CUSTKEY")
    HubSourceMapping.objects.create(
        hub_column=key,
        staging_column=get_or_create_staging_column(
            SourceColumn.objects.get(source_column_physical_name="C_CUSTKEY")
        ),
        is_primary_source=True,
    )
    link = Link.objects.create(
        project=project,
        link_physical_name="CUSTOMER_CUSTOMER_L",
        link_hashkey_name="hk_customer_customer_l",
        generation_config=LINK_CONFIG,
    )
    LinkHubReference.objects.create(link=link, hub=hub)
    satellite = Satellite.objects.create(
        project=project,
        satellite_physical_name="CUSTOMER_S",
        parent_hub=hub,
        source_table=customer,
        generation_config=SAT_CONFIG,
    )
    SatelliteColumn.objects.create(
        satellite=satellite,
        staging_column=get_or_create_staging_column(
            SourceColumn.objects.get(source_column_physical_name="C_NAME")
        ),
    )
    return project


def _export(project: Project, out: Path) -> Path:
    out.write_text(
        json.dumps(ModelBuilder(project).build().model_dump(mode="json"), default=str),
        encoding="utf-8",
    )
    return out


def _import(project: Project, path: Path) -> None:
    report = import_metadata(
        project=project,
        source=JsonSource(path=path),
        options=ImportOptions(skip_snapshots=True),
    )
    assert report.status == "success", report.issues


def _configs(project: Project) -> dict[str, dict]:
    return {
        "stage": SourceTable.objects.get(project=project).generation_config,
        "hub": Hub.objects.get(project=project).generation_config,
        "link": Link.objects.get(project=project).generation_config,
        "satellite": Satellite.objects.get(project=project).generation_config,
    }


def test_json_round_trip_keeps_generation_config(tmp_path):
    path = _export(_build("attrs-src"), tmp_path / "export.json")
    target = Project.objects.create(name="attrs-dst")

    _import(target, path)

    assert _configs(target) == {
        "stage": STAGE_CONFIG,
        "hub": HUB_CONFIG,
        "link": LINK_CONFIG,
        "satellite": SAT_CONFIG,
    }


def test_older_exports_leave_generation_config_alone(tmp_path):
    project = _build("attrs-old")
    path = _export(project, tmp_path / "export.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    # As written before generation_config existed.
    for system in data["sources"]:
        for table in system["tables"]:
            del table["generation_config"]
    for kind in ("hubs", "links", "satellites", "stages"):
        for definition in data[kind]:
            del definition["generation_config"]
    path.write_text(json.dumps(data), encoding="utf-8")

    _import(project, path)

    assert _configs(project)["hub"] == HUB_CONFIG
    assert _configs(project)["stage"] == STAGE_CONFIG
