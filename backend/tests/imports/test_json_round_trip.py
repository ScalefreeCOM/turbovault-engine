"""A JSON export restores everything a project stores.

The stage, satellite, hub, link, PIT and snapshot control options and every
entity's stored model outputs (names, folders, config() settings) come back
as they were: in a new project, and unchanged in the project itself. A
setting the export doesn't have (it was written before the setting existed)
leaves the project's value alone; one it has, an empty value included, is
restored. Snapshot controls are imported before the PITs and reference
tables that read them, also when a stored name renames their models.
"""

from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path
from typing import Any

import pytest
from engine.models import (
    PIT,
    Hub,
    HubColumn,
    HubSourceMapping,
    Link,
    LinkHubReference,
    ModelOutput,
    Project,
    ReferenceTable,
    ReferenceTableSatelliteAssignment,
    Satellite,
    SatelliteColumn,
    SnapshotControlLogic,
    SnapshotControlTable,
    SourceColumn,
    SourceSystem,
    SourceTable,
)
from engine.services.export.builder import ModelBuilder
from engine.services.imports import ImportOptions, JsonSource, import_metadata
from engine.services.staging_service import get_or_create_staging_column

pytestmark = pytest.mark.django_db

Component = SnapshotControlLogic.SnapshotComponent
Unit = SnapshotControlLogic.SnapshotUnit


# ---------------------------------------------------------------------------
# A project that stores every setting
# ---------------------------------------------------------------------------


def _column(table: SourceTable, name: str, **values: Any) -> SourceColumn:
    return SourceColumn.objects.create(
        source_table=table,
        source_column_physical_name=name,
        source_column_datatype="VARCHAR",
        **values,
    )


def _staging(table: SourceTable, name: str):
    return get_or_create_staging_column(
        SourceColumn.objects.get(source_table=table, source_column_physical_name=name)
    )


def _build(name: str) -> Project:
    project = Project.objects.create(name=name)
    crm = SourceSystem.objects.create(
        project=project,
        schema_name="crm_raw",
        name="CRM",
        include_source_columns=False,
        delivery_method="single_batch",
    )
    customer = SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="CUSTOMER",
        enable_ghost_records=False,
        sequence_column="SEQ",
        delivery_method="multi_batch",
    )
    for column in ("ID", "REFERRER_ID", "NAME", "SEQ"):
        _column(customer, column)
    _column(customer, "LEGACY_FLAG", is_missing=True)
    ModelOutput.objects.create(
        source_table=customer,
        kind="stage",
        model_name="stg_crm_customer",
        folder="models/staging/crm",
        materialized="view",
        tags=["crm"],
        config={"on_schema_change": "sync_all_columns"},
    )
    address = SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="ADDRESS",
        table_type=SourceTable.TableType.PRESTAGE,
    )
    _column(address, "CUSTOMER_ID")
    ModelOutput.objects.create(
        source_table=address, kind="prestage", model_name="prep_crm_address"
    )
    nation = SourceTable.objects.create(
        project=project, source_system=crm, physical_table_name="NATION"
    )
    for column in ("N_NATIONKEY", "N_NAME"):
        _column(nation, column)

    # A hub loaded twice from one stage (role-playing), with options
    customer_h = Hub.objects.create(
        project=project,
        hub_physical_name="CUSTOMER_H",
        hub_hashkey_name="HK_CUSTOMER_H",
        create_effectivity_satellite=True,
        disable_hwm=True,
        effectivity_is_active_alias="is_live",
        effectivity_disable_hwm=True,
        effectivity_additional_columns=["NAME"],
    )
    customer_id = HubColumn.objects.create(hub=customer_h, column_name="CUSTOMER_ID")
    HubSourceMapping.objects.create(
        hub_column=customer_id,
        staging_column=_staging(customer, "ID"),
        is_primary_source=True,
    )
    HubSourceMapping.objects.create(
        hub_column=customer_id,
        staging_column=_staging(customer, "REFERRER_ID"),
        stage_hashkey_name="HK_REFERRER_H",
    )
    ModelOutput.objects.create(
        hub=customer_h, kind="hub", folder="models/raw_vault/hubs", alias="customer"
    )
    ModelOutput.objects.create(
        hub=customer_h, kind="effectivity_satellite", model_name="customer_es"
    )

    referral_l = Link.objects.create(
        project=project,
        link_physical_name="REFERRAL_L",
        link_hashkey_name="HK_REFERRAL_L",
        link_type=Link.LinkType.NON_HISTORIZED,
        create_effectivity_satellite=True,
        disable_hwm=True,
        union_strategy="distinct",
        effectivity_is_active_alias="active",
    )
    LinkHubReference.objects.create(link=referral_l, hub=customer_h, sort_order=1)
    ModelOutput.objects.create(
        link=referral_l, kind="link", tags=[], materialized="incremental"
    )

    # A satellite with every option, and one that stores none
    customer_s = Satellite.objects.create(
        project=project,
        satellite_physical_name="CUSTOMER_S",
        parent_hub=customer_h,
        source_table=customer,
        hashdiff_name="HD_CUSTOMER_CUSTOM",
        hashdiff_alias="hashdiff",
        create_v1_view=False,
        v1_ledts_alias="valid_to",
        v1_add_is_current_flag=False,
        v1_include_payload=False,
        disable_hwm=True,
    )
    SatelliteColumn.objects.create(
        satellite=customer_s, staging_column=_staging(customer, "NAME")
    )
    ModelOutput.objects.create(
        satellite=customer_s, kind="satellite_v0", model_name="customer_sat"
    )
    plain_s = Satellite.objects.create(
        project=project,
        satellite_physical_name="CUSTOMER_PLAIN_S",
        parent_hub=customer_h,
        source_table=customer,
    )
    SatelliteColumn.objects.create(
        satellite=plain_s, staging_column=_staging(customer, "SEQ")
    )

    # A snapshot control whose logic model has a stored name
    control = SnapshotControlTable.objects.create(
        project=project,
        name="control_snap",
        snapshot_start_date=date(2020, 1, 1),
        daily_snapshot_time=time(7, 30),
        sdts_alias="snapshot_ts",
    )
    is_active = SnapshotControlLogic.objects.create(
        snapshot_control_table=control,
        snapshot_control_logic_column_name="is_active",
        snapshot_component=Component.BEGINNING_OF_MONTH,
        snapshot_duration=1,
        snapshot_unit=Unit.YEAR,
    )
    is_weekly = SnapshotControlLogic.objects.create(
        snapshot_control_table=control,
        snapshot_control_logic_column_name="is_weekly",
        snapshot_component=Component.BEGINNING_OF_WEEK,
        snapshot_forever=True,
    )
    ModelOutput.objects.create(
        snapshot_control=control,
        kind="snapshot_control_v1",
        model_name="snapshot_logic",
        folder="models/control",
    )

    pit = PIT.objects.create(
        project=project,
        pit_physical_name="CUSTOMER_PIT",
        tracked_entity_type="hub",
        tracked_hub=customer_h,
        snapshot_control_table=control,
        snapshot_control_logic=is_weekly,
        use_snapshot_optimization=True,
        custom_record_source="TURBOVAULT",
        include_business_objects_before_appearance=True,
    )
    pit.satellites.set([customer_s])
    ModelOutput.objects.create(pit=pit, kind="pit", folder="models/business_vault/pits")

    # A snapshot-based reference table
    nation_rh = Hub.objects.create(
        project=project, hub_physical_name="NATION_RH", hub_type="reference"
    )
    HubSourceMapping.objects.create(
        hub_column=HubColumn.objects.create(
            hub=nation_rh, column_name="N_NATIONKEY", column_type="reference_key"
        ),
        staging_column=_staging(nation, "N_NATIONKEY"),
        is_primary_source=True,
    )
    nation_rs = Satellite.objects.create(
        project=project,
        satellite_physical_name="NATION_RS",
        satellite_type="reference",
        parent_hub=nation_rh,
        source_table=nation,
    )
    SatelliteColumn.objects.create(
        satellite=nation_rs, staging_column=_staging(nation, "N_NAME")
    )
    nation_r = ReferenceTable.objects.create(
        project=project,
        reference_table_physical_name="NATION_R",
        reference_hub=nation_rh,
        historization_type="snapshot_based",
        snapshot_control_table=control,
        snapshot_control_logic=is_active,
    )
    ReferenceTableSatelliteAssignment.objects.create(
        reference_table=nation_r, reference_satellite=nation_rs
    )
    ModelOutput.objects.create(
        reference_table=nation_r, kind="reference_table", materialized="table"
    )
    return project


# ---------------------------------------------------------------------------
# What a project stores, by entity name
# ---------------------------------------------------------------------------

_OUTPUT_FIELDS = (
    "model_name",
    "folder",
    "alias",
    "schema_name",
    "database_name",
    "materialized",
    "tags",
    "config",
)


def _values(obj: Any, *fields: str) -> dict[str, Any]:
    return {field: getattr(obj, field) for field in fields}


def _output_owner(row: ModelOutput) -> str:
    entity = row.entity
    for attr in (
        "physical_table_name",
        "hub_physical_name",
        "link_physical_name",
        "satellite_physical_name",
        "pit_physical_name",
        "reference_table_physical_name",
        "name",
    ):
        if hasattr(entity, attr):
            return getattr(entity, attr)
    raise AssertionError(row)


def _stored(project: Project) -> dict[str, Any]:
    """Every value the round trip restores, keyed by names (not keys)."""
    state: dict[str, Any] = {}
    for system in SourceSystem.objects.filter(project=project):
        state[f"system:{system.name}"] = _values(
            system, "include_source_columns", "enable_ghost_records", "delivery_method"
        )
    for table in SourceTable.objects.filter(project=project):
        state[f"table:{table.physical_table_name}"] = {
            **_values(
                table,
                "table_type",
                "include_source_columns",
                "enable_ghost_records",
                "sequence_column",
                "delivery_method",
            ),
            "columns": {
                column.source_column_physical_name: column.is_missing
                for column in table.columns.all()
            },
        }
    for hub in Hub.objects.filter(project=project):
        state[f"hub:{hub.hub_physical_name}"] = {
            **_values(
                hub,
                "hub_type",
                "hub_hashkey_name",
                "create_effectivity_satellite",
                "disable_hwm",
                "effectivity_is_active_alias",
                "effectivity_disable_hwm",
                "effectivity_additional_columns",
            ),
            "mappings": sorted(
                (
                    mapping.hub_column.column_name,
                    mapping.staging_column.physical_name,
                    mapping.is_primary_source,
                    mapping.stage_hashkey_name,
                )
                for mapping in HubSourceMapping.objects.filter(hub_column__hub=hub)
            ),
        }
    for link in Link.objects.filter(project=project):
        state[f"link:{link.link_physical_name}"] = _values(
            link,
            "link_type",
            "create_effectivity_satellite",
            "disable_hwm",
            "union_strategy",
            "effectivity_is_active_alias",
            "effectivity_disable_hwm",
            "effectivity_additional_columns",
        )
    for sat in Satellite.objects.filter(project=project):
        state[f"satellite:{sat.satellite_physical_name}"] = _values(
            sat,
            "satellite_type",
            "hashdiff_name",
            "hashdiff_alias",
            "create_v1_view",
            "v1_ledts_alias",
            "v1_add_is_current_flag",
            "v1_include_payload",
            "disable_hwm",
        )
    for control in SnapshotControlTable.objects.filter(project=project):
        state[f"snapshot_control:{control.name}"] = {
            **_values(
                control,
                "snapshot_start_date",
                "snapshot_end_date",
                "daily_snapshot_time",
                "sdts_alias",
            ),
            "logic": sorted(
                (
                    rule.snapshot_control_logic_column_name,
                    rule.snapshot_component,
                    rule.snapshot_duration,
                    rule.snapshot_unit,
                    rule.snapshot_forever,
                )
                for rule in control.logic_rules.all()
            ),
        }
    for pit in PIT.objects.filter(project=project):
        state[f"pit:{pit.pit_physical_name}"] = {
            **_values(
                pit,
                "use_snapshot_optimization",
                "custom_record_source",
                "include_business_objects_before_appearance",
            ),
            "control": pit.snapshot_control_table.name,
            "logic": pit.snapshot_control_logic.snapshot_control_logic_column_name,
            "satellites": sorted(
                s.satellite_physical_name for s in pit.satellites.all()
            ),
        }
    for ref in ReferenceTable.objects.filter(project=project):
        state[f"reference_table:{ref.reference_table_physical_name}"] = {
            "historization_type": ref.historization_type,
            "control": ref.snapshot_control_table and ref.snapshot_control_table.name,
            "logic": ref.snapshot_control_logic
            and ref.snapshot_control_logic.snapshot_control_logic_column_name,
        }
    for row in ModelOutput.objects.filter(project=project):
        state[f"output:{_output_owner(row)}:{row.kind}"] = _values(row, *_OUTPUT_FIELDS)
    return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _export_data(project: Project) -> dict:
    return json.loads(
        json.dumps(ModelBuilder(project).build().model_dump(mode="json"), default=str)
    )


def _write(data: dict, path: Path) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _import(project: Project, path: Path, **options: Any):
    return import_metadata(
        project=project, source=JsonSource(path=path), options=ImportOptions(**options)
    )


def _entities(data: dict, key: str) -> list[dict]:
    if key in ("tables", "columns"):
        tables = [table for system in data["sources"] for table in system["tables"]]
        if key == "tables":
            return tables
        return [column for table in tables for column in table["columns"]]
    return data[key]


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_an_export_restores_every_stored_setting(tmp_path):
    source = _build("source")
    path = _write(_export_data(source), tmp_path / "model.json")
    target = Project.objects.create(name="target")

    report = _import(target, path)

    assert report.status == "success", report.issues
    assert _stored(target) == _stored(source)


def test_reimporting_an_export_changes_nothing(tmp_path):
    project = _build("again")
    before = _stored(project)
    path = _write(_export_data(project), tmp_path / "model.json")

    report = _import(project, path)

    assert report.status == "success", report.issues
    changed = {
        (entity.ref.type, entity.ref.name): entity.changes
        for entity in report.plan.entities
        if entity.action != "unchanged"
    }
    assert changed == {}
    assert _stored(project) == before


def test_the_export_carries_the_stored_values_not_the_derived_ones():
    data = _export_data(_build("stored"))

    customer = next(
        t for t in _entities(data, "tables") if t["table_name"] == "CUSTOMER"
    )
    assert customer["model_outputs"] == {
        "stage": {
            "model_name": "stg_crm_customer",
            "folder": "models/staging/crm",
            "alias": None,
            "schema_name": None,
            "database_name": None,
            "materialized": "view",
            "tags": ["crm"],
            "config": {"on_schema_change": "sync_all_columns"},
        }
    }
    nation = next(t for t in _entities(data, "tables") if t["table_name"] == "NATION")
    assert nation["model_outputs"] == {}
    hub = next(h for h in data["hubs"] if h["hub_name"] == "CUSTOMER_H")
    assert hub["model_outputs"]["hub"]["model_name"] is None
    assert hub["output"]["model_name"] == "CUSTOMER_H"


# ---------------------------------------------------------------------------
# What the export has, and what it doesn't
# ---------------------------------------------------------------------------


def test_an_older_export_leaves_the_stored_settings_alone(tmp_path):
    project = _build("older")
    before = _stored(project)
    data = _export_data(project)
    newer = {
        "systems": (
            "include_source_columns",
            "enable_ghost_records",
            "delivery_method",
        ),
        "tables": (
            "include_source_columns",
            "enable_ghost_records",
            "sequence_column",
            "delivery_method",
            "model_outputs",
        ),
        "columns": ("is_missing",),
        "hubs": ("disable_hwm", "effectivity_options", "model_outputs"),
        "links": (
            "create_effectivity_satellite",
            "disable_hwm",
            "union_strategy",
            "effectivity_options",
            "model_outputs",
        ),
        "satellites": (
            "hashdiff_alias",
            "create_v1_view",
            "v1_ledts_alias",
            "v1_add_is_current_flag",
            "v1_include_payload",
            "disable_hwm",
            "model_outputs",
        ),
        "snapshot_controls": ("sdts_alias", "model_outputs"),
        "reference_tables": ("model_outputs",),
        "pits": (
            "use_snapshot_optimization",
            "include_business_objects_before_appearance",
            "model_outputs",
        ),
    }
    for key, fields in newer.items():
        entities = data["sources"] if key == "systems" else _entities(data, key)
        for entity in entities:
            for field in fields:
                entity.pop(field, None)
    for hub in data["hubs"]:
        for source in hub["source_tables"]:
            source.pop("hk_column", None)

    report = _import(project, _write(data, tmp_path / "older.json"))

    assert report.status == "success", report.issues
    assert _stored(project) == before


def test_an_export_clears_what_it_leaves_empty(tmp_path):
    project = _build("cleared")
    data = _export_data(project)
    customer = next(
        t for t in _entities(data, "tables") if t["table_name"] == "CUSTOMER"
    )
    customer["sequence_column"] = None
    del customer["model_outputs"]["stage"]
    sat = next(s for s in data["satellites"] if s["satellite_name"] == "CUSTOMER_S")
    sat["hashdiff_alias"] = None
    sat["create_v1_view"] = None
    pit = data["pits"][0]
    pit["use_snapshot_optimization"] = None
    data["snapshot_controls"][0]["sdts_alias"] = None

    report = _import(project, _write(data, tmp_path / "cleared.json"))

    assert report.status == "success", report.issues
    table = SourceTable.objects.get(project=project, physical_table_name="CUSTOMER")
    assert table.sequence_column is None
    assert not ModelOutput.objects.filter(source_table=table).exists()
    satellite = Satellite.objects.get(
        project=project, satellite_physical_name="CUSTOMER_S"
    )
    assert satellite.hashdiff_alias is None
    assert satellite.create_v1_view is None
    assert PIT.objects.get(project=project).use_snapshot_optimization is None
    assert SnapshotControlTable.objects.get(project=project).sdts_alias is None
    changes = {
        entity.ref.name: {change.field for change in entity.changes}
        for entity in report.plan.entities
        if entity.action == "update"
    }
    assert changes["CUSTOMER"] == {"sequence_column", "model_outputs.stage"}


def test_a_derived_hash_diff_name_stays_derived(tmp_path):
    source = _build("hashdiff")
    data = _export_data(source)
    plain = next(
        s for s in data["satellites"] if s["satellite_name"] == "CUSTOMER_PLAIN_S"
    )
    assert plain["hashdiff_name"] == "hd_CUSTOMER_PLAIN_S"
    target = Project.objects.create(name="hashdiff_target")

    _import(target, _write(data, tmp_path / "model.json"))

    satellites = {
        sat.satellite_physical_name: sat.hashdiff_name
        for sat in Satellite.objects.filter(project=target)
    }
    assert satellites["CUSTOMER_PLAIN_S"] is None
    assert satellites["CUSTOMER_S"] == "HD_CUSTOMER_CUSTOM"


def test_an_invalid_model_output_is_reported_and_left_out(tmp_path):
    data = _export_data(_build("invalid"))
    hub = next(h for h in data["hubs"] if h["hub_name"] == "CUSTOMER_H")
    hub["model_outputs"]["hub"]["folder"] = "../outside"
    target = Project.objects.create(name="invalid_target")

    report = _import(target, _write(data, tmp_path / "invalid.json"))

    (issue,) = [i for i in report.issues if i.code == "entity.invalid_configuration"]
    assert "hub model of hub 'CUSTOMER_H'" in issue.message
    assert "must stay inside the dbt project" in issue.message
    imported = Hub.objects.get(project=target, hub_physical_name="CUSTOMER_H")
    kinds = set(ModelOutput.objects.filter(hub=imported).values_list("kind", flat=True))
    assert kinds == {"effectivity_satellite"}


# ---------------------------------------------------------------------------
# Snapshot controls
# ---------------------------------------------------------------------------


def test_snapshot_controls_are_skipped_with_skip_snapshots(tmp_path):
    data = _export_data(_build("no_snapshots"))
    target = Project.objects.create(name="no_snapshots_target")

    report = _import(target, _write(data, tmp_path / "model.json"), skip_snapshots=True)

    controls = [e for e in report.plan.entities if e.ref.type == "snapshot_control"]
    assert [(e.action, e.skip_reason) for e in controls] == [("skip", "skip_snapshots")]
    assert not SnapshotControlTable.objects.filter(project=target).exists()


def test_a_snapshot_control_matches_by_base_name(tmp_path):
    """An export naming the control control_snap_v0 updates control_snap."""
    project = _build("base_name")
    data = _export_data(project)
    data["snapshot_controls"][0]["name"] = "control_snap_v0"
    data["snapshot_controls"][0]["daily_time"] = "06:00:00"

    report = _import(project, _write(data, tmp_path / "model.json"))

    assert report.status == "success", report.issues
    (control,) = SnapshotControlTable.objects.filter(project=project)
    assert control.name == "control_snap"
    assert control.daily_snapshot_time == time(6, 0)


def test_project_init_from_an_export_restores_its_snapshot_controls(
    tmp_path, monkeypatch
):
    """`project init --source model.json` imports the PITs and their controls."""
    from engine.cli.commands import init_cmd
    from engine.services import project_config
    from engine.services.config_schema import TurboVaultConfig

    source = _build("init_source")
    path = _write(_export_data(source), tmp_path / "model.json")
    monkeypatch.setattr(
        project_config, "initialize_project_folder", lambda project, config: tmp_path
    )
    config = TurboVaultConfig(
        project={"name": "init_copy"}, source={"type": "json", "path": str(path)}
    )

    init_cmd._create_project(config)

    assert _stored(Project.objects.get(name="init_copy")) == _stored(source)
