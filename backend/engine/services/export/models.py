"""
Intermediate Pydantic models for Data Vault export.

These models provide a target-agnostic representation of the Data Vault
that can be serialized to various output formats (JSON, dbt, DBML, etc.).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# Source Layer Models
# =============================================================================


class SourceColumnDef(BaseModel):
    """Definition of a source column."""

    column_name: str
    datatype: str


class SourceTableDef(BaseModel):
    """Definition of a source table with its columns and metadata."""

    table_name: str
    alias: Optional[str] = None
    record_source: Optional[str] = None
    load_date: Optional[str] = None
    columns: list[SourceColumnDef] = Field(default_factory=list)


class SourceSystemDef(BaseModel):
    """Definition of a source system containing multiple tables."""

    name: str
    schema_name: str
    database_name: Optional[str] = None
    tables: list[SourceTableDef] = Field(default_factory=list)


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


class HubSourceInfo(BaseModel):
    """Information about a source table feeding a hub."""

    source_table: str
    source_system: str
    stage_name: str = Field(description="Stage model name for this source table")
    business_key_columns: list[str] = Field(
        default_factory=list, description="Source columns mapped to business keys"
    )


class HubDefinition(BaseModel):
    """
    Definition of a Data Vault hub.

    Contains all metadata needed to generate hub-related artifacts.
    """

    hub_name: str
    hub_type: str  # "standard" or "reference"
    group: Optional[str] = None
    hashkey: Optional[HashkeyDefinition] = None
    business_key_columns: list[str] = Field(
        default_factory=list, description="Target hub column names for business keys"
    )
    additional_columns: list[str] = Field(
        default_factory=list, description="Additional non-key columns in the hub"
    )
    source_tables: list[HubSourceInfo] = Field(
        default_factory=list, description="Source tables that feed this hub"
    )
    create_record_tracking_satellite: bool = False
    create_effectivity_satellite: bool = True


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


class PrejoinDefinitionExport(BaseModel):
    """Prejoin definition exported to stage."""

    target_table: str = Field(description="Target table physical name to join")
    join_conditions: PrejoinCondition = Field(
        description="Join conditions between source and target"
    )
    extraction_columns: list[str] = Field(
        default_factory=list, description="Columns extracted from target table"
    )


class LinkColumnMapping(BaseModel):
    """Mapping of link column to source column."""

    link_column_name: str
    link_column_type: str  # business_key, payload, or additional_column
    source_column_name: str


class LinkSourceInfo(BaseModel):
    """Information about source tables feeding a link."""

    source_table: str
    source_system: str
    stage_name: str = Field(description="Stage model name for this source table")
    columns: list[LinkColumnMapping] = Field(
        default_factory=list, description="Mapped columns from this source table"
    )


class LinkDefinition(BaseModel):
    """
    Definition of a Data Vault link.

    Contains all metadata needed to generate link-related artifacts.
    """

    link_name: str
    link_type: str  # "standard" or "non_historized"
    group: Optional[str] = None
    hashkey: HashkeyDefinition = Field(description="Link hashkey definition")
    hub_references: list[str] = Field(
        default_factory=list, description="Names of hubs connected by this link"
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


# =============================================================================
# Stage Layer Models
# =============================================================================


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
    record_source: Optional[str] = None
    load_date: Optional[str] = None

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
    multi_active_config: Optional[MultiActiveConfig] = Field(
        None,
        description="Multi-active key config if a multi-active satellite uses this source",
    )

    # Source columns
    columns: list[SourceColumnDef] = Field(
        default_factory=list, description="Source columns available in this stage"
    )

    # Future additions
    # prejoins: list[PrejoinDef] = Field(default_factory=list)
    # derived_columns: list[DerivedColumnDef] = Field(default_factory=list)


# =============================================================================
# Satellite Layer Models
# =============================================================================


class SatelliteColumnDef(BaseModel):
    """Definition of a satellite column."""

    source_column: str = Field(description="Source column physical name")
    target_column_name: Optional[str] = Field(
        None, description="Target column name (if renamed from source)"
    )
    is_multi_active_key: bool = Field(
        default=False, description="Whether this column is part of multi-active key"
    )
    include_in_delta_detection: bool = Field(
        default=True, description="Whether to include in hashdiff calculation"
    )
    target_column_transformation: Optional[str] = Field(
        None, description="Optional transformation expression"
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
    group: Optional[str] = None
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
    hashdiff_name: str = Field(description="Hashdiff column name for this satellite")
    columns: list[SatelliteColumnDef] = Field(
        default_factory=list, description="Satellite columns"
    )
    # Future: hashdiff definition


# =============================================================================
# Project Export (Root Model)
# =============================================================================


# ============================================================================
# REFERENCE TABLE MODELS
# ============================================================================


class ReferenceTableSatelliteAssignment(BaseModel):
    """Satellite assignment for a reference table."""

    satellite_name: str = Field(description="Name of the reference satellite")
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
    reference_hub_name: str = Field(
        description="Name of the reference hub this table is based on"
    )
    historization_type: str = Field(
        description="Historization strategy: latest, full, or snapshot_based"
    )
    snapshot_control_table: Optional[str] = Field(
        None, description="Snapshot control table name (if snapshot_based)"
    )
    snapshot_logic_column: Optional[str] = Field(
        None, description="Snapshot logic column name (if snapshot_based)"
    )
    satellites: list[ReferenceTableSatelliteAssignment] = Field(
        default_factory=list, description="Reference satellite assignments"
    )


class PITDefinition(BaseModel):
    """Point-in-Time structure definition."""

    pit_name: str = Field(description="Physical name of the PIT structure")
    tracked_entity_type: str = Field(description="Type of tracked entity: hub or link")
    tracked_entity_name: str = Field(description="Name of the tracked hub or link")
    tracked_hashkey: str = Field(description="Hashkey name of the tracked hub or link")
    satellites: list[str] = Field(
        default_factory=list, description="List of satellite names included in the PIT"
    )
    snapshot_control_name: str = Field(
        description="Name of the snapshot control table (v1)"
    )
    snapshot_logic_column: str = Field(description="Snapshot logic column name")
    dimension_key_column: Optional[str] = Field(
        None, description="Optional dimension key column name"
    )
    pit_type: Optional[str] = Field(
        None, description="Optional PIT type classification"
    )
    use_snapshot_optimization: bool = Field(
        default=True, description="Whether snapshot optimization is enabled"
    )
    include_business_objects_before_appearance: bool = Field(
        default=False,
        description="Whether to include business keys before first appearance",
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
    duration: Optional[int] = Field(None, description="Duration value (e.g., 1, 7, 30)")
    unit: Optional[str] = Field(
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
        description="Base name of the snapshot control (e.g., 'control_snap')"
    )
    start_date: str = Field(description="Overall snapshot start date (YYYY-MM-DD)")
    end_date: str = Field(description="Overall snapshot end date (YYYY-MM-DD)")
    daily_time: str = Field(description="Daily snapshot execution time (HH:MM:SS)")
    logic_patterns: list[SnapshotLogicPattern] = Field(
        default_factory=list, description="List of snapshot logic patterns"
    )

    @property
    def v0_name(self) -> str:
        """
        Model name for the snapshot control table (_v0 suffix).

        Used for the base snapshot control model that contains
        start_date, end_date, and daily_time configuration.
        """
        base_name = self.name.removesuffix("_v0").removesuffix("_v1")
        return f"{base_name}_v0"

    @property
    def v1_name(self) -> str:
        """
        Model name for the snapshot control logic (_v1 suffix).

        Used for the model that implements the logic patterns
        (daily, weekly, monthly, etc. snapshot windows).
        """
        base_name = self.name.removesuffix("_v0").removesuffix("_v1")
        return f"{base_name}_v1"


# ============================================================================
# PROJECT EXPORT MODEL
# ============================================================================


class ProjectExport(BaseModel):
    """
    Complete export of a Data Vault project.

    Contains all definitions needed to generate target artifacts.
    """

    project_name: str
    project_description: Optional[str] = None
    generated_at: datetime = Field(default_factory=datetime.now)

    # Configuration
    stage_schema: Optional[str] = None
    rdv_schema: Optional[str] = None

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
