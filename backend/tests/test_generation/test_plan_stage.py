"""Unit tests for the plan stage."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.django_db


def test_dbt_plan_counts_two_files_per_entity(django_setup, project_export):
    from engine.services.generation.stages.plan import build_plan
    from engine.services.generation.types import GenerationOptions

    plan, _, issues = build_plan(
        project_export=project_export,
        output_type="dbt",
        options=GenerationOptions(),
    )

    # Each hub contributes one SQL + one YAML file; same for links and sats.
    if project_export.hubs:
        assert plan.by_entity_type["hub"] == len(project_export.hubs) * 2
    if project_export.links:
        assert plan.by_entity_type["link"] == len(project_export.links) * 2
    assert plan.files_planned > 0
    assert not [i for i in issues if i.severity == "error"]


def test_json_plan_is_a_single_artifact(django_setup, project_export):
    from engine.services.generation.stages.plan import build_plan
    from engine.services.generation.types import GenerationOptions

    plan, _, _ = build_plan(
        project_export=project_export,
        output_type="json",
        options=GenerationOptions(),
    )
    # One artifact regardless of how many entities are included.
    assert plan.files_planned == 1


def test_plan_empty_project_emits_info(django_setup, project_export):
    from engine.services.generation.stages.plan import build_plan
    from engine.services.generation.types import (
        EntityRef,
        EntitySelection,
        GenerationOptions,
    )

    # Force the plan empty via an impossible selection.
    options = GenerationOptions(
        entity_selection=EntitySelection(
            only_entities=[EntityRef(type="hub", name="__nonexistent__")],
        ),
    )
    plan, _, issues = build_plan(
        project_export=project_export,
        output_type="dbt",
        options=options,
    )
    # No user-facing entities survive the filter (hubs / links / sats /
    # pits / ref tables); only infrastructure files may remain in the
    # plan. The "empty_project" info issue should still fire.
    for kind in ("hub", "link", "satellite", "pit", "reference_table"):
        assert plan.by_entity_type.get(kind, 0) == 0
    assert any(i.code == "plan.empty_project" for i in issues)
    assert all(i.severity in ("info", "warning") for i in issues)


def test_selection_filters_project_export(django_setup, project_export):
    """An `only_entities` selection produces a filtered ProjectExport that
    contains only the explicitly selected entities."""
    from engine.services.generation.stages.plan import build_plan
    from engine.services.generation.types import (
        EntityRef,
        EntitySelection,
        GenerationOptions,
    )

    if not project_export.hubs:
        pytest.skip("Sample export has no hubs to select")

    target = project_export.hubs[0]
    options = GenerationOptions(
        entity_selection=EntitySelection(
            only_entities=[EntityRef(type="hub", name=target.hub_name)],
        ),
    )
    _, filtered, _ = build_plan(
        project_export=project_export,
        output_type="dbt",
        options=options,
    )
    assert len(filtered.hubs) == 1
    assert filtered.hubs[0].hub_name == target.hub_name
    assert filtered.links == []
    assert filtered.satellites == []
