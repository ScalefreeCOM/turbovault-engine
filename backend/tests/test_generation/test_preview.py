"""The dbt models one entity generates, for the admin (generation/preview.py).

Rendered in memory by the stages of a real generation: each model's path and
config() block, stored model outputs marked, nothing written and no
generation run recorded.
"""

from __future__ import annotations

import pytest

from tests.test_generation.test_model_outputs import _get, _store, build_project


@pytest.fixture
def project(django_setup, db):
    return build_project()


def test_an_entitys_models_with_their_files(project):
    from engine.models import GenerationRun
    from engine.services.generation.preview import generated_models

    hub = _get("Hub", hub_physical_name="CUSTOMER_H")

    models = {m.kind: m for m in generated_models(hub)}

    assert set(models) == {"hub", "effectivity_satellite", "record_tracking_satellite"}
    assert models["hub"].path == "models/30_raw_vault/CUSTOMER_H.sql"
    assert models["hub"].stored == ()
    assert not GenerationRun.objects.exists()


def test_stored_settings_are_marked_and_rendered(project):
    from engine.services.generation.preview import generated_models

    customer = _get("SourceTable", physical_table_name="CUSTOMER")
    _store(
        "stage",
        customer,
        model_name="stg_customer",
        folder="models/staging/crm",
        materialized="table",
    )

    (stage,) = generated_models(customer)

    assert (stage.model_name, stage.path) == (
        "stg_customer",
        "models/staging/crm/stg_customer.sql",
    )
    assert stage.stored == ("model_name", "folder", "materialized")
    assert "materialized='table'" in stage.config_block


def test_the_admin_page_shows_them(project, admin_client):
    satellite = _get("Satellite", satellite_physical_name="CUSTOMER_S")

    page = admin_client.get(f"/admin/engine/satellite/{satellite.pk}/change/")

    html = page.content.decode()
    assert page.status_code == 200
    assert "Generated dbt models" in html
    assert "models/30_raw_vault/CUSTOMER_S_v0.sql" in html
    assert "models/30_raw_vault/CUSTOMER_S_v1.sql" in html


def test_the_admin_lists_model_outputs(project, admin_client):
    index = admin_client.get("/admin/").content.decode()

    assert "/admin/engine/modeloutput/" in index
