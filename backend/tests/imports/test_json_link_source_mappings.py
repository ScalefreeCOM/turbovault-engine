"""Regression tests for JSON import of link source mappings.

The JSON export carries a link's full column-level source mappings inside
`source_tables[].columns`, tagged with `link_column_type`. The parser used to
build link columns only from the export's `payload_columns` / `additional_columns`
arrays, so `dependent_child_key` columns — which appear ONLY in the source-table
mappings — were never created and their source mappings were silently dropped.

This dropped source information for both standard links (a dependent child key
on a relationship link) and non-historized links (a degenerate column hashed
into the link key). The tests below build a model, export it to JSON via the
real ModelBuilder, re-import that JSON, and assert the link source mappings
survive the round trip.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine.models import (
    Link,
    LinkColumn,
    LinkHubSourceMapping,
    LinkSourceMapping,
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


def _make_source_table(project: Project) -> None:
    system = SourceSystem.objects.create(
        project=project, schema_name="raw", name="CRM", database_name="orders"
    )
    src_tbl = SourceTable.objects.create(
        project=project,
        source_system=system,
        physical_table_name="orders",
        record_source_value="CRM.orders",
        load_date_value="LOAD_DATE",
    )
    for col in ("O_ORDERKEY", "O_CUSTKEY", "O_COMMENT", "O_TOTALPRICE"):
        SourceColumn.objects.create(
            source_table=src_tbl,
            source_column_physical_name=col,
            source_column_datatype="VARCHAR",
        )


def _export_json(project: Project, tmp_path: Path) -> Path:
    export = ModelBuilder(project).build()
    out = tmp_path / "export.json"
    out.write_text(
        json.dumps(export.model_dump(mode="json"), default=str), encoding="utf-8"
    )
    return out


def _roundtrip(tmp_path: Path, link_type: str) -> Project:
    src = Project.objects.create(name=f"src-{link_type}")
    _make_source_table(src)

    schema = ModelImportSchema.model_validate(
        {
            "hubs": [
                {"name": "ORDER_H", "business_keys": ["O_ORDERKEY"], "source_table": "orders"},
                {"name": "CUSTOMER_H", "business_keys": ["O_CUSTKEY"], "source_table": "orders"},
            ],
            "links": [
                {
                    "name": "ORDERS_CUSTOMERS_L",
                    "link_type": link_type,
                    "hubs": ["ORDER_H", "CUSTOMER_H"],
                    "dependent_child_keys": ["O_COMMENT"],
                    "payload_columns": ["O_TOTALPRICE"] if link_type == "non_historized" else [],
                    "source_table": "orders",
                }
            ],
        }
    )
    result = import_model(src.name, schema)
    assert result.errors == [], result.errors

    json_path = _export_json(src, tmp_path)

    dst = Project.objects.create(name=f"dst-{link_type}")
    report = import_metadata(
        project=dst,
        source=JsonSource(path=json_path),
        options=ImportOptions(skip_snapshots=True),
    )
    assert report.status == "success", report.issues
    return dst


def test_standard_link_dependent_child_key_survives_json_roundtrip(tmp_path):
    dst = _roundtrip(tmp_path, "standard")
    link = Link.objects.get(project=dst, link_physical_name="ORDERS_CUSTOMERS_L")

    # Both hub keys are still wired.
    assert LinkHubSourceMapping.objects.filter(link_hub_reference__link=link).count() == 2

    # The dependent child key column and its source mapping survived.
    dck = LinkColumn.objects.get(link=link, column_name="O_COMMENT")
    assert dck.column_type == LinkColumn.ColumnType.DEPENDENT_CHILD_KEY
    dck_maps = LinkSourceMapping.objects.filter(link_column=dck)
    assert dck_maps.count() == 1
    assert (
        dck_maps.first().staging_column.source_column.source_column_physical_name
        == "O_COMMENT"
    )


def test_non_historized_link_dck_and_payload_survive_json_roundtrip(tmp_path):
    dst = _roundtrip(tmp_path, "non_historized")
    link = Link.objects.get(project=dst, link_physical_name="ORDERS_CUSTOMERS_L")
    assert link.link_type == "non_historized"

    dck = LinkColumn.objects.get(link=link, column_name="O_COMMENT")
    assert dck.column_type == LinkColumn.ColumnType.DEPENDENT_CHILD_KEY
    assert LinkSourceMapping.objects.filter(link_column=dck).count() == 1

    payload = LinkColumn.objects.get(link=link, column_name="O_TOTALPRICE")
    assert payload.column_type == LinkColumn.ColumnType.PAYLOAD
    assert LinkSourceMapping.objects.filter(link_column=payload).count() == 1
