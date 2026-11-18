"""
The dbt models one entity generates, rendered in memory.

For the admin's "Generated dbt models" view: each model an entity becomes,
with the path generation writes it to and its ``config()`` block, rendered by
the same stages as a real generation (build, plan, render) with the
project's settings and templates. Nothing is written and no generation run
is recorded. Stored model outputs are marked; everything else is derived.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

# Entities a generation can select directly; the others (source tables,
# snapshot controls) are rendered with the whole project.
_SELECTABLE = {
    "Hub": "hub",
    "Link": "link",
    "Satellite": "satellite",
    "PIT": "pit",
    "ReferenceTable": "reference_table",
}


@dataclass(frozen=True)
class GeneratedModel:
    """One dbt model of an entity, as generation writes it."""

    kind: str
    model_name: str
    # The model's .sql file relative to the dbt project; None when nothing is
    # generated for it (a pre-stage is the dbt project's own model)
    path: str | None
    # The stored model output's fields that are set; empty: all derived
    stored: tuple[str, ...] = field(default_factory=tuple)
    # The model's config() call as generated ("" without one)
    config_block: str = ""


def generated_models(entity: Any) -> list[GeneratedModel]:
    """The dbt models ``entity`` generates, in generation's order of kinds.

    Raises what generation raises for a project it can't render (an invalid
    config.yml, ...); the caller shows it.
    """
    from engine.models import ModelOutput
    from engine.services.export.model_outputs import ModelOutputs
    from engine.services.runtime_config import resolve_runtime_config

    project = entity.project
    config = resolve_runtime_config(project, None)
    outputs = ModelOutputs(project, config)
    stored = {
        row.kind: row
        for row in ModelOutput.objects.filter(
            project=project, framework=ModelOutput.Framework.DBT
        )
        if row.entity_field and getattr(row, f"{row.entity_field}_id") == entity.pk
    }
    models = _models_of(entity, outputs)
    files = _rendered_files(entity, config)

    result = []
    for kind, name in models:
        row = stored.get(kind)
        sql = files.get(name)
        result.append(
            GeneratedModel(
                kind=kind,
                model_name=name,
                path=sql[0] if sql else None,
                stored=_stored_fields(row) if row else (),
                config_block=_config_block(sql[1]) if sql else "",
            )
        )
    return result


def _models_of(entity: Any, outputs: Any) -> list[tuple[str, str]]:
    """(kind, model name) of each model the entity can generate."""
    kind = type(entity).__name__
    if kind == "SourceTable":
        models = [("stage", outputs.stage(entity).model_name)]
        if entity.table_type == "prestage":
            models.insert(0, ("prestage", outputs.prestage_name(entity)))
        return models
    if kind in ("Hub", "Link"):
        own = "hub" if kind == "Hub" else "link"
        models = [(own, getattr(outputs, own)(entity).model_name)]
        if entity.create_effectivity_satellite:
            models.append(
                (
                    "effectivity_satellite",
                    outputs.effectivity_satellite(entity).model_name,
                )
            )
        if entity.create_record_tracking_satellite:
            models.append(
                (
                    "record_tracking_satellite",
                    outputs.record_tracking_satellite(entity).model_name,
                )
            )
        return models
    if kind == "Satellite":
        return [
            ("satellite_v0", outputs.satellite_v0(entity).model_name),
            ("satellite_v1", outputs.satellite_v1(entity).model_name),
        ]
    if kind == "PIT":
        return [("pit", outputs.pit(entity).model_name)]
    if kind == "ReferenceTable":
        return [("reference_table", outputs.reference_table(entity).model_name)]
    if kind == "SnapshotControlTable":
        return [
            ("snapshot_control_v0", outputs.snapshot_control_v0(entity).model_name),
            ("snapshot_control_v1", outputs.snapshot_control_v1(entity).model_name),
        ]
    return []


def _rendered_files(entity: Any, config: Any) -> dict[str, tuple[str, str]]:
    """Rendered .sql files by model name: (path, content)."""
    from engine.services.generation.stages.build import build_export
    from engine.services.generation.stages.plan import build_plan
    from engine.services.generation.stages.render import render
    from engine.services.generation.types import (
        EntityRef,
        EntitySelection,
        GenerationOptions,
    )

    selectable = _SELECTABLE.get(type(entity).__name__)
    selection = None
    if selectable:
        name_field = {
            "hub": "hub_physical_name",
            "link": "link_physical_name",
            "satellite": "satellite_physical_name",
            "pit": "pit_physical_name",
            "reference_table": "reference_table_physical_name",
        }[selectable]
        selection = EntitySelection(
            only_entities=[EntityRef(type=selectable, name=getattr(entity, name_field))]
        )
    options = GenerationOptions(entity_selection=selection, return_content=True)
    project_export = build_export(
        project=entity.project, runtime_config=config, options=options
    )
    _plan, filtered, _issues = build_plan(
        project_export=project_export,
        output_type="dbt",
        options=options,
        generate_profiles_yml=False,
    )
    artifacts, _render_issues = render(
        project_export=filtered,
        output_type="dbt",
        runtime_config=config,
        options=options,
    )
    files = {}
    for artifact in artifacts:
        if artifact.kind == "sql_model" and artifact.path:
            path = PurePosixPath(artifact.path)
            files[path.stem] = (path.as_posix(), artifact.content or "")
    return files


def _stored_fields(row: Any) -> tuple[str, ...]:
    names = (
        "model_name",
        "folder",
        "alias",
        "schema_name",
        "database_name",
        "materialized",
        "tags",
        "config",
    )
    return tuple(name for name in names if getattr(row, name) not in (None, "", {}))


def _config_block(sql: str) -> str:
    """The model's config() call: from "{{ config(" to ") }}" on a line of
    its own (values such as hooks may contain "}}" themselves)."""
    start = sql.find("{{ config(")
    if start < 0:
        return ""
    end = sql.find("\n) }}", start)
    return sql[start : end + len("\n) }}")] if end >= 0 else ""
