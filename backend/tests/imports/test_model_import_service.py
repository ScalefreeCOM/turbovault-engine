"""Tests for the JSON model importer's link source-mapping wiring.

Covers the two gaps the importer historically left for links:
  * LinkHubSourceMapping rows for each hub key (so the link has a source and
    its hashkey can be generated — validator LNK_003).
  * dependent_child_key link columns (+ their source mappings).
"""

from __future__ import annotations

import pytest
from engine.models import (
    Link,
    LinkColumn,
    LinkHubReference,
    LinkHubSourceMapping,
    LinkSourceMapping,
    SourceColumn,
    SourceSystem,
    SourceTable,
)
from engine.services.model_import_schema import ModelImportSchema
from engine.services.model_import_service import import_model


def _make_source_table(project, table: str, columns: list[str]) -> SourceTable:
    system = SourceSystem.objects.create(
        project=project, schema_name="raw", name="TXN", database_name=table
    )
    src_tbl = SourceTable.objects.create(
        project=project,
        source_system=system,
        physical_table_name=table,
        record_source_value=f"TXN.{table}",
        load_date_value="LOAD_DATE",
    )
    for col in columns:
        SourceColumn.objects.create(
            source_table=src_tbl,
            source_column_physical_name=col,
            source_column_datatype="VARCHAR",
        )
    return src_tbl


@pytest.fixture
def project(db):
    from engine.models import Project

    return Project.objects.create(name="Link Import Test")


def test_nh_link_wires_hub_keys_and_dependent_child_key(project):
    _make_source_table(
        project, "txn", ["TRANSACTION_ID", "CONTRACT_ID", "CUSTOMER_ID", "AMOUNT"]
    )

    schema = ModelImportSchema.model_validate(
        {
            "hubs": [
                {"name": "contract_h", "business_keys": ["CONTRACT_ID"]},
                {"name": "customer_h", "business_keys": ["CUSTOMER_ID"]},
            ],
            "links": [
                {
                    "name": "transaction_contract_customer_nl",
                    "link_type": "non_historized",
                    "hubs": ["contract_h", "customer_h"],
                    "dependent_child_keys": ["TRANSACTION_ID"],
                    "payload_columns": ["AMOUNT"],
                    "source_table": "txn",
                }
            ],
        }
    )

    result = import_model(project.name, schema)
    assert result.errors == []
    assert result.skipped == []

    link = Link.objects.get(
        project=project, link_physical_name="transaction_contract_customer_nl"
    )

    # Both hub references are wired to a staging column in the link's source.
    refs = LinkHubReference.objects.filter(link=link)
    assert refs.count() == 2
    hub_maps = LinkHubSourceMapping.objects.filter(link_hub_reference__link=link)
    assert hub_maps.count() == 2
    mapped = {
        (
            m.link_hub_reference.hub.hub_physical_name,
            m.staging_column.source_column.source_column_physical_name,
        )
        for m in hub_maps
    }
    assert mapped == {("contract_h", "CONTRACT_ID"), ("customer_h", "CUSTOMER_ID")}

    # TRANSACTION_ID becomes a dependent_child_key column with a source mapping.
    dck = LinkColumn.objects.get(link=link, column_name="TRANSACTION_ID")
    assert dck.column_type == LinkColumn.ColumnType.DEPENDENT_CHILD_KEY
    assert LinkSourceMapping.objects.filter(link_column=dck).count() == 1

    # AMOUNT stays a payload column with a source mapping.
    payload = LinkColumn.objects.get(link=link, column_name="AMOUNT")
    assert payload.column_type == LinkColumn.ColumnType.PAYLOAD
    assert LinkSourceMapping.objects.filter(link_column=payload).count() == 1


def test_hub_source_columns_override_for_renamed_fk(project):
    _make_source_table(project, "txn", ["TRANSACTION_ID", "CONTRA_TRANSACTION_ID"])

    schema = ModelImportSchema.model_validate(
        {
            "hubs": [{"name": "transaction_h", "business_keys": ["TRANSACTION_ID"]}],
            "links": [
                {
                    "name": "transaction_contra_nl",
                    "link_type": "non_historized",
                    "hubs": ["transaction_h"],
                    "hub_source_columns": {"transaction_h": "CONTRA_TRANSACTION_ID"},
                    "source_table": "txn",
                }
            ],
        }
    )

    result = import_model(project.name, schema)
    assert result.errors == []

    link = Link.objects.get(project=project, link_physical_name="transaction_contra_nl")
    mapping = LinkHubSourceMapping.objects.get(link_hub_reference__link=link)
    # The override points the transaction_h key at the CONTRA column, not TRANSACTION_ID.
    assert mapping.standard_hub_column.column_name == "TRANSACTION_ID"
    assert (
        mapping.staging_column.source_column.source_column_physical_name
        == "CONTRA_TRANSACTION_ID"
    )


def test_idempotent_reimport_does_not_duplicate_mappings(project):
    _make_source_table(project, "txn", ["TRANSACTION_ID", "CONTRACT_ID"])
    payload = {
        "hubs": [{"name": "contract_h", "business_keys": ["CONTRACT_ID"]}],
        "links": [
            {
                "name": "txn_contract_nl",
                "link_type": "non_historized",
                "hubs": ["contract_h"],
                "dependent_child_keys": ["TRANSACTION_ID"],
                "source_table": "txn",
            }
        ],
    }
    import_model(project.name, ModelImportSchema.model_validate(payload))
    import_model(project.name, ModelImportSchema.model_validate(payload))

    link = Link.objects.get(project=project, link_physical_name="txn_contract_nl")
    assert (
        LinkHubSourceMapping.objects.filter(link_hub_reference__link=link).count() == 1
    )
    assert (
        LinkColumn.objects.filter(link=link, column_name="TRANSACTION_ID").count() == 1
    )
