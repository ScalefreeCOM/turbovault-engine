"""Unit tests for SQLMesh-specific plan stage counting (ticket 423).

Mirrors test_plan_stage.py for the sqlmesh output_type.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.django_db


def test_sqlmesh_plan_counts_five_scaffold_files(django_setup, project_export):
    from engine.services.generation.stages.plan import build_plan
    from engine.services.generation.types import GenerationOptions

    plan, _, issues = build_plan(
        project_export=project_export,
        output_type="sqlmesh",
        options=GenerationOptions(),
    )

    # config.yaml, config.json, models/__init__.py, requirements.txt, README.md
    assert plan.by_entity_type["project"] == 5
    assert not [i for i in issues if i.severity == "error"]


def test_sqlmesh_plan_counts_one_file_per_supported_entity(django_setup, project_export):
    from engine.services.generation.stages.plan import build_plan
    from engine.services.generation.types import GenerationOptions

    plan, _, _ = build_plan(
        project_export=project_export,
        output_type="sqlmesh",
        options=GenerationOptions(generate_satellite_v1_views=False),
    )

    # One .py file per entity — unlike dbt there is no paired YAML file.
    if project_export.stages:
        assert plan.by_entity_type["stage"] == len(project_export.stages)

    standard_hubs = [h for h in project_export.hubs if h.hub_type == "standard"]
    if standard_hubs:
        assert plan.by_entity_type["hub"] == len(standard_hubs)

    standard_links = [lnk for lnk in project_export.links if lnk.link_type == "standard"]
    if standard_links:
        assert plan.by_entity_type["link"] == len(standard_links)

    standard_sats = [s for s in project_export.satellites if s.satellite_type == "standard"]
    if standard_sats:
        assert plan.by_entity_type["satellite"] == len(standard_sats)


def test_sqlmesh_plan_satellite_v1_doubles_satellite_count(django_setup, project_export):
    from engine.services.generation.stages.plan import build_plan
    from engine.services.generation.types import GenerationOptions

    standard_sats = [s for s in project_export.satellites if s.satellite_type == "standard"]
    if not standard_sats:
        pytest.skip("No standard satellites in fixture")

    plan, _, _ = build_plan(
        project_export=project_export,
        output_type="sqlmesh",
        options=GenerationOptions(generate_satellite_v1_views=True),
    )

    # One v0 + one v1 file per standard satellite.
    assert plan.by_entity_type["satellite"] == len(standard_sats) * 2


def test_sqlmesh_plan_excludes_reference_hubs(django_setup):
    from engine.services.export.models import HashkeyDefinition, HubDefinition, ProjectExport
    from engine.services.generation.stages.plan import build_plan
    from engine.services.generation.types import GenerationOptions

    export = ProjectExport(
        project_name="test",
        hubs=[
            HubDefinition(
                hub_name="hub_ref",
                hub_type="reference",
                hashkey=HashkeyDefinition(hashkey_name="hk_ref", business_keys=[]),
                business_key_columns=[],
                source_tables=[],
            )
        ],
    )
    plan, _, _ = build_plan(
        project_export=export,
        output_type="sqlmesh",
        options=GenerationOptions(),
    )
    assert plan.by_entity_type.get("hub", 0) == 0


def test_sqlmesh_plan_excludes_non_historized_links(django_setup):
    from engine.services.export.models import (
        HashkeyDefinition,
        LinkDefinition,
        ProjectExport,
    )
    from engine.services.generation.stages.plan import build_plan
    from engine.services.generation.types import GenerationOptions

    export = ProjectExport(
        project_name="test",
        links=[
            LinkDefinition(
                link_name="lnk_nh",
                link_type="non_historized",
                hashkey=HashkeyDefinition(hashkey_name="hk_nh", business_keys=[]),
                hub_references=[],
                foreign_hashkeys=[],
                payload_columns=[],
                source_tables=[],
            )
        ],
    )
    plan, _, _ = build_plan(
        project_export=export,
        output_type="sqlmesh",
        options=GenerationOptions(),
    )
    assert plan.by_entity_type.get("link", 0) == 0


def test_sqlmesh_plan_files_planned_equals_sum_of_counts(django_setup, project_export):
    from engine.services.generation.stages.plan import build_plan
    from engine.services.generation.types import GenerationOptions

    plan, _, _ = build_plan(
        project_export=project_export,
        output_type="sqlmesh",
        options=GenerationOptions(),
    )

    assert plan.files_planned == sum(plan.by_entity_type.values())
