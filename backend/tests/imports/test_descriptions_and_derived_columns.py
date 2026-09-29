"""Descriptions and derived columns through the import pipeline.

A JSON export must import back into an identical project: descriptions where
they were set, inherited ones still inherited, derived columns with the
mappings that use them. Formats that have no place for descriptions or derived
columns must leave the project's untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine.models import (
    DerivedColumn,
    Hub,
    HubColumn,
    HubSourceMapping,
    Project,
    Satellite,
    SatelliteColumn,
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

EXPRESSION = "TRIM(C_FIRST) || ' ' || TRIM(C_LAST)"


def _build(name: str) -> Project:
    project = Project.objects.create(name=name)
    crm = SourceSystem.objects.create(
        project=project,
        schema_name="crm_raw",
        name="CRM",
        database_name="ops",
        description="The CRM",
    )
    customer = SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="customer",
        record_source_value="CRM.customer",
        load_date_value="LOAD_DATE",
        description="One row per customer",
    )
    for column, description in (
        ("C_CUSTKEY", "Customer number"),
        ("C_FIRST", None),
        ("C_LAST", None),
    ):
        SourceColumn.objects.create(
            source_table=customer,
            source_column_physical_name=column,
            source_column_datatype="VARCHAR",
            description=description,
        )
    full_name = DerivedColumn.objects.create(
        project=project,
        source_table=customer,
        column_name="FULL_NAME",
        expression=EXPRESSION,
        datatype="VARCHAR(200)",
        description="First and last name",
    )

    hub = Hub.objects.create(
        project=project,
        hub_physical_name="CUSTOMER_H",
        hub_hashkey_name="hk_customer_h",
        description="Everyone who ordered",
    )
    key = HubColumn.objects.create(
        hub=hub,
        column_name="C_CUSTKEY",
        target_column_transformation="UPPER([[source_column]])",
        target_column_datatype="VARCHAR(20)",
    )
    HubSourceMapping.objects.create(
        hub_column=key,
        staging_column=get_or_create_staging_column(
            SourceColumn.objects.get(source_column_physical_name="C_CUSTKEY")
        ),
        is_primary_source=True,
    )
    satellite = Satellite.objects.create(
        project=project,
        satellite_physical_name="CUSTOMER_S",
        parent_hub=hub,
        source_table=customer,
        description="Customer details",
    )
    SatelliteColumn.objects.create(
        satellite=satellite,
        staging_column=get_or_create_staging_column(full_name),
        description="Name on the invoice",
    )
    return project


def _export(project: Project, out: Path) -> Path:
    out.write_text(
        json.dumps(ModelBuilder(project).build().model_dump(mode="json"), default=str),
        encoding="utf-8",
    )
    return out


def _import(project: Project, path: Path, source=JsonSource):
    report = import_metadata(
        project=project,
        source=source(path=path),
        options=ImportOptions(skip_snapshots=True),
    )
    assert report.status == "success", report.issues
    return report


# ---------------------------------------------------------------------------
# JSON round trip
# ---------------------------------------------------------------------------


def test_json_round_trip_keeps_descriptions(tmp_path):
    path = _export(_build("docs-src"), tmp_path / "export.json")
    dst = Project.objects.create(name="docs-dst")
    _import(dst, path)

    assert SourceSystem.objects.get(project=dst).description == "The CRM"
    assert SourceTable.objects.get(project=dst).description == "One row per customer"
    assert (
        SourceColumn.objects.get(
            source_table__project=dst, source_column_physical_name="C_CUSTKEY"
        ).description
        == "Customer number"
    )
    assert Hub.objects.get(project=dst).description == "Everyone who ordered"
    assert Satellite.objects.get(project=dst).description == "Customer details"
    assert SatelliteColumn.objects.get(satellite__project=dst).description == (
        "Name on the invoice"
    )


def test_json_round_trip_keeps_inherited_descriptions_inherited(tmp_path):
    """The hub column takes the source column's description; the export shows
    it, but importing it back must not freeze it into a copy."""
    path = _export(_build("inherit-src"), tmp_path / "export.json")
    data = json.loads(path.read_text())
    docs = data["hubs"][0]["column_descriptions"]["C_CUSTKEY"]
    assert docs == {"description": None, "source_description": "Customer number"}

    dst = Project.objects.create(name="inherit-dst")
    _import(dst, path)
    assert HubColumn.objects.get(hub__project=dst).description is None


def test_json_round_trip_keeps_derived_columns_and_their_mappings(tmp_path):
    path = _export(_build("derived-src"), tmp_path / "export.json")
    dst = Project.objects.create(name="derived-dst")
    _import(dst, path)

    derived = DerivedColumn.objects.get(project=dst)
    assert (derived.column_name, derived.expression, derived.datatype) == (
        "FULL_NAME",
        EXPRESSION,
        "VARCHAR(200)",
    )
    assert derived.description == "First and last name"
    # The satellite reads the derived column, not a new source column of that name.
    column = SatelliteColumn.objects.get(satellite__project=dst)
    assert column.staging_column.derived_column == derived
    assert not SourceColumn.objects.filter(
        source_table__project=dst, source_column_physical_name="FULL_NAME"
    ).exists()


def test_json_round_trip_keeps_transformation_datatypes(tmp_path):
    path = _export(_build("types-src"), tmp_path / "export.json")
    dst = Project.objects.create(name="types-dst")
    _import(dst, path)

    key = HubColumn.objects.get(hub__project=dst)
    assert key.target_column_transformation == "UPPER([[source_column]])"
    assert key.target_column_datatype == "VARCHAR(20)"


def test_older_exports_leave_derived_columns_alone(tmp_path):
    """An export from before derived columns has no `derived_columns` key."""
    project = _build("older")
    path = _export(project, tmp_path / "export.json")
    data = json.loads(path.read_text())
    for system in data["sources"]:
        for table in system["tables"]:
            del table["derived_columns"]
    path.write_text(json.dumps(data), encoding="utf-8")

    _import(project, path)
    assert DerivedColumn.objects.filter(project=project).count() == 1


def test_the_plan_reports_description_and_derived_column_changes(tmp_path):
    project = _build("plan")
    path = _export(project, tmp_path / "export.json")
    data = json.loads(path.read_text())
    table = data["sources"][0]["tables"][0]
    table["description"] = "Customers, deduplicated"
    next(c for c in table["columns"] if c["column_name"] == "C_CUSTKEY")[
        "description"
    ] = "Customer id"
    table["derived_columns"][0]["expression"] = "C_FIRST || C_LAST"
    path.write_text(json.dumps(data), encoding="utf-8")

    report = import_metadata(
        project=project,
        source=JsonSource(path=path),
        options=ImportOptions(skip_snapshots=True, dry_run=True),
    )
    planned = next(e for e in report.plan.entities if e.ref.type == "source_table")
    assert planned.action == "update"
    changes = {change.field: change for change in planned.changes}
    assert changes["description"].after == "Customers, deduplicated"
    assert changes["columns.C_CUSTKEY.description"].before == "Customer number"
    assert changes["columns.C_CUSTKEY.description"].after == "Customer id"
    expression = changes["derived_columns.FULL_NAME.expression"]
    assert (expression.before, expression.after) == (EXPRESSION, "C_FIRST || C_LAST")
    assert expression.path == ["derived_columns", "FULL_NAME", "expression"]
    # What didn't change isn't listed.
    assert set(changes) == {
        "description",
        "columns.C_CUSTKEY.description",
        "derived_columns.FULL_NAME.expression",
    }


# ---------------------------------------------------------------------------
# Formats without descriptions
# ---------------------------------------------------------------------------


def _source_metadata(tmp_path: Path, *, with_descriptions: bool) -> Path:
    def described(value: str) -> dict:
        return {"description": value} if with_descriptions else {}

    payload = {
        "format": "source_metadata",
        "format_version": 1,
        "source_systems": [
            {
                "name": "CRM",
                "schema_name": "crm_raw",
                "database_name": "ops",
                **described("From the database"),
                "tables": [
                    {
                        "physical_table_name": "customer",
                        **described("Table comment"),
                        "columns": [
                            {
                                "physical_name": "C_CUSTKEY",
                                "datatype": "VARCHAR",
                                **described("Column comment"),
                            },
                            {"physical_name": "C_FIRST", "datatype": "VARCHAR"},
                        ],
                    }
                ],
            }
        ],
    }
    out = tmp_path / "collected.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


def test_database_import_stores_comments_as_descriptions(tmp_path):
    project = Project.objects.create(name="db-comments")
    _import(
        project,
        _source_metadata(tmp_path, with_descriptions=True),
        SourceMetadataSource,
    )

    assert SourceSystem.objects.get(project=project).description == "From the database"
    assert SourceTable.objects.get(project=project).description == "Table comment"
    assert (
        SourceColumn.objects.get(
            source_table__project=project, source_column_physical_name="C_CUSTKEY"
        ).description
        == "Column comment"
    )


def test_import_without_descriptions_keeps_the_projects(tmp_path):
    project = _build("keep")
    _import(
        project,
        _source_metadata(tmp_path, with_descriptions=False),
        SourceMetadataSource,
    )

    assert SourceSystem.objects.get(project=project).description == "The CRM"
    assert (
        SourceTable.objects.get(project=project).description == "One row per customer"
    )
    assert (
        SourceColumn.objects.get(
            source_table__project=project, source_column_physical_name="C_CUSTKEY"
        ).description
        == "Customer number"
    )
    assert DerivedColumn.objects.filter(project=project).count() == 1


def test_a_mapping_to_a_derived_columns_name_binds_to_it(tmp_path, workbook_factory):
    """An Excel file can't define derived columns, but it can map one the
    project already has. That binds to it rather than inventing a source
    column of the same name."""
    project = _build("excel")
    path = workbook_factory(
        {
            "source_data": [
                [
                    "source_system",
                    "source_schema_physical_name",
                    "source_table_physical_name",
                    "source_table_identifier",
                    "source_database_name",
                    "record_source_column",
                    "load_date_column",
                ],
                [
                    "CRM",
                    "crm_raw",
                    "customer",
                    "crm.customer",
                    "ops",
                    "CRM.customer",
                    "LOAD_DATE",
                ],
            ],
            "standard_hub": [
                [
                    "target_hub_table_physical_name",
                    "hub_identifier",
                    "target_primary_key_physical_name",
                    "business_key_physical_name",
                    "source_table_identifier",
                    "source_column_physical_name",
                    "is_primary_source",
                ],
                [
                    "NAME_H",
                    "h_name",
                    "hk_name_h",
                    "FULL_NAME",
                    "crm.customer",
                    "FULL_NAME",
                    True,
                ],
            ],
        }
    )
    from engine.services.imports import ExcelSource

    report = import_metadata(
        project=project,
        source=ExcelSource(path=path),
        options=ImportOptions(skip_snapshots=True),
    )
    assert report.status == "success", report.issues

    mapping = HubSourceMapping.objects.get(hub_column__hub__hub_physical_name="NAME_H")
    assert mapping.staging_column.derived_column.column_name == "FULL_NAME"
    assert not SourceColumn.objects.filter(
        source_table__project=project, source_column_physical_name="FULL_NAME"
    ).exists()
