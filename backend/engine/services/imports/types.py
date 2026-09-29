"""
Public type contracts for the import pipeline.

All callers (CLI, Studio, tests) should depend only on these types.
The internal pipeline stages exchange richer Python objects (see domain.py,
ir.py); these are the boundary types that get persisted in ImportRun.report
and shipped back to the Studio.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Source declaration (discriminated union by `type`)
# ---------------------------------------------------------------------------


class _SourceBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Path = Field(..., description="Filesystem path to the metadata source")
    display_name: str | None = Field(
        default=None,
        description="Optional human-readable name; defaults to path.name",
    )


class ExcelSource(_SourceBase):
    type: Literal["excel"] = "excel"


class SqliteSource(_SourceBase):
    type: Literal["sqlite"] = "sqlite"


class JsonSource(_SourceBase):
    type: Literal["json"] = "json"


class SourceMetadataSource(_SourceBase):
    """A versioned JSON document describing source-side metadata only.

    Contract used by external metadata producers (notably the Studio's
    live-database connector subsystem). Unlike ``JsonSource`` — which
    consumes a full ``ProjectExport`` of an existing TurboVault project —
    this format carries **only** source systems → tables → columns, so a
    ``merge`` import leaves hubs/links/satellites untouched.

    Schema: ``parsers.source_metadata.SourceMetadataV1``.
    """

    type: Literal["source_metadata"] = "source_metadata"


class IrisSource(_SourceBase):
    """The three-file IRiS export (Source / DataVault / Mappings workbooks).

    ``path`` points at the directory holding the ``Source_*`` / ``DataVault_*``
    / ``Mappings_*`` workbooks. The parser rebuilds a ``DomainModel`` directly,
    inverting the IRiS exporter. See ``parsers.iris.parse_iris``.
    """

    type: Literal["iris"] = "iris"


SourceInput = Annotated[
    ExcelSource | SqliteSource | JsonSource | SourceMetadataSource | IrisSource,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


ConflictStrategy = Literal["merge", "replace_all", "update_only"]
ErrorStrategy = Literal["fail_fast", "best_effort"]


class ImportOptions(BaseModel):
    """Caller-supplied knobs that shape pipeline behavior.

    Defaults are tuned for the most common user expectation: pull in as much
    of the file as is valid, skip the parts that aren't, and report exactly
    what was skipped. Callers that want strict all-or-nothing semantics can
    pass `error_strategy="fail_fast"`.
    """

    model_config = ConfigDict(extra="forbid")

    conflict_strategy: ConflictStrategy = "merge"
    error_strategy: ErrorStrategy = "best_effort"
    dry_run: bool = False
    skip_snapshots: bool = False
    allow_unknown_columns: bool = True


# ---------------------------------------------------------------------------
# Locations & references
# ---------------------------------------------------------------------------


EntityType = Literal[
    "project",
    "group",
    "source_system",
    "source_table",
    "source_column",
    "hub",
    "hub_column",
    "hub_source_mapping",
    "link",
    "link_column",
    "link_hub_reference",
    "link_hub_source_mapping",
    "link_source_mapping",
    "satellite",
    "satellite_column",
    "snapshot_control",
    "snapshot_control_logic",
    "reference_table",
    "reference_table_satellite_assignment",
    "pit",
    "prejoin",
    "prejoin_extraction_column",
    "staging_column",
]


PipelineStage = Literal[
    "parse",
    "validate",
    "resolve",
    "plan",
    "execute",
    "report",
]


# What happens to an entity. `update` means the import changed something on
# an entity that already exists; `unchanged` means it exists and already
# matches the source, so nothing is written.
PlanAction = Literal["create", "update", "unchanged", "delete", "skip"]
PLAN_ACTIONS: tuple[PlanAction, ...] = (
    "create",
    "update",
    "unchanged",
    "delete",
    "skip",
)


class IssueLocation(BaseModel):
    """Where in the source an issue was detected."""

    model_config = ConfigDict(extra="forbid")

    file: str | None = None
    sheet: str | None = None
    row: int | None = None
    column: str | None = None


class EntityRef(BaseModel):
    """Lightweight reference to a domain entity by type and name."""

    model_config = ConfigDict(extra="forbid")

    type: EntityType
    name: str
    parent: EntityRef | None = None


EntityRef.model_rebuild()


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------


Severity = Literal["error", "warning", "info"]


class Issue(BaseModel):
    """A single diagnostic produced anywhere in the pipeline."""

    model_config = ConfigDict(extra="forbid")

    severity: Severity
    code: str
    message: str
    stage: PipelineStage
    location: IssueLocation | None = None
    entity: EntityRef | None = None
    suggestion: str | None = None


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


ChangeKind = Literal["changed", "added", "removed"]


class EntityChange(BaseModel):
    """One change the import makes to an existing entity.

    ``path`` locates it: pairs of (collection, key) down to a child row,
    followed by a field name for a changed value. An even-length path names a
    child row that was added or removed, e.g. ``["columns", "customer_id",
    "source_mappings", "orders.customer_no"]``; an odd-length one a field,
    e.g. ``["columns", "customer_id", "target_column_datatype"]`` or just
    ``["hub_hashkey_name"]``. Keys are raw names and may contain dots, so
    ``field`` (the path joined with dots) is for display only.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    before: Any = None
    after: Any = None
    path: list[str] | None = None
    kind: ChangeKind = "changed"


class PlannedEntity(BaseModel):
    """One entity in the plan with the action that would be taken."""

    model_config = ConfigDict(extra="forbid")

    ref: EntityRef
    action: PlanAction
    changes: list[EntityChange] = Field(default_factory=list)
    skip_reason: str | None = None


def _empty_action_counts() -> dict[str, int]:
    return dict.fromkeys(PLAN_ACTIONS, 0)


class PlanCounts(BaseModel):
    """Per-entity-type and total counts of planned actions."""

    model_config = ConfigDict(extra="forbid")

    by_entity_type: dict[str, dict[str, int]] = Field(default_factory=dict)
    totals: dict[str, int] = Field(default_factory=_empty_action_counts)

    def add(self, entity_type: str, action: PlanAction) -> None:
        bucket = self.by_entity_type.setdefault(entity_type, _empty_action_counts())
        bucket[action] = bucket.get(action, 0) + 1
        self.totals[action] = self.totals.get(action, 0) + 1

    @classmethod
    def from_entities(cls, entities: list[PlannedEntity]) -> PlanCounts:
        counts = cls()
        for entity in entities:
            counts.add(entity.ref.type, entity.action)
        return counts


# How far the plan got:
# - planned  : matched against the project only; an entity that exists is
#              `update` until the import has compared it field by field.
# - simulated: a dry run applied it and rolled back; every action is final.
# - applied  : the import wrote it.
PlanState = Literal["planned", "simulated", "applied"]


class ImportPlan(BaseModel):
    """The full diff against current project state."""

    model_config = ConfigDict(extra="forbid")

    entities: list[PlannedEntity] = Field(default_factory=list)
    counts: PlanCounts = Field(default_factory=PlanCounts)
    state: PlanState = "planned"


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------


ImportStatus = Literal[
    "success",
    "partial_success",
    "failed",
    "validation_failed",
]


class ImportReport(BaseModel):
    """The single artifact returned by `import_metadata()`."""

    model_config = ConfigDict(extra="forbid")

    import_run_id: UUID
    project_id: UUID
    status: ImportStatus
    is_dry_run: bool
    started_at: datetime
    finished_at: datetime
    timings_ms: dict[str, int] = Field(default_factory=dict)
    options: ImportOptions
    source_type: str
    source_name: str
    plan: ImportPlan
    issues: list[Issue] = Field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    def worst_issue(self) -> Issue | None:
        """Return the first error, then the first warning, or None."""
        for severity in ("error", "warning", "info"):
            for issue in self.issues:
                if issue.severity == severity:
                    return issue
        return None


# ---------------------------------------------------------------------------
# Progress events
# ---------------------------------------------------------------------------


ProgressStatus = Literal["started", "in_progress", "done", "failed"]


class ProgressEvent(BaseModel):
    """Lifecycle event emitted between pipeline stages.

    Used by the CLI to drive a progress bar and by Studio's Celery task to
    update `Job.current_step` mid-import.
    """

    model_config = ConfigDict(extra="forbid")

    stage: PipelineStage
    status: ProgressStatus
    message: str
    current: int | None = None
    total: int | None = None
