"""Unit tests for the validate stage adapter."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.django_db


def test_validate_returns_structured_issues(django_setup, project_export):
    """Each ValidationError/Warning is wrapped in a structured Issue with
    `stage='validate'` and a dot-separated stable code."""
    from engine.services.generation.stages.validate import validate
    from engine.services.generation.types import GenerationOptions

    issues = validate(project_export=project_export, options=GenerationOptions())

    for issue in issues:
        assert issue.stage == "validate"
        # New codes are dot-separated; the adapter falls back to the
        # legacy alphanumeric code only when an unmapped legacy code is
        # encountered. Either way the code must be non-empty.
        assert issue.code
        assert issue.severity in ("error", "warning", "info")


def test_validate_skipped_when_option_set(django_setup, project_export):
    from engine.services.generation.stages.validate import validate
    from engine.services.generation.types import GenerationOptions

    issues = validate(
        project_export=project_export,
        options=GenerationOptions(skip_validation=True),
    )
    assert issues == []


def test_validate_filters_by_selection(django_setup, project_export):
    """When entity_selection is set, issues for non-selected entities are
    dropped from the report."""
    from engine.services.generation.stages.validate import validate
    from engine.services.generation.types import (
        EntityRef,
        EntitySelection,
        GenerationOptions,
    )

    # Run without selection first to see what issues the sample export
    # surfaces, then pick a single entity and confirm the selection
    # narrows the issue list.
    full_issues = validate(
        project_export=project_export, options=GenerationOptions()
    )
    if not full_issues or not any(i.entity for i in full_issues):
        pytest.skip("Sample export validates clean — no selection to compare against")

    target_ref = next(i.entity for i in full_issues if i.entity is not None)
    selection = EntitySelection(
        only_entities=[EntityRef(type=target_ref.type, name=target_ref.name)],
    )
    filtered = validate(
        project_export=project_export,
        options=GenerationOptions(entity_selection=selection),
    )

    # Every emitted issue should target the selected entity (entity-less
    # issues are allowed; the filter only drops issues with a mismatching
    # entity).
    for issue in filtered:
        if issue.entity is not None:
            assert (issue.entity.type, issue.entity.name) == (
                target_ref.type,
                target_ref.name,
            )
