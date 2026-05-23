"""
Resolved domain model — the parser/validator output the planner consumes.

This is a Pythonic, source-format-agnostic representation of the metadata
the user wants in the project. It is not yet committed to the database;
the planner diffs it against the current ORM state and the executor
applies the resulting plan.

Why a separate layer (rather than feeding raw IR straight to the planner)?
  - Excel/SQLite imports require non-trivial cross-sheet resolution
    (links span multiple rows; satellites group rows by parent; pre-joins
    are recovered from link rows). That logic doesn't belong in the planner.
  - JSON imports already arrive as a structured ProjectExport and can be
    converted to this model directly, bypassing the IR layer.
  - The planner can then be format-agnostic: it only knows how to diff
    DomainModel against the ORM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Source metadata
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DSourceColumn:
    name: str
    datatype: str = ""


@dataclass(slots=True)
class DSourceTable:
    identifier: str  # source-side identifier used to reference this table
    physical_name: str
    record_source_value: str = ""
    static_part_of_record_source: str = ""
    load_date_value: str = "sysdate()"
    alias: str = ""
    columns: dict[str, DSourceColumn] = field(default_factory=dict)


@dataclass(slots=True)
class DSourceSystem:
    name: str
    schema_name: str
    database_name: str | None = None
    tables: dict[str, DSourceTable] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Hubs
# ---------------------------------------------------------------------------


HubType = Literal["standard", "reference"]
HubColumnType = Literal["business_key", "reference_key", "additional_column"]


@dataclass(slots=True)
class DHubSourceMapping:
    """A mapping from a hub column to a (table_identifier, column_name) source."""

    source_table_identifier: str
    source_column_name: str
    is_primary_source: bool = False


@dataclass(slots=True)
class DHubColumn:
    name: str
    column_type: HubColumnType = "business_key"
    sort_order: int | None = None
    source_mappings: list[DHubSourceMapping] = field(default_factory=list)


@dataclass(slots=True)
class DHub:
    physical_name: str
    hub_type: HubType = "standard"
    hashkey_name: str | None = None
    create_record_tracking_satellite: bool = False
    create_effectivity_satellite: bool = False
    group_name: str | None = None
    columns: list[DHubColumn] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


LinkType = Literal["standard", "non_historized"]
LinkColumnType = Literal["payload", "additional_column", "dependent_child_key"]


@dataclass(slots=True)
class DLinkHubReference:
    """A hub referenced from a link."""

    hub_physical_name: str
    hub_hashkey_alias_in_link: str = ""
    sort_order: int = 0


@dataclass(slots=True)
class DLinkSourceMapping:
    """A mapping from a link payload column to a source column."""

    source_table_identifier: str
    source_column_name: str


@dataclass(slots=True)
class DLinkColumn:
    name: str
    column_type: LinkColumnType = "payload"
    sort_order: int = 0
    source_mappings: list[DLinkSourceMapping] = field(default_factory=list)


@dataclass(slots=True)
class DLinkHubSourceMapping:
    """A mapping for a link's hub-key column."""

    link_hub_ref_index: int  # index into DLink.hub_references
    hub_column_name: str
    source_table_identifier: str
    source_column_name: str


@dataclass(slots=True)
class DLink:
    physical_name: str
    link_type: LinkType = "standard"
    hashkey_name: str = ""
    group_name: str | None = None
    hub_references: list[DLinkHubReference] = field(default_factory=list)
    columns: list[DLinkColumn] = field(default_factory=list)
    hub_source_mappings: list[DLinkHubSourceMapping] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Satellites
# ---------------------------------------------------------------------------


SatelliteType = Literal["standard", "reference", "non_historized", "multi_active"]


@dataclass(slots=True)
class DSatelliteColumn:
    source_column_name: str
    target_column_name: str | None = None
    is_multi_active_key: bool = False
    include_in_delta_detection: bool = True
    sort_order: int | None = None


@dataclass(slots=True)
class DSatellite:
    physical_name: str
    satellite_type: SatelliteType = "standard"
    parent_entity_name: str = ""  # hub or link physical name
    parent_entity_type: Literal["hub", "link"] = "hub"
    source_table_identifier: str = ""
    group_name: str | None = None
    columns: list[DSatelliteColumn] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Snapshot controls, reference tables, PITs
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DSnapshotControlLogic:
    column_name: str
    component: str  # SnapshotComponent value
    duration: int | None = None
    unit: str | None = None
    forever: bool = False


@dataclass(slots=True)
class DSnapshotControl:
    name: str = "control_snap"
    start_date: str | None = None  # ISO date
    end_date: str | None = None
    daily_time: str | None = None  # ISO time
    logic_rules: list[DSnapshotControlLogic] = field(default_factory=list)


@dataclass(slots=True)
class DReferenceTable:
    physical_name: str
    reference_hub_name: str
    historization_type: str = "latest"  # latest | full | snapshot_based
    snapshot_control_name: str | None = None
    snapshot_logic_column: str | None = None
    referenced_satellite_name: str | None = None
    group_name: str | None = None
    include_columns: list[str] = field(default_factory=list)
    exclude_columns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DPIT:
    physical_name: str
    tracked_entity_name: str
    tracked_entity_type: Literal["hub", "link"] = "hub"
    satellite_names: list[str] = field(default_factory=list)
    snapshot_control_name: str | None = None
    snapshot_logic_column: str | None = None
    dimension_key_column_name: str | None = None
    pit_type: str | None = None
    custom_record_source: str | None = None
    group_name: str | None = None


# ---------------------------------------------------------------------------
# Prejoins (simplified — full prejoin support is a follow-up)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DPrejoinExtractionColumn:
    source_column_name: str  # column in the target table being extracted
    alias: str | None = None


@dataclass(slots=True)
class DPrejoin:
    source_table_identifier: str
    target_table_identifier: str
    operator: str = "AND"
    source_join_columns: list[str] = field(default_factory=list)
    target_join_columns: list[str] = field(default_factory=list)
    extraction_columns: list[DPrejoinExtractionColumn] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level resolved model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DomainModel:
    """The full set of metadata to be applied to a project."""

    source_systems: dict[str, DSourceSystem] = field(default_factory=dict)
    groups: set[str] = field(default_factory=set)
    hubs: dict[str, DHub] = field(default_factory=dict)
    links: dict[str, DLink] = field(default_factory=dict)
    satellites: dict[str, DSatellite] = field(default_factory=dict)
    snapshot_controls: dict[str, DSnapshotControl] = field(default_factory=dict)
    reference_tables: dict[str, DReferenceTable] = field(default_factory=dict)
    pits: dict[str, DPIT] = field(default_factory=dict)
    prejoins: list[DPrejoin] = field(default_factory=list)

    # ---------------- helpers ----------------

    def get_source_table(self, identifier: str) -> tuple[DSourceSystem, DSourceTable] | None:
        """Find a source table by its identifier across all systems."""
        for system in self.source_systems.values():
            table = system.tables.get(identifier)
            if table:
                return system, table
        return None

    def get_source_column(
        self, table_identifier: str, column_name: str
    ) -> DSourceColumn | None:
        result = self.get_source_table(table_identifier)
        if not result:
            return None
        _, table = result
        return table.columns.get(column_name.lower())
