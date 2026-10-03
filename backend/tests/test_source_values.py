"""Record Source and Load Date values, from import to the generated stage.

datavault4dbt reads ``rsrc`` / ``ldts`` as a column name unless the text starts
with ``!`` (fixed text) or reads as SQL. A table that sets no value inherits
one from its source system, then the project, then the engine's defaults.
These tests pin that reading, the inheritance, that imports leave unset values
to inherit (and keep what a table already has), and that whatever a user
writes reaches the generated YAML unchanged.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
import yaml
from django.apps import apps as django_apps
from engine.services.imports.ir import IRDocument, IRRow, IRSheet
from engine.services.imports.parsers.json_parser import parse_json
from engine.services.imports.validation.resolver import resolve
from engine.services.source_values import (
    DEFAULT_LOAD_DATE,
    SourceValues,
    ValueKind,
    ValueOrigin,
    classify,
    default_record_source,
    fill_placeholders,
    resolve_source_values,
)

# Resolving an import, loading templates and the builder read the database.
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


def test_default_record_source_is_the_system_name_as_fixed_text() -> None:
    assert default_record_source("CRM") == "!CRM"
    assert classify(default_record_source("CRM")) is ValueKind.FIXED_TEXT


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------


def _resolve(
    table: SourceValues,
    system: SourceValues | None = None,
    project: SourceValues | None = None,
):
    return resolve_source_values(
        source_system_name="CRM",
        source_table_name="CUSTOMER",
        table=table,
        source_system=system,
        project=project,
    )


def test_nothing_set_uses_the_engine_defaults() -> None:
    values = _resolve(SourceValues())

    assert values.record_source.value == "!CRM"
    assert values.record_source.origin is ValueOrigin.DEFAULT
    assert values.load_date.value == DEFAULT_LOAD_DATE
    assert values.load_date.origin is ValueOrigin.DEFAULT
    assert values.static_part.value is None
    assert values.static_part.origin is None


def test_each_value_comes_from_the_closest_level_that_sets_it() -> None:
    values = _resolve(
        SourceValues(load_date="LOAD_TS"),
        system=SourceValues(record_source="!ERP", load_date="SYS_LOAD_TS"),
        project=SourceValues(
            record_source="!PROJECT", static_part="PROJECT", load_date="sysdate()"
        ),
    )

    assert (values.load_date.value, values.load_date.origin) == (
        "LOAD_TS",
        ValueOrigin.TABLE,
    )
    assert (values.record_source.value, values.record_source.origin) == (
        "!ERP",
        ValueOrigin.SOURCE_SYSTEM,
    )
    assert (values.static_part.value, values.static_part.origin) == (
        "PROJECT",
        ValueOrigin.PROJECT,
    )


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_value_inherits(blank: str) -> None:
    values = _resolve(
        SourceValues(record_source=blank), project=SourceValues(record_source="RSRC")
    )

    assert values.record_source.value == "RSRC"
    assert values.record_source.origin is ValueOrigin.PROJECT


def test_placeholders_name_each_table() -> None:
    values = _resolve(
        SourceValues(),
        project=SourceValues(
            record_source="![[ source_system ]].[[source_table]]",
            static_part="[[ source_system ]].[[ source_table ]]",
        ),
    )

    assert values.record_source.value == "!CRM.CUSTOMER"
    assert values.record_source.written == "![[ source_system ]].[[source_table]]"
    assert values.static_part.value == "CRM.CUSTOMER"


def test_fill_placeholders_leaves_other_text_alone() -> None:
    assert (
        fill_placeholders(
            "CONCAT('[[ source_system ]]', '/', FILE_NAME)",
            source_system_name="SAP",
            source_table_name="KNA1",
        )
        == "CONCAT('SAP', '/', FILE_NAME)"
    )


# ---------------------------------------------------------------------------
# Imports leave unset values to inherit
# ---------------------------------------------------------------------------


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


def test_excel_import_leaves_missing_values_to_inherit() -> None:
    model, _issues = resolve(_source_data_doc(None, None))

    found = model.get_source_table("SRC1")
    assert found is not None
    _system, table = found
    assert table.record_source_value is None
    assert table.load_date_value is None


def test_excel_import_keeps_given_values() -> None:
    model, _issues = resolve(_source_data_doc("!Customer", "LOAD_TS"))

    found = model.get_source_table("SRC1")
    assert found is not None
    _system, table = found
    assert table.record_source_value == "!Customer"
    assert table.load_date_value == "LOAD_TS"


def test_json_import_reads_system_values_and_leaves_table_values_unset(
    tmp_path: Path, django_setup: object
) -> None:
    from engine.services.export.models import (
        ProjectExport,
        SourceSystemDef,
        SourceTableDef,
    )

    export = ProjectExport(
        project_name="inheritance",
        sources=[
            SourceSystemDef(
                name="CRM",
                schema_name="crm_raw",
                record_source="![[ source_system ]].[[ source_table ]]",
                load_date="LOAD_TS",
                tables=[SourceTableDef(table_name="customer")],
            )
        ],
    )
    path = tmp_path / "export.json"
    path.write_text(export.model_dump_json(), encoding="utf-8")

    found = parse_json(path).get_source_table("CRM|customer")

    assert found is not None
    system, table = found
    assert system.record_source_value == "![[ source_system ]].[[ source_table ]]"
    assert system.load_date_value == "LOAD_TS"
    assert table.record_source_value is None
    assert table.load_date_value is None


def _source_metadata_file(tmp_path: Path, name: str, table: dict, system: dict) -> Path:
    payload = {
        "format": "source_metadata",
        "format_version": 1,
        "source_systems": [
            {
                "name": "CRM",
                "schema_name": "CRM",
                **system,
                "tables": [
                    {
                        "physical_table_name": "CUSTOMERS",
                        "columns": [{"physical_name": "ID", "datatype": "NUMBER"}],
                        **table,
                    }
                ],
            }
        ],
    }
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_reimport_keeps_values_the_source_leaves_out(tmp_path: Path) -> None:
    from engine.models import Project, SourceSystem, SourceTable
    from engine.services.imports import (
        ImportOptions,
        SourceMetadataSource,
        import_metadata,
    )

    project = Project.objects.create(name="reimport")

    def run(name: str, table: dict, system: dict) -> None:
        report = import_metadata(
            project=project,
            source=SourceMetadataSource(
                path=_source_metadata_file(tmp_path, name, table, system)
            ),
            options=ImportOptions(conflict_strategy="merge"),
        )
        assert report.status == "success", report.issues

    run(
        "first",
        {"record_source_value": "!CRM.CUSTOMERS", "alias": "customer"},
        {"load_date_value": "LOAD_TS"},
    )
    # The second collection says nothing about either value.
    run("second", {}, {})

    table = SourceTable.objects.get(project=project)
    system = SourceSystem.objects.get(project=project)
    assert table.record_source_value == "!CRM.CUSTOMERS"
    assert table.alias == "customer"
    assert table.load_date_value is None
    assert system.load_date_value == "LOAD_TS"


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _yaml_metadata(sql: str) -> dict:
    """The parsed ``yaml_metadata`` block of a rendered model."""
    start = sql.index("{%- set yaml_metadata -%}") + len("{%- set yaml_metadata -%}")
    end = sql.index("{%- endset -%}")
    return yaml.safe_load(sql[start:end])


def _stage_yaml_metadata(record_source: str, load_date: str) -> dict:
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
    return _yaml_metadata(template.render(**stage.model_dump()))


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


@pytest.fixture
def inheriting_project(django_setup: object):
    """CRM sets the record source for its tables; ORDERS sets its own load
    date and static part; CUSTOMER sets nothing. Both feed one hub."""
    from engine.models import (
        Hub,
        HubColumn,
        HubSourceMapping,
        Project,
        SourceColumn,
        SourceSystem,
        SourceTable,
        StagingColumn,
    )

    project = Project.objects.create(name="inheriting")
    crm = SourceSystem.objects.create(
        project=project,
        name="CRM",
        schema_name="crm",
        record_source_value="![[ source_system ]].[[ source_table ]]",
    )
    hub = Hub.objects.create(
        project=project,
        hub_physical_name="customer_h",
        hub_hashkey_name="hk_customer_h",
    )
    key = HubColumn.objects.create(
        hub=hub,
        column_name="customer_id",
        column_type=HubColumn.ColumnType.BUSINESS_KEY,
    )
    own_values = {
        "CUSTOMER": {},
        "ORDERS": {
            "load_date_value": "LOAD_TS",
            "static_part_of_record_source": "CRM.%",
        },
    }
    for name, own in own_values.items():
        table = SourceTable.objects.create(
            project=project, source_system=crm, physical_table_name=name, **own
        )
        column = SourceColumn.objects.create(
            source_table=table,
            source_column_physical_name="CUSTOMER_ID",
            source_column_datatype="NUMBER",
        )
        HubSourceMapping.objects.create(
            hub_column=key,
            staging_column=StagingColumn.objects.get(source_column=column),
            is_primary_source=True,
        )
    return project


def _build(project, **defaults):
    from engine.services.export.builder import ModelBuilder
    from engine.services.runtime_config import EngineRuntimeConfig

    config = EngineRuntimeConfig(project_name=project.name, **defaults)
    return ModelBuilder(project, runtime_config=config).build()


def test_stages_use_the_inherited_values(inheriting_project) -> None:
    export = _build(inheriting_project, default_load_date_value="CURRENT_TIMESTAMP()")
    stages = {stage.source_table: stage for stage in export.stages}

    assert stages["CUSTOMER"].record_source == "!CRM.CUSTOMER"
    assert stages["CUSTOMER"].load_date == "CURRENT_TIMESTAMP()"
    assert stages["ORDERS"].record_source == "!CRM.ORDERS"
    assert stages["ORDERS"].load_date == "LOAD_TS"


def test_export_keeps_what_each_level_sets(inheriting_project) -> None:
    export = _build(inheriting_project)
    crm = export.sources[0]
    tables = {table.table_name: table for table in crm.tables}

    assert crm.record_source == "![[ source_system ]].[[ source_table ]]"
    assert tables["CUSTOMER"].record_source is None
    assert tables["ORDERS"].load_date == "LOAD_TS"
    assert tables["ORDERS"].static_part_of_record_source == "CRM.%"


def test_hub_gets_each_sources_static_part(inheriting_project) -> None:
    from engine.services.generation.template_resolver import TemplateResolver

    hub = _build(inheriting_project).hubs[0]
    static_parts = {
        source.source_table: source.rsrc_static for source in hub.source_tables
    }

    assert static_parts == {"CUSTOMER": None, "ORDERS": "CRM.%"}

    template = TemplateResolver().get_sql_template("hub_standard")
    assert template is not None
    metadata = _yaml_metadata(template.render(**hub.model_dump()))
    rendered = {
        source["name"]: source.get("rsrc_static")
        for source in metadata["source_models"]
    }
    assert rendered == {"stg__crm__customer": None, "stg__crm__orders": "CRM.%"}


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


def _migration(name: str):
    return importlib.import_module(f"engine.migrations.{name}")


def test_migration_turns_old_fallbacks_into_fixed_text(django_setup: object) -> None:
    from engine.models import Project, SourceColumn, SourceSystem, SourceTable

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

    _migration("0016_record_source_fallback_as_fixed_text").prefix_fallbacks(
        django_apps, None
    )

    def value(source_table) -> str:
        source_table.refresh_from_db()
        return source_table.record_source_value

    assert value(by_system_name) == "!TPCH"
    assert value(by_schema_name) == "!TPCH_SF1"
    assert value(by_mcp_default) == "!TPCH.part"
    assert value(real_column) == "TPCH"
    assert value(fixed) == "!TPCH"
    assert value(other_column) == "RECORD_SOURCE"


def test_migration_makes_blank_table_values_inherit(django_setup: object) -> None:
    from engine.models import Project, SourceSystem, SourceTable

    project = Project.objects.create(name="blank_values")
    system = SourceSystem.objects.create(project=project, name="CRM", schema_name="crm")
    blank = SourceTable.objects.create(
        project=project,
        source_system=system,
        physical_table_name="customer",
        record_source_value="",
        static_part_of_record_source="",
        load_date_value="",
    )
    kept = SourceTable.objects.create(
        project=project,
        source_system=system,
        physical_table_name="orders",
        record_source_value="!CRM",
        load_date_value="LOAD_TS",
    )

    _migration("0017_source_value_inheritance").blank_means_inherit(django_apps, None)

    blank.refresh_from_db()
    kept.refresh_from_db()
    assert blank.record_source_value is None
    assert blank.static_part_of_record_source is None
    assert blank.load_date_value is None
    assert (kept.record_source_value, kept.load_date_value) == ("!CRM", "LOAD_TS")
