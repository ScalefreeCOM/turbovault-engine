"""
Internal exception hierarchy and helpers for building Issues.

The pipeline never lets these exceptions escape to callers — they are caught
at stage boundaries and translated into `Issue`s on the report. Code paths
that must abort the entire run raise `PipelineAbort` with a single Issue.
"""

from __future__ import annotations

from engine.services.imports.types import (
    EntityRef,
    Issue,
    IssueLocation,
    PipelineStage,
    Severity,
)


def make_issue(
    *,
    severity: Severity,
    code: str,
    message: str,
    stage: PipelineStage,
    location: IssueLocation | None = None,
    entity: EntityRef | None = None,
    suggestion: str | None = None,
) -> Issue:
    """Construct an Issue with all the boilerplate kwargs in one place."""
    return Issue(
        severity=severity,
        code=code,
        message=message,
        stage=stage,
        location=location,
        entity=entity,
        suggestion=suggestion,
    )


class PipelineAbort(Exception):
    """Raised inside a stage when the run cannot continue.

    Carries a single Issue so the runner can record it and finalize the
    report cleanly. Used for fail-fast errors and unrecoverable format
    errors at the parse stage.
    """

    def __init__(self, issue: Issue):
        self.issue = issue
        super().__init__(issue.message)


# ---------------------------------------------------------------------------
# Issue codes (centralized — keep in sync with codes.md for users)
# ---------------------------------------------------------------------------


class Code:
    # Parse stage
    SOURCE_UNREADABLE = "source.unreadable"
    SOURCE_UNSUPPORTED_FORMAT = "source.unsupported_format"
    SOURCE_EMPTY = "source.empty"
    SOURCE_INVALID_JSON = "source.invalid_json"

    # Schema validation
    SCHEMA_MISSING_SHEET = "schema.missing_sheet"
    SCHEMA_MISSING_COLUMN = "schema.missing_column"
    SCHEMA_UNKNOWN_SHEET = "schema.unknown_sheet"
    SCHEMA_UNKNOWN_COLUMN = "schema.unknown_column"

    # Row validation
    ROW_REQUIRED_VALUE_MISSING = "row.required_value_missing"
    ROW_INVALID_TYPE = "row.invalid_type"
    ROW_INVALID_ENUM_VALUE = "row.invalid_enum_value"

    # Resolution / semantic
    ENTITY_DUPLICATE_NAME = "entity.duplicate_name"
    ENTITY_MISSING_PARENT = "entity.missing_parent"
    ENTITY_MISSING_REFERENCE = "entity.missing_reference"
    ENTITY_MISSING_SOURCE_COLUMN = "entity.missing_source_column"
    ENTITY_MISSING_SOURCE_TABLE = "entity.missing_source_table"
    ENTITY_INVALID_CONFIGURATION = "entity.invalid_configuration"

    # Plan stage
    PLAN_WOULD_CREATE = "plan.would_create"
    PLAN_WOULD_UPDATE = "plan.would_update"
    PLAN_WOULD_DELETE = "plan.would_delete"
    PLAN_WOULD_SKIP = "plan.would_skip"

    # Execute stage
    EXECUTE_CONSTRAINT_VIOLATION = "execute.constraint_violation"
    EXECUTE_UNEXPECTED_ERROR = "execute.unexpected_error"

    # Internal
    INTERNAL_BUG = "internal.bug"
