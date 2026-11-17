"""Pre-stages: dbt models that prepare a table's data for its stage.

A pre-stage is a source table of type ``prestage``. Generation writes its SQL
as it is (with a YAML file for its columns) to models/01_prestaging/, and its
stage reads it with ref() instead of a dbt source. Hubs, links and satellites
map its columns like any table's.

The fixture's CUSTOMER_RAW lands JSON; the pre-stage CUSTOMER_ADDRESS flattens
it. ORDER_ITEMS is a pre-stage maintained outside TurboVault: no SQL, only
referenced.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from django.core.exceptions import ValidationError

pytestmark = pytest.mark.django_db

ADDRESS_SQL = """select
    r.ID as CUSTOMER_ID,
    a.index as ADDRESS_NO,
    a.value:street::varchar as STREET,
    a.value:city::varchar as CITY,
    r.LOAD_TS
from {{ source('crm', 'CUSTOMER_RAW') }} as r,
     lateral flatten(input => r.PAYLOAD:addresses) as a
where r.STATUS != 'deleted'"""


def _columns(table, *specs) -> dict:
    from engine.models import SourceColumn

    return {
        name: SourceColumn.objects.create(
            source_table=table,
            source_column_physical_name=name,
            source_column_datatype=datatype,
            description=description,
        )
        for name, datatype, description in specs
    }


@pytest.fixture
def prestage_project(django_setup, db):
    from engine.models import (
        Hub,
        HubColumn,
        HubSourceMapping,
        Project,
        Satellite,
        SatelliteColumn,
        SourceSystem,
        SourceTable,
    )
    from engine.services.staging_service import get_or_create_staging_column

    project = Project.objects.create(name="prestages")
    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM"
    )

    raw = SourceTable.objects.create(
        project=project, source_system=crm, physical_table_name="CUSTOMER_RAW"
    )
    _columns(
        raw,
        ("ID", "VARCHAR", None),
        ("PAYLOAD", "VARIANT", None),
        ("STATUS", "VARCHAR", None),
        ("LOAD_TS", "TIMESTAMP_NTZ", None),
    )
    customer = SourceTable.objects.create(
        project=project, source_system=crm, physical_table_name="CUSTOMER"
    )
    customer_columns = _columns(
        customer, ("C_ID", "VARCHAR", None), ("C_NAME", "VARCHAR", None)
    )
    address = SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="CUSTOMER_ADDRESS",
        table_type=SourceTable.TableType.PRESTAGE,
        prestage_sql=ADDRESS_SQL,
        load_date_value="LOAD_TS",
        description="One row per customer address",
    )
    address_columns = _columns(
        address,
        ("CUSTOMER_ID", "VARCHAR", None),
        ("ADDRESS_NO", "NUMBER(38,0)", None),
        ("STREET", "VARCHAR", "Street and number"),
        ("CITY", "VARCHAR", None),
        ("LOAD_TS", "TIMESTAMP_NTZ", None),
    )
    items = SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="ORDER_ITEMS",
        table_type=SourceTable.TableType.PRESTAGE,
    )
    item_columns = _columns(
        items, ("ORDER_ID", "VARCHAR", None), ("ITEM_NO", "NUMBER", None)
    )

    customer_hub = Hub.objects.create(
        project=project,
        hub_physical_name="CUSTOMER_H",
        hub_hashkey_name="hk_customer_h",
    )
    customer_key = HubColumn.objects.create(hub=customer_hub, column_name="CUSTOMER_ID")
    HubSourceMapping.objects.create(
        hub_column=customer_key,
        staging_column=get_or_create_staging_column(customer_columns["C_ID"]),
        is_primary_source=True,
    )
    HubSourceMapping.objects.create(
        hub_column=customer_key,
        staging_column=get_or_create_staging_column(address_columns["CUSTOMER_ID"]),
    )
    satellite = Satellite.objects.create(
        project=project,
        satellite_physical_name="CUSTOMER_ADDRESS_S",
        parent_hub=customer_hub,
        source_table=address,
    )
    for name in ("STREET", "CITY"):
        SatelliteColumn.objects.create(
            satellite=satellite,
            staging_column=get_or_create_staging_column(address_columns[name]),
        )

    order_hub = Hub.objects.create(
        project=project, hub_physical_name="ORDER_H", hub_hashkey_name="hk_order_h"
    )
    HubSourceMapping.objects.create(
        hub_column=HubColumn.objects.create(hub=order_hub, column_name="ORDER_ID"),
        staging_column=get_or_create_staging_column(item_columns["ORDER_ID"]),
        is_primary_source=True,
    )
    return project


def _export(project):
    from engine.services.export.builder import ModelBuilder

    return ModelBuilder(project).build()


def _generate(project, tmp_path: Path, output_type: str = "dbt", **kwargs):
    from engine.services.generation import generate

    return generate(
        project=project,
        output_type=output_type,
        output_path=tmp_path / output_type,
        **kwargs,
    )


def _dry_run(project, tmp_path: Path, **options):
    from engine.services.generation.types import GenerationOptions

    return _generate(
        project, tmp_path, options=GenerationOptions(dry_run=True, **options)
    )


def _yaml_metadata(path: Path) -> dict:
    """A stage's yaml_metadata block, parsed as datavault4dbt will."""
    sql = path.read_text(encoding="utf-8")
    block = re.search(
        r"\{%- set yaml_metadata -%\}\n(.*?)\{%- endset -%\}", sql, re.DOTALL
    )
    assert block, sql
    return yaml.safe_load(block.group(1))


def _table(name: str):
    from engine.models import SourceTable

    return SourceTable.objects.get(physical_table_name=name)


# ---------------------------------------------------------------------------
# Model and export
# ---------------------------------------------------------------------------


def test_only_a_prestage_has_sql(prestage_project):
    customer = _table("CUSTOMER")
    customer.prestage_sql = "select 1"
    with pytest.raises(ValidationError, match="Only a pre-stage has SQL"):
        customer.full_clean()

    _table("CUSTOMER_ADDRESS").full_clean()


def test_the_export_describes_the_prestages(prestage_project):
    export = _export(prestage_project)

    prestages = {p.model_name: p for p in export.prestages}
    address = prestages["pstg__crm__customer_address"]
    assert address.sql == ADDRESS_SQL
    assert address.source_system == "CRM"
    assert address.description == "One row per customer address"
    assert [c.column_name for c in address.columns] == [
        "ADDRESS_NO",
        "CITY",
        "CUSTOMER_ID",
        "LOAD_TS",
        "STREET",
    ]
    assert prestages["pstg__crm__order_items"].sql is None

    tables = {t.table_name: t for t in export.sources[0].tables}
    assert tables["CUSTOMER_ADDRESS"].table_type == "prestage"
    assert tables["CUSTOMER_ADDRESS"].prestage_sql == ADDRESS_SQL
    assert tables["CUSTOMER"].table_type == "physical"
    assert tables["CUSTOMER"].prestage_sql is None

    stages = {s.stage_name: s for s in export.stages}
    assert stages["stg__crm__customer_address"].prestage_model == (
        "pstg__crm__customer_address"
    )
    assert stages["stg__crm__order_items"].prestage_model == "pstg__crm__order_items"
    assert stages["stg__crm__customer"].prestage_model is None


def test_a_table_only_prestages_read_gets_no_stage(prestage_project):
    stages = {s.stage_name for s in _export(prestage_project).stages}

    assert "stg__crm__customer_raw" not in stages
    assert stages == {
        "stg__crm__customer",
        "stg__crm__customer_address",
        "stg__crm__order_items",
    }


def test_a_prestage_input_the_raw_vault_loads_from_keeps_its_stage(prestage_project):
    from engine.models import Hub, Satellite, SatelliteColumn, SourceColumn
    from engine.services.staging_service import get_or_create_staging_column

    raw = _table("CUSTOMER_RAW")
    satellite = Satellite.objects.create(
        project=prestage_project,
        satellite_physical_name="CUSTOMER_STATUS_S",
        parent_hub=Hub.objects.get(hub_physical_name="CUSTOMER_H"),
        source_table=raw,
    )
    SatelliteColumn.objects.create(
        satellite=satellite,
        staging_column=get_or_create_staging_column(
            SourceColumn.objects.get(
                source_table=raw, source_column_physical_name="STATUS"
            )
        ),
    )

    stages = {s.stage_name for s in _export(prestage_project).stages}
    assert "stg__crm__customer_raw" in stages


def test_a_prestage_only_another_prestage_reads_gets_no_stage(prestage_project):
    from engine.models import SourceTable

    address = _table("CUSTOMER_ADDRESS")
    SourceTable.objects.create(
        project=prestage_project,
        source_system=address.source_system,
        physical_table_name="ADDRESS_BASE",
        table_type=SourceTable.TableType.PRESTAGE,
        prestage_sql="select * from {{ source('crm', 'CUSTOMER_RAW') }}",
    )
    address.prestage_sql = "select * from {{ ref('pstg__crm__address_base') }}"
    address.save()

    stages = {s.stage_name for s in _export(prestage_project).stages}
    assert "stg__crm__address_base" not in stages
    assert "stg__crm__customer_raw" not in stages
    assert "stg__crm__customer_address" in stages


# ---------------------------------------------------------------------------
# Generated dbt project
# ---------------------------------------------------------------------------


def test_the_prestage_model_is_written_as_it_is(prestage_project, tmp_path):
    report = _generate(prestage_project, tmp_path)
    assert report.status == "success", report.issues

    folder = tmp_path / "dbt" / "models" / "01_prestaging" / "crm"
    model = folder / "pstg__crm__customer_address.sql"
    assert model.read_text(encoding="utf-8") == ADDRESS_SQL + "\n"

    schema = yaml.safe_load(
        (folder / "pstg__crm__customer_address.yml").read_text(encoding="utf-8")
    )
    (entry,) = schema["models"]
    assert entry["name"] == "pstg__crm__customer_address"
    assert entry["description"] == "One row per customer address"
    assert entry["config"]["tags"] == ["prestage", "crm"]
    columns = {column["name"]: column for column in entry["columns"]}
    assert columns["STREET"] == {
        "name": "STREET",
        "data_type": "VARCHAR",
        "description": "Street and number",
    }
    assert columns["ADDRESS_NO"]["data_type"] == "NUMBER(38,0)"


def test_the_stage_reads_the_prestage_model(prestage_project, tmp_path):
    _generate(prestage_project, tmp_path)
    staging = tmp_path / "dbt" / "models" / "02_staging" / "crm"

    stage = _yaml_metadata(staging / "stg__crm__customer_address.sql")
    assert stage["source_model"] == "pstg__crm__customer_address"
    assert stage["ldts"] == "LOAD_TS"
    assert list(stage["hashed_columns"]) == ["hk_customer_h", "hd_CUSTOMER_ADDRESS_S"]

    physical = _yaml_metadata(staging / "stg__crm__customer.sql")
    assert physical["source_model"] == {"crm": "CUSTOMER"}

    assert not (staging / "stg__crm__customer_raw.sql").exists()


def test_a_prestage_without_sql_is_only_referenced(prestage_project, tmp_path):
    _generate(prestage_project, tmp_path)
    root = tmp_path / "dbt" / "models"

    assert not list(root.rglob("pstg__crm__order_items*"))
    stage = _yaml_metadata(root / "02_staging" / "crm" / "stg__crm__order_items.sql")
    assert stage["source_model"] == "pstg__crm__order_items"


def test_sources_leave_the_prestages_out(prestage_project, tmp_path):
    _generate(prestage_project, tmp_path)

    sources = yaml.safe_load(
        (tmp_path / "dbt" / "models" / "01_sources" / "source__crm.yml").read_text(
            encoding="utf-8"
        )
    )
    tables = [table["name"] for table in sources["sources"][0]["tables"]]
    assert tables == ["CUSTOMER", "CUSTOMER_RAW"]


def test_a_system_with_only_prestages_has_no_sources_file(prestage_project, tmp_path):
    from engine.models import SourceSystem, SourceTable

    lake = SourceSystem.objects.create(
        project=prestage_project, schema_name="lake", name="Lake"
    )
    SourceTable.objects.create(
        project=prestage_project,
        source_system=lake,
        physical_table_name="EVENTS_FLAT",
        table_type=SourceTable.TableType.PRESTAGE,
        prestage_sql="select * from {{ source('crm', 'CUSTOMER_RAW') }}",
    )

    _generate(prestage_project, tmp_path)
    models = tmp_path / "dbt" / "models"
    assert not (models / "01_sources" / "source__lake.yml").exists()
    assert (models / "01_prestaging" / "lake" / "pstg__lake__events_flat.sql").exists()


def test_the_prestaging_layer_follows_the_staging_layer(prestage_project, tmp_path):
    _generate(prestage_project, tmp_path)

    project_yml = yaml.safe_load(
        (tmp_path / "dbt" / "dbt_project.yml").read_text(encoding="utf-8")
    )
    (layers,) = project_yml["models"].values()
    assert layers["01_prestaging"] == {"+schema": "stage", "+materialized": "view"}


def test_the_prestaging_layer_is_never_ephemeral(prestage_project, tmp_path):
    from engine.services.runtime_config import EngineRuntimeConfig

    _generate(
        prestage_project,
        tmp_path,
        runtime_config=EngineRuntimeConfig(
            project_name="prestages", staging_materialization="ephemeral"
        ),
    )

    project_yml = yaml.safe_load(
        (tmp_path / "dbt" / "dbt_project.yml").read_text(encoding="utf-8")
    )
    (layers,) = project_yml["models"].values()
    assert layers["01_prestaging"]["+materialized"] == "view"
    assert layers["02_staging"]["+materialized"] == "ephemeral"


def test_no_prestaging_layer_without_prestage_models(prestage_project, tmp_path):
    from engine.models import SourceTable

    SourceTable.objects.filter(table_type=SourceTable.TableType.PRESTAGE).update(
        prestage_sql=None
    )
    _generate(prestage_project, tmp_path)

    root = tmp_path / "dbt"
    assert "01_prestaging" not in (root / "dbt_project.yml").read_text(encoding="utf-8")
    assert not (root / "models" / "01_prestaging").exists()


def test_a_prejoin_onto_a_prestage_reads_the_model(prestage_project, tmp_path):
    from engine.models import (
        PrejoinDefinition,
        PrejoinExtractionColumn,
        SourceColumn,
    )

    customer = _table("CUSTOMER")
    address = _table("CUSTOMER_ADDRESS")
    address_no = SourceColumn.objects.create(
        source_table=customer,
        source_column_physical_name="C_ADDRESS_NO",
        source_column_datatype="NUMBER",
    )
    prejoin = PrejoinDefinition.objects.create(
        project=prestage_project, source_table=customer, prejoin_target_table=address
    )
    prejoin.prejoin_condition_source_column.add(address_no)
    prejoin.prejoin_condition_target_column.add(
        address.columns.get(source_column_physical_name="ADDRESS_NO")
    )
    PrejoinExtractionColumn.objects.create(
        prejoin=prejoin,
        source_column=address.columns.get(source_column_physical_name="STREET"),
        prejoin_target_column_alias="ADDRESS_STREET",
    )

    _generate(prestage_project, tmp_path)

    stage = _yaml_metadata(
        tmp_path / "dbt" / "models" / "02_staging" / "crm" / "stg__crm__customer.sql"
    )
    (prejoined,) = stage["prejoined_columns"]
    assert prejoined["ref_model"] == "pstg__crm__customer_address"
    assert "src_name" not in prejoined
    assert "src_table" not in prejoined
    assert prejoined["extract_columns"] == ["STREET"]
    assert prejoined["aliases"] == ["ADDRESS_STREET"]


def test_a_workspace_template_gets_the_sql_unescaped(prestage_project, tmp_path):
    """Templates loaded from strings autoescape; the SQL's quotes must survive."""
    from engine.models import ModelTemplate

    ModelTemplate.objects.create(
        name="custom",
        framework="dbt",
        entity_type="prestage",
        sql_template_content="-- generated by TurboVault\n[[ prestage_sql ]]",
    )

    _generate(prestage_project, tmp_path)

    model = (
        tmp_path / "dbt" / "models" / "01_prestaging" / "crm"
    ) / "pstg__crm__customer_address.sql"
    assert model.read_text(encoding="utf-8") == (
        "-- generated by TurboVault\n" + ADDRESS_SQL + "\n"
    )


def test_the_plan_counts_the_prestage_files(prestage_project, tmp_path):
    report = _dry_run(prestage_project, tmp_path)

    # The model with SQL: one .sql and one .yml. ORDER_ITEMS gets none.
    assert report.plan.by_entity_type["prestage"] == 2
    prestage_files = [a for a in report.artifacts if a.entity_type == "prestage"]
    assert len(prestage_files) == 2


# ---------------------------------------------------------------------------
# Validation and templates
# ---------------------------------------------------------------------------


def _issues(report, code: str) -> list:
    return [issue for issue in report.issues if issue.code == code]


def test_an_ephemeral_prestage_is_an_error(prestage_project, tmp_path):
    address = _table("CUSTOMER_ADDRESS")
    address.prestage_sql = "{{ config(materialized='ephemeral') }}\n" + ADDRESS_SQL
    address.save()

    (issue,) = _issues(
        _dry_run(prestage_project, tmp_path), "validate.prestage.ephemeral"
    )
    assert issue.severity == "error"
    assert issue.entity.type == "prestage"
    assert issue.entity.name == "pstg__crm__customer_address"


def test_a_misspelled_source_is_reported(prestage_project, tmp_path):
    address = _table("CUSTOMER_ADDRESS")
    address.prestage_sql = ADDRESS_SQL.replace("'CUSTOMER_RAW'", "'customer_raw'")
    address.save()

    (issue,) = _issues(
        _dry_run(prestage_project, tmp_path), "validate.prestage.unknown_source"
    )
    assert issue.severity == "warning"
    assert "Did you mean source('crm', 'CUSTOMER_RAW')?" in issue.message


def test_sources_defined_elsewhere_are_not_checked(prestage_project, tmp_path):
    from engine.services.generation.types import GenerationOptions
    from engine.services.runtime_config import EngineRuntimeConfig

    address = _table("CUSTOMER_ADDRESS")
    address.prestage_sql = ADDRESS_SQL.replace("'crm'", "'landing'")
    address.save()

    report = _generate(
        prestage_project,
        tmp_path,
        runtime_config=EngineRuntimeConfig(
            project_name="prestages", export_sources=False
        ),
        options=GenerationOptions(dry_run=True),
    )
    assert not _issues(report, "validate.prestage.unknown_source")


OLD_STAGE_TEMPLATE = """{%- set yaml_metadata -%}
source_model:
    [[ source_system | lower | replace(" ", "_") ]]: [[ source_table ]]
ldts: [[ load_date | yaml_quote ]]
rsrc: [[ record_source | yaml_quote ]]
{%- endset -%}

{{ datavault4dbt.stage(yaml_metadata=yaml_metadata) }}
"""


def test_a_stage_template_that_predates_prestages_is_reported(
    prestage_project, tmp_path
):
    from engine.services.generation.types import TemplateOverride

    report = _dry_run(
        prestage_project,
        tmp_path,
        templates_override={"dbt": {"stage": TemplateOverride(sql=OLD_STAGE_TEMPLATE)}},
    )

    outdated = _issues(report, "render.template_outdated")
    assert {issue.entity.name for issue in outdated} == {
        "stg__crm__customer_address",
        "stg__crm__order_items",
    }
    assert all(issue.severity == "warning" for issue in outdated)


# ---------------------------------------------------------------------------
# SQLMesh
# ---------------------------------------------------------------------------


def test_sqlmesh_output_leaves_the_prestages_out(prestage_project, tmp_path):
    from engine.services.generation.types import GenerationOptions

    report = _generate(
        prestage_project,
        tmp_path,
        output_type="sqlmesh",
        options=GenerationOptions(dry_run=True),
    )

    skipped = {
        (issue.code, issue.entity.name) for issue in report.issues if issue.entity
    }
    for model in ("pstg__crm__customer_address", "pstg__crm__order_items"):
        assert ("render.sqlmesh.unsupported.prestage", model) in skipped
    for entity in ("CUSTOMER_H", "ORDER_H", "CUSTOMER_ADDRESS_S"):
        assert ("render.sqlmesh.prestage_dependent_skipped", entity) in skipped

    stages = {a.entity_name for a in report.artifacts if a.entity_type == "stage"}
    assert stages == {"stg__crm__customer"}
    assert report.plan.by_entity_type["stage"] == 1


# ---------------------------------------------------------------------------
# Output attributes (#442): pre-stages keep their imported path, name, config
# ---------------------------------------------------------------------------
#
# A pre-stage's attributes are stored on its source table under the output
# kind `prestage`, next to the table's `stage` attributes. Its SQL is the
# user's complete model and may call config() itself, so the stored config
# goes into the pre-stage's .yml (which dbt ranks below the SQL's config()).


def _set_prestage_attributes(table_name: str, **attributes) -> None:
    table = _table(table_name)
    table.generation_config = {"dbt": {"prestage": attributes}}
    table.full_clean(validate_unique=False, validate_constraints=False)
    table.save()


def _prestage_yml(path: Path) -> dict:
    (entry,) = yaml.safe_load(path.read_text(encoding="utf-8"))["models"]
    return entry


def _error_codes(report) -> list[str]:
    return [issue.code for issue in report.issues if issue.severity == "error"]


def test_a_prestage_is_written_to_its_stored_path_and_name(prestage_project, tmp_path):
    _set_prestage_attributes(
        "CUSTOMER_ADDRESS", file_path="prep/crm/customer_addresses.sql"
    )
    report = _generate(prestage_project, tmp_path)
    assert report.status == "success", report.issues

    models = tmp_path / "dbt" / "models"
    model = models / "prep" / "crm" / "customer_addresses.sql"
    assert model.read_text(encoding="utf-8") == ADDRESS_SQL + "\n"
    assert _prestage_yml(model.with_suffix(".yml"))["name"] == "customer_addresses"
    assert not list(models.rglob("pstg__crm__customer_address*"))


def test_the_stage_and_prejoins_read_the_stored_prestage_name(
    prestage_project, tmp_path
):
    from engine.models import PrejoinDefinition, PrejoinExtractionColumn, SourceColumn

    customer = _table("CUSTOMER")
    address = _table("CUSTOMER_ADDRESS")
    address_no = SourceColumn.objects.create(
        source_table=customer,
        source_column_physical_name="C_ADDRESS_NO",
        source_column_datatype="NUMBER",
    )
    prejoin = PrejoinDefinition.objects.create(
        project=prestage_project, source_table=customer, prejoin_target_table=address
    )
    prejoin.prejoin_condition_source_column.add(address_no)
    prejoin.prejoin_condition_target_column.add(
        address.columns.get(source_column_physical_name="ADDRESS_NO")
    )
    PrejoinExtractionColumn.objects.create(
        prejoin=prejoin,
        source_column=address.columns.get(source_column_physical_name="STREET"),
    )
    _set_prestage_attributes("CUSTOMER_ADDRESS", model_name="customer_addresses")

    _generate(prestage_project, tmp_path)
    staging = tmp_path / "dbt" / "models" / "02_staging" / "crm"

    stage = _yaml_metadata(staging / "stg__crm__customer_address.sql")
    assert stage["source_model"] == "customer_addresses"
    (prejoined,) = _yaml_metadata(staging / "stg__crm__customer.sql")[
        "prejoined_columns"
    ]
    assert prejoined["ref_model"] == "customer_addresses"


def test_a_prestage_without_sql_is_referenced_by_its_stored_name(
    prestage_project, tmp_path
):
    _set_prestage_attributes("ORDER_ITEMS", model_name="order_items_flat")
    _generate(prestage_project, tmp_path)
    models = tmp_path / "dbt" / "models"

    assert not list(models.rglob("order_items_flat*"))
    stage = _yaml_metadata(models / "02_staging" / "crm" / "stg__crm__order_items.sql")
    assert stage["source_model"] == "order_items_flat"


def test_the_stored_config_goes_into_the_yml(prestage_project, tmp_path):
    _set_prestage_attributes(
        "CUSTOMER_ADDRESS",
        alias="customer_address",
        schema="prep",
        database="analytics",
        materialized="table",
        tags=["prep", "pii"],
        custom_config_json={"persist_docs": {"relation": True}, "meta": {"o": "x"}},
    )
    _generate(prestage_project, tmp_path)
    folder = tmp_path / "dbt" / "models" / "01_prestaging" / "crm"

    config = _prestage_yml(folder / "pstg__crm__customer_address.yml")["config"]
    assert config == {
        "alias": "customer_address",
        "schema": "prep",
        "database": "analytics",
        "materialized": "table",
        "persist_docs": {"relation": True},
        "meta": {"o": "x"},
        "tags": ["prep", "pii"],
    }
    # The user's SQL is written as it is.
    sql = (folder / "pstg__crm__customer_address.sql").read_text(encoding="utf-8")
    assert sql == ADDRESS_SQL + "\n"


def test_a_prestage_outside_its_layer_folder_gets_the_layer_config(
    prestage_project, tmp_path
):
    _set_prestage_attributes("CUSTOMER_ADDRESS", file_path="prep/customer_address.sql")
    _generate(prestage_project, tmp_path)
    root = tmp_path / "dbt"

    config = _prestage_yml(root / "models" / "prep" / "customer_address.yml")["config"]
    assert config["schema"] == "stage"
    assert config["materialized"] == "view"
    # No pre-stage is left in 01_prestaging, so dbt_project.yml doesn't
    # configure the (unused) folder.
    assert "01_prestaging" not in (root / "dbt_project.yml").read_text(encoding="utf-8")


def test_a_prestage_in_its_layer_folder_inherits_the_layer_config(
    prestage_project, tmp_path
):
    _set_prestage_attributes(
        "CUSTOMER_ADDRESS", file_path="01_prestaging/crm/customer_address.sql"
    )
    _generate(prestage_project, tmp_path)
    root = tmp_path / "dbt"

    folder = root / "models" / "01_prestaging" / "crm"
    config = _prestage_yml(folder / "customer_address.yml")["config"]
    assert config == {"tags": ["prestage", "crm"]}
    assert "01_prestaging" in (root / "dbt_project.yml").read_text(encoding="utf-8")


def test_standard_paths_ignore_the_prestage_attributes(prestage_project, tmp_path):
    from engine.services.generation.types import GenerationOptions

    _set_prestage_attributes(
        "CUSTOMER_ADDRESS",
        file_path="prep/customer_addresses.sql",
        materialized="table",
    )
    report = _generate(
        prestage_project, tmp_path, options=GenerationOptions(use_original_paths=False)
    )
    assert report.status == "success", report.issues
    models = tmp_path / "dbt" / "models"

    folder = models / "01_prestaging" / "crm"
    config = _prestage_yml(folder / "pstg__crm__customer_address.yml")["config"]
    assert config == {"tags": ["prestage", "crm"]}
    stage = _yaml_metadata(
        models / "02_staging" / "crm" / "stg__crm__customer_address.sql"
    )
    assert stage["source_model"] == "pstg__crm__customer_address"


@pytest.mark.parametrize(
    ("table_name", "model_name"),
    [
        # A written pre-stage taking a stage's name.
        ("CUSTOMER_ADDRESS", "stg__crm__customer"),
        # A pre-stage maintained outside TurboVault still takes its name.
        ("ORDER_ITEMS", "CUSTOMER_H"),
        # Names compare case-insensitively.
        ("CUSTOMER_ADDRESS", "PSTG__CRM__ORDER_ITEMS"),
    ],
)
def test_a_prestage_name_collision_writes_nothing(
    prestage_project, tmp_path, table_name, model_name
):
    _set_prestage_attributes(table_name, model_name=model_name)
    report = _generate(prestage_project, tmp_path)

    assert _error_codes(report) == ["write.path_collision"]
    assert not (tmp_path / "dbt" / "models").exists()


def test_a_stored_ephemeral_materialization_is_an_error(prestage_project, tmp_path):
    _set_prestage_attributes("CUSTOMER_ADDRESS", materialized="ephemeral")

    (issue,) = _issues(
        _dry_run(prestage_project, tmp_path), "validate.prestage.ephemeral"
    )
    assert issue.severity == "error"
    assert issue.entity.name == "pstg__crm__customer_address"

    # With the stored attributes ignored, nothing is ephemeral.
    assert not _issues(
        _dry_run(prestage_project, tmp_path / "std", use_original_paths=False),
        "validate.prestage.ephemeral",
    )


def test_the_sql_config_ranks_above_a_stored_materialization(
    prestage_project, tmp_path
):
    address = _table("CUSTOMER_ADDRESS")
    address.prestage_sql = "{{ config(materialized='view') }}\n" + ADDRESS_SQL
    address.save()
    _set_prestage_attributes("CUSTOMER_ADDRESS", materialized="ephemeral")

    assert not _issues(
        _dry_run(prestage_project, tmp_path), "validate.prestage.ephemeral"
    )


def test_prestage_attributes_are_validated():
    from engine.services.export.models import PrestageDefinition, StageDefinition
    from pydantic import ValidationError as SchemaError

    with pytest.raises(SchemaError, match="must stay inside models/"):
        PrestageDefinition(
            model_name="p",
            table_name="t",
            source_system="s",
            generation_config={"dbt": {"prestage": {"file_path": "../p.sql"}}},
        )
    # Each definition carries only its own output kind.
    with pytest.raises(SchemaError, match="unknown dbt output kind"):
        PrestageDefinition(
            model_name="p",
            table_name="t",
            source_system="s",
            generation_config={"dbt": {"stage": {"model_name": "x"}}},
        )
    with pytest.raises(SchemaError, match="unknown dbt output kind"):
        StageDefinition(
            stage_name="s",
            source_table="t",
            source_schema="s",
            source_system="s",
            generation_config={"dbt": {"prestage": {"model_name": "x"}}},
        )


def test_the_source_table_field_accepts_prestage_attributes(prestage_project):
    address = _table("CUSTOMER_ADDRESS")
    address.generation_config = {
        "dbt": {
            "stage": {"model_name": "stg_addresses"},
            "prestage": {"file_path": "../escape.sql"},
        }
    }
    with pytest.raises(ValidationError, match="must stay inside models/"):
        address.full_clean(validate_unique=False, validate_constraints=False)

    address.generation_config["dbt"]["prestage"] = {"model_name": "customer_addresses"}
    address.full_clean(validate_unique=False, validate_constraints=False)


def test_the_export_splits_the_attributes_of_a_table(prestage_project):
    address = _table("CUSTOMER_ADDRESS")
    address.generation_config = {
        "dbt": {
            "stage": {"model_name": "stg_addresses"},
            "prestage": {"model_name": "customer_addresses"},
        }
    }
    address.save()
    export = _export(prestage_project)

    prestage = next(p for p in export.prestages if p.table_name == "CUSTOMER_ADDRESS")
    stage = next(s for s in export.stages if s.source_table == "CUSTOMER_ADDRESS")
    assert prestage.generation_config.as_stored() == {
        "dbt": {"prestage": {"model_name": "customer_addresses"}}
    }
    assert stage.generation_config.as_stored() == {
        "dbt": {"stage": {"model_name": "stg_addresses"}}
    }


def test_json_round_trip_keeps_the_prestage_attributes(prestage_project, tmp_path):
    import json

    from engine.models import Project, SourceTable
    from engine.services.imports import ImportOptions, JsonSource, import_metadata

    stored = {
        "CUSTOMER_ADDRESS": {
            "dbt": {
                "stage": {"model_name": "stg_addresses"},
                "prestage": {
                    "file_path": "prep/customer_addresses.sql",
                    "custom_config_json": {"meta": {"owner": "data"}},
                },
            }
        },
        # Only its pre-stage definition carries this one: ORDER_ITEMS has a
        # stage, but CUSTOMER_RAW (read only by pre-stages) has none.
        "ORDER_ITEMS": {"dbt": {"prestage": {"model_name": "order_items_flat"}}},
    }
    for name, value in stored.items():
        table = _table(name)
        table.generation_config = value
        table.save()

    path = tmp_path / "export.json"
    path.write_text(
        json.dumps(_export(prestage_project).model_dump(mode="json"), default=str),
        encoding="utf-8",
    )
    target = Project.objects.create(name="prestages-copy")
    report = import_metadata(
        project=target, source=JsonSource(path=path), options=ImportOptions()
    )
    assert report.status == "success", report.issues
    for name, value in stored.items():
        table = SourceTable.objects.get(project=target, physical_table_name=name)
        assert table.generation_config == value

    # Importing the same export again changes nothing.
    again = import_metadata(
        project=prestage_project,
        source=JsonSource(path=path),
        options=ImportOptions(dry_run=True),
    )
    changed = [e for e in again.plan.entities if e.changes]
    assert changed == [], [(e.ref, e.changes) for e in changed]
