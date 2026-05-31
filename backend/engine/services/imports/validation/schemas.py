"""
Sheet schema declarations for tabular sources.

Each entry says what columns are required (must be present in the header)
and what extra columns are recognized (everything else is reported as
`schema.unknown_column`, controlled by ImportOptions.allow_unknown_columns).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SheetSchema:
    name: str
    required_columns: tuple[str, ...] = ()
    optional_columns: tuple[str, ...] = ()
    description: str = ""

    @property
    def known_columns(self) -> set[str]:
        return set(self.required_columns) | set(self.optional_columns)


# ---------------------------------------------------------------------------
# Sheet definitions
# ---------------------------------------------------------------------------


SOURCE_DATA = SheetSchema(
    name="source_data",
    required_columns=(
        "source_system",
        "source_schema_physical_name",
        "source_table_physical_name",
        "source_table_identifier",
    ),
    optional_columns=(
        "source_database_name",
        "record_source_column",
        "static_part_of_record_source_column",
        "load_date_column",
        "alias",
    ),
    description="Source systems, schemas, and tables.",
)

STANDARD_HUB = SheetSchema(
    name="standard_hub",
    required_columns=(
        "target_hub_table_physical_name",
        "source_table_identifier",
        "source_column_physical_name",
    ),
    optional_columns=(
        "hub_identifier",
        "target_primary_key_physical_name",
        "business_key_physical_name",
        "record_tracking_satellite",
        "group_name",
        "is_primary_source",
        "target_column_sort_order",
    ),
    description="Standard hubs and their business keys.",
)

REF_HUB = SheetSchema(
    name="ref_hub",
    required_columns=(
        "target_reference_table_physical_name",
        "source_table_identifier",
        "source_column_physical_name",
    ),
    optional_columns=(
        "reference_hub_identifier",
        "group_name",
        "target_column_sort_order",
    ),
    description="Reference hubs (table-of-values style).",
)

STANDARD_LINK = SheetSchema(
    name="standard_link",
    required_columns=(
        "target_link_table_physical_name",
        "source_table_identifier",
        "source_column_physical_name",
    ),
    optional_columns=(
        "link_identifier",
        "hub_identifier",
        "target_primary_key_physical_name",
        "target_column_physical_name",
        "target_column_sort_order",
        "group_name",
        "prejoin_table_identifier",
        "prejoin_table_column_name",
        "prejoin_extraction_column_name",
        "prejoin_target_column_alias",
    ),
    description="Standard links and their hub references.",
)

NON_HISTORIZED_LINK = SheetSchema(
    name="non_historized_link",
    required_columns=(
        "target_link_table_physical_name",
        "source_table_identifier",
        "source_column_physical_name",
    ),
    optional_columns=(
        "nh_link_identifier",
        "hub_identifier",
        "target_primary_key_physical_name",
        "target_column_physical_name",
        "target_column_sort_order",
        "group_name",
        "prejoin_table_identifier",
        "prejoin_table_column_name",
        "prejoin_extraction_column_name",
        "prejoin_target_column_alias",
    ),
    description="Non-historized links.",
)

STANDARD_SATELLITE = SheetSchema(
    name="standard_satellite",
    required_columns=(
        "target_satellite_table_physical_name",
        "parent_identifier",
        "source_table_identifier",
        "source_column_physical_name",
    ),
    optional_columns=(
        "satellite_identifier",
        "target_column_physical_name",
        "target_column_sort_order",
        "group_name",
        # Older / alternate parent-column names accepted by the resolver:
        "parent_table_identifier",
        "nh_link_identifier",
        "referenced_hub",
        "parent_hub",
    ),
    description="Standard satellites attached to hubs or links.",
)

NON_HISTORIZED_SATELLITE = SheetSchema(
    name="non_historized_satellite",
    required_columns=(
        "target_satellite_table_physical_name",
        "parent_identifier",
        "source_table_identifier",
        "source_column_physical_name",
    ),
    optional_columns=(
        "satellite_identifier",
        "target_column_physical_name",
        "target_column_sort_order",
        "group_name",
        "parent_table_identifier",
        "nh_link_identifier",
        "referenced_hub",
        "parent_hub",
    ),
    description="Non-historized satellites.",
)

MULTIACTIVE_SATELLITE = SheetSchema(
    name="multiactive_satellite",
    required_columns=(
        "target_satellite_table_physical_name",
        "parent_identifier",
        "source_table_identifier",
        "source_column_physical_name",
        "multi_active_attributes",
    ),
    optional_columns=(
        "ma_satellite_identifier",
        "target_column_physical_name",
        "target_column_sort_order",
        "group_name",
        "parent_table_identifier",
        "nh_link_identifier",
        "referenced_hub",
        "parent_hub",
    ),
    description="Multi-active satellites.",
)

REF_SAT = SheetSchema(
    name="ref_sat",
    required_columns=(
        "target_reference_table_physical_name",
        "source_table_identifier",
        "source_column_physical_name",
    ),
    optional_columns=(
        "reference_satellite_identifier",
        "target_column_physical_name",
        "target_column_sort_order",
        "group_name",
        # ref_sat uses `parent_table_identifier` (e.g. RH0001) to reference
        # the parent reference hub. Other parent aliases are accepted for
        # backward compatibility with older templates.
        "parent_table_identifier",
        "parent_identifier",
        "referenced_hub",
        "parent_hub",
    ),
    description="Reference satellites attached to reference hubs.",
)

REF_TABLE = SheetSchema(
    name="ref_table",
    required_columns=(
        "target_reference_table_physical_name",
        "referenced_hub",
    ),
    optional_columns=(
        "referenced_satellite",
        "historized",
        "group_name",
        "included_columns",
        "excluded_columns",
    ),
    description="Reference table definitions.",
)

PIT_SHEET = SheetSchema(
    name="pit",
    required_columns=(
        "pit_physical_table_name",
        "tracked_entity",
        "satellite_identifiers",
    ),
    optional_columns=(
        "dimension_key_name",
        "pit_type",
        "custom_record_source",
        "group_name",
    ),
    description="Point-in-time structures.",
)


# Ordered tuple: parsers / validators iterate this for consistent diagnostics.
SHEET_SCHEMAS: tuple[SheetSchema, ...] = (
    SOURCE_DATA,
    STANDARD_HUB,
    REF_HUB,
    STANDARD_LINK,
    NON_HISTORIZED_LINK,
    STANDARD_SATELLITE,
    NON_HISTORIZED_SATELLITE,
    MULTIACTIVE_SATELLITE,
    REF_SAT,
    REF_TABLE,
    PIT_SHEET,
)


SCHEMA_BY_NAME: dict[str, SheetSchema] = {s.name: s for s in SHEET_SCHEMAS}
