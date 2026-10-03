"""
Pre-generation validators for dbt project generation.

Validates export data before generation to catch common errors early.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from engine.services.source_values import ValueKind, classify

if TYPE_CHECKING:
    from engine.services.export.models import (
        HubDefinition,
        LinkDefinition,
        PITDefinition,
        ProjectExport,
        SatelliteDefinition,
        SnapshotControlDefinition,
        SourceDefinition,
        StageDefinition,
    )


@dataclass
class ValidationError:
    """Represents a validation error (blocks generation in strict mode)."""

    entity_type: str
    entity_name: str
    field: str
    message: str
    code: str = ""

    def __str__(self) -> str:
        code_str = f"[{self.code}] " if self.code else ""
        return f"{code_str}{self.entity_type}:{self.entity_name} - {self.message}"


@dataclass
class ValidationWarning:
    """Represents a validation warning (logged but doesn't block generation)."""

    entity_type: str
    entity_name: str
    field: str
    message: str
    code: str = ""

    def __str__(self) -> str:
        code_str = f"[{self.code}] " if self.code else ""
        return f"{code_str}{self.entity_type}:{self.entity_name} - {self.message}"


@dataclass
class ValidationResult:
    """Result of pre-generation validation."""

    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationWarning] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True if there are no errors (warnings are allowed)."""
        return len(self.errors) == 0

    def add_error(
        self,
        entity_type: str,
        entity_name: str,
        field: str,
        message: str,
        code: str = "",
    ) -> None:
        """Add a validation error."""
        self.errors.append(
            ValidationError(
                entity_type=entity_type,
                entity_name=entity_name,
                field=field,
                message=message,
                code=code,
            )
        )

    def add_warning(
        self,
        entity_type: str,
        entity_name: str,
        field: str,
        message: str,
        code: str = "",
    ) -> None:
        """Add a validation warning."""
        self.warnings.append(
            ValidationWarning(
                entity_type=entity_type,
                entity_name=entity_name,
                field=field,
                message=message,
                code=code,
            )
        )

    def merge(self, other: ValidationResult) -> None:
        """Merge another validation result into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


# A value that is only a column name, which datavault4dbt can type by itself.
_PLAIN_COLUMN = re.compile(r'[A-Za-z_][A-Za-z0-9_$]*|"[^"]+"')


def validate_export(
    project_export: ProjectExport, *, keeps_load_columns: bool = False
) -> ValidationResult:
    """
    Validate a project export before generation.

    Args:
        project_export: The project export to validate.
        keeps_load_columns: Whether the stages keep the columns their record
            source and load date are read from (datavault4dbt's
            ``copy_rsrc_ldts_input_columns``); by default they drop them.

    Returns:
        ValidationResult with any errors and warnings found.
    """
    result = ValidationResult()

    if not keeps_load_columns:
        result.merge(_validate_load_columns_unused(project_export))

    # Validate sources
    for source in project_export.sources:
        result.merge(_validate_source(source))

    # Validate stages
    for stage in project_export.stages:
        result.merge(_validate_stage(stage))

    # Validate hubs
    for hub in project_export.hubs:
        result.merge(_validate_hub(hub))

    # Validate links
    for link in project_export.links:
        result.merge(_validate_link(link))

    # Validate satellites
    for satellite in project_export.satellites:
        result.merge(_validate_satellite(satellite))

    # Validate PITs
    for pit in project_export.pits:
        result.merge(_validate_pit(pit))

    # Validate snapshot controls
    for snap_ctrl in project_export.snapshot_controls:
        result.merge(_validate_snapshot_control(snap_ctrl))

    return result


def _validate_source(source: SourceDefinition) -> ValidationResult:
    """Validate a source definition."""
    result = ValidationResult()

    if not source.schema_name:
        result.add_error(
            entity_type="source",
            entity_name=source.source_system,
            field="schema_name",
            message="Source must have a schema name",
            code="SRC_001",
        )

    if not source.tables:
        result.add_warning(
            entity_type="source",
            entity_name=source.source_system,
            field="tables",
            message="Source has no tables defined",
            code="SRC_002",
        )

    return result


def _validate_stage(stage: StageDefinition) -> ValidationResult:
    """Validate a stage definition."""
    result = ValidationResult()

    if not stage.source_table:
        result.add_error(
            entity_type="stage",
            entity_name=stage.stage_name,
            field="source_table",
            message="Stage must have a source table defined",
            code="STG_001",
        )

    if not stage.hashkeys and not stage.hashdiffs:
        result.add_warning(
            entity_type="stage",
            entity_name=stage.stage_name,
            field="hashkeys",
            message="Stage has no hashkeys or hashdiffs defined",
            code="STG_002",
        )

    # datavault4dbt looks a derived column's data type up only when its value
    # is a plain column name; for an expression, dbt fails to compile the stage.
    for derived in stage.derived_columns:
        value = (derived.transformation or "").strip()
        if value and not derived.datatype and not _PLAIN_COLUMN.fullmatch(value):
            result.add_warning(
                entity_type="stage",
                entity_name=stage.stage_name,
                field="derived_columns",
                message=(
                    f"Derived column '{derived.target_column_name}' has no data "
                    "type. datavault4dbt needs one for an SQL expression, and "
                    "the stage won't compile without it"
                ),
                code="STG_003",
            )

    return result


def _validate_load_columns_unused(project_export: ProjectExport) -> ValidationResult:
    """Warn when a model reads the column a stage turns into ``rsrc``/``ldts``.

    datavault4dbt renames a record source or load date read from a column to
    the stage's ``rsrc``/``ldts`` and doesn't pass the column on under its own
    name, so a hash key or satellite that names it fails in dbt.
    """
    result = ValidationResult()
    satellites_by_stage = defaultdict(list)
    for satellite in project_export.satellites:
        satellites_by_stage[satellite.stage_name].append(satellite)

    for stage in project_export.stages:
        load_columns: dict[str, str] = {}
        for label, value in (
            ("Record Source", stage.record_source),
            ("Load Date", stage.load_date),
        ):
            if value and classify(value) is ValueKind.COLUMN:
                load_columns[value.lower()] = label
        if not load_columns:
            continue

        uses: list[tuple[str, str]] = [
            (column, f"Hash Key {hashkey.hashkey_name}")
            for hashkey in stage.hashkeys
            for column in hashkey.business_key_columns
        ]
        uses += [
            (column.source_column, f"Satellite {satellite.satellite_name}")
            for satellite in satellites_by_stage[stage.stage_name]
            for column in satellite.columns
        ]
        reported: set[tuple[str, str]] = set()
        for column, user in uses:
            label = load_columns.get(column.lower())
            if label is None or (column.lower(), user) in reported:
                continue
            reported.add((column.lower(), user))
            result.add_warning(
                entity_type="stage",
                entity_name=stage.stage_name,
                field="columns",
                message=(
                    f"{user} uses {column}, the column the stage's {label} is "
                    "read from. datavault4dbt turns it into the stage's "
                    f"{label} and doesn't pass it on, so the model will fail. "
                    "Map another column, or set the datavault4dbt variable "
                    "copy_rsrc_ldts_input_columns"
                ),
                code="STG_004",
            )
    return result


def _validate_hub(hub: HubDefinition) -> ValidationResult:
    """Validate a hub definition."""
    result = ValidationResult()

    # Standard hubs must have hashkey
    if hub.hub_type == "standard":
        if not hub.hashkey or not getattr(hub.hashkey, "hashkey_name", None):
            result.add_error(
                entity_type="hub",
                entity_name=hub.hub_name,
                field="hashkey",
                message="Standard hub must have a hashkey defined",
                code="HUB_001",
            )

    # Standard hubs must have at least one business key
    if hub.hub_type == "standard":
        if not hub.business_key_columns:
            result.add_error(
                entity_type="hub",
                entity_name=hub.hub_name,
                field="business_key_columns",
                message="Standard Hub must have at least one business key column",
                code="HUB_002",
            )

    # Hub should have at least one source
    if not hub.source_tables:
        result.add_warning(
            entity_type="hub",
            entity_name=hub.hub_name,
            field="source_tables",
            message="Hub has no source tables defined",
            code="HUB_003",
        )

    return result


def _validate_link(link: LinkDefinition) -> ValidationResult:
    """Validate a link definition."""
    result = ValidationResult()

    # Links must have hashkey
    if not link.hashkey or not getattr(link.hashkey, "hashkey_name", None):
        result.add_error(
            entity_type="link",
            entity_name=link.link_name,
            field="hashkey",
            message="Link must have a hashkey defined",
            code="LNK_001",
        )

    # Links must reference at least 2 hubs (except non-historized links)
    if link.link_type != "non_historized":
        if not link.foreign_hashkeys or len(link.foreign_hashkeys) < 2:
            result.add_warning(
                entity_type="link",
                entity_name=link.link_name,
                field="foreign_hashkeys",
                message="A standard Link should reference at least 1 hub",
                code="LNK_002",
            )

    # Link MUST have at least one source table. Without it the generated dbt
    # model has an empty `source_models` block (an invalid datavault4dbt link)
    # and no stage computes the link hashkey. This happens when a link is
    # imported without a source_table, so no link_hub_source_mapping rows are
    # created. Fail loudly rather than emit a broken model.
    if not link.source_tables:
        result.add_error(
            entity_type="link",
            entity_name=link.link_name,
            field="source_tables",
            message=(
                "Link has no source tables — set a source_table on the link so "
                "its hub-key and hashkey source mappings (link_hub_source_mapping) "
                "can be created"
            ),
            code="LNK_003",
        )

    return result


def _validate_satellite(satellite: SatelliteDefinition) -> ValidationResult:
    """Validate a satellite definition."""
    result = ValidationResult()

    # Satellite must have parent entity
    if not satellite.parent_entity:
        result.add_error(
            entity_type="satellite",
            entity_name=satellite.satellite_name,
            field="parent_entity",
            message="Satellite must have a parent entity (hub or link)",
            code="SAT_001",
        )

    # Satellite must have stage
    if not satellite.stage_name:
        result.add_error(
            entity_type="satellite",
            entity_name=satellite.satellite_name,
            field="stage_name",
            message="Satellite must have a source stage assigned",
            code="SAT_002",
        )

    # Satellite should have at least one column (warning only)
    if not satellite.columns:
        result.add_warning(
            entity_type="satellite",
            entity_name=satellite.satellite_name,
            field="columns",
            message="Satellite has no payload columns defined",
            code="SAT_003",
        )

    # Standard satellites should have hashdiff
    if satellite.satellite_type == "standard" and not satellite.hashdiff_name:
        result.add_warning(
            entity_type="satellite",
            entity_name=satellite.satellite_name,
            field="hashdiff_name",
            message="Standard satellite should have a hashdiff defined",
            code="SAT_004",
        )

    return result


def _validate_pit(pit: PITDefinition) -> ValidationResult:
    """Validate a PIT definition."""
    result = ValidationResult()

    # PIT must have at least one satellite
    if not pit.satellites:
        result.add_error(
            entity_type="pit",
            entity_name=pit.pit_name,
            field="satellites",
            message="PIT must have at least one satellite",
            code="PIT_001",
        )

    # PIT must have snapshot logic column
    if not pit.snapshot_logic_column:
        result.add_error(
            entity_type="pit",
            entity_name=pit.pit_name,
            field="snapshot_logic_column",
            message="PIT must have a snapshot logic column",
            code="PIT_002",
        )

    # PIT must have tracked entity
    if not pit.tracked_entity_name:
        result.add_error(
            entity_type="pit",
            entity_name=pit.pit_name,
            field="tracked_entity_name",
            message="PIT must have a tracked entity (hub or link)",
            code="PIT_003",
        )

    return result


def _validate_snapshot_control(
    snap_ctrl: SnapshotControlDefinition,
) -> ValidationResult:
    """Validate a snapshot control definition."""
    result = ValidationResult()

    # Must have name
    if not snap_ctrl.name:
        result.add_error(
            entity_type="snapshot_control",
            entity_name="unknown",
            field="name",
            message="Snapshot control must have a name",
            code="SNAP_001",
        )

    # Must have start date
    if not snap_ctrl.start_date:
        result.add_error(
            entity_type="snapshot_control",
            entity_name=snap_ctrl.name or "unknown",
            field="start_date",
            message="Snapshot control must have a start date",
            code="SNAP_002",
        )

    # Should have at least one logic pattern (warning)
    if not snap_ctrl.logic_patterns:
        result.add_warning(
            entity_type="snapshot_control",
            entity_name=snap_ctrl.name or "unknown",
            field="logic_patterns",
            message="Snapshot control has no logic patterns defined",
            code="SNAP_003",
        )

    return result
