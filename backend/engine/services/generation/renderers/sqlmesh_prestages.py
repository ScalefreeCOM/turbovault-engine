"""
Pre-stage handling for SQLMesh output.

A pre-stage is a model of the dbt project: the dbt project maintains it and
TurboVault generates nothing for it. A SQLMesh project has no such model to
read, so SQLMesh output can't load from pre-stages. This module works out,
before anything is rendered, what is left out because of that:

- every stage that reads a pre-stage;
- the hubs, links and satellites loaded from those stages.

Links and satellites whose hub or parent is skipped follow from the
renderer's own checks. One warning is reported per pre-stage and one per
skipped entity, so the generated project stays runnable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.services.export.models import ProjectExport
from engine.services.generation.errors import Code, make_issue
from engine.services.generation.types import EntityRef, Issue


@dataclass(frozen=True)
class PrestageSkips:
    """Everything SQLMesh output leaves out because of pre-stages."""

    stages: frozenset[str] = frozenset()
    """Stages that read a pre-stage."""
    entities: dict[tuple[str, str], str] = field(default_factory=dict)
    """(entity type, name) -> the pre-stage's stage the entity loads from."""
    issues: list[Issue] = field(default_factory=list)
    """One warning per pre-stage."""

    def stage_of(self, entity_type: str, name: str) -> str | None:
        """The pre-stage's stage *name* loads from, if it is skipped."""
        return self.entities.get((entity_type, name))


def plan_prestage_skips(export: ProjectExport) -> PrestageSkips:
    """Find what SQLMesh output must leave out because of pre-stages."""
    if not export.prestages:
        return PrestageSkips()

    stages = frozenset(
        stage.stage_name for stage in export.stages if stage.prestage_model
    )
    issues = [
        make_issue(
            severity="warning",
            code=Code.SQLMESH_UNSUPPORTED_PRESTAGE,
            stage="render",
            message=(
                f"Pre-stage '{prestage.model_name}' is a model of the dbt "
                "project, which SQLMesh output can't read. Its stage and the "
                "hubs, links and satellites loaded from it are skipped."
            ),
            entity=EntityRef(type="prestage", name=prestage.model_name),
            suggestion=(
                "Generate dbt output for this project, or create the pre-stage's "
                "data as a table or view and describe it as a physical source table."
            ),
        )
        for prestage in export.prestages
    ]

    entities: dict[tuple[str, str], str] = {}
    for hub in export.hubs:
        for src in hub.source_tables:
            if src.stage_name in stages:
                entities[("hub", hub.hub_name)] = src.stage_name
                break
    for link in export.links:
        for src in link.source_tables:
            if src.stage_name in stages:
                entities[("link", link.link_name)] = src.stage_name
                break
    for sat in export.satellites:
        if sat.stage_name in stages:
            entities[("satellite", sat.satellite_name)] = sat.stage_name

    return PrestageSkips(stages=stages, entities=entities, issues=issues)


def prestage_dependent_warning(
    entity_type: str, name: str, group: str | None, stage_name: str
) -> Issue:
    """Warning Issue for a hub, link or satellite loaded from a pre-stage."""
    return make_issue(
        severity="warning",
        code=Code.SQLMESH_PRESTAGE_DEPENDENT_SKIPPED,
        stage="render",
        message=(
            f"{entity_type.capitalize()} '{name}' was skipped because it loads "
            f"from stage '{stage_name}', which reads a pre-stage: a model of the "
            "dbt project, which SQLMesh output can't read."
        ),
        entity=EntityRef(type=entity_type, name=name, group=group),
    )
