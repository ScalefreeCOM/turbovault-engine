"""SQLMesh output and stage prejoins.

datavault4sqlmesh's stage_model has no prejoin support, so prejoined columns
don't exist in the generated stage. Hash keys, hash diffs, derived columns and
entities that read them must be left out with warnings, so the generated
project stays runnable.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("django_setup")

STAGE = "stg__webshop__order"
OTHER_STAGE = "stg__crm__customer"


def _export(**overrides):
    """A stage with a prejoin to `kunden` that extracts `kunden_nr`.

    From the prejoin stage:
      - order_h        hub on order_id                         → unaffected
      - customer_h     hub on the prejoined kunden_nr          → skipped
      - order_customer_l link, FK hk_customer_h from kunden_nr → skipped
      - order_s        satellite on status                     → unaffected
      - order_kunde_s  satellite with prejoined payload        → skipped
    customer_h is also loaded from OTHER_STAGE, which has no prejoins.
    """
    from engine.services.export.models import (
        DerivedColumnDef,
        HashkeyDefinition,
        HubColumnMapping,
        HubDefinition,
        HubSourceInfo,
        LinkDefinition,
        LinkSourceInfo,
        PrejoinCondition,
        PrejoinDefinitionExport,
        PrejoinExtractionColumn,
        ProjectExport,
        SatelliteColumnDef,
        SatelliteDefinition,
        StageDefinition,
        StageHashdiffDef,
        StageHashkeyDef,
    )

    def hub(name, bk, sources):
        return HubDefinition(
            hub_name=name,
            hub_type=overrides.get(f"{name}_type", "standard"),
            hashkey=HashkeyDefinition(hashkey_name=f"hk_{name}", business_keys=[bk]),
            business_key_columns=[bk],
            source_tables=[
                HubSourceInfo(
                    source_table=stage,
                    source_system="webshop",
                    stage_name=stage,
                    business_key_columns=[source],
                    column_mappings=[HubColumnMapping(hub_column=bk, source_column=source)],
                )
                for stage, source in sources
            ],
        )

    def sat(name, parent, columns, hashdiff_columns):
        return SatelliteDefinition(
            satellite_name=name,
            satellite_type="standard",
            parent_entity=parent,
            parent_entity_type="hub" if parent.endswith("_h") else "link",
            parent_hashkey=f"hk_{parent}",
            source_table="order",
            source_system="webshop",
            stage_name=STAGE,
            hashdiff_name=f"hd_{name}",
            columns=[SatelliteColumnDef(source_column=c) for c in columns],
        ), StageHashdiffDef(
            satellite_name=name, hashdiff_name=f"hd_{name}", columns=hashdiff_columns
        )

    order_s, order_s_hd = sat("order_s", "order_h", ["status"], ["status"])
    kunde_s, kunde_s_hd = sat("order_kunde_s", "order_h", ["kunden_nr_clean"], ["kunden_nr_clean"])

    return ProjectExport(
        project_name="prejoins",
        hubs=[
            hub("order_h", "order_id", [(STAGE, "order_id")]),
            hub("customer_h", "customer_nr", [(OTHER_STAGE, "customer_nr"), (STAGE, "kunden_nr")]),
        ],
        links=[
            LinkDefinition(
                link_name="order_customer_l",
                link_type="standard",
                hashkey=HashkeyDefinition(hashkey_name="hk_order_customer_l", business_keys=[]),
                foreign_hashkeys=["hk_order_h", "hk_customer_h"],
                source_tables=[
                    LinkSourceInfo(source_table="order", source_system="webshop", stage_name=STAGE)
                ],
            )
        ],
        satellites=[order_s, kunde_s],
        stages=[
            StageDefinition(
                stage_name=STAGE,
                source_table="order",
                source_schema="webshop_raw",
                source_system="webshop",
                prejoins=overrides.get(
                    "prejoins",
                    [
                        PrejoinDefinitionExport(
                            target_table="kunden",
                            join_conditions=PrejoinCondition(
                                source_columns=["kunden_ref"], target_columns=["kunden_ref"]
                            ),
                            extraction_columns=[
                                PrejoinExtractionColumn(
                                    source_column_name="kundennummer",
                                    target_column_alias="kunden_nr",
                                )
                            ],
                        )
                    ],
                ),
                hashkeys=[
                    StageHashkeyDef(target_entity="order_h", hashkey_name="hk_order_h",
                                    business_key_columns=["order_id"]),
                    StageHashkeyDef(target_entity="customer_h", hashkey_name="hk_customer_h",
                                    business_key_columns=["KUNDEN_NR"]),  # case differs
                    StageHashkeyDef(target_entity="order_customer_l", entity_type="link",
                                    hashkey_name="hk_order_customer_l",
                                    business_key_columns=["order_id", "kunden_nr"]),
                ],
                hashdiffs=[order_s_hd, kunde_s_hd],
                derived_columns=[
                    DerivedColumnDef(
                        target_column_name="kunden_nr_clean",
                        source_column_name="kunden_nr",
                        transformation="TRIM(kunden_nr)",
                        src_cols_required=["kunden_nr"],
                    ),
                    DerivedColumnDef(
                        target_column_name="status_clean",
                        source_column_name="status",
                        transformation="TRIM(status)",
                    ),
                ],
            ),
            StageDefinition(
                stage_name=OTHER_STAGE,
                source_table="customer",
                source_schema="crm_raw",
                source_system="crm",
                hashkeys=[
                    StageHashkeyDef(target_entity="customer_h", hashkey_name="hk_customer_h",
                                    business_key_columns=["customer_nr"]),
                ],
            ),
        ],
    )


def _render(export):
    from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh
    from engine.services.generation.types import GenerationOptions
    from engine.services.runtime_config import EngineRuntimeConfig

    return render_sqlmesh(export, EngineRuntimeConfig(), GenerationOptions())


def _rendered_names(artifacts):
    return {a.entity_name for a in artifacts if a.entity_name}


def _codes(issues, code):
    return [i for i in issues if i.code == code]


def test_stage_with_prejoins_gets_one_warning():
    from engine.services.generation.errors import Code

    _, issues = _render(_export())
    (warning,) = _codes(issues, Code.SQLMESH_UNSUPPORTED_PREJOIN)
    assert warning.severity == "warning"
    assert warning.entity is not None and warning.entity.name == STAGE
    assert "kunden" in warning.message
    assert "'hk_customer_h'" in warning.message and "'hk_order_customer_l'" in warning.message
    assert "'order_kunde_s'" in warning.message


def test_entities_using_prejoined_columns_are_skipped_with_warnings():
    from engine.services.generation.errors import Code

    artifacts, issues = _render(_export())
    names = _rendered_names(artifacts)
    assert {"order_h", "order_s"} <= names
    assert not {"customer_h", "order_customer_l", "order_kunde_s"} & names

    skipped = {i.entity.name for i in _codes(issues, Code.SQLMESH_PREJOIN_DEPENDENT_SKIPPED)}
    assert skipped == {"customer_h", "order_customer_l", "order_kunde_s"}
    assert all(i.severity == "warning" for i in issues)


def test_prejoin_stage_leaves_out_unavailable_hash_keys_diffs_and_derived_columns():
    artifacts, _ = _render(_export())
    stage = next(a for a in artifacts if a.entity_type == "stage" and a.entity_name == STAGE)
    assert "hk_order_h" in stage.content
    assert "hd_order_s" in stage.content
    assert "status_clean" in stage.content
    # Read the prejoined column (directly or via a derived column):
    assert "hk_customer_h" not in stage.content
    assert "hk_order_customer_l" not in stage.content
    assert "hd_order_kunde_s" not in stage.content
    assert "kunden_nr" not in stage.content


def test_hash_key_of_skipped_entity_is_also_left_out_of_other_stages():
    """customer_h is skipped, so its hash key isn't computed in its other stage either."""
    artifacts, _ = _render(_export())
    other = next(a for a in artifacts if a.entity_name == OTHER_STAGE)
    assert "hk_customer_h" not in other.content


def test_entity_skipped_for_another_reason_is_not_reported_twice():
    from engine.services.generation.errors import Code

    _, issues = _render(_export(customer_h_type="reference"))
    assert _codes(issues, Code.SQLMESH_UNSUPPORTED_REFERENCE_HUB)
    skipped = {i.entity.name for i in _codes(issues, Code.SQLMESH_PREJOIN_DEPENDENT_SKIPPED)}
    assert "customer_h" not in skipped


def test_without_prejoins_nothing_is_skipped():
    from engine.services.generation.errors import Code

    artifacts, issues = _render(_export(prejoins=[]))
    assert not _codes(issues, Code.SQLMESH_UNSUPPORTED_PREJOIN)
    assert not _codes(issues, Code.SQLMESH_PREJOIN_DEPENDENT_SKIPPED)
    assert {"order_h", "customer_h", "order_customer_l", "order_s", "order_kunde_s"} <= (
        _rendered_names(artifacts)
    )
