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

from dataclasses import dataclass, field
from typing import Any

from engine.models import (
    PIT,
    PrejoinDefinition,
    Project,
    ReferenceTable,
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
                self._record(CreateOp(entity_type="source_system", name=d.name, payload=d))
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
            for ss in existing_by_key.values():
                if ss.pk not in used_pks:
                    self._record(
                        DeleteOp(
                            entity_type="source_system",
                            name=ss.name,
                            existing_pk=ss.pk,
                        )
                    )

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
            for t in existing_tables:
                if t.pk not in used_pks:
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

        A prejoin has no name of its own; it is identified by the pair of tables
        it joins, so ``(source table, target table)`` is the natural key here and
        in the executor.
        """
        # Deduplicate: the same table pair may be described more than once
        # (e.g. the export repeats it under several stages). Last one wins,
        # matching the executor's update_or_create.
        desired: dict[tuple[str, str], DPrejoin] = {}
        for pj in self.domain.prejoins:
            desired[(pj.source_table_identifier, pj.target_table_identifier)] = pj

        existing_rows = list(
            PrejoinDefinition.objects.filter(project=self.project).select_related(
                "source_table__source_system",
                "prejoin_target_table__source_system",
            )
        )
        # Index by both the qualified "{system}|{table}" identifier the JSON
        # parser produces and the bare physical name, so parsers that use plain
        # table identifiers still match instead of duplicating the row.
        existing_by_key: dict[tuple[str, str], PrejoinDefinition] = {}
        for row in existing_rows:
            for key in _prejoin_keys(
                _qualified_name(row.source_table),
                _qualified_name(row.prejoin_target_table),
            ):
                existing_by_key.setdefault(key, row)

        used_pks: set[Any] = set()
        for (source_id, target_id), d in desired.items():
            name = _prejoin_display_name(source_id, target_id)
            existing = next(
                (
                    existing_by_key[key]
                    for key in _prejoin_keys(source_id, target_id)
                    if key in existing_by_key
                ),
                None,
            )
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
                used_pks.add(existing.pk)
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
                            name=_prejoin_display_name(
                                _qualified_name(row.source_table),
                                _qualified_name(row.prejoin_target_table),
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
                self._record(CreateOp(entity_type="hub", name=d.physical_name, payload=d))
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

        if self.strategy == "replace_all":
            for h in existing_by_name.values():
                if h.pk not in used_pks:
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
                self._record(CreateOp(entity_type="link", name=d.physical_name, payload=d))
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
                    SkipOp(entity_type="pit", name=d.physical_name, reason="skip_snapshots"),
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
                self._record(CreateOp(entity_type="pit", name=d.physical_name, payload=d))
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


def _prejoin_display_name(source_id: str, target_id: str) -> str:
    return f"{_bare_name(source_id)}->{_bare_name(target_id)}"
