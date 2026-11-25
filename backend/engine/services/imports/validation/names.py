"""
Name checks on a resolved import (#450), following Studio's rules (#451).

Run on the `DomainModel` of every import source (Excel, SQLite, JSON, IRiS,
source metadata), so the same rules apply however metadata arrives:

- ``entity.invalid_name`` (error): a Data Vault name is not a plain
  identifier (``^[A-Za-z_][A-Za-z0-9_]*$``).
- ``entity.name_case_collision`` (error): two entity names differ only in case.
- ``entity.invalid_source_name`` (error): a source schema, database, table or
  column name holds a control character, leading or trailing whitespace or a
  quote character. So does a stage's sequence column or a further column of
  an effectivity satellite: both name stage columns taken from the source.
- ``entity.name_reserved_word`` / ``entity.name_too_long`` (warnings): a Data
  Vault name is an SQL reserved word or longer than Postgres keeps.
- ``entity.unusual_source_name`` (warning): a source table or column name only
  works quoted (spaces, hyphens, reserved words, mixed case).
- ``entity.unusual_display_name`` (warning): a source system or subject area
  name holds characters other than letters, digits, spaces, ``-``, ``_``, ``.``.
- ``entity.invalid_display_name`` (error): a source system or subject area
  name starts with ``.`` or holds characters no generated code can carry.

Names are reported, never renamed. In ``best_effort`` the entities with an
invalid name or a case collision are left out (``leave_out_invalid_names``). The rules live in
``engine.services.naming``, shared with generation and TurboVault Studio.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from engine.services.imports.domain import DomainModel
from engine.services.imports.errors import Code, make_issue
from engine.services.imports.types import EntityRef, EntityType, Issue
from engine.services.naming import (
    DISPLAY_NAME_RULE,
    DV_NAME_RULE,
    MAX_IDENTIFIER_LENGTH,
    case_insensitive_collisions,
    invalid_display_name_reason,
    invalid_source_name_reason,
    is_display_name,
    is_dv_name,
    is_reserved_word,
    is_too_long,
    source_name_quoting_reason,
)

_SUGGESTION_INVALID = (
    "Rename it using only letters, digits and _, starting with a letter or _."
)


def check_names(domain: DomainModel) -> list[Issue]:
    """Return the name issues of a resolved import, errors first."""
    return [
        *_invalid_names(domain),
        *_case_collisions(domain),
        *_invalid_source_names(domain),
        *_invalid_effectivity_columns(domain),
        *_risky_dv_names(domain),
        *_unusual_source_names(domain),
        *_unusual_display_names(domain),
    ]


def _given(value: Any) -> str | None:
    """A name the source sets: None and CLEAR (keep, empty) set none."""
    return value if isinstance(value, str) and value else None


def _dv_names(domain: DomainModel) -> Iterator[tuple[EntityType, str, str, str]]:
    """Every Data Vault name as (entity type, entity name, what it names, name)."""
    for system in domain.source_systems.values():
        for table in system.tables.values():
            if table.alias:
                yield "source_table", table.physical_name, "table alias", table.alias

    for hub in domain.hubs.values():
        yield "hub", hub.physical_name, "Hub name", hub.physical_name
        if hub.hashkey_name:
            yield "hub", hub.physical_name, "hash key", hub.hashkey_name
        for column in hub.columns:
            yield "hub", hub.physical_name, "column", column.name
            for mapping in column.source_mappings:
                if stage_hashkey := _given(mapping.stage_hashkey_name):
                    yield "hub", hub.physical_name, "stage hash key", stage_hashkey
        if is_active := _given(hub.effectivity_is_active_alias):
            yield "hub", hub.physical_name, "is_active alias", is_active

    for link in domain.links.values():
        yield "link", link.physical_name, "Link name", link.physical_name
        if link.hashkey_name:
            yield "link", link.physical_name, "hash key", link.hashkey_name
        for reference in link.hub_references:
            if reference.hub_hashkey_alias_in_link:
                yield (
                    "link",
                    link.physical_name,
                    "hub hash key alias",
                    reference.hub_hashkey_alias_in_link,
                )
        for column in link.columns:
            yield "link", link.physical_name, "column", column.name
        if is_active := _given(link.effectivity_is_active_alias):
            yield "link", link.physical_name, "is_active alias", is_active

    for satellite in domain.satellites.values():
        name = satellite.physical_name
        yield "satellite", name, "Satellite name", name
        for label, value in (
            ("hash diff", satellite.hashdiff_name),
            ("hash diff alias", satellite.hashdiff_alias),
            ("v1 load end date alias", satellite.v1_ledts_alias),
        ):
            if given := _given(value):
                yield "satellite", name, label, given
        for column in satellite.columns:
            if column.target_column_name:
                yield "satellite", name, "column alias", column.target_column_name

    for pit in domain.pits.values():
        yield "pit", pit.physical_name, "PIT name", pit.physical_name
        if pit.dimension_key_column_name:
            yield (
                "pit",
                pit.physical_name,
                "dimension key",
                pit.dimension_key_column_name,
            )

    for ref_table in domain.reference_tables.values():
        name = ref_table.physical_name
        yield "reference_table", name, "reference table name", name

    for control in domain.snapshot_controls.values():
        yield "snapshot_control", control.name, "snapshot control name", control.name
        if sdts_alias := _given(control.sdts_alias):
            yield "snapshot_control", control.name, "snapshot date alias", sdts_alias
        for rule in control.logic_rules:
            yield "snapshot_control", control.name, "logic column", rule.column_name

    for system in domain.source_systems.values():
        for table in system.tables.values():
            for derived in (table.derived_columns or {}).values():
                yield (
                    "source_table",
                    table.physical_name,
                    "derived column",
                    derived.name,
                )

    for prejoin in domain.prejoins:
        for extraction in prejoin.extraction_columns:
            if extraction.alias:
                yield (
                    "source_table",
                    prejoin.source_table_identifier,
                    "prejoin alias",
                    extraction.alias,
                )


def _invalid_names(domain: DomainModel) -> Iterator[Issue]:
    seen: set[tuple[str, str, str]] = set()
    for entity_type, entity_name, label, name in _dv_names(domain):
        if is_dv_name(name) or (entity_type, entity_name, name) in seen:
            continue
        seen.add((entity_type, entity_name, name))
        yield make_issue(
            severity="error",
            code=Code.ENTITY_INVALID_NAME,
            stage="resolve",
            message=f"The {label} {name!r} of {entity_name!r} {DV_NAME_RULE}.",
            entity=EntityRef(type=entity_type, name=entity_name),
            suggestion=_SUGGESTION_INVALID,
        )


def _risky_dv_names(domain: DomainModel) -> Iterator[Issue]:
    """Valid Data Vault names that are reserved words or too long (warnings)."""
    seen: set[tuple[str, str, str]] = set()
    for entity_type, entity_name, label, name in _dv_names(domain):
        if not is_dv_name(name) or (entity_type, entity_name, name) in seen:
            continue
        seen.add((entity_type, entity_name, name))
        entity = EntityRef(type=entity_type, name=entity_name)
        if is_reserved_word(name):
            yield make_issue(
                severity="warning",
                code=Code.ENTITY_NAME_RESERVED_WORD,
                stage="resolve",
                message=(
                    f"The {label} {name!r} of {entity_name!r} is an SQL reserved "
                    "word; it only works where the generated code quotes it."
                ),
                entity=entity,
                suggestion="Rename it, e.g. add a prefix or suffix.",
            )
        if is_too_long(name):
            yield make_issue(
                severity="warning",
                code=Code.ENTITY_NAME_TOO_LONG,
                stage="resolve",
                message=(
                    f"The {label} {name!r} of {entity_name!r} has {len(name)} "
                    f"characters; Postgres truncates names after "
                    f"{MAX_IDENTIFIER_LENGTH}."
                ),
                entity=entity,
                suggestion="Shorten it if the project runs on Postgres.",
            )


def _invalid_source_names(domain: DomainModel) -> Iterator[Issue]:
    """Source names no quoting can carry (errors)."""
    for system in domain.source_systems.values():
        system_names = [
            ("source_system", system.name, "schema", system.schema_name),
            ("source_system", system.name, "database", system.database_name),
        ]
        table_names = [
            ("source_table", table.physical_name, label, name)
            for table in system.tables.values()
            for label, name in (
                ("table name", table.physical_name),
                *(("column", column.name) for column in table.columns.values()),
                ("sequence column", _given(table.sequence_column)),
            )
        ]
        for entity_type, entity_name, label, name in [*system_names, *table_names]:
            if not name or (reason := invalid_source_name_reason(name)) is None:
                continue
            yield make_issue(
                severity="error",
                code=Code.ENTITY_INVALID_SOURCE_NAME,
                stage="resolve",
                message=(
                    f"The source {label} {name!r} of {entity_name!r} {reason}, "
                    "which no quoting can carry."
                ),
                entity=EntityRef(type=entity_type, name=entity_name),
                suggestion="Fix the name in the metadata; it must match the source.",
            )


def _invalid_effectivity_columns(domain: DomainModel) -> Iterator[Issue]:
    """The further stage columns an effectivity satellite carries keep their
    source names, so they follow the source rule (errors)."""
    entities: list[tuple[EntityType, str, Any]] = [
        *(
            ("hub", hub.physical_name, hub.effectivity_additional_columns)
            for hub in domain.hubs.values()
        ),
        *(
            ("link", link.physical_name, link.effectivity_additional_columns)
            for link in domain.links.values()
        ),
    ]
    for entity_type, entity_name, columns in entities:
        if not isinstance(columns, list):
            continue  # None keeps, CLEAR empties: no names to check
        for name in columns:
            if (
                not isinstance(name, str)
                or (reason := invalid_source_name_reason(name)) is None
            ):
                continue
            yield make_issue(
                severity="error",
                code=Code.ENTITY_INVALID_SOURCE_NAME,
                stage="resolve",
                message=(
                    f"The effectivity satellite column {name!r} of {entity_name!r} "
                    f"{reason}, which no quoting can carry."
                ),
                entity=EntityRef(type=entity_type, name=entity_name),
                suggestion="Fix the name in the metadata; it must match the stage.",
            )


def _unusual_display_names(domain: DomainModel) -> Iterator[Issue]:
    """Source system and subject area names outside rule C (warnings)."""
    display_names: dict[str, tuple[EntityType, str]] = {}
    for system in domain.source_systems.values():
        display_names.setdefault(system.name, ("source_system", "source system"))
    groups = set(domain.groups)
    for entities in (
        domain.hubs,
        domain.links,
        domain.satellites,
        domain.reference_tables,
        domain.pits,
    ):
        groups.update(e.group_name for e in entities.values() if e.group_name)
    for group in sorted(groups):
        display_names.setdefault(group, ("group", "subject area"))

    for name, (entity_type, label) in display_names.items():
        if reason := invalid_display_name_reason(name):
            yield make_issue(
                severity="error",
                code=Code.ENTITY_INVALID_DISPLAY_NAME,
                stage="resolve",
                message=f"The {label} name {name!r} {reason}.",
                entity=EntityRef(type=entity_type, name=name),
                suggestion="Rename it.",
            )
            continue
        if is_display_name(name):
            continue
        yield make_issue(
            severity="warning",
            code=Code.ENTITY_UNUSUAL_DISPLAY_NAME,
            stage="resolve",
            message=(
                f"The {label} name {name!r} {DISPLAY_NAME_RULE}. Its technical "
                "name is derived safely, but TurboVault Studio rejects it."
            ),
            entity=EntityRef(type=entity_type, name=name),
            suggestion="Rename it, e.g. 'Sales & Ops' to 'Sales and Ops'.",
        )


# The DomainModel dicts holding Data Vault entities, by entity type.
DV_ENTITY_DICTS: tuple[tuple[EntityType, str], ...] = (
    ("hub", "hubs"),
    ("link", "links"),
    ("satellite", "satellites"),
    ("pit", "pits"),
    ("reference_table", "reference_tables"),
    ("snapshot_control", "snapshot_controls"),
)


def entity_name(entity: Any) -> str:
    """A domain entity's name: its physical name (a snapshot control's name)."""
    return getattr(entity, "physical_name", None) or entity.name


def dv_entities(domain: DomainModel) -> list[tuple[EntityType, str, Any]]:
    """Every Data Vault entity once, as (entity type, name, entity).

    Hubs and links are also keyed by their identifiers, so the dicts' keys
    are not their names.
    """
    entities: list[tuple[EntityType, str, Any]] = []
    for entity_type, attribute in DV_ENTITY_DICTS:
        seen: set[int] = set()
        for entity in getattr(domain, attribute).values():
            if id(entity) not in seen:
                seen.add(id(entity))
                entities.append((entity_type, entity_name(entity), entity))
    return entities


def _case_collisions(domain: DomainModel) -> Iterator[Issue]:
    """Entity names become model names: unique however they are cased."""
    entities = [(entity_type, name) for entity_type, name, _ in dv_entities(domain)]
    # One issue per entity, so best_effort can leave each of them out
    for group in case_insensitive_collisions(entities, key=lambda entity: entity[1]):
        described = ", ".join(f"{kind} '{name}'" for kind, name in group)
        for entity_type, name in group:
            yield make_issue(
                severity="error",
                code=Code.ENTITY_NAME_CASE_COLLISION,
                stage="resolve",
                message=f"Names that differ only in case collide: {described}.",
                entity=EntityRef(type=entity_type, name=name),
                suggestion="Give each entity a name that differs in more than case.",
            )


def _unusual_source_names(domain: DomainModel) -> Iterator[Issue]:
    """One warning per source table listing its names that only work quoted."""
    for system in domain.source_systems.values():
        for table in system.tables.values():
            if table.table_type == "prestage":
                continue
            unusual = [
                f"{name!r} ({reason})"
                for name in (
                    table.physical_name,
                    *(column.name for column in table.columns.values()),
                )
                if (reason := source_name_quoting_reason(name))
            ]
            if not unusual:
                continue
            yield make_issue(
                severity="warning",
                code=Code.ENTITY_UNUSUAL_SOURCE_NAME,
                stage="resolve",
                message=(
                    f"Source table {table.physical_name!r} has names that only "
                    f"work quoted: {', '.join(unusual)}."
                ),
                entity=EntityRef(type="source_table", name=table.physical_name),
                suggestion=(
                    "No change needed if the names are right; check that the "
                    "generated stage compiles."
                ),
            )
