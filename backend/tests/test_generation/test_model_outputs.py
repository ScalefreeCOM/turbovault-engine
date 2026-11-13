"""Model outputs: stored names, folders and config() settings of dbt models.

Every entity's dbt models are named by the project's naming patterns unless a
``ModelOutput`` stores a name; it may also store the model's folder and
config() settings. Generation names files after the resolved names, and every
reference between models (a stage in a hub, a v0 table in its v1 view,
satellites and a snapshot control in a PIT, v1 views in a reference table)
follows them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from django.core.exceptions import ValidationError

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(django_setup, db):
    """CUSTOMER_H with a satellite, effectivity and record-tracking satellites
    and a PIT; NATION_RH with a reference satellite and a reference table."""
    from engine.models import (
        PIT,
        Hub,
        HubColumn,
        HubSourceMapping,
        Project,
        ReferenceTable,
        Satellite,
        SatelliteColumn,
        SnapshotControlLogic,
        SnapshotControlTable,
        SourceColumn,
        SourceSystem,
        SourceTable,
    )
    from engine.services.staging_service import get_or_create_staging_column

    project = Project.objects.create(name="outputs")
    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM"
    )

    def table(name: str, *columns: str) -> tuple[SourceTable, dict]:
        source_table = SourceTable.objects.create(
            project=project,
            source_system=crm,
            physical_table_name=name,
            load_date_value="LOAD_TS",
        )
        return source_table, {
            column: get_or_create_staging_column(
                SourceColumn.objects.create(
                    source_table=source_table,
                    source_column_physical_name=column,
                    source_column_datatype="VARCHAR",
                )
            )
            for column in columns
        }

    customer, customer_columns = table("CUSTOMER", "C_ID", "C_NAME", "LOAD_TS")
    hub = Hub.objects.create(
        project=project,
        hub_physical_name="CUSTOMER_H",
        hub_hashkey_name="hk_customer_h",
        create_effectivity_satellite=True,
        create_record_tracking_satellite=True,
    )
    HubSourceMapping.objects.create(
        hub_column=HubColumn.objects.create(hub=hub, column_name="CUSTOMER_ID"),
        staging_column=customer_columns["C_ID"],
        is_primary_source=True,
    )
    satellite = Satellite.objects.create(
        project=project,
        satellite_physical_name="CUSTOMER_S",
        parent_hub=hub,
        source_table=customer,
    )
    SatelliteColumn.objects.create(
        satellite=satellite, staging_column=customer_columns["C_NAME"]
    )

    control = SnapshotControlTable.objects.create(project=project, name="control_snap")
    logic = SnapshotControlLogic.objects.create(
        snapshot_control_table=control,
        snapshot_control_logic_column_name="is_daily",
        snapshot_component="daily",
        snapshot_forever=True,
    )
    pit = PIT.objects.create(
        project=project,
        pit_physical_name="CUSTOMER_PIT",
        tracked_entity_type="hub",
        tracked_hub=hub,
        snapshot_control_table=control,
        snapshot_control_logic=logic,
    )
    pit.satellites.add(satellite)

    nation, nation_columns = table("NATION", "N_KEY", "N_NAME", "LOAD_TS")
    reference_hub = Hub.objects.create(
        project=project,
        hub_physical_name="NATION_RH",
        hub_type=Hub.HubType.REFERENCE,
        create_effectivity_satellite=False,
    )
    HubSourceMapping.objects.create(
        hub_column=HubColumn.objects.create(
            hub=reference_hub,
            column_name="N_KEY",
            column_type=HubColumn.ColumnType.REFERENCE_KEY,
        ),
        staging_column=nation_columns["N_KEY"],
        is_primary_source=True,
    )
    reference_satellite = Satellite.objects.create(
        project=project,
        satellite_physical_name="NATION_RS",
        satellite_type=Satellite.SatelliteType.REFERENCE,
        parent_hub=reference_hub,
        source_table=nation,
    )
    SatelliteColumn.objects.create(
        satellite=reference_satellite, staging_column=nation_columns["N_NAME"]
    )
    ReferenceTable.objects.create(
        project=project,
        reference_table_physical_name="NATION_R",
        reference_hub=reference_hub,
        historization_type=ReferenceTable.HistorizationType.LATEST,
    )
    return project


def _get(model: str, **lookup):
    from engine import models

    return getattr(models, model).objects.get(**lookup)


def _store(kind: str, entity, **fields):
    """Store a model output for *entity*, validated like a form would."""
    from engine.models import ModelOutput
    from engine.models.model_output import ENTITY_FIELDS

    field = next(
        name
        for name in ENTITY_FIELDS
        if ModelOutput._meta.get_field(name).related_model is type(entity)
    )
    output = ModelOutput(kind=kind, **{field: entity}, **fields)
    output.full_clean(exclude=["project"])
    output.save()
    return output


def _export(project, runtime_config=None):
    from engine.services.export.builder import ModelBuilder

    return ModelBuilder(project, runtime_config=runtime_config).build()


def _generate(project, tmp_path: Path, runtime_config=None, **options):
    from engine.services.generation import generate
    from engine.services.generation.types import GenerationOptions

    return generate(
        project=project,
        output_type="dbt",
        output_path=tmp_path / "dbt",
        runtime_config=runtime_config,
        options=GenerationOptions(**options),
    )


def _issues(report, code: str) -> list:
    return [issue for issue in report.issues if issue.code == code]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Resolved names in the export
# ---------------------------------------------------------------------------


def test_without_stored_outputs_the_names_are_derived(project):
    export = _export(project)

    (hub,) = [h for h in export.hubs if h.hub_name == "CUSTOMER_H"]
    assert hub.output.model_name == "CUSTOMER_H"
    assert hub.effectivity_satellite_output.model_name == "customer_es"
    assert hub.record_tracking_satellite_output.model_name == "customer_ts"
    stages = {s.stage_name for s in export.stages}
    assert stages == {"stg__crm__customer", "stg__crm__nation"}

    satellites = {s.satellite_name: s for s in export.satellites}
    assert satellites["CUSTOMER_S"].v0_output.model_name == "CUSTOMER_S_v0"
    assert satellites["CUSTOMER_S"].v1_output.model_name == "CUSTOMER_S_v1"

    (pit,) = export.pits
    assert pit.satellite_models == ["CUSTOMER_S_v0"]
    assert pit.snapshot_control_name == "control_snap_v1"
    (reference_table,) = export.reference_tables
    assert [s.model_name for s in reference_table.satellites] == ["NATION_RS_v1"]
    (control,) = export.snapshot_controls
    assert (control.v0_name, control.v1_name) == ("control_snap_v0", "control_snap_v1")


def test_stored_names_reach_every_reference(project):
    customer = _get("SourceTable", physical_table_name="CUSTOMER")
    satellite = _get("Satellite", satellite_physical_name="CUSTOMER_S")
    reference_satellite = _get("Satellite", satellite_physical_name="NATION_RS")
    control = _get("SnapshotControlTable", name="control_snap")
    _store("stage", customer, model_name="stg_customer")
    _store("satellite_v0", satellite, model_name="customer_s")
    _store("satellite_v1", reference_satellite, model_name="nation_rs_current")
    _store("snapshot_control_v1", control, model_name="snapshot_logic")

    export = _export(project)

    hub = next(h for h in export.hubs if h.hub_name == "CUSTOMER_H")
    assert [s.stage_name for s in hub.source_tables] == ["stg_customer"]
    satellites = {s.satellite_name: s for s in export.satellites}
    assert satellites["CUSTOMER_S"].stage_name == "stg_customer"
    (pit,) = export.pits
    assert pit.satellite_models == ["customer_s"]
    assert pit.snapshot_control_name == "snapshot_logic"
    (reference_table,) = export.reference_tables
    assert [s.model_name for s in reference_table.satellites] == ["nation_rs_current"]


def test_stage_and_prestage_names_follow_their_patterns(project):
    from engine.models import SourceTable
    from engine.services.runtime_config import EngineRuntimeConfig

    SourceTable.objects.filter(physical_table_name="NATION").update(
        table_type=SourceTable.TableType.PRESTAGE
    )
    config = EngineRuntimeConfig(
        project_name="outputs",
        stage_naming="[[ source_system ]]_[[ source_table ]]_stage",
        prestage_naming="prep_[[ source_table ]]",
    )

    export = _export(project, runtime_config=config)

    stages = {s.source_table: s for s in export.stages}
    assert stages["CUSTOMER"].stage_name == "crm_customer_stage"
    assert stages["NATION"].stage_name == "crm_nation_stage"
    assert stages["NATION"].prestage_model == "prep_nation"
    assert [p.model_name for p in export.prestages] == ["prep_nation"]


def test_a_stored_prestage_name_is_what_its_stage_reads(project):
    from engine.models import SourceTable

    nation = _get("SourceTable", physical_table_name="NATION")
    nation.table_type = SourceTable.TableType.PRESTAGE
    nation.save()
    _store("prestage", nation, model_name="int_nation_flattened")

    export = _export(project)

    stage = next(s for s in export.stages if s.source_table == "NATION")
    assert stage.prestage_model == "int_nation_flattened"
    assert [p.model_name for p in export.prestages] == ["int_nation_flattened"]


# ---------------------------------------------------------------------------
# Generated files
# ---------------------------------------------------------------------------


def test_files_and_references_follow_the_stored_names(project, tmp_path):
    customer = _get("SourceTable", physical_table_name="CUSTOMER")
    satellite = _get("Satellite", satellite_physical_name="CUSTOMER_S")
    reference_satellite = _get("Satellite", satellite_physical_name="NATION_RS")
    control = _get("SnapshotControlTable", name="control_snap")
    _store("stage", customer, model_name="stg_customer")
    _store("satellite_v0", satellite, model_name="customer_s")
    _store("satellite_v1", satellite, model_name="customer_s_current")
    _store("satellite_v1", reference_satellite, model_name="nation_rs_current")
    _store("snapshot_control_v1", control, model_name="snapshot_logic")

    report = _generate(project, tmp_path)
    assert report.status == "success", report.issues
    models = tmp_path / "dbt" / "models"

    hub = _read(models / "30_raw_vault" / "CUSTOMER_H.sql")
    assert "    - name: stg_customer\n" in hub
    assert (models / "20_staging" / "crm" / "stg_customer.sql").exists()

    v1 = _read(models / "30_raw_vault" / "customer_s_current.sql")
    assert "sat_v0: customer_s\n" in v1
    v1_yaml = yaml.safe_load(_read(models / "30_raw_vault" / "customer_s_current.yml"))
    assert v1_yaml["models"][0]["name"] == "customer_s_current"

    pit = _read(models / "40_business_vault" / "pits" / "CUSTOMER_PIT.sql")
    assert "sat_names:\n    - customer_s\n" in pit
    assert "snapshot_relation: snapshot_logic\n" in pit
    assert "clean_up_pit('snapshot_logic')" in pit

    reference_table = _read(models / "30_raw_vault" / "NATION_R.sql")
    assert "    nation_rs_current:" in reference_table

    snapshot_logic = _read(models / "00_control" / "snapshot_logic.sql")
    assert "control_snap_v0: control_snap_v0\n" in snapshot_logic
    assert not _issues(report, "render.template_outdated")


def test_a_stored_folder_outside_the_layer_gets_the_layer_settings(project, tmp_path):
    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    _store("hub", hub, folder="models/raw_vault/hubs")

    report = _generate(project, tmp_path)
    assert report.status == "success", report.issues

    folder = tmp_path / "dbt" / "models" / "raw_vault" / "hubs"
    assert _read(folder / "CUSTOMER_H.sql").startswith(
        "{{ config(\n"
        "    materialized='incremental',\n"
        "    schema='rdv',\n"
        "    tags=['hub', 'raw_vault']\n"
        ") }}\n"
    )
    # Its effectivity and record-tracking satellites follow the hub
    assert (folder / "customer_es.sql").exists()
    assert (folder / "customer_ts.sql").exists()
    assert not (
        tmp_path / "dbt" / "models" / "30_raw_vault" / "CUSTOMER_H.sql"
    ).exists()


def test_a_folder_inside_the_layer_inherits_its_settings(project, tmp_path):
    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    _store("hub", hub, folder="models/30_raw_vault/crm/")

    _generate(project, tmp_path)

    sql = _read(tmp_path / "dbt" / "models" / "30_raw_vault" / "crm" / "CUSTOMER_H.sql")
    assert sql.startswith("{{ config(\n    tags=['hub', 'raw_vault']\n) }}\n")


def test_stored_settings_override_the_template_defaults(project, tmp_path):
    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    _store(
        "hub",
        hub,
        alias="customer_hub",
        schema_name="raw",
        tags=["crm", "core"],
        config={
            "unique_key": "hk_customer_h",
            "post_hook": "grant select on {{ this }} to role reporting",
        },
    )

    report = _generate(project, tmp_path)
    assert report.status == "success", report.issues

    folder = tmp_path / "dbt" / "models" / "30_raw_vault"
    # Stored tags add to the template's
    assert _read(folder / "CUSTOMER_H.sql").startswith(
        "{{ config(\n"
        "    alias='customer_hub',\n"
        "    schema='raw',\n"
        "    tags=['hub', 'raw_vault', 'crm', 'core'],\n"
        "    unique_key='hk_customer_h',\n"
        "    post_hook='grant select on {{ this }} to role reporting'\n"
        ") }}\n"
    )
    schema = yaml.safe_load(_read(folder / "CUSTOMER_H.yml"))
    assert schema["models"][0]["config"]["tags"] == ["hub", "raw_vault", "crm", "core"]


def test_without_default_tags_models_carry_their_own(project, tmp_path):
    from engine.services.runtime_config import EngineRuntimeConfig

    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    _store("hub", hub, tags=["crm"])

    report = _generate(
        project, tmp_path, runtime_config=EngineRuntimeConfig(add_default_tags=False)
    )

    assert report.status == "success", report.issues
    folder = tmp_path / "dbt" / "models" / "30_raw_vault"
    assert "tags=['crm']" in _read(folder / "CUSTOMER_H.sql")
    schema = yaml.safe_load(_read(folder / "CUSTOMER_H.yml"))
    assert schema["models"][0]["config"]["tags"] == ["crm"]
    # A model without tags of its own has none
    nation = _read(folder / "NATION_RH.sql")
    assert "tags=" not in nation.split("{%- set yaml_metadata")[0]


def test_a_stored_materialization_replaces_the_specific_one(project, tmp_path):
    satellite = _get("Satellite", satellite_physical_name="CUSTOMER_S")
    _store("satellite_v1", satellite, materialized="table")

    _generate(project, tmp_path)

    v1 = _read(tmp_path / "dbt" / "models" / "30_raw_vault" / "CUSTOMER_S_v1.sql")
    assert v1.startswith("{{ config(\n    materialized='table',\n")


def test_the_v1_view_follows_its_v0_folder(project, tmp_path):
    satellite = _get("Satellite", satellite_physical_name="CUSTOMER_S")
    _store("satellite_v0", satellite, folder="models/raw_vault/satellites")

    _generate(project, tmp_path)

    folder = tmp_path / "dbt" / "models" / "raw_vault" / "satellites"
    assert (folder / "CUSTOMER_S_v0.sql").exists()
    v1 = _read(folder / "CUSTOMER_S_v1.sql")
    # The view keeps its own materialization and gets the layer's schema
    assert v1.startswith("{{ config(\n    materialized='view',\n    schema='rdv',\n")


def test_model_paths_cover_folders_outside_models(project, tmp_path):
    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    _store("hub", hub, folder="dv/raw_vault")

    _generate(project, tmp_path)

    project_yml = yaml.safe_load(_read(tmp_path / "dbt" / "dbt_project.yml"))
    assert project_yml["model-paths"] == ["models", "dv"]
    assert (tmp_path / "dbt" / "dv" / "raw_vault" / "CUSTOMER_H.sql").exists()


def test_without_model_folders_every_model_goes_to_its_layer(project, tmp_path):
    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    customer = _get("SourceTable", physical_table_name="CUSTOMER")
    _store("hub", hub, folder="dv/raw_vault")
    _store("stage", customer, model_name="stg_customer", folder="models/staging")

    _generate(project, tmp_path, use_model_folders=False)

    root = tmp_path / "dbt"
    sql = _read(root / "models" / "30_raw_vault" / "CUSTOMER_H.sql")
    assert "schema=" not in sql
    assert (root / "models" / "20_staging" / "crm" / "stg_customer.sql").exists()
    assert yaml.safe_load(_read(root / "dbt_project.yml"))["model-paths"] == ["models"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_two_models_of_one_name_are_an_error(project, tmp_path):
    customer = _get("SourceTable", physical_table_name="CUSTOMER")
    _store("stage", customer, model_name="customer_h")

    report = _generate(project, tmp_path, dry_run=True)

    (issue,) = _issues(report, "validate.model.duplicate_name")
    assert issue.severity == "error"
    assert "customer_h" in issue.message


def test_a_folder_outside_the_project_is_never_written(project, tmp_path):
    from engine.models import ModelOutput

    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    # Stored without validation, as a direct database write could
    ModelOutput.objects.create(kind="hub", hub=hub, folder="../outside")

    report = _generate(project, tmp_path)

    assert _issues(report, "validate.model.invalid_folder")
    assert not (tmp_path / "outside").exists()
    assert not list(tmp_path.rglob("CUSTOMER_H.sql"))


# ---------------------------------------------------------------------------
# Templates from before model outputs
# ---------------------------------------------------------------------------

OLD_HUB_TEMPLATE = """{{ config(
    tags=['hub', 'raw_vault']
) }}

{%- set yaml_metadata -%}
source_models:
[% for source in source_tables %]
    - name: [[ source.stage_name ]]
[% endfor %]
hashkey: [[ hashkey.hashkey_name ]]
business_keys:
[% for bk in business_key_columns %]
    - [[ bk ]]
[% endfor %]
{%- endset -%}

{{ datavault4dbt.hub(yaml_metadata=yaml_metadata) }}
"""

OLD_V1_TEMPLATE = """{{ config(materialized='view') }}
{%- set yaml_metadata -%}
sat_v0: [[ satellite_name ]]_v0
hashkey: [[ parent_hashkey ]]
hashdiff: [[ hashdiff_name ]]
{%- endset -%}
{{ datavault4dbt.sat_v1(yaml_metadata=yaml_metadata) }}
"""


def test_an_old_template_that_ignores_stored_settings_is_reported(project, tmp_path):
    from engine.services.generation.types import TemplateOverride

    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    _store("hub", hub, alias="customer_hub")

    report = _generate(
        project,
        tmp_path,
        dry_run=True,
        templates_override={
            "dbt": {"hub_standard": TemplateOverride(sql=OLD_HUB_TEMPLATE)}
        },
    )

    outdated = _issues(report, "render.template_outdated")
    assert [issue.entity.name for issue in outdated] == ["CUSTOMER_H"]
    assert "stored dbt settings" in outdated[0].message


def test_an_old_v1_template_missing_the_stored_v0_name_is_reported(project, tmp_path):
    from engine.services.generation.types import TemplateOverride

    satellite = _get("Satellite", satellite_physical_name="CUSTOMER_S")
    _store("satellite_v0", satellite, model_name="customer_s")

    report = _generate(
        project,
        tmp_path,
        dry_run=True,
        templates_override={
            "dbt": {"satellite_v1": TemplateOverride(sql=OLD_V1_TEMPLATE)}
        },
    )

    outdated = [
        issue
        for issue in _issues(report, "render.template_outdated")
        if issue.entity.name == "CUSTOMER_S_v1"
    ]
    assert len(outdated) == 1
    assert "'customer_s'" in outdated[0].message


def test_an_old_template_is_fine_while_nothing_is_stored(project, tmp_path):
    from engine.services.generation.types import TemplateOverride

    report = _generate(
        project,
        tmp_path,
        dry_run=True,
        templates_override={
            "dbt": {
                "hub_standard": TemplateOverride(sql=OLD_HUB_TEMPLATE),
                "satellite_v1": TemplateOverride(sql=OLD_V1_TEMPLATE),
            }
        },
    )

    assert not _issues(report, "render.template_outdated")


# ---------------------------------------------------------------------------
# The stored model
# ---------------------------------------------------------------------------


def test_the_project_and_folder_are_set_on_save(project):
    hub = _get("Hub", hub_physical_name="CUSTOMER_H")

    output = _store("hub", hub, folder="models\\raw_vault\\")

    assert output.project == project
    assert output.folder == "models/raw_vault"


@pytest.mark.parametrize(
    ("kind", "entity", "fields", "message"),
    [
        ("satellite_v0", "hub", {}, "belongs to a satellite"),
        ("hub", "hub", {"model_name": "customer_hub"}, "rename the entity"),
        ("stage", "table", {"model_name": "stg customer"}, "can't name a dbt model"),
        ("stage", "table", {"model_name": "../stg"}, "can't name a dbt model"),
        ("prestage", "table", {"folder": "models/prep"}, "only its name"),
        ("hub", "hub", {"folder": "../models"}, "inside the dbt project"),
        ("hub", "hub", {"folder": "/models"}, "relative to the dbt project"),
        ("hub", "hub", {"config": {"schema": "raw"}}, r"own field \(schema_name\)"),
        ("hub", "hub", {"folder": "\\models"}, "relative to the dbt project"),
        ("hub", "hub", {"tags": "crm"}, "list of strings"),
    ],
)
def test_invalid_outputs_are_rejected(project, kind, entity, fields, message):
    target = (
        _get("Hub", hub_physical_name="CUSTOMER_H")
        if entity == "hub"
        else _get("SourceTable", physical_table_name="CUSTOMER")
    )

    with pytest.raises(ValidationError, match=message):
        _store(kind, target, **fields)


def test_a_stored_name_is_unique_in_the_project(project):
    customer = _get("SourceTable", physical_table_name="CUSTOMER")
    nation = _get("SourceTable", physical_table_name="NATION")
    _store("stage", customer, model_name="stg_shared")

    with pytest.raises(ValidationError, match="Another model"):
        _store("stage", nation, model_name="stg_shared")
