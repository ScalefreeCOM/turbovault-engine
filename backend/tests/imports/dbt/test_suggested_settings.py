"""Settings a dbt project suggests for its TurboVault project (spec D22, D28).

The import infers the settings most of the project's models follow (naming
patterns, layer schemas and materializations, the tables' default record
source and load date, stage options, the delivery method, default tags,
folders) and copies its dbt_project.yml and packages. It suggests what
differs from the project's settings, keyed by runtime config field, and
stores on each entity only what differs from the settings in effect.
"""

from __future__ import annotations

import textwrap
from typing import Any

import pytest
import yaml

from tests.imports.dbt.test_dbt_mapping import (
    CUSTOMER,
    CUSTOMER_H,
    CUSTOMER_S_V0,
    CUSTOMER_S_V1,
    ORDER_CUSTOMER_L,
    ORDER_H,
    ORDERS,
    STG_CUSTOMER,
    STG_ORDERS,
    map_manifest,
    write_manifest,
)

pytestmark = pytest.mark.django_db

_UNSET = object()


def configured(
    entry: tuple[str, dict[str, Any]],
    *,
    folder: str | None = None,
    schema: Any = _UNSET,
    materialized: str | None = None,
    tags: list[str] | None = None,
    raw_code: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """A model as dbt resolves it: its config has the schema and the
    materialization (None: no custom schema)."""
    unique_id, node = entry
    node = dict(node)
    if folder is not None:
        node["original_file_path"] = f"{folder}/{node['name']}.sql"
        node["fqn"] = ["shop", *folder.split("/")[1:], node["name"]]
    if raw_code is not None:
        node["raw_code"] = raw_code
    config: dict[str, Any] = {"tags": list(tags or [])}
    unrendered: dict[str, Any] = {}
    if schema is not _UNSET:
        config["schema"] = schema
        if schema is not None:
            unrendered["schema"] = schema
    if materialized:
        config["materialized"] = materialized
        unrendered["materialized"] = materialized
    node["config"] = config
    node["unrendered_config"] = unrendered
    return unique_id, node


def described_in(entry: tuple[str, dict[str, Any]], path: str):
    unique_id, node = entry
    return unique_id, {**node, "original_file_path": path}


def suggestions(domain) -> dict[str, Any]:
    return {
        key: suggestion.value
        for key, suggestion in domain.project_settings.suggestions.items()
    }


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def test_most_samples_decide_and_the_current_setting_wins_a_tie():
    from engine.services.imports.dbt.naming import majority

    assert majority(["a", "a", "b"]).value == "a"
    assert majority(["a", "a", "b", "b"], prefer="b").value == "b"
    # Fewer than half, or a single one of several, suggest nothing
    assert majority(["a", "b", "c"]) is None
    assert majority([True]).value is True


def test_values_keep_their_placeholders():
    from engine.services.imports.dbt.naming import infer_value

    found = infer_value(
        [
            ({"source_system": "crm", "source_table": "customer"}, "!crm.customer"),
            ({"source_system": "crm", "source_table": "orders"}, "!crm.orders"),
            ({"source_system": "erp", "source_table": "items"}, "!erp.items"),
        ]
    )

    assert found.value == "![[ source_system ]].[[ source_table ]]"
    assert (found.matching, found.total) == (3, 3)


def test_a_value_stands_for_a_placeholder_only_as_a_word_of_its_own():
    from engine.services.imports.dbt.naming import infer_value

    found = infer_value(
        [
            ({"source_system": "a", "source_table": "t1"}, "load_date"),
            ({"source_system": "a", "source_table": "t2"}, "load_date"),
        ]
    )

    assert found.value == "load_date"


def test_the_current_value_wins_when_the_samples_cant_tell():
    from engine.services.imports.dbt.naming import infer_value

    samples = [
        ({"source_system": "crm", "source_table": "customer"}, "!crm"),
        ({"source_system": "crm", "source_table": "orders"}, "!crm"),
    ]

    # One system: '!crm' and '![[ source_system ]]' give the same
    assert infer_value(samples, prefer="![[ source_system ]]").value == (
        "![[ source_system ]]"
    )
    assert infer_value(samples, prefer="!crm").value == "!crm"


def test_folder_patterns_find_the_group_folder():
    from engine.services.imports.dbt.naming import FolderSample, infer_folder

    found = infer_folder(
        [
            FolderSample("models/rdv/customer", group="customer"),
            FolderSample("models/rdv/customer", group="customer"),
            FolderSample("models/rdv/order", group="order"),
            # Without a group the group's folder is left out
            FolderSample("models/rdv", group=None),
        ]
    )

    assert found.value == "models/rdv/[[ group ]]"
    assert (found.matching, found.total) == (4, 4)
    spelled = infer_folder(
        [
            FolderSample("models/RDV/Customer", group="Customer"),
            FolderSample("models/RDV/Order", group="Order"),
        ]
    )
    assert spelled.value == "models/RDV/[[ group_name ]]"


def test_a_folder_that_differs_per_model_ends_the_pattern():
    from engine.services.imports.dbt.naming import FolderSample, infer_folder

    # Below the group, a folder per source: no placeholder stands for it
    samples = [
        FolderSample(f"models/rdv/{group}/{source}/v0", group=group)
        for group in ("sales", "finance")
        for source in ("crm", "crm", "crm", "erp", "web")
    ]

    found = infer_folder(samples)

    assert found.value == "models/rdv/[[ group ]]"
    assert (found.matching, found.total) == (10, 10)


# ---------------------------------------------------------------------------
# Layers: schemas and materializations
# ---------------------------------------------------------------------------


def test_layer_schemas_and_materializations_are_suggested(tmp_path):
    from engine.services.runtime_config import EngineRuntimeConfig

    stage = {"schema": "staging", "materialized": "table", "folder": "models/stages"}
    vault = {"schema": "edw", "materialized": "incremental", "folder": "models/rdv"}
    path = write_manifest(
        tmp_path,
        [
            configured(STG_CUSTOMER, **stage),
            configured(STG_ORDERS, **stage),
            configured(CUSTOMER_H, **vault),
            configured(ORDER_H, **vault),
            configured(ORDER_CUSTOMER_L, **vault),
            configured(CUSTOMER_S_V0, **vault),
            configured(CUSTOMER_S_V1, **{**vault, "materialized": "table"}),
        ],
        [CUSTOMER, ORDERS],
    )

    domain, issues = map_manifest(path, EngineRuntimeConfig())

    found = suggestions(domain)
    assert found["stage_schema"] == "staging"
    assert found["rdv_schema"] == "edw"
    assert found["staging_materialization"] == "table"
    # Raw vault models are incremental, like the project's: nothing to suggest
    assert "raw_vault_materialization" not in found
    # The v1 view's own materialization
    assert found["model_materializations.satellite_v1"] == "table"
    note = next(i for i in issues if "rdv_schema:" in i.message)
    assert note.code == "dbt.setting_suggested"
    assert note.severity == "info"
    assert "5 of 5 models follow it" in note.message
    # Stored relative to the project's settings: the schema differs
    assert domain.hubs["customer_h"].outputs["hub"].schema_name == "edw"

    # Applied, the models store none of it
    applied = EngineRuntimeConfig().with_settings(found)
    domain, _ = map_manifest(path, applied)

    assert "hub" not in domain.hubs["customer_h"].outputs
    assert "satellite_v1" not in domain.satellites["customer_s"].outputs
    assert domain.project_settings.is_empty()


def test_models_without_custom_schema_suggest_none(tmp_path):
    from engine.services.runtime_config import EngineRuntimeConfig

    path = write_manifest(
        tmp_path,
        [
            STG_CUSTOMER,
            STG_ORDERS,
            configured(CUSTOMER_H, schema=None, materialized="incremental"),
            configured(ORDER_H, schema=None, materialized="incremental"),
        ],
        [CUSTOMER, ORDERS],
    )

    domain, _ = map_manifest(path, EngineRuntimeConfig())

    found = suggestions(domain)
    assert "rdv_schema" in found and found["rdv_schema"] is None
    # Stages without the resolved config tell nothing
    assert "stage_schema" not in found


# ---------------------------------------------------------------------------
# Source tables: default values, stage options, delivery method
# ---------------------------------------------------------------------------


def _stage(entry, **replacements):
    unique_id, node = entry
    code = node["raw_code"]
    for old, new in replacements.items():
        assert old in code
        code = code.replace(old, new)
    return unique_id, {**node, "raw_code": code}


def test_default_record_source_and_load_date_are_suggested(tmp_path):
    from engine.services.imports.domain import CLEAR
    from engine.services.runtime_config import EngineRuntimeConfig

    path = write_manifest(
        tmp_path,
        [
            _stage(STG_CUSTOMER, **{"'!crm'": "'!crm.customer'"}),
            _stage(STG_ORDERS, **{"'!crm'": "'!crm.orders'"}),
            CUSTOMER_H,
        ],
        [CUSTOMER, ORDERS],
    )

    domain, _ = map_manifest(path, EngineRuntimeConfig())

    found = suggestions(domain)
    assert found["default_record_source_value"] == (
        "![[ source_system ]].[[ source_table ]]"
    )
    assert found["default_load_date_value"] == "LOAD_TS"
    tables = domain.source_systems["crm"].tables
    assert tables["crm|orders"].record_source_value == "!crm.orders"

    domain, _ = map_manifest(path, EngineRuntimeConfig().with_settings(found))

    crm = domain.source_systems["crm"]
    # What the project gives them isn't stored, on the system or the tables
    assert (crm.record_source_value, crm.load_date_value) == (CLEAR, CLEAR)
    for table in crm.tables.values():
        assert (table.record_source_value, table.load_date_value) == (CLEAR, CLEAR)


def test_a_tables_static_part_is_stored_relative_to_the_projects(tmp_path):
    from engine.services.imports.domain import CLEAR
    from engine.services.runtime_config import EngineRuntimeConfig

    path = write_manifest(
        tmp_path, [STG_CUSTOMER, STG_ORDERS, CUSTOMER_H], [CUSTOMER, ORDERS]
    )

    stored, _ = map_manifest(path, EngineRuntimeConfig())
    relative, _ = map_manifest(
        path, EngineRuntimeConfig(default_static_part_of_record_source="!crm")
    )

    customer = "crm|customer"
    assert stored.source_systems["crm"].tables[customer].static_part_of_record_source
    assert (
        relative.source_systems["crm"].tables[customer].static_part_of_record_source
        is CLEAR
    )


def test_stage_options_most_stages_use_are_suggested(tmp_path):
    from engine.services.imports.domain import CLEAR
    from engine.services.runtime_config import EngineRuntimeConfig

    path = write_manifest(
        tmp_path,
        [
            STG_CUSTOMER,  # include_source_columns: false
            _stage(
                STG_ORDERS,
                **{"rsrc: '!crm'": "rsrc: '!crm'\ninclude_source_columns: false"},
            ),
        ],
        [CUSTOMER, ORDERS],
    )

    domain, _ = map_manifest(path, EngineRuntimeConfig())

    found = suggestions(domain)
    assert found["include_source_columns"] is False
    assert "enable_ghost_records" not in found
    domain, _ = map_manifest(path, EngineRuntimeConfig(include_source_columns=False))
    for table in domain.source_systems["crm"].tables.values():
        assert table.include_source_columns is CLEAR


def test_delivery_methods_are_stored_relative_to_the_projects(tmp_path):
    from engine.services.imports.domain import CLEAR
    from engine.services.runtime_config import EngineRuntimeConfig

    from tests.imports.dbt.test_dbt_mapping import dv, model

    single = model(
        "customer_es",
        dv(
            "eff_sat_v0",
            """
            source_model: stg__crm__customer
            tracked_hashkey: hk_customer_h
            source_is_single_batch: true
            """,
        ),
    )
    path = write_manifest(
        tmp_path, [STG_CUSTOMER, STG_ORDERS, CUSTOMER_H, single], [CUSTOMER, ORDERS]
    )

    domain, _ = map_manifest(
        path,
        EngineRuntimeConfig(use_delivery_method=True, delivery_method="single_batch"),
    )

    tables = domain.source_systems["crm"].tables
    # The project's delivery method isn't stored; the other one is
    assert tables["crm|customer"].delivery_method is CLEAR
    assert tables["crm|orders"].delivery_method == "multi_batch"
    assert "use_delivery_method" not in domain.project_settings.suggestions


# ---------------------------------------------------------------------------
# Tags and folders
# ---------------------------------------------------------------------------


def test_default_tags_are_turned_off_when_most_models_lack_them(tmp_path):
    from engine.services.runtime_config import EngineRuntimeConfig

    tagged = write_manifest(
        tmp_path,
        [
            STG_CUSTOMER,
            STG_ORDERS,
            configured(CUSTOMER_H, tags=["hub", "raw_vault"]),
            configured(ORDER_H, tags=["hub", "raw_vault", "orders"]),
        ],
        [CUSTOMER, ORDERS],
    )
    domain, _ = map_manifest(tagged, EngineRuntimeConfig())
    assert "add_default_tags" not in suggestions(domain)

    (tmp_path / "plain").mkdir()
    plain = write_manifest(
        tmp_path / "plain",
        [
            STG_CUSTOMER,
            STG_ORDERS,
            configured(CUSTOMER_H, tags=["pii"]),
            configured(ORDER_H, tags=[]),
        ],
        [CUSTOMER, ORDERS],
    )
    domain, _ = map_manifest(plain, EngineRuntimeConfig())
    assert suggestions(domain)["add_default_tags"] is False


def test_subject_folders_become_groups_and_folder_patterns(tmp_path):
    from engine.services.runtime_config import EngineRuntimeConfig

    path = write_manifest(
        tmp_path,
        [
            configured(STG_CUSTOMER, folder="models/stages/crm"),
            configured(STG_ORDERS, folder="models/stages/crm"),
            configured(CUSTOMER_H, folder="models/rdv/customer"),
            configured(CUSTOMER_S_V0, folder="models/rdv/customer"),
            configured(CUSTOMER_S_V1, folder="models/rdv/customer"),
            configured(ORDER_H, folder="models/rdv/order"),
            configured(ORDER_CUSTOMER_L, folder="models/rdv/order"),
        ],
        [
            described_in(CUSTOMER, "models/sources/crm.yml"),
            described_in(ORDERS, "models/sources/crm.yml"),
        ],
    )

    domain, _ = map_manifest(path, EngineRuntimeConfig())

    # Each subject folder holds several kinds of entity: a group
    assert domain.groups == {"customer", "order"}
    assert domain.hubs["customer_h"].group_name == "customer"
    assert domain.links["order_customer_l"].group_name == "order"
    found = suggestions(domain)
    assert found["folders.staging"] == "models/stages/[[ source_system ]]"
    assert found["folders.raw_vault"] == "models/rdv/[[ group ]]"
    assert found["folders.sources"] == "models/sources"
    # v1 views sit next to their v0, as generated
    assert "folders.satellite_v1" not in found

    domain, _ = map_manifest(path, EngineRuntimeConfig().with_settings(found))

    assert all(
        output.folder is None
        for entity in (*domain.hubs.values(), *domain.satellites.values())
        for output in (entity.outputs or {}).values()
    )


def test_vault_folders_may_follow_the_source_system(tmp_path):
    from engine.services.runtime_config import EngineRuntimeConfig

    vault = {"folder": "models/rdv/crm", "materialized": "incremental"}
    path = write_manifest(
        tmp_path,
        [
            STG_CUSTOMER,
            STG_ORDERS,
            configured(CUSTOMER_H, **vault),
            configured(ORDER_H, **vault),
            configured(ORDER_CUSTOMER_L, **vault),
            configured(CUSTOMER_S_V0, **vault),
        ],
        [CUSTOMER, ORDERS],
    )

    domain, _ = map_manifest(path, EngineRuntimeConfig())

    # Every entity loads from crm: the folder names the source system
    found = suggestions(domain)
    assert found["folders.raw_vault"] == "models/rdv/[[ source_system ]]"
    domain, _ = map_manifest(path, EngineRuntimeConfig().with_settings(found))
    assert "hub" not in domain.hubs["customer_h"].outputs


def test_folders_named_after_kinds_of_model_are_no_groups(tmp_path):
    path = write_manifest(
        tmp_path,
        [
            STG_CUSTOMER,
            STG_ORDERS,
            configured(CUSTOMER_H, folder="models/rdv/hubs"),
            configured(ORDER_H, folder="models/rdv/hubs"),
            configured(ORDER_CUSTOMER_L, folder="models/rdv/links"),
            configured(CUSTOMER_S_V0, folder="models/rdv/satellites"),
        ],
        [CUSTOMER, ORDERS],
    )

    domain, _ = map_manifest(path)

    assert domain.groups == set()


# ---------------------------------------------------------------------------
# The dbt project's files
# ---------------------------------------------------------------------------


def test_packages_are_suggested_from_the_package_files(tmp_path):
    (tmp_path / "packages.yml").write_text(
        textwrap.dedent(
            """
            packages:
              - package: ScalefreeCOM/datavault4dbt
                version: [">=1.9.0", "<2.0.0"]
              - package: dbt-labs/dbt_utils
                version: 1.3.0
            """
        ),
        encoding="utf-8",
    )
    path = write_manifest(tmp_path, [STG_CUSTOMER, STG_ORDERS], [CUSTOMER, ORDERS])

    domain, _ = map_manifest(path)

    packages = domain.project_settings.suggestions["dbt_packages"]
    assert packages.value == [
        {"package": "ScalefreeCOM/datavault4dbt", "version": [">=1.9.0", "<2.0.0"]},
        {"package": "dbt-labs/dbt_utils", "version": "1.3.0"},
    ]
    assert packages.total is None  # copied


def test_without_packages_yml_the_lock_files_versions_are_suggested(tmp_path):
    (tmp_path / "package-lock.yml").write_text(
        textwrap.dedent(
            """
            packages:
              - package: ScalefreeCOM/datavault4dbt
                name: datavault4dbt
                version: 1.9.3
            sha1_hash: abc
            """
        ),
        encoding="utf-8",
    )
    path = write_manifest(tmp_path, [STG_CUSTOMER, STG_ORDERS], [CUSTOMER, ORDERS])

    domain, _ = map_manifest(path)

    assert suggestions(domain)["dbt_packages"] == [
        {"package": "ScalefreeCOM/datavault4dbt", "version": "1.9.3"}
    ]


# ---------------------------------------------------------------------------
# Applying suggestions
# ---------------------------------------------------------------------------


def test_settings_apply_to_a_runtime_config():
    from engine.services.runtime_config import EngineRuntimeConfig

    config = EngineRuntimeConfig(folders={"pit": "models/pits"}).with_settings(
        {
            "rdv_schema": None,
            "folders.raw_vault": "models/rdv/[[ group ]]",
            "model_materializations.pit": "table",
        }
    )

    assert config.rdv_schema is None
    assert config.folders == {
        "pit": "models/pits",
        "raw_vault": "models/rdv/[[ group ]]",
    }
    assert config.model_materializations == {"pit": "table"}
    with pytest.raises(ValueError, match="Unknown project setting"):
        config.with_settings({"no_such_setting": 1})


def test_settings_are_written_into_config_yml_keeping_the_rest(tmp_path):
    from engine.services.config_schema import TurboVaultConfig
    from engine.services.project_config import apply_settings
    from engine.services.runtime_config import EngineRuntimeConfig

    path = tmp_path / "config.yml"
    path.write_text(
        textwrap.dedent(
            """
            project:
              name: shop
            configuration:
              hashkey_naming: hk_[[ entity_name ]]
            output:
              sqlmesh:
                dialect: snowflake
            """
        ),
        encoding="utf-8",
    )

    apply_settings(
        path,
        {
            "stage_naming": "stg_[[ source_table ]]",
            "rdv_schema": None,
            "folders.raw_vault": "models/rdv/[[ group ]]",
            "dbt_project_name": "shop_dv",
            "global_vars": {"datavault4dbt.hash": "SHA2"},
            "dbt_packages": [{"package": "dbt-labs/dbt_utils", "version": "1.3.0"}],
        },
    )

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert document["output"] == {
        "sqlmesh": {"dialect": "snowflake"},
        "dbt_project_name": "shop_dv",
    }
    runtime = EngineRuntimeConfig.from_turbovault_config(TurboVaultConfig(**document))
    assert runtime.hashkey_naming == "hk_[[ entity_name ]]"
    assert runtime.stage_naming == "stg_[[ source_table ]]"
    assert runtime.rdv_schema is None
    assert runtime.folders == {"raw_vault": "models/rdv/[[ group ]]"}
    assert runtime.global_vars == {"datavault4dbt.hash": "SHA2"}
    assert runtime.dbt_packages == [
        {"package": "dbt-labs/dbt_utils", "version": "1.3.0"}
    ]

    # An invalid setting leaves the file as it is
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        apply_settings(path, {"folders.vault": "models/dv"})
    assert path.read_text(encoding="utf-8") == before
