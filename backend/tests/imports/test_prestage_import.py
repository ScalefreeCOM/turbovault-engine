"""Pre-stages through the import pipeline.

A JSON export carries each table's type and a pre-stage's SQL, and imports
back into an identical project. Exports from before pre-stages existed, and
formats with no place for them, leave the project's pre-stages alone; under
``replace_all`` too, since their absence from such a source says nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine.models import (
    Hub,
    HubColumn,
    HubSourceMapping,
    Project,
    SourceColumn,
    SourceSystem,
    SourceTable,
)
from engine.services.export.builder import ModelBuilder
from engine.services.imports import (
    ImportOptions,
    JsonSource,
    SourceMetadataSource,
    import_metadata,
)
from engine.services.staging_service import get_or_create_staging_column

pytestmark = pytest.mark.django_db

ADDRESS_SQL = """select r.ID as CUSTOMER_ID, a.value:street::varchar as STREET
from {{ source('crm', 'CUSTOMER_RAW') }} as r,
     lateral flatten(input => r.PAYLOAD:addresses) as a"""


def _build(name: str) -> Project:
    project = Project.objects.create(name=name)
    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM"
    )
    raw = SourceTable.objects.create(
        project=project, source_system=crm, physical_table_name="CUSTOMER_RAW"
    )
    for column in ("ID", "PAYLOAD"):
        SourceColumn.objects.create(
            source_table=raw,
            source_column_physical_name=column,
            source_column_datatype="VARCHAR",
        )
    address = SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="CUSTOMER_ADDRESS",
        table_type=SourceTable.TableType.PRESTAGE,
        prestage_sql=ADDRESS_SQL,
    )
    customer_id = SourceColumn.objects.create(
        source_table=address,
        source_column_physical_name="CUSTOMER_ID",
        source_column_datatype="VARCHAR",
    )
    SourceColumn.objects.create(
        source_table=address,
        source_column_physical_name="STREET",
        source_column_datatype="VARCHAR",
    )
    SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="ORDER_ITEMS",
        table_type=SourceTable.TableType.PRESTAGE,
    )

    hub = Hub.objects.create(
        project=project,
        hub_physical_name="CUSTOMER_H",
        hub_hashkey_name="hk_customer_h",
    )
    HubSourceMapping.objects.create(
        hub_column=HubColumn.objects.create(hub=hub, column_name="CUSTOMER_ID"),
        staging_column=get_or_create_staging_column(customer_id),
        is_primary_source=True,
    )
    return project


def _export_data(project: Project) -> dict:
    return json.loads(
        json.dumps(ModelBuilder(project).build().model_dump(mode="json"), default=str)
    )


def _write(data: dict, path: Path) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _import(project: Project, path: Path, source=JsonSource, **options):
    report = import_metadata(
        project=project,
        source=source(path=path),
        options=ImportOptions(skip_snapshots=True, **options),
    )
    assert report.status == "success", report.issues
    return report


def _tables(project: Project) -> dict[str, SourceTable]:
    return {
        table.physical_table_name: table
        for table in SourceTable.objects.filter(project=project)
    }


def _source_tables(data: dict) -> list[dict]:
    return [table for system in data["sources"] for table in system["tables"]]


def test_a_json_export_imports_back_with_its_prestages(tmp_path):
    path = _write(_export_data(_build("source")), tmp_path / "model.json")
    target = Project.objects.create(name="target")

    _import(target, path)

    tables = _tables(target)
    assert tables["CUSTOMER_ADDRESS"].table_type == "prestage"
    assert tables["CUSTOMER_ADDRESS"].prestage_sql == ADDRESS_SQL
    assert tables["ORDER_ITEMS"].table_type == "prestage"
    assert tables["ORDER_ITEMS"].prestage_sql is None
    assert tables["CUSTOMER_RAW"].table_type == "physical"
    mapping = HubSourceMapping.objects.get(hub_column__hub__project=target)
    assert mapping.staging_column.source_table == tables["CUSTOMER_ADDRESS"]


def test_reimporting_the_same_export_changes_nothing(tmp_path):
    project = _build("again")
    path = _write(_export_data(project), tmp_path / "model.json")

    report = _import(project, path)

    tables = [e for e in report.plan.entities if e.ref.type == "source_table"]
    assert {e.action for e in tables} == {"unchanged"}


def test_an_export_from_before_prestages_leaves_them_alone(tmp_path):
    project = _build("old_export")
    data = _export_data(project)
    for table in _source_tables(data):
        del table["table_type"]
        del table["prestage_sql"]

    _import(project, _write(data, tmp_path / "old.json"))

    address = _tables(project)["CUSTOMER_ADDRESS"]
    assert address.table_type == "prestage"
    assert address.prestage_sql == ADDRESS_SQL


def test_an_export_without_the_sql_clears_it(tmp_path):
    project = _build("cleared")
    data = _export_data(project)
    for table in _source_tables(data):
        if table["table_name"] == "CUSTOMER_ADDRESS":
            table["prestage_sql"] = None

    _import(project, _write(data, tmp_path / "cleared.json"))

    address = _tables(project)["CUSTOMER_ADDRESS"]
    assert address.table_type == "prestage"
    assert address.prestage_sql is None


def test_an_unknown_table_type_is_rejected(tmp_path):
    project = _build("typo")
    data = _export_data(project)
    for table in _source_tables(data):
        if table["table_name"] == "CUSTOMER_ADDRESS":
            table["table_type"] = "pre-stage"

    report = import_metadata(
        project=project,
        source=JsonSource(path=_write(data, tmp_path / "typo.json")),
        options=ImportOptions(skip_snapshots=True),
    )

    assert report.status != "success"
    assert any(issue.code == "source.invalid_json" for issue in report.issues)
    assert _tables(project)["CUSTOMER_ADDRESS"].table_type == "prestage"


def test_replace_all_from_a_database_catalog_keeps_the_prestages(tmp_path):
    """A catalog lists what the database has: never a pre-stage's model."""
    project = _build("catalog")
    lake = SourceSystem.objects.create(project=project, schema_name="lake", name="Lake")
    SourceTable.objects.create(
        project=project,
        source_system=lake,
        physical_table_name="EVENTS_FLAT",
        table_type=SourceTable.TableType.PRESTAGE,
        prestage_sql="select 1",
    )
    SourceTable.objects.create(
        project=project,
        source_system=SourceSystem.objects.get(project=project, name="CRM"),
        physical_table_name="CUSTOMER_OLD",
    )
    catalog = {
        "format": "source_metadata",
        "format_version": 1,
        "source_systems": [
            {
                "name": "CRM",
                "schema_name": "crm_raw",
                "tables": [
                    {
                        "physical_table_name": "CUSTOMER_RAW",
                        "columns": [{"physical_name": "ID", "datatype": "VARCHAR"}],
                    }
                ],
            }
        ],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    _import(project, path, source=SourceMetadataSource, conflict_strategy="replace_all")

    tables = _tables(project)
    assert {"CUSTOMER_ADDRESS", "ORDER_ITEMS", "EVENTS_FLAT"} <= set(tables)
    assert "CUSTOMER_OLD" not in tables
    assert SourceSystem.objects.filter(project=project, name="Lake").exists()


def test_replace_all_from_a_json_export_deletes_a_prestage_it_leaves_out(tmp_path):
    project = _build("replace")
    data = _export_data(project)
    for system in data["sources"]:
        system["tables"] = [
            table for table in system["tables"] if table["table_name"] != "ORDER_ITEMS"
        ]

    _import(
        project,
        _write(data, tmp_path / "replace.json"),
        conflict_strategy="replace_all",
    )

    tables = _tables(project)
    assert "ORDER_ITEMS" not in tables
    assert tables["CUSTOMER_ADDRESS"].prestage_sql == ADDRESS_SQL
