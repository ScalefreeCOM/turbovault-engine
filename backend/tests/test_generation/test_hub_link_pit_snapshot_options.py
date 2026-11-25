"""Hub, link, PIT and snapshot control options; delivery method.

Hubs and links: additional columns, loading without the high-water mark,
role-playing sources (a stage loading a hub under another hash key), and
effectivity satellites on links too. Non-historized links: union strategy.
The delivery method of source tables (issue #468) turns on datavault4dbt's
single-batch logic. PITs: custom record source and snapshot optimization
(written only when set). Snapshot controls: end date and sdts alias, written
only when set. Snapshot-based reference tables read their snapshot control.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(django_setup, db):
    """CUSTOMER_H (from CUSTOMER and ORDERS), ORDER_H, the link
    ORDER_CUSTOMER_L and the satellite CUSTOMER_S."""
    from engine.models import (
        Hub,
        HubColumn,
        HubSourceMapping,
        Link,
        LinkHubReference,
        LinkHubSourceMapping,
        Project,
        Satellite,
        SatelliteColumn,
        SourceColumn,
        SourceSystem,
        SourceTable,
    )
    from engine.services.staging_service import get_or_create_staging_column

    project = Project.objects.create(name="loading")
    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM"
    )

    def table(name: str, *columns: str):
        source_table = SourceTable.objects.create(
            project=project,
            source_system=crm,
            physical_table_name=name,
            load_date_value="LOAD_TS",
        )
        return {
            column: get_or_create_staging_column(
                SourceColumn.objects.create(
                    source_table=source_table,
                    source_column_physical_name=column,
                    source_column_datatype="VARCHAR",
                )
            )
            for column in columns
        }

    customer = table("CUSTOMER", "C_ID", "C_NAME", "C_BATCH", "LOAD_TS")
    orders = table("ORDERS", "O_ID", "O_CUSTOMER", "O_SELLER", "LOAD_TS")

    customer_hub = Hub.objects.create(
        project=project,
        hub_physical_name="CUSTOMER_H",
        hub_hashkey_name="hk_customer_h",
    )
    customer_id = HubColumn.objects.create(hub=customer_hub, column_name="CUSTOMER_ID")
    HubSourceMapping.objects.create(
        hub_column=customer_id, staging_column=customer["C_ID"], is_primary_source=True
    )
    HubSourceMapping.objects.create(
        hub_column=customer_id, staging_column=orders["O_CUSTOMER"]
    )

    order_hub = Hub.objects.create(
        project=project, hub_physical_name="ORDER_H", hub_hashkey_name="hk_order_h"
    )
    order_id = HubColumn.objects.create(hub=order_hub, column_name="ORDER_ID")
    HubSourceMapping.objects.create(
        hub_column=order_id, staging_column=orders["O_ID"], is_primary_source=True
    )

    link = Link.objects.create(
        project=project,
        link_physical_name="ORDER_CUSTOMER_L",
        link_hashkey_name="hk_order_customer_l",
    )
    for hub, column, staging in (
        (order_hub, order_id, orders["O_ID"]),
        (customer_hub, customer_id, orders["O_CUSTOMER"]),
    ):
        reference = LinkHubReference.objects.create(link=link, hub=hub)
        LinkHubSourceMapping.objects.create(
            link_hub_reference=reference,
            standard_hub_column=column,
            staging_column=staging,
        )

    satellite = Satellite.objects.create(
        project=project,
        satellite_physical_name="CUSTOMER_S",
        parent_hub=customer_hub,
        source_table=customer["C_NAME"].source_table,
    )
    SatelliteColumn.objects.create(
        satellite=satellite, staging_column=customer["C_NAME"]
    )
    return project


def _get(model: str, **lookup):
    from engine import models

    return getattr(models, model).objects.get(**lookup)


def _update(model: str, lookup: dict, **values) -> None:
    from engine import models

    getattr(models, model).objects.filter(**lookup).update(**values)


def _generate(project, tmp_path: Path, runtime_config=None, **options):
    from engine.services.generation import generate
    from engine.services.generation.types import GenerationOptions

    report = generate(
        project=project,
        output_type="dbt",
        output_path=tmp_path / "dbt",
        runtime_config=runtime_config,
        options=GenerationOptions(**options),
    )
    assert report.status == "success", report.issues
    return report


def _with_payload(link_name: str, column: str, source_column: str) -> None:
    """Give a link a payload column: a non-historized link needs one."""
    from engine.models import LinkColumn, LinkSourceMapping, StagingColumn

    staging = StagingColumn.objects.get(
        source_column__source_column_physical_name=source_column
    )
    payload = LinkColumn.objects.create(
        link=_get("Link", link_physical_name=link_name),
        column_name=column,
        column_type=LinkColumn.ColumnType.PAYLOAD,
        sort_order=1,
    )
    LinkSourceMapping.objects.create(link_column=payload, staging_column=staging)


def _metadata(tmp_path: Path, *parts: str) -> dict:
    """A model's yaml_metadata block, parsed as datavault4dbt will."""
    sql = (tmp_path / "dbt" / "models" / Path(*parts)).read_text(encoding="utf-8")
    block = re.search(
        r"\{%- set yaml_metadata -%\}\n(.*?)\{%- endset -%\}", sql, re.DOTALL
    )
    assert block, sql
    return yaml.safe_load(block.group(1))


def _raw_vault(tmp_path: Path, model: str) -> dict:
    return _metadata(tmp_path, "30_raw_vault", f"{model}.sql")


def _stage(tmp_path: Path, table: str) -> dict:
    return _metadata(tmp_path, "20_staging", "crm", f"stg__crm__{table}.sql")


def _delivery(**values):
    from engine.services.runtime_config import EngineRuntimeConfig

    return EngineRuntimeConfig(project_name="loading", **values)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_nothing_new_is_written_by_default(project, tmp_path):
    _update(
        "Hub", {"hub_physical_name": "CUSTOMER_H"}, create_effectivity_satellite=True
    )

    _generate(project, tmp_path)

    hub = _raw_vault(tmp_path, "CUSTOMER_H")
    link = _raw_vault(tmp_path, "ORDER_CUSTOMER_L")
    satellite = _raw_vault(tmp_path, "CUSTOMER_S_v0")
    for metadata in (hub, link, satellite):
        for key in ("additional_columns", "disable_hwm", "source_is_single_batch"):
            assert key not in metadata
    assert [source.get("hk_column") for source in hub["source_models"]] == [None, None]
    effectivity = _raw_vault(tmp_path, "customer_es")
    assert effectivity["source_is_single_batch"] is False
    assert "is_active_alias" not in effectivity


# ---------------------------------------------------------------------------
# Additional columns and high-water mark
# ---------------------------------------------------------------------------


def test_a_hubs_additional_column_comes_from_its_stage(project, tmp_path):
    from engine.models import HubColumn, HubSourceMapping, StagingColumn

    batch = HubColumn.objects.create(
        hub=_get("Hub", hub_physical_name="CUSTOMER_H"),
        column_name="LOAD_BATCH",
        column_type=HubColumn.ColumnType.ADDITIONAL_COLUMN,
        sort_order=9,
    )
    HubSourceMapping.objects.create(
        hub_column=batch,
        staging_column=StagingColumn.objects.get(
            source_column__source_column_physical_name="C_BATCH"
        ),
    )

    _generate(project, tmp_path)

    assert _raw_vault(tmp_path, "CUSTOMER_H")["additional_columns"] == ["LOAD_BATCH"]
    # The stage provides it under the hub column's name
    derived = _stage(tmp_path, "customer")["derived_columns"]
    assert derived["LOAD_BATCH"]["value"] == "C_BATCH"


def test_loading_without_the_high_water_mark(project, tmp_path):
    _update("Hub", {"hub_physical_name": "CUSTOMER_H"}, disable_hwm=True)
    _update("Link", {"link_physical_name": "ORDER_CUSTOMER_L"}, disable_hwm=True)
    _update("Satellite", {"satellite_physical_name": "CUSTOMER_S"}, disable_hwm=True)

    _generate(project, tmp_path)

    for model in ("CUSTOMER_H", "ORDER_CUSTOMER_L", "CUSTOMER_S_v0"):
        assert _raw_vault(tmp_path, model)["disable_hwm"] is True, model


# ---------------------------------------------------------------------------
# Delivery method
# ---------------------------------------------------------------------------


def test_the_delivery_method_needs_the_project_switch(project, tmp_path):
    _update(
        "SourceTable",
        {"physical_table_name": "CUSTOMER"},
        delivery_method="single_batch",
    )

    _generate(project, tmp_path)

    assert "source_is_single_batch" not in _raw_vault(tmp_path, "CUSTOMER_S_v0")


def test_single_batch_sources_use_the_single_batch_logic(project, tmp_path):
    _update(
        "SourceTable",
        {"physical_table_name": "CUSTOMER"},
        delivery_method="single_batch",
    )
    _update(
        "Hub", {"hub_physical_name": "CUSTOMER_H"}, create_effectivity_satellite=True
    )

    _generate(project, tmp_path, runtime_config=_delivery(use_delivery_method=True))

    assert _raw_vault(tmp_path, "CUSTOMER_S_v0")["source_is_single_batch"] is True
    # The effectivity satellite reads the hub's first source: CUSTOMER
    assert _raw_vault(tmp_path, "customer_es")["source_is_single_batch"] is True


def test_the_delivery_method_inherits_from_system_and_project(project, tmp_path):
    from engine.models import Link

    _update("SourceSystem", {"name": "CRM"}, delivery_method="single_batch")
    _update(
        "SourceTable", {"physical_table_name": "ORDERS"}, delivery_method="multi_batch"
    )
    _update(
        "Link",
        {"link_physical_name": "ORDER_CUSTOMER_L"},
        link_type=Link.LinkType.NON_HISTORIZED,
    )
    _with_payload("ORDER_CUSTOMER_L", "SELLER", "O_SELLER")

    _generate(
        project,
        tmp_path,
        runtime_config=_delivery(
            use_delivery_method=True, delivery_method="multi_batch"
        ),
    )

    # CUSTOMER inherits single_batch from its system; ORDERS overrides it
    assert _raw_vault(tmp_path, "CUSTOMER_S_v0")["source_is_single_batch"] is True
    assert "source_is_single_batch" not in _raw_vault(tmp_path, "ORDER_CUSTOMER_L")


# ---------------------------------------------------------------------------
# Links: effectivity satellites and union strategy
# ---------------------------------------------------------------------------


def test_a_link_gets_an_effectivity_satellite(project, tmp_path):
    _update(
        "Link",
        {"link_physical_name": "ORDER_CUSTOMER_L"},
        create_effectivity_satellite=True,
        effectivity_is_active_alias="is_current",
        effectivity_disable_hwm=True,
        effectivity_additional_columns=["O_SELLER"],
    )

    report = _generate(project, tmp_path)

    effectivity = _raw_vault(tmp_path, "order_customer_es")
    assert effectivity == {
        "source_model": "stg__crm__orders",
        "tracked_hashkey": "hk_order_customer_l",
        "is_active_alias": "is_current",
        "additional_columns": ["O_SELLER"],
        "disable_hwm": True,
        "source_is_single_batch": False,
    }
    assert report.plan.by_entity_type["effectivity_satellite"] == 2


def test_a_non_historized_links_union_strategy(project, tmp_path):
    from engine.models import Link

    _update(
        "Link",
        {"link_physical_name": "ORDER_CUSTOMER_L"},
        link_type=Link.LinkType.NON_HISTORIZED,
        union_strategy="distinct",
    )
    _with_payload("ORDER_CUSTOMER_L", "SELLER", "O_SELLER")

    _generate(project, tmp_path)

    assert _raw_vault(tmp_path, "ORDER_CUSTOMER_L")["union_strategy"] == "distinct"


# ---------------------------------------------------------------------------
# Role-playing hub sources
# ---------------------------------------------------------------------------


def test_one_stage_loads_a_hub_in_two_roles(project, tmp_path):
    from engine.models import HubSourceMapping, StagingColumn

    HubSourceMapping.objects.create(
        hub_column=_get("HubColumn", column_name="CUSTOMER_ID"),
        staging_column=StagingColumn.objects.get(
            source_column__source_column_physical_name="O_SELLER"
        ),
        stage_hashkey_name="hk_seller_h",
    )

    _generate(project, tmp_path)

    sources = _raw_vault(tmp_path, "CUSTOMER_H")["source_models"]
    assert sources == [
        {"name": "stg__crm__customer", "bk_columns": ["C_ID"]},
        {"name": "stg__crm__orders", "bk_columns": ["O_CUSTOMER"]},
        {
            "name": "stg__crm__orders",
            "hk_column": "hk_seller_h",
            "bk_columns": ["O_SELLER"],
        },
    ]
    hashed = _stage(tmp_path, "orders")["hashed_columns"]
    assert hashed["hk_customer_h"] == ["O_CUSTOMER"]
    assert hashed["hk_seller_h"] == ["O_SELLER"]


# ---------------------------------------------------------------------------
# PITs, snapshot controls and reference tables
# ---------------------------------------------------------------------------


def _snapshot_control(project, **values):
    from engine.models import SnapshotControlLogic, SnapshotControlTable

    control = SnapshotControlTable.objects.create(
        project=project, name="control_snap", **values
    )
    logic = SnapshotControlLogic.objects.create(
        snapshot_control_table=control,
        snapshot_control_logic_column_name="is_daily",
        snapshot_component="daily",
        snapshot_forever=True,
    )
    return control, logic


def _pit(project, **values):
    from engine.models import PIT

    control, logic = _snapshot_control(project)
    pit = PIT.objects.create(
        project=project,
        pit_physical_name="CUSTOMER_PIT",
        tracked_entity_type="hub",
        tracked_hub=_get("Hub", hub_physical_name="CUSTOMER_H"),
        snapshot_control_table=control,
        snapshot_control_logic=logic,
        **values,
    )
    pit.satellites.add(_get("Satellite", satellite_physical_name="CUSTOMER_S"))
    return pit


def _pit_metadata(tmp_path: Path) -> dict:
    return _metadata(tmp_path, "40_business_vault", "pits", "CUSTOMER_PIT.sql")


def test_pit_options_are_written_only_when_set(project, tmp_path):
    _pit(project)

    _generate(project, tmp_path)

    pit = _pit_metadata(tmp_path)
    assert "snapshot_optimization" not in pit
    assert "custom_rsrc" not in pit


@pytest.mark.parametrize("optimization", [True, False])
def test_pit_options(project, tmp_path, optimization):
    _pit(
        project, use_snapshot_optimization=optimization, custom_record_source="PIT_LOAD"
    )

    _generate(project, tmp_path)

    pit = _pit_metadata(tmp_path)
    assert pit["snapshot_optimization"] is optimization
    assert pit["custom_rsrc"] == "PIT_LOAD"


def test_a_snapshot_control_runs_up_to_today_without_an_end_date(project, tmp_path):
    from engine.models import SnapshotControlTable

    control, _logic = _snapshot_control(project)
    assert control.snapshot_end_date is None
    assert SnapshotControlTable._meta.get_field("snapshot_end_date").default is None

    _generate(project, tmp_path)

    metadata = _metadata(tmp_path, "00_control", "control_snap_v0.sql")
    assert "end_date" not in metadata
    assert "sdts_alias" not in metadata


def test_a_snapshot_controls_end_date_and_sdts_alias(project, tmp_path):
    from datetime import date

    _snapshot_control(
        project, snapshot_end_date=date(2030, 12, 31), sdts_alias="snapshot_ts"
    )

    _generate(project, tmp_path)

    metadata = _metadata(tmp_path, "00_control", "control_snap_v0.sql")
    assert metadata["end_date"] == "2030-12-31"
    assert metadata["sdts_alias"] == "snapshot_ts"


def test_a_snapshot_based_reference_table_reads_its_snapshot_control(project, tmp_path):
    from engine.models import (
        Hub,
        HubColumn,
        HubSourceMapping,
        ReferenceTable,
        Satellite,
        SatelliteColumn,
        StagingColumn,
    )

    control, logic = _snapshot_control(project)
    batch = StagingColumn.objects.get(
        source_column__source_column_physical_name="C_BATCH"
    )
    reference_hub = Hub.objects.create(
        project=project, hub_physical_name="BATCH_RH", hub_type=Hub.HubType.REFERENCE
    )
    HubSourceMapping.objects.create(
        hub_column=HubColumn.objects.create(
            hub=reference_hub,
            column_name="BATCH",
            column_type=HubColumn.ColumnType.REFERENCE_KEY,
        ),
        staging_column=batch,
        is_primary_source=True,
    )
    reference_satellite = Satellite.objects.create(
        project=project,
        satellite_physical_name="BATCH_RS",
        satellite_type=Satellite.SatelliteType.REFERENCE,
        parent_hub=reference_hub,
        source_table=batch.source_table,
    )
    SatelliteColumn.objects.create(
        satellite=reference_satellite,
        staging_column=StagingColumn.objects.get(
            source_column__source_column_physical_name="C_NAME"
        ),
    )
    ReferenceTable.objects.create(
        project=project,
        reference_table_physical_name="BATCH_R",
        reference_hub=reference_hub,
        historization_type=ReferenceTable.HistorizationType.SNAPSHOT_BASED,
        snapshot_control_table=control,
        snapshot_control_logic=logic,
    )

    _generate(project, tmp_path)

    reference_table = _raw_vault(tmp_path, "BATCH_R")
    assert reference_table["historized"] == "snapshot"
    assert reference_table["snapshot_relation"] == "control_snap_v1"
    assert reference_table["snapshot_trigger_column"] == "is_daily"


# ---------------------------------------------------------------------------
# Dependent child keys
# ---------------------------------------------------------------------------


def test_a_link_selects_its_dependent_child_keys(project, tmp_path):
    """datavault4dbt has no dependent child keys: the link lists them in
    foreign_hashkeys after the hub hash keys, and its hash key hashes them."""
    from engine.models import LinkColumn, LinkSourceMapping, StagingColumn

    seller = StagingColumn.objects.get(
        source_column__source_column_physical_name="O_SELLER"
    )
    column = LinkColumn.objects.create(
        link=_get("Link", link_physical_name="ORDER_CUSTOMER_L"),
        column_name="SELLER_ID",
        column_type=LinkColumn.ColumnType.DEPENDENT_CHILD_KEY,
        sort_order=1,
    )
    LinkSourceMapping.objects.create(link_column=column, staging_column=seller)

    _generate(project, tmp_path)

    link = _raw_vault(tmp_path, "ORDER_CUSTOMER_L")
    assert link["foreign_hashkeys"][-1] == "SELLER_ID"
    assert set(link["foreign_hashkeys"][:2]) == {"hk_order_h", "hk_customer_h"}
    stage = _stage(tmp_path, "orders")
    assert stage["hashed_columns"]["hk_order_customer_l"][-1] == "O_SELLER"
    # The stage provides it under the link's name
    assert stage["derived_columns"]["SELLER_ID"]["value"] == "O_SELLER"
    yml = tmp_path / "dbt" / "models" / "30_raw_vault" / "ORDER_CUSTOMER_L.yml"
    assert "- name: SELLER_ID" in yml.read_text(encoding="utf-8")


def test_a_non_historized_link_has_its_dependent_child_keys_in_its_payload(
    project, tmp_path
):
    """datavault4dbt's nh_link requires a payload and selects it as the
    link's own columns: dependent child keys go first in it."""
    from engine.models import Link, LinkColumn, LinkSourceMapping, StagingColumn

    link = _get("Link", link_physical_name="ORDER_CUSTOMER_L")
    Link.objects.filter(pk=link.pk).update(link_type=Link.LinkType.NON_HISTORIZED)
    seller = StagingColumn.objects.get(
        source_column__source_column_physical_name="O_SELLER"
    )
    column = LinkColumn.objects.create(
        link=link,
        column_name="SELLER_ID",
        column_type=LinkColumn.ColumnType.DEPENDENT_CHILD_KEY,
        sort_order=1,
    )
    LinkSourceMapping.objects.create(link_column=column, staging_column=seller)

    report = _generate(project, tmp_path)

    assert report.status == "success", report.issues
    metadata = _raw_vault(tmp_path, "ORDER_CUSTOMER_L")
    assert set(metadata["foreign_hashkeys"]) == {"hk_order_h", "hk_customer_h"}
    assert metadata["payload"] == ["SELLER_ID"]
    stage = _stage(tmp_path, "orders")
    assert stage["hashed_columns"]["hk_order_customer_l"][-1] == "O_SELLER"


def test_a_non_historized_link_without_payload_is_an_error(project, tmp_path):
    from engine.models import Link
    from engine.services.generation import generate

    _update(
        "Link",
        {"link_physical_name": "ORDER_CUSTOMER_L"},
        link_type=Link.LinkType.NON_HISTORIZED,
    )

    report = generate(project=project, output_type="dbt", output_path=tmp_path)

    codes = [issue.code for issue in report.issues if issue.severity == "error"]
    assert "validate.link.nh_without_payload" in codes


def _without_hubs(link_name: str) -> None:
    """Disconnect a link from its hubs (their key mappings go with them)."""
    from engine.models import LinkHubReference

    LinkHubReference.objects.filter(link__link_physical_name=link_name).delete()


def test_a_non_historized_link_without_hubs_is_hashed_from_its_child_keys(
    project, tmp_path
):
    """A non-historized link recording transactions on their own connects no hub:
    its hash key is hashed from its dependent child keys alone."""
    from engine.models import Link, LinkColumn, LinkSourceMapping, StagingColumn

    link = _get("Link", link_physical_name="ORDER_CUSTOMER_L")
    Link.objects.filter(pk=link.pk).update(link_type=Link.LinkType.NON_HISTORIZED)
    _without_hubs("ORDER_CUSTOMER_L")
    seller = StagingColumn.objects.get(
        source_column__source_column_physical_name="O_SELLER"
    )
    column = LinkColumn.objects.create(
        link=link,
        column_name="SELLER_ID",
        column_type=LinkColumn.ColumnType.DEPENDENT_CHILD_KEY,
        sort_order=1,
    )
    LinkSourceMapping.objects.create(link_column=column, staging_column=seller)

    report = _generate(project, tmp_path)

    assert report.status == "success", report.issues
    assert not [i for i in report.issues if i.code.startswith("validate.link")]
    metadata = _raw_vault(tmp_path, "ORDER_CUSTOMER_L")
    # datavault4dbt's nh_link takes no foreign hash keys as none
    assert not metadata["foreign_hashkeys"]
    assert metadata["payload"] == ["SELLER_ID"]
    stage = _stage(tmp_path, "orders")
    assert stage["hashed_columns"]["hk_order_customer_l"] == ["O_SELLER"]


def test_a_link_without_hubs_or_child_keys_has_nothing_to_hash(project, tmp_path):
    from engine.models import Link
    from engine.services.generation import generate

    _update(
        "Link",
        {"link_physical_name": "ORDER_CUSTOMER_L"},
        link_type=Link.LinkType.NON_HISTORIZED,
    )
    _without_hubs("ORDER_CUSTOMER_L")
    _with_payload("ORDER_CUSTOMER_L", "SELLER_ID", "O_SELLER")

    report = generate(project=project, output_type="dbt", output_path=tmp_path)

    codes = [issue.code for issue in report.issues if issue.severity == "error"]
    assert "validate.link.no_hashkey_input" in codes


def test_a_standard_link_with_one_hub_is_generated_with_a_warning(project, tmp_path):
    from engine.models import LinkHubReference

    LinkHubReference.objects.filter(
        link__link_physical_name="ORDER_CUSTOMER_L",
        hub__hub_physical_name__iexact="CUSTOMER_H",
    ).delete()

    report = _generate(project, tmp_path)

    assert report.status in ("success", "partial_success"), report.issues
    [warning] = [i for i in report.issues if i.code == "validate.link.too_few_hubs"]
    assert warning.severity == "warning"
    assert warning.message == (
        "A standard Link usually connects two or more Hubs; this one connects one"
    )
    assert _raw_vault(tmp_path, "ORDER_CUSTOMER_L")["foreign_hashkeys"] == [
        "hk_order_h"
    ]
