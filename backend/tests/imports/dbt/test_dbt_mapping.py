"""Mapping a datavault4dbt project to TurboVault entities (spec §7).

Hand-written manifests of a small shop project: stages become source tables
or pre-stages; Hubs, Links and Satellites map their columns to the stage's
source, derived and prejoined columns; effectivity and record-tracking
Satellites become their Hub's. Names are kept, and stored only where they
differ from the project's naming patterns. What can't be mapped is reported
on its model and left out.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.django_db

PROJECT = "shop"
V12 = "https://schemas.getdbt.com/dbt/manifest/v12.json"


# ---------------------------------------------------------------------------
# Building manifests
# ---------------------------------------------------------------------------


def dv(macro: str, yaml: str) -> str:
    """A model calling datavault4dbt.<macro> with a yaml_metadata block."""
    return (
        "{{ config(materialized='incremental') }}\n"
        "{%- set yaml_metadata -%}\n"
        + textwrap.dedent(yaml).strip()
        + "\n{%- endset -%}\n"
        + f"{{{{ datavault4dbt.{macro}(yaml_metadata=yaml_metadata) }}}}\n"
    )


def model(
    name: str,
    raw_code: str,
    *,
    folder: str = "models/raw_vault",
    columns: dict[str, dict[str, Any]] | None = None,
    description: str = "",
) -> tuple[str, dict[str, Any]]:
    unique_id = f"model.{PROJECT}.{name}"
    return unique_id, {
        "resource_type": "model",
        "package_name": PROJECT,
        "name": name,
        "language": "sql",
        "raw_code": raw_code,
        "original_file_path": f"{folder}/{name}.sql",
        "path": f"{name}.sql",
        "database": "analytics",
        "schema": "dv",
        "description": description,
        "columns": {
            key: {"name": key, **value} for key, value in (columns or {}).items()
        },
        "config": {},
        "unrendered_config": {},
        "fqn": [PROJECT, *folder.split("/")[1:], name],
    }


def source(
    source_name: str,
    table: str,
    columns: list[str] | dict[str, str],
    *,
    schema: str | None = None,
    database: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if isinstance(columns, list):
        columns = dict.fromkeys(columns, "varchar")
    unique_id = f"source.{PROJECT}.{source_name}.{table}"
    return unique_id, {
        "resource_type": "source",
        "package_name": PROJECT,
        "source_name": source_name,
        "name": table,
        "identifier": table,
        "schema": schema or f"{source_name}_raw",
        "database": database or "analytics",
        "unrendered_database": database,
        "description": "",
        "columns": {
            name: {"name": name, "data_type": datatype}
            for name, datatype in columns.items()
        },
    }


def write_manifest(
    path: Path,
    nodes: list[tuple[str, dict[str, Any]]],
    sources: list[tuple[str, dict[str, Any]]],
    parent_map: dict[str, list[str]] | None = None,
) -> Path:
    manifest = {
        "metadata": {
            "dbt_schema_version": V12,
            "project_name": PROJECT,
            "adapter_type": "postgres",
            "dbt_version": "1.10.0",
        },
        "nodes": dict(nodes),
        "sources": dict(sources),
        "macros": {},
        "parent_map": parent_map or {},
        "child_map": {},
    }
    target = path / "manifest.json"
    target.write_text(json.dumps(manifest), encoding="utf-8")
    return target


CUSTOMER = source(
    "crm", "customer", ["ID", "REFERRER_ID", "NAME", "EMAIL", "COUNTRY", "LOAD_TS"]
)
ORDERS = source("crm", "orders", ["ORDER_ID", "CUSTOMER_ID", "LINE_NO", "AMOUNT"])

STG_CUSTOMER = model(
    "stg__crm__customer",
    dv(
        "stage",
        """
        source_model:
            crm: customer
        ldts: LOAD_TS
        rsrc: '!crm'
        include_source_columns: false
        derived_columns:
            NAME_UPPER:
                value: UPPER(NAME)
                datatype: VARCHAR
        missing_columns:
            LEGACY_CODE: VARCHAR
        hashed_columns:
            hk_customer_h:
                - ID
            hk_referrer_h:
                - REFERRER_ID
            hd_customer_s:
                is_hashdiff: true
                columns:
                    - NAME_UPPER
                    - EMAIL
        """,
    ),
    folder="models/staging",
)
STG_ORDERS = model(
    "stg__crm__orders",
    dv(
        "stage",
        """
        source_model:
            crm: orders
        ldts: LOAD_TS
        rsrc: '!crm'
        hashed_columns:
            hk_order_h:
                - ORDER_ID
            hk_customer_h:
                - CUSTOMER_ID
            hk_order_customer_l:
                - ORDER_ID
                - CUSTOMER_ID
                - LINE_NO
        """,
    ),
    folder="models/staging",
)
CUSTOMER_H = model(
    "customer_h",
    dv(
        "hub",
        """
        hashkey: hk_customer_h
        business_keys:
            - customer_id
        source_models:
            - name: stg__crm__customer
              bk_columns: [ID]
              rsrc_static: '!crm'
            - name: stg__crm__customer
              hk_column: hk_referrer_h
              bk_columns: [REFERRER_ID]
            - name: stg__crm__orders
              bk_columns: [CUSTOMER_ID]
        additional_columns:
            - COUNTRY
        disable_hwm: true
        """,
    ),
    description="Customers",
)
ORDER_H = model(
    "order_h",
    dv(
        "hub",
        """
        hashkey: hk_order_h
        business_keys: [ORDER_ID]
        source_models: stg__crm__orders
        """,
    ),
)
ORDER_CUSTOMER_L = model(
    "order_customer_l",
    dv(
        "link",
        """
        link_hashkey: hk_order_customer_l
        foreign_hashkeys:
            - hk_order_h
            - hk_customer_h
        source_models: stg__crm__orders
        """,
    ),
)
CUSTOMER_S_V0 = model(
    "customer_s_v0",
    dv(
        "sat_v0",
        """
        source_model: stg__crm__customer
        parent_hashkey: hk_customer_h
        src_hashdiff:
            source_column: hd_customer_s
            alias: hashdiff
        src_payload:
            - NAME_UPPER
            - EMAIL
            - LEGACY_CODE
        """,
    ),
    columns={"EMAIL": {"description": "Mail address"}},
)
CUSTOMER_S_V1 = model(
    "customer_s_v1",
    dv(
        "sat_v1",
        """
        sat_v0: customer_s_v0
        hashkey: hk_customer_h
        hashdiff: hashdiff
        ledts_alias: valid_to
        add_is_current_flag: false
        """,
    ),
)


def shop(tmp_path: Path, *extra: tuple[str, dict[str, Any]], sources=()) -> Path:
    return write_manifest(
        tmp_path,
        [
            STG_CUSTOMER,
            STG_ORDERS,
            CUSTOMER_H,
            ORDER_H,
            ORDER_CUSTOMER_L,
            CUSTOMER_S_V0,
            CUSTOMER_S_V1,
            *extra,
        ],
        [CUSTOMER, ORDERS, *sources],
    )


def map_manifest(path: Path, runtime_config=None):
    from engine.services.imports.dbt.parser import parse_dbt
    from engine.services.imports.types import DbtSource

    return parse_dbt(DbtSource(path=path), runtime_config=runtime_config)


def codes(issues) -> list[str]:
    return [issue.code for issue in issues]


def names(outputs) -> dict[str, str]:
    """The model names stored in an entity's outputs, by kind."""
    return {
        kind: output.model_name
        for kind, output in (outputs or {}).items()
        if output.model_name
    }


@pytest.fixture
def project(django_setup, db):
    from engine.models import Project

    return Project.objects.create(name="shop")


def import_shop(project, path: Path, **options):
    from engine.services.imports import DbtSource, ImportOptions, import_metadata

    return import_metadata(
        project=project,
        source=DbtSource(path=path),
        options=ImportOptions(**{"skip_snapshots": True, **options}),
    )


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def test_a_stage_becomes_its_source_table(tmp_path):
    from engine.services.imports.domain import CLEAR

    domain, _ = map_manifest(shop(tmp_path))

    crm = domain.source_systems["crm"]
    assert (crm.schema_name, crm.database_name) == ("crm_raw", None)
    # Both tables load with LOAD_TS: set on the system. Their record source
    # '!crm' is what a crm table gets anyway: not stored.
    assert (crm.record_source_value, crm.load_date_value) == (CLEAR, "LOAD_TS")
    customer = crm.tables["crm|customer"]
    assert customer.record_source_value is CLEAR
    assert customer.include_source_columns is False
    assert customer.enable_ghost_records is CLEAR
    assert customer.derived_columns["name_upper"].expression == "UPPER(NAME)"
    assert customer.columns["legacy_code"].is_missing is True
    assert customer.columns["email"].is_missing is False
    # stg__crm__customer is what the default stage pattern gives
    assert names(customer.outputs) == {}


def test_a_stage_name_off_the_pattern_is_stored(tmp_path):
    from engine.services.runtime_config import EngineRuntimeConfig

    path = shop(tmp_path)
    domain, _ = map_manifest(
        path, EngineRuntimeConfig(stage_naming="stage_[[ source_table ]]")
    )

    outputs = domain.source_systems["crm"].tables["crm|customer"].outputs
    assert outputs["stage"].model_name == "stg__crm__customer"


def test_a_stage_reading_a_model_gets_a_prestage(tmp_path):
    prep = model("pstg__crm__address", "select * from {{ source('crm', 'address') }}")
    address = source("crm", "address", ["CUSTOMER_ID", "STREET"])
    stage = model(
        "stg__crm__address",
        dv(
            "stage",
            """
            source_model: pstg__crm__address
            ldts: LOAD_TS
            rsrc: '!crm'
            """,
        ),
    )
    path = write_manifest(
        tmp_path,
        [stage, prep],
        [address],
        parent_map={prep[0]: [address[0]]},
    )

    domain, issues = map_manifest(path)

    table = domain.source_systems["crm"].tables["crm|address"]
    assert table.table_type == "prestage"
    assert names(table.outputs) == {}
    assert "dbt.prestage_maintained_in_dbt" in codes(issues)


# ---------------------------------------------------------------------------
# Hubs and Links
# ---------------------------------------------------------------------------


def test_a_hub_maps_its_business_keys_to_each_stage(tmp_path):
    from engine.services.imports.domain import CLEAR

    domain, _ = map_manifest(shop(tmp_path))

    hub = domain.hubs["customer_h"]
    assert (hub.hashkey_name, hub.disable_hwm, hub.description) == (
        "hk_customer_h",
        True,
        "Customers",
    )
    key, country = hub.columns
    assert (key.name, country.name, country.column_type) == (
        "customer_id",
        "COUNTRY",
        "additional_column",
    )
    mappings = [
        (m.source_table_identifier, m.source_column_name, m.is_primary_source)
        for m in key.source_mappings
    ]
    assert mappings == [
        ("crm|customer", "ID", True),
        ("crm|customer", "REFERRER_ID", False),
        ("crm|orders", "CUSTOMER_ID", False),
    ]
    roles = [m.stage_hashkey_name for m in key.source_mappings]
    assert roles == [CLEAR, "hk_referrer_h", CLEAR]
    table = domain.source_systems["crm"].tables["crm|customer"]
    assert table.static_part_of_record_source == "!crm"


def test_a_link_finds_its_hubs_and_dependent_child_keys(tmp_path):
    domain, _ = map_manifest(shop(tmp_path))

    link = domain.links["order_customer_l"]
    assert [
        (r.hub_physical_name, r.hub_hashkey_alias_in_link) for r in link.hub_references
    ] == [
        ("order_h", ""),
        ("customer_h", ""),
    ]
    assert [
        (m.hub_column_name, m.source_column_name) for m in link.hub_source_mappings
    ] == [
        ("ORDER_ID", "ORDER_ID"),
        ("customer_id", "CUSTOMER_ID"),
    ]
    # The link hash key hashes LINE_NO on top of the hubs' keys
    assert [(c.name, c.column_type) for c in link.columns] == [
        ("LINE_NO", "dependent_child_key")
    ]


def test_a_self_link_references_its_hub_twice(tmp_path):
    referral = model(
        "customer_referral_l",
        dv(
            "link",
            """
            link_hashkey: hk_customer_referral_l
            foreign_hashkeys: [hk_customer_h, hk_referrer_h]
            source_models: stg__crm__customer
            """,
        ),
    )
    stage = model(
        "stg__crm__customer",
        STG_CUSTOMER[1]["raw_code"].replace(
            "hashed_columns:",
            "hashed_columns:\n    hk_customer_referral_l:\n        - ID\n        - REFERRER_ID",
        ),
        folder="models/staging",
    )
    path = write_manifest(
        tmp_path, [stage, STG_ORDERS, CUSTOMER_H, referral], [CUSTOMER, ORDERS]
    )

    domain, _ = map_manifest(path)

    link = domain.links["customer_referral_l"]
    assert [
        (r.hub_physical_name, r.hub_hashkey_alias_in_link) for r in link.hub_references
    ] == [
        ("customer_h", ""),
        ("customer_h", "hk_referrer_h"),
    ]
    assert [m.source_column_name for m in link.hub_source_mappings] == [
        "ID",
        "REFERRER_ID",
    ]
    assert link.columns == []


def test_a_foreign_hash_key_without_its_hub_skips_the_link(tmp_path):
    orphan = model(
        "order_product_l",
        dv(
            "link",
            """
            link_hashkey: hk_order_product_l
            foreign_hashkeys: [hk_order_h, hk_product_h]
            source_models: stg__crm__orders
            """,
        ),
    )
    domain, issues = map_manifest(shop(tmp_path, orphan))

    assert "order_product_l" not in domain.links
    assert ("link", "order_product_l") in domain.skipped
    (issue,) = [i for i in issues if i.code == "dbt.link_hub_ambiguous"]
    assert issue.location.node_id == "model.shop.order_product_l"
    assert issue.location.parameter == "foreign_hashkeys"


def test_a_non_historized_link_keeps_its_payload_and_union_strategy(tmp_path):
    lines = model(
        "order_line_nl",
        dv(
            "nh_link",
            """
            link_hashkey: hk_order_customer_l
            foreign_hashkeys: [hk_order_h, hk_customer_h]
            payload: [AMOUNT]
            union_strategy: distinct
            source_models: stg__crm__orders
            """,
        ),
    )
    domain, _ = map_manifest(shop(tmp_path, lines))

    link = domain.links["order_line_nl"]
    assert (link.link_type, link.union_strategy) == ("non_historized", "distinct")
    assert [(c.name, c.column_type) for c in link.columns] == [
        ("LINE_NO", "dependent_child_key"),
        ("AMOUNT", "payload"),
    ]


# ---------------------------------------------------------------------------
# Satellites
# ---------------------------------------------------------------------------


def test_a_satellite_maps_its_payload_and_v1_view(tmp_path):
    from engine.services.imports.domain import CLEAR

    domain, _ = map_manifest(shop(tmp_path))

    sat = domain.satellites["customer_s"]
    assert (sat.parent_entity_name, sat.parent_entity_type) == ("customer_h", "hub")
    assert (sat.hashdiff_name, sat.hashdiff_alias) == ("hd_customer_s", "hashdiff")
    assert [
        (c.source_column_name, c.include_in_delta_detection, c.description)
        for c in sat.columns
    ] == [
        ("NAME_UPPER", True, None),
        ("EMAIL", True, "Mail address"),
        ("LEGACY_CODE", False, None),
    ]
    assert sat.v1_ledts_alias == "valid_to"
    assert sat.v1_add_is_current_flag is False
    # Named like the default v0/v1 patterns, with a v1 view as by default
    assert sat.create_v1_view is CLEAR
    assert names(sat.outputs) == {}


def test_satellite_models_off_the_patterns_keep_their_names(tmp_path):
    v0 = model("sat_customer", CUSTOMER_S_V0[1]["raw_code"])
    v1 = model(
        "sat_customer_current",
        CUSTOMER_S_V1[1]["raw_code"].replace("customer_s_v0", "sat_customer"),
    )
    path = write_manifest(
        tmp_path,
        [STG_CUSTOMER, STG_ORDERS, CUSTOMER_H, v0, v1],
        [CUSTOMER, ORDERS],
    )

    domain, _ = map_manifest(path)

    sat = domain.satellites["sat_customer"]
    assert sat.outputs["satellite_v0"].model_name == "sat_customer"
    assert sat.outputs["satellite_v1"].model_name == "sat_customer_current"


def test_a_satellite_without_a_v1_view_says_so(tmp_path):
    path = write_manifest(
        tmp_path,
        [STG_CUSTOMER, STG_ORDERS, CUSTOMER_H, CUSTOMER_S_V0],
        [CUSTOMER, ORDERS],
    )

    domain, _ = map_manifest(path)

    assert domain.satellites["customer_s"].create_v1_view is False


def test_a_multi_active_satellite_marks_its_keys(tmp_path):
    ma = model(
        "customer_phone_ms_v0",
        dv(
            "ma_sat_v0",
            """
            source_model: stg__crm__customer
            parent_hashkey: hk_customer_h
            src_hashdiff: hd_customer_s
            src_ma_key: [EMAIL]
            src_payload: [NAME]
            """,
        ),
    )
    domain, _ = map_manifest(shop(tmp_path, ma))

    sat = domain.satellites["customer_phone_ms"]
    assert sat.satellite_type == "multi_active"
    assert [(c.source_column_name, c.is_multi_active_key) for c in sat.columns] == [
        ("EMAIL", True),
        ("NAME", False),
    ]


def test_effectivity_and_record_tracking_satellites_belong_to_their_hub(tmp_path):
    eff = model(
        "customer_es",
        dv(
            "eff_sat_v0",
            """
            source_model: stg__crm__customer
            tracked_hashkey: hk_customer_h
            is_active_alias: is_live
            source_is_single_batch: true
            """,
        ),
    )
    rts = model(
        "customer_tracking",
        dv(
            "rec_track_sat",
            """
            tracked_hashkey: hk_customer_h
            source_models:
                - name: stg__crm__customer
                - name: stg__crm__orders
            """,
        ),
    )
    domain, issues = map_manifest(shop(tmp_path, eff, rts))

    hub = domain.hubs["customer_h"]
    assert hub.create_effectivity_satellite is True
    assert hub.effectivity_is_active_alias == "is_live"
    assert hub.create_record_tracking_satellite is True
    # customer_es follows the pattern; customer_tracking doesn't
    assert names(hub.outputs) == {"record_tracking_satellite": "customer_tracking"}
    table = domain.source_systems["crm"].tables["crm|customer"]
    assert table.delivery_method == "single_batch"
    # The project's delivery method needs switching on
    suggestion = domain.project_settings.suggestions["use_delivery_method"]
    assert (suggestion.value, suggestion.matching, suggestion.total) == (True, 1, 2)
    assert "dbt.setting_suggested" in codes(issues)


# ---------------------------------------------------------------------------
# Prejoins
# ---------------------------------------------------------------------------


def test_a_prejoined_column_loads_a_satellite(tmp_path, project):
    from engine.models import PrejoinExtractionColumn, SatelliteColumn

    country = source("crm", "country", ["CODE", "COUNTRY_NAME"])
    stage = model(
        "stg__crm__customer",
        STG_CUSTOMER[1]["raw_code"].replace(
            "hashed_columns:",
            textwrap.dedent(
                """\
                prejoined_columns:
                    - extract_columns: [COUNTRY_NAME]
                      aliases: [CUSTOMER_COUNTRY]
                      src_name: crm
                      src_table: country
                      this_column_name: [COUNTRY]
                      ref_column_name: [CODE]
                hashed_columns:"""
            ),
        ),
        folder="models/staging",
    )
    sat = model(
        "customer_country_s_v0",
        dv(
            "sat_v0",
            """
            source_model: stg__crm__customer
            parent_hashkey: hk_customer_h
            src_hashdiff: hd_customer_s
            src_payload: [CUSTOMER_COUNTRY]
            """,
        ),
    )
    path = write_manifest(
        tmp_path,
        [stage, STG_ORDERS, CUSTOMER_H, ORDER_H, sat],
        [CUSTOMER, ORDERS, country],
    )

    report = import_shop(project, path)

    assert report.status in ("success", "partial_success"), report.issues
    (column,) = SatelliteColumn.objects.filter(
        satellite__satellite_physical_name="customer_country_s"
    )
    extraction = column.staging_column.prejoin_column
    assert isinstance(extraction, PrejoinExtractionColumn)
    assert extraction.prejoin_target_column_alias == "CUSTOMER_COUNTRY"


# ---------------------------------------------------------------------------
# Through the pipeline
# ---------------------------------------------------------------------------


def test_a_dbt_project_imports_and_reimports_unchanged(tmp_path, project):
    from engine.models import Hub, Link, Satellite, SourceTable

    path = shop(tmp_path)

    first = import_shop(project, path)

    assert first.status == "success", [
        i.message for i in first.issues if i.severity == "error"
    ]
    assert set(
        Hub.objects.filter(project=project).values_list("hub_physical_name", flat=True)
    ) == {
        "customer_h",
        "order_h",
    }
    assert Link.objects.filter(project=project).count() == 1
    sat = Satellite.objects.get(project=project)
    assert (sat.hashdiff_name, sat.hashdiff_alias) == (None, "hashdiff")
    table = SourceTable.objects.get(project=project, physical_table_name="customer")
    assert table.include_source_columns is False

    again = import_shop(project, path)

    changed = [
        (e.ref.type, e.ref.name, e.changes)
        for e in again.plan.entities
        if e.action not in ("unchanged", "skip")
    ]
    assert changed == []


def test_mapping_errors_stop_a_fail_fast_import(tmp_path, project):
    from engine.models import Hub

    orphan = model(
        "orphan_h",
        dv(
            "hub",
            """
            hashkey: hk_orphan_h
            business_keys: [ID]
            source_models: stg_unknown
            """,
        ),
    )

    report = import_shop(project, shop(tmp_path, orphan), error_strategy="fail_fast")

    assert report.status != "success"
    assert "dbt.reference_unresolved" in codes(report.issues)
    assert not Hub.objects.filter(project=project).exists()


def test_models_without_a_data_vault_call_are_reported(tmp_path):
    mart = model("customer_mart", "select * from {{ ref('customer_s_v1') }}")
    domain, issues = map_manifest(shop(tmp_path, mart))

    (issue,) = [i for i in issues if i.code == "dbt.model_not_mapped"]
    assert issue.severity == "info"
    assert issue.location.node_id == "model.shop.customer_mart"


def test_invert_pattern():
    from engine.services.imports.dbt.mapping import invert_pattern

    assert invert_pattern("[[ satellite_name ]]_v0", "customer_s_v0") == {
        "satellite_name": "customer_s"
    }
    assert invert_pattern(
        "stg__[[ source_system ]]__[[ source_table ]]", "stg__crm__order_lines"
    ) == {"source_system": "crm", "source_table": "order_lines"}
    assert invert_pattern("[[ satellite_name ]]_v0", "customer_s") is None


def test_a_key_column_among_the_foreign_hash_keys_is_a_child_key(tmp_path):
    """datavault4dbt lists a dependent child key (a transactional link's
    transaction id) among the foreign hash keys, as TurboVault generates it."""
    lines = model(
        "order_line_tl",
        dv(
            "nh_link",
            """
            link_hashkey: hk_order_customer_l
            foreign_hashkeys: [hk_order_h, hk_customer_h, LINE_NO]
            payload: [AMOUNT]
            source_models: stg__crm__orders
            """,
        ),
    )
    domain, issues = map_manifest(shop(tmp_path, lines))

    link = domain.links["order_line_tl"]
    assert [r.hub_physical_name for r in link.hub_references] == [
        "order_h",
        "customer_h",
    ]
    key = next(c for c in link.columns if c.column_type == "dependent_child_key")
    assert key.name == "LINE_NO"
    assert [m.source_column_name for m in key.source_mappings] == ["LINE_NO"]
    assert not [
        i
        for i in issues
        if i.location and i.location.node_id == "model.shop.order_line_tl"
    ]


def test_a_child_key_only_the_link_hash_key_hashes_is_noted(tmp_path):
    """order_customer_l hashes LINE_NO without listing it: the generated link
    will select it."""
    domain, issues = map_manifest(shop(tmp_path))

    assert [c.name for c in domain.links["order_customer_l"].columns] == ["LINE_NO"]
    (note,) = [
        i
        for i in issues
        if i.location and i.location.node_id == "model.shop.order_customer_l"
    ]
    assert note.severity == "info"
    assert "'LINE_NO'" in note.message


def test_several_stages_may_read_one_prestage(tmp_path):
    prep = model("pstg__crm__organizations", "select 1")
    stages = [
        model(
            name,
            dv(
                "stage",
                """
                source_model: pstg__crm__organizations
                ldts: LOAD_TS
                rsrc: '!crm'
                """,
            ),
        )
        for name in ("stg__crm__organizations", "stg__crm__billing_address")
    ]
    path = write_manifest(
        tmp_path, [*stages, prep], [CUSTOMER], parent_map={prep[0]: [CUSTOMER[0]]}
    )

    domain, issues = map_manifest(path)

    tables = {
        table.physical_name: table
        for system in domain.source_systems.values()
        for table in system.tables.values()
        if table.table_type == "prestage"
    }
    assert set(tables) == {"organizations", "billing_address"}
    # Both read the same model of the dbt project
    assert tables["billing_address"].outputs["prestage"].model_name == (
        "pstg__crm__organizations"
    )
    assert "prestage" not in tables["organizations"].outputs
    assert not [i for i in issues if i.severity == "error"]


def test_what_depends_on_a_left_out_stage_is_left_out_quietly(tmp_path):
    broken = model(
        "stg__crm__broken",
        dv("stage", "source_model:\n    crm: nowhere\nldts: LOAD_TS\nrsrc: '!crm'"),
    )
    hub = model(
        "broken_h",
        dv(
            "hub",
            """
            hashkey: hk_broken_h
            business_keys: [ID]
            source_models: stg__crm__broken
            """,
        ),
    )
    sat = model(
        "broken_s_v0",
        dv(
            "sat_v0",
            """
            source_model: stg__crm__orders
            parent_hashkey: hk_broken_h
            src_hashdiff: hd_broken_s
            src_payload: [AMOUNT]
            """,
        ),
    )

    domain, issues = map_manifest(shop(tmp_path, broken, hub, sat))

    errors = [(i.code, i.location.node_id) for i in issues if i.severity == "error"]
    assert errors == [("dbt.reference_unresolved", "model.shop.stg__crm__broken")]
    cascades = {
        i.location.node_id for i in issues if i.code == "entity.depends_on_skipped"
    }
    assert cascades == {"model.shop.broken_h", "model.shop.broken_s_v0"}
    assert domain.skipped[("hub", "broken_h")].reason == "depends_on_skipped"
    assert domain.skipped[("satellite", "broken_s")].reason == "depends_on_skipped"


# ---------------------------------------------------------------------------
# Snapshot controls, PITs, reference tables
# ---------------------------------------------------------------------------

CONTROL_V0 = model(
    "control_snap_v0",
    dv(
        "control_snap_v0",
        """
        start_date: '2021-01-01'
        daily_snapshot_time: 07:30:00
        end_date: 2030-12-31
        """,
    ),
    folder="models/control",
)
CONTROL_V1 = model(
    "control_snap_v1",
    dv(
        "control_snap_v1",
        """
        control_snap_v0: control_snap_v0
        log_logic:
            daily:
                duration: 3
                unit: MONTH
            yearly:
                forever: true
        """,
    ),
    folder="models/control",
)
CUSTOMER_PIT = model(
    "customer_pit",
    dv(
        "pit",
        """
        tracked_entity: customer_h
        hashkey: hk_customer_h
        sat_names:
            - customer_s_v1
        snapshot_relation: control_snap_v1
        snapshot_trigger_column: is_active
        dimension_key: hk_customer_d
        custom_rsrc: 'TurboVault'
        snapshot_optimization: true
        """,
    ),
    folder="models/business_vault",
)


def test_snapshot_controls_keep_their_dates_and_logic(tmp_path):
    from engine.services.imports.domain import CLEAR

    domain, _ = map_manifest(shop(tmp_path, CONTROL_V0, CONTROL_V1))

    control = domain.snapshot_controls["control_snap"]
    # YAML reads an unquoted 07:30:00 as seconds: the import reads it back
    assert (control.start_date, control.end_date, control.daily_time) == (
        "2021-01-01",
        "2030-12-31",
        "07:30:00",
    )
    assert control.sdts_alias is CLEAR
    assert [
        (r.column_name, r.component, r.duration, r.unit, r.forever)
        for r in control.logic_rules
    ] == [
        ("is_active", "daily", 3, "MONTH", False),
        ("is_active", "beginning_of_year", None, None, True),
    ]
    assert names(control.outputs) == {}


def test_a_list_of_logic_columns_names_each(tmp_path):
    named_v0 = model("snapshots", CONTROL_V0[1]["raw_code"], folder="models/control")
    logic = model(
        "snapshot_logic",
        dv(
            "control_snap_v1",
            """
            control_snap_v0: snapshots
            log_logic:
                - is_recent:
                    daily:
                        duration: 1
                        unit: MONTH
                - is_monthly:
                    monthly:
                        forever: true
            """,
        ),
        folder="models/control",
    )
    domain, _ = map_manifest(shop(tmp_path, named_v0, logic))

    control = domain.snapshot_controls["snapshots"]
    assert [(r.column_name, r.component) for r in control.logic_rules] == [
        ("is_recent", "daily"),
        ("is_monthly", "beginning_of_month"),
    ]
    assert control.outputs["snapshot_control_v0"].model_name == "snapshots"
    assert control.outputs["snapshot_control_v1"].model_name == "snapshot_logic"


def test_a_pit_reads_its_hub_satellites_and_snapshot_control(tmp_path):
    domain, issues = map_manifest(shop(tmp_path, CONTROL_V0, CONTROL_V1, CUSTOMER_PIT))

    pit = domain.pits["customer_pit"]
    assert (pit.tracked_entity_name, pit.tracked_entity_type) == ("customer_h", "hub")
    assert pit.satellite_names == ["customer_s"]
    assert (pit.snapshot_control_name, pit.snapshot_logic_column) == (
        "control_snap",
        "is_active",
    )
    assert pit.dimension_key_column_name == "hk_customer_d"
    assert pit.custom_record_source == "TurboVault"
    assert pit.use_snapshot_optimization is True
    assert not [i for i in issues if i.severity == "error"]


def test_a_pit_trigger_column_the_control_lacks_is_noted(tmp_path):
    pit = model(
        "customer_pit",
        CUSTOMER_PIT[1]["raw_code"].replace(
            "snapshot_trigger_column: is_active", "snapshot_trigger_column: is_daily"
        ),
        folder="models/business_vault",
    )
    _, issues = map_manifest(shop(tmp_path, CONTROL_V0, CONTROL_V1, pit))

    (note,) = [
        i
        for i in issues
        if i.location and i.location.parameter == "snapshot_trigger_column"
    ]
    assert note.severity == "warning"
    assert "is_daily" in note.message


def test_a_pit_without_its_satellite_is_left_out(tmp_path):
    pit = model(
        "customer_pit",
        CUSTOMER_PIT[1]["raw_code"].replace("customer_s_v1", "missing_s_v1"),
        folder="models/business_vault",
    )
    domain, issues = map_manifest(shop(tmp_path, CONTROL_V0, CONTROL_V1, pit))

    assert "customer_pit" not in domain.pits
    assert domain.skipped[("pit", "customer_pit")].reason == "missing_reference"
    assert "dbt.reference_unresolved" in codes(issues)


def test_a_reference_table_reads_its_hub_and_satellites(tmp_path):
    country = source("crm", "country", ["CODE", "NAME", "REGION"])
    stage = model(
        "stg__crm__country",
        dv(
            "stage",
            """
            source_model:
                crm: country
            ldts: LOAD_TS
            rsrc: '!crm'
            hashed_columns:
                hd_country_rs:
                    is_hashdiff: true
                    columns: [NAME, REGION]
            """,
        ),
    )
    ref_hub = model(
        "country_rh",
        dv(
            "ref_hub",
            """
            ref_keys: [CODE]
            source_models: stg__crm__country
            """,
        ),
    )
    ref_sat = model(
        "country_rs_v0",
        dv(
            "ref_sat_v0",
            """
            source_model: stg__crm__country
            parent_ref_keys: [CODE]
            src_hashdiff: hd_country_rs
            src_payload: [NAME, REGION]
            """,
        ),
    )
    ref_sat_v1 = model(
        "country_rs_v1",
        dv(
            "ref_sat_v1",
            """
            ref_sat_v0: country_rs_v0
            ref_keys: [CODE]
            hashdiff: hd_country_rs
            """,
        ),
    )
    table = model(
        "country_r",
        dv(
            "ref_table",
            """
            ref_hub: country_rh
            ref_satellites:
                country_rs_v1:
                    exclude: [REGION]
            historized: snapshot
            snapshot_relation: control_snap_v1
            snapshot_trigger_column: is_active
            """,
        ),
    )
    path = write_manifest(
        tmp_path,
        [stage, ref_hub, ref_sat, ref_sat_v1, table, CONTROL_V0, CONTROL_V1],
        [country],
    )

    domain, issues = map_manifest(path)

    ref = domain.reference_tables["country_r"]
    assert (ref.reference_hub_name, ref.historization_type) == (
        "country_rh",
        "snapshot_based",
    )
    assert (ref.snapshot_control_name, ref.snapshot_logic_column) == (
        "control_snap",
        "is_active",
    )
    (assignment,) = ref.satellite_assignments
    assert (assignment.satellite_name, assignment.exclude_columns) == (
        "country_rs",
        ["REGION"],
    )
    assert not [i for i in issues if i.severity == "error"]


def test_snapshot_controls_and_pits_import_together(tmp_path, project):
    from engine.models import PIT, SnapshotControlTable

    path = shop(tmp_path, CONTROL_V0, CONTROL_V1, CUSTOMER_PIT)

    report = import_shop(project, path, skip_snapshots=False)

    assert report.status == "success", [
        i.message for i in report.issues if i.severity == "error"
    ]
    (control,) = SnapshotControlTable.objects.filter(project=project)
    assert control.name == "control_snap"
    pit = PIT.objects.get(project=project)
    assert pit.snapshot_control_logic.snapshot_control_logic_column_name == "is_active"
    assert pit.snapshot_control_table == control


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def test_groups_come_from_turbovaults_folders_and_tags(tmp_path):
    hub = model(
        "customer_h",
        CUSTOMER_H[1]["raw_code"],
        folder="models/30_raw_vault/customers",
    )
    hub[1]["config"] = {"tags": ["hub", "raw_vault", "Customers"]}
    sat = model(
        "customer_s_v0",
        CUSTOMER_S_V0[1]["raw_code"],
        folder="models/30_raw_vault/customers",
    )
    pit = model(
        "customer_pit",
        CUSTOMER_PIT[1]["raw_code"],
        folder="models/40_business_vault/pits/customers",
    )
    path = write_manifest(
        tmp_path,
        [
            STG_CUSTOMER,
            STG_ORDERS,
            hub,
            sat,
            CUSTOMER_S_V1,
            CONTROL_V0,
            CONTROL_V1,
            pit,
        ],
        [CUSTOMER, ORDERS],
    )

    domain, _ = map_manifest(path)

    # The hub's tag spells the group; its folder places the others in it
    assert domain.hubs["customer_h"].group_name == "Customers"
    assert domain.satellites["customer_s"].group_name == "Customers"
    assert domain.pits["customer_pit"].group_name == "Customers"
    assert domain.groups == {"Customers"}


# ---------------------------------------------------------------------------
# Model settings, dbt_project.yml and naming (D20, D22, D25)
# ---------------------------------------------------------------------------


def _with_settings(entry, *, tags=None, unrendered=None, folder=None, fqn=None):
    unique_id, node = entry
    node = dict(node)
    if folder is not None:
        node["original_file_path"] = f"{folder}/{node['name']}.sql"
    node["config"] = {"tags": list(tags or [])}
    node["unrendered_config"] = dict(unrendered or {})
    if fqn is not None:
        node["fqn"] = fqn
    return unique_id, node


def test_a_model_off_turbovaults_folders_keeps_its_folder(tmp_path):
    # unrendered_config has the folder's settings too (no dbt_project.yml here)
    layer = {"schema": "rdv", "materialized": "incremental"}
    hub = _with_settings(
        CUSTOMER_H,
        tags=["hub", "raw_vault"],
        folder="models/30_raw_vault",
        unrendered=layer,
    )
    v0 = _with_settings(
        CUSTOMER_S_V0,
        tags=["satellite", "standard", "raw_vault"],
        folder="models/vault/satellites",
        unrendered=layer,
    )
    v1 = _with_settings(
        CUSTOMER_S_V1,
        tags=["satellite", "v1", "raw_vault"],
        folder="models/vault/satellites",
        unrendered={**layer, "materialized": "view"},
    )
    path = write_manifest(
        tmp_path, [STG_CUSTOMER, STG_ORDERS, hub, v0, v1], [CUSTOMER, ORDERS]
    )

    domain, _ = map_manifest(path)

    # In TurboVault's folder, with its tags: nothing stored
    assert "hub" not in domain.hubs["customer_h"].outputs
    outputs = domain.satellites["customer_s"].outputs
    assert outputs["satellite_v0"].folder == "models/vault/satellites"
    assert outputs["satellite_v0"].tags is None
    # The v1 view sits next to its v0 and is a view, as TurboVault makes it
    assert "satellite_v1" not in outputs


def test_tags_and_settings_turbovault_doesnt_give_are_kept(tmp_path):
    hub = _with_settings(
        CUSTOMER_H,
        tags=["pii"],
        folder="models/30_raw_vault",
        unrendered={
            "schema": "rdv",
            "materialized": "table",
            "alias": "hub_customer",
            "unique_key": "hk",
        },
    )
    path = write_manifest(tmp_path, [STG_CUSTOMER, STG_ORDERS, hub], [CUSTOMER, ORDERS])

    domain, _ = map_manifest(path)

    output = domain.hubs["customer_h"].outputs["hub"]
    assert output.tags == ["pii"]
    assert (output.materialized, output.alias) == ("table", "hub_customer")
    assert output.config == {"unique_key": "hk"}
    assert output.folder is None


def test_folder_level_settings_stay_in_the_project_settings(tmp_path):
    (tmp_path / "dbt_project.yml").write_text(
        textwrap.dedent(
            """
            name: shop
            profile: shop_warehouse
            version: '3.1.0'
            vars:
              datavault4dbt.hash: SHA2
            models:
              shop:
                vault:
                  +schema: rdv
                  +materialized: incremental
                  +tags: [vault]
              elementary:
                +schema: elementary
            seeds:
              shop:
                +schema: seeds
            """
        ),
        encoding="utf-8",
    )
    hub = _with_settings(
        CUSTOMER_H,
        tags=["vault", "hub", "raw_vault", "pii"],
        folder="models/vault",
        fqn=["shop", "vault", "customer_h"],
        unrendered={
            "schema": "rdv",
            "materialized": "incremental",
            "tags": ["vault", "pii"],
        },
    )
    path = write_manifest(tmp_path, [STG_CUSTOMER, STG_ORDERS, hub], [CUSTOMER, ORDERS])

    domain, _ = map_manifest(path)

    output = domain.hubs["customer_h"].outputs["hub"]
    # The folder's schema and materialization aren't the model's own
    assert (output.schema_name, output.materialized) == (None, None)
    assert output.folder == "models/vault"
    # Tags add up (folder, TurboVault's defaults, its own): it keeps its own
    assert output.tags == ["pii"]
    # dbt_project.yml is suggested as it is (copied: no share)
    settings = {
        key: suggestion.value
        for key, suggestion in domain.project_settings.suggestions.items()
        if suggestion.total is None
    }
    assert settings == {
        "dbt_project_name": "shop",
        "profile_name": "shop_warehouse",
        "global_vars": {"datavault4dbt.hash": "SHA2"},
        "dbt_project_models": {
            "vault": {
                "+schema": "rdv",
                "+materialized": "incremental",
                "+tags": ["vault"],
            }
        },
        "dbt_project_settings": {
            "version": "3.1.0",
            "seeds": {"shop": {"+schema": "seeds"}},
            "models": {"elementary": {"+schema": "elementary"}},
        },
    }


def test_naming_patterns_the_project_follows_are_suggested(tmp_path):
    from engine.services.runtime_config import EngineRuntimeConfig

    path = shop(tmp_path)

    domain, issues = map_manifest(
        path, EngineRuntimeConfig(stage_naming="stage_[[ source_table ]]")
    )

    suggestions = domain.project_settings.suggestions
    suggestion = suggestions["stage_naming"]
    assert suggestion.value == "stg__[[ source_system ]]__[[ source_table ]]"
    assert (suggestion.matching, suggestion.total) == (2, 2)
    (note,) = [
        i
        for i in issues
        if i.code == "dbt.setting_suggested" and "stage_naming:" in i.message
    ]
    assert "2 of 2 names follow it" in note.message
    # Patterns the project already uses aren't suggested
    assert "hashkey_naming" not in suggestions


def test_the_report_carries_the_suggested_settings(tmp_path, project):
    from engine.services.imports import DbtSource, ImportOptions, import_metadata
    from engine.services.runtime_config import EngineRuntimeConfig

    report = import_metadata(
        project=project,
        source=DbtSource(path=shop(tmp_path)),
        options=ImportOptions(skip_snapshots=True, dry_run=True),
        runtime_config=EngineRuntimeConfig(stage_naming="stage_[[ source_table ]]"),
    )

    assert report.project_settings is not None
    assert "stage_naming" in report.project_settings.suggestions


def test_the_cli_writes_the_suggested_settings_before_importing(tmp_path, project):
    from engine.cli.commands import import_cmd
    from engine.services.config_schema import TurboVaultConfig
    from engine.services.imports import DbtSource, ImportOptions
    from engine.services.project_config import write_project_config

    folder = tmp_path / "project"
    folder.mkdir()
    write_project_config(
        folder / "config.yml",
        TurboVaultConfig(
            project={"name": "shop"},
            configuration={"stage_naming": "stage_[[ source_table ]]"},
        ),
    )
    project.project_directory = str(folder)
    project.save()
    dbt = tmp_path / "dbt"
    dbt.mkdir()
    (dbt / "dbt_project.yml").write_text(
        "name: shop_dv\nprofile: shop_wh\nvars:\n  datavault4dbt.hash: SHA2\n",
        encoding="utf-8",
    )

    import_cmd._offer_project_settings(
        project,
        DbtSource(path=shop(dbt)),
        ImportOptions(skip_snapshots=True),
        True,
    )

    config = project.load_config()
    assert config.configuration.stage_naming == (
        "stg__[[ source_system ]]__[[ source_table ]]"
    )
    assert config.configuration.profile_name == "shop_wh"
    assert config.output.dbt_project_name == "shop_dv"
    assert config.dbt_project.vars == {"datavault4dbt.hash": "SHA2"}


def test_without_default_tags_a_model_keeps_all_its_own_tags(tmp_path):
    from engine.services.runtime_config import EngineRuntimeConfig

    hub = _with_settings(
        CUSTOMER_H,
        tags=["hub", "pii"],
        folder="models/30_raw_vault",
        unrendered={"schema": "rdv", "materialized": "incremental"},
    )
    plain = _with_settings(
        ORDER_H,
        tags=[],
        folder="models/30_raw_vault",
        unrendered={"schema": "rdv", "materialized": "incremental"},
    )
    path = write_manifest(
        tmp_path, [STG_CUSTOMER, STG_ORDERS, hub, plain], [CUSTOMER, ORDERS]
    )

    domain, _ = map_manifest(path, EngineRuntimeConfig(add_default_tags=False))

    assert domain.hubs["customer_h"].outputs["hub"].tags == ["hub", "pii"]
    # Nothing to store for a model without tags
    assert "hub" not in domain.hubs["order_h"].outputs
