"""
Stage 5: executor.

Applies an ExecutionPlan to the database inside a single atomic transaction,
and reports what it did for every planned entity.

Every row is written through the change-aware helpers in `changes.py`: a row
that already matches the source is not written at all, and each difference
is recorded against the entity being applied. A dry run executes the same
plan and rolls the transaction back, so its report is exactly what the
import would do.

Each entity is applied in its own savepoint. In `fail_fast` the first error
raises PipelineAbort and the whole transaction rolls back. In `best_effort`
an entity that fails is rolled back on its own and reported as skipped, and
the executor carries on with the rest.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, connection, transaction

from engine.models import (
    PIT,
    DerivedColumn,
    Group,
    Hub,
    HubColumn,
    HubSourceMapping,
    Link,
    LinkColumn,
    LinkHubReference,
    LinkHubSourceMapping,
    LinkSourceMapping,
    PrejoinDefinition,
    PrejoinExtractionColumn,
    Project,
    ReferenceTable,
    ReferenceTableSatelliteAssignment,
    Satellite,
    SatelliteColumn,
    SnapshotControlLogic,
    SnapshotControlTable,
    SourceColumn,
    SourceSystem,
    SourceTable,
    StagingColumn,
)
from engine.services.imports.changes import (
    LOOKUP,
    OpOutcome,
    remove,
    sync_members,
    upsert,
)
from engine.services.imports.domain import (
    DPIT,
    DHub,
    DLink,
    DomainModel,
    DPrejoin,
    DReferenceTable,
    DSatellite,
    DSourceSystem,
)
from engine.services.imports.errors import Code, PipelineAbort, make_issue
from engine.services.imports.planner import (
    CreateOp,
    DeleteOp,
    ExecutionPlan,
    UpdateOp,
)
from engine.services.imports.staging_helpers import get_or_create_staging_column
from engine.services.imports.types import (
    EntityRef,
    ErrorStrategy,
    ImportPlan,
    Issue,
    PlanCounts,
    PlanState,
)


def _only_supplied(**fields: Any) -> dict[str, Any]:
    """The fields a source actually supplied.

    None means the format has no place for the field (see domain.py), so the
    value the project has is kept rather than cleared.
    """
    return {name: value for name, value in fields.items() if value is not None}


def _snapshot_base_name(name: str) -> str:
    """Base name of a snapshot control: trailing _v0/_v1 stripped, lowercased."""
    lowered = (name or "").lower()
    for suffix in ("_v0", "_v1"):
        if lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


@dataclass(slots=True)
class ExecutionResult:
    issues: list[Issue]
    # One per plan op, in plan order; None for the ops that were skipped.
    outcomes: list[OpOutcome | None]


def execute_plan(
    *,
    project: Project,
    domain: DomainModel,
    plan: ExecutionPlan,
    error_strategy: ErrorStrategy,
    skip_snapshots: bool,
    dry_run: bool = False,
) -> ExecutionResult:
    """Apply the plan to the database; return the issues and what each op did.

    The whole call runs in a single atomic transaction. On `fail_fast` the
    first error issue is raised as PipelineAbort and the runner rolls back.
    On `best_effort` the executor continues past per-entity errors and the
    transaction commits at the end with whatever succeeded. A dry run
    always rolls back.
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
        _check_deferred_constraints()
        if dry_run:
            transaction.set_rollback(True)
    return ExecutionResult(issues=executor.issues, outcomes=executor.outcomes)


def _check_deferred_constraints() -> None:
    """Surface foreign keys that would fail at COMMIT, which a dry run never reaches.

    SQLite can only check the whole database, which would also flag rows the
    import didn't touch, so it is left to COMMIT there.
    """
    if connection.vendor == "sqlite":
        return
    try:
        connection.check_constraints()
    except IntegrityError as exc:
        raise PipelineAbort(
            make_issue(
                severity="error",
                code=Code.EXECUTE_CONSTRAINT_VIOLATION,
                stage="execute",
                message=f"The import would leave broken references: {exc}",
            )
        ) from exc


# Why an entity whose row was never written is left out, by the first error
# recorded for it. Matches the resolver's skip reasons where they overlap.
_SKIP_REASON_BY_CODE: dict[str, str] = {
    Code.ENTITY_MISSING_SOURCE_TABLE: "missing_source_table",
    Code.ENTITY_MISSING_PARENT: "missing_parent",
    Code.ENTITY_MISSING_REFERENCE: "missing_reference",
    Code.ENTITY_MISSING_SOURCE_COLUMN: "missing_reference",
    Code.ENTITY_INVALID_CONFIGURATION: "invalid_configuration",
}


def apply_outcomes(
    plan: ImportPlan,
    exec_plan: ExecutionPlan,
    outcomes: list[OpOutcome | None],
    *,
    state: PlanState,
) -> None:
    """Turn the planned actions into what the executor actually did.

    An entity that exists is only `update` if something about it changed,
    else `unchanged`; one that could not be written is a `skip`.
    """
    for entity, op, outcome in zip(plan.entities, exec_plan.ops, outcomes, strict=True):
        if outcome is None:
            continue
        if outcome.failed is not None:
            entity.action = "skip"
            entity.skip_reason = outcome.failed
            entity.changes = []
        elif isinstance(op, DeleteOp):
            continue
        elif not outcome.touched:
            entity.action = "skip"
            entity.skip_reason = next(
                (
                    _SKIP_REASON_BY_CODE[code]
                    for code in outcome.error_codes
                    if code in _SKIP_REASON_BY_CODE
                ),
                "execute_failed",
            )
            entity.changes = []
        elif outcome.created:
            entity.action = "create"
            entity.changes = []
        else:
            entity.action = "update" if outcome.changes else "unchanged"
            entity.changes = list(outcome.changes)
    plan.counts = PlanCounts.from_entities(plan.entities)
    plan.state = state


_MISSING: Any = object()


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
        self.outcomes: list[OpOutcome | None] = [None] * len(plan.ops)
        # The outcome of the op being applied, and how to undo the cache
        # writes it made if it has to be rolled back.
        self._current: OpOutcome | None = None
        self._journal: list[Callable[[], None]] = []

        # ORM lookup caches, warmed after the deletes (see run) and kept up to
        # date as entities get created/updated.
        self._source_systems: dict[tuple[str, str, str | None], SourceSystem] = {}
        self._source_tables_by_identifier: dict[str, SourceTable] = {}
        # Existing tables by (system pk, physical name), and their columns and
        # derived columns by name, so a table costs no queries of its own.
        self._tables_by_key: dict[tuple[Any, str], SourceTable] = {}
        self._columns_by_table: dict[Any, dict[str, SourceColumn]] = {}
        self._derived_by_table: dict[Any, dict[str, DerivedColumn]] = {}
        self._source_columns: dict[tuple[str, str], SourceColumn] = (
            {}
        )  # (table_id, col_name)
        # Derived columns by (source table pk, lowercased name).
        self._derived_columns: dict[tuple[Any, str], DerivedColumn] = {}
        self._groups: dict[str, Group] = {}
        self._hubs_by_name: dict[str, Hub] = {}
        self._hub_columns: dict[tuple[Any, str], HubColumn] = {}
        self._links_by_name: dict[str, Link] = {}
        self._satellites_by_name: dict[str, Satellite] = {}
        # Staging columns by (column model name, column pk), and a readable
        # "table.column" label for each, used in change paths.
        self._staging: dict[tuple[str, Any], StagingColumn] = {}
        self._staging_labels: dict[Any, str] = {}
        # The outcome of the op that wrote each source table, so a source
        # column another entity's mapping creates is reported on its table.
        self._table_outcomes: dict[Any, OpOutcome] = {}
        # Prejoin extraction columns keyed by
        # (source table pk, target table pk, staged column name lowercased),
        # i.e. how a link mapping names them. Lets a prejoin-fed business key
        # bind to the extraction instead of inventing a source column.
        self._prejoin_extractions: dict[
            tuple[Any, Any, str], PrejoinExtractionColumn
        ] = {}
        self._default_snap_control: SnapshotControlTable | None = None
        self._default_snap_logic: SnapshotControlLogic | None = None
        # PIT snapshot logic resolved by (control name, trigger column).
        self._named_snap_logic: dict[tuple[str, str], SnapshotControlLogic] = {}

    def _warm_caches(self) -> None:
        """Load what the project already has into the lookup caches."""
        for ss in self.project.source_systems.all():
            self._source_systems[(ss.name, ss.schema_name, ss.database_name)] = ss
        for st in SourceTable.objects.filter(source_system__project=self.project):
            self._source_tables_by_identifier.setdefault(st.physical_table_name, st)
            self._tables_by_key[(st.source_system_id, st.physical_table_name)] = st
            self._columns_by_table[st.pk] = {}
            self._derived_by_table[st.pk] = {}
        for sc in SourceColumn.objects.filter(
            source_table__source_system__project=self.project
        ).select_related("source_table"):
            self._source_columns[
                (sc.source_table.physical_table_name, sc.source_column_physical_name)
            ] = sc
            self._columns_by_table.setdefault(sc.source_table_id, {})[
                sc.source_column_physical_name
            ] = sc
        for derived in DerivedColumn.objects.filter(project=self.project):
            self._derived_columns[
                (derived.source_table_id, derived.column_name.lower())
            ] = derived
            self._derived_by_table.setdefault(derived.source_table_id, {})[
                derived.column_name
            ] = derived
        for staging in StagingColumn.objects.filter(project=self.project):
            if staging.source_column_id:
                self._staging[("SourceColumn", staging.source_column_id)] = staging
            elif staging.prejoin_column_id:
                self._staging[
                    ("PrejoinExtractionColumn", staging.prejoin_column_id)
                ] = staging
            elif staging.derived_column_id:
                self._staging[("DerivedColumn", staging.derived_column_id)] = staging
        for g in self.project.groups.all():
            self._groups[g.group_name] = g
        for h in self.project.hubs.all():
            self._hubs_by_name[h.hub_physical_name] = h
        for link in self.project.links.all():
            self._links_by_name[link.link_physical_name] = link
        for s in self.project.satellites.all():
            self._satellites_by_name[s.satellite_physical_name] = s
        for ext in PrejoinExtractionColumn.objects.filter(
            prejoin__project=self.project
        ).select_related("prejoin", "source_column"):
            self._prejoin_extractions[self._extraction_key(ext)] = ext

    # ------------------------------------------------------------ journal
    def _cache(self, cache: dict, key: Any, value: Any) -> None:
        """Put ``value`` in a cache, undoably: a rolled-back op must not leave
        later ones pointing at rows that no longer exist."""
        previous = cache.get(key, _MISSING)

        def undo() -> None:
            if previous is _MISSING:
                cache.pop(key, None)
            else:
                cache[key] = previous

        self._journal.append(undo)
        cache[key] = value

    def _cache_default(self, cache: dict, key: Any, value: Any) -> None:
        if key not in cache:
            self._cache(cache, key, value)

    def _set(self, attr: str, value: Any) -> None:
        previous = getattr(self, attr)
        self._journal.append(lambda: setattr(self, attr, previous))
        setattr(self, attr, value)

    def _undo(self) -> None:
        while self._journal:
            self._journal.pop()()

    # ------------------------------------------------------------ writes
    def _upsert(
        self,
        model: type,
        *,
        lookup: Mapping[str, Any],
        values: Mapping[str, Any],
        create_values: Mapping[str, Any] | None = None,
        existing: Any = LOOKUP,
        path: tuple[str, ...] = (),
        outcome: OpOutcome | None = None,
    ) -> tuple[Any, bool]:
        target = outcome or self._current
        assert target is not None
        recorded = len(target.changes)
        obj, created = upsert(
            model,
            lookup=lookup,
            values=values,
            outcome=target,
            create_values=create_values,
            existing=existing,
            path=path,
        )
        if target is not self._current and len(target.changes) > recorded:
            # A change reported on another entity must go if this op is undone.
            added = target.changes[recorded:]
            self._journal.append(
                lambda: [target.changes.remove(change) for change in added]
            )
        return obj, created

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
        if self._current is not None:
            self._current.error_codes.append(code)
        if self.error_strategy == "fail_fast":
            raise PipelineAbort(issue)

    def _get_or_create_group(self, name: str | None) -> Group | None:
        if not name:
            return None
        if name in self._groups:
            return self._groups[name]
        group, _ = Group.objects.get_or_create(project=self.project, group_name=name)
        self._cache(self._groups, name, group)
        return group

    def _ensure_default_snapshot_control(self) -> SnapshotControlLogic | None:
        if self.skip_snapshots:
            return None
        if self._default_snap_logic is not None:
            return self._default_snap_logic

        existing_table = SnapshotControlTable.objects.filter(
            project=self.project
        ).first()
        if existing_table is not None:
            self._set("_default_snap_control", existing_table)
            self._set(
                "_default_snap_logic",
                SnapshotControlLogic.objects.filter(
                    snapshot_control_table=existing_table
                ).first(),
            )
            return self._default_snap_logic

        from datetime import date, time

        today = date.today()
        control = SnapshotControlTable.objects.create(
            project=self.project,
            snapshot_start_date=date(today.year - 5, 1, 1),
            snapshot_end_date=date(today.year + 5, 12, 31),
            daily_snapshot_time=time(8, 0, 0),
        )
        self._set("_default_snap_control", control)
        self._set(
            "_default_snap_logic",
            SnapshotControlLogic.objects.create(
                snapshot_control_table=control,
                snapshot_control_logic_column_name="is_active",
                snapshot_component=SnapshotControlLogic.SnapshotComponent.BEGINNING_OF_MONTH,
                snapshot_duration=1,
                snapshot_unit=SnapshotControlLogic.SnapshotUnit.YEAR,
                snapshot_forever=False,
            ),
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

    def _resolve_snapshot_control_for_pit(self, d: DPIT) -> SnapshotControlLogic | None:
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
        self._cache(self._named_snap_logic, cache_key, logic)
        return logic

    def _get_or_create_snapshot_control_table(self, name: str) -> SnapshotControlTable:
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
        for index, op in enumerate(self.plan.ops):
            if isinstance(op, DeleteOp):
                self._run_op(index, op, self._apply_delete)

        # Only now: a delete cascades, and the caches must not hold what it took.
        self._warm_caches()

        for index, op in enumerate(self.plan.ops):
            if isinstance(op, (CreateOp, UpdateOp)):
                self._run_op(index, op, self._apply_upsert)
            # SkipOps are already recorded in the plan.

        # Default snapshot control is auto-created on demand (PITs etc.).
        # If we have any PITs in the domain and snap is not skipped, ensure one exists.
        if not self.skip_snapshots and self.domain.pits:
            self._ensure_default_snapshot_control()

    def _run_op(self, index: int, op: Any, apply: Callable[[Any], None]) -> None:
        """Apply one op in its own savepoint, recording what it did.

        An exception rolls back this entity alone, undoes its cache writes and
        reports it as skipped; the other entities are unaffected.
        """
        outcome = OpOutcome()
        self.outcomes[index] = outcome
        self._current = outcome
        self._journal = []
        try:
            with transaction.atomic():
                apply(op)
        except PipelineAbort:
            raise
        except IntegrityError as exc:
            self._fail(
                op,
                outcome,
                code=Code.EXECUTE_CONSTRAINT_VIOLATION,
                message=f"Database constraint blocked {op.entity_type} '{op.name}': {exc}",
                suggestion="Resolve the conflict in the source file and re-import.",
            )
        except Exception as exc:
            self._fail(
                op,
                outcome,
                code=Code.EXECUTE_UNEXPECTED_ERROR,
                message=f"Unexpected error writing {op.entity_type} '{op.name}': {exc}",
            )
        finally:
            self._current = None
            self._journal = []

    def _fail(
        self,
        op: Any,
        outcome: OpOutcome,
        *,
        code: str,
        message: str,
        suggestion: str | None = None,
    ) -> None:
        self._undo()
        outcome.failed = "execute_failed"
        outcome.changes.clear()
        self._record_error(
            code=code,
            message=message,
            entity_type=op.entity_type,
            entity_name=op.name,
            suggestion=suggestion,
        )

    # --------------------------------------------------------------- dispatch
    def _apply_delete(self, op: DeleteOp) -> None:
        model_cls = _MODEL_FOR_DELETE.get(op.entity_type)
        if model_cls is None:
            return
        model_cls.objects.filter(pk=op.existing_pk).delete()

    def _apply_upsert(self, op: CreateOp | UpdateOp) -> None:
        handler = _UPSERT_DISPATCH.get(op.entity_type)
        if handler is None:
            return
        handler(self, op)

    # ----------------------------------------------------------- source system
    def _upsert_source_system(self, op: CreateOp | UpdateOp) -> None:
        d: DSourceSystem = op.payload
        # Keyed like the table's unique constraint: a system is where it lives,
        # and a new name for it is a rename.
        obj, _ = self._upsert(
            SourceSystem,
            lookup={
                "project": self.project,
                "schema_name": d.schema_name,
                "database_name": d.database_name,
            },
            values={
                "name": d.name,
                **_only_supplied(
                    description=d.description,
                    record_source_value=d.record_source_value,
                    static_part_of_record_source=d.static_part_of_record_source,
                    load_date_value=d.load_date_value,
                ),
            },
        )
        self._cache(self._source_systems, (d.name, d.schema_name, d.database_name), obj)

    # ------------------------------------------------------------ source table
    def _upsert_source_table(self, op: CreateOp | UpdateOp) -> None:
        sys_d, table_d = op.payload  # type: ignore[misc]
        # Find the SourceSystem we just created/updated.
        system = self._source_systems.get(
            (sys_d.name, sys_d.schema_name, sys_d.database_name)
        )
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

        table_key = (system.pk, table_d.physical_name)
        obj, _ = self._upsert(
            SourceTable,
            lookup={
                "project": self.project,
                "source_system": system,
                "physical_table_name": table_d.physical_name,
            },
            # A value the source leaves out keeps what the table has, so a
            # re-import doesn't undo what was set in the meantime.
            values=_only_supplied(
                alias=table_d.alias,
                record_source_value=table_d.record_source_value,
                load_date_value=table_d.load_date_value,
                static_part_of_record_source=table_d.static_part_of_record_source,
                description=table_d.description,
            ),
            existing=self._tables_by_key.get(table_key, LOOKUP),
        )
        self._cache(self._tables_by_key, table_key, obj)
        self._cache(self._table_outcomes, obj.pk, self._current)
        # Cache under both physical name and identifier for lookups.
        self._cache(self._source_tables_by_identifier, table_d.identifier, obj)
        self._cache_default(
            self._source_tables_by_identifier, table_d.physical_name, obj
        )
        # The table's rows by name, kept current for a table the source
        # describes twice (e.g. under two identifiers).
        columns = self._columns_by_table.setdefault(obj.pk, {})
        derived_columns = self._derived_by_table.setdefault(obj.pk, {})

        # Derived columns first: a mapped column with a derived column's name
        # is that derived column, not a source column to create.
        for derived_d in (table_d.derived_columns or {}).values():
            derived, _ = self._upsert(
                DerivedColumn,
                lookup={"source_table": obj, "column_name": derived_d.name},
                values={
                    "expression": derived_d.expression,
                    "datatype": derived_d.datatype or None,
                    "description": derived_d.description or None,
                },
                create_values={"project": self.project},
                existing=derived_columns.get(derived_d.name),
                path=("derived_columns", derived_d.name),
            )
            self._cache(derived_columns, derived_d.name, derived)
            self._cache(
                self._derived_columns, (obj.pk, derived_d.name.lower()), derived
            )

        for col in table_d.columns.values():
            if (obj.pk, col.name.lower()) in self._derived_columns:
                continue
            sc, _ = self._upsert(
                SourceColumn,
                lookup={"source_table": obj, "source_column_physical_name": col.name},
                # A column whose type the format doesn't carry (Excel creates
                # them from mappings) keeps the type the project has.
                values=_only_supplied(
                    source_column_datatype=col.datatype,
                    description=col.description,
                ),
                create_values={"source_column_datatype": ""},
                existing=columns.get(col.name),
                path=("columns", col.name),
            )
            self._cache(columns, col.name, sc)
            self._cache(self._source_columns, (table_d.physical_name, col.name), sc)
            self._cache(self._source_columns, (table_d.identifier, col.name), sc)

    def _ensure_source_column(
        self, table_identifier: str, col_name: str
    ) -> SourceColumn | None:
        """The source column a mapping names, created if the table lacks it.

        Never changes a column that exists: the mapping says nothing about its
        type or description.
        """
        sc = self._source_columns.get((table_identifier, col_name))
        if sc is not None:
            return sc
        table = self._source_tables_by_identifier.get(table_identifier)
        if table is None:
            return None
        sc, _ = self._upsert(
            SourceColumn,
            lookup={"source_table": table, "source_column_physical_name": col_name},
            values={},
            create_values={"source_column_datatype": ""},
            path=("columns", col_name),
            # A column the mapping adds is a change to its table.
            outcome=self._table_outcomes.get(table.pk),
        )
        self._cache(self._source_columns, (table_identifier, col_name), sc)
        self._cache(self._source_columns, (table.physical_table_name, col_name), sc)
        return sc

    def _staging_for(
        self, column: SourceColumn | PrejoinExtractionColumn | DerivedColumn, label: str
    ) -> StagingColumn:
        key = (type(column).__name__, column.pk)
        staging = self._staging.get(key)
        if staging is None:
            staging = get_or_create_staging_column(column)
            self._cache(self._staging, key, staging)
        self._staging_labels[staging.pk] = label
        return staging

    def _staging_label(self, staging: StagingColumn) -> str:
        """``table.column`` for a staging column, as change paths name it."""
        label = self._staging_labels.get(staging.pk)
        if label is None:
            label = (
                f"{staging.source_table.physical_table_name}.{staging.physical_name}"
            )
            self._staging_labels[staging.pk] = label
        return label

    def _resolve_staging_column(
        self, table_identifier: str, col_name: str
    ) -> StagingColumn | None:
        """The staging column a mapping names on a source table.

        A derived column of the table if there is one by that name, else the
        source column (created if absent, as before).
        """
        table = self._source_tables_by_identifier.get(table_identifier)
        if table is not None:
            derived = self._derived_columns.get((table.pk, col_name.lower()))
            if derived is not None:
                return self._staging_for(
                    derived, f"{table.physical_table_name}.{derived.column_name}"
                )
        src_col = self._ensure_source_column(table_identifier, col_name)
        if src_col is None:
            return None
        table_name = (
            table.physical_table_name if table is not None else table_identifier
        )
        return self._staging_for(
            src_col, f"{table_name}.{src_col.source_column_physical_name}"
        )

    # ---------------------------------------------------------------- prejoin
    @staticmethod
    def _extraction_key(ext: PrejoinExtractionColumn) -> tuple[Any, Any, str]:
        """Index an extraction column under the name a link mapping would use.

        That is the alias when one is set, else the target column's physical
        name — the same rule ``StagingColumn.physical_name`` applies, which is
        what the exporter writes into ``LinkColumnMapping.source_column_name``.
        """
        return (
            ext.prejoin.source_table_id,
            ext.prejoin.prejoin_target_table_id,
            _staged_name(ext).lower(),
        )

    def _find_source_column(
        self, table_identifier: str, col_name: str
    ) -> SourceColumn | None:
        """Look up an existing source column without creating it.

        Falls back to a case-insensitive match, because column names travel
        through the export as free text and casing is not always preserved.
        """
        sc = self._source_columns.get((table_identifier, col_name))
        if sc is not None:
            return sc
        table = self._source_tables_by_identifier.get(table_identifier)
        if table is None:
            return None
        return next(
            (
                col
                for col in SourceColumn.objects.filter(source_table=table)
                if col.source_column_physical_name.lower() == col_name.lower()
            ),
            None,
        )

    def _find_prejoin_extraction(
        self, source_table_identifier: str, target_table_identifier: str, col_name: str
    ) -> PrejoinExtractionColumn | None:
        source_table = self._source_tables_by_identifier.get(source_table_identifier)
        target_table = self._source_tables_by_identifier.get(target_table_identifier)
        if source_table is None or target_table is None:
            return None
        return self._prejoin_extractions.get(
            (source_table.pk, target_table.pk, col_name.lower())
        )

    def _upsert_prejoin(self, op: CreateOp | UpdateOp) -> None:
        d: DPrejoin = op.payload

        source_table = self._source_tables_by_identifier.get(d.source_table_identifier)
        target_table = self._source_tables_by_identifier.get(d.target_table_identifier)
        if source_table is None or target_table is None:
            missing = (
                d.source_table_identifier
                if source_table is None
                else d.target_table_identifier
            )
            self._record_error(
                code=Code.ENTITY_MISSING_SOURCE_TABLE,
                message=(
                    f"Prejoin '{op.name}' references source table "
                    f"'{missing}' which is not defined."
                ),
                entity_type="prejoin",
                entity_name=op.name,
            )
            return

        # The join condition is stored as two parallel M2M sets, so the two
        # sides must line up. A partially resolved condition would silently
        # join on the wrong columns, so refuse the whole prejoin instead.
        if not d.source_join_columns or len(d.source_join_columns) != len(
            d.target_join_columns
        ):
            self._record_error(
                code=Code.ENTITY_INVALID_CONFIGURATION,
                message=(
                    f"Prejoin '{op.name}' needs at least one join condition with "
                    f"matching source and target columns (got "
                    f"{len(d.source_join_columns)} source, "
                    f"{len(d.target_join_columns)} target)."
                ),
                entity_type="prejoin",
                entity_name=op.name,
                suggestion="Fix the prejoin's join_conditions and re-import.",
            )
            return

        source_cols: list[SourceColumn] = []
        target_cols: list[SourceColumn] = []
        for identifier, names, bucket in (
            (d.source_table_identifier, d.source_join_columns, source_cols),
            (d.target_table_identifier, d.target_join_columns, target_cols),
        ):
            for name in names:
                # Deliberately not _ensure_source_column: a join condition on an
                # invented column is worse than no prejoin at all.
                col = self._find_source_column(identifier, name)
                if col is None:
                    self._record_error(
                        code=Code.ENTITY_MISSING_SOURCE_COLUMN,
                        message=(
                            f"Prejoin '{op.name}' joins on unknown source column "
                            f"'{identifier}.{name}'."
                        ),
                        entity_type="prejoin",
                        entity_name=op.name,
                    )
                    return
                bucket.append(col)

        operator = (d.operator or "AND").upper()
        if operator not in PrejoinDefinition.JoinOperator.values:
            operator = PrejoinDefinition.JoinOperator.AND

        obj, created = self._upsert(
            PrejoinDefinition,
            lookup={
                "project": self.project,
                "source_table": source_table,
                "prejoin_target_table": target_table,
            },
            values={"prejoin_operator": operator},
        )
        # A changed join condition replaces the old one rather than
        # accumulating alongside it on re-import.
        for relation, columns in (
            ("prejoin_condition_source_column", source_cols),
            ("prejoin_condition_target_column", target_cols),
        ):
            sync_members(
                obj,
                relation,
                columns,
                key=lambda column: column.source_column_physical_name,
                outcome=self._current,
            )

        existing_extractions = (
            {}
            if created
            else {
                ext.source_column_id: ext
                for ext in obj.extraction_columns.select_related("source_column")
            }
        )
        for ext_d in d.extraction_columns:
            src_col = self._find_source_column(
                d.target_table_identifier, ext_d.source_column_name
            )
            if src_col is None:
                self._record_error(
                    code=Code.ENTITY_MISSING_SOURCE_COLUMN,
                    message=(
                        f"Prejoin '{op.name}' extracts unknown source column "
                        f"'{d.target_table_identifier}.{ext_d.source_column_name}'."
                    ),
                    entity_type="prejoin_extraction_column",
                    entity_name=f"{op.name}.{ext_d.source_column_name}",
                )
                continue
            # The exporter always writes an alias, defaulting it to the physical
            # column name. Normalise that back to None so an export -> import
            # round trip reproduces the original row rather than inventing a
            # redundant alias. Mirrors target_column_name in _upsert_satellite.
            alias = ext_d.alias
            if alias == src_col.source_column_physical_name:
                alias = None
            ext, _ = self._upsert(
                PrejoinExtractionColumn,
                lookup={"prejoin": obj, "source_column": src_col},
                values={"prejoin_target_column_alias": alias},
                existing=existing_extractions.get(src_col.pk),
                path=("extraction_columns", src_col.source_column_physical_name),
            )
            existing_extractions[src_col.pk] = ext
            self._cache(self._prejoin_extractions, self._extraction_key(ext), ext)

    # -------------------------------------------------------------------- hub
    def _upsert_hub(self, op: CreateOp | UpdateOp) -> None:
        d: DHub = op.payload
        group = self._get_or_create_group(d.group_name)
        # What Hub.save() would store, so an unnamed hashkey compares as the
        # name the naming pattern gives it rather than as a change.
        hashkey = d.hashkey_name
        if d.hub_type == Hub.HubType.STANDARD and not hashkey:
            hashkey = self.project.resolve_naming_pattern(
                "hashkey_naming", d.physical_name
            )
        obj, created = self._upsert(
            Hub,
            lookup={"project": self.project, "hub_physical_name": d.physical_name},
            values={
                "hub_type": d.hub_type,
                "hub_hashkey_name": hashkey,
                "create_record_tracking_satellite": d.create_record_tracking_satellite,
                "create_effectivity_satellite": d.create_effectivity_satellite,
                "group": group,
                **_only_supplied(description=d.description),
            },
            existing=self._hubs_by_name.get(d.physical_name, LOOKUP),
        )
        self._cache(self._hubs_by_name, d.physical_name, obj)

        existing_columns = (
            {} if created else {c.column_name: c for c in obj.columns.all()}
        )
        mappings_by_column: dict[Any, dict[Any, HubSourceMapping]] = {}
        if not created:
            for mapping in HubSourceMapping.objects.filter(hub_column__hub=obj):
                mappings_by_column.setdefault(mapping.hub_column_id, {})[
                    mapping.staging_column_id
                ] = mapping

        for hc in d.columns:
            hub_column, _ = self._upsert(
                HubColumn,
                lookup={"hub": obj, "column_name": hc.name},
                values={
                    "column_type": hc.column_type,
                    # Only written when the parser actually supplied one. The
                    # Excel, SQLite and IRiS formats have no concept of a column
                    # transformation, so they always leave this None — writing
                    # that unconditionally would silently clear a transformation
                    # a user had set on the next re-import.
                    **_only_supplied(
                        target_column_transformation=hc.target_column_transformation,
                        target_column_datatype=hc.target_column_datatype,
                        description=hc.description,
                        sort_order=hc.sort_order,
                    ),
                },
                existing=existing_columns.get(hc.name),
                path=("columns", hc.name),
            )
            existing_columns[hc.name] = hub_column
            self._cache(self._hub_columns, (obj.pk, hc.name), hub_column)
            self._apply_hub_source_mappings(
                d,
                hc.name,
                hub_column,
                hc.source_mappings,
                mappings_by_column.setdefault(hub_column.pk, {}),
            )

    def _apply_hub_source_mappings(
        self,
        d: DHub,
        column_name: str,
        hub_column: HubColumn,
        source_mappings: list,
        existing: dict[Any, HubSourceMapping],
    ) -> None:
        """Map a hub column to its sources, keeping one of them primary.

        The source's primary flags win when it sets any. Otherwise the ones
        the project has stay, and a column without a primary source gets its
        first mapping as primary — once, not again on every re-import.
        """
        resolved: list[tuple[Any, StagingColumn]] = []
        for mapping in source_mappings:
            staging = self._resolve_staging_column(
                mapping.source_table_identifier, mapping.source_column_name
            )
            if staging is None:
                self._record_error(
                    code=Code.ENTITY_MISSING_SOURCE_COLUMN,
                    message=(
                        f"Hub '{d.physical_name}' column '{column_name}' references unknown "
                        f"source column '{mapping.source_table_identifier}.{mapping.source_column_name}'."
                    ),
                    entity_type="hub_source_mapping",
                    entity_name=f"{d.physical_name}.{column_name}",
                )
                continue
            resolved.append((mapping, staging))

        file_sets_primary = any(mapping.is_primary_source for mapping, _ in resolved)
        has_primary = file_sets_primary or any(
            row.is_primary_source for row in existing.values()
        )
        for index, (mapping, staging) in enumerate(resolved):
            if file_sets_primary:
                is_primary = mapping.is_primary_source
                values = {"is_primary_source": is_primary}
            else:
                is_primary = not has_primary and index == 0
                values = {"is_primary_source": True} if is_primary else {}
            row, _ = self._upsert(
                HubSourceMapping,
                lookup={"hub_column": hub_column, "staging_column": staging},
                values=values,
                create_values={"is_primary_source": is_primary},
                existing=existing.get(staging.pk),
                path=(
                    "columns",
                    column_name,
                    "source_mappings",
                    self._staging_label(staging),
                ),
            )
            existing[staging.pk] = row

    def _hub_column(self, hub: Hub, column_name: str) -> HubColumn | None:
        key = (hub.pk, column_name)
        if key not in self._hub_columns:
            column = HubColumn.objects.filter(hub=hub, column_name=column_name).first()
            if column is None:
                return None
            self._cache(self._hub_columns, key, column)
        return self._hub_columns[key]

    def _resolve_mapping_staging_column(
        self,
        source_table_identifier: str,
        source_column_name: str,
        prejoin_target_table_identifier: str | None,
        *,
        entity_type: str,
        entity_name: str,
    ) -> StagingColumn | None:
        """Staging column a link mapping refers to.

        Without a prejoin target this is the direct source column (created if
        absent, as before). With one, the column is not on the source table at
        all — it is pulled in by a prejoin — so bind to the existing extraction
        column. Creating a source column here would put a phantom column on the
        source table and generate stage SQL that hashes a column that does not
        exist.
        """
        if prejoin_target_table_identifier:
            ext = self._find_prejoin_extraction(
                source_table_identifier,
                prejoin_target_table_identifier,
                source_column_name,
            )
            if ext is None:
                self._record_error(
                    code=Code.ENTITY_MISSING_REFERENCE,
                    message=(
                        f"'{entity_name}' maps to '{source_column_name}', declared as "
                        f"a prejoin extraction from '{source_table_identifier}' to "
                        f"'{prejoin_target_table_identifier}', but no such prejoin "
                        f"extraction column is defined."
                    ),
                    entity_type=entity_type,
                    entity_name=entity_name,
                    suggestion=(
                        "Check that the prejoin and its extraction columns are "
                        "present in the imported file."
                    ),
                )
                return None
            source_table = self._source_tables_by_identifier[source_table_identifier]
            return self._staging_for(
                ext, f"{source_table.physical_table_name}.{_staged_name(ext)}"
            )

        return self._resolve_staging_column(source_table_identifier, source_column_name)

    # ------------------------------------------------------------------- link
    def _upsert_link(self, op: CreateOp | UpdateOp) -> None:
        d: DLink = op.payload
        group = self._get_or_create_group(d.group_name)
        obj, created = self._upsert(
            Link,
            lookup={"project": self.project, "link_physical_name": d.physical_name},
            values={
                "link_type": d.link_type,
                # What Link.save() would store for an unnamed hashkey.
                "link_hashkey_name": d.hashkey_name
                or self.project.resolve_naming_pattern(
                    "hashkey_naming", d.physical_name
                ),
                "create_record_tracking_satellite": d.create_record_tracking_satellite,
                "group": group,
                **_only_supplied(description=d.description),
            },
            existing=self._links_by_name.get(d.physical_name, LOOKUP),
        )
        self._cache(self._links_by_name, d.physical_name, obj)

        ref_objs = self._apply_link_hub_references(d, obj, created)
        self._apply_link_hub_source_mappings(d, obj, created, ref_objs)
        self._apply_link_columns(d, obj, created)

    def _apply_link_hub_references(
        self, d: DLink, obj: Link, created: bool
    ) -> list[LinkHubReference | None]:
        """Bring the link's hub references in line with the source.

        A reference is matched by hub and alias, then by hub alone (an alias
        change), and updated in place, so it keeps its identity and its
        mappings. References the source no longer has are removed.
        """
        unmatched = [] if created else list(obj.hub_references.select_related("hub"))
        ref_objs: list[LinkHubReference | None] = []
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
                ref_objs.append(None)
                continue
            alias = ref_d.hub_hashkey_alias_in_link or ""
            match = next(
                (
                    ref
                    for ref in unmatched
                    if ref.hub_id == hub.pk
                    and (ref.hub_hashkey_alias_in_link or "") == alias
                ),
                None,
            ) or next((ref for ref in unmatched if ref.hub_id == hub.pk), None)
            if match is not None:
                unmatched.remove(match)
            ref, _ = self._upsert(
                LinkHubReference,
                lookup={"link": obj, "hub": hub},
                values={
                    "hub_hashkey_alias_in_link": alias,
                    # 0 means "not given": a new reference is numbered after the
                    # others, an existing one keeps its place.
                    **({"sort_order": ref_d.sort_order} if ref_d.sort_order else {}),
                },
                create_values={"sort_order": 0},
                existing=match,
                path=("hub_references", _reference_key(alias, hub)),
            )
            ref_objs.append(ref)

        for ref in unmatched:
            # Deleting a reference takes its hub key mappings with it.
            remove(
                ref,
                outcome=self._current,
                path=(
                    "hub_references",
                    _reference_key(ref.hub_hashkey_alias_in_link, ref.hub),
                ),
            )
        return ref_objs

    def _apply_link_hub_source_mappings(
        self,
        d: DLink,
        obj: Link,
        created: bool,
        ref_objs: list[LinkHubReference | None],
    ) -> None:
        """Map each hub reference's key columns to exactly the sources given."""
        existing: dict[Any, dict[tuple[Any, Any], LinkHubSourceMapping]] = {}
        if not created:
            for mapping in LinkHubSourceMapping.objects.filter(
                link_hub_reference__link=obj
            ).select_related(
                "standard_hub_column",
                "staging_column__source_table",
                "staging_column__source_column",
                "staging_column__prejoin_column__source_column",
                "staging_column__derived_column",
            ):
                existing.setdefault(mapping.link_hub_reference_id, {})[
                    (mapping.standard_hub_column_id, mapping.staging_column_id)
                ] = mapping

        wanted: dict[Any, set[tuple[Any, Any]]] = {}
        for m in d.hub_source_mappings:
            if (
                m.link_hub_ref_index >= len(ref_objs)
                or ref_objs[m.link_hub_ref_index] is None
            ):
                continue
            ref = ref_objs[m.link_hub_ref_index]
            hub_col = self._hub_column(ref.hub, m.hub_column_name)
            if hub_col is None:
                continue
            staging = self._resolve_mapping_staging_column(
                m.source_table_identifier,
                m.source_column_name,
                m.prejoin_target_table_identifier,
                entity_type="link_hub_source_mapping",
                entity_name=f"{d.physical_name}.{m.hub_column_name}",
            )
            if staging is None:
                continue
            # staging_column is part of the identity: a hub reference's
            # business key can be fed by more than one source table (e.g. the
            # same relationship captured in two source systems), which needs
            # one row per source.
            key = (hub_col.pk, staging.pk)
            wanted.setdefault(ref.pk, set()).add(key)
            rows = existing.setdefault(ref.pk, {})
            if key in rows:
                continue
            rows[key], _ = self._upsert(
                LinkHubSourceMapping,
                lookup={
                    "link_hub_reference": ref,
                    "standard_hub_column": hub_col,
                    "staging_column": staging,
                },
                values={},
                existing=None,
                path=(
                    "hub_references",
                    _reference_key(ref.hub_hashkey_alias_in_link, ref.hub),
                    "columns",
                    hub_col.column_name,
                    "source_mappings",
                    self._staging_label(staging),
                ),
            )

        for ref in ref_objs:
            if ref is None:
                continue
            for key, mapping in existing.get(ref.pk, {}).items():
                if key in wanted.get(ref.pk, set()):
                    continue
                remove(
                    mapping,
                    outcome=self._current,
                    path=(
                        "hub_references",
                        _reference_key(ref.hub_hashkey_alias_in_link, ref.hub),
                        "columns",
                        mapping.standard_hub_column.column_name,
                        "source_mappings",
                        self._staging_label(mapping.staging_column),
                    ),
                )

    def _apply_link_columns(self, d: DLink, obj: Link, created: bool) -> None:
        """Payload / additional columns and their sources."""
        existing_columns = (
            {} if created else {c.column_name: c for c in obj.columns.all()}
        )
        existing_mappings: set[tuple[Any, Any]] = (
            set()
            if created
            else set(
                LinkSourceMapping.objects.filter(link_column__link=obj).values_list(
                    "link_column_id", "staging_column_id"
                )
            )
        )
        for col_d in d.columns:
            lc, _ = self._upsert(
                LinkColumn,
                lookup={"link": obj, "column_name": col_d.name},
                values={
                    "column_type": col_d.column_type,
                    # 0 means "not given": a new column is numbered after the
                    # others, an existing one keeps its place.
                    **({"sort_order": col_d.sort_order} if col_d.sort_order else {}),
                    # See _upsert_hub: never clear a transformation that the
                    # parser did not supply.
                    **_only_supplied(
                        target_column_transformation=col_d.target_column_transformation,
                        target_column_datatype=col_d.target_column_datatype,
                        description=col_d.description,
                    ),
                },
                create_values={"sort_order": 0},
                existing=existing_columns.get(col_d.name),
                path=("columns", col_d.name),
            )
            existing_columns[col_d.name] = lc
            for sm in col_d.source_mappings:
                staging = self._resolve_mapping_staging_column(
                    sm.source_table_identifier,
                    sm.source_column_name,
                    sm.prejoin_target_table_identifier,
                    entity_type="link_source_mapping",
                    entity_name=f"{d.physical_name}.{col_d.name}",
                )
                if staging is None or (lc.pk, staging.pk) in existing_mappings:
                    continue
                self._upsert(
                    LinkSourceMapping,
                    lookup={"link_column": lc, "staging_column": staging},
                    values={},
                    existing=None,
                    path=(
                        "columns",
                        col_d.name,
                        "source_mappings",
                        self._staging_label(staging),
                    ),
                )
                existing_mappings.add((lc.pk, staging.pk))

    # ------------------------------------------------------------ satellite
    def _upsert_satellite(self, op: CreateOp | UpdateOp) -> None:
        d: DSatellite = op.payload
        parent_hub = (
            self._hubs_by_name.get(d.parent_entity_name)
            if d.parent_entity_type == "hub"
            else None
        )
        parent_link = (
            self._links_by_name.get(d.parent_entity_name)
            if d.parent_entity_type == "link"
            else None
        )
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
        obj, created = self._upsert(
            Satellite,
            lookup={
                "project": self.project,
                "satellite_physical_name": d.physical_name,
            },
            values={
                "satellite_type": d.satellite_type,
                "parent_hub": parent_hub,
                "parent_link": parent_link,
                "source_table": source_table,
                "group": group,
                **_only_supplied(description=d.description),
            },
            existing=self._satellites_by_name.get(d.physical_name, LOOKUP),
        )
        self._cache(self._satellites_by_name, d.physical_name, obj)

        existing_columns = (
            {} if created else {c.staging_column_id: c for c in obj.columns.all()}
        )
        # Sort columns: explicit sort orders first to avoid (sat, sort_order) collisions.
        ordered_cols = sorted(
            d.columns,
            key=lambda c: (c.sort_order is None, c.sort_order or 0),
        )

        for col_d in ordered_cols:
            staging = self._resolve_staging_column(
                d.source_table_identifier, col_d.source_column_name
            )
            if staging is None:
                continue
            target = col_d.target_column_name
            if target == col_d.source_column_name:
                target = None
            column, _ = self._upsert(
                SatelliteColumn,
                lookup={"satellite": obj, "staging_column": staging},
                values={
                    "is_multi_active_key": col_d.is_multi_active_key,
                    "include_in_delta_detection": col_d.include_in_delta_detection,
                    "target_column_name": target,
                    # Only written when the parser actually supplied one. The
                    # Excel, SQLite and IRiS formats have no concept of a column
                    # transformation, so they always leave this None — writing
                    # that unconditionally would silently clear a transformation
                    # a user had set on the next re-import. Same for the sort order.
                    **_only_supplied(
                        target_column_transformation=col_d.target_column_transformation,
                        target_column_datatype=col_d.target_column_datatype,
                        description=col_d.description,
                        column_sort_order=col_d.sort_order,
                    ),
                },
                existing=existing_columns.get(staging.pk),
                path=("columns", col_d.source_column_name),
            )
            existing_columns[staging.pk] = column

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
        rt, created = self._upsert(
            ReferenceTable,
            lookup={
                "project": self.project,
                "reference_table_physical_name": d.physical_name,
            },
            values={
                "reference_hub": hub,
                "historization_type": d.historization_type,
                "group": group,
                **_only_supplied(description=d.description),
            },
        )

        # Satellite assignments come from the Excel/JSON. When a ref table has
        # none, generation falls back to all reference satellites of the hub.
        def _match(
            names: list[str], cols: list[SatelliteColumn]
        ) -> list[SatelliteColumn]:
            # A column's effective name is its target override or, when absent,
            # its staging column name.
            wanted = set(names)
            return [c for c in cols if _satellite_column_name(c) in wanted]

        existing = (
            {}
            if created
            else {
                a.reference_satellite_id: a
                for a in rt.satellite_assignments.select_related("reference_satellite")
            }
        )
        seen_sat_pks = set()
        for a in d.satellite_assignments:
            sat = self._satellites_by_name.get(a.satellite_name)
            if sat is None:
                self._record_error(
                    code=Code.ENTITY_MISSING_REFERENCE,
                    message=(
                        f"Reference table '{d.physical_name}' references satellite "
                        f"'{a.satellite_name}' which is not defined."
                    ),
                    entity_type="reference_table",
                    entity_name=d.physical_name,
                )
                continue

            path = ("satellite_assignments", sat.satellite_physical_name)
            assignment, _ = self._upsert(
                ReferenceTableSatelliteAssignment,
                lookup={"reference_table": rt, "reference_satellite": sat},
                values={},
                existing=existing.get(sat.pk),
                path=path,
            )
            existing[sat.pk] = assignment
            seen_sat_pks.add(sat.pk)

            sat_columns = list(
                SatelliteColumn.objects.filter(satellite=sat).select_related(
                    "staging_column__source_column",
                    "staging_column__prejoin_column__source_column",
                    "staging_column__derived_column",
                )
            )

            # The model allows only one of include/exclude. Include wins.
            include = (
                _match(a.include_columns, sat_columns) if a.include_columns else []
            )
            exclude = (
                _match(a.exclude_columns, sat_columns)
                if a.exclude_columns and not a.include_columns
                else []
            )
            for relation, columns in (
                ("include_columns", include),
                ("exclude_columns", exclude),
            ):
                sync_members(
                    assignment,
                    relation,
                    columns,
                    key=_satellite_column_name,
                    outcome=self._current,
                    path=path,
                )

        # Drop assignments no longer present in the source (idempotent re-import).
        for sat_pk, assignment in existing.items():
            if sat_pk not in seen_sat_pks:
                remove(
                    assignment,
                    outcome=self._current,
                    path=(
                        "satellite_assignments",
                        assignment.reference_satellite.satellite_physical_name,
                    ),
                )

    # --------------------------------------------------------------------- PIT
    def _upsert_pit(self, op: CreateOp | UpdateOp) -> None:
        d: DPIT = op.payload
        hub = (
            self._hubs_by_name.get(d.tracked_entity_name)
            if d.tracked_entity_type == "hub"
            else None
        )
        link = (
            self._links_by_name.get(d.tracked_entity_name)
            if d.tracked_entity_type == "link"
            else None
        )
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
            # skip_snapshots: the planner already reports PITs as skipped.
            return

        group = self._get_or_create_group(d.group_name)
        pit, _ = self._upsert(
            PIT,
            lookup={"project": self.project, "pit_physical_name": d.physical_name},
            values={
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
        sync_members(
            pit,
            "satellites",
            sats,
            key=lambda satellite: satellite.satellite_physical_name,
            outcome=self._current,
        )


def _staged_name(ext: PrejoinExtractionColumn) -> str:
    return (
        ext.prejoin_target_column_alias or ext.source_column.source_column_physical_name
    )


def _reference_key(alias: str | None, hub: Hub) -> str:
    """How a change path names a link's hub reference: its alias, else the hub."""
    return alias or hub.hub_physical_name


def _satellite_column_name(column: SatelliteColumn) -> str:
    return column.target_column_name or column.staging_column.physical_name


# ---------------------------------------------------------------------------
# Dispatch tables
# ---------------------------------------------------------------------------


_UPSERT_DISPATCH = {
    "source_system": _Executor._upsert_source_system,
    "source_table": _Executor._upsert_source_table,
    "prejoin": _Executor._upsert_prejoin,
    "hub": _Executor._upsert_hub,
    "link": _Executor._upsert_link,
    "satellite": _Executor._upsert_satellite,
    "reference_table": _Executor._upsert_reference_table,
    "pit": _Executor._upsert_pit,
}


_MODEL_FOR_DELETE = {
    "source_system": SourceSystem,
    "source_table": SourceTable,
    "prejoin": PrejoinDefinition,
    "hub": Hub,
    "link": Link,
    "satellite": Satellite,
    "reference_table": ReferenceTable,
    "pit": PIT,
}
