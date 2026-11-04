"""
Prejoin handling for SQLMesh output.

datavault4sqlmesh's ``stage_model`` has no prejoin support, so columns that a
stage pulls in through a prejoin (``PrejoinExtractionColumn``) don't exist in
the generated stage. This module works out, before anything is rendered, what
can't be generated because of that:

- the prejoined columns of each stage, plus derived columns computed from them;
- the stage hash keys and hash diffs that read those columns;
- the hubs, links and satellites that read those columns or hash keys.

The renderer leaves all of these out and reports one warning per stage with
prejoins and one per skipped entity, so the generated project stays runnable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from engine.services.export.models import ProjectExport, StageDefinition
from engine.services.generation.errors import Code, make_issue
from engine.services.generation.types import EntityRef, Issue


@dataclass(frozen=True)
class StagePrejoinGaps:
    """What a single stage can't provide because of its prejoins.

    Column names are casefolded: identifiers that differ only in case name the
    same column after the dialect's normalization.
    """

    unavailable_columns: frozenset[str] = frozenset()
    """Prejoined columns, and derived columns computed from them."""
    hashkeys: frozenset[str] = frozenset()
    """Hash keys that read an unavailable column."""
    hashdiff_satellites: frozenset[str] = frozenset()
    """Satellites whose hash diff reads an unavailable column."""

    def uses(self, columns: Iterable[str]) -> bool:
        """Return True when any of *columns* is unavailable in this stage."""
        return any(column.casefold() in self.unavailable_columns for column in columns)


@dataclass(frozen=True)
class PrejoinSkips:
    """Everything SQLMesh output leaves out because of prejoins."""

    stages: dict[str, StagePrejoinGaps] = field(default_factory=dict)
    # entity name -> stage whose prejoined columns it uses
    hubs: dict[str, str] = field(default_factory=dict)
    links: dict[str, str] = field(default_factory=dict)
    satellites: dict[str, str] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    """One warning per stage with prejoins."""

    def for_stage(self, stage_name: str) -> StagePrejoinGaps:
        """Return the gaps of *stage_name* (empty when it has no prejoins)."""
        return self.stages.get(stage_name, _NO_GAPS)


_NO_GAPS = StagePrejoinGaps()


def plan_prejoin_skips(export: ProjectExport) -> PrejoinSkips:
    """Find what SQLMesh output must leave out because of stage prejoins.

    Returns the gaps per stage, the hubs, links and satellites to skip, and one
    warning Issue per stage with prejoins. The warnings for skipped entities
    come from ``prejoin_dependent_warning``, raised by the renderer when it
    skips them (so an entity skipped for another reason isn't reported twice).
    """
    stages = {
        stage.stage_name: _stage_gaps(stage)
        for stage in export.stages
        if stage.prejoins
    }
    if not stages:
        return PrejoinSkips()

    def gaps(stage_name: str) -> StagePrejoinGaps:
        return stages.get(stage_name, _NO_GAPS)

    issues = [
        _stage_warning(stage, stages[stage.stage_name])
        for stage in export.stages
        if stage.stage_name in stages
    ]

    skipped_hubs: dict[str, str] = {}
    for hub in export.hubs:
        hashkey = hub.hashkey.hashkey_name if hub.hashkey else None
        for src in hub.source_tables:
            stage_gaps = gaps(src.stage_name)
            if (hashkey and hashkey in stage_gaps.hashkeys) or stage_gaps.uses(
                m.source_column for m in src.column_mappings
            ):
                skipped_hubs[hub.hub_name] = src.stage_name
                break

    skipped_links: dict[str, str] = {}
    for link in export.links:
        needed_hashkeys = {link.hashkey.hashkey_name, *link.foreign_hashkeys}
        for src in link.source_tables:
            stage_gaps = gaps(src.stage_name)
            # link_model reads only the hash keys; payload columns don't matter.
            # The business-key check is a fallback for keys the export marks as
            # prejoined but whose hash key the stage doesn't list.
            if needed_hashkeys & stage_gaps.hashkeys or any(
                column.link_column_type == "business_key"
                and column.source_prejoin_target_table
                for column in src.columns
            ):
                skipped_links[link.link_name] = src.stage_name
                break

    skipped_satellites: dict[str, str] = {}
    for sat in export.satellites:
        stage_gaps = gaps(sat.stage_name)
        if (
            sat.satellite_name in stage_gaps.hashdiff_satellites
            or sat.parent_hashkey in stage_gaps.hashkeys
            or stage_gaps.uses(column.source_column for column in sat.columns)
        ):
            skipped_satellites[sat.satellite_name] = sat.stage_name

    return PrejoinSkips(
        stages=stages,
        hubs=skipped_hubs,
        links=skipped_links,
        satellites=skipped_satellites,
        issues=issues,
    )


def _stage_gaps(stage: StageDefinition) -> StagePrejoinGaps:
    """Work out the unavailable columns, hash keys and hash diffs of *stage*."""
    unavailable = {
        (extraction.target_column_alias or extraction.source_column_name).casefold()
        for prejoin in stage.prejoins
        for extraction in prejoin.extraction_columns
    }
    # Derived columns computed from a prejoined column are unavailable too
    # (repeat so chains of derived columns are covered).
    changed = True
    while changed:
        changed = False
        for derived in stage.derived_columns:
            target = derived.target_column_name.casefold()
            if target in unavailable:
                continue
            reads = [derived.source_column_name, *derived.src_cols_required]
            if any(column.casefold() in unavailable for column in reads):
                unavailable.add(target)
                changed = True

    def uses(columns: Iterable[str]) -> bool:
        return any(column.casefold() in unavailable for column in columns)

    return StagePrejoinGaps(
        unavailable_columns=frozenset(unavailable),
        hashkeys=frozenset(
            hk.hashkey_name for hk in stage.hashkeys if uses(hk.business_key_columns)
        ),
        hashdiff_satellites=frozenset(
            hd.satellite_name for hd in stage.hashdiffs if uses(hd.columns)
        ),
    )


def _stage_warning(stage: StageDefinition, stage_gaps: StagePrejoinGaps) -> Issue:
    targets = ", ".join(sorted({prejoin.target_table for prejoin in stage.prejoins}))
    left_out = [
        f"hash keys {_names(stage_gaps.hashkeys)}" if stage_gaps.hashkeys else "",
        (
            f"hash diffs of {_names(stage_gaps.hashdiff_satellites)}"
            if stage_gaps.hashdiff_satellites
            else ""
        ),
    ]
    left_out_text = " and ".join(part for part in left_out if part)
    message = (
        f"Stage '{stage.stage_name}' uses prejoins (to {targets}), which SQLMesh "
        f"output doesn't support yet. Its prejoined columns "
        f"{_names(stage_gaps.unavailable_columns)} are not available"
    )
    message += f"; {left_out_text} were left out." if left_out_text else "."
    return make_issue(
        severity="warning",
        code=Code.SQLMESH_UNSUPPORTED_PREJOIN,
        stage="render",
        message=message,
        entity=EntityRef(type="stage", name=stage.stage_name),
        suggestion=(
            "Entities that use prejoined columns are skipped. Add the columns to "
            "the source table (e.g. a view that does the join) to generate them."
        ),
    )


def prejoin_dependent_warning(
    entity_type: str, name: str, group: str | None, stage_name: str
) -> Issue:
    """Warning Issue for a hub, link or satellite skipped because of prejoins."""
    return make_issue(
        severity="warning",
        code=Code.SQLMESH_PREJOIN_DEPENDENT_SKIPPED,
        stage="render",
        message=(
            f"{entity_type.capitalize()} '{name}' was skipped because it uses "
            f"prejoined columns of stage '{stage_name}', which SQLMesh output "
            "doesn't support yet."
        ),
        entity=EntityRef(type=entity_type, name=name, group=group),
    )


def _names(values: Iterable[str]) -> str:
    return ", ".join(f"'{value}'" for value in sorted(values))
