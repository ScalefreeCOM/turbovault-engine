"""
Stage 2 — Validate.

Wraps the legacy `validate_export()` and re-types every
`ValidationError` / `ValidationWarning` as a structured `Issue` with
`stage="validate"`, a dot-separated stable code, and an `EntityRef`
populated with the entity's group so downstream selection filtering
works.

If `options.entity_selection` is set, the stage post-filters issues so
only those targeting selected entities reach the report. (Transitive
dependents — e.g. issues on satellites of a selected hub — are not yet
included; that is tracked as a future polish.)
"""

from __future__ import annotations

from engine.services.export.models import ProjectExport
from engine.services.generation.errors import make_issue
from engine.services.generation.types import (
    EntityRef,
    GenerationOptions,
    Issue,
    IssueLocation,
)
from engine.services.generation.validators import (
    ValidationError,
    ValidationResult,
    ValidationWarning,
    validate_export,
)

# Map the legacy numeric code emitted by `validators.py` to a dot-separated
# stable code in the new taxonomy. Codes the legacy validator does not emit
# fall through with their original alphanumeric form.
_LEGACY_CODE_MAP: dict[str, str] = {
    "SRC_001": "validate.source.no_schema",
    "SRC_002": "validate.source.no_tables",
    "STG_001": "validate.stage.no_source_table",
    "STG_002": "validate.stage.no_keys",
    "HUB_001": "validate.hub.missing_hashkey",
    "HUB_002": "validate.hub.no_business_keys",
    "HUB_003": "validate.hub.no_source_tables",
    "LNK_001": "validate.link.missing_hashkey",
    "LNK_002": "validate.link.too_few_hubs",
    "LNK_003": "validate.link.no_sources",
    "SAT_001": "validate.satellite.no_parent",
    "SAT_002": "validate.satellite.no_stage",
    "SAT_003": "validate.satellite.no_columns",
    "SAT_004": "validate.satellite.no_hashdiff",
    "PIT_001": "validate.pit.no_satellites",
    "PIT_002": "validate.pit.no_snapshot_logic",
    "PIT_003": "validate.pit.no_tracked_entity",
    "SNAP_001": "validate.snapshot.no_name",
    "SNAP_002": "validate.snapshot.no_start_date",
    "SNAP_003": "validate.snapshot.no_logic_patterns",
}


def validate(
    *,
    project_export: ProjectExport,
    options: GenerationOptions,
) -> list[Issue]:
    """Run validation against the export and return structured issues.

    Returns an empty list when `options.skip_validation` is True (the
    caller asked to bypass validation entirely).
    """
    if options.skip_validation:
        return []

    result: ValidationResult = validate_export(project_export)
    group_lookup = _build_group_lookup(project_export)

    issues: list[Issue] = []
    for err in result.errors:
        issues.append(_to_issue(err, severity="error", group_lookup=group_lookup))
    for warn in result.warnings:
        issues.append(_to_issue(warn, severity="warning", group_lookup=group_lookup))

    selection = options.entity_selection
    if selection is None or selection.is_unrestricted():
        return issues
    return [i for i in issues if i.entity is None or selection.matches(i.entity)]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _to_issue(
    raw: ValidationError | ValidationWarning,
    *,
    severity,
    group_lookup: dict[tuple[str, str], str | None],
) -> Issue:
    code = _LEGACY_CODE_MAP.get(raw.code, raw.code or "validate.unknown")
    group = group_lookup.get((raw.entity_type, raw.entity_name))
    return make_issue(
        severity=severity,
        code=code,
        stage="validate",
        message=raw.message,
        location=IssueLocation(
            entity_type=raw.entity_type or None,
            entity_name=raw.entity_name or None,
            field=raw.field or None,
        ),
        entity=EntityRef(
            type=raw.entity_type,
            name=raw.entity_name,
            group=group,
        )
        if raw.entity_type and raw.entity_name
        else None,
    )


def _build_group_lookup(
    project_export: ProjectExport,
) -> dict[tuple[str, str], str | None]:
    """Index every entity by (type, name) → group so issues can carry it.

    Group filtering at the validate stage depends on this — if the lookup
    doesn't have an entry, the entity has no group and falls into the
    'no group' bucket for selection purposes.
    """
    lookup: dict[tuple[str, str], str | None] = {}
    for hub in project_export.hubs:
        lookup[("hub", hub.hub_name)] = hub.group
    for link in project_export.links:
        lookup[("link", link.link_name)] = link.group
    for sat in project_export.satellites:
        lookup[("satellite", sat.satellite_name)] = sat.group
    for pit in project_export.pits:
        lookup[("pit", pit.pit_name)] = pit.group
    for rt in project_export.reference_tables:
        lookup[("reference_table", rt.table_name)] = rt.group
    # Sources, stages, and snapshot controls don't have groups in the
    # current export schema — leave them out of the lookup so they fall
    # through to None.
    return lookup
