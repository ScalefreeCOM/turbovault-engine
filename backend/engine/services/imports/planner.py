"""
Stage 4: planner.

Compares the resolved DomainModel against the current project state in the
database, and produces an ImportPlan describing the operations the executor
would perform.

Conflict strategies:
  - merge      : create new, update existing; leave others untouched
  - replace_all: create new, update existing, DELETE everything else
  - update_only: update existing only; skip creates

In dry-run mode the plan is the final artifact; the executor never runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.models import (
    PIT,
    Hub,
    Link,
    Project,
    ReferenceTable,
    Satellite,
    SourceSystem,
    SourceTable,
)
from engine.services.imports.domain import (
    DHub,
    DLink,
    DomainModel,
    DSatellite,
    DSourceSystem,
    DSourceTable,
)
from engine.services.imports.types import (
    ConflictStrategy,
    EntityChange,
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
    changes: list[EntityChange] = field(default_factory=list)
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
) -> tuple[ExecutionPlan, ImportPlan]:
    """Build both the rich execution plan (for the executor) and the public
    ImportPlan (returned in the report)."""
    builder = _PlanBuilder(project=project, domain=domain, strategy=strategy)
    return builder.run()


class _PlanBuilder:
    def __init__(
        self,
        *,
        project: Project,
        domain: DomainModel,
        strategy: ConflictStrategy,
    ):
        self.project = project
        self.domain = domain
        self.strategy = strategy
        self.exec_plan = ExecutionPlan()
        self.public_plan = ImportPlan()

    # ------------------------------------------------------------------ run
    def run(self) -> tuple[ExecutionPlan, ImportPlan]:
        self._plan_source_systems()
        self._plan_source_tables()
        self._plan_hubs()
        self._plan_links()
        self._plan_satellites()
        self._plan_reference_tables()
        self._plan_pits()
        return self.exec_plan, self.public_plan

    # ------------------------------------------------------------- internal
    def _record(
        self,
        op: PlanOp,
        *,
        changes: list[EntityChange] | None = None,
        skip_reason: str | None = None,
    ) -> None:
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
                changes=changes or [],
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

        existing_by_key: dict[tuple[str, str, str | None], SourceSystem] = {}
        for ss in self.project.source_systems.all():
            existing_by_key[(ss.name, ss.schema_name, ss.database_name)] = ss

        used_pks: set[Any] = set()
        for d in desired:
            key = (d.name, d.schema_name, d.database_name)
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
                changes = _diff_source_system(d, existing)
                self._record(
                    UpdateOp(
                        entity_type="source_system",
                        name=d.name,
                        payload=d,
                        existing_pk=existing.pk,
                        changes=changes,
                    ),
                    changes=changes,
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
            SourceTable.objects.filter(source_system__project=self.project)
            .select_related("source_system")
        )

        existing_by_key: dict[tuple[str, str, str | None, str], SourceTable] = {}
        for t in existing_tables:
            existing_by_key[
                (
                    t.source_system.name,
                    t.source_system.schema_name,
                    t.source_system.database_name,
                    t.physical_table_name,
                )
            ] = t

        used_pks: set[Any] = set()
        for sys, table in desired_pairs:
            key = (sys.name, sys.schema_name, sys.database_name, table.physical_name)
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
                changes = _diff_source_table(table, existing)
                self._record(
                    UpdateOp(
                        entity_type="source_table",
                        name=table.physical_name,
                        payload=(sys, table),
                        existing_pk=existing.pk,
                        changes=changes,
                        parent_ref=parent_ref,
                    ),
                    changes=changes,
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
                changes = _diff_hub(d, existing)
                self._record(
                    UpdateOp(
                        entity_type="hub",
                        name=d.physical_name,
                        payload=d,
                        existing_pk=existing.pk,
                        changes=changes,
                    ),
                    changes=changes,
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
                changes = _diff_link(d, existing)
                self._record(
                    UpdateOp(
                        entity_type="link",
                        name=d.physical_name,
                        payload=d,
                        existing_pk=existing.pk,
                        changes=changes,
                    ),
                    changes=changes,
                )

        if self.strategy == "replace_all":
            for l in existing_by_name.values():
                if l.pk not in used_pks:
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
                changes = _diff_satellite(d, existing)
                self._record(
                    UpdateOp(
                        entity_type="satellite",
                        name=d.physical_name,
                        payload=d,
                        existing_pk=existing.pk,
                        changes=changes,
                    ),
                    changes=changes,
                )

        if self.strategy == "replace_all":
            for s in existing_by_name.values():
                if s.pk not in used_pks:
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

        if self.strategy == "replace_all":
            for r in existing_by_name.values():
                if r.pk not in used_pks:
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

        if self.strategy == "replace_all":
            for p in existing_by_name.values():
                if p.pk not in used_pks:
                    self._record(
                        DeleteOp(
                            entity_type="pit",
                            name=p.pit_physical_name,
                            existing_pk=p.pk,
                        )
                    )


# ---------------------------------------------------------------------------
# Field-level diffs (used to populate EntityChange lists)
# ---------------------------------------------------------------------------


def _change(field_name: str, before: Any, after: Any) -> EntityChange | None:
    if before == after:
        return None
    return EntityChange(field=field_name, before=before, after=after)


def _diff_source_system(d: DSourceSystem, existing: SourceSystem) -> list[EntityChange]:
    return [
        c
        for c in (
            _change("name", existing.name, d.name),
            _change("schema_name", existing.schema_name, d.schema_name),
            _change("database_name", existing.database_name, d.database_name),
        )
        if c is not None
    ]


def _diff_source_table(d: DSourceTable, existing: SourceTable) -> list[EntityChange]:
    return [
        c
        for c in (
            _change(
                "record_source_value",
                existing.record_source_value,
                d.record_source_value or "",
            ),
            _change(
                "load_date_value",
                existing.load_date_value,
                d.load_date_value or "sysdate()",
            ),
            _change("alias", existing.alias or "", d.alias or ""),
        )
        if c is not None
    ]


def _diff_hub(d: DHub, existing: Hub) -> list[EntityChange]:
    return [
        c
        for c in (
            _change("hub_type", existing.hub_type, d.hub_type),
            _change(
                "hub_hashkey_name", existing.hub_hashkey_name, d.hashkey_name
            ),
            _change(
                "create_record_tracking_satellite",
                existing.create_record_tracking_satellite,
                d.create_record_tracking_satellite,
            ),
            _change(
                "create_effectivity_satellite",
                existing.create_effectivity_satellite,
                d.create_effectivity_satellite,
            ),
        )
        if c is not None
    ]


def _diff_link(d: DLink, existing: Link) -> list[EntityChange]:
    return [
        c
        for c in (
            _change("link_type", existing.link_type, d.link_type),
            _change(
                "link_hashkey_name", existing.link_hashkey_name, d.hashkey_name
            ),
        )
        if c is not None
    ]


def _diff_satellite(d: DSatellite, existing: Satellite) -> list[EntityChange]:
    return [
        c
        for c in (
            _change("satellite_type", existing.satellite_type, d.satellite_type),
        )
        if c is not None
    ]
