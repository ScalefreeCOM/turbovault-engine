"""
The dbt models an entity or a whole project generates, rendered in memory.

For the admin's "Generated dbt models" view and for callers such as Studio:
each model an entity becomes, with the path generation writes it to and its
``config()`` block, rendered by the same stages as a real generation (build,
plan, render). Nothing is written and no generation run is recorded. Stored
model outputs are marked; everything else is derived.

By default the project's own settings (``config.yml``) and the templates in
the database apply. A caller that generates with settings and templates of
its own passes the ``runtime_config`` and ``options`` it gives
``generate()``, so the preview matches its generation (the options' entity
selection doesn't apply here: the preview selects).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.models import Project
    from engine.services.generation.types import GeneratedArtifact, GenerationOptions
    from engine.services.runtime_config import EngineRuntimeConfig

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
    # generated for it (a pre-stage is the dbt project's own model; a v1 view
    # switched off; an entity the plan leaves out)
    path: str | None
    # The stored model output's fields that are set; empty: all derived
    stored: tuple[str, ...] = field(default_factory=tuple)
    # The model's config() call as generated ("" without one)
    config_block: str = ""


@dataclass(frozen=True)
class EntityModels:
    """The dbt models one entity of a project generates."""

    # The entity's field on ModelOutput: "source_table", "hub", "link",
    # "satellite", "pit", "reference_table" or "snapshot_control"
    entity_type: str
    entity_id: int
    # The entity's physical name (a snapshot control's name)
    entity_name: str
    models: tuple[GeneratedModel, ...]


def generated_models(
    entity: Any,
    *,
    runtime_config: EngineRuntimeConfig | None = None,
    options: GenerationOptions | None = None,
) -> list[GeneratedModel]:
    """The dbt models ``entity`` generates, in generation's order of kinds.

    ``runtime_config`` defaults to the project's settings, ``options`` to
    ``GenerationOptions()``. Raises what generation raises for a project it
    can't render (an invalid config.yml, ...); the caller shows it.
    """
    from engine.services.export.model_outputs import ModelOutputs

    project = entity.project
    config = _config(project, runtime_config)
    outputs = ModelOutputs(project, config)
    stored = _stored_rows(project)
    files = _sql_files(_render(project, config, options, _selection(entity)))
    return _models(entity, outputs, stored, files)


def project_models(
    project: Project,
    *,
    runtime_config: EngineRuntimeConfig | None = None,
    options: GenerationOptions | None = None,
) -> list[EntityModels]:
    """Every dbt model ``project`` generates, by entity.

    Renders the whole project once. Entities come in generation's order of
    layers (source tables, snapshot controls, hubs, links, satellites, PITs,
    reference tables), each type by name; entities that generate nothing are
    left out. ``runtime_config`` and ``options`` work as in
    ``generated_models()``.
    """
    from engine.services.export.model_outputs import ModelOutputs

    config = _config(project, runtime_config)
    outputs = ModelOutputs(project, config)
    stored = _stored_rows(project)
    files = _sql_files(_render(project, config, options, None))
    result = []
    for entity_type, entity in _project_entities(project):
        models = _models(entity, outputs, stored, files)
        if models:
            result.append(
                EntityModels(
                    entity_type=entity_type,
                    entity_id=entity.pk,
                    entity_name=_entity_name(entity_type, entity),
                    models=tuple(models),
                )
            )
    return result


@dataclass(frozen=True)
class ProjectFiles:
    """The dbt project files a generation writes into an empty folder."""

    dbt_project_yml: str
    packages_yml: str


def project_files(
    project: Project,
    *,
    runtime_config: EngineRuntimeConfig | None = None,
    options: GenerationOptions | None = None,
) -> ProjectFiles:
    """``dbt_project.yml`` and ``packages.yml`` as generation writes them.

    Rendered with the whole project, since both depend on it (the vars, the
    folders the models go to, whether it has pre-stages). A caller that keeps
    a hand-edited ``dbt_project.yml`` can start it from this one.
    ``runtime_config`` and ``options`` work as in ``generated_models()``; an
    empty string means the template wrote nothing.
    """
    config = _config(project, runtime_config)
    contents = {
        artifact.kind: artifact.content or ""
        for artifact in _render(project, config, options, None)
        if artifact.kind in ("project_yml", "packages_yml")
    }
    return ProjectFiles(
        dbt_project_yml=contents.get("project_yml", ""),
        packages_yml=contents.get("packages_yml", ""),
    )


def _config(
    project: Project, runtime_config: EngineRuntimeConfig | None
) -> EngineRuntimeConfig:
    from engine.services.runtime_config import resolve_runtime_config

    return resolve_runtime_config(project, runtime_config)


def _stored_rows(project: Project) -> dict[tuple[str, object, str], Any]:
    """The project's stored dbt model outputs by (entity field, entity id, kind)."""
    from engine.models import ModelOutput

    rows: dict[tuple[str, object, str], Any] = {}
    for row in ModelOutput.objects.filter(
        project=project, framework=ModelOutput.Framework.DBT
    ):
        if row.entity_field:
            entity_pk = getattr(row, f"{row.entity_field}_id")
            rows[(row.entity_field, entity_pk, row.kind)] = row
    return rows


def _models(
    entity: Any,
    outputs: Any,
    stored: dict[tuple[str, object, str], Any],
    files: dict[str, tuple[str, str]],
) -> list[GeneratedModel]:
    entity_type = _ENTITY_TYPES[type(entity).__name__]
    result = []
    for kind, name in _models_of(entity, outputs):
        row = stored.get((entity_type, entity.pk, kind))
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


# ModelOutput's entity field of each entity class.
_ENTITY_TYPES = {
    "SourceTable": "source_table",
    "Hub": "hub",
    "Link": "link",
    "Satellite": "satellite",
    "PIT": "pit",
    "ReferenceTable": "reference_table",
    "SnapshotControlTable": "snapshot_control",
}

# The physical name field of each entity type ("name" for snapshot controls).
_NAME_FIELDS = {
    "source_table": "physical_table_name",
    "hub": "hub_physical_name",
    "link": "link_physical_name",
    "satellite": "satellite_physical_name",
    "pit": "pit_physical_name",
    "reference_table": "reference_table_physical_name",
    "snapshot_control": "name",
}


def _entity_name(entity_type: str, entity: Any) -> str:
    return str(getattr(entity, _NAME_FIELDS[entity_type]))


def _project_entities(project: Project) -> list[tuple[str, Any]]:
    """(entity type, entity) of every entity that can generate a model."""
    from engine.models import (
        PIT,
        Hub,
        Link,
        ReferenceTable,
        Satellite,
        SnapshotControlTable,
        SourceTable,
    )

    querysets = (
        ("source_table", SourceTable.objects.select_related("source_system")),
        ("snapshot_control", SnapshotControlTable.objects.all()),
        ("hub", Hub.objects.all()),
        ("link", Link.objects.all()),
        ("satellite", Satellite.objects.all()),
        ("pit", PIT.objects.all()),
        ("reference_table", ReferenceTable.objects.all()),
    )
    entities: list[tuple[str, Any]] = []
    for entity_type, queryset in querysets:
        rows = queryset.filter(project=project).order_by(_NAME_FIELDS[entity_type])
        entities.extend((entity_type, row) for row in rows)
    return entities


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


def _selection(entity: Any) -> Any:
    """The generation's entity selection for ``entity``: None renders the
    whole project (source tables and snapshot controls can't be selected)."""
    from engine.services.generation.types import EntityRef, EntitySelection

    selectable = _SELECTABLE.get(type(entity).__name__)
    if not selectable:
        return None
    name = getattr(entity, _NAME_FIELDS[selectable])
    return EntitySelection(only_entities=[EntityRef(type=selectable, name=name)])


def _render(
    project: Project,
    config: EngineRuntimeConfig,
    options: GenerationOptions | None,
    selection: Any,
) -> list[GeneratedArtifact]:
    """The generation's artifacts, rendered in memory for ``selection``."""
    from engine.services.generation.stages.build import build_export
    from engine.services.generation.stages.plan import build_plan
    from engine.services.generation.stages.render import render
    from engine.services.generation.types import GenerationOptions

    options = (options or GenerationOptions()).model_copy(
        update={"entity_selection": selection, "return_content": True}
    )
    project_export = build_export(
        project=project, runtime_config=config, options=options
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
    return artifacts


def _sql_files(artifacts: list[GeneratedArtifact]) -> dict[str, tuple[str, str]]:
    """Rendered .sql files by model name: (path, content)."""
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
