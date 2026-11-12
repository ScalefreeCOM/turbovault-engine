"""Output attributes through JSON export, import and generation (#442).

A project whose models carry the file paths, names and configs of the project
they came from must keep them through a JSON export/import, and generating
the imported project must write the models there again.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from engine.models import (
    PIT,
    Hub,
    HubColumn,
    HubSourceMapping,
    Project,
    Satellite,
    SatelliteColumn,
    SnapshotControlLogic,
    SnapshotControlTable,
    SourceColumn,
    SourceSystem,
    SourceTable,
)
from engine.services.export.builder import ModelBuilder
from engine.services.generation import GenerationOptions, generate
from engine.services.imports import ImportOptions, JsonSource, import_metadata
from engine.services.staging_service import get_or_create_staging_column

pytestmark = pytest.mark.django_db

STAGE_ATTRIBUTES = {"dbt": {"stage": {"file_path": "staging/stg_customers.sql"}}}
HUB_ATTRIBUTES = {
    "dbt": {
        "hub": {
            "file_path": "raw_vault/customer_h.sql",
            "alias": "customer_hub",
            "schema": "raw",
            "materialized": "incremental",
            "tags": ["raw", "daily"],
            "custom_config_json": {
                "unique_key": "hk_customer_h",
                "persist_docs": {"relation": True},
            },
        },
        "record_tracking_satellite": {"model_name": "customer_tracking"},
    }
}
SATELLITE_ATTRIBUTES = {
    "dbt": {
        "satellite_v0": {"file_path": "raw_vault/customer_s.sql"},
        "satellite_v1": {"model_name": "customer_s_current", "alias": "customer"},
    }
}
PIT_ATTRIBUTES = {
    "dbt": {
        "pit": {
            "file_path": "marts/customer_pit.sql",
            "custom_config_json": {"post_hook": "{{ my_pit_cleanup() }}"},
        }
    }
}
CONTROL_ATTRIBUTES = {"dbt": {"snapshot_control_v1": {"model_name": "snapshot_dates"}}}


def _build(name: str, *, with_attributes: bool = True) -> Project:
    project = Project.objects.create(name=name)
    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM"
    )
    customer = SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="customer",
        record_source_value="CRM.customer",
        load_date_value="LOAD_DATE",
    )
    columns = {
        column: SourceColumn.objects.create(
            source_table=customer,
            source_column_physical_name=column,
            source_column_datatype="VARCHAR",
        )
        for column in ("C_CUSTKEY", "C_NAME")
    }
    hub = Hub.objects.create(
        project=project,
        hub_physical_name="CUSTOMER_H",
        hub_hashkey_name="hk_customer_h",
        create_record_tracking_satellite=True,
    )
    key = HubColumn.objects.create(hub=hub, column_name="C_CUSTKEY")
    HubSourceMapping.objects.create(
        hub_column=key,
        staging_column=get_or_create_staging_column(columns["C_CUSTKEY"]),
        is_primary_source=True,
    )
    satellite = Satellite.objects.create(
        project=project,
        satellite_physical_name="CUSTOMER_S",
        parent_hub=hub,
        source_table=customer,
    )
    SatelliteColumn.objects.create(
        satellite=satellite,
        staging_column=get_or_create_staging_column(columns["C_NAME"]),
    )
    control = SnapshotControlTable.objects.create(project=project, name="control_snap")
    logic = SnapshotControlLogic.objects.create(
        snapshot_control_table=control,
        snapshot_control_logic_column_name="is_active",
        snapshot_component=SnapshotControlLogic.SnapshotComponent.DAILY,
        snapshot_forever=True,
    )
    pit = PIT.objects.create(
        project=project,
        pit_physical_name="CUSTOMER_BP",
        tracked_entity_type="hub",
        tracked_hub=hub,
        snapshot_control_table=control,
        snapshot_control_logic=logic,
    )
    pit.satellites.add(satellite)

    if with_attributes:
        for obj, attributes in (
            (customer, STAGE_ATTRIBUTES),
            (hub, HUB_ATTRIBUTES),
            (satellite, SATELLITE_ATTRIBUTES),
            (pit, PIT_ATTRIBUTES),
            (control, CONTROL_ATTRIBUTES),
        ):
            obj.generation_config = attributes
            obj.full_clean(validate_unique=False, validate_constraints=False)
            obj.save()
    return project


def _export(project: Project, out: Path) -> Path:
    out.write_text(
        json.dumps(ModelBuilder(project).build().model_dump(mode="json"), default=str),
        encoding="utf-8",
    )
    return out


def _import(project: Project, path: Path, **options):
    report = import_metadata(
        project=project, source=JsonSource(path=path), options=ImportOptions(**options)
    )
    assert report.status == "success", report.issues
    return report


def _stored(project: Project) -> dict[str, dict]:
    return {
        "stage": SourceTable.objects.get(project=project).generation_config,
        "hub": Hub.objects.get(project=project).generation_config,
        "satellite": Satellite.objects.get(project=project).generation_config,
        "pit": PIT.objects.get(project=project).generation_config,
        "control": SnapshotControlTable.objects.get(project=project).generation_config,
    }


EXPECTED = {
    "stage": STAGE_ATTRIBUTES,
    "hub": HUB_ATTRIBUTES,
    "satellite": SATELLITE_ATTRIBUTES,
    "pit": PIT_ATTRIBUTES,
    "control": CONTROL_ATTRIBUTES,
}


def test_json_export_carries_the_attributes(tmp_path):
    data = json.loads(_export(_build("export"), tmp_path / "e.json").read_text())
    assert data["stages"][0]["generation_config"] == STAGE_ATTRIBUTES
    assert data["hubs"][0]["generation_config"] == HUB_ATTRIBUTES
    assert data["satellites"][0]["generation_config"] == SATELLITE_ATTRIBUTES
    assert data["pits"][0]["generation_config"] == PIT_ATTRIBUTES
    assert data["snapshot_controls"][0]["generation_config"] == CONTROL_ATTRIBUTES
    # Unset attributes are left out, not written as null.
    assert data["links"] == [] and "alias" not in json.dumps(
        data["stages"][0]["generation_config"]
    )


def test_json_round_trip_keeps_the_attributes(tmp_path):
    path = _export(_build("src"), tmp_path / "export.json")
    dst = Project.objects.create(name="dst")
    _import(dst, path)
    assert _stored(dst) == EXPECTED


def test_reimport_is_unchanged(tmp_path):
    project = _build("again")
    path = _export(project, tmp_path / "export.json")
    report = _import(project, path, dry_run=True)
    changed = [e for e in report.plan.entities if e.changes]
    assert changed == [], [(e.ref, e.changes) for e in changed]


def test_changed_attributes_are_reported_and_applied(tmp_path):
    project = _build("change")
    path = _export(project, tmp_path / "export.json")
    data = json.loads(path.read_text())
    data["hubs"][0]["generation_config"]["dbt"]["hub"]["alias"] = "hub_customer"
    path.write_text(json.dumps(data), encoding="utf-8")

    report = _import(project, path)
    hub_entry = next(e for e in report.plan.entities if e.ref.type == "hub")
    change = next(c for c in hub_entry.changes if c.field == "generation_config")
    assert change.before["dbt"]["hub"]["alias"] == "customer_hub"
    assert change.after["dbt"]["hub"]["alias"] == "hub_customer"
    assert Hub.objects.get(project=project).generation_config["dbt"]["hub"][
        "alias"
    ] == ("hub_customer")


def test_export_names_the_entity_with_an_unknown_output_kind():
    """A kind written past validation (e.g. via `.update()`) fails with the
    entity named, not with a bare schema error."""
    project = _build("bad-kind")
    Hub.objects.filter(project=project).update(
        generation_config={"dbt": {"satellite_v2": {"model_name": "x"}}}
    )
    with pytest.raises(ValueError) as excinfo:
        ModelBuilder(project).build()
    message = str(excinfo.value)
    assert "Invalid generation_config on hub '" in message
    assert "dbt: unknown output kind 'satellite_v2'" in message


def _issue_codes(report) -> list[str]:
    return [issue.code for issue in report.issues]


def test_changed_snapshot_control_attributes_are_reported(tmp_path):
    """Snapshot controls have no plan entry: the change is an info issue."""
    project = _build("snap-change")
    path = _export(project, tmp_path / "export.json")
    data = json.loads(path.read_text())
    data["snapshot_controls"][0]["generation_config"] = {
        "dbt": {"snapshot_control_v1": {"model_name": "snapshots_daily"}}
    }
    path.write_text(json.dumps(data), encoding="utf-8")

    report = _import(project, path)
    updated = [
        issue
        for issue in report.issues
        if issue.code == "execute.snapshot_control_attributes_updated"
    ]
    assert len(updated) == 1 and updated[0].severity == "info"
    assert "snapshots_daily" in updated[0].message
    assert SnapshotControlTable.objects.get(project=project).generation_config == {
        "dbt": {"snapshot_control_v1": {"model_name": "snapshots_daily"}}
    }

    again = _import(project, path, dry_run=True)
    assert "execute.snapshot_control_attributes_updated" not in _issue_codes(again)


def test_snapshot_control_attributes_without_a_table_warn(tmp_path):
    """Without a PIT the import creates no snapshot control, so the
    attributes can't be stored; that must not go unnoticed."""
    path = _export(_build("snap-src"), tmp_path / "export.json")
    data = json.loads(path.read_text())
    data["pits"] = []
    path.write_text(json.dumps(data), encoding="utf-8")

    dst = Project.objects.create(name="snap-dst")
    report = _import(dst, path)
    warnings = [
        issue
        for issue in report.issues
        if issue.code == "execute.snapshot_control_not_found"
    ]
    assert len(warnings) == 1 and warnings[0].severity == "warning"
    assert not SnapshotControlTable.objects.filter(project=dst).exists()


def test_older_exports_keep_the_projects_attributes(tmp_path):
    """An export from before #442 has no `generation_config` keys."""
    project = _build("older")
    path = _export(_build("plain", with_attributes=False), tmp_path / "e.json")
    data = json.loads(path.read_text())
    for section in ("stages", "hubs", "satellites", "pits", "snapshot_controls"):
        for definition in data[section]:
            del definition["generation_config"]
    path.write_text(json.dumps(data), encoding="utf-8")

    _import(project, path)
    assert _stored(project) == EXPECTED


def test_invalid_attributes_in_json_are_rejected(tmp_path):
    path = _export(_build("bad"), tmp_path / "export.json")
    data = json.loads(path.read_text())
    data["hubs"][0]["generation_config"]["dbt"]["hub"]["file_path"] = "../../escape.sql"
    path.write_text(json.dumps(data), encoding="utf-8")

    report = import_metadata(
        project=Project.objects.create(name="bad-dst"),
        source=JsonSource(path=path),
        options=ImportOptions(),
    )
    assert report.status != "success"
    assert any("must stay inside models/" in issue.message for issue in report.issues)


def test_imported_project_regenerates_with_the_original_layout(tmp_path):
    path = _export(_build("gen-src"), tmp_path / "export.json")
    dst = Project.objects.create(name="gen-dst")
    _import(dst, path)

    out = tmp_path / "dbt"
    report = generate(
        project=dst,
        output_type="dbt",
        output_path=out,
        options=GenerationOptions(use_db_templates=False),
    )
    assert report.status == "success", report.issues
    files = {
        path.relative_to(out).as_posix() for path in (out / "models").rglob("*.sql")
    }
    assert {
        "models/staging/stg_customers.sql",
        "models/raw_vault/customer_h.sql",
        "models/raw_vault/customer_s.sql",
        "models/03_raw_vault/customer_s_current.sql",
        "models/03_raw_vault/customer_tracking.sql",
        "models/marts/customer_pit.sql",
        "models/00_control/control_snap_v0.sql",
        "models/00_control/snapshot_dates.sql",
    } == files

    hub_sql = (out / "models/raw_vault/customer_h.sql").read_text()
    assert "alias='customer_hub'" in hub_sql
    assert "schema='raw'" in hub_sql
    assert "tags=['raw', 'daily']" in hub_sql
    assert "unique_key='hk_customer_h'," in hub_sql
    assert "persist_docs={'relation': True}," in hub_sql
    assert "- name: stg_customers" in hub_sql
    pit_sql = (out / "models/marts/customer_pit.sql").read_text()
    # The stored post_hook replaces the default clean-up hook.
    assert "post_hook='{{ my_pit_cleanup() }}'," in pit_sql
    assert "clean_up_pit" not in pit_sql
    assert "- customer_s\n" in pit_sql
    assert "snapshot_relation: snapshot_dates" in pit_sql
    assert "tracked_entity: customer_h" in pit_sql
    v1_yml = yaml.safe_load(
        (out / "models/03_raw_vault/customer_s_current.yml").read_text()
    )
    assert v1_yml["models"][0]["name"] == "customer_s_current"


def test_standard_paths_after_import(tmp_path):
    path = _export(_build("std-src"), tmp_path / "export.json")
    dst = Project.objects.create(name="std-dst")
    _import(dst, path)

    out = tmp_path / "dbt"
    report = generate(
        project=dst,
        output_type="dbt",
        output_path=out,
        options=GenerationOptions(use_db_templates=False, use_original_paths=False),
    )
    assert report.status == "success", report.issues
    names = {path.stem for path in (out / "models").rglob("*.sql")}
    assert {"stg__crm__customer", "CUSTOMER_H", "CUSTOMER_S_v0", "CUSTOMER_BP"} <= names
