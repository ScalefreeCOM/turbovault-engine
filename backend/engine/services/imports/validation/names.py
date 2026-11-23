"""
Name checks on a resolved import (#450), following Studio's rules (#451).

Run on the `DomainModel` of every import source (Excel, SQLite, JSON, IRiS,
source metadata), so the same rules apply however metadata arrives:

- ``entity.invalid_name`` (error): a Data Vault name is not a plain
  identifier (``^[A-Za-z_][A-Za-z0-9_]*$``).
- ``entity.name_case_collision`` (error): two entity names differ only in case.
- ``entity.invalid_source_name`` (error): a source schema, database, table or
  column name holds a control character, leading or trailing whitespace or a
  quote character.
- ``entity.name_reserved_word`` / ``entity.name_too_long`` (warnings): a Data
  Vault name is an SQL reserved word or longer than Postgres keeps.
- ``entity.unusual_source_name`` (warning): a source table or column name only
  works quoted (spaces, hyphens, reserved words, mixed case).
- ``entity.unusual_display_name`` (warning): a source system or subject area
  name holds characters other than letters, digits, spaces, ``-``, ``_``, ``.``.

Names are reported, never renamed. The rules live in
``engine.services.naming``, shared with generation and TurboVault Studio.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

from engine.services.imports.domain import DomainModel
from engine.services.imports.errors import Code, make_issue
from engine.services.imports.types import EntityRef, EntityType, Issue
from engine.services.naming import (
    DISPLAY_NAME_RULE,
    DV_NAME_RULE,
    MAX_IDENTIFIER_LENGTH,
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
        *_risky_dv_names(domain),
        *_unusual_source_names(domain),
        *_unusual_display_names(domain),
    ]


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

    for satellite in domain.satellites.values():
        name = satellite.physical_name
        yield "satellite", name, "Satellite name", name
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


def _case_collisions(domain: DomainModel) -> Iterator[Issue]:
    """Entity names become model names: unique however they are cased."""
    entities: list[tuple[EntityType, str]] = [
        *(("hub", name) for name in domain.hubs),
        *(("link", name) for name in domain.links),
        *(("satellite", name) for name in domain.satellites),
        *(("pit", name) for name in domain.pits),
        *(("reference_table", name) for name in domain.reference_tables),
        *(("snapshot_control", name) for name in domain.snapshot_controls),
    ]
    by_folded: dict[str, list[tuple[EntityType, str]]] = defaultdict(list)
    for entity in entities:
        by_folded[entity[1].casefold()].append(entity)

    for group in by_folded.values():
        if len(group) < 2:
            continue
        described = ", ".join(f"{kind} '{name}'" for kind, name in group)
        first_type, first_name = group[0]
        yield make_issue(
            severity="error",
            code=Code.ENTITY_NAME_CASE_COLLISION,
            stage="resolve",
            message=f"Names that differ only in case collide: {described}.",
            entity=EntityRef(type=first_type, name=first_name),
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
