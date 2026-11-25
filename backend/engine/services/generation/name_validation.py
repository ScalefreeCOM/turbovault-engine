"""
Name checks run before generation (#450), following Studio's rules (#451).

- Every Data Vault name must be a plain identifier (``NAM_001``, error).
- Data Vault names must stay unique ignoring case: entity names across the
  project, and the columns that meet in one stage or satellite (``NAM_002``,
  error).
- Source table and column names that only work quoted are reported once per
  table (``NAM_003``, warning). The generated code quotes them where dbt lets
  it; datavault4dbt escapes columns itself and may change their case.
- Data Vault names that are SQL reserved words (``NAM_004``) or longer than
  Postgres keeps (``NAM_005``) are warnings.
- Source schema, database, table and column names with control characters,
  leading or trailing whitespace or quote characters (``NAM_006``, error).
  The same goes for a stage's sequence column and the further columns an
  effectivity satellite carries: both name stage columns taken from the source.
- Source system and subject area names outside letters, digits, spaces,
  ``-``, ``_`` and ``.`` (``NAM_007``, warning): their technical names are
  still derived safely. Names starting with ``.`` or holding characters no
  generated code can carry are errors (``NAM_009``).
- Display names that give the same technical name (``NAM_008``): an error
  for two source systems (one dbt source name, one staging folder) or two
  tables of one system (one stage name), a warning for two subject areas
  (they share a folder and tag).

With ``error_strategy="best_effort"`` the entities with name errors are left
out of the output (``engine.services.generation.name_skips``).

The rules themselves live in ``engine.services.naming`` so the import pipeline
and TurboVault Studio apply the same ones.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.services.export.model_outputs import dbt_source_name
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
    technical_name,
)

if TYPE_CHECKING:
    from engine.services.export.models import ProjectExport
    from engine.services.generation.validators import ValidationResult


@dataclass(frozen=True, slots=True)
class DvName:
    """One Data Vault name and where it is defined."""

    entity_type: str
    entity_name: str
    field: str
    name: str


def validate_names(project_export: ProjectExport, result: ValidationResult) -> None:
    """Add every name problem of ``project_export`` to ``result``."""
    names = list(_dv_names(project_export))
    _check_formats(names, result)
    _check_entity_collisions(project_export, result)
    _check_column_collisions(project_export, result)
    _check_source_names(project_export, result)
    _check_effectivity_columns(project_export, result)
    _check_display_names(project_export, result)
    _check_technical_name_collisions(project_export, result)


# ---------------------------------------------------------------------------
# Data Vault names
# ---------------------------------------------------------------------------


def _dv_names(export: ProjectExport) -> Iterator[DvName]:
    """Every Data Vault name of the export, with where it is defined."""
    project_name = export.project_name or "project"
    for field_name in ("stage_schema", "rdv_schema", "bdv_schema"):
        schema = getattr(export, field_name)
        if schema:
            yield DvName("project", project_name, field_name, schema)

    for system in export.sources:
        for table in system.tables:
            if table.alias:
                yield DvName(
                    "source", f"{system.name}.{table.table_name}", "alias", table.alias
                )

    for hub in export.hubs:
        yield DvName("hub", hub.hub_name, "hub_name", hub.hub_name)
        if hub.hashkey and hub.hashkey.hashkey_name:
            yield DvName("hub", hub.hub_name, "hashkey", hub.hashkey.hashkey_name)
        for field_name in (
            "business_key_columns",
            "reference_key_columns",
            "additional_columns",
        ):
            for column in getattr(hub, field_name):
                yield DvName("hub", hub.hub_name, field_name, column)
        for source in hub.source_tables:
            if source.hk_column:
                yield DvName("hub", hub.hub_name, "hk_column", source.hk_column)
        if hub.effectivity_options.is_active_alias:
            yield DvName(
                "hub",
                hub.hub_name,
                "is_active_alias",
                hub.effectivity_options.is_active_alias,
            )

    for link in export.links:
        yield DvName("link", link.link_name, "link_name", link.link_name)
        if link.hashkey and link.hashkey.hashkey_name:
            yield DvName("link", link.link_name, "hashkey", link.hashkey.hashkey_name)
        for field_name in (
            "foreign_hashkeys",
            "business_key_columns",
            "payload_columns",
            "dependent_child_keys",
            "additional_columns",
        ):
            for column in getattr(link, field_name):
                yield DvName("link", link.link_name, field_name, column)
        if link.effectivity_options.is_active_alias:
            yield DvName(
                "link",
                link.link_name,
                "is_active_alias",
                link.effectivity_options.is_active_alias,
            )
        for reference in link.hub_references:
            if reference.hub_hashkey_alias_in_link:
                yield DvName(
                    "link",
                    link.link_name,
                    "hub_hashkey_alias_in_link",
                    reference.hub_hashkey_alias_in_link,
                )

    for satellite in export.satellites:
        name = satellite.satellite_name
        yield DvName("satellite", name, "satellite_name", name)
        for field_name in ("hashdiff_name", "hashdiff_alias", "v1_ledts_alias"):
            value = getattr(satellite, field_name)
            if value:
                yield DvName("satellite", name, field_name, value)
        # A renamed column gets a Data Vault name; one kept as it is stays a
        # source name, checked with the source names.
        for column in satellite.columns:
            if column.target_column_name:
                yield DvName(
                    "satellite", name, "target_column_name", column.target_column_name
                )

    for stage in export.stages:
        for derived in stage.derived_columns:
            yield DvName(
                "stage",
                stage.stage_name,
                "derived_columns",
                derived.target_column_name,
            )
        for prejoin in stage.prejoins:
            for extraction in prejoin.extraction_columns:
                if extraction.target_column_alias:
                    yield DvName(
                        "stage",
                        stage.stage_name,
                        "prejoins",
                        extraction.target_column_alias,
                    )

    for pit in export.pits:
        yield DvName("pit", pit.pit_name, "pit_name", pit.pit_name)
        if pit.dimension_key_column:
            yield DvName(
                "pit", pit.pit_name, "dimension_key_column", pit.dimension_key_column
            )

    for ref_table in export.reference_tables:
        yield DvName(
            "reference_table", ref_table.table_name, "table_name", ref_table.table_name
        )

    for control in export.snapshot_controls:
        if not control.name:
            continue  # SNAP_001 reports the missing name
        yield DvName("snapshot_control", control.name, "name", control.name)
        if control.sdts_alias:
            yield DvName(
                "snapshot_control", control.name, "sdts_alias", control.sdts_alias
            )
        for pattern in control.logic_patterns:
            yield DvName(
                "snapshot_control", control.name, "logic_patterns", pattern.column_name
            )


def _check_formats(names: Iterable[DvName], result: ValidationResult) -> None:
    """Invalid names are errors; reserved words and long names warnings."""
    reported: set[DvName] = set()
    for dv_name in names:
        if dv_name in reported:
            continue
        reported.add(dv_name)
        location = {
            "entity_type": dv_name.entity_type,
            "entity_name": dv_name.entity_name,
            "field": dv_name.field,
        }
        if not is_dv_name(dv_name.name):
            result.add_error(
                **location,
                message=f"Name {dv_name.name!r} {DV_NAME_RULE}",
                code="NAM_001",
            )
            continue
        if is_reserved_word(dv_name.name):
            result.add_warning(
                **location,
                message=(
                    f"Name {dv_name.name!r} is an SQL reserved word; it only "
                    "works where the generated code quotes it"
                ),
                code="NAM_004",
            )
        if is_too_long(dv_name.name):
            result.add_warning(
                **location,
                message=(
                    f"Name {dv_name.name!r} has {len(dv_name.name)} characters; "
                    f"Postgres truncates names after {MAX_IDENTIFIER_LENGTH}"
                ),
                code="NAM_005",
            )


def _check_entity_collisions(export: ProjectExport, result: ValidationResult) -> None:
    """Entity names become dbt model names: one per name, however it is cased."""
    entities: list[tuple[str, str]] = [
        *(("hub", hub.hub_name) for hub in export.hubs),
        *(("link", link.link_name) for link in export.links),
        *(("satellite", sat.satellite_name) for sat in export.satellites),
        *(("pit", pit.pit_name) for pit in export.pits),
        *(("reference_table", ref.table_name) for ref in export.reference_tables),
        *(
            ("snapshot_control", control.name)
            for control in export.snapshot_controls
            if control.name
        ),
    ]
    # Exactly equal names are no case collision: validate.model.duplicate_name
    # reports them.
    for group in case_insensitive_collisions(entities, key=lambda entity: entity[1]):
        described = ", ".join(f"{kind} '{name}'" for kind, name in group)
        for kind, name in group:
            result.add_error(
                entity_type=kind,
                entity_name=name,
                field="name",
                message=(
                    f"Names that differ only in case can't be told apart in the "
                    f"warehouse or on every file system: {described}"
                ),
                code="NAM_002",
            )


def _check_column_collisions(export: ProjectExport, result: ValidationResult) -> None:
    """Columns that end up in one stage or satellite must differ ignoring case."""
    for stage in export.stages:
        columns = [
            *(hashkey.hashkey_name for hashkey in stage.hashkeys),
            *(hashdiff.hashdiff_name for hashdiff in stage.hashdiffs),
            *(derived.target_column_name for derived in stage.derived_columns),
            *(
                extraction.target_column_alias or extraction.source_column_name
                for prejoin in stage.prejoins
                for extraction in prejoin.extraction_columns
            ),
        ]
        _report_column_collisions("stage", stage.stage_name, columns, result)

    for satellite in export.satellites:
        columns = [
            column.target_column_name or column.source_column
            for column in satellite.columns
        ]
        _report_column_collisions(
            "satellite", satellite.satellite_name, columns, result
        )


def _report_column_collisions(
    entity_type: str, entity_name: str, columns: list[str], result: ValidationResult
) -> None:
    for spellings in case_insensitive_collisions(columns):
        result.add_error(
            entity_type=entity_type,
            entity_name=entity_name,
            field="columns",
            message=(
                "Columns that differ only in case can't be told apart in the "
                f"warehouse: {', '.join(spellings)}"
            ),
            code="NAM_002",
        )


# ---------------------------------------------------------------------------
# Source names
# ---------------------------------------------------------------------------


def _check_source_names(export: ProjectExport, result: ValidationResult) -> None:
    """Reject source names no quoting can carry; warn once per source table
    about names that only work quoted."""
    for system in export.sources:
        for field_name, name in (
            ("schema_name", system.schema_name),
            ("database_name", system.database_name),
        ):
            _check_source_name("source", system.name, field_name, name, result)
        for table in system.tables:
            table_ref = f"{system.name}.{table.table_name}"
            _check_source_name(
                "source", table_ref, "table_name", table.table_name, result
            )
            for column in table.columns:
                _check_source_name(
                    "source", table_ref, "columns", column.column_name, result
                )
            _check_source_name(
                "source", table_ref, "sequence_column", table.sequence_column, result
            )
            if table.table_type == "prestage":
                continue
            unusual = [
                f"{name!r} ({reason})"
                for name in (table.table_name, *(c.column_name for c in table.columns))
                if (reason := source_name_quoting_reason(name))
            ]
            if not unusual:
                continue
            result.add_warning(
                entity_type="source",
                entity_name=f"{system.name}.{table.table_name}",
                field="names",
                message=(
                    "These source names only work quoted: "
                    f"{', '.join(unusual)}. TurboVault quotes them in sources.yml; "
                    "datavault4dbt escapes column names itself and may change "
                    "their case (lowercase on Postgres/Redshift, uppercase on "
                    "Snowflake/Exasol), so check the generated stage compiles"
                ),
                code="NAM_003",
            )


def _check_effectivity_columns(export: ProjectExport, result: ValidationResult) -> None:
    """The further stage columns an effectivity satellite carries keep their
    source names, so they follow the source rule."""
    entities = [
        *(("hub", hub.hub_name, hub.effectivity_options) for hub in export.hubs),
        *(("link", link.link_name, link.effectivity_options) for link in export.links),
    ]
    for entity_type, entity_name, options in entities:
        for column in options.additional_columns:
            _check_source_name(
                entity_type, entity_name, "additional_columns", column, result
            )


def _check_source_name(
    entity_type: str,
    entity_name: str,
    field_name: str,
    name: str | None,
    result: ValidationResult,
) -> None:
    if not name or (reason := invalid_source_name_reason(name)) is None:
        return
    result.add_error(
        entity_type=entity_type,
        entity_name=entity_name,
        field=field_name,
        message=f"Source name {name!r} {reason}, which no quoting can carry",
        code="NAM_006",
    )


# ---------------------------------------------------------------------------
# Display names
# ---------------------------------------------------------------------------


def _display_names(export: ProjectExport) -> dict[str, tuple[str, str]]:
    """Every source system and subject area name: name -> (entity type, label)."""
    display_names: dict[str, tuple[str, str]] = {}
    for system in export.sources:
        display_names.setdefault(system.name, ("source", "source system"))
    for group in _groups(export):
        display_names.setdefault(group, ("group", "subject area"))
    return display_names


def _groups(export: ProjectExport) -> list[str]:
    """The subject areas of the export's entities, in order of appearance."""
    groups: dict[str, None] = {}
    for entities in (
        export.hubs,
        export.links,
        export.satellites,
        export.pits,
        export.reference_tables,
    ):
        for entity in entities:
            if group := getattr(entity, "group", None):
                groups.setdefault(group)
    return list(groups)


def _check_display_names(export: ProjectExport, result: ValidationResult) -> None:
    """Source system and subject area names: errors for names no folder or
    generated code can carry, one warning per name outside rule C."""
    for name, (entity_type, label) in _display_names(export).items():
        if reason := invalid_display_name_reason(name):
            result.add_error(
                entity_type=entity_type,
                entity_name=name,
                field="name",
                message=f"The {label} name {name!r} {reason}",
                code="NAM_009",
            )
            continue
        if is_display_name(name):
            continue
        result.add_warning(
            entity_type=entity_type,
            entity_name=name,
            field="name",
            message=(
                f"The {label} name {name!r} {DISPLAY_NAME_RULE}; its technical "
                f"name is derived safely, but TurboVault Studio rejects it"
            ),
            code="NAM_007",
        )


def _check_technical_name_collisions(
    export: ProjectExport, result: ValidationResult
) -> None:
    """Display names that give one technical name.

    Two source systems would share a dbt source name and staging folder, two
    tables of one system a stage name: errors on each of them. Two subject
    areas only share a folder and tag: a warning.
    """
    for names in _shared_technical_names(
        [system.name for system in export.sources], dbt_source_name
    ):
        _report_shared_technical_name(
            "source", names, names, dbt_source_name(names[0]), "error", result
        )

    for system in export.sources:
        tables = [table.table_name for table in system.tables]
        for names in _shared_technical_names(tables, technical_name):
            _report_shared_technical_name(
                "source",
                [f"{system.name}.{name}" for name in names],
                names,
                technical_name(names[0]),
                "error",
                result,
                what="stage name part",
            )

    for names in _shared_technical_names(_groups(export), technical_name):
        _report_shared_technical_name(
            "group", names, names, technical_name(names[0]), "warning", result
        )


def _shared_technical_names(
    names: Iterable[str], derive: Callable[[str], str]
) -> list[list[str]]:
    """Groups of distinct names that derive the same technical name."""
    by_technical: dict[str, list[str]] = defaultdict(list)
    for name in names:
        group = by_technical[derive(name)]
        if name not in group:
            group.append(name)
    return [group for group in by_technical.values() if len(group) > 1]


def _report_shared_technical_name(
    entity_type: str,
    entity_names: list[str],
    names: list[str],
    shared: str,
    severity: str,
    result: ValidationResult,
    what: str = "technical name",
) -> None:
    described = ", ".join(repr(name) for name in names)
    consequence = (
        "their models share a folder and tag"
        if severity == "warning"
        else "their generated models and sources would overwrite each other"
    )
    for entity_name in entity_names:
        add = result.add_error if severity == "error" else result.add_warning
        add(
            entity_type=entity_type,
            entity_name=entity_name,
            field="name",
            message=(
                f"{described} all give the {what} {shared!r}; {consequence}. "
                "Rename one of them"
            ),
            code="NAM_008",
        )
