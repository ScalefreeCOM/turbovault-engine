"""Round-trip tests for hub and link column transformations.

Column transformations (hard business rules expressed in SQL) used to exist on
``SatelliteColumn`` only. A business key frequently needs normalising before it
is hashed — trimming, upper-casing, casting — and without an equivalent field on
``HubColumn``/``LinkColumn`` the hashkey was computed from the RAW value, so the
same business key arriving from another source system produced a different
hashkey.

These tests pin the JSON export/import round trip of the new fields, including
the conditional-write behaviour introduced in PR #198: a parser that supplies no
transformation (Excel, SQLite, IRiS) must never clear one set in Django Admin.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine.models import (
    HubColumn,
    LinkColumn,
    Project,
    SourceColumn,
    SourceSystem,
    SourceTable,
)
from engine.services.export.builder import ModelBuilder
from engine.services.imports import ImportOptions, JsonSource, import_metadata
from engine.services.model_import_schema import ModelImportSchema
from engine.services.model_import_service import import_model

pytestmark = pytest.mark.django_db

HUB_TRANSFORMATION = "UPPER(TRIM([[source_column]]))"
LINK_TRANSFORMATION = "CAST([[source_column]] AS INT64)"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table(
    project: Project, system: SourceSystem, name: str, columns: tuple[str, ...]
) -> SourceTable:
    table = SourceTable.objects.create(
        project=project,
        source_system=system,
        physical_table_name=name,
        record_source_value=f"{system.name}.{name}",
        load_date_value="LOAD_DATE",
    )
    for col in columns:
        SourceColumn.objects.create(
            source_table=table,
            source_column_physical_name=col,
            source_column_datatype="VARCHAR",
        )
    return table


def _write_export(project: Project, out: Path) -> dict:
    data = ModelBuilder(project).build().model_dump(mode="json")
    out.write_text(json.dumps(data, default=str), encoding="utf-8")
    return data


def _model(project: Project) -> None:
    """CUSTOMER_H + ORDER_H + a link over `orders` with a dependent child key.

    `CUSTOMER_H` is fed both directly (from `customer.C_CUSTKEY`) and through the
    link (from `orders.O_CUSTKEY`), which is exactly the cross-source case a
    business-key transformation has to survive.
    """
    result = import_model(
        project.name,
        ModelImportSchema.model_validate(
            {
                "hubs": [
                    {
                        "name": "CUSTOMER_H",
                        "business_keys": ["C_CUSTKEY"],
                        "source_table": "customer",
                    },
                    {
                        "name": "ORDER_H",
                        "business_keys": ["O_ORDERKEY"],
                        "source_table": "orders",
                    },
                ],
                "links": [
                    {
                        "name": "ORDER_CUSTOMER_L",
                        "hubs": ["ORDER_H", "CUSTOMER_H"],
                        "source_table": "orders",
                        "hub_source_columns": {"CUSTOMER_H": "O_CUSTKEY"},
                        "dependent_child_keys": ["O_LINENUMBER"],
                    }
                ],
                "satellites": [
                    {
                        "name": "ORDER_S",
                        "parent_hub": "ORDER_H",
                        "columns": ["O_COMMENT"],
                        "source_table": "orders",
                    }
                ],
            }
        ),
    )
    assert result.errors == [], result.errors


def _build_project(name: str, *, with_transformations: bool = True) -> Project:
    project = Project.objects.create(name=name)
    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM", database_name="ops"
    )
    _table(project, crm, "customer", ("C_CUSTKEY", "C_NAME"))
    _table(
        project, crm, "orders", ("O_ORDERKEY", "O_CUSTKEY", "O_LINENUMBER", "O_COMMENT")
    )
    _model(project)

    if with_transformations:
        hub_col = HubColumn.objects.get(
            hub__project=project,
            hub__hub_physical_name="CUSTOMER_H",
            column_name="C_CUSTKEY",
        )
        hub_col.target_column_transformation = HUB_TRANSFORMATION
        hub_col.save(update_fields=["target_column_transformation"])

        link_col = LinkColumn.objects.get(
            link__project=project,
            link__link_physical_name="ORDER_CUSTOMER_L",
            column_name="O_LINENUMBER",
        )
        link_col.target_column_transformation = LINK_TRANSFORMATION
        link_col.save(update_fields=["target_column_transformation"])

    return project


def _reimport(data_path: Path, name: str) -> Project:
    dst = Project.objects.create(name=name)
    report = import_metadata(
        project=dst,
        source=JsonSource(path=data_path),
        options=ImportOptions(skip_snapshots=True),
    )
    assert report.status == "success", report.issues
    return dst


# ---------------------------------------------------------------------------
# Export shape
# ---------------------------------------------------------------------------


def test_export_carries_hub_column_transformation(tmp_path):
    src = _build_project("hub-transform-src")
    data = _write_export(src, tmp_path / "export.json")

    mappings = {
        (hub["hub_name"], m["hub_column"]): m
        for hub in data["hubs"]
        for source in hub["source_tables"]
        for m in source["column_mappings"]
    }
    assert (
        mappings[("CUSTOMER_H", "C_CUSTKEY")]["target_column_transformation"]
        == HUB_TRANSFORMATION
    )
    # A hub column without a rule must not gain one.
    assert mappings[("ORDER_H", "O_ORDERKEY")]["target_column_transformation"] is None


def test_export_carries_link_column_transformation(tmp_path):
    src = _build_project("link-transform-src")
    data = _write_export(src, tmp_path / "export.json")

    columns = {
        m["link_column_name"]: m
        for link in data["links"]
        for source in link["source_tables"]
        for m in source["columns"]
    }
    assert columns["O_LINENUMBER"]["link_column_type"] == "dependent_child_key"
    assert (
        columns["O_LINENUMBER"]["target_column_transformation"] == LINK_TRANSFORMATION
    )
    # The link's business-key mapping reports the referenced HUB column's rule,
    # so a hub that is only ever loaded through a link keeps its transformation.
    assert columns["C_CUSTKEY"]["link_column_type"] == "business_key"
    assert columns["C_CUSTKEY"]["target_column_transformation"] == HUB_TRANSFORMATION
    assert columns["O_ORDERKEY"]["target_column_transformation"] is None


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_hub_column_transformation_survives_json_roundtrip(tmp_path):
    src = _build_project("hub-rt-src")
    out = tmp_path / "export.json"
    _write_export(src, out)

    dst = _reimport(out, "hub-rt-dst")

    col = HubColumn.objects.get(
        hub__project=dst, hub__hub_physical_name="CUSTOMER_H", column_name="C_CUSTKEY"
    )
    assert col.target_column_transformation == HUB_TRANSFORMATION

    plain = HubColumn.objects.get(
        hub__project=dst, hub__hub_physical_name="ORDER_H", column_name="O_ORDERKEY"
    )
    assert plain.target_column_transformation in (None, "")


def test_link_column_transformation_survives_json_roundtrip(tmp_path):
    src = _build_project("link-rt-src")
    out = tmp_path / "export.json"
    _write_export(src, out)

    dst = _reimport(out, "link-rt-dst")

    col = LinkColumn.objects.get(
        link__project=dst,
        link__link_physical_name="ORDER_CUSTOMER_L",
        column_name="O_LINENUMBER",
    )
    assert col.column_type == LinkColumn.ColumnType.DEPENDENT_CHILD_KEY
    assert col.target_column_transformation == LINK_TRANSFORMATION


def test_hub_transformation_recovered_from_link_business_key(tmp_path):
    """A hub with no source table of its own is only described by the link's
    business-key mappings; its transformation must be recovered from there."""
    src = _build_project("hub-via-link-src")
    out = tmp_path / "export.json"
    data = _write_export(src, out)

    # Simulate a hub that is loaded exclusively through the link: drop its own
    # source tables from the export.
    for hub in data["hubs"]:
        if hub["hub_name"] == "CUSTOMER_H":
            hub["source_tables"] = []
    stripped = tmp_path / "stripped.json"
    stripped.write_text(json.dumps(data, default=str), encoding="utf-8")

    dst = _reimport(stripped, "hub-via-link-dst")

    col = HubColumn.objects.get(
        hub__project=dst, hub__hub_physical_name="CUSTOMER_H", column_name="C_CUSTKEY"
    )
    assert col.target_column_transformation == HUB_TRANSFORMATION


def test_reimport_without_transformations_preserves_existing_ones(tmp_path):
    """A format that has no transformation concept must not clear one.

    Excel, SQLite and IRiS have no column-transformation field, so their parsers
    always leave the domain field at ``None``. Writing that into
    ``update_or_create`` defaults unconditionally would wipe a transformation the
    user set in Django Admin on the next re-import. This pins the conditional
    write in ``_upsert_hub`` and ``_upsert_link``.
    """
    project = _build_project("preserve-src")

    out = tmp_path / "export.json"
    data = _write_export(project, out)
    for hub in data["hubs"]:
        for source in hub["source_tables"]:
            for m in source["column_mappings"]:
                m["target_column_transformation"] = None
    for link in data["links"]:
        for source in link["source_tables"]:
            for m in source["columns"]:
                m["target_column_transformation"] = None
    out.write_text(json.dumps(data, default=str), encoding="utf-8")

    report = import_metadata(
        project=project,
        source=JsonSource(path=out),
        options=ImportOptions(skip_snapshots=True),
    )
    assert report.status == "success", report.issues

    hub_col = HubColumn.objects.get(
        hub__project=project,
        hub__hub_physical_name="CUSTOMER_H",
        column_name="C_CUSTKEY",
    )
    link_col = LinkColumn.objects.get(
        link__project=project,
        link__link_physical_name="ORDER_CUSTOMER_L",
        column_name="O_LINENUMBER",
    )
    assert hub_col.target_column_transformation == HUB_TRANSFORMATION
    assert link_col.target_column_transformation == LINK_TRANSFORMATION


def test_model_without_transformations_is_unchanged(tmp_path):
    """A project that uses no transformations exports and re-imports exactly as
    it did before the feature: no transformation fields set, no derived columns."""
    src = _build_project("plain-src", with_transformations=False)
    out = tmp_path / "export.json"
    data = _write_export(src, out)

    assert all(
        m["target_column_transformation"] is None
        for hub in data["hubs"]
        for source in hub["source_tables"]
        for m in source["column_mappings"]
    )
    assert all(
        m["target_column_transformation"] is None
        for link in data["links"]
        for source in link["source_tables"]
        for m in source["columns"]
    )
    assert all(stage["derived_columns"] == [] for stage in data["stages"])

    dst = _reimport(out, "plain-dst")
    assert (
        HubColumn.objects.filter(hub__project=dst)
        .exclude(target_column_transformation=None)
        .exclude(target_column_transformation="")
        .count()
        == 0
    )
    assert (
        LinkColumn.objects.filter(link__project=dst)
        .exclude(target_column_transformation=None)
        .exclude(target_column_transformation="")
        .count()
        == 0
    )
