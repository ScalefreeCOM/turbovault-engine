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

    # dbt project import
    DBT_UNSUPPORTED_MANIFEST_VERSION = "dbt.unsupported_manifest_version"
    DBT_ARTIFACT_TOO_LARGE = "dbt.artifact_too_large"
    DBT_MANIFEST_MISSING = "dbt.manifest_missing"
    DBT_NOTHING_TO_IMPORT = "dbt.nothing_to_import"
    DBT_ARTIFACTS_LOCATED = "dbt.artifacts_located"
    DBT_CATALOG_MISSING = "dbt.catalog_missing"
    DBT_PROJECT_FILE_MISSING = "dbt.project_file_missing"
    DBT_PACKAGES_MISSING = "dbt.packages_missing"
    DBT_MODEL_NOT_MAPPED = "dbt.model_not_mapped"
    DBT_MODEL_RENDER_FAILED = "dbt.model_render_failed"
    DBT_MACRO_UNSUPPORTED = "dbt.macro_unsupported"
    DBT_PARAMETER_UNSUPPORTED = "dbt.parameter_unsupported"
    DBT_PARAMETER_IGNORED = "dbt.parameter_ignored"
    DBT_PARAMETER_GIVEN_TWICE = "dbt.parameter_given_twice"
    DBT_VALUE_UNRESOLVED = "dbt.value_unresolved"
    DBT_VALUE_INVALID = "dbt.value_invalid"
    DBT_REFERENCE_UNRESOLVED = "dbt.reference_unresolved"
    DBT_LINK_HUB_AMBIGUOUS = "dbt.link_hub_ambiguous"
    DBT_SETTING_SUGGESTED = "dbt.setting_suggested"
    DBT_PRESTAGE_MAINTAINED_IN_DBT = "dbt.prestage_maintained_in_dbt"
    DBT_HASH_INPUTS_DIFFER = "dbt.hash_inputs_differ"
    DBT_COLUMN_UNKNOWN = "dbt.column_unknown"
    DBT_RESOURCE_NOT_IMPORTED = "dbt.resource_not_imported"

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
    ENTITY_DEPENDS_ON_SKIPPED = "entity.depends_on_skipped"
    # Imported as another kind of entity than the source gives it, e.g. an
    # effectivity satellite as its parent's effectivity flag.
    ENTITY_IMPORTED_DIFFERENTLY = "entity.imported_differently"
    # Names (#450): Data Vault names must be plain identifiers, unique ignoring
    # case; unusual source names are only reported.
    ENTITY_INVALID_NAME = "entity.invalid_name"
    ENTITY_NAME_CASE_COLLISION = "entity.name_case_collision"
    ENTITY_UNUSUAL_SOURCE_NAME = "entity.unusual_source_name"
    # Studio's naming rules (#451)
    ENTITY_INVALID_SOURCE_NAME = "entity.invalid_source_name"
    ENTITY_NAME_RESERVED_WORD = "entity.name_reserved_word"
    ENTITY_NAME_TOO_LONG = "entity.name_too_long"
    ENTITY_UNUSUAL_DISPLAY_NAME = "entity.unusual_display_name"

    # Plan stage
    PLAN_WOULD_CREATE = "plan.would_create"
    PLAN_WOULD_UPDATE = "plan.would_update"
    PLAN_WOULD_DELETE = "plan.would_delete"
    PLAN_WOULD_SKIP = "plan.would_skip"
    # The caller's on_plan callback stopped the import before any write.
    PLAN_REJECTED = "plan.rejected"

    # Execute stage
    EXECUTE_CONSTRAINT_VIOLATION = "execute.constraint_violation"
    EXECUTE_UNEXPECTED_ERROR = "execute.unexpected_error"

    # Internal
    INTERNAL_BUG = "internal.bug"
