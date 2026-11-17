"""Migration 0026: stored ``generation_config`` values become model outputs.

#235 (issue #442) stored each entity's output attributes in a JSON field;
the project keeps them as ``model_output`` rows. A ``file_path`` gives the
folder (and the name, when ``model_name`` doesn't), the other attributes map
onto the row's fields. Values a row can't hold are dropped: a hub is named
after itself, a pre-stage's model belongs to the dbt project.
"""

from __future__ import annotations

import importlib

import pytest

BEFORE = [("engine", "0025_hub_link_pit_snapshot_options")]
AFTER = [("engine", "0026_generation_config_to_model_outputs")]


def _migration():
    return importlib.import_module(
        "engine.migrations.0026_generation_config_to_model_outputs"
    )


def test_a_file_path_gives_the_folder_and_the_name(django_setup):
    values = _migration()._values(
        "satellite_v0",
        {
            "file_path": "raw_vault/satellites/sat_customer.sql",
            "schema": "rdv",
            "tags": [],
            "custom_config_json": {"post-hook": "{{ x() }}", "unique_key": "hk"},
        },
    )

    assert values["folder"] == "models/raw_vault/satellites"
    assert values["model_name"] == "sat_customer"
    assert values["schema_name"] == "rdv"
    # An empty tag list stays one: a model without tags of its own
    assert values["tags"] == []
    # Hooks as a config() call takes them
    assert values["config"] == {"post_hook": "{{ x() }}", "unique_key": "hk"}
    assert _migration()._values("stage", {"file_path": "stg.sql"})["folder"] == (
        "models"
    )


@pytest.mark.django_db(transaction=True)
def test_stored_attributes_move_to_model_outputs(django_setup):
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE)
    old = executor.loader.project_state(BEFORE).apps
    project = old.get_model("engine", "Project").objects.create(name="shop")
    system = old.get_model("engine", "SourceSystem").objects.create(
        project=project, name="crm", schema_name="raw"
    )
    table = old.get_model("engine", "SourceTable").objects.create(
        project=project,
        source_system=system,
        physical_table_name="customer",
        table_type="prestage",
        generation_config={
            "dbt": {
                "stage": {"file_path": "staging/crm/stg_customer.sql"},
                "prestage": {"model_name": "prep_customer", "materialized": "view"},
            }
        },
    )
    hub = old.get_model("engine", "Hub").objects.create(
        project=project,
        hub_physical_name="customer_h",
        hub_hashkey_name="hk_customer_h",
        generation_config={
            "dbt": {
                # Named after the hub: only the alias stays
                "hub": {"model_name": "hub_customer", "alias": "customer"},
                "record_tracking_satellite": {"tags": ["daily"]},
            }
        },
    )
    old.get_model("engine", "Hub").objects.create(
        project=project, hub_physical_name="order_h", hub_hashkey_name="hk_order_h"
    )

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())

    from engine.models import ModelOutput

    rows = {
        (row.kind, row.source_table_id or row.hub_id): row
        for row in ModelOutput.objects.filter(project_id=project.pk)
    }
    assert set(rows) == {
        ("stage", table.pk),
        ("prestage", table.pk),
        ("hub", hub.pk),
        ("record_tracking_satellite", hub.pk),
    }
    stage = rows[("stage", table.pk)]
    assert (stage.folder, stage.model_name, stage.framework) == (
        "models/staging/crm",
        "stg_customer",
        "dbt",
    )
    prestage = rows[("prestage", table.pk)]
    assert (prestage.model_name, prestage.materialized) == ("prep_customer", None)
    assert (rows[("hub", hub.pk)].model_name, rows[("hub", hub.pk)].alias) == (
        None,
        "customer",
    )
    assert rows[("record_tracking_satellite", hub.pk)].tags == ["daily"]
