"""The order of a stage's hash keys doesn't change from one run to the next.

The mappings behind them have UUID keys, so the database's own order differs
between imports of the same metadata. A stage lists the Hubs it loads by name,
then the Hub keys its Links reference, then the Link keys.
"""

from __future__ import annotations

import pytest

from tests.test_generation.test_model_outputs import build_project

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
