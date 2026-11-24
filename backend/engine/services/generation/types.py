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
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Aliases & enums
# ---------------------------------------------------------------------------

OutputType = Literal["dbt", "json", "dbml", "sqlmesh"]
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
    "sqlmesh_model",
    "sqlmesh_config",
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


class TemplateOverride(BaseModel):
    """In-memory template content supplied for a single generation run.

    Keyed by framework, then entity_type, in GenerationOptions.templates_override
    (e.g. ``{"sqlmesh": {"hub_standard": TemplateOverride(...)}}``); an
    override for one framework never applies to another. Either field may be
    None to inherit from the DB / bundled file default; a non-None value takes
    precedence. SQL and YAML resolve independently.
    """

    model_config = ConfigDict(extra="forbid")

    sql: str | None = None
    yaml: str | None = None


class GenerationOptions(BaseModel):
    """Caller-supplied knobs that shape pipeline behavior."""

    model_config = ConfigDict(extra="forbid")

    error_strategy: ErrorStrategy = "best_effort"
    dry_run: bool = False
    skip_validation: bool = False
    create_zip: bool = False
    generate_satellite_v1_views: bool = True
    # Write models into the folders stored for them (ModelOutput.folder); off:
    # every model goes to the project's folder patterns, keeping its original
    # folder's settings. Names stay either way. None: the project's setting
    # (runtime config use_model_folders).
    use_model_folders: bool | None = None
    # dbt: whether to write dbt_project.yml and packages.yml (spec D17). None:
    # unless the output folder holds a dbt project whose dbt_project.yml
    # TurboVault didn't write (its record, .turbovault/generated.json).
    write_project_files: bool | None = None
    # Delete the files TurboVault generated earlier and no longer generates
    # (while unchanged since); off: they are reported.
    remove_stale_files: bool = False
    # Preserve the legacy resolver contract: active DB templates precede files.
    use_db_templates: bool = True
    entity_selection: EntitySelection | None = None
    return_content: bool = False
    templates_override: dict[str, dict[str, TemplateOverride]] | None = None


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
    overwrite: bool = True


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
    """Lifecycle event emitted as the pipeline runs.

    Every stage emits `started` and `done`. The render and write stages
    also emit one `in_progress` event per file, with `current` (1-based)
    and `total`. `message` is a short, plain sentence; `detail` holds small
    JSON-serializable values (str, int, float, bool, None, and lists and
    dicts of those) for logs and progress bars.

    `detail` by stage and status:

    - `build` / `done`: ``{"entities": {<entity_type>: count}}``, what the
      export holds: ``source`` (source systems), ``source_table``,
      ``prestage``, ``stage``, ``hub``, ``link``, ``satellite``, ``pit``,
      ``reference_table``, ``snapshot_control``. Every key is present.
    - `validate` / `done`: ``{"errors": n, "warnings": n}``, the issues
      the validate stage found.
    - `plan` / `done`: ``{"files_planned": n, "by_entity_type": {...}}``,
      the `GenerationPlan` fields.
    - `render` / `in_progress`: one per rendered artifact,
      ``{"path", "kind", "entity_type", "entity_name"}`` as on
      `GeneratedArtifact` (``path`` relative to the output folder; None
      where unknown, e.g. for a JSON or DBML export). Emitted once the
      renderer has produced the artifacts.
    - `render` / `done`: ``{"files": n}``, the artifacts rendered.
    - `write` / `in_progress`: one per file written (none on a dry run),
      ``{"path", "size_bytes"}`` with ``path`` relative to the output
      folder. Write-once files that already exist are kept, not written,
      and don't count. A file that can't be written is an error issue and
      gets no event, so `current` then stops short of `total`.
    - `write` / `done`: ``{"files": n, "size_bytes": total}``, the files
      written and their bytes, the ZIP aside (both 0 on a dry run).

    Other events have no `detail`. A caller can drive a progress bar from
    these events; the Studio Celery task forwards `message` into
    `Job.current_step` and turns the events into a run's detailed log.
    """

    model_config = ConfigDict(extra="forbid")

    stage: PipelineStage
    status: ProgressStatus
    message: str
    current: int | None = None
    total: int | None = None
    detail: dict[str, Any] | None = None
