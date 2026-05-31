"""Tests for the ``source_metadata`` import format.

Two layers:

1. Parser unit tests — pure function over a temp JSON file. No database.
2. End-to-end import — exercises the full pipeline via ``import_metadata``
   with a ``SourceMetadataSource`` and asserts ORM state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from engine.models import SourceColumn, SourceSystem, SourceTable
from engine.services.imports import (
    ImportOptions,
    SourceMetadataSource,
    import_metadata,
)
from engine.services.imports.errors import Code, PipelineAbort
from engine.services.imports.parsers.source_metadata import (
    FORMAT_NAME,
    SUPPORTED_FORMAT_VERSIONS,
    parse_source_metadata,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_payload(tmp_path: Path, payload: dict[str, Any]) -> Path:
    out = tmp_path / "collected.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


def _valid_payload() -> dict[str, Any]:
    return {
        "format": "source_metadata",
        "format_version": 1,
        "source_systems": [
            {
                "name": "CRM",
                "schema_name": "CRM",
                "database_name": "PROD_DB",
                "description": "Customer data warehouse",
                "tables": [
                    {
                        "physical_table_name": "CUSTOMERS",
                        "alias": "customer",
                        "record_source_value": "CRM_RAW",
                        "load_date_value": "_LOAD_DATE",
                        "description": "Master customer list",
                        "columns": [
                            {
                                "physical_name": "CUSTOMER_ID",
                                "datatype": "NUMBER(38,0)",
                                "ordinal_position": 1,
                                "is_nullable": False,
                                "description": "PK",
                            },
                            {
                                "physical_name": "EMAIL",
                                "datatype": "VARCHAR(255)",
                                "ordinal_position": 2,
                                "is_nullable": True,
                            },
                        ],
                    },
                    {
                        "physical_table_name": "ORDERS",
                        "columns": [
                            {
                                "physical_name": "ORDER_ID",
                                "datatype": "NUMBER(38,0)",
                            }
                        ],
                    },
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Parser — happy path + defaults
# ---------------------------------------------------------------------------


def test_parse_happy_path(tmp_path: Path) -> None:
    path = _write_payload(tmp_path, _valid_payload())
    domain = parse_source_metadata(path)

    assert set(domain.source_systems) == {"CRM"}
    crm = domain.source_systems["CRM"]
    assert crm.schema_name == "CRM"
    assert crm.database_name == "PROD_DB"
    # Tables are keyed by both synthetic identifier and physical name.
    assert "CRM|CUSTOMERS" in crm.tables
    assert "CUSTOMERS" in crm.tables
    customers = crm.tables["CRM|CUSTOMERS"]
    assert customers.physical_name == "CUSTOMERS"
    assert customers.alias == "customer"
    assert customers.record_source_value == "CRM_RAW"
    assert customers.load_date_value == "_LOAD_DATE"
    # Columns are keyed case-insensitively.
    assert set(customers.columns) == {"customer_id", "email"}
    assert customers.columns["customer_id"].datatype == "NUMBER(38,0)"


def test_parse_record_source_defaults_to_system_name(tmp_path: Path) -> None:
    payload = _valid_payload()
    # Strip the explicit record_source — should fall back to the system name.
    del payload["source_systems"][0]["tables"][0]["record_source_value"]
    domain = parse_source_metadata(_write_payload(tmp_path, payload))
    customers = domain.source_systems["CRM"].tables["CRM|CUSTOMERS"]
    assert customers.record_source_value == "CRM"


def test_parse_load_date_defaults_to_sysdate(tmp_path: Path) -> None:
    payload = _valid_payload()
    del payload["source_systems"][0]["tables"][0]["load_date_value"]
    domain = parse_source_metadata(_write_payload(tmp_path, payload))
    customers = domain.source_systems["CRM"].tables["CRM|CUSTOMERS"]
    assert customers.load_date_value == "sysdate()"


def test_parse_only_populates_source_systems(tmp_path: Path) -> None:
    """The format is source-only by design — hubs / links / sats remain empty
    so a downstream merge import doesn't disturb them."""
    domain = parse_source_metadata(_write_payload(tmp_path, _valid_payload()))
    assert domain.hubs == {}
    assert domain.links == {}
    assert domain.satellites == {}


def test_parse_tolerates_descriptions_at_all_levels(tmp_path: Path) -> None:
    """Descriptions are accepted but currently dropped — assert no crash."""
    payload = _valid_payload()
    # Every level already has a description in _valid_payload; sanity-assert.
    assert payload["source_systems"][0].get("description")
    assert payload["source_systems"][0]["tables"][0].get("description")
    assert payload["source_systems"][0]["tables"][0]["columns"][0].get("description")
    parse_source_metadata(_write_payload(tmp_path, payload))  # no raise


# ---------------------------------------------------------------------------
# Parser — error paths
# ---------------------------------------------------------------------------


def test_parse_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    with pytest.raises(PipelineAbort) as ctx:
        parse_source_metadata(missing)
    assert ctx.value.issue.code == Code.SOURCE_UNREADABLE


def test_parse_malformed_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid", encoding="utf-8")
    with pytest.raises(PipelineAbort) as ctx:
        parse_source_metadata(bad)
    assert ctx.value.issue.code == Code.SOURCE_INVALID_JSON
    # Line number is captured so the operator can find the typo.
    assert ctx.value.issue.location is not None
    assert ctx.value.issue.location.row is not None


def test_parse_unknown_top_level_field(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["evil"] = "drop database prod"
    with pytest.raises(PipelineAbort) as ctx:
        parse_source_metadata(_write_payload(tmp_path, payload))
    assert ctx.value.issue.code == Code.SOURCE_INVALID_JSON


def test_parse_unknown_column_field_rejected(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["source_systems"][0]["tables"][0]["columns"][0]["evil"] = "x"
    with pytest.raises(PipelineAbort) as ctx:
        parse_source_metadata(_write_payload(tmp_path, payload))
    assert ctx.value.issue.code == Code.SOURCE_INVALID_JSON


def test_parse_missing_required_field(tmp_path: Path) -> None:
    payload = _valid_payload()
    del payload["source_systems"][0]["tables"][0]["physical_table_name"]
    with pytest.raises(PipelineAbort) as ctx:
        parse_source_metadata(_write_payload(tmp_path, payload))
    assert ctx.value.issue.code == Code.SOURCE_INVALID_JSON


def test_parse_unsupported_format_version(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["format_version"] = 999
    with pytest.raises(PipelineAbort) as ctx:
        parse_source_metadata(_write_payload(tmp_path, payload))
    assert ctx.value.issue.code == Code.SOURCE_INVALID_JSON
    assert "format_version" in ctx.value.issue.message
    assert "999" in ctx.value.issue.message


def test_supported_versions_includes_one() -> None:
    """Sanity guard — keep this in sync with the constant if we ever rev v2."""
    assert 1 in SUPPORTED_FORMAT_VERSIONS
    assert FORMAT_NAME == "source_metadata"


# ---------------------------------------------------------------------------
# End-to-end via import_metadata
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_end_to_end_creates_source_metadata(project, tmp_path: Path) -> None:
    """Full pipeline: parse → validate → plan → execute → report."""
    payload = _valid_payload()
    path = _write_payload(tmp_path, payload)

    report = import_metadata(
        project=project,
        source=SourceMetadataSource(path=path),
        options=ImportOptions(conflict_strategy="merge"),
    )

    assert report.status == "success", report.issues
    assert report.error_count == 0
    assert report.source_type == "source_metadata"

    # ORM state matches the payload.
    crm = SourceSystem.objects.get(project=project, schema_name="CRM")
    assert crm.database_name == "PROD_DB"
    customers = SourceTable.objects.get(
        source_system=crm, physical_table_name="CUSTOMERS"
    )
    assert customers.alias == "customer"
    assert customers.record_source_value == "CRM_RAW"
    assert customers.load_date_value == "_LOAD_DATE"
    col_names = sorted(
        SourceColumn.objects.filter(source_table=customers).values_list(
            "source_column_physical_name", flat=True
        )
    )
    assert col_names == ["CUSTOMER_ID", "EMAIL"]


@pytest.mark.django_db
def test_end_to_end_is_idempotent_under_merge(project, tmp_path: Path) -> None:
    """Re-importing the same payload should leave row counts unchanged."""
    path = _write_payload(tmp_path, _valid_payload())
    import_metadata(
        project=project,
        source=SourceMetadataSource(path=path),
        options=ImportOptions(conflict_strategy="merge"),
    )
    first_systems = SourceSystem.objects.filter(project=project).count()
    first_tables = SourceTable.objects.filter(source_system__project=project).count()
    first_columns = SourceColumn.objects.filter(
        source_table__source_system__project=project
    ).count()

    import_metadata(
        project=project,
        source=SourceMetadataSource(path=path),
        options=ImportOptions(conflict_strategy="merge"),
    )

    assert SourceSystem.objects.filter(project=project).count() == first_systems
    assert (
        SourceTable.objects.filter(source_system__project=project).count()
        == first_tables
    )
    assert (
        SourceColumn.objects.filter(source_table__source_system__project=project).count()
        == first_columns
    )


@pytest.mark.django_db
def test_end_to_end_dry_run_leaves_no_rows(project, tmp_path: Path) -> None:
    path = _write_payload(tmp_path, _valid_payload())
    report = import_metadata(
        project=project,
        source=SourceMetadataSource(path=path),
        options=ImportOptions(conflict_strategy="merge", dry_run=True),
    )
    assert report.status == "success"
    assert report.is_dry_run is True
    assert SourceSystem.objects.filter(project=project).count() == 0
    # The plan should describe what would be created.
    assert report.plan.counts.totals["create"] > 0
