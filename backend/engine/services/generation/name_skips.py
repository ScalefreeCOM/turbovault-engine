"""
Leave entities with name errors out of a ``best_effort`` generation (#450).

The templates don't escape Data Vault names: they rely on name validation
(``validate.name.*``). ``fail_fast`` stops on any such error; ``best_effort``
generates the rest, so the entities with a name error, and every entity that
depends on one, are left out here, before the plan. Each left-out entity gets
a ``validate.name.entity_left_out`` warning naming the cause.

What a name error on each kind of entity leaves out:

- a source system (schema, database or display name): all its tables;
- a source table (table or column name), or a stage (derived column, prejoin
  alias): the table, i.e. its ``sources.yml`` entry, pre-stage and stage;
- a subject area (display name): every entity of that group;
- a Hub, Link, Satellite, PIT, reference table or snapshot control: itself;
- a project schema: everything, see ``blocks_generation``.

Then, until nothing changes: a left-out table takes the stages that prejoin
it and every Hub, Link and Satellite loaded from it; a Hub its Satellites,
Links, reference tables and PITs; a Link its Satellites and PITs; a Satellite
the PITs and reference tables that read it; a snapshot control the PITs and
reference tables that use it. Stages drop the hash keys and hash diffs of
left-out entities.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from engine.services.export.models import (
    PITDefinition,
    ProjectExport,
    ReferenceTableDefinition,
    StageDefinition,
)
from engine.services.generation.errors import Code, make_issue
from engine.services.generation.types import EntityRef, Issue

_NAME_CODE_PREFIX = "validate.name."

# Entity types whose name errors leave out the entity of that name.
_ENTITY_TYPES = ("hub", "link", "satellite", "pit", "reference_table")

# A source table: (source system name, table name).
TableKey = tuple[str, str]


def is_name_error(issue: Issue) -> bool:
    """Whether ``issue`` is a name error the templates rely on."""
    return issue.severity == "error" and issue.code.startswith(_NAME_CODE_PREFIX)


def blocks_generation(issues: Iterable[Issue]) -> bool:
    """Whether a name error leaves nothing to generate.

    The stage and raw vault schemas go into every model's config, so an
    invalid one stops the run in any error strategy.
    """
    return any(
        is_name_error(issue)
        and issue.location is not None
        and issue.location.entity_type == "project"
        for issue in issues
    )


@dataclass
class _LeftOut:
    """What is left out, and why: entity -> cause (``None``: its own error)."""

    tables: dict[TableKey, str | None] = field(default_factory=dict)
    entities: dict[tuple[str, str], str | None] = field(default_factory=dict)

    def add_table(self, key: TableKey, cause: str | None) -> bool:
        if key in self.tables:
            return False
        self.tables[key] = cause
        return True

    def add(self, entity_type: str, name: str, cause: str | None) -> bool:
        if (entity_type, name) in self.entities:
            return False
        self.entities[(entity_type, name)] = cause
        return True

    def has(self, entity_type: str, name: str | None) -> bool:
        return name is not None and (entity_type, name) in self.entities


def leave_out_name_errors(
    export: ProjectExport, issues: Iterable[Issue]
) -> tuple[ProjectExport, list[Issue]]:
    """The export without entities that have, or depend on, name errors.

    Returns the reduced export and one ``validate.name.entity_left_out``
    warning per left-out entity. Without name errors the export is returned
    unchanged.
    """
    name_errors = [issue for issue in issues if is_name_error(issue)]
    if not name_errors:
        return export, []

    left_out = _LeftOut()
    _add_roots(export, name_errors, left_out)
    if not left_out.tables and not left_out.entities:
        return export, []
    _cascade(export, left_out)
    return _reduced_export(export, left_out), _left_out_issues(left_out)


# ---------------------------------------------------------------------------
# Roots: the entities the name errors are reported on
# ---------------------------------------------------------------------------


def _add_roots(
    export: ProjectExport, name_errors: list[Issue], left_out: _LeftOut
) -> None:
    for issue in name_errors:
        location = issue.location
        if location is None or not location.entity_name:
            continue
        entity_type, name = location.entity_type, location.entity_name
        if entity_type == "source":
            _add_source_root(export, name, left_out)
        elif entity_type == "stage":
            for stage in export.stages:
                if stage.stage_name == name:
                    left_out.add_table(_stage_table(stage), None)
        elif entity_type == "group":
            for kind, entity_name, group in _grouped_entities(export):
                if group == name:
                    left_out.add(kind, entity_name, f"its subject area {name!r}")
        elif entity_type in _ENTITY_TYPES or entity_type == "snapshot_control":
            left_out.add(entity_type, name, None)


def _add_source_root(export: ProjectExport, name: str, left_out: _LeftOut) -> None:
    """A ``source`` issue names a system or ``"system.table"``; system names
    may hold dots themselves, so both are matched exactly."""
    for system in export.sources:
        if system.name == name:
            for table in system.tables:
                left_out.add_table((system.name, table.table_name), None)
            continue
        for table in system.tables:
            if f"{system.name}.{table.table_name}" == name:
                left_out.add_table((system.name, table.table_name), None)


def _grouped_entities(export: ProjectExport) -> Iterable[tuple[str, str, str | None]]:
    yield from (("hub", hub.hub_name, hub.group) for hub in export.hubs)
    yield from (("link", link.link_name, link.group) for link in export.links)
    yield from (
        ("satellite", sat.satellite_name, sat.group) for sat in export.satellites
    )
    yield from (("pit", pit.pit_name, pit.group) for pit in export.pits)
    yield from (
        ("reference_table", ref.table_name, ref.group)
        for ref in export.reference_tables
    )


def _stage_table(stage: StageDefinition) -> TableKey:
    return (stage.source_system, stage.source_table)


# ---------------------------------------------------------------------------
# Cascade to dependents
# ---------------------------------------------------------------------------


def _cascade(export: ProjectExport, left_out: _LeftOut) -> None:
    """Add every dependent of a left-out entity until nothing changes."""
    changed = True
    while changed:
        changed = _cascade_tables(export, left_out)
        changed |= _cascade_entities(export, left_out)


def _cascade_tables(export: ProjectExport, left_out: _LeftOut) -> bool:
    changed = False
    # A stage that prejoins a left-out table can't be built either.
    for stage in export.stages:
        for prejoin in stage.prejoins:
            target = (
                prejoin.target_source_system or stage.source_system,
                prejoin.target_table,
            )
            if target in left_out.tables:
                changed |= left_out.add_table(
                    _stage_table(stage), f"it prejoins {_table_label(target)}"
                )
    for hub in export.hubs:
        for source in hub.source_tables:
            key = (source.source_system, source.source_table)
            if key in left_out.tables:
                changed |= left_out.add(
                    "hub", hub.hub_name, f"its source table {_table_label(key)}"
                )
    for link in export.links:
        for source in link.source_tables:
            key = (source.source_system, source.source_table)
            if key in left_out.tables:
                changed |= left_out.add(
                    "link", link.link_name, f"its source table {_table_label(key)}"
                )
    for sat in export.satellites:
        key = (sat.source_system, sat.source_table)
        if key in left_out.tables:
            changed |= left_out.add(
                "satellite",
                sat.satellite_name,
                f"its source table {_table_label(key)}",
            )
    return changed


def _cascade_entities(export: ProjectExport, left_out: _LeftOut) -> bool:
    changed = False
    for link in export.links:
        for reference in link.hub_references:
            if left_out.has("hub", reference.hub_name):
                changed |= left_out.add(
                    "link", link.link_name, f"hub {reference.hub_name!r}"
                )
    for sat in export.satellites:
        if left_out.has(sat.parent_entity_type, sat.parent_entity):
            changed |= left_out.add(
                "satellite",
                sat.satellite_name,
                f"its parent {sat.parent_entity_type} {sat.parent_entity!r}",
            )
    for ref in export.reference_tables:
        cause = _reference_table_cause(ref, left_out)
        if cause:
            changed |= left_out.add("reference_table", ref.table_name, cause)
    for pit in export.pits:
        cause = _pit_cause(pit, left_out)
        if cause:
            changed |= left_out.add("pit", pit.pit_name, cause)
    return changed


def _reference_table_cause(
    ref: ReferenceTableDefinition, left_out: _LeftOut
) -> str | None:
    if left_out.has("hub", ref.reference_hub_name):
        return f"hub {ref.reference_hub_name!r}"
    if left_out.has("snapshot_control", ref.snapshot_control_table):
        return f"snapshot control {ref.snapshot_control_table!r}"
    for assignment in ref.satellites:
        if left_out.has("satellite", assignment.satellite_name):
            return f"satellite {assignment.satellite_name!r}"
    return None


def _pit_cause(pit: PITDefinition, left_out: _LeftOut) -> str | None:
    if left_out.has(pit.tracked_entity_type, pit.tracked_entity_name):
        return f"its tracked {pit.tracked_entity_type} {pit.tracked_entity_name!r}"
    if left_out.has("snapshot_control", pit.snapshot_control_name):
        return f"snapshot control {pit.snapshot_control_name!r}"
    for satellite in pit.satellites:
        if left_out.has("satellite", satellite):
            return f"satellite {satellite!r}"
    return None


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


def _reduced_export(export: ProjectExport, left_out: _LeftOut) -> ProjectExport:
    def kept(entity_type: str, name: str) -> bool:
        return not left_out.has(entity_type, name)

    sources = []
    for system in export.sources:
        tables = [
            table
            for table in system.tables
            if (system.name, table.table_name) not in left_out.tables
        ]
        if tables:
            sources.append(system.model_copy(update={"tables": tables}))

    stages = [
        _without_left_out_keys(stage, left_out)
        for stage in export.stages
        if _stage_table(stage) not in left_out.tables
    ]
    return export.model_copy(
        update={
            "sources": sources,
            "prestages": [
                prestage
                for prestage in export.prestages
                if (prestage.source_system, prestage.table_name) not in left_out.tables
            ],
            "stages": stages,
            "hubs": [h for h in export.hubs if kept("hub", h.hub_name)],
            "links": [link for link in export.links if kept("link", link.link_name)],
            "satellites": [
                s for s in export.satellites if kept("satellite", s.satellite_name)
            ],
            "pits": [p for p in export.pits if kept("pit", p.pit_name)],
            "reference_tables": [
                r
                for r in export.reference_tables
                if kept("reference_table", r.table_name)
            ],
            "snapshot_controls": [
                c
                for c in export.snapshot_controls
                if not c.name or kept("snapshot_control", c.name)
            ],
        }
    )


def _without_left_out_keys(
    stage: StageDefinition, left_out: _LeftOut
) -> StageDefinition:
    """A kept stage without the hash keys and hash diffs of left-out entities:
    their (possibly invalid) names would otherwise still reach the stage."""
    hashkeys = [
        hashkey
        for hashkey in stage.hashkeys
        if not left_out.has(hashkey.entity_type, hashkey.target_entity)
    ]
    hashdiffs = [
        hashdiff
        for hashdiff in stage.hashdiffs
        if not left_out.has("satellite", hashdiff.satellite_name)
    ]
    if len(hashkeys) == len(stage.hashkeys) and len(hashdiffs) == len(stage.hashdiffs):
        return stage
    update: dict[str, object] = {"hashkeys": hashkeys, "hashdiffs": hashdiffs}
    kept_hashkeys = {hashkey.hashkey_name for hashkey in hashkeys}
    multi_active = stage.multi_active_config
    if (
        multi_active is not None
        and multi_active.main_hashkey_column not in kept_hashkeys
    ):
        update["multi_active_config"] = None
    return stage.model_copy(update=update)


def _left_out_issues(left_out: _LeftOut) -> list[Issue]:
    issues = [
        _left_out_issue(
            "source",
            f"{system}.{table}",
            f"source table {_table_label((system, table))}",
            cause,
        )
        for (system, table), cause in left_out.tables.items()
    ]
    issues += [
        _left_out_issue(entity_type, name, f"{entity_type} {name!r}", cause)
        for (entity_type, name), cause in left_out.entities.items()
    ]
    return issues


def _left_out_issue(
    entity_type: str, name: str, label: str, cause: str | None
) -> Issue:
    reason = (
        "it has a name error"
        if cause is None
        else f"{cause}, which it depends on, has a name error or is left out"
    )
    return make_issue(
        severity="warning",
        code=Code.VALIDATE_NAME_ENTITY_LEFT_OUT,
        stage="validate",
        message=f"The {label} is not generated: {reason}",
        entity=EntityRef(type=entity_type, name=name),
        suggestion="Fix the name error reported for it.",
    )


def _table_label(key: TableKey) -> str:
    system, table = key
    return f"'{system}.{table}'"
