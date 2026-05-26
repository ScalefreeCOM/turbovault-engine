"""
Public type contracts for the generation pipeline.

All callers (CLI, Studio, tests) should depend only on these types.
Internal stages exchange richer Python objects; these are the boundary
types serialized into `GenerationRun.report` and returned from
`engine.services.generation.generate()`.

Mirrors the shape of `engine.services.imports.types` so frontends can
render both kinds of run reports with shared components.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Aliases & enums
# ---------------------------------------------------------------------------

OutputType = Literal["dbt", "json", "dbml"]
ErrorStrategy = Literal["fail_fast", "best_effort"]
GenerationStatus = Literal["success", "partial_success", "validation_failed", "failed"]
PipelineStage = Literal["build", "validate", "plan", "render", "write", "report"]
Severity = Literal["error", "warning", "info"]
ArtifactKind = Literal[
    "sql_model",
    "yaml_schema",
    "project_yml",
    "packages_yml",
    "sources_yml",
    "dbt_profiles",
    "zip",
    "json_export",
    "dbml_export",
]


# ---------------------------------------------------------------------------
# Entity references & locations
# ---------------------------------------------------------------------------


class EntityRef(BaseModel):
    """A lightweight reference to a Data Vault entity."""

    model_config = ConfigDict(extra="forbid")

    type: str
    name: str
    group: str | None = None


class IssueLocation(BaseModel):
    """Where in the *stored metadata* an issue lives.

    The generation pipeline reads from the Django ORM, not a source file,
    so locations are entity- and field-scoped. There is no sheet/row/column.
    """

    model_config = ConfigDict(extra="forbid")

    entity_type: str | None = None
    entity_name: str | None = None
    field: str | None = None


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
# Selection / options
# ---------------------------------------------------------------------------


class EntitySelection(BaseModel):
    """Filter controlling which entities the generator emits.

    All criteria AND together; within each criterion the values OR together.
    `only_entities`, when set, is an explicit allowlist that overrides every
    include / exclude rule. An entirely empty selection means "emit
    everything" — the default.
    """

    model_config = ConfigDict(extra="forbid")

    include_entity_types: set[str] | None = None
    exclude_entity_types: set[str] | None = None
    include_groups: set[str] | None = None
    exclude_groups: set[str] | None = None
    only_entities: list[EntityRef] | None = None

    def is_unrestricted(self) -> bool:
        return not (
            self.include_entity_types
            or self.exclude_entity_types
            or self.include_groups
            or self.exclude_groups
            or self.only_entities
        )

    def matches(self, ref: EntityRef) -> bool:
        """Return True if `ref` passes the filter."""
        if self.only_entities is not None:
            return any(
                e.type == ref.type and e.name == ref.name for e in self.only_entities
            )
        if self.include_entity_types and ref.type not in self.include_entity_types:
            return False
        if self.exclude_entity_types and ref.type in self.exclude_entity_types:
            return False
        if self.include_groups is not None and (
            ref.group is None or ref.group not in self.include_groups
        ):
            return False
        if self.exclude_groups and ref.group in self.exclude_groups:
            return False
        return True


class GenerationOptions(BaseModel):
    """Caller-supplied knobs that shape pipeline behavior."""

    model_config = ConfigDict(extra="forbid")

    error_strategy: ErrorStrategy = "best_effort"
    dry_run: bool = False
    skip_validation: bool = False
    create_zip: bool = False
    generate_satellite_v1_views: bool = True
    use_db_templates: bool = False
    entity_selection: EntitySelection | None = None
    return_content: bool = False


# ---------------------------------------------------------------------------
# Plan & artifacts
# ---------------------------------------------------------------------------


class GenerationPlan(BaseModel):
    """What the pipeline expects to produce."""

    model_config = ConfigDict(extra="forbid")

    output_type: OutputType
    files_planned: int = 0
    by_entity_type: dict[str, int] = Field(default_factory=dict)


class GeneratedArtifact(BaseModel):
    """A single artifact produced (or planned) by the pipeline."""

    model_config = ConfigDict(extra="forbid")

    kind: ArtifactKind
    entity_type: str | None = None
    entity_name: str | None = None
    path: str | None = None
    size_bytes: int = 0
    checksum: str | None = None
    content: str | None = None


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------


class GenerationReport(BaseModel):
    """The single artifact returned by `generate()`."""

    model_config = ConfigDict(extra="forbid")

    generation_run_id: UUID
    project_id: UUID
    output_type: OutputType
    status: GenerationStatus
    is_dry_run: bool
    started_at: datetime
    finished_at: datetime
    timings_ms: dict[str, int] = Field(default_factory=dict)
    options: GenerationOptions
    plan: GenerationPlan
    artifacts: list[GeneratedArtifact] = Field(default_factory=list)
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

    @property
    def files_generated(self) -> int:
        """Count of artifacts that were actually persisted to disk."""
        return sum(1 for a in self.artifacts if a.path)

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

    The CLI drives a progress bar from these events; the Studio Celery
    task forwards `message` into `Job.current_step` so polling clients see
    "Building project export" / "Validating model" / etc. instead of a
    static "Preparing generation".
    """

    model_config = ConfigDict(extra="forbid")

    stage: PipelineStage
    status: ProgressStatus
    message: str
    current: int | None = None
    total: int | None = None
