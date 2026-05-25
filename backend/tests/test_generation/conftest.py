"""Fixtures specific to generation-pipeline tests.

The package-level `tests/conftest.py` has a `project_export` fixture that
skips when no sample JSON file is in the repo root. To keep these tests
runnable in CI without that file, we provide a minimal hand-built
`ProjectExport` here that covers the same shape the pipeline cares about.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def project_export(django_setup):
    """A small but complete ProjectExport with one source, one hub, one link
    referencing that hub, one satellite, and one stage."""
    from engine.services.export.models import (
        HashkeyDefinition,
        HubColumnMapping,
        HubDefinition,
        HubSourceInfo,
        LinkColumnMapping,
        LinkDefinition,
        LinkHubReferenceDefinition,
        LinkSourceInfo,
        ProjectExport,
        SatelliteColumnDef,
        SatelliteDefinition,
        SourceColumnDef,
        SourceSystemDef,
        SourceTableDef,
        StageDefinition,
        StageHashdiffDef,
        StageHashkeyDef,
    )

    sources = [
        SourceSystemDef(
            name="crm",
            schema_name="crm_raw",
            tables=[
                SourceTableDef(
                    table_name="customer",
                    record_source="crm.customer",
                    load_date="load_dt",
                    columns=[
                        SourceColumnDef(column_name="customer_id", datatype="STRING"),
                        SourceColumnDef(column_name="customer_name", datatype="STRING"),
                    ],
                ),
            ],
        ),
    ]

    hubs = [
        HubDefinition(
            hub_name="hub_customer",
            hub_type="standard",
            group="sales",
            hashkey=HashkeyDefinition(
                hashkey_name="hk_customer", business_keys=["customer_id"]
            ),
            business_key_columns=["customer_id"],
            source_tables=[
                HubSourceInfo(
                    source_table="customer",
                    source_system="crm",
                    stage_name="stg__crm__customer",
                    business_key_columns=["customer_id"],
                    is_primary_source=True,
                    column_mappings=[
                        HubColumnMapping(
                            hub_column="customer_id",
                            source_column="customer_id",
                        )
                    ],
                )
            ],
        )
    ]

    links = [
        LinkDefinition(
            link_name="lnk_customer_order",
            link_type="standard",
            group="sales",
            hashkey=HashkeyDefinition(
                hashkey_name="hk_customer_order",
                business_keys=["customer_id", "order_id"],
            ),
            hub_references=[
                LinkHubReferenceDefinition(hub_name="hub_customer"),
            ],
            foreign_hashkeys=["hk_customer", "hk_order"],
            payload_columns=[],
            source_tables=[
                LinkSourceInfo(
                    source_table="customer",
                    source_system="crm",
                    stage_name="stg__crm__customer",
                    columns=[
                        LinkColumnMapping(
                            link_column_name="customer_id",
                            link_column_type="business_key",
                            source_column_name="customer_id",
                        ),
                    ],
                )
            ],
        )
    ]

    satellites = [
        SatelliteDefinition(
            satellite_name="sat_customer_details",
            satellite_type="standard",
            group="sales",
            parent_entity="hub_customer",
            parent_entity_type="hub",
            parent_hashkey="hk_customer",
            source_table="customer",
            source_system="crm",
            stage_name="stg__crm__customer",
            hashdiff_name="hd_sat_customer_details",
            columns=[
                SatelliteColumnDef(source_column="customer_name"),
            ],
        )
    ]

    stages = [
        StageDefinition(
            stage_name="stg__crm__customer",
            source_table="customer",
            source_schema="crm_raw",
            source_system="crm",
            hashkeys=[
                StageHashkeyDef(
                    target_entity="hub_customer",
                    entity_type="hub",
                    hashkey_name="hk_customer",
                    business_key_columns=["customer_id"],
                )
            ],
            hashdiffs=[
                StageHashdiffDef(
                    satellite_name="sat_customer_details",
                    hashdiff_name="hd_sat_customer_details",
                    columns=["customer_name"],
                )
            ],
            columns=[
                SourceColumnDef(column_name="customer_id", datatype="STRING"),
                SourceColumnDef(column_name="customer_name", datatype="STRING"),
            ],
        )
    ]

    return ProjectExport(
        project_name="pipeline_test",
        sources=sources,
        hubs=hubs,
        stages=stages,
        satellites=satellites,
        links=links,
    )
