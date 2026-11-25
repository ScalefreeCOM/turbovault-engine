"""
Stage 4: planner.

Compares the resolved DomainModel against the current project state in the
database, and produces an ImportPlan describing the operations the executor
would perform.

Conflict strategies:
  - merge      : create new, update existing; leave others untouched
  - replace_all: create new, update existing, DELETE everything else
  - update_only: update existing only; skip creates

Entities the resolver left out (`DomainModel.skipped`) are reported as skips
with their reason, whatever the strategy. They are in the source, so
`replace_all` never deletes the project's copy of them.

The planner only matches: an entity that exists is planned as `update`. What
actually differs is found by the executor, which compares every row it
writes; it then reports the entity as `update` or `unchanged` (see
`executor.apply_outcomes`). A dry run runs the executor too, and rolls back.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from engine.models import (
    PIT,
    PrejoinDefinition,
    Project,
    ReferenceTable,
    SnapshotControlTable,
    SourceSystem,
    SourceTable,
)
from engine.services.imports.domain import (
    DHub,
    DLink,
    DomainModel,
    DPrejoin,
    DSourceSystem,
    DSourceTable,
    snapshot_base_name,
)
from engine.services.imports.types import (
    ConflictStrategy,
    EntityRef,
    ImportPlan,
    PlannedEntity,
)

# ---------------------------------------------------------------------------
# Plan items track create/update/delete on entities, plus carry the resolved
# domain object for the executor to use. We use a wrapper rather than the
# Pydantic PlannedEntity because we need to attach mutable Python references.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CreateOp:
    entity_type: str
    name: str
    payload: Any  # the corresponding D* dataclass
    parent_ref: EntityRef | None = None


@dataclass(slots=True)
class UpdateOp:
    entity_type: str
    name: str
    payload: Any
    existing_pk: Any
    parent_ref: EntityRef | None = None


@dataclass(slots=True)
class DeleteOp:
    entity_type: str
    name: str
    existing_pk: Any
    parent_ref: EntityRef | None = None


@dataclass(slots=True)
class SkipOp:
    entity_type: str
    name: str
    reason: str
    parent_ref: EntityRef | None = None


PlanOp = CreateOp | UpdateOp | DeleteOp | SkipOp


@dataclass(slots=True)
class ExecutionPlan:
    """Internal richer plan handed to the executor."""

    ops: list[PlanOp] = field(default_factory=list)

    def add(self, op: PlanOp) -> None:
        self.ops.append(op)


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------


def build_plan(
    *,
    project: Project,
    domain: DomainModel,
    strategy: ConflictStrategy,
    skip_snapshots: bool = False,
) -> tuple[ExecutionPlan, ImportPlan]:
    """Build both the rich execution plan (for the executor) and the public
    ImportPlan (returned in the report)."""
    builder = _PlanBuilder(
        project=project,
        domain=domain,
        strategy=strategy,
        skip_snapshots=skip_snapshots,
    )
    return builder.run()


class _PlanBuilder:
    def __init__(
        self,
        *,
        project: Project,
        domain: DomainModel,
        strategy: ConflictStrategy,
        skip_snapshots: bool = False,
    ):
        self.project = project
        self.domain = domain
        self.strategy = strategy
        self.skip_snapshots = skip_snapshots
        self.exec_plan = ExecutionPlan()
        self.public_plan = ImportPlan()

    # ------------------------------------------------------------------ run
    def run(self) -> tuple[ExecutionPlan, ImportPlan]:
        self._plan_source_systems()
        self._plan_source_tables()
        # Prejoins sit between source tables and links on purpose: they need the
        # source tables to exist, and links need their extraction columns to
        # exist so a prejoin-fed business key can bind to one.
        self._plan_prejoins()
        self._plan_hubs()
        self._plan_links()
        self._plan_satellites()
        # Before the reference tables and PITs that read them.
        self._plan_snapshot_controls()
        self._plan_reference_tables()
        self._plan_pits()
        return self.exec_plan, self.public_plan

    # ------------------------------------------------------------- internal
    def _plan_left_out(self, entity_type: str) -> set[str]:
        """Plan this type's left-out entities as skips; return their names."""
        names: set[str] = set()
        for (kind, name), skipped in self.domain.skipped.items():
            if kind != entity_type:
                continue
            names.add(name)
            self._record(
                SkipOp(entity_type=kind, name=name, reason=skipped.reason),
                skip_reason=skipped.reason,
            )
        return names

    def _record(self, op: PlanOp, *, skip_reason: str | None = None) -> None:
        # Both plans grow together: `exec_plan.ops[i]` is `public_plan.entities[i]`,
        # which is how the executor's outcomes find their entity.
        self.exec_plan.add(op)
        if isinstance(op, CreateOp):
            action = "create"
        elif isinstance(op, UpdateOp):
            action = "update"
        elif isinstance(op, DeleteOp):
            action = "delete"
        else:
            action = "skip"
        self.public_plan.entities.append(
            PlannedEntity(
                ref=EntityRef(type=op.entity_type, name=op.name, parent=op.parent_ref),
                action=action,
                skip_reason=skip_reason,
            )
        )
        self.public_plan.counts.add(op.entity_type, action)

    # ------------------------------------------------------- source systems
    def _plan_source_systems(self) -> None:
        # Deduplicate the multi-keyed dict so we only see each system once.
        seen: set[int] = set()
        desired: list[DSourceSystem] = []
        for sys in self.domain.source_systems.values():
            if id(sys) in seen:
                continue
            seen.add(id(sys))
            desired.append(sys)

        # A system is identified by where it lives, like its unique
        # constraint and the executor: a new name for the same schema is a
        # rename, not a new system (which replace_all would pair with
        # deleting the old one and everything in it).
        existing_by_key: dict[tuple[str, str | None], SourceSystem] = {}
        for ss in self.project.source_systems.all():
            existing_by_key[(ss.schema_name, ss.database_name)] = ss

        used_pks: set[Any] = set()
        for d in desired:
            key = (d.schema_name, d.database_name)
            existing = existing_by_key.get(key)
            if existing is None:
                if self.strategy == "update_only":
                    self._record(
                        SkipOp(
                            entity_type="source_system",
                            name=d.name,
                            reason="update_only: source system does not exist",
                        ),
                        skip_reason="update_only",
                    )
                    continue
                self._record(
                    CreateOp(entity_type="source_system", name=d.name, payload=d)
                )
            else:
                used_pks.add(existing.pk)
                self._record(
                    UpdateOp(
                        entity_type="source_system",
                        name=d.name,
                        payload=d,
                        existing_pk=existing.pk,
                    )
                )

        if self.strategy == "replace_all":
            # A system holding pre-stages stays when the source can't list
            # them (see `_keeps_prestages`).
            holding_prestages: set[Any] = (
                set(
                    SourceTable.objects.filter(
                        source_system__project=self.project,
                        table_type=SourceTable.TableType.PRESTAGE,
                    ).values_list("source_system_id", flat=True)
                )
                if self._keeps_prestages()
                else set()
            )
            for ss in existing_by_key.values():
                if ss.pk not in used_pks and ss.pk not in holding_prestages:
                    self._record(
                        DeleteOp(
                            entity_type="source_system",
                            name=ss.name,
                            existing_pk=ss.pk,
                        )
                    )

    def _keeps_prestages(self) -> bool:
        """Whether `replace_all` keeps the pre-stages the source leaves out.

        It does when the source can't describe pre-stages at all (Excel,
        SQLite, IRiS, a database's catalog): their absence there says nothing.
        """
        return not self.domain.describes_prestages

    def _plan_source_tables(self) -> None:
        seen: set[int] = set()
        desired_pairs: list[tuple[DSourceSystem, DSourceTable]] = []
        for sys in self.domain.source_systems.values():
            if id(sys) in seen:
                continue
            seen.add(id(sys))
            seen_tables: set[int] = set()
            for table in sys.tables.values():
                if id(table) in seen_tables:
                    continue
                seen_tables.add(id(table))
                desired_pairs.append((sys, table))

        existing_tables = list(
            SourceTable.objects.filter(
                source_system__project=self.project
            ).select_related("source_system")
        )

        # Keyed by the system's location, like the systems above.
        existing_by_key: dict[tuple[str, str | None, str], SourceTable] = {}
        for t in existing_tables:
            existing_by_key[
                (
                    t.source_system.schema_name,
                    t.source_system.database_name,
                    t.physical_table_name,
                )
            ] = t

        used_pks: set[Any] = set()
        for sys, table in desired_pairs:
            key = (sys.schema_name, sys.database_name, table.physical_name)
            existing = existing_by_key.get(key)
            parent_ref = EntityRef(type="source_system", name=sys.name)
            if existing is None:
                if self.strategy == "update_only":
                    self._record(
                        SkipOp(
                            entity_type="source_table",
                            name=table.physical_name,
                            reason="update_only",
                            parent_ref=parent_ref,
                        ),
                        skip_reason="update_only",
                    )
                    continue
                self._record(
                    CreateOp(
                        entity_type="source_table",
                        name=table.physical_name,
                        payload=(sys, table),
                        parent_ref=parent_ref,
                    )
                )
            else:
                used_pks.add(existing.pk)
                self._record(
                    UpdateOp(
                        entity_type="source_table",
                        name=table.physical_name,
                        payload=(sys, table),
                        existing_pk=existing.pk,
                        parent_ref=parent_ref,
                    )
                )

        if self.strategy == "replace_all":
            keeps_prestages = self._keeps_prestages()
            for t in existing_tables:
                if t.pk in used_pks or (keeps_prestages and t.is_prestage):
                    continue
                self._record(
                    DeleteOp(
                        entity_type="source_table",
                        name=t.physical_table_name,
                        existing_pk=t.pk,
                    )
                )

    # -------------------------------------------------------------- prejoins
    def _plan_prejoins(self) -> None:
        """Plan prejoin definitions.

        A prejoin has no name of its own. Two tables can be prejoined more than
        one way (datavault4dbt's prejoined_columns allows it: a customer's
        billing and shipping country), so a prejoin is identified by its tables
        and its join columns. One the source describes twice is one: the last
        description wins (an export repeats it under several stages).

        When the source and the project each prejoin a pair of tables once and
        on different columns, the join changed: that prejoin is updated, not
        joined by a second one.
        """
        desired: dict[_PrejoinKey, DPrejoin] = {}
        for pj in self.domain.prejoins:
            desired[_prejoin_key(pj)] = pj

        existing_rows = list(
            PrejoinDefinition.objects.filter(project=self.project)
            .select_related(
                "source_table__source_system",
                "prejoin_target_table__source_system",
            )
            .prefetch_related(
                "prejoin_condition_source_column", "prejoin_condition_target_column"
            )
        )
        # Index by both the qualified "{system}|{table}" identifier the JSON
        # parser produces and the bare physical name, so parsers that use plain
        # table identifiers still match instead of duplicating the row.
        rows_by_pair: dict[tuple[str, str], list[PrejoinDefinition]] = {}
        for row in existing_rows:
            for pair in _prejoin_keys(
                _qualified_name(row.source_table),
                _qualified_name(row.prejoin_target_table),
            ):
                rows_by_pair.setdefault(pair, []).append(row)

        def candidates(key: _PrejoinKey) -> list[PrejoinDefinition]:
            for pair in _prejoin_keys(key[0], key[1]):
                if pair in rows_by_pair:
                    return rows_by_pair[pair]
            return []

        # The same join first, then a pair prejoined once on both sides.
        matched: dict[_PrejoinKey, PrejoinDefinition] = {}
        used_pks: set[Any] = set()
        for key in desired:
            same_join = next(
                (
                    row
                    for row in candidates(key)
                    if row.pk not in used_pks and _row_join(row) == key[2]
                ),
                None,
            )
            if same_join is not None:
                matched[key] = same_join
                used_pks.add(same_join.pk)
        for key in desired:
            if key in matched:
                continue
            rows = [row for row in candidates(key) if row.pk not in used_pks]
            unmatched = [k for k in desired if k not in matched and k[:2] == key[:2]]
            if len(rows) == 1 and len(unmatched) == 1:
                matched[key] = rows[0]
                used_pks.add(rows[0].pk)

        # Name the join too where a pair of tables is prejoined more than once:
        # by the source, or by the source and the project's other prejoins.
        per_pair = Counter((_bare_name(key[0]), _bare_name(key[1])) for key in desired)
        per_pair.update(
            _pair_of(row) for row in existing_rows if row.pk not in used_pks
        )
        several = {pair for pair, count in per_pair.items() if count > 1}

        def name_of(source_id: str, target_id: str, join: _Join) -> str:
            ambiguous = (_bare_name(source_id), _bare_name(target_id)) in several
            return _prejoin_display_name(
                source_id, target_id, join if ambiguous else None
            )

        for key, d in desired.items():
            source_id, target_id = key[0], key[1]
            name = name_of(
                source_id,
                target_id,
                (tuple(d.source_join_columns), tuple(d.target_join_columns)),
            )
            existing = matched.get(key)
            parent_ref = EntityRef(type="source_table", name=_bare_name(source_id))
            if existing is None:
                if self.strategy == "update_only":
                    self._record(
                        SkipOp(
                            entity_type="prejoin",
                            name=name,
                            reason="update_only",
                            parent_ref=parent_ref,
                        ),
                        skip_reason="update_only",
                    )
                    continue
                self._record(
                    CreateOp(
                        entity_type="prejoin",
                        name=name,
                        payload=d,
                        parent_ref=parent_ref,
                    )
                )
            else:
                self._record(
                    UpdateOp(
                        entity_type="prejoin",
                        name=name,
                        payload=d,
                        existing_pk=existing.pk,
                        parent_ref=parent_ref,
                    )
                )

        if self.strategy == "replace_all":
            for row in existing_rows:
                if row.pk not in used_pks:
                    self._record(
                        DeleteOp(
                            entity_type="prejoin",
                            name=name_of(
                                _qualified_name(row.source_table),
                                _qualified_name(row.prejoin_target_table),
                                _row_join_columns(row),
                            ),
                            existing_pk=row.pk,
                        )
                    )

    # ------------------------------------------------------------------ hubs
    def _plan_hubs(self) -> None:
        # Dedup hubs (some entries are alias keys).
        seen: set[int] = set()
        desired: list[DHub] = []
        for hub in self.domain.hubs.values():
            if id(hub) in seen:
                continue
            seen.add(id(hub))
            desired.append(hub)

        existing_by_name = {h.hub_physical_name: h for h in self.project.hubs.all()}
        used_pks: set[Any] = set()

        for d in desired:
            existing = existing_by_name.get(d.physical_name)
            if existing is None:
                if self.strategy == "update_only":
                    self._record(
                        SkipOp(
                            entity_type="hub",
                            name=d.physical_name,
                            reason="update_only",
                        ),
                        skip_reason="update_only",
                    )
                    continue
                self._record(
                    CreateOp(entity_type="hub", name=d.physical_name, payload=d)
                )
            else:
                used_pks.add(existing.pk)
                self._record(
                    UpdateOp(
                        entity_type="hub",
                        name=d.physical_name,
                        payload=d,
                        existing_pk=existing.pk,
                    )
                )

        left_out = self._plan_left_out("hub")

        if self.strategy == "replace_all":
            for h in existing_by_name.values():
                if h.pk not in used_pks and h.hub_physical_name not in left_out:
                    self._record(
                        DeleteOp(
                            entity_type="hub",
                            name=h.hub_physical_name,
                            existing_pk=h.pk,
                        )
                    )

    # ----------------------------------------------------------------- links
    def _plan_links(self) -> None:
        seen: set[int] = set()
        desired: list[DLink] = []
        for link in self.domain.links.values():
            if id(link) in seen:
                continue
            seen.add(id(link))
            desired.append(link)

        existing_by_name = {l.link_physical_name: l for l in self.project.links.all()}
        used_pks: set[Any] = set()
        for d in desired:
            existing = existing_by_name.get(d.physical_name)
            if existing is None:
                if self.strategy == "update_only":
                    self._record(
                        SkipOp(
                            entity_type="link",
                            name=d.physical_name,
                            reason="update_only",
                        ),
                        skip_reason="update_only",
                    )
                    continue
                self._record(
                    CreateOp(entity_type="link", name=d.physical_name, payload=d)
                )
            else:
                used_pks.add(existing.pk)
                self._record(
                    UpdateOp(
                        entity_type="link",
                        name=d.physical_name,
                        payload=d,
                        existing_pk=existing.pk,
                    )
                )

        left_out = self._plan_left_out("link")

        if self.strategy == "replace_all":
            for l in existing_by_name.values():
                if l.pk not in used_pks and l.link_physical_name not in left_out:
                    self._record(
                        DeleteOp(
                            entity_type="link",
                            name=l.link_physical_name,
                            existing_pk=l.pk,
                        )
                    )

    # ------------------------------------------------------------- satellites
    def _plan_satellites(self) -> None:
        desired = list(self.domain.satellites.values())
        existing_by_name = {
            s.satellite_physical_name: s for s in self.project.satellites.all()
        }
        used_pks: set[Any] = set()
        for d in desired:
            existing = existing_by_name.get(d.physical_name)
            if existing is None:
                if self.strategy == "update_only":
                    self._record(
                        SkipOp(
                            entity_type="satellite",
                            name=d.physical_name,
                            reason="update_only",
                        ),
                        skip_reason="update_only",
                    )
                    continue
                self._record(
                    CreateOp(entity_type="satellite", name=d.physical_name, payload=d)
                )
            else:
                used_pks.add(existing.pk)
                self._record(
                    UpdateOp(
                        entity_type="satellite",
                        name=d.physical_name,
                        payload=d,
                        existing_pk=existing.pk,
                    )
                )

        left_out = self._plan_left_out("satellite")

        if self.strategy == "replace_all":
            for s in existing_by_name.values():
                if s.pk not in used_pks and s.satellite_physical_name not in left_out:
                    self._record(
                        DeleteOp(
                            entity_type="satellite",
                            name=s.satellite_physical_name,
                            existing_pk=s.pk,
                        )
                    )

    # ---------------------------------------------------- snapshot controls
    def _plan_snapshot_controls(self) -> None:
        """Create and update the snapshot controls the source describes.

        Matched by base name (a trailing _v0/_v1 dropped, case-insensitive).
        Never deleted, not even by replace_all: PITs and reference tables the
        import leaves alone may read them. Skipped with skip_snapshots.
        """
        existing_by_base = {}
        for control in SnapshotControlTable.objects.filter(project=self.project):
            existing_by_base.setdefault(snapshot_base_name(control.name), control)
        seen: set[str] = set()
        for d in self.domain.snapshot_controls.values():
            base = snapshot_base_name(d.name)
            if base in seen:
                continue
            seen.add(base)
            existing = existing_by_base.get(base)
            if self.skip_snapshots:
                self._record(
                    SkipOp(
                        entity_type="snapshot_control",
                        name=d.name,
                        reason="skip_snapshots",
                    ),
                    skip_reason="skip_snapshots",
                )
            elif existing is not None:
                self._record(
                    UpdateOp(
                        entity_type="snapshot_control",
                        name=d.name,
                        payload=d,
                        existing_pk=existing.pk,
                    )
                )
            elif self.strategy == "update_only":
                self._record(
                    SkipOp(
                        entity_type="snapshot_control",
                        name=d.name,
                        reason="update_only",
                    ),
                    skip_reason="update_only",
                )
            else:
                self._record(
                    CreateOp(entity_type="snapshot_control", name=d.name, payload=d)
                )
        # Left out for an invalid name; never deleted anyway (see above).
        self._plan_left_out("snapshot_control")

    # --------------------------------------------------------- ref tables
    def _plan_reference_tables(self) -> None:
        desired = list(self.domain.reference_tables.values())
        existing_by_name = {
            r.reference_table_physical_name: r
            for r in ReferenceTable.objects.filter(project=self.project)
        }
        used_pks: set[Any] = set()
        for d in desired:
            existing = existing_by_name.get(d.physical_name)
            if existing is None:
                if self.strategy == "update_only":
                    self._record(
                        SkipOp(
                            entity_type="reference_table",
                            name=d.physical_name,
                            reason="update_only",
                        ),
                        skip_reason="update_only",
                    )
                    continue
                self._record(
                    CreateOp(
                        entity_type="reference_table",
                        name=d.physical_name,
                        payload=d,
                    )
                )
            else:
                used_pks.add(existing.pk)
                self._record(
                    UpdateOp(
                        entity_type="reference_table",
                        name=d.physical_name,
                        payload=d,
                        existing_pk=existing.pk,
                    )
                )

        left_out = self._plan_left_out("reference_table")

        if self.strategy == "replace_all":
            for r in existing_by_name.values():
                if (
                    r.pk not in used_pks
                    and r.reference_table_physical_name not in left_out
                ):
                    self._record(
                        DeleteOp(
                            entity_type="reference_table",
                            name=r.reference_table_physical_name,
                            existing_pk=r.pk,
                        )
                    )

    # ------------------------------------------------------------------ pits
    def _plan_pits(self) -> None:
        desired = list(self.domain.pits.values())
        existing_by_name = {
            p.pit_physical_name: p for p in PIT.objects.filter(project=self.project)
        }
        used_pks: set[Any] = set()
        for d in desired:
            existing = existing_by_name.get(d.physical_name)
            if self.skip_snapshots:
                # A PIT needs a snapshot control, and snapshots are off: it is
                # left out, and an existing one is kept (replace_all included).
                if existing is not None:
                    used_pks.add(existing.pk)
                self._record(
                    SkipOp(
                        entity_type="pit", name=d.physical_name, reason="skip_snapshots"
                    ),
                    skip_reason="skip_snapshots",
                )
                continue
            if existing is None:
                if self.strategy == "update_only":
                    self._record(
                        SkipOp(
                            entity_type="pit",
                            name=d.physical_name,
                            reason="update_only",
                        ),
                        skip_reason="update_only",
                    )
                    continue
                self._record(
                    CreateOp(entity_type="pit", name=d.physical_name, payload=d)
                )
            else:
                used_pks.add(existing.pk)
                self._record(
                    UpdateOp(
                        entity_type="pit",
                        name=d.physical_name,
                        payload=d,
                        existing_pk=existing.pk,
                    )
                )

        left_out = self._plan_left_out("pit")

        if self.strategy == "replace_all":
            for p in existing_by_name.values():
                if p.pk not in used_pks and p.pit_physical_name not in left_out:
                    self._record(
                        DeleteOp(
                            entity_type="pit",
                            name=p.pit_physical_name,
                            existing_pk=p.pk,
                        )
                    )


# ---------------------------------------------------------------------------
# Prejoin identity helpers
# ---------------------------------------------------------------------------


def _bare_name(identifier: str) -> str:
    """Strip the "{system}|" prefix the JSON parser adds to table identifiers."""
    return identifier.split("|", 1)[1] if "|" in identifier else identifier


def _qualified_name(table: SourceTable) -> str:
    """The identifier form the JSON parser uses for a source table."""
    return f"{table.source_system.name}|{table.physical_table_name}"


def _prejoin_keys(
    source_id: str, target_id: str
) -> tuple[tuple[str, str], tuple[str, str]]:
    """Lookup keys for a prejoin, most specific first."""
    return (
        (source_id, target_id),
        (_bare_name(source_id), _bare_name(target_id)),
    )


# A prejoin's join columns, without order or case: source side, target side.
_Join = tuple[tuple[str, ...], tuple[str, ...]]
_JoinSet = tuple[frozenset[str], frozenset[str]]
# What identifies a prejoin: its source table, its target table, its join.
_PrejoinKey = tuple[str, str, _JoinSet]


def _join_set(source_columns: Any, target_columns: Any) -> _JoinSet:
    """Join columns compared as the database keeps them: two unordered sets."""
    return (
        frozenset(str(c).lower() for c in source_columns),
        frozenset(str(c).lower() for c in target_columns),
    )


def _prejoin_key(pj: DPrejoin) -> _PrejoinKey:
    return (
        pj.source_table_identifier,
        pj.target_table_identifier,
        _join_set(pj.source_join_columns, pj.target_join_columns),
    )


def _row_join_columns(row: PrejoinDefinition) -> _Join:
    return (
        tuple(
            sorted(
                c.source_column_physical_name
                for c in row.prejoin_condition_source_column.all()
            )
        ),
        tuple(
            sorted(
                c.source_column_physical_name
                for c in row.prejoin_condition_target_column.all()
            )
        ),
    )


def _row_join(row: PrejoinDefinition) -> _JoinSet:
    source, target = _row_join_columns(row)
    return _join_set(source, target)


def _pair_of(row: PrejoinDefinition) -> tuple[str, str]:
    return (
        row.source_table.physical_table_name,
        row.prejoin_target_table.physical_table_name,
    )


def _prejoin_display_name(
    source_id: str, target_id: str, join: _Join | None = None
) -> str:
    """ "orders->customers", with its join where the tables are prejoined twice:
    "orders->customers (customer_id = id)"."""
    name = f"{_bare_name(source_id)}->{_bare_name(target_id)}"
    if join is None:
        return name
    source, target = join
    return f"{name} ({', '.join(source)} = {', '.join(target)})"
