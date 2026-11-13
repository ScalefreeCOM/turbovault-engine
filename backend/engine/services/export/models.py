"""
Intermediate Pydantic models for Data Vault export.

These models provide a target-agnostic representation of the Data Vault
that can be serialized to various output formats (JSON, dbt, DBML, etc.).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# Satellite types with a v1 view (load end date) on top of their v0 table.
V1_SATELLITE_TYPES = frozenset({"standard", "effectivity", "multi_active", "reference"})


# =============================================================================
# Generated dbt models
# =============================================================================


class ModelOutputDef(BaseModel):
    """A generated dbt model: its name and the settings it's generated with.

    ``model_name`` is always set: the stored name, else the one TurboVault
    derives. The other fields are the model's stored settings (see
    ``engine.models.ModelOutput``); None keeps TurboVault's defaults. Derived
    from the project: the JSON import doesn't read it back.
    """

    model_name: str
    folder: str | None = Field(
        None, description="Folder of the model's files, relative to the dbt project"
    )
    alias: str | None = None
    schema_name: str | None = None
    database_name: str | None = None
    materialized: str | None = None
    tags: list[str] | None = Field(
        None, description="Tags replacing TurboVault's default tags"
    )
    config: dict[str, Any] | None = Field(
        None, description="Further config() keys, written as they are"
    )

    def settings(self) -> dict[str, Any]:
        """The stored config() settings, without empty values."""
        values = {
            "materialized": self.materialized,
            "alias": self.alias,
            "schema": self.schema_name,
            "database": self.database_name,
        }
        settings: dict[str, Any] = {k: v for k, v in values.items() if v}
        if self.tags is not None:
            settings["tags"] = list(self.tags)
        settings.update(self.config or {})
        return settings


# =============================================================================
# Source Layer Models
# =============================================================================


class SourceColumnDef(BaseModel):
    """Definition of a source column."""

    column_name: str
    datatype: str
    description: str | None = None
    is_missing: bool = Field(
        default=False,
        description=(
            "The source no longer has the column: the stage adds it with NULL "
            "values (missing_columns), and the dbt source leaves it out"
        ),
    )


class SourceDerivedColumnDef(BaseModel):
    """A column the stage computes with a SQL expression (a derived column).

    Defined on its source table and mapped like any other column of it.
    """

    column_name: str
    expression: str = Field(
        description=(
            "SQL expression computing the value from the source table's "
            "columns, in the target platform's dialect"
        )
    )
    datatype: str | None = Field(
        default=None, description="Data type of the computed value"
    )
    description: str | None = None


class SourceTableDef(BaseModel):
    """Definition of a source table with its columns and metadata."""

    table_name: str
    table_type: Literal["physical", "prestage"] = Field(
        default="physical",
        description=(
            "physical: a table of the source system, read with source(). "
            "prestage: a dbt model of the project (pre-stage) the stage reads "
            "with ref(); the dbt project maintains it"
        ),
    )
    alias: str | None = None
    # As the table sets them; None inherits from the system and the project.
    record_source: str | None = None
    static_part_of_record_source: str | None = None
    load_date: str | None = None
    # Stage options as the table sets them; None inherits.
    include_source_columns: bool | None = None
    enable_ghost_records: bool | None = None
    sequence_column: str | None = None
    description: str | None = None
    columns: list[SourceColumnDef] = Field(default_factory=list)
    derived_columns: list[SourceDerivedColumnDef] = Field(
        default_factory=list,
        description="Columns the stage computes from this table's columns",
    )


class SourceSystemDef(BaseModel):
    """Definition of a source system containing multiple tables."""

    name: str
    schema_name: str
    database_name: str | None = None
    description: str | None = None
    # Inherited by the system's tables that set none.
    record_source: str | None = None
    static_part_of_record_source: str | None = None
    load_date: str | None = None
    include_source_columns: bool | None = None
    enable_ghost_records: bool | None = None
    tables: list[SourceTableDef] = Field(default_factory=list)


class ColumnDescriptionDef(BaseModel):
    """A Raw Vault column's description.

    ``description`` is the column's own, ``source_description`` the one of the
    source column it is loaded from, which applies when it has none. Only
    ``description`` is read back on import, so an inherited description stays
    inherited across an export/import round trip.
    """

    description: str | None = None
    source_description: str | None = None

    @property
    def effective(self) -> str | None:
        return self.description or self.source_description


# =============================================================================
# Hub Layer Models
# =============================================================================


class HashkeyDefinition(BaseModel):
    """Definition of a hashkey with its constituent business keys."""

    hashkey_name: str
    business_keys: list[str] = Field(
        default_factory=list,
        description="Column names that compose this hashkey, in order",
    )


class HubColumnMapping(BaseModel):
    """Explicit mapping from a hub column name to its source column name."""

    hub_column: str
    source_column: str
    target_column_transformation: str | None = Field(
        default=None,
        description=(
            "Optional SQL transformation (hard business rule) applied to the "
            "source column in the stage before the business key is hashed. "
            "Belongs to the hub column, so it repeats on every source mapping "
            "of that column."
        ),
    )
    target_column_datatype: str | None = Field(
        default=None,
        description=(
            "Data type of the transformed value; the source column's data type "
            "when omitted. Repeats on every source mapping, like the "
            "transformation."
        ),
    )


class HubSourceInfo(BaseModel):
    """Information about a source table feeding a hub."""

    source_table: str
    source_system: str
    stage_name: str = Field(description="Stage model name for this source table")
    rsrc_static: str | None = Field(
        default=None,
        description="Static part of the source table's record source, if set",
    )
    business_key_columns: list[str] = Field(
        default_factory=list, description="Source columns mapped to business keys"
    )
    is_primary_source: bool = Field(
        default=True,
        description="Whether this source table is the primary source for this hub",
    )
    column_mappings: list[HubColumnMapping] = Field(
        default_factory=list,
        description="Explicit hub column → source column mappings for round-trip import",
    )


class HubDefinition(BaseModel):
    """
    Definition of a Data Vault hub.

    Contains all metadata needed to generate hub-related artifacts.
    """

    hub_name: str
    hub_type: str  # "standard" or "reference"
    group: str | None = None
    hashkey: HashkeyDefinition | None = None
    business_key_columns: list[str] = Field(
        default_factory=list, description="Target hub column names for business keys"
    )
    reference_key_columns: list[str] = Field(
        default_factory=list,
        description="Target hub column names for reference keys (for reference hubs)",
    )
    additional_columns: list[str] = Field(
        default_factory=list, description="Additional non-key columns in the hub"
    )
    source_tables: list[HubSourceInfo] = Field(
        default_factory=list, description="Source tables that feed this hub"
    )
    create_record_tracking_satellite: bool = False
    create_effectivity_satellite: bool = True
    description: str | None = None
    column_descriptions: dict[str, ColumnDescriptionDef] = Field(
        default_factory=dict,
        description="Descriptions by hub column name, for columns that have one",
    )
    output: ModelOutputDef | None = Field(
        None, description="The hub's dbt model (None: named hub_name, defaults)"
    )
    effectivity_satellite_output: ModelOutputDef | None = Field(
        None, description="The effectivity satellite's model, when the hub has one"
    )
    record_tracking_satellite_output: ModelOutputDef | None = Field(
        None, description="The record-tracking satellite's model, when the hub has one"
    )


# =============================================================================
# Link Layer Models
# =============================================================================


class PrejoinCondition(BaseModel):
    """Prejoin join condition for staging."""

    source_columns: list[str] = Field(
        default_factory=list, description="Join column names from source table"
    )
    target_columns: list[str] = Field(
        default_factory=list, description="Join column names from target table"
    )
    operator: str = Field(
        default="AND", description="Operator for multiple conditions: AND or OR"
    )


class PrejoinExtractionColumn(BaseModel):
    """Column extracted from target table."""

    source_column_name: str
    target_column_alias: str | None = None


class PrejoinDefinitionExport(BaseModel):
    """Prejoin definition exported to stage."""

    target_table: str = Field(description="Target table physical name to join")
    target_source_system: str | None = Field(
        default=None,
        description=(
            "Source system of the target table. Omit (or null) when the target "
            "lives in the same source system as the stage; importers fall back "
            "to the stage's own source system in that case."
        ),
    )
    target_model: str | None = Field(
        default=None,
        description=(
            "The pre-stage model of the target table, when that is a pre-stage: "
            "the stage then prejoins the model (ref_model) instead of a source"
        ),
    )
    join_conditions: PrejoinCondition = Field(
        description="Join conditions between source and target"
    )
    extraction_columns: list[PrejoinExtractionColumn] = Field(
        default_factory=list, description="Columns extracted from target table"
    )


class LinkColumnMapping(BaseModel):
    """Mapping of link column to source column."""

    link_column_name: str
    link_column_type: str  # business_key, payload, or additional_column
    source_column_name: str
    source_prejoin_target_table: str | None = Field(
        default=None,
        description=(
            "Set when `source_column_name` is not a column of `source_table` but "
            "is brought in by a prejoin from `source_table` to this target table. "
            "`source_column_name` then names the extracted column as it appears in "
            "the stage (the extraction alias, else the target column's physical "
            "name). Omit (or null) for ordinary direct source columns."
        ),
    )
    source_prejoin_target_source_system: str | None = Field(
        default=None,
        description=(
            "Source system of `source_prejoin_target_table`. Omit (or null) when "
            "the prejoin target lives in the same source system as `source_table`; "
            "importers fall back to that system. Ignored when "
            "`source_prejoin_target_table` is null."
        ),
    )
    target_foreign_hashkey: str | None = Field(
        default=None,
        description=(
            "For business_key mappings only: the foreign hashkey (hub hashkey "
            "alias, else hub hashkey name) of the specific link hub reference this "
            "mapping feeds. Disambiguates links that reference the same hub more "
            "than once; ignored for non-business-key columns."
        ),
    )
    target_column_transformation: str | None = Field(
        default=None,
        description=(
            "Optional SQL transformation (hard business rule) applied to the "
            "source column in the stage before the value is hashed. For "
            "business_key mappings this is the transformation of the referenced "
            "hub column; otherwise it is the link column's own transformation."
        ),
    )
    target_column_datatype: str | None = Field(
        default=None,
        description=(
            "Data type of the transformed value, from the same column as "
            "target_column_transformation; the source column's data type when "
            "omitted."
        ),
    )


class LinkSourceHashkeyMapping(BaseModel):
    """
    Mapping of a Link Foreign Hashkey to a Stage Hashkey.

    Defines which hashkey from the source stage is used to populate
    a specific foreign hashkey in the link.
    """

    target_foreign_hashkey: str = Field(
        description="The foreign hashkey in the Link this maps to"
    )
    source_stage_hashkey: str = Field(
        description="The hashkey column in the stage model"
    )


class LinkSourceInfo(BaseModel):
    """Information about source tables feeding a link."""

    source_table: str
    source_system: str
    stage_name: str = Field(description="Stage model name for this source table")
    rsrc_static: str | None = Field(
        default=None,
        description="Static part of the source table's record source, if set",
    )
    columns: list[LinkColumnMapping] = Field(
        default_factory=list, description="Mapped columns from this source table"
    )
    hashkey_mappings: list[LinkSourceHashkeyMapping] = Field(
        default_factory=list,
        description="Mappings from link foreign hashkeys to stage hashkeys",
    )


class LinkHubReferenceDefinition(BaseModel):
    """Definition of a hub reference in a link."""

    hub_name: str
    hub_hashkey_alias_in_link: str | None = None


class LinkDefinition(BaseModel):
    """
    Definition of a Data Vault link.

    Contains all metadata needed to generate link-related artifacts.
    """

    link_name: str
    link_type: str  # "standard" or "non_historized"
    group: str | None = None
    hashkey: HashkeyDefinition = Field(description="Link hashkey definition")
    hub_references: list[LinkHubReferenceDefinition] = Field(
        default_factory=list, description="Hubs connected by this link"
    )
    foreign_hashkeys: list[str] = Field(
        default_factory=list,
        description="Hashkey names from referenced hubs (for datavault4dbt)",
    )
    business_key_columns: list[str] = Field(
        default_factory=list, description="Link column names with type business_key"
    )
    payload_columns: list[str] = Field(
        default_factory=list, description="Payload columns in the link"
    )
    additional_columns: list[str] = Field(
        default_factory=list, description="Additional non-payload columns"
    )
    source_tables: list[LinkSourceInfo] = Field(
        default_factory=list,
        description="Source tables that feed this link with column mappings",
    )
    create_record_tracking_satellite: bool = False
    description: str | None = None
    output: ModelOutputDef | None = Field(
        None, description="The link's dbt model (None: named link_name, defaults)"
    )
    record_tracking_satellite_output: ModelOutputDef | None = Field(
        None,
        description="The record-tracking satellite's model, when the link has one",
    )
    column_descriptions: dict[str, ColumnDescriptionDef] = Field(
        default_factory=dict,
        description="Descriptions by link column name, for columns that have one",
    )


# =============================================================================
# Stage Layer Models
# =============================================================================


class PrestageDefinition(BaseModel):
    """A pre-stage: a dbt model of the project that prepares data for a stage.

    Built from a source table of type ``prestage``. The dbt project maintains
    the model; TurboVault generates no file for it, and its stage reads it
    with ``ref()``.
    """

    model_name: str = Field(
        description="Name of the dbt model, e.g. pstg__crm__customer_address"
    )
    table_name: str = Field(description="Name of the pre-stage's source table")
    source_system: str = Field(description="Source system the pre-stage belongs to")
    description: str | None = None
    columns: list[SourceColumnDef] = Field(
        default_factory=list, description="Columns the model provides"
    )


class StageHashkeyDef(BaseModel):
    """
    Hashkey definition within a stage model.

    Represents a hashkey calculation that must be performed in the stage
    for a specific hub or link.
    """

    target_entity: str = Field(description="Target entity name (e.g., 'hub_customer')")
    entity_type: str = Field(
        default="hub", description="Type of entity: 'hub' or 'link'"
    )
    hashkey_name: str = Field(description="Name of the hashkey column")
    business_key_columns: list[str] = Field(
        default_factory=list, description="Source columns used to compute this hashkey"
    )


class StageHashdiffDef(BaseModel):
    """
    Hashdiff definition within a stage model.

    Represents a hashdiff calculation for a satellite.
    """

    satellite_name: str = Field(description="Target satellite name")
    hashdiff_name: str = Field(
        description="Name of the hashdiff column (e.g., 'hd_customer_details')"
    )
    columns: list[str] = Field(
        default_factory=list,
        description="Source columns included in hashdiff calculation",
    )


class DerivedColumnDef(BaseModel):
    """
    Derived column definition within a stage model.

    A column the stage computes: a derived column defined on the source table,
    a Raw Vault column's transformation, or a satellite column's rename.
    """

    target_column_name: str = Field(description="Name of the column in the stage")
    source_column_name: str = Field(
        description=(
            "The stage column it is computed from. For an expression over "
            "several columns, the first one it reads"
        )
    )
    datatype: str = Field(
        default="",
        description=(
            "Data type of the value. datavault4dbt needs it for an expression "
            "to build ghost records"
        ),
    )
    transformation: str | None = Field(
        None, description="SQL expression computing the value (if any)"
    )
    src_cols_required: list[str] = Field(
        default_factory=list,
        description="Source columns the value is computed from",
    )
    description: str | None = Field(
        default=None, description="Description of a derived column"
    )


class MultiActiveConfig(BaseModel):
    """
    Multi-active satellite configuration for a stage.

    Defines the multi-active key columns and associated parent hashkey.
    """

    multi_active_key: list[str] = Field(
        default_factory=list, description="Column(s) that form the multi-active key"
    )
    main_hashkey_column: str = Field(description="Parent hub/link hashkey column name")


class StageDefinition(BaseModel):
    """
    Definition of a staging model for a source table.

    Aggregates all hashkeys (from hubs and links) and hashdiffs (from satellites)
    that must be computed for this source table.
    """

    stage_name: str
    source_table: str
    source_schema: str
    source_system: str
    prestage_model: str | None = Field(
        default=None,
        description=(
            "The pre-stage model the stage reads with ref(), when its source "
            "table is a pre-stage. None: it reads the table as a dbt source"
        ),
    )
    record_source: str | None = None
    load_date: str | None = None
    output: ModelOutputDef | None = Field(
        None, description="The stage's dbt model (None: named stage_name, defaults)"
    )
    description: str | None = Field(
        default=None, description="Description of the source table"
    )

    # Stage options, resolved over table, source system and project
    include_source_columns: bool = Field(
        default=True, description="Whether the stage passes all source columns on"
    )
    enable_ghost_records: bool = Field(
        default=True, description="Whether the stage adds ghost records"
    )
    sequence_column: str | None = Field(
        default=None, description="Column holding the extraction's sequence number"
    )
    missing_columns: list[SourceColumnDef] = Field(
        default_factory=list,
        description="Columns the source no longer has: added with NULL values",
    )

    # Hashkey calculations for hubs
    hashkeys: list[StageHashkeyDef] = Field(
        default_factory=list, description="All hashkeys to compute in this stage"
    )

    # Hashdiff calculations for satellites
    hashdiffs: list[StageHashdiffDef] = Field(
        default_factory=list, description="All hashdiffs to compute in this stage"
    )

    # Prejoins applied in this stage
    prejoins: list[PrejoinDefinitionExport] = Field(
        default_factory=list, description="Prejoins applied in this stage"
    )

    # Multi-active configuration (if any multi-active satellite uses this source)
    multi_active_config: MultiActiveConfig | None = Field(
        None,
        description="Multi-active key config if a multi-active satellite uses this source",
    )

    # Derived columns (transformations or renames needed for satellite processing)
    derived_columns: list[DerivedColumnDef] = Field(
        default_factory=list,
        description="Derived columns from satellites with transformations or renamed targets",
    )

    # Source columns
    columns: list[SourceColumnDef] = Field(
        default_factory=list, description="Source columns available in this stage"
    )


# =============================================================================
# Satellite Layer Models
# =============================================================================


class SatelliteColumnDef(BaseModel):
    """Definition of a satellite column."""

    source_column: str = Field(description="Source column physical name")
    target_column_name: str | None = Field(
        None, description="Target column name (if renamed from source)"
    )
    is_multi_active_key: bool = Field(
        default=False, description="Whether this column is part of multi-active key"
    )
    include_in_delta_detection: bool = Field(
        default=True, description="Whether to include in hashdiff calculation"
    )
    target_column_transformation: str | None = Field(
        None, description="Optional transformation expression"
    )
    target_column_datatype: str | None = Field(
        None,
        description=(
            "Data type of the transformed value; the source column's data type "
            "when omitted"
        ),
    )
    description: str | None = Field(
        None, description="The column's own description (None: inherited)"
    )
    source_description: str | None = Field(
        None,
        description="Description of the source column, which applies when it has none",
    )


class SatelliteDefinition(BaseModel):
    """
    Definition of a Data Vault satellite.

    Contains all metadata needed to generate satellite-related artifacts.
    """

    satellite_name: str
    satellite_type: str = Field(
        description="Type: standard, reference, non_historized, or multi_active"
    )
    group: str | None = None
    parent_entity: str = Field(description="Name of parent hub or link")
    parent_entity_type: str = Field(description="Type of parent: 'hub' or 'link'")
    parent_hashkey: str = Field(
        description="Hashkey name of parent hub or link (for datavault4dbt)"
    )
    parent_business_keys: list[str] = Field(
        default_factory=list,
        description="Business key columns of parent (for reference satellites)",
    )
    source_table: str = Field(description="Source table name that feeds this satellite")
    source_system: str = Field(description="Source system name")
    stage_name: str = Field(description="Stage model name that feeds this satellite")
    hashdiff_name: str = Field(
        description="The stage's hash diff column for this satellite"
    )
    hashdiff_alias: str | None = Field(
        None,
        description=(
            "The hash diff column's name inside the satellite, when it differs "
            "from the stage's"
        ),
    )
    columns: list[SatelliteColumnDef] = Field(
        default_factory=list, description="Satellite columns"
    )
    description: str | None = None
    v0_output: ModelOutputDef | None = Field(
        None, description="The satellite's v0 model (None: the v0 naming pattern)"
    )
    v1_output: ModelOutputDef | None = Field(
        None,
        description=(
            "The satellite's v1 view, for the types that have one (generated "
            "when v1 views are on)"
        ),
    )
    create_v1_view: bool | None = Field(
        None, description="Whether it gets a v1 view; None: the project's setting"
    )
    v1_ledts_alias: str | None = Field(
        None, description="Load end date column of the v1 view (None: the variable)"
    )
    v1_add_is_current_flag: bool = Field(
        True, description="Whether the v1 view adds an is_current flag"
    )
    v1_include_payload: bool = Field(
        True, description="Whether the v1 view includes the payload"
    )

    @property
    def hashdiff_column(self) -> str:
        """The hash diff column inside the satellite: its alias, else its name."""
        return self.hashdiff_alias or self.hashdiff_name

    def gets_v1_view(self, project_default: bool) -> bool:
        """Whether the satellite gets a v1 view: its own setting, else the project's.

        Only the types with a load end date view have one.
        """
        if self.satellite_type not in V1_SATELLITE_TYPES:
            return False
        if self.create_v1_view is not None:
            return self.create_v1_view
        return project_default


# =============================================================================
# Project Export (Root Model)
# =============================================================================


# ============================================================================
# REFERENCE TABLE MODELS
# ============================================================================


class ReferenceTableSatelliteAssignment(BaseModel):
    """Satellite assignment for a reference table."""

    satellite_name: str = Field(description="Name of the reference satellite")
    model_name: str | None = Field(
        None, description="The satellite's v1 model, which the reference table reads"
    )
    include_columns: list[str] = Field(
        default_factory=list,
        description="Specific columns to include (if empty, includes all except excluded)",
    )
    exclude_columns: list[str] = Field(
        default_factory=list,
        description="Specific columns to exclude (only used if include_columns is empty)",
    )


class ReferenceTableDefinition(BaseModel):
    """Reference table definition."""

    table_name: str = Field(description="Physical name of the reference table")
    group: str | None = None
    reference_hub_name: str = Field(
        description="Name of the reference hub this table is based on"
    )
    historization_type: str = Field(
        description="Historization strategy: latest, full, or snapshot_based"
    )
    snapshot_control_table: str | None = Field(
        None, description="Snapshot control table name (if snapshot_based)"
    )
    snapshot_logic_column: str | None = Field(
        None, description="Snapshot logic column name (if snapshot_based)"
    )
    satellites: list[ReferenceTableSatelliteAssignment] = Field(
        default_factory=list, description="Reference satellite assignments"
    )
    description: str | None = None
    output: ModelOutputDef | None = Field(
        None, description="The reference table's dbt model (None: named table_name)"
    )


class PITDefinition(BaseModel):
    """Point-in-Time structure definition."""

    pit_name: str = Field(description="Physical name of the PIT structure")
    group: str | None = None
    tracked_entity_type: str = Field(description="Type of tracked entity: hub or link")
    tracked_entity_name: str = Field(description="Name of the tracked hub or link")
    tracked_hashkey: str = Field(description="Hashkey name of the tracked hub or link")
    satellites: list[str] = Field(
        default_factory=list, description="List of satellite names included in the PIT"
    )
    satellite_models: list[str] = Field(
        default_factory=list,
        description="The v0 models of those satellites, which the PIT reads",
    )
    snapshot_control_name: str = Field(
        description="Name of the snapshot control table (v1)"
    )
    snapshot_logic_column: str = Field(description="Snapshot logic column name")
    dimension_key_column: str | None = Field(
        None, description="Optional dimension key column name"
    )
    pit_type: str | None = Field(None, description="Optional PIT type classification")
    use_snapshot_optimization: bool = Field(
        default=True, description="Whether snapshot optimization is enabled"
    )
    include_business_objects_before_appearance: bool = Field(
        default=False,
        description="Whether to include business keys before first appearance",
    )
    output: ModelOutputDef | None = Field(
        None, description="The PIT's dbt model (None: named pit_name, defaults)"
    )


# ============================================================================
# SNAPSHOT CONTROL MODELS
# ============================================================================


class SnapshotLogicPattern(BaseModel):
    """Snapshot logic pattern definition."""

    column_name: str = Field(description="Column name for this snapshot logic")
    component: str = Field(
        description="Snapshot component (daily, end_of_week, end_of_month, etc.)"
    )
    duration: int | None = Field(None, description="Duration value (e.g., 1, 7, 30)")
    unit: str | None = Field(
        None, description="Duration unit (DAY, WEEK, MONTH, QUARTER, YEAR)"
    )
    forever: bool = Field(
        default=False, description="If true, snapshots are kept indefinitely"
    )


class SnapshotControlDefinition(BaseModel):
    """
    Snapshot control table definition.

    During dbt generation, this produces two models:
    - `{name}_v0`: The snapshot control table model (base metadata)
    - `{name}_v1`: The snapshot control logic model (logic patterns)
    """

    name: str = Field(
        description=(
            "Name of the snapshot control (e.g., 'control_snap'). May carry a "
            "_v0/_v1 suffix, e.g. 'control_snap_v0', which model names drop"
        )
    )
    start_date: str = Field(description="Overall snapshot start date (YYYY-MM-DD)")
    end_date: str = Field(description="Overall snapshot end date (YYYY-MM-DD)")
    daily_time: str = Field(description="Daily snapshot execution time (HH:MM:SS)")
    logic_patterns: list[SnapshotLogicPattern] = Field(
        default_factory=list, description="List of snapshot logic patterns"
    )
    v0_output: ModelOutputDef | None = Field(
        None, description="The control table's model (None: named <base>_v0)"
    )
    v1_output: ModelOutputDef | None = Field(
        None, description="The control logic's model (None: named <base>_v1)"
    )

    @property
    def base_name(self) -> str:
        """The name without a _v0/_v1 suffix: 'control_snap_v0' -> 'control_snap'."""
        return self.name.removesuffix("_v0").removesuffix("_v1")

    @property
    def v0_name(self) -> str:
        """
        Model name of the snapshot control table: its stored name, else
        ``<base>_v0``.

        Used for the base snapshot control model that contains
        start_date, end_date, and daily_time configuration.
        """
        if self.v0_output is not None:
            return self.v0_output.model_name
        return f"{self.base_name}_v0"

    @property
    def v1_name(self) -> str:
        """
        Model name of the snapshot control logic: its stored name, else
        ``<base>_v1``.

        Used for the model that implements the logic patterns
        (daily, weekly, monthly, etc. snapshot windows).
        """
        if self.v1_output is not None:
            return self.v1_output.model_name
        return f"{self.base_name}_v1"


# ============================================================================
# PROJECT EXPORT MODEL
# ============================================================================


class ProjectExport(BaseModel):
    """
    Complete export of a Data Vault project.

    Contains all definitions needed to generate target artifacts.
    """

    project_name: str
    project_description: str | None = None
    generated_at: datetime = Field(default_factory=datetime.now)

    # Configuration
    stage_schema: str | None = None
    rdv_schema: str | None = None
    bdv_schema: str | None = None

    # Export configuration
    export_sources: bool = True
    generate_tests: bool = True
    generate_dbml: bool = False

    # Definitions
    sources: list[SourceSystemDef] = Field(
        default_factory=list, description="Source system definitions"
    )
    hubs: list[HubDefinition] = Field(
        default_factory=list, description="Hub definitions"
    )
    prestages: list[PrestageDefinition] = Field(
        default_factory=list, description="Pre-stage model definitions"
    )
    stages: list[StageDefinition] = Field(
        default_factory=list, description="Stage model definitions"
    )
    satellites: list[SatelliteDefinition] = Field(
        default_factory=list, description="Satellite definitions"
    )
    links: list[LinkDefinition] = Field(
        default_factory=list, description="Link definitions"
    )

    snapshot_controls: list[SnapshotControlDefinition] = Field(
        default_factory=list, description="Snapshot control definitions"
    )

    reference_tables: list[ReferenceTableDefinition] = Field(
        default_factory=list, description="Reference table definitions"
    )

    pits: list[PITDefinition] = Field(
        default_factory=list, description="PIT structure definitions"
    )
