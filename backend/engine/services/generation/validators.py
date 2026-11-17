"""
Pre-generation validators for dbt project generation.

Validates export data before generation to catch common errors early.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from engine.services.generation.name_validation import validate_names
from engine.services.source_values import ValueKind, classify

if TYPE_CHECKING:
    from engine.services.export.models import (
        HubDefinition,
        LinkDefinition,
        ModelOutputDef,
        PITDefinition,
        ProjectExport,
        SatelliteDefinition,
        SnapshotControlDefinition,
        SourceDefinition,
        StageDefinition,
        StageHashdiffDef,
        StageHashkeyDef,
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
    project_export: ProjectExport,
    *,
    keeps_load_columns: bool = False,
    generate_satellite_v1_views: bool = True,
) -> ValidationResult:
    """
    Validate a project export before generation.

    Args:
        project_export: The project export to validate.
        keeps_load_columns: Whether the stages keep the columns their record
            source and load date are read from (datavault4dbt's
            ``copy_rsrc_ldts_input_columns``); by default they drop them.
        generate_satellite_v1_views: Whether satellites get their v1 views,
            whose names then count among the project's model names.

    Returns:
        ValidationResult with any errors and warnings found.
    """
    result = ValidationResult()

    if not keeps_load_columns:
        result.merge(_validate_load_columns_unused(project_export))

    # Model names and folders: one model per name, files inside the project
    result.merge(_validate_models(project_export, generate_satellite_v1_views))

    # Reference tables read v1 views
    result.merge(
        _validate_reference_tables(project_export, generate_satellite_v1_views)
    )

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

    # Validate names: Data Vault names, case collisions, quoted source names
    validate_names(project_export, result)

    return result


def _project_models(
    project_export: ProjectExport, generate_satellite_v1_views: bool
) -> list[tuple[str, str, ModelOutputDef | None, str]]:
    """Every dbt model of the project: (entity type, entity, output, name).

    Pre-stages count too: they are models of the dbt project. Entities whose
    export carries no resolved output (older exports) are left out.
    """
    models: list[tuple[str, str, ModelOutputDef | None, str]] = []
    for stage in project_export.stages:
        models.append(("stage", stage.stage_name, stage.output, stage.stage_name))
    for prestage in project_export.prestages:
        models.append(("prestage", prestage.model_name, None, prestage.model_name))
    for hub in project_export.hubs:
        if hub.output:
            models.append(("hub", hub.hub_name, hub.output, hub.output.model_name))
        for flag, output in (
            (hub.create_effectivity_satellite, hub.effectivity_satellite_output),
            (
                hub.create_record_tracking_satellite,
                hub.record_tracking_satellite_output,
            ),
        ):
            if flag and output:
                models.append(("hub", hub.hub_name, output, output.model_name))
    for link in project_export.links:
        if link.output:
            models.append(("link", link.link_name, link.output, link.output.model_name))
        for flag, output in (
            (link.create_effectivity_satellite, link.effectivity_satellite_output),
            (
                link.create_record_tracking_satellite,
                link.record_tracking_satellite_output,
            ),
        ):
            if flag and output:
                models.append(("link", link.link_name, output, output.model_name))
    for sat in project_export.satellites:
        if sat.v0_output:
            models.append(
                (
                    "satellite",
                    sat.satellite_name,
                    sat.v0_output,
                    sat.v0_output.model_name,
                )
            )
        if sat.v1_output and sat.gets_v1_view(generate_satellite_v1_views):
            models.append(
                (
                    "satellite",
                    sat.satellite_name,
                    sat.v1_output,
                    sat.v1_output.model_name,
                )
            )
    for pit in project_export.pits:
        if pit.output:
            models.append(("pit", pit.pit_name, pit.output, pit.output.model_name))
    for table in project_export.reference_tables:
        if table.output:
            models.append(
                (
                    "reference_table",
                    table.table_name,
                    table.output,
                    table.output.model_name,
                )
            )
    for control in project_export.snapshot_controls:
        for output in (control.v0_output, control.v1_output):
            if output:
                models.append(
                    ("snapshot_control", control.name, output, output.model_name)
                )
    return models


def _validate_models(
    project_export: ProjectExport, generate_satellite_v1_views: bool
) -> ValidationResult:
    """Each model name names one model, and every file stays in the project.

    dbt refuses two models of one name. A name or folder that leaves the
    project (slashes, '..', absolute paths) would write outside it.
    """
    from engine.models.model_output import folder_error

    result = ValidationResult()
    seen: dict[str, tuple[str, str]] = {}
    for entity_type, entity_name, output, model_name in _project_models(
        project_export, generate_satellite_v1_views
    ):
        if (
            not model_name
            or model_name in (".", "..")
            or any(char in model_name for char in "/\\\x00")
        ):
            result.add_error(
                entity_type=entity_type,
                entity_name=entity_name,
                field="model_name",
                message=(
                    f"'{model_name}' can't name a dbt model file: no slashes or '..'"
                ),
                code="MDL_002",
            )
            continue
        if output is not None and output.folder:
            if error := folder_error(output.folder):
                result.add_error(
                    entity_type=entity_type,
                    entity_name=entity_name,
                    field="folder",
                    message=f"{error} (model '{model_name}')",
                    code="MDL_003",
                )
        key = model_name.lower()
        if key in seen:
            other_type, other_name = seen[key]
            result.add_error(
                entity_type=entity_type,
                entity_name=entity_name,
                field="model_name",
                message=(
                    f"Model '{model_name}' of {entity_type} '{entity_name}' has "
                    f"the name of a model of {other_type} '{other_name}': dbt "
                    "needs a name per model. Rename one of them."
                ),
                code="MDL_001",
            )
        else:
            seen[key] = (entity_type, entity_name)
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

    # One hash key column per name: hubs and links naming theirs alike get it
    # once, for the first (entities sharing a key hash the same columns).
    hashkeys: dict[str, StageHashkeyDef] = {}
    for hashkey in stage.hashkeys:
        first = hashkeys.setdefault(hashkey.hashkey_name.lower(), hashkey)
        if first is not hashkey and first.business_key_columns != (
            hashkey.business_key_columns
        ):
            result.add_warning(
                entity_type="stage",
                entity_name=stage.stage_name,
                field="hashkeys",
                message=(
                    f"{first.entity_type.capitalize()} '{first.target_entity}' and "
                    f"{hashkey.entity_type} '{hashkey.target_entity}' both name "
                    f"their hash key '{hashkey.hashkey_name}' but hash different "
                    f"columns: the stage computes it once, for "
                    f"'{first.target_entity}'. Give one of them its own hash key "
                    "name."
                ),
                code="STG_006",
            )

    # One hash diff column per name: satellites may share one only if they hash
    # the same columns (a stored hash diff name can make two collide).
    hashdiffs: dict[str, StageHashdiffDef] = {}
    for hashdiff in stage.hashdiffs:
        other = hashdiffs.setdefault(hashdiff.hashdiff_name.lower(), hashdiff)
        if other is not hashdiff and other.columns != hashdiff.columns:
            result.add_error(
                entity_type="stage",
                entity_name=stage.stage_name,
                field="hashdiffs",
                message=(
                    f"Satellites '{other.satellite_name}' and "
                    f"'{hashdiff.satellite_name}' both name their hash diff "
                    f"'{hashdiff.hashdiff_name}' but hash different columns. "
                    "Give one of them its own hash diff name."
                ),
                code="STG_005",
            )

    return result


def _validate_reference_tables(
    project_export: ProjectExport, generate_satellite_v1_views: bool
) -> ValidationResult:
    """A reference table reads its satellites' v1 views, which must exist."""
    result = ValidationResult()
    satellites = {sat.satellite_name: sat for sat in project_export.satellites}
    for table in project_export.reference_tables:
        for assignment in table.satellites:
            satellite = satellites.get(assignment.satellite_name)
            if satellite is not None and not satellite.gets_v1_view(
                generate_satellite_v1_views
            ):
                result.add_warning(
                    entity_type="reference_table",
                    entity_name=table.table_name,
                    field="satellites",
                    message=(
                        f"Reference table '{table.table_name}' reads the v1 view "
                        f"of satellite '{assignment.satellite_name}', which gets "
                        "none. Turn on its v1 view."
                    ),
                    code="REF_001",
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
        hubs = len(link.foreign_hashkeys or [])
        if hubs < 2:
            result.add_warning(
                entity_type="link",
                entity_name=link.link_name,
                field="foreign_hashkeys",
                message=(
                    "A standard Link should connect at least two Hubs; this one "
                    f"connects {'none' if hubs == 0 else 'one'}"
                ),
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

    # datavault4dbt's nh_link requires a payload: the link's dependent child
    # keys and payload columns
    if link.link_type == "non_historized" and not (
        link.payload_columns or link.dependent_child_keys
    ):
        result.add_error(
            entity_type="link",
            entity_name=link.link_name,
            field="payload_columns",
            message=(
                "A non-historized link needs at least one payload column or "
                "dependent child key: datavault4dbt can't build it without a "
                "payload"
            ),
            code="LNK_004",
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
