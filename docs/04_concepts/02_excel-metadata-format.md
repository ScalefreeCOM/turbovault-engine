---
sidebar_position: 10
sidebar_label: Excel Metadata Format
title: Excel Metadata Format
---

# Excel Metadata Format

TurboVault Engine can import your Data Vault model definition from an **Excel spreadsheet**. This page describes the required sheet names, their column structure, and how they map to the domain model.

> **See also:** [Domain Model](01_domain-model.md) for full entity definitions. A ready-to-use example file (`TurboVault_TPCH_Data.xlsx`) is included in the repository root.

---

## Overview

The Excel file acts as a **flat metadata input** that TurboVault transforms into a relational domain model. Each sheet represents one entity type. Not all sheets are required — TurboVault will skip any sheet that is absent.

**Supported sheets:**

| Sheet Name | What it defines |
|------------|----------------|
| `source_data` | Source systems and source tables |
| `standard_hub` | Standard Data Vault hubs and their business keys |
| `ref_hub` | Reference hubs |
| `standard_link` | Standard links (including prejoins) |
| `non_historized_link` | Non-historized links (including prejoins) |
| `standard_satellite` | Standard satellites and their columns |
| `ref_sat` | Reference satellites |
| `non_historized_satellite` | Non-historized satellites |
| `multiactive_satellite` | Multi-active satellites |
| `ref_table` | Reference table definitions |
| `pit` | Point-in-Time structure definitions |

---

## Sheet Definitions

### `source_data`

Defines source systems and source tables. Each row is one source table.

| Column | Required | Description |
|--------|----------|-------------|
| `source_system` | ✓ | Human-readable name of the source system |
| `source_schema_physical_name` | ✓ | Database schema name |
| `source_table_physical_name` | ✓ | Physical source table name |
| `source_table_identifier` | ✓ | Unique ID used to reference this table in other sheets |
| `record_source_column` | | The record source value for this table (e.g. `ERP`) |
| `static_part_of_record_source_column` | | Static prefix for record source |
| `load_date_column` | | Load date expression (default: `sysdate()`) |

---

### `standard_hub`

Defines standard hubs and maps their business keys to source columns. Each row is one business key mapping.

| Column | Required | Description |
|--------|----------|-------------|
| `target_hub_table_physical_name` | ✓ | Physical name of the hub (e.g. `hub_customer`) |
| `target_primary_key_physical_name` | | Hashkey column name (e.g. `hk_customer`) |
| `hub_identifier` | | Unique ID for referencing this hub in other sheets |
| `business_key_physical_name` | | Target business key column in the hub |
| `source_table_identifier` | ✓ | Reference to a row in `source_data` |
| `source_column_physical_name` | ✓ | Source column providing the business key value |
| `is_primary_source` | | `TRUE` / `FALSE` — marks this as the primary source mapping |
| `record_tracking_satellite` | | `TRUE` to auto-generate a record-tracking satellite |

---

### `ref_hub`

Defines reference hubs. Structure is similar to `standard_hub` but uses reference-specific column names.

| Column | Required | Description |
|--------|----------|-------------|
| `target_reference_table_physical_name` | ✓ | Physical name of the reference hub |
| `reference_hub_identifier` | | Unique ID for referencing this hub in other sheets |
| `source_table_identifier` | ✓ | Reference to a row in `source_data` |
| `source_column_physical_name` | ✓ | Source column providing the reference key |

---

### `standard_link` and `non_historized_link`

Defines links between hubs. Multiple rows per link — rows with a `hub_identifier` define hub key references; rows without define payload columns. Prejoins are also defined in this sheet.

| Column | Required | Description |
|--------|----------|-------------|
| `target_link_table_physical_name` | ✓ | Physical name of the link (carry-forward applied automatically) |
| `target_primary_key_physical_name` | | Link hashkey column name (e.g. `lk_customer_order`) |
| `link_identifier` / `nh_link_identifier` | | Unique ID for the link |
| `hub_identifier` | | Fill for hub-key rows; leave empty for payload rows |
| `target_column_physical_name` | | Target column name in the link (alias or payload name) |
| `target_column_sort_order` | | Sort order for business key columns within a hub reference |
| `source_table_identifier` | ✓ | Source table providing data for this row |
| `source_column_physical_name` | ✓ | Source column for this row |
| `prejoin_table_identifier` | | Source table ID of the pre-joined (target) table |
| `prejoin_table_column_name` | | Join condition column in the pre-joined table |
| `prejoin_extraction_column_name` | | Column to extract from the pre-joined table |
| `prejoin_target_column_alias` | | Optional alias for the extracted prejoin column |

---

### `standard_satellite`, `non_historized_satellite`, `multiactive_satellite`

Defines satellites and maps source columns to satellite columns. Each row is one column mapping.

| Column | Required | Description |
|--------|----------|-------------|
| `target_satellite_table_physical_name` | ✓ | Physical satellite name (carry-forward applied) |
| `satellite_identifier` / `ma_satellite_identifier` | | Unique ID for this satellite |
| `parent_identifier` / `parent_table_identifier` | ✓ | Hub or Link identifier this satellite belongs to |
| `source_table_identifier` | ✓ | Source table for this satellite |
| `source_column_physical_name` | ✓ | Source column name |
| `target_column_physical_name` | | Optional: target column name (rename) |
| `multi_active_attributes` | MA only | Semicolon-separated list of multi-active key column names |

---

### `ref_sat`

Defines reference satellites. Structure is the same as `standard_satellite` but uses:
- `target_reference_table_physical_name` instead of `target_satellite_table_physical_name`
- `reference_satellite_identifier` instead of `satellite_identifier`
- `referenced_hub` as the parent reference

---

### `ref_table`

Defines reference table structures (built on top of reference hubs and their satellites).

| Column | Required | Description |
|--------|----------|-------------|
| `target_reference_table_physical_name` | ✓ | Physical reference table name |
| `referenced_hub` | ✓ | Hub identifier of the linked reference hub |
| `referenced_satellite` | | Satellite identifier to include in the reference table |

---

### `pit`

Defines Point-in-Time structures.

| Column | Required | Description |
|--------|----------|-------------|
| `pit_physical_table_name` | ✓ | Physical PIT table name |
| `tracked_entity` | ✓ | Hub or Link identifier to track |
| `satellite_identifiers` | ✓ | Comma-separated list of satellite identifiers to include |

---

## General Rules

- **Carry-forward**: For multi-row entities (links, satellites), only the first row needs the entity name — subsequent rows for the same entity can leave it blank and it will be inherited from the row above.
- **Identifiers**: The `*_identifier` columns are internal cross-reference keys. They must be unique within the file but are not persisted — they are used only during import to wire entities together.
- **Case sensitivity**: Column names are matched case-sensitively. Use exactly the column names listed above.
- **Extra columns**: Any columns not listed above are silently ignored.
- **Missing sheets**: Missing sheets are skipped without error.

---

## Download a Template

The repository includes a complete working example:

- **`TurboVault_TPCH_Data.xlsx`** — a fully populated example using the TPC-H dataset.

Use this as a starting point for your own metadata file. See the [Step-by-Step Example](../02_getting-started/03_step-by-step-example.md) for a walkthrough using this file.
