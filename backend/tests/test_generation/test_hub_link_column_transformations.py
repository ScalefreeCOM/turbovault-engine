"""Generation tests for hub and link column transformations.

A transformation on a hub or link column is only useful if it reaches the
*stage*: datavault4dbt computes `hashed_columns` on top of `derived_columns`, so
a derived column that replaces the raw source column is what makes the hashkey
hash the normalised business key rather than the raw one.

These tests build a real Django project, run the real `ModelBuilder`, and assert
on the dbt SQL that actually lands on disk.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.django_db

HUB_TRANSFORMATION = "UPPER(TRIM([[source_column]]))"
LINK_TRANSFORMATION = "CAST([[source_column]] AS INT64)"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def transformed_project(django_setup, db):
    """CUSTOMER_H's business key carries a transformation and is loaded from two
    different physical columns: `customer.C_CUSTKEY` directly, and
    `orders.O_CUSTKEY` via the link. The link also has a transformed dependent
    child key."""
    from engine.models import (
        HubColumn,
        LinkColumn,
        Project,
        SourceColumn,
        SourceSystem,
        SourceTable,
    )
    from engine.services.model_import_schema import ModelImportSchema
    from engine.services.model_import_service import import_model

    project = Project.objects.create(name="hub-link-transformations")
    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM", database_name="ops"
    )

    def table(name: str, columns: tuple[str, ...]) -> None:
        source_table = SourceTable.objects.create(
            project=project,
            source_system=crm,
            physical_table_name=name,
            record_source_value=f"CRM.{name}",
            load_date_value="LOAD_DATE",
        )
        for col in columns:
            SourceColumn.objects.create(
                source_table=source_table,
                source_column_physical_name=col,
                source_column_datatype="VARCHAR",
            )

    table("customer", ("C_CUSTKEY", "C_NAME"))
    table("orders", ("O_ORDERKEY", "O_CUSTKEY", "O_LINENUMBER", "O_COMMENT"))

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stages(project) -> dict[str, dict]:
    from engine.services.export.builder import ModelBuilder

    export = ModelBuilder(project).build().model_dump(mode="json")
    return {stage["stage_name"]: stage for stage in export["stages"]}


def _derived(stage: dict) -> dict[str, str | None]:
    return {
        d["target_column_name"]: d["transformation"] for d in stage["derived_columns"]
    }


def _generate_stage_sql(project, tmp_path: Path) -> dict[str, str]:
    from engine.services.generation import generate

    report = generate(
        project=project, output_type="dbt", output_path=tmp_path / "dbt_out"
    )
    assert report.status in ("success", "partial_success"), report.issues

    sql: dict[str, str] = {}
    for artifact in report.artifacts:
        path = Path(artifact.path)
        if path.name.startswith("stg__") and path.suffix == ".sql":
            sql[path.stem] = path.read_text(encoding="utf-8")
    return sql


def _yaml_block(sql: str, key: str) -> str:
    """Return the indented body of a top-level key in the yaml_metadata block."""
    match = re.search(rf"^{key}:\n((?:[ \t]+.*\n?)*)", sql, re.MULTILINE)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# Builder level
# ---------------------------------------------------------------------------


def test_hub_transformation_becomes_a_derived_column(transformed_project):
    stages = _stages(transformed_project)
    assert _derived(stages["stg__crm__customer"]) == {
        "C_CUSTKEY": "UPPER(TRIM(C_CUSTKEY))"
    }


def test_hub_transformation_applies_in_every_stage_that_hashes_the_key(
    transformed_project,
):
    """The same business key arrives as `C_CUSTKEY` from `customer` and as
    `O_CUSTKEY` from `orders` (via the link). Both stages must normalise it, or
    the two stages produce different `hk_CUSTOMER_H` values for the same key —
    which is the bug this feature fixes."""
    stages = _stages(transformed_project)
    derived_orders = _derived(stages["stg__crm__orders"])

    assert derived_orders["O_CUSTKEY"] == "UPPER(TRIM(O_CUSTKEY))"
    assert _derived(stages["stg__crm__customer"])["C_CUSTKEY"] == (
        "UPPER(TRIM(C_CUSTKEY))"
    )


def test_link_dependent_child_key_transformation_becomes_a_derived_column(
    transformed_project,
):
    derived = _derived(_stages(transformed_project)["stg__crm__orders"])
    assert derived["O_LINENUMBER"] == "CAST(O_LINENUMBER AS INT64)"


def test_hashkeys_reference_the_derived_columns(transformed_project):
    """The derived column replaces the raw source column of the same name, so
    every hashkey that names it hashes the transformed value."""
    stages = _stages(transformed_project)

    customer = stages["stg__crm__customer"]
    hk = next(h for h in customer["hashkeys"] if h["target_entity"] == "CUSTOMER_H")
    assert hk["business_key_columns"] == ["C_CUSTKEY"]
    assert "C_CUSTKEY" in _derived(customer)

    orders = stages["stg__crm__orders"]
    derived_orders = _derived(orders)
    orders_hashkeys = {h["hashkey_name"]: h for h in orders["hashkeys"]}

    # Hub hashkey computed in the link's stage.
    assert orders_hashkeys["hk_CUSTOMER_H"]["business_key_columns"] == ["O_CUSTKEY"]
    # Link hashkey: both the foreign business key and the dependent child key
    # are derived columns.
    link_bks = orders_hashkeys["hk_ORDER_CUSTOMER_L"]["business_key_columns"]
    assert link_bks == ["O_ORDERKEY", "O_CUSTKEY", "O_LINENUMBER"]
    assert {"O_CUSTKEY", "O_LINENUMBER"} <= set(derived_orders)
    # An untransformed key stays raw.
    assert "O_ORDERKEY" not in derived_orders


def test_derived_column_names_are_unique_per_stage(transformed_project):
    """`derived_columns` renders as a YAML mapping, so a column reached through
    several routes (here `O_CUSTKEY`, used by both the hub hashkey and the link
    hashkey) must not be emitted twice."""
    for stage in _stages(transformed_project).values():
        names = [d["target_column_name"] for d in stage["derived_columns"]]
        assert len(names) == len(set(names)), names


def test_stage_without_transformations_has_no_derived_columns(django_setup, db):
    from engine.models import Project, SourceColumn, SourceSystem, SourceTable
    from engine.services.model_import_schema import ModelImportSchema
    from engine.services.model_import_service import import_model

    project = Project.objects.create(name="no-transformations")
    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM", database_name="ops"
    )
    table = SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="customer",
        record_source_value="CRM.customer",
        load_date_value="LOAD_DATE",
    )
    for col in ("C_CUSTKEY", "C_NAME"):
        SourceColumn.objects.create(
            source_table=table,
            source_column_physical_name=col,
            source_column_datatype="VARCHAR",
        )
    import_model(
        project.name,
        ModelImportSchema.model_validate(
            {
                "hubs": [
                    {
                        "name": "CUSTOMER_H",
                        "business_keys": ["C_CUSTKEY"],
                        "source_table": "customer",
                    }
                ],
                "satellites": [
                    {
                        "name": "CUSTOMER_S",
                        "parent_hub": "CUSTOMER_H",
                        "columns": ["C_NAME"],
                        "source_table": "customer",
                    }
                ],
            }
        ),
    )

    assert _stages(project)["stg__crm__customer"]["derived_columns"] == []


# ---------------------------------------------------------------------------
# Generated SQL
# ---------------------------------------------------------------------------


def test_generated_stage_sql_derives_and_hashes_the_transformed_key(
    transformed_project, tmp_path
):
    sql = _generate_stage_sql(transformed_project, tmp_path)

    customer = sql["stg__crm__customer"]
    assert "derived_columns:" in customer
    assert "value: 'UPPER(TRIM(C_CUSTKEY))'" in customer
    assert "src_cols_required: 'C_CUSTKEY'" in customer
    # The hashkey names the (now derived) column.
    hashed = _yaml_block(customer, "hashed_columns")
    assert "hk_CUSTOMER_H:" in hashed
    assert "- C_CUSTKEY" in hashed


def test_generated_link_stage_sql_derives_both_transformed_columns(
    transformed_project, tmp_path
):
    orders = _generate_stage_sql(transformed_project, tmp_path)["stg__crm__orders"]

    derived = _yaml_block(orders, "derived_columns")
    assert "value: 'UPPER(TRIM(O_CUSTKEY))'" in derived
    assert "value: 'CAST(O_LINENUMBER AS INT64)'" in derived
    # Rendered once each — duplicate YAML keys would silently drop one.
    assert derived.count("O_CUSTKEY:") == 1
    assert derived.count("O_LINENUMBER:") == 1

    hashed = _yaml_block(orders, "hashed_columns")
    assert "- O_CUSTKEY" in hashed
    assert "- O_LINENUMBER" in hashed


def test_generated_stage_sql_unchanged_without_transformations(
    django_setup, db, tmp_path
):
    """Models with no transformations must not gain a `derived_columns` block."""
    from engine.models import Project, SourceColumn, SourceSystem, SourceTable
    from engine.services.model_import_schema import ModelImportSchema
    from engine.services.model_import_service import import_model

    project = Project.objects.create(name="plain-generation")
    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM", database_name="ops"
    )
    table = SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="customer",
        record_source_value="CRM.customer",
        load_date_value="LOAD_DATE",
    )
    for col in ("C_CUSTKEY", "C_NAME"):
        SourceColumn.objects.create(
            source_table=table,
            source_column_physical_name=col,
            source_column_datatype="VARCHAR",
        )
    import_model(
        project.name,
        ModelImportSchema.model_validate(
            {
                "hubs": [
                    {
                        "name": "CUSTOMER_H",
                        "business_keys": ["C_CUSTKEY"],
                        "source_table": "customer",
                    }
                ],
                "satellites": [
                    {
                        "name": "CUSTOMER_S",
                        "parent_hub": "CUSTOMER_H",
                        "columns": ["C_NAME"],
                        "source_table": "customer",
                    }
                ],
            }
        ),
    )

    sql = _generate_stage_sql(project, tmp_path)["stg__crm__customer"]
    assert "derived_columns:" not in sql
    assert "- C_CUSTKEY" in _yaml_block(sql, "hashed_columns")
