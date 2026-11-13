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
from typing import Any, Literal


class _Clear:
    """The source sets a value to empty, so the stored one is cleared.

    For fields whose empty value means something (inherit from the source
    system or the project, use datavault4dbt's default), where None already
    means "the format has no place for it, keep what the project has".
    """

    _instance: _Clear | None = None

    def __new__(cls) -> _Clear:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "CLEAR"

    def __deepcopy__(self, memo: dict) -> _Clear:
        return self


CLEAR: Any = _Clear()


@dataclass(slots=True)
class DModelOutput:
    """A stored model output (``engine.models.ModelOutput``) of an entity.

    Its fields are the stored values; None stores nothing. An entity whose
    ``outputs`` is a dict has exactly those outputs (the others are removed),
    keyed by kind; None leaves the entity's outputs alone.
    """

    kind: str
    model_name: str | None = None
    folder: str | None = None
    alias: str | None = None
    schema_name: str | None = None
    database_name: str | None = None
    materialized: str | None = None
    tags: list[str] | None = None
    config: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Source metadata
# ---------------------------------------------------------------------------


# Descriptions are None when the source format has no place for them (Excel,
# SQLite, IRiS). The executor then leaves what the project has untouched, so a
# re-import from such a file doesn't wipe descriptions set in the meantime.


@dataclass(slots=True)
class DSourceColumn:
    name: str
    # None when the format doesn't give it: Excel creates columns from the
    # mappings that name them. The project's type is then kept, e.g. the one
    # a database import collected.
    datatype: str | None = None
    description: str | None = None
    # Whether the column is listed in the stage's missing_columns. None when
    # the format has no place for it: the column keeps its flag.
    is_missing: bool | None = None


@dataclass(slots=True)
class DDerivedColumn:
    """A column the stage computes from the table's columns."""

    name: str
    expression: str
    datatype: str | None = None
    description: str | None = None


@dataclass(slots=True)
class DSourceTable:
    identifier: str  # source-side identifier used to reference this table
    physical_name: str
    # None: the source sets none, so the table keeps what it has (or, when
    # new, inherits from its source system and the project).
    record_source_value: str | None = None
    static_part_of_record_source: str | None = None
    load_date_value: str | None = None
    alias: str | None = None
    description: str | None = None
    # "physical" or "prestage". None when the format has no place for it: the
    # table keeps its type (a new one is physical).
    table_type: str | None = None
    # Stage options and the delivery method. None keeps what the table has;
    # CLEAR inherits from the source system and the project.
    include_source_columns: Any = None
    enable_ghost_records: Any = None
    sequence_column: Any = None
    delivery_method: Any = None
    # The stage's or pre-stage's stored model outputs (see DModelOutput).
    outputs: dict[str, DModelOutput] | None = None
    columns: dict[str, DSourceColumn] = field(default_factory=dict)
    # Keyed by lowercased name. None when the format carries no derived
    # columns, so the table's existing ones are left alone.
    derived_columns: dict[str, DDerivedColumn] | None = None


@dataclass(slots=True)
class DSourceSystem:
    name: str
    schema_name: str
    database_name: str | None = None
    description: str | None = None
    # Values the system's tables inherit; None keeps what the system has.
    record_source_value: str | None = None
    static_part_of_record_source: str | None = None
    load_date_value: str | None = None
    # None keeps what the system has; CLEAR inherits from the project.
    include_source_columns: Any = None
    enable_ghost_records: Any = None
    delivery_method: Any = None
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
    # The stage hash key the mapping loads, when it isn't the hub's own
    # (role-playing business keys). None keeps what the mapping has; CLEAR:
    # the hub's hash key.
    stage_hashkey_name: Any = None


@dataclass(slots=True)
class DHubColumn:
    name: str
    column_type: HubColumnType = "business_key"
    sort_order: int | None = None
    target_column_transformation: str | None = None
    target_column_datatype: str | None = None
    description: str | None = None
    source_mappings: list[DHubSourceMapping] = field(default_factory=list)


@dataclass(slots=True)
class DHub:
    physical_name: str
    hub_type: HubType = "standard"
    hashkey_name: str | None = None
    create_record_tracking_satellite: bool = False
    create_effectivity_satellite: bool = False
    group_name: str | None = None
    description: str | None = None
    # None keeps what the hub has; CLEAR empties a value that may be empty.
    disable_hwm: bool | None = None
    effectivity_is_active_alias: Any = None
    effectivity_disable_hwm: bool | None = None
    effectivity_additional_columns: Any = None
    outputs: dict[str, DModelOutput] | None = None
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
    # When set, `source_column_name` is not a column of the source table but an
    # extraction pulled in by the prejoin from it to this target table. The
    # identifier is already resolved by the parser (same "{system}|{table}" form
    # as `source_table_identifier`). None means an ordinary direct column.
    prejoin_target_table_identifier: str | None = None


@dataclass(slots=True)
class DLinkColumn:
    name: str
    column_type: LinkColumnType = "payload"
    sort_order: int = 0
    target_column_transformation: str | None = None
    target_column_datatype: str | None = None
    description: str | None = None
    source_mappings: list[DLinkSourceMapping] = field(default_factory=list)


@dataclass(slots=True)
class DLinkHubSourceMapping:
    """A mapping for a link's hub-key column."""

    link_hub_ref_index: int  # index into DLink.hub_references
    hub_column_name: str
    source_table_identifier: str
    source_column_name: str
    # See DLinkSourceMapping.prejoin_target_table_identifier. A link's hub
    # business key is the common case for this: the FK on the source table
    # points at a non-key column of the target, so the real business key has to
    # be prejoined across to compute the hub hashkey.
    prejoin_target_table_identifier: str | None = None


@dataclass(slots=True)
class DLink:
    physical_name: str
    link_type: LinkType = "standard"
    hashkey_name: str = ""
    create_record_tracking_satellite: bool = False
    group_name: str | None = None
    description: str | None = None
    # None keeps what the link has; CLEAR empties a value that may be empty.
    create_effectivity_satellite: bool | None = None
    disable_hwm: bool | None = None
    union_strategy: Any = None
    effectivity_is_active_alias: Any = None
    effectivity_disable_hwm: bool | None = None
    effectivity_additional_columns: Any = None
    outputs: dict[str, DModelOutput] | None = None
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
    target_column_transformation: str | None = None
    target_column_datatype: str | None = None
    description: str | None = None
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
    description: str | None = None
    # None keeps what the satellite has; CLEAR empties a value that may be
    # empty (the stored hash diff name, the alias, the v1 view's project
    # default, the v1 end-date alias).
    hashdiff_name: Any = None
    hashdiff_alias: Any = None
    create_v1_view: Any = None
    v1_ledts_alias: Any = None
    v1_add_is_current_flag: bool | None = None
    v1_include_payload: bool | None = None
    disable_hwm: bool | None = None
    outputs: dict[str, DModelOutput] | None = None
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


def snapshot_base_name(name: str) -> str:
    """Base name of a snapshot control: trailing _v0/_v1 stripped, lowercased.

    ``control_snap``, ``control_snap_v0`` and ``Control_Snap_v1`` name one
    control.
    """
    lowered = (name or "").lower()
    for suffix in ("_v0", "_v1"):
        if lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


@dataclass(slots=True)
class DSnapshotControl:
    name: str = "control_snap"
    # ISO values. None keeps what the control has (a new one gets the
    # defaults); CLEAR removes the end date: snapshots run up to today.
    start_date: str | None = None
    end_date: Any = None
    daily_time: str | None = None
    # None keeps what the snapshot control has; CLEAR empties it.
    sdts_alias: Any = None
    outputs: dict[str, DModelOutput] | None = None
    logic_rules: list[DSnapshotControlLogic] = field(default_factory=list)


@dataclass(slots=True)
class DRefSatAssignment:
    satellite_name: str
    include_columns: list[str] = field(default_factory=list)
    exclude_columns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DReferenceTable:
    physical_name: str
    reference_hub_name: str
    historization_type: str = "latest"  # latest | full | snapshot_based
    snapshot_control_name: str | None = None
    snapshot_logic_column: str | None = None
    group_name: str | None = None
    description: str | None = None
    outputs: dict[str, DModelOutput] | None = None
    satellite_assignments: list[DRefSatAssignment] = field(default_factory=list)


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
    # None keeps what the PIT has; CLEAR empties it (datavault4dbt's default).
    use_snapshot_optimization: Any = None
    include_business_objects_before_appearance: bool | None = None
    outputs: dict[str, DModelOutput] | None = None


# ---------------------------------------------------------------------------
# Skipped entities
# ---------------------------------------------------------------------------


SkipReason = Literal[
    "missing_reference",
    "missing_parent",
    "missing_source_table",
    "depends_on_skipped",
    "invalid_configuration",
]


@dataclass(slots=True)
class DSkipped:
    """An entity the source defines but that cannot be imported, and why.

    The resolver leaves it out of the model instead of importing a broken
    version of it; the planner reports it as a skip and never deletes the
    project's copy of it under `replace_all`.
    """

    entity_type: str  # "hub" | "link" | "satellite" | "reference_table" | "pit"
    name: str
    reason: SkipReason


# ---------------------------------------------------------------------------
# Prejoins
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
    # Entities left out because something they need is missing, keyed by
    # (entity_type, physical name).
    skipped: dict[tuple[str, str], DSkipped] = field(default_factory=dict)
    # Whether the source can describe pre-stages (JSON exports that know
    # them). One that can't — Excel, SQLite, IRiS, a database's catalog —
    # never lists them, so `replace_all` must not take that as a deletion.
    describes_prestages: bool = False
    # Settings the source suggests for the project (types.ProjectSettings),
    # reported, not applied
    project_settings: Any = None

    # ---------------- helpers ----------------

    def is_empty(self) -> bool:
        """Whether the model holds no entity at all."""
        return not any(
            (
                self.source_systems,
                self.hubs,
                self.links,
                self.satellites,
                self.snapshot_controls,
                self.reference_tables,
                self.pits,
                self.prejoins,
            )
        )

    def get_source_table(
        self, identifier: str
    ) -> tuple[DSourceSystem, DSourceTable] | None:
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
