"""
Internal exception hierarchy and helpers for building Issues.

Pipeline stages never let these escape to callers — the runner catches
them at stage boundaries and translates them into `Issue`s on the report.
Code paths that must abort the entire run raise `PipelineAbort` with a
single Issue carrying everything the user needs to act.
"""

from __future__ import annotations

from engine.services.generation.types import (
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
    report cleanly. Used for fail-fast errors and unrecoverable conditions
    at any stage (e.g. project export build failure, missing dbt output
    path).
    """

    def __init__(self, issue: Issue):
        self.issue = issue
        super().__init__(issue.message)


# ---------------------------------------------------------------------------
# Issue codes (centralized — keep in sync with codes.md for users)
# ---------------------------------------------------------------------------


class Code:
    # Build stage
    BUILD_PROJECT_LOAD_FAILED = "build.project_load_failed"
    BUILD_EXPORT_INCONSISTENT = "build.export_inconsistent"

    # Validate stage — sources / stages
    VALIDATE_SOURCE_NO_SCHEMA = "validate.source.no_schema"
    VALIDATE_SOURCE_NO_TABLES = "validate.source.no_tables"
    VALIDATE_STAGE_NO_SOURCE_TABLE = "validate.stage.no_source_table"
    VALIDATE_STAGE_NO_KEYS = "validate.stage.no_keys"

    # Validate stage — hubs
    VALIDATE_HUB_MISSING_HASHKEY = "validate.hub.missing_hashkey"
    VALIDATE_HUB_NO_BUSINESS_KEYS = "validate.hub.no_business_keys"
    VALIDATE_HUB_NO_SOURCE_TABLES = "validate.hub.no_source_tables"

    # Validate stage — links
    VALIDATE_LINK_MISSING_HASHKEY = "validate.link.missing_hashkey"
    VALIDATE_LINK_TOO_FEW_HUBS = "validate.link.too_few_hubs"
    VALIDATE_LINK_NO_SOURCES = "validate.link.no_sources"

    # Validate stage — satellites
    VALIDATE_SATELLITE_NO_PARENT = "validate.satellite.no_parent"
    VALIDATE_SATELLITE_NO_STAGE = "validate.satellite.no_stage"
    VALIDATE_SATELLITE_NO_COLUMNS = "validate.satellite.no_columns"
    VALIDATE_SATELLITE_NO_HASHDIFF = "validate.satellite.no_hashdiff"

    # Validate stage — PITs
    VALIDATE_PIT_NO_SATELLITES = "validate.pit.no_satellites"
    VALIDATE_PIT_NO_SNAPSHOT_LOGIC = "validate.pit.no_snapshot_logic"
    VALIDATE_PIT_NO_TRACKED_ENTITY = "validate.pit.no_tracked_entity"

    # Validate stage — snapshot controls
    VALIDATE_SNAPSHOT_NO_NAME = "validate.snapshot.no_name"
    VALIDATE_SNAPSHOT_NO_START_DATE = "validate.snapshot.no_start_date"
    VALIDATE_SNAPSHOT_NO_LOGIC_PATTERNS = "validate.snapshot.no_logic_patterns"

    # Plan stage
    PLAN_UNSUPPORTED_OUTPUT_TYPE = "plan.unsupported_output_type"
    PLAN_EMPTY_PROJECT = "plan.empty_project"

    # Render stage
    RENDER_TEMPLATE_NOT_FOUND = "render.template_not_found"
    RENDER_TEMPLATE_RENDER_FAILED = "render.template_render_failed"
    RENDER_ENTITY_SKIPPED = "render.entity_skipped"

    # Write stage
    WRITE_IO_ERROR = "write.io_error"
    WRITE_PATH_COLLISION = "write.path_collision"
    WRITE_ZIP_FAILED = "write.zip_failed"

    # Internal
    INTERNAL_BUG = "internal.bug"
