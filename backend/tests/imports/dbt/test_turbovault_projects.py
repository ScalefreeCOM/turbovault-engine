"""Importing a dbt project TurboVault generated: it comes back as it was.

What TurboVault's templates write by themselves (default descriptions, the
derived column renaming a link's dependent child key, its dbt_project.yml
layer blocks and packages) isn't imported as the project's own, and what
datavault4dbt's parameters lose (a multi-active key's place among the
columns, a logic column's spelling, columns differing in case only) is read
back from the stage and the YAML. The round trip itself (generate, dbt parse,
import, generate again) is in test_round_trip.py.
"""

from __future__ import annotations

import textwrap

import pytest

from tests.imports.dbt.test_dbt_mapping import (
    CONTROL_V0,
    CONTROL_V1,
    CUSTOMER,
    CUSTOMER_H,
    CUSTOMER_S_V0,
    ORDER_H,
    ORDERS,
    STG_CUSTOMER,
    STG_ORDERS,
    dv,
    map_manifest,
    model,
    source,
    write_manifest,
)

pytestmark = pytest.mark.django_db


def described(entry, description: str, **columns: str):
    unique_id, node = entry
    node = {**node, "description": description}
    if columns:
        node["columns"] = {
            name: {"name": name, "description": text} for name, text in columns.items()
        }
    return unique_id, node


def test_columns_differing_in_case_only_stay_apart(tmp_path):
    table = source("crm", "contact", ["ID", "NAME", "Name", "name"])
    stage = model(
        "stg__crm__contact",
        dv(
            "stage",
            """
            source_model:
                crm: contact
            hashed_columns:
                hk_contact_h: [ID]
                hd_contact_s:
                    is_hashdiff: true
                    columns: [Name, name]
            """,
        ),
        folder="models/staging",
    )
    hub = model(
        "contact_h",
        dv(
            "hub",
            """
            hashkey: hk_contact_h
            business_keys: [ID]
            source_models: stg__crm__contact
            """,
        ),
    )
    satellite = model(
        "contact_s_v0",
        dv(
            "sat_v0",
            """
            source_model: stg__crm__contact
            parent_hashkey: hk_contact_h
            src_hashdiff: hd_contact_s
            src_payload: [Name, name]
            """,
        ),
    )

    domain, _ = map_manifest(write_manifest(tmp_path, [stage, hub, satellite], [table]))

    columns = domain.source_systems["crm"].tables["crm|contact"].columns.values()
    assert [column.name for column in columns] == ["ID", "NAME", "Name", "name"]
    assert [c.source_column_name for c in domain.satellites["contact_s"].columns] == [
        "Name",
        "name",
    ]


def test_a_dependent_child_key_renamed_for_its_link_maps_to_the_hashed_column(
    tmp_path,
):
    stage = model(
        "stg__crm__orders",
        STG_ORDERS[1]["raw_code"].replace(
            "hashed_columns:",
            "derived_columns:\n    DCK_LINE:\n        value: LINE_NO\nhashed_columns:",
        ),
        folder="models/staging",
    )
    link = model(
        "order_customer_l",
        dv(
            "link",
            """
            link_hashkey: hk_order_customer_l
            foreign_hashkeys: [hk_order_h, hk_customer_h, DCK_LINE]
            source_models: stg__crm__orders
            """,
        ),
    )

    domain, issues = map_manifest(
        write_manifest(
            tmp_path,
            [STG_CUSTOMER, stage, CUSTOMER_H, ORDER_H, link],
            [CUSTOMER, ORDERS],
        )
    )

    (key,) = [
        c
        for c in domain.links["order_customer_l"].columns
        if c.column_type == "dependent_child_key"
    ]
    assert key.name == "DCK_LINE"
    assert [m.source_column_name for m in key.source_mappings] == ["LINE_NO"]
    # Generation writes the rename again from the link
    orders = domain.source_systems["crm"].tables["crm|orders"]
    assert "dck_line" not in (orders.derived_columns or {})
    assert not [i for i in issues if "foreign_hashkeys doesn't list" in i.message]


def test_turbovaults_default_descriptions_arent_imported(tmp_path):
    crm = described(
        source("crm", "customer", ["ID", "NAME", "EMAIL", "LOAD_TS"]),
        "Source table from CRM",
    )
    orders = described(ORDERS, "Orders as the shop records them")
    hub = described(CUSTOMER_H, "Standard hub for customer_h")
    satellite = described(
        CUSTOMER_S_V0, "Standard satellite for customer_h", EMAIL="Payload column"
    )

    domain, _ = map_manifest(
        write_manifest(
            tmp_path, [STG_CUSTOMER, STG_ORDERS, hub, satellite], [crm, orders]
        )
    )

    # The default description spells the system as TurboVault named it
    system = domain.source_systems["CRM"]
    assert system.tables["CRM|customer"].description is None
    assert system.tables["CRM|orders"].description == "Orders as the shop records them"
    assert domain.hubs["customer_h"].description is None
    satellite = domain.satellites["customer_s"]
    assert satellite.description is None
    assert {c.source_column_name: c.description for c in satellite.columns}[
        "EMAIL"
    ] is None


def test_a_multi_active_key_keeps_its_place_among_the_columns(tmp_path):
    stage = model(
        "stg__crm__customer",
        STG_CUSTOMER[1]["raw_code"].replace("hd_customer_s:", "hd_customer_ms:"),
        folder="models/staging",
    )
    assert "hd_customer_ms" in stage[1]["raw_code"]
    satellite = model(
        "customer_ms_v0",
        dv(
            "ma_sat_v0",
            """
            source_model: stg__crm__customer
            parent_hashkey: hk_customer_h
            src_hashdiff: hd_customer_ms
            src_ma_key: [EMAIL]
            src_payload: [NAME_UPPER]
            """,
        ),
    )

    domain, _ = map_manifest(
        write_manifest(
            tmp_path, [stage, STG_ORDERS, CUSTOMER_H, satellite], [CUSTOMER, ORDERS]
        )
    )

    columns = domain.satellites["customer_ms"].columns
    assert [(c.source_column_name, c.is_multi_active_key) for c in columns] == [
        ("NAME_UPPER", False),
        ("EMAIL", True),
    ]


def test_a_non_historized_satellite_detects_no_changes(tmp_path):
    satellite = model(
        "customer_ns",
        dv(
            "nh_sat",
            """
            source_model: stg__crm__customer
            parent_hashkey: hk_customer_h
            src_payload: [NAME_UPPER, EMAIL]
            """,
        ),
    )

    domain, _ = map_manifest(
        write_manifest(
            tmp_path,
            [STG_CUSTOMER, STG_ORDERS, CUSTOMER_H, satellite],
            [CUSTOMER, ORDERS],
        )
    )

    columns = domain.satellites["customer_ns"].columns
    assert [c.include_in_delta_detection for c in columns] == [False, False]


def test_a_logic_column_keeps_its_documented_spelling(tmp_path):
    unique_id, control = CONTROL_V1
    control = {**control, "columns": {"is_active": {"name": "IS_ACTIVE"}}}

    domain, _ = map_manifest(
        write_manifest(
            tmp_path,
            [STG_CUSTOMER, STG_ORDERS, CONTROL_V0, (unique_id, control)],
            [CUSTOMER, ORDERS],
        )
    )

    (snapshot_control,) = domain.snapshot_controls.values()
    assert {rule.column_name for rule in snapshot_control.logic_rules} == {"IS_ACTIVE"}


def test_what_turbovault_writes_anyway_isnt_suggested(tmp_path):
    (tmp_path / "dbt_project.yml").write_text(
        textwrap.dedent("""
            name: shop
            version: '1.0.0'
            config-version: 2
            profile: default
            model-paths: ["models"]
            clean-targets: ["target", "dbt_packages"]
            models:
              shop:
                00_control:
                  +schema: control
                  +materialized: table
                20_staging:
                  +schema: stage
                  +materialized: view
                30_raw_vault:
                  +schema: rdv
                  +materialized: incremental
                  +tags: [vault]
                40_business_vault:
                  +schema: bdv
                  +materialized: table
            """),
        encoding="utf-8",
    )
    (tmp_path / "packages.yml").write_text(
        "packages:\n  - package: ScalefreeCOM/datavault4dbt\n"
        '    version: [">=1.0.0", "<3.0.0"]\n',
        encoding="utf-8",
    )
    path = write_manifest(tmp_path, [STG_CUSTOMER, STG_ORDERS], [CUSTOMER, ORDERS])

    domain, _ = map_manifest(path)

    suggestions = domain.project_settings.suggestions
    # Only what TurboVault doesn't write by itself
    assert suggestions["dbt_project_models"].value == {
        "30_raw_vault": {"+tags": ["vault"]}
    }
    assert "dbt_project_settings" not in suggestions
    assert "dbt_packages" not in suggestions


def test_a_payload_column_the_link_key_hashes_is_one_column(tmp_path):
    link = model(
        "order_customer_l",
        dv(
            "nh_link",
            """
            link_hashkey: hk_order_customer_l
            foreign_hashkeys: [hk_order_h, hk_customer_h]
            payload: [LINE_NO, AMOUNT]
            source_models: stg__crm__orders
            """,
        ),
    )

    domain, _ = map_manifest(
        write_manifest(
            tmp_path,
            [STG_CUSTOMER, STG_ORDERS, CUSTOMER_H, ORDER_H, link],
            [CUSTOMER, ORDERS],
        )
    )

    columns = [
        (c.name, c.column_type) for c in domain.links["order_customer_l"].columns
    ]
    assert columns == [("LINE_NO", "dependent_child_key"), ("AMOUNT", "payload")]


def test_a_logic_column_keeps_all_its_rules_in_the_project(tmp_path, django_setup):
    from engine.models import Project, SnapshotControlLogic

    from tests.imports.dbt.test_dbt_mapping import import_shop

    project = Project.objects.create(name="shop")
    path = write_manifest(
        tmp_path, [STG_CUSTOMER, STG_ORDERS, CONTROL_V0, CONTROL_V1], [CUSTOMER, ORDERS]
    )

    import_shop(project, path, skip_snapshots=False)
    again = import_shop(project, path, skip_snapshots=False)

    # One column, a rule per interval (daily, yearly)
    rules = SnapshotControlLogic.objects.filter(snapshot_control_table__project=project)
    assert sorted(rules.values_list("snapshot_component", flat=True)) == [
        "beginning_of_year",
        "daily",
    ]
    assert all(e.action in ("unchanged", "skip") for e in again.plan.entities)
