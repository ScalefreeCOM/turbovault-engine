"""
Name checks run before generation (#450).

- Every Data Vault name must be a plain identifier (``NAM_001``, error).
- Data Vault names must stay unique ignoring case: entity names across the
  project, and the columns that meet in one stage or satellite (``NAM_002``,
  error).
- Source table and column names that only work quoted are reported once per
  table (``NAM_003``, warning). The generated code quotes them where dbt lets
  it; datavault4dbt escapes columns itself and may change their case.

The rules themselves live in ``engine.services.naming`` so the import pipeline
and TurboVault Studio apply the same ones.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.services.naming import (
    DV_NAME_RULE,
    is_dv_name,
    source_name_quoting_reason,
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


# ---------------------------------------------------------------------------
# Data Vault names
# ---------------------------------------------------------------------------


def _dv_names(export: ProjectExport) -> Iterator[DvName]:
    """Every Data Vault name of the export, with where it is defined."""
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

    for link in export.links:
        yield DvName("link", link.link_name, "link_name", link.link_name)
        if link.hashkey and link.hashkey.hashkey_name:
            yield DvName("link", link.link_name, "hashkey", link.hashkey.hashkey_name)
        for field_name in (
            "foreign_hashkeys",
            "business_key_columns",
            "payload_columns",
            "additional_columns",
        ):
            for column in getattr(link, field_name):
                yield DvName("link", link.link_name, field_name, column)
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
        if satellite.hashdiff_name:
            yield DvName("satellite", name, "hashdiff_name", satellite.hashdiff_name)
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
        for pattern in control.logic_patterns:
            yield DvName(
                "snapshot_control", control.name, "logic_patterns", pattern.column_name
            )


def _check_formats(names: Iterable[DvName], result: ValidationResult) -> None:
    reported: set[DvName] = set()
    for dv_name in names:
        if is_dv_name(dv_name.name) or dv_name in reported:
            continue
        reported.add(dv_name)
        result.add_error(
            entity_type=dv_name.entity_type,
            entity_name=dv_name.entity_name,
            field=dv_name.field,
            message=f"Name {dv_name.name!r} {DV_NAME_RULE}",
            code="NAM_001",
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
    by_folded: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for entity in entities:
        by_folded[entity[1].casefold()].append(entity)

    for group in by_folded.values():
        if len(group) < 2:
            continue
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
    by_folded: dict[str, list[str]] = defaultdict(list)
    for column in columns:
        spellings = by_folded[column.casefold()]
        if column not in spellings:
            spellings.append(column)
    for spellings in by_folded.values():
        if len(spellings) < 2:
            continue
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
    """Warn once per source table about names that only work quoted."""
    for system in export.sources:
        for table in system.tables:
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
