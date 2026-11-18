"""A stage's hash keys: in an order that doesn't change, each once.

The mappings behind them have UUID keys, so the database's own order differs
between imports of the same metadata. A stage lists the Hubs it loads by name,
then the Hub keys its Links reference, then the Link keys. Hubs or Links
naming their hash keys alike get one column, the first's; a warning names
them where they hash different columns.
"""

from __future__ import annotations

import pytest

from tests.test_generation.test_model_outputs import (
    _generate,
    _issues,
    _read,
    build_project,
)

pytestmark = pytest.mark.django_db


def test_a_stage_lists_the_hubs_it_loads_by_name(django_setup, db):
    from engine.models import Hub, HubColumn, HubSourceMapping, SourceColumn
    from engine.services.export.builder import ModelBuilder
    from engine.services.staging_service import get_or_create_staging_column

    project = build_project()
    customer = SourceColumn.objects.get(
        source_table__physical_table_name="CUSTOMER",
        source_column_physical_name="C_NAME",
    )
    # Created after CUSTOMER_H, named before it
    hub = Hub.objects.create(
        project=project, hub_physical_name="ACCOUNT_H", hub_hashkey_name="hk_account_h"
    )
    HubSourceMapping.objects.create(
        hub_column=HubColumn.objects.create(hub=hub, column_name="ACCOUNT_NAME"),
        staging_column=get_or_create_staging_column(customer),
        is_primary_source=True,
    )

    export = ModelBuilder(project).build()

    stage = next(s for s in export.stages if s.source_table == "CUSTOMER")
    assert [h.hashkey_name for h in stage.hashkeys] == ["hk_account_h", "hk_customer_h"]


def _second_hub(project, column: str):
    """ACCOUNT_H, loaded from CUSTOMER and named before CUSTOMER_H, with the
    hash key name hk_customer_h."""
    from engine.models import Hub, HubColumn, HubSourceMapping, SourceColumn
    from engine.services.staging_service import get_or_create_staging_column

    hub = Hub.objects.create(
        project=project, hub_physical_name="ACCOUNT_H", hub_hashkey_name="hk_customer_h"
    )
    HubSourceMapping.objects.create(
        hub_column=HubColumn.objects.create(hub=hub, column_name="ACCOUNT_KEY"),
        staging_column=get_or_create_staging_column(
            SourceColumn.objects.get(
                source_table__physical_table_name="CUSTOMER",
                source_column_physical_name=column,
            )
        ),
        is_primary_source=True,
    )


def _stage_sql(tmp_path) -> str:
    (path,) = (tmp_path / "dbt").rglob("stg__crm__customer.sql")
    return _read(path)


def test_hubs_naming_their_hash_key_alike_share_one_column(django_setup, tmp_path):
    project = build_project()
    _second_hub(project, "C_ID")  # the same column as CUSTOMER_H's

    report = _generate(project, tmp_path)

    assert report.status == "success", report.issues
    assert _stage_sql(tmp_path).count("hk_customer_h:") == 1
    assert not _issues(report, "validate.stage.duplicate_hashkey")


def test_a_hash_key_name_hashing_different_columns_is_computed_for_the_first(
    django_setup, tmp_path
):
    project = build_project()
    _second_hub(project, "C_NAME")

    report = _generate(project, tmp_path)

    sql = _stage_sql(tmp_path)
    assert sql.count("hk_customer_h:") == 1
    assert "hk_customer_h:\n        - C_NAME" in sql
    (issue,) = _issues(report, "validate.stage.duplicate_hashkey")
    assert issue.severity == "warning"
    assert "for 'ACCOUNT_H'" in issue.message
