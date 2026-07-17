"""
Stage 5: executor.

Applies an ExecutionPlan to the database inside a single atomic transaction.
Uses `update_or_create` so re-imports actually pick up corrections in the
source file (the old code used `get_or_create` and silently kept stale
values — that's the bug the user called out).

Per-entity exceptions become Issue(severity=error). In `fail_fast` the
first error raises PipelineAbort; in `best_effort` the executor continues
and the failed entity is recorded as skipped in the plan and ImportReport.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from engine.models import (
    PIT,
    Group,
    Hub,
    HubColumn,
    HubSourceMapping,
    Link,
    LinkColumn,
    LinkHubReference,
    LinkHubSourceMapping,
    LinkSourceMapping,
    Project,
    ReferenceTable,
    Satellite,
    SatelliteColumn,
    SnapshotControlLogic,
    SnapshotControlTable,
    SourceColumn,
    SourceSystem,
    SourceTable,
)
from engine.services.imports.domain import (
    DPIT,
    DHub,
    DLink,
    DomainModel,
    DReferenceTable,
    DSatellite,
    DSourceSystem,
)
from engine.services.imports.errors import Code, PipelineAbort, make_issue
from engine.services.imports.planner import (
    CreateOp,
    DeleteOp,
    ExecutionPlan,
    SkipOp,
    UpdateOp,
)
from engine.services.imports.staging_helpers import get_or_create_staging_column
from engine.services.imports.types import (
    EntityRef,
    ErrorStrategy,
    Issue,
)


def _snapshot_base_name(name: str) -> str:
    """Base name of a snapshot control: trailing _v0/_v1 stripped, lowercased."""
    lowered = (name or "").lower()
    for suffix in ("_v0", "_v1"):
        if lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


def execute_plan(
    *,
    project: Project,
    domain: DomainModel,
    plan: ExecutionPlan,
    error_strategy: ErrorStrategy,
    skip_snapshots: bool,
) -> list[Issue]:
    """Apply the plan to the database; return any issues that arose.

    The whole call runs in a single atomic transaction. On `fail_fast` the
    first error issue is raised as PipelineAbort and the runner rolls back.
    On `best_effort` the executor continues past per-entity errors and the
    transaction commits at the end with whatever succeeded.
    """
    executor = _Executor(
        project=project,
        domain=domain,
        plan=plan,
        error_strategy=error_strategy,
        skip_snapshots=skip_snapshots,
    )
    with transaction.atomic():
        executor.run()
    return executor.issues


class _Executor:
    def __init__(
        self,
        *,
        project: Project,
        domain: DomainModel,
        plan: ExecutionPlan,
        error_strategy: ErrorStrategy,
        skip_snapshots: bool,
    ):
        self.project = project
        self.domain = domain
        self.plan = plan
        self.error_strategy = error_strategy
        self.skip_snapshots = skip_snapshots
        self.issues: list[Issue] = []

        # ORM lookup caches (populated as entities get created/updated).
        self._source_systems: dict[tuple[str, str, str | None], SourceSystem] = {}
        self._source_tables_by_identifier: dict[str, SourceTable] = {}
        self._source_columns: dict[tuple[str, str], SourceColumn] = {}  # (table_id, col_name)
        self._groups: dict[str, Group] = {}
        self._hubs_by_name: dict[str, Hub] = {}
        self._links_by_name: dict[str, Link] = {}
        self._satellites_by_name: dict[str, Satellite] = {}
        self._default_snap_control: SnapshotControlTable | None = None
        self._default_snap_logic: SnapshotControlLogic | None = None
        # PIT snapshot logic resolved by (control name, trigger column).
        self._named_snap_logic: dict[tuple[str, str], SnapshotControlLogic] = {}

        # Pre-warm caches with anything already in the project.
        for ss in self.project.source_systems.all():
            self._source_systems[(ss.name, ss.schema_name, ss.database_name)] = ss
        for st in SourceTable.objects.filter(source_system__project=self.project):
            self._source_tables_by_identifier.setdefault(st.physical_table_name, st)
        for sc in SourceColumn.objects.filter(source_table__source_system__project=self.project):
            self._source_columns[(sc.source_table.physical_table_name, sc.source_column_physical_name)] = sc
        for g in self.project.groups.all():
            self._groups[g.group_name] = g
        for h in self.project.hubs.all():
            self._hubs_by_name[h.hub_physical_name] = h
        for l in self.project.links.all():
            self._links_by_name[l.link_physical_name] = l
        for s in self.project.satellites.all():
            self._satellites_by_name[s.satellite_physical_name] = s

    # ------------------------------------------------------------------ helpers
    def _record_error(
        self,
        *,
        code: str,
        message: str,
        entity_type: str,
        entity_name: str,
        suggestion: str | None = None,
    ) -> None:
        issue = make_issue(
            severity="error",
            code=code,
            message=message,
            stage="execute",
            entity=EntityRef(type=entity_type, name=entity_name),
            suggestion=suggestion,
        )
        self.issues.append(issue)
        if self.error_strategy == "fail_fast":
            raise PipelineAbort(issue)

    def _get_or_create_group(self, name: str | None) -> Group | None:
        if not name:
            return None
        if name in self._groups:
            return self._groups[name]
        group, _ = Group.objects.update_or_create(
            project=self.project,
            group_name=name,
        )
        self._groups[name] = group
        return group

    def _ensure_default_snapshot_control(self) -> SnapshotControlLogic | None:
        if self.skip_snapshots:
            return None
        if self._default_snap_logic is not None:
            return self._default_snap_logic

        existing_table = SnapshotControlTable.objects.filter(project=self.project).first()
        if existing_table is not None:
            self._default_snap_control = existing_table
            self._default_snap_logic = SnapshotControlLogic.objects.filter(
                snapshot_control_table=existing_table
            ).first()
            return self._default_snap_logic

        from datetime import date, time

        today = date.today()
        self._default_snap_control = SnapshotControlTable.objects.create(
            project=self.project,
            snapshot_start_date=date(today.year - 5, 1, 1),
            snapshot_end_date=date(today.year + 5, 12, 31),
            daily_snapshot_time=time(8, 0, 0),
        )
        self._default_snap_logic = SnapshotControlLogic.objects.create(
            snapshot_control_table=self._default_snap_control,
            snapshot_control_logic_column_name="is_active",
            snapshot_component=SnapshotControlLogic.SnapshotComponent.BEGINNING_OF_MONTH,
            snapshot_duration=1,
            snapshot_unit=SnapshotControlLogic.SnapshotUnit.YEAR,
            snapshot_forever=False,
        )
        return self._default_snap_logic

    def _logic_row_for(
        self, table: SnapshotControlTable, trigger_column: str | None
    ) -> SnapshotControlLogic:
        """Return the control's logic row for ``trigger_column`` (default is_active).

        Matches an existing row by column name (case-insensitive); creates one with
        that name if the control doesn't have it.
        """
        col = trigger_column or "is_active"
        existing = next(
            (
                logic
                for logic in SnapshotControlLogic.objects.filter(
                    snapshot_control_table=table
                )
                if logic.snapshot_control_logic_column_name.lower() == col.lower()
            ),
            None,
        )
        if existing is not None:
            return existing
        return SnapshotControlLogic.objects.create(
            snapshot_control_table=table,
            snapshot_control_logic_column_name=col,
            snapshot_component=SnapshotControlLogic.SnapshotComponent.BEGINNING_OF_MONTH,
            snapshot_duration=1,
            snapshot_unit=SnapshotControlLogic.SnapshotUnit.YEAR,
            snapshot_forever=False,
        )

    def _resolve_snapshot_control_for_pit(
        self, d: DPIT
    ) -> SnapshotControlLogic | None:
        """Link a PIT to a snapshot control logic row.

        The control table is chosen by ``snapshot_model_name``, matched by base name
        (trailing ``_v0``/``_v1`` stripped, case-insensitive) so version/case variants
        reuse the existing control instead of duplicating it; a new control is created
        only for a genuinely new base name. Within that control, the logic row is
        chosen by ``snapshot_trigger_column`` (default is_active), created if absent.
        Falls back to the project default control when neither is given.
        """
        if self.skip_snapshots:
            return None

        name = d.snapshot_control_name
        trigger = d.snapshot_logic_column
        if not name and not trigger:
            return self._ensure_default_snapshot_control()

        cache_key = (name or "", trigger or "")
        if cache_key in self._named_snap_logic:
            return self._named_snap_logic[cache_key]

        if name:
            table = self._get_or_create_snapshot_control_table(name)
        else:
            default_logic = self._ensure_default_snapshot_control()
            if default_logic is None:
                return None
            table = default_logic.snapshot_control_table

        logic = self._logic_row_for(table, trigger)
        self._named_snap_logic[cache_key] = logic
        return logic

    def _get_or_create_snapshot_control_table(
        self, name: str
    ) -> SnapshotControlTable:
        """Find a control table by base name (case-insensitive), or create it."""
        target_base = _snapshot_base_name(name)
        table = next(
            (
                t
                for t in SnapshotControlTable.objects.filter(project=self.project)
                if _snapshot_base_name(t.name) == target_base
            ),
            None,
        )
        if table is not None:
            return table

        from datetime import date, time

        today = date.today()
        return SnapshotControlTable.objects.create(
            project=self.project,
            name=name,
            snapshot_start_date=date(today.year - 5, 1, 1),
            snapshot_end_date=date(today.year + 5, 12, 31),
            daily_snapshot_time=time(8, 0, 0),
        )

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        # Execute deletes first to free up unique-constraint slots.
        for op in self.plan.ops:
            if isinstance(op, DeleteOp):
                self._apply_delete(op)

        for op in self.plan.ops:
            if isinstance(op, (CreateOp, UpdateOp)):
                self._apply_upsert(op)
            elif isinstance(op, SkipOp):
                continue  # already recorded in the plan

        # Default snapshot control is auto-created on demand (PITs etc.).
        # If we have any PITs in the domain and snap is not skipped, ensure one exists.
        if not self.skip_snapshots and self.domain.pits:
            self._ensure_default_snapshot_control()

    # --------------------------------------------------------------- dispatch
    def _apply_delete(self, op: DeleteOp) -> None:
        try:
            model_cls = _MODEL_FOR_DELETE.get(op.entity_type)
            if model_cls is None:
                return
            model_cls.objects.filter(pk=op.existing_pk).delete()
        except Exception as exc:  # pragma: no cover - very rare
            self._record_error(
                code=Code.EXECUTE_UNEXPECTED_ERROR,
                message=f"Failed to delete {op.entity_type} '{op.name}': {exc}",
                entity_type=op.entity_type,
                entity_name=op.name,
            )

    def _apply_upsert(self, op: CreateOp | UpdateOp) -> None:
        try:
            handler = _UPSERT_DISPATCH.get(op.entity_type)
            if handler is None:
                return
            handler(self, op)
        except IntegrityError as exc:
            self._record_error(
                code=Code.EXECUTE_CONSTRAINT_VIOLATION,
                message=f"Database constraint blocked {op.entity_type} '{op.name}': {exc}",
                entity_type=op.entity_type,
                entity_name=op.name,
                suggestion="Resolve the conflict in the source file and re-import.",
            )
        except Exception as exc:
            self._record_error(
                code=Code.EXECUTE_UNEXPECTED_ERROR,
                message=f"Unexpected error writing {op.entity_type} '{op.name}': {exc}",
                entity_type=op.entity_type,
                entity_name=op.name,
            )

    # ----------------------------------------------------------- source system
    def _upsert_source_system(self, op: CreateOp | UpdateOp) -> None:
        d: DSourceSystem = op.payload
        obj, _ = SourceSystem.objects.update_or_create(
            project=self.project,
            schema_name=d.schema_name,
            database_name=d.database_name,
            defaults={"name": d.name},
        )
        self._source_systems[(d.name, d.schema_name, d.database_name)] = obj

    # ------------------------------------------------------------ source table
    def _upsert_source_table(self, op: CreateOp | UpdateOp) -> None:
        sys_d, table_d = op.payload  # type: ignore[misc]
        # Find the SourceSystem we just created/updated.
        system = self._source_systems.get((sys_d.name, sys_d.schema_name, sys_d.database_name))
        if system is None:
            # If planning ran before us in update_only mode we may not have
            # created the system; bail with an Issue.
            self._record_error(
                code=Code.ENTITY_MISSING_SOURCE_TABLE,
                message=f"Cannot create source table '{table_d.physical_name}': system not found.",
                entity_type="source_table",
                entity_name=table_d.physical_name,
            )
            return

        obj, _ = SourceTable.objects.update_or_create(
            project=self.project,
            source_system=system,
            physical_table_name=table_d.physical_name,
            defaults={
                "alias": table_d.alias or "",
                "record_source_value": table_d.record_source_value or "",
                "load_date_value": table_d.load_date_value or "sysdate()",
                "static_part_of_record_source": table_d.static_part_of_record_source or "",
            },
        )
        # Cache under both physical name and identifier for lookups.
        self._source_tables_by_identifier[table_d.identifier] = obj
        self._source_tables_by_identifier.setdefault(table_d.physical_name, obj)

        for col in table_d.columns.values():
            sc, _ = SourceColumn.objects.update_or_create(
                source_table=obj,
                source_column_physical_name=col.name,
                defaults={"source_column_datatype": col.datatype or ""},
            )
            self._source_columns[(table_d.physical_name, col.name)] = sc
            self._source_columns[(table_d.identifier, col.name)] = sc

    def _ensure_source_column(self, table_identifier: str, col_name: str) -> SourceColumn | None:
        sc = self._source_columns.get((table_identifier, col_name))
        if sc is not None:
            return sc
        table = self._source_tables_by_identifier.get(table_identifier)
        if table is None:
            return None
        sc, _ = SourceColumn.objects.update_or_create(
            source_table=table,
            source_column_physical_name=col_name,
            defaults={"source_column_datatype": ""},
        )
        self._source_columns[(table_identifier, col_name)] = sc
        self._source_columns[(table.physical_table_name, col_name)] = sc
        return sc

    # -------------------------------------------------------------------- hub
    def _upsert_hub(self, op: CreateOp | UpdateOp) -> None:
        d: DHub = op.payload
        group = self._get_or_create_group(d.group_name)
        obj, _ = Hub.objects.update_or_create(
            project=self.project,
            hub_physical_name=d.physical_name,
            defaults={
                "hub_type": d.hub_type,
                "hub_hashkey_name": d.hashkey_name,
                "create_record_tracking_satellite": d.create_record_tracking_satellite,
                "create_effectivity_satellite": d.create_effectivity_satellite,
                "group": group,
            },
        )
        self._hubs_by_name[d.physical_name] = obj

        for hc in d.columns:
            hub_column, _ = HubColumn.objects.update_or_create(
                hub=obj,
                column_name=hc.name,
                defaults={
                    "column_type": hc.column_type,
                    **({"sort_order": hc.sort_order} if hc.sort_order is not None else {}),
                },
            )

            for mapping in hc.source_mappings:
                src_col = self._ensure_source_column(
                    mapping.source_table_identifier, mapping.source_column_name
                )
                if src_col is None:
                    self._record_error(
                        code=Code.ENTITY_MISSING_SOURCE_COLUMN,
                        message=(
                            f"Hub '{d.physical_name}' column '{hc.name}' references unknown "
                            f"source column '{mapping.source_table_identifier}.{mapping.source_column_name}'."
                        ),
                        entity_type="hub_source_mapping",
                        entity_name=f"{d.physical_name}.{hc.name}",
                    )
                    continue
                staging = get_or_create_staging_column(src_col)
                HubSourceMapping.objects.update_or_create(
                    hub_column=hub_column,
                    staging_column=staging,
                    defaults={"is_primary_source": mapping.is_primary_source},
                )

        # Ensure at least one primary source per hub column where mappings exist.
        for hc in obj.columns.all():
            mappings = HubSourceMapping.objects.filter(hub_column=hc)
            if mappings.exists() and not mappings.filter(is_primary_source=True).exists():
                first = mappings.first()
                if first is not None:
                    first.is_primary_source = True
                    first.save(update_fields=["is_primary_source"])

    # ------------------------------------------------------------------- link
    def _upsert_link(self, op: CreateOp | UpdateOp) -> None:
        d: DLink = op.payload
        group = self._get_or_create_group(d.group_name)
        obj, _ = Link.objects.update_or_create(
            project=self.project,
            link_physical_name=d.physical_name,
            defaults={
                "link_type": d.link_type,
                "link_hashkey_name": d.hashkey_name or "",
                "create_record_tracking_satellite": d.create_record_tracking_satellite,
                "group": group,
            },
        )
        self._links_by_name[d.physical_name] = obj

        # Hub references — clear and rebuild to keep ordering consistent.
        LinkHubReference.objects.filter(link=obj).delete()
        ref_objs: list[LinkHubReference] = []
        for ref_d in d.hub_references:
            hub = self._hubs_by_name.get(ref_d.hub_physical_name)
            if hub is None:
                self._record_error(
                    code=Code.ENTITY_MISSING_REFERENCE,
                    message=(
                        f"Link '{d.physical_name}' references hub "
                        f"'{ref_d.hub_physical_name}' which is not yet created."
                    ),
                    entity_type="link_hub_reference",
                    entity_name=f"{d.physical_name}->{ref_d.hub_physical_name}",
                )
                ref_objs.append(None)  # type: ignore[arg-type]
                continue
            lhr = LinkHubReference.objects.create(
                link=obj,
                hub=hub,
                hub_hashkey_alias_in_link=ref_d.hub_hashkey_alias_in_link or "",
                sort_order=ref_d.sort_order or 0,
            )
            ref_objs.append(lhr)

        # Hub source mappings
        for m in d.hub_source_mappings:
            if m.link_hub_ref_index >= len(ref_objs) or ref_objs[m.link_hub_ref_index] is None:
                continue
            lhr = ref_objs[m.link_hub_ref_index]
            hub_col = HubColumn.objects.filter(
                hub=lhr.hub, column_name=m.hub_column_name
            ).first()
            if hub_col is None:
                continue
            src_col = self._ensure_source_column(
                m.source_table_identifier, m.source_column_name
            )
            if src_col is None:
                continue
            LinkHubSourceMapping.objects.update_or_create(
                link_hub_reference=lhr,
                standard_hub_column=hub_col,
                defaults={"staging_column": get_or_create_staging_column(src_col)},
            )

        # Payload / additional columns
        for col_d in d.columns:
            lc, _ = LinkColumn.objects.update_or_create(
                link=obj,
                column_name=col_d.name,
                defaults={
                    "column_type": col_d.column_type,
                    "sort_order": col_d.sort_order or 0,
                },
            )
            for sm in col_d.source_mappings:
                src_col = self._ensure_source_column(
                    sm.source_table_identifier, sm.source_column_name
                )
                if src_col is None:
                    continue
                LinkSourceMapping.objects.update_or_create(
                    link_column=lc,
                    staging_column=get_or_create_staging_column(src_col),
                )

    # ------------------------------------------------------------ satellite
    def _upsert_satellite(self, op: CreateOp | UpdateOp) -> None:
        d: DSatellite = op.payload
        parent_hub = self._hubs_by_name.get(d.parent_entity_name) if d.parent_entity_type == "hub" else None
        parent_link = self._links_by_name.get(d.parent_entity_name) if d.parent_entity_type == "link" else None
        if not parent_hub and not parent_link:
            self._record_error(
                code=Code.ENTITY_MISSING_PARENT,
                message=(
                    f"Satellite '{d.physical_name}' parent "
                    f"'{d.parent_entity_name}' is not yet created."
                ),
                entity_type="satellite",
                entity_name=d.physical_name,
            )
            return

        source_table = self._source_tables_by_identifier.get(d.source_table_identifier)
        if source_table is None:
            self._record_error(
                code=Code.ENTITY_MISSING_SOURCE_TABLE,
                message=(
                    f"Satellite '{d.physical_name}' source table "
                    f"'{d.source_table_identifier}' is not defined."
                ),
                entity_type="satellite",
                entity_name=d.physical_name,
            )
            return

        group = self._get_or_create_group(d.group_name)
        obj, _ = Satellite.objects.update_or_create(
            project=self.project,
            satellite_physical_name=d.physical_name,
            defaults={
                "satellite_type": d.satellite_type,
                "parent_hub": parent_hub,
                "parent_link": parent_link,
                "source_table": source_table,
                "group": group,
            },
        )
        self._satellites_by_name[d.physical_name] = obj

        # Sort columns: explicit sort orders first to avoid (sat, sort_order) collisions.
        ordered_cols = sorted(
            d.columns,
            key=lambda c: (c.sort_order is None, c.sort_order or 0),
        )

        for col_d in ordered_cols:
            src_col = self._ensure_source_column(
                d.source_table_identifier, col_d.source_column_name
            )
            if src_col is None:
                continue
            staging = get_or_create_staging_column(src_col)
            target = col_d.target_column_name
            if target == col_d.source_column_name:
                target = None
            SatelliteColumn.objects.update_or_create(
                satellite=obj,
                staging_column=staging,
                defaults={
                    "is_multi_active_key": col_d.is_multi_active_key,
                    "include_in_delta_detection": col_d.include_in_delta_detection,
                    "target_column_name": target,
                    **(
                        {"column_sort_order": col_d.sort_order}
                        if col_d.sort_order is not None
                        else {}
                    ),
                },
            )

    # -------------------------------------------------------- reference table
    def _upsert_reference_table(self, op: CreateOp | UpdateOp) -> None:
        d: DReferenceTable = op.payload
        hub = self._hubs_by_name.get(d.reference_hub_name)
        if hub is None:
            self._record_error(
                code=Code.ENTITY_MISSING_REFERENCE,
                message=(
                    f"Reference table '{d.physical_name}' references hub "
                    f"'{d.reference_hub_name}' which is not yet created."
                ),
                entity_type="reference_table",
                entity_name=d.physical_name,
            )
            return

        group = self._get_or_create_group(d.group_name)
        rt, _ = ReferenceTable.objects.update_or_create(
            project=self.project,
            reference_table_physical_name=d.physical_name,
            defaults={
                "reference_hub": hub,
                "historization_type": d.historization_type,
                "group": group,
            },
        )

        # Satellite assignment (single satellite per ref table in our IR).
        if d.referenced_satellite_name:
            sat = self._satellites_by_name.get(d.referenced_satellite_name)
            if sat is not None:
                from engine.models import ReferenceTableSatelliteAssignment

                ReferenceTableSatelliteAssignment.objects.update_or_create(
                    reference_table=rt,
                    reference_satellite=sat,
                )

    # --------------------------------------------------------------------- PIT
    def _upsert_pit(self, op: CreateOp | UpdateOp) -> None:
        d: DPIT = op.payload
        hub = self._hubs_by_name.get(d.tracked_entity_name) if d.tracked_entity_type == "hub" else None
        link = self._links_by_name.get(d.tracked_entity_name) if d.tracked_entity_type == "link" else None
        if not hub and not link:
            self._record_error(
                code=Code.ENTITY_MISSING_REFERENCE,
                message=(
                    f"PIT '{d.physical_name}' tracks unknown entity "
                    f"'{d.tracked_entity_name}'."
                ),
                entity_type="pit",
                entity_name=d.physical_name,
            )
            return

        snap_logic = self._resolve_snapshot_control_for_pit(d)
        if snap_logic is None:
            # In skip_snapshots mode we just skip PITs.
            return

        group = self._get_or_create_group(d.group_name)
        pit, _ = PIT.objects.update_or_create(
            project=self.project,
            pit_physical_name=d.physical_name,
            defaults={
                "tracked_entity_type": d.tracked_entity_type,
                "tracked_hub": hub,
                "tracked_link": link,
                "snapshot_control_table": snap_logic.snapshot_control_table,
                "snapshot_control_logic": snap_logic,
                "dimension_key_column_name": d.dimension_key_column_name,
                "pit_type": d.pit_type,
                "custom_record_source": d.custom_record_source,
                "group": group,
            },
        )

        # Link the satellites tracked by this PIT (M2M).
        sats = []
        for sat_name in d.satellite_names:
            sat = self._satellites_by_name.get(sat_name)
            if sat is None:
                self._record_error(
                    code=Code.ENTITY_MISSING_REFERENCE,
                    message=(
                        f"PIT '{d.physical_name}' references satellite "
                        f"'{sat_name}' which is not defined."
                    ),
                    entity_type="pit",
                    entity_name=d.physical_name,
                )
                continue
            sats.append(sat)
        pit.satellites.set(sats)


# ---------------------------------------------------------------------------
# Dispatch tables
# ---------------------------------------------------------------------------


_UPSERT_DISPATCH = {
    "source_system": _Executor._upsert_source_system,
    "source_table": _Executor._upsert_source_table,
    "hub": _Executor._upsert_hub,
    "link": _Executor._upsert_link,
    "satellite": _Executor._upsert_satellite,
    "reference_table": _Executor._upsert_reference_table,
    "pit": _Executor._upsert_pit,
}


_MODEL_FOR_DELETE = {
    "source_system": SourceSystem,
    "source_table": SourceTable,
    "hub": Hub,
    "link": Link,
    "satellite": Satellite,
    "reference_table": ReferenceTable,
    "pit": PIT,
}
