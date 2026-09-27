"""Derived columns: columns a stage computes with SQL.

A derived column is defined once on its source table and then mapped like any
other column of it. It reaches the stage's `derived_columns`, where
datavault4dbt computes it before hashing, so it can be a business key.

The stage's yaml_metadata block is parsed back in these tests: an expression
with quotes, line breaks or a comment must arrive in dbt exactly as written.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from django.core.exceptions import ValidationError

pytestmark = pytest.mark.django_db

FULL_NAME = "TRIM(C_FIRST) || ' ' || TRIM(C_LAST)"
# Several lines, a comment, and quotes of both kinds.
CUSTOMER_KEY = """CASE
  -- customers from the old system have no number
  WHEN C_CUSTKEY IS NULL THEN 'legacy:' || "C_LEGACY_ID"
  ELSE C_CUSTKEY
END"""


@pytest.fixture
def derived_project(django_setup, db):
    """`customer` computes FULL_NAME and CUSTOMER_KEY. The hub's business key is
    CUSTOMER_KEY, the satellite carries FULL_NAME (renamed to NAME)."""
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
    from engine.services.staging_service import get_or_create_staging_column

    project = Project.objects.create(name="derived")
    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM", database_name="ops"
    )
    customer = SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="customer",
        record_source_value="CRM.customer",
        load_date_value="LOAD_DATE",
    )
    for column in ("C_CUSTKEY", "C_LEGACY_ID", "C_FIRST", "C_LAST"):
        SourceColumn.objects.create(
            source_table=customer,
            source_column_physical_name=column,
            source_column_datatype="VARCHAR",
        )
    full_name = DerivedColumn.objects.create(
        project=project,
        source_table=customer,
        column_name="FULL_NAME",
        expression=FULL_NAME,
        datatype="VARCHAR(200)",
        description="First and last name",
    )
    customer_key = DerivedColumn.objects.create(
        project=project,
        source_table=customer,
        column_name="CUSTOMER_KEY",
        expression=CUSTOMER_KEY,
        datatype="VARCHAR",
    )

    hub = Hub.objects.create(
        project=project,
        hub_physical_name="CUSTOMER_H",
        hub_hashkey_name="hk_customer_h",
    )
    hub_column = HubColumn.objects.create(hub=hub, column_name="CUSTOMER_KEY")
    HubSourceMapping.objects.create(
        hub_column=hub_column,
        staging_column=get_or_create_staging_column(customer_key),
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
        staging_column=get_or_create_staging_column(full_name),
        target_column_name="NAME",
    )
    return project


def _stage(project) -> dict:
    from engine.services.export.builder import ModelBuilder

    export = ModelBuilder(project).build().model_dump(mode="json")
    return next(s for s in export["stages"] if s["stage_name"] == "stg__crm__customer")


def _stage_metadata(project, tmp_path: Path) -> dict:
    """The stage's yaml_metadata block, parsed as datavault4dbt will."""
    from engine.services.generation import generate

    report = generate(
        project=project, output_type="dbt", output_path=tmp_path / "dbt_out"
    )
    assert report.status in ("success", "partial_success"), report.issues
    sql = next(
        Path(a.path).read_text(encoding="utf-8")
        for a in report.artifacts
        if Path(a.path).name == "stg__crm__customer.sql"
    )
    block = re.search(
        r"\{%- set yaml_metadata -%\}\n(.*?)\{%- endset -%\}", sql, re.DOTALL
    )
    assert block, sql
    return yaml.safe_load(block.group(1))


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_a_derived_column_is_a_staging_column(derived_project):
    from engine.models import StagingColumn

    staging = StagingColumn.objects.get(derived_column__column_name="FULL_NAME")
    assert staging.physical_name == "FULL_NAME"
    assert staging.datatype == "VARCHAR(200)"
    assert staging.description == "First and last name"
    assert str(staging) == "[derived] customer.FULL_NAME"


def test_a_derived_column_cannot_shadow_a_source_column(derived_project):
    from engine.models import DerivedColumn, SourceTable

    customer = SourceTable.objects.get(project=derived_project)
    duplicate = DerivedColumn(
        project=derived_project,
        source_table=customer,
        column_name="c_custkey",
        expression="1",
    )
    with pytest.raises(ValidationError) as error:
        duplicate.full_clean()
    assert "column_name" in error.value.message_dict


def test_a_derived_column_needs_an_expression(derived_project):
    from engine.models import DerivedColumn, SourceTable

    empty = DerivedColumn(
        project=derived_project,
        source_table=SourceTable.objects.get(project=derived_project),
        column_name="NOTHING",
        expression="   ",
    )
    with pytest.raises(ValidationError) as error:
        empty.full_clean()
    assert "expression" in error.value.message_dict


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_the_stage_computes_every_derived_column(derived_project):
    derived = {
        d["target_column_name"]: d for d in _stage(derived_project)["derived_columns"]
    }

    assert derived["FULL_NAME"]["transformation"] == FULL_NAME
    assert derived["FULL_NAME"]["datatype"] == "VARCHAR(200)"
    assert derived["FULL_NAME"]["src_cols_required"] == ["C_FIRST", "C_LAST"]
    assert derived["FULL_NAME"]["description"] == "First and last name"
    # Only real columns count: not the ones inside quotes or a comment.
    assert derived["CUSTOMER_KEY"]["src_cols_required"] == ["C_CUSTKEY", "C_LEGACY_ID"]


def test_the_hub_hashes_the_derived_column(derived_project):
    stage = _stage(derived_project)
    hashkey = next(h for h in stage["hashkeys"] if h["hashkey_name"] == "hk_customer_h")
    assert hashkey["business_key_columns"] == ["CUSTOMER_KEY"]


def test_a_rename_of_a_derived_column_inlines_its_expression(derived_project):
    """datavault4dbt computes every derived column in one SELECT, so NAME
    can't read FULL_NAME: it repeats FULL_NAME's expression instead."""
    derived = {
        d["target_column_name"]: d for d in _stage(derived_project)["derived_columns"]
    }
    assert derived["NAME"]["transformation"] == f"({FULL_NAME})"
    assert derived["NAME"]["datatype"] == "VARCHAR(200)"
    assert derived["NAME"]["src_cols_required"] == ["C_FIRST", "C_LAST"]


def test_a_transformation_of_a_derived_key_wraps_its_expression(derived_project):
    """In place, like any hub transformation: CUSTOMER_KEY is computed once,
    with the rule applied to its expression."""
    from engine.models import HubColumn

    HubColumn.objects.filter(column_name="CUSTOMER_KEY").update(
        target_column_transformation="UPPER([[source_column]])",
        target_column_datatype="VARCHAR(50)",
    )
    derived = [
        d
        for d in _stage(derived_project)["derived_columns"]
        if d["target_column_name"] == "CUSTOMER_KEY"
    ]
    assert len(derived) == 1
    assert derived[0]["transformation"] == f"UPPER(({CUSTOMER_KEY}))"
    assert derived[0]["datatype"] == "VARCHAR(50)"


def test_a_transformation_without_a_type_takes_the_source_columns(derived_project):
    from engine.models import SatelliteColumn, SourceColumn

    phone = SourceColumn.objects.create(
        source_table=SatelliteColumn.objects.get().satellite.source_table,
        source_column_physical_name="C_PHONE",
        source_column_datatype="NUMBER(12)",
    )
    from engine.services.staging_service import get_or_create_staging_column

    SatelliteColumn.objects.create(
        satellite=SatelliteColumn.objects.get().satellite,
        staging_column=get_or_create_staging_column(phone),
        target_column_name="PHONE",
        target_column_transformation="NULLIF([[source_column]], 0)",
    )
    derived = {
        d["target_column_name"]: d for d in _stage(derived_project)["derived_columns"]
    }
    assert derived["PHONE"]["transformation"] == "NULLIF(C_PHONE, 0)"
    assert derived["PHONE"]["datatype"] == "NUMBER(12)"


# ---------------------------------------------------------------------------
# Generated stage
# ---------------------------------------------------------------------------


def test_generated_stage_carries_expressions_exactly(derived_project, tmp_path):
    metadata = _stage_metadata(derived_project, tmp_path)
    derived = metadata["derived_columns"]

    assert derived["FULL_NAME"] == {
        "value": FULL_NAME,
        "datatype": "VARCHAR(200)",
        "src_cols_required": ["C_FIRST", "C_LAST"],
    }
    # Line breaks, the comment and both kinds of quotes survive.
    assert derived["CUSTOMER_KEY"]["value"] == CUSTOMER_KEY
    assert derived["NAME"]["value"] == f"({FULL_NAME})"
    assert metadata["hashed_columns"]["hk_customer_h"] == ["CUSTOMER_KEY"]


def test_generated_stage_yml_documents_derived_columns(derived_project, tmp_path):
    from engine.services.generation import generate

    report = generate(
        project=derived_project, output_type="dbt", output_path=tmp_path / "out"
    )
    stage_yml = next(
        Path(a.path).read_text(encoding="utf-8")
        for a in report.artifacts
        if Path(a.path).name == "stg__crm__customer.yml"
    )
    columns = {
        c["name"]: c.get("description")
        for c in yaml.safe_load(stage_yml)["models"][0]["columns"]
    }
    assert columns["FULL_NAME"] == "First and last name"


def test_an_expression_without_a_type_is_flagged(derived_project):
    """datavault4dbt can't type an expression by itself; dbt would fail."""
    from engine.models import DerivedColumn
    from engine.services.export.builder import ModelBuilder
    from engine.services.generation.validators import validate_export

    DerivedColumn.objects.filter(column_name="FULL_NAME").update(datatype=None)
    result = validate_export(ModelBuilder(derived_project).build())
    flagged = [w for w in result.warnings if w.code == "STG_003"]
    assert any("FULL_NAME" in w.message for w in flagged)
    # NAME inlines FULL_NAME's expression, so it has no type either.
    assert any("'NAME'" in w.message for w in flagged)
    assert not any("CUSTOMER_KEY" in w.message for w in flagged)
