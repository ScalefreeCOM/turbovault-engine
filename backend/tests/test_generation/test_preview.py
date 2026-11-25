"""The dbt models an entity or a project generates (generation/preview.py).

Rendered in memory by the stages of a real generation: each model's path and
config() block, stored model outputs marked, nothing written and no
generation run recorded. A caller's own settings and templates apply as in
its generation.
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


def test_the_callers_settings_name_and_place_the_models(project):
    from engine.services.generation.preview import generated_models
    from engine.services.runtime_config import EngineRuntimeConfig

    customer = _get("SourceTable", physical_table_name="CUSTOMER")
    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    config = EngineRuntimeConfig.from_project(project).with_settings(
        {
            "stage_naming": "stage_[[ source_table ]]",
            "folders.raw_vault": "models/vault",
        }
    )

    (stage,) = generated_models(customer, runtime_config=config)
    models = {m.kind: m for m in generated_models(hub, runtime_config=config)}

    assert stage.model_name == "stage_customer"
    assert models["hub"].path == "models/vault/CUSTOMER_H.sql"


def test_the_callers_templates_render_without_the_database(project):
    from engine.models import ModelTemplate
    from engine.services.generation.preview import generated_models
    from engine.services.generation.types import GenerationOptions, TemplateOverride

    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    override = "{{ config(\n    materialized='view',\n) }}\n-- the caller's hub\n"
    queries = []

    def count(execute, sql, params, many, context):
        queries.append(sql)
        return execute(sql, params, many, context)

    from django.db import connection

    with connection.execute_wrapper(count):
        models = {
            m.kind: m
            for m in generated_models(
                hub,
                options=GenerationOptions(
                    use_db_templates=False,
                    templates_override={
                        "dbt": {"hub_standard": TemplateOverride(sql=override)}
                    },
                ),
            )
        }

    assert models["hub"].config_block == "{{ config(\n    materialized='view',\n) }}"
    table = ModelTemplate._meta.db_table
    assert not [sql for sql in queries if table in sql]


def test_a_projects_models_by_entity(project):
    from engine.services.generation.preview import project_models

    entities = project_models(project)

    by_name = {(e.entity_type, e.entity_name): e for e in entities}
    assert [e.entity_type for e in entities] == sorted(
        (e.entity_type for e in entities),
        key=[
            "source_table",
            "snapshot_control",
            "hub",
            "link",
            "satellite",
            "pit",
            "reference_table",
        ].index,
    )
    hub = by_name[("hub", "CUSTOMER_H")]
    assert hub.entity_id == _get("Hub", hub_physical_name="CUSTOMER_H").pk
    assert [m.kind for m in hub.models] == [
        "hub",
        "effectivity_satellite",
        "record_tracking_satellite",
    ]
    assert hub.models[0].path == "models/30_raw_vault/CUSTOMER_H.sql"
    (stage,) = by_name[("source_table", "CUSTOMER")].models
    assert stage.model_name == "stg__crm__customer"
    assert stage.path and stage.path.endswith("/stg__crm__customer.sql")
    control = by_name[("snapshot_control", "control_snap")]
    assert [m.kind for m in control.models] == [
        "snapshot_control_v0",
        "snapshot_control_v1",
    ]
    assert by_name[("pit", "CUSTOMER_PIT")].models[0].config_block


def test_a_projects_models_mark_what_is_stored(project):
    from engine.services.generation.preview import project_models

    satellite = _get("Satellite", satellite_physical_name="CUSTOMER_S")
    _store("satellite_v1", satellite, model_name="customer_current", tags=["pii"])

    entities = {e.entity_name: e for e in project_models(project)}

    v0, v1 = entities["CUSTOMER_S"].models
    assert (v0.stored, v1.stored) == ((), ("model_name", "tags"))
    assert v1.path == "models/30_raw_vault/customer_current.sql"


def test_the_callers_options_apply(project):
    from engine.services.generation.preview import generated_models
    from engine.services.generation.types import GenerationOptions

    satellite = _get("Satellite", satellite_physical_name="CUSTOMER_S")

    models = generated_models(
        satellite, options=GenerationOptions(generate_satellite_v1_views=False)
    )

    v1 = next(m for m in models if m.kind == "satellite_v1")
    assert v1.path is None


def test_the_project_files_as_generation_writes_them(project):
    from engine.services.generation.preview import project_files
    from engine.services.runtime_config import EngineRuntimeConfig

    config = EngineRuntimeConfig.from_project(project).with_settings(
        {
            "folders.raw_vault": "models/vault",
            "dbt_packages": [{"package": "dbt-labs/dbt_utils", "version": "1.3.0"}],
        }
    )

    files = project_files(project, runtime_config=config)

    assert "vault:" in files.dbt_project_yml
    assert "30_raw_vault" not in files.dbt_project_yml
    assert "dbt-labs/dbt_utils" in files.packages_yml


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
