"""
Leave entities with invalid names out of a ``best_effort`` import (#450).

The generated code relies on Data Vault names following the naming rules, so
an import doesn't store an entity whose name breaks them
(``entity.invalid_name``) or differs from another only in case
(``entity.name_case_collision``). It is planned as a skip with reason
``invalid_name``; every entity that depends on it is left out too, with an
``entity.depends_on_skipped`` warning, as the resolver does for entities that
can't be resolved:

- a Hub takes the Links connecting it, its Satellites, the reference tables
  built on it and the PITs tracking it;
- a Link its Satellites and the PITs tracking it;
- a Satellite the PITs and reference tables that read it;
- a snapshot control the PITs and reference tables that use it.

Source and display name errors are reported only: generation leaves their
output out (``engine.services.generation.name_skips``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from engine.services.imports.domain import DomainModel, DSkipped
from engine.services.imports.errors import Code, make_issue
from engine.services.imports.types import EntityRef, EntityType, Issue
from engine.services.imports.validation.names import (
    DV_ENTITY_DICTS,
    dv_entities,
    entity_name,
)

_NAME_ERROR_CODES = frozenset(
    {Code.ENTITY_INVALID_NAME, Code.ENTITY_NAME_CASE_COLLISION}
)

_LABELS: dict[str, str] = {
    "hub": "Hub",
    "link": "Link",
    "satellite": "Satellite",
    "pit": "PIT",
    "reference_table": "Reference table",
    "snapshot_control": "Snapshot control",
}

# (entity type, name) -> what it depends on that is left out (None: itself)
_LeftOut = dict[tuple[str, str], str | None]


def leave_out_invalid_names(
    domain: DomainModel, issues: Iterable[Issue]
) -> list[Issue]:
    """Remove entities with name errors, and their dependents, from ``domain``.

    Records them in ``domain.skipped`` so the planner plans them as skips and
    ``replace_all`` keeps the project's copies. Returns the
    ``entity.depends_on_skipped`` warnings of the dependents.
    """
    entities = dv_entities(domain)
    names = {(entity_type, name) for entity_type, name, _ in entities}
    left_out: _LeftOut = {}
    for issue in issues:
        if issue.severity != "error" or issue.code not in _NAME_ERROR_CODES:
            continue
        if issue.entity is not None:
            key = (issue.entity.type, issue.entity.name)
            if key in names:
                left_out.setdefault(key, None)
    if not left_out:
        return []

    _cascade(entities, left_out)
    _remove(domain, left_out)
    return [
        _depends_on_skipped(entity_type, name, cause)
        for (entity_type, name), cause in left_out.items()
        if cause is not None
    ]


def _cascade(entities: list[tuple[EntityType, str, Any]], left_out: _LeftOut) -> None:
    """Add every dependent of a left-out entity until nothing changes."""
    changed = True
    while changed:
        changed = False
        for entity_type, name, entity in entities:
            if (entity_type, name) in left_out:
                continue
            cause = _left_out_dependency(entity_type, entity, left_out)
            if cause is not None:
                left_out[(entity_type, name)] = cause
                changed = True


def _left_out_dependency(
    entity_type: str, entity: Any, left_out: _LeftOut
) -> str | None:
    """What ``entity`` depends on that is left out, as a label, or None."""
    dependencies: list[tuple[str, str | None]] = []
    if entity_type == "link":
        dependencies = [
            ("hub", reference.hub_physical_name) for reference in entity.hub_references
        ]
    elif entity_type == "satellite":
        dependencies = [(entity.parent_entity_type, entity.parent_entity_name)]
    elif entity_type == "reference_table":
        dependencies = [
            ("hub", entity.reference_hub_name),
            ("snapshot_control", entity.snapshot_control_name),
            *(
                ("satellite", assignment.satellite_name)
                for assignment in entity.satellite_assignments
            ),
        ]
    elif entity_type == "pit":
        dependencies = [
            (entity.tracked_entity_type, entity.tracked_entity_name),
            ("snapshot_control", entity.snapshot_control_name),
            *(("satellite", name) for name in entity.satellite_names),
        ]
    for dependency_type, dependency_name in dependencies:
        if dependency_name and (dependency_type, dependency_name) in left_out:
            return f"{_LABELS[dependency_type]} '{dependency_name}'"
    return None


def _remove(domain: DomainModel, left_out: _LeftOut) -> None:
    """Drop the left-out entities (and their identifier keys) from ``domain``."""
    for entity_type, attribute in DV_ENTITY_DICTS:
        entities: dict[str, Any] = getattr(domain, attribute)
        for key in [
            key
            for key, entity in entities.items()
            if (entity_type, entity_name(entity)) in left_out
        ]:
            del entities[key]
    for (entity_type, name), cause in left_out.items():
        domain.skipped.setdefault(
            (entity_type, name),
            DSkipped(
                entity_type=entity_type,
                name=name,
                reason="invalid_name" if cause is None else "depends_on_skipped",
            ),
        )


def _depends_on_skipped(entity_type: str, name: str, cause: str) -> Issue:
    return make_issue(
        severity="warning",
        code=Code.ENTITY_DEPENDS_ON_SKIPPED,
        stage="resolve",
        message=(
            f"{_LABELS[entity_type]} '{name}' is left out because {cause} has a "
            "name error or is left out."
        ),
        entity=EntityRef(type=entity_type, name=name),  # type: ignore[arg-type]
        suggestion="Fix the name error reported for it and import again.",
    )
