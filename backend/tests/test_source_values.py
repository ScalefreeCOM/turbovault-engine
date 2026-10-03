"""Record Source and Load Date values, from import to the generated stage.

datavault4dbt reads ``rsrc`` / ``ldts`` as a column name unless the text starts
with ``!`` (fixed text) or reads as SQL. These tests pin that reading, the
fallbacks a table gets when its source gives no value, and that whatever a
user writes reaches the stage's YAML unchanged.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml
from django.apps import apps as django_apps
from engine.services.imports.ir import IRDocument, IRRow, IRSheet
from engine.services.imports.parsers.json_parser import parse_json
from engine.services.imports.validation.resolver import resolve
from engine.services.source_values import (
    DEFAULT_LOAD_DATE,
    ValueKind,
    classify,
    default_record_source,
    effective_load_date,
    effective_record_source,
)

# Resolving an import and loading templates both read the database.
pytestmark = pytest.mark.django_db

# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("!CRM", ValueKind.FIXED_TEXT),
        ("!SAP.Accounts", ValueKind.FIXED_TEXT),
        ("!", ValueKind.FIXED_TEXT),
        ("LOAD_TS", ValueKind.COLUMN),
        ("edwRecordSource", ValueKind.COLUMN),
        # Looks like a qualified name, but datavault4dbt reads it as a column.
        ("CRM.customers", ValueKind.COLUMN),
        # Without brackets these are column names outside Trino.
        ("CURRENT_TIMESTAMP", ValueKind.COLUMN),
        ("sysdate()", ValueKind.SQL),
        ("CURRENT_TIMESTAMP()", ValueKind.SQL),
        ("TO_TIMESTAMP(LOAD_TS, 'YYYY-MM-DD')", ValueKind.SQL),
        ("load_ts::timestamp", ValueKind.SQL),
        ("src || '.' || obj", ValueKind.SQL),
        ("'CRM'", ValueKind.SQL),
    ],
)
def test_classify_follows_datavault4dbt(value: str, kind: ValueKind) -> None:
    assert classify(value) is kind


def test_classify_reads_bare_sql_keywords_as_sql_only_on_trino() -> None:
    assert classify("current_timestamp", target_type="trino") is ValueKind.SQL
    assert classify("current_timestamp", target_type="snowflake") is ValueKind.COLUMN


# ---------------------------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------------------------


def test_default_record_source_is_the_system_name_as_fixed_text() -> None:
    assert default_record_source("CRM") == "!CRM"
    assert classify(default_record_source("CRM")) is ValueKind.FIXED_TEXT


@pytest.mark.parametrize("missing", [None, "", "  "])
def test_effective_values_fall_back_when_missing(missing: str | None) -> None:
    assert effective_record_source(missing, source_system_name="CRM") == "!CRM"
    assert effective_load_date(missing) == DEFAULT_LOAD_DATE


def test_effective_values_keep_what_was_given() -> None:
    assert effective_record_source(" LOAD_SRC ", source_system_name="CRM") == (
        "LOAD_SRC"
    )
    assert effective_load_date("LOAD_TS") == "LOAD_TS"


def _source_data_doc(record_source: str | None, load_date: str | None) -> IRDocument:
    headers = [
        "source_table_identifier",
        "source_system",
        "source_schema_physical_name",
        "source_table_physical_name",
        "record_source_column",
        "load_date_column",
    ]
    row = IRRow(
        row_number=2,
        values={
            "source_table_identifier": "SRC1",
            "source_system": "TPCH",
            "source_schema_physical_name": "TPCH_SF1",
            "source_table_physical_name": "Customer",
            "record_source_column": record_source,
            "load_date_column": load_date,
        },
    )
    sheet = IRSheet(name="source_data", headers=headers, rows=[row])
    return IRDocument(source_name="model.xlsx", sheets={"source_data": sheet})


def test_excel_import_fills_a_missing_record_source_with_fixed_text() -> None:
    model, _issues = resolve(_source_data_doc(None, None))

    found = model.get_source_table("SRC1")
    assert found is not None
    _system, table = found
    assert table.record_source_value == "!TPCH"
    assert table.load_date_value == DEFAULT_LOAD_DATE


def test_excel_import_keeps_given_values() -> None:
    model, _issues = resolve(_source_data_doc("!Customer", "LOAD_TS"))

    found = model.get_source_table("SRC1")
    assert found is not None
    _system, table = found
    assert table.record_source_value == "!Customer"
    assert table.load_date_value == "LOAD_TS"


def test_json_import_fills_a_missing_record_source_with_fixed_text(
    tmp_path: Path, django_setup: object
) -> None:
    from engine.services.export.models import (
        ProjectExport,
        SourceSystemDef,
        SourceTableDef,
    )

    export = ProjectExport(
        project_name="fallbacks",
        sources=[
            SourceSystemDef(
                name="CRM",
                schema_name="crm_raw",
                tables=[SourceTableDef(table_name="customer")],
            )
        ],
    )
    path = tmp_path / "export.json"
    path.write_text(export.model_dump_json(), encoding="utf-8")

    found = parse_json(path).get_source_table("CRM|customer")

    assert found is not None
    _system, table = found
    assert table.record_source_value == "!CRM"
    assert table.load_date_value == DEFAULT_LOAD_DATE


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _stage_yaml_metadata(record_source: str, load_date: str) -> dict:
    """Render the stage template and parse its ``yaml_metadata`` block."""
    from engine.services.export.models import StageDefinition
    from engine.services.generation.template_resolver import TemplateResolver

    stage = StageDefinition(
        stage_name="stg__crm__customer",
        source_table="customer",
        source_schema="crm_raw",
        source_system="crm",
        record_source=record_source,
        load_date=load_date,
    )
    template = TemplateResolver().get_sql_template("stage")
    assert template is not None
    sql = template.render(**stage.model_dump())
    start = sql.index("{%- set yaml_metadata -%}") + len("{%- set yaml_metadata -%}")
    end = sql.index("{%- endset -%}")
    return yaml.safe_load(sql[start:end])


@pytest.mark.parametrize(
    ("record_source", "load_date"),
    [
        ("!CRM", "sysdate()"),
        ("RECORD_SOURCE", "LOAD_TS"),
        # The examples from the datavault4dbt docs: quotes inside SQL.
        (
            "CONCAT(source_system, '||', source_object)",
            "PARSE_TIMESTAMP('%Y-%m-%d', LOAD_TS)",
        ),
        ("'CRM'", "TO_TIMESTAMP(LOAD_TS, 'YYYY-MM-DD HH24:MI:SS')"),
        ('!O"Brien # not a comment', "load_ts::timestamp"),
    ],
)
def test_stage_keeps_record_source_and_load_date_exactly(
    django_setup: object, record_source: str, load_date: str
) -> None:
    metadata = _stage_yaml_metadata(record_source, load_date)

    assert metadata["rsrc"] == record_source
    assert metadata["ldts"] == load_date


def test_stage_falls_back_when_a_table_has_no_values(django_setup: object) -> None:
    from engine.models import Project, SourceSystem, SourceTable
    from engine.services.export.builder import ModelBuilder

    project = Project.objects.create(name="no_values")
    crm = SourceSystem.objects.create(project=project, name="CRM", schema_name="crm")
    SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="customer",
        record_source_value="",
        load_date_value="",
    )

    stage = ModelBuilder(project).build().stages[0]

    assert stage.record_source == "!CRM"
    assert stage.load_date == DEFAULT_LOAD_DATE


# ---------------------------------------------------------------------------
# Migration 0016
# ---------------------------------------------------------------------------


def test_migration_turns_old_fallbacks_into_fixed_text(django_setup: object) -> None:
    from engine.models import Project, SourceColumn, SourceSystem, SourceTable

    migration = importlib.import_module(
        "engine.migrations.0016_record_source_fallback_as_fixed_text"
    )
    project = Project.objects.create(name="old_fallbacks")
    system = SourceSystem.objects.create(
        project=project, name="TPCH", schema_name="TPCH_SF1"
    )

    def table(name: str, record_source: str, columns: tuple[str, ...] = ()):
        created = SourceTable.objects.create(
            project=project,
            source_system=system,
            physical_table_name=name,
            record_source_value=record_source,
            load_date_value="sysdate()",
        )
        for column in columns:
            SourceColumn.objects.create(
                source_table=created,
                source_column_physical_name=column,
                source_column_datatype="VARCHAR",
            )
        return created

    by_system_name = table("customer", "TPCH")
    by_schema_name = table("orders", "TPCH_SF1")
    by_mcp_default = table("part", "TPCH.part")
    real_column = table("lineitem", "TPCH", columns=("tpch",))
    fixed = table("nation", "!TPCH")
    other_column = table("region", "RECORD_SOURCE")

    migration.prefix_fallbacks(django_apps, None)

    def value(source_table) -> str:
        source_table.refresh_from_db()
        return source_table.record_source_value

    assert value(by_system_name) == "!TPCH"
    assert value(by_schema_name) == "!TPCH_SF1"
    assert value(by_mcp_default) == "!TPCH.part"
    assert value(real_column) == "TPCH"
    assert value(fixed) == "!TPCH"
    assert value(other_column) == "RECORD_SOURCE"
