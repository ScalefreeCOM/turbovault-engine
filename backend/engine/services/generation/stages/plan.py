"""
Stage 3 — Plan.

Walks the `ProjectExport`, applies `options.entity_selection`, and
returns:

  1. A `GenerationPlan` with per-entity-type counts of what the pipeline
     intends to produce.
  2. A filtered `ProjectExport` containing only the selected entities,
     ready to hand to the render stage.

For `output_type == "dbt"` the plan counts each model file the renderer
will emit (one or two per entity depending on satellite v1 views,
plus 3 project-level files: dbt_project.yml, packages.yml, sources.yml).
For `output_type in {"json", "dbml"}` the plan is trivial — a single
artifact — regardless of how many entities are involved.
"""

from __future__ import annotations

from engine.services.export.models import ProjectExport
from engine.services.generation.errors import Code, make_issue
from engine.services.generation.types import (
    EntityRef,
    GenerationOptions,
    GenerationPlan,
    Issue,
    OutputType,
)


def build_plan(
    *,
    project_export: ProjectExport,
    output_type: OutputType,
    options: GenerationOptions,
) -> tuple[GenerationPlan, ProjectExport, list[Issue]]:
    """Return (plan, filtered_export, issues)."""
    issues: list[Issue] = []
    filtered = _filter_export(project_export, options)

    if output_type == "dbt":
        by_type = _count_dbt(filtered, options)
    elif output_type in ("json", "dbml"):
        by_type = _count_single_artifact(filtered)
    else:  # pragma: no cover - guarded by Literal
        return (
            GenerationPlan(output_type=output_type, files_planned=0, by_entity_type={}),
            filtered,
            [
                make_issue(
                    severity="error",
                    code=Code.PLAN_UNSUPPORTED_OUTPUT_TYPE,
                    stage="plan",
                    message=f"Unsupported output_type: {output_type}",
                )
            ],
        )

    files_planned = (
        sum(by_type.values())
        if output_type == "dbt"
        else 1
        if any(by_type.values())
        else 0
    )

    # "Empty project" is judged by USER-FACING entities (hubs / links /
    # satellites / pits / reference tables), not by infrastructure files
    # like project.yml or stage models. A filter that excludes every
    # user entity should still emit this info-severity hint even though
    # the plan technically writes a few infra files.
    user_entity_types = {"hub", "link", "satellite", "pit", "reference_table"}
    user_files = sum(
        count for kind, count in by_type.items() if kind in user_entity_types
    )
    if user_files == 0:
        issues.append(
            make_issue(
                severity="info",
                code=Code.PLAN_EMPTY_PROJECT,
                stage="plan",
                message=(
                    "Nothing to generate — the project (or current selection) "
                    "contains no eligible entities."
                ),
                suggestion=(
                    "Widen the selection or add entities to the project."
                ),
            )
        )

    return (
        GenerationPlan(
            output_type=output_type,
            files_planned=files_planned,
            by_entity_type=by_type,
        ),
        filtered,
        issues,
    )


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def _filter_export(
    project_export: ProjectExport, options: GenerationOptions
) -> ProjectExport:
    """Return a copy of `project_export` containing only selected entities.

    Sources, stages, and snapshot controls are always passed through —
    they are infrastructure-level, not user-selectable. (The render stage
    will further prune sources that have no surviving consumers later if
    needed.)
    """
    selection = options.entity_selection
    if selection is None or selection.is_unrestricted():
        return project_export

    def keep(type_: str, name: str, group: str | None) -> bool:
        return selection.matches(EntityRef(type=type_, name=name, group=group))

    return project_export.model_copy(
        update={
            "hubs": [h for h in project_export.hubs if keep("hub", h.hub_name, h.group)],
            "links": [
                l for l in project_export.links if keep("link", l.link_name, l.group)
            ],
            "satellites": [
                s
                for s in project_export.satellites
                if keep("satellite", s.satellite_name, s.group)
            ],
            "pits": [
                p for p in project_export.pits if keep("pit", p.pit_name, p.group)
            ],
            "reference_tables": [
                rt
                for rt in project_export.reference_tables
                if keep("reference_table", rt.table_name, rt.group)
            ],
        }
    )


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------


def _count_dbt(
    project_export: ProjectExport, options: GenerationOptions
) -> dict[str, int]:
    """Count the SQL + YAML files the dbt renderer will produce per entity type.

    Two files per entity (sql + yaml) plus an extra v1 view for standard
    satellites when `generate_satellite_v1_views` is True. Project-level
    files (dbt_project.yml, packages.yml, sources.yml) are counted under
    `project`.
    """
    counts: dict[str, int] = {}

    # Project-level files: dbt_project.yml, packages.yml, sources.yml.
    counts["project"] = 3 if project_export.sources else 2

    # Stages: one sql + one yml per stage.
    if project_export.stages:
        counts["stage"] = len(project_export.stages) * 2

    if project_export.hubs:
        counts["hub"] = len(project_export.hubs) * 2

    if project_export.links:
        counts["link"] = len(project_export.links) * 2

    if project_export.satellites:
        # _v0 (sql + yml) plus optional _v1 view (sql + yml).
        sat_files = len(project_export.satellites) * 2
        if options.generate_satellite_v1_views:
            sat_files += sum(
                2
                for s in project_export.satellites
                if s.satellite_type in ("standard", "multi_active")
            )
        counts["satellite"] = sat_files

    if project_export.pits:
        counts["pit"] = len(project_export.pits) * 2

    if project_export.reference_tables:
        counts["reference_table"] = len(project_export.reference_tables) * 2

    if project_export.snapshot_controls:
        counts["snapshot_control"] = len(project_export.snapshot_controls) * 2

    return counts


def _count_single_artifact(project_export: ProjectExport) -> dict[str, int]:
    """Single-string outputs (JSON, DBML) — one artifact regardless of size.

    We still record per-type entity counts here so the planner row in the
    report has something meaningful to display ("planning to serialize
    3 hubs, 2 links, …") even though only one file lands on disk.
    """
    return {
        "hub": len(project_export.hubs),
        "link": len(project_export.links),
        "satellite": len(project_export.satellites),
        "pit": len(project_export.pits),
        "reference_table": len(project_export.reference_tables),
        "snapshot_control": len(project_export.snapshot_controls),
        "stage": len(project_export.stages),
        "source": len(project_export.sources),
    }
