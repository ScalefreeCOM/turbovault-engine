---
sidebar_position: 9
sidebar_label: Backend Data Model
title: Backend Data Model
---

# Domain Model

This document describes the **logical domain model** for the TurboVault Engine. It is the blueprint for the Django ORM models and is intended to remain stable so that:

- the **CLI-based Engine** and
- future **front-end applications**

can share the same core data structures.

The focus here is on **entities, fields, relationships, and semantics**, not on exact Django field types or implementation details.

> **See also:** [Architecture Overview](../01_introduction/02_architecture.md) explains how these entities are used by the service and CLI layers at runtime.

---

## 1. Conventions

- **identifier** — Logical primary key type (e.g. `UUID`, `BIGINT`, or similar). In Django this will typically be a `UUIDField` or `BigAutoField`.
- **string** — Text field (e.g. `CharField` / `TextField` depending on length).
- **int** — Integer number.
- **boolean** — True/False.
- **date / time** — Date-only / time-only fields.
- **list[...]** — Represents a multi-value relationship. In relational / Django terms this will be implemented as:

  - a many-to-many relation, or
  - a helper table providing multiple rows (depending on the specific case).
- **FK** (Foreign Key) — References another table’s primary key.

> **Note on Project scoping:**
> Conceptually, **all DV-related entities are scoped to a `Project`**.
> To avoid clutter, `project_id` is not repeated in every table definition below, but in the actual implementation most tables will have a foreign key to `Project`.

---

## 2. Project

### 2.1 `Project`

Represents a full modeling context (e.g. a specific Data Vault implementation or customer/domain).

| Field       | Type       | Required | Description                                               |
| ----------- | ---------- | -------- | --------------------------------------------------------- |
| project_id  | identifier | PK       | Unique identifier for the project.                        |
| name        | string     | ✓       | Human-readable name of the project.                       |
| description | string     |          | Optional longer description of the project.               |
| config      | JSON       |          | Optional JSON for project-level configuration parameters. |
| created_at  | datetime   | ✓       | Timestamp when the project was created.                   |
| updated_at  | datetime   | ✓       | Timestamp when the project was last updated.              |

**Relationships**

- A `Project` is the **parent** for:
  - `source_system`, `source_table`, `source_column`
  - `hub`, `hub_column`, `hub_source_mapping`
  - `link`, `link_column`, `link_source_mapping`, `link_hub_source_mapping`
  - `prejoin_definition`, `prejoin_extraction_column`
  - `satellite`, `satellite_column`
  - `snapshot_control_table`, `snapshot_control_logic`
  - `reference_table`, `reference_table_satellite_assignment`
  - `pit`
  - `GeneratedArtifact` (documented separately in generation docs)

---

## 3. Source Metadata

These tables represent the **upstream source systems** and their physical schemas.

### 3.1 `source_system`

Describes a physical source system (database/schema) and a human-readable name.

| Field            | Type       | Required | Description                                   |
| ---------------- | ---------- | -------- | --------------------------------------------- |
| source_system_id | identifier | PK       | Unique identifier of the source system.       |
| project_id       | identifier | ✓ (FK)  | FK to `Project` (scopes the source system). |
| schema_name      | string     | ✓       | Schema name in the source system.             |
| database_name    | string     |          | Optional database name (if applicable).       |
| name             | string     | ✓       | Human-readable name for this source system.   |
| created_at       | datetime   | ✓       | Timestamp when the record was created.        |
| updated_at       | datetime   | ✓       | Timestamp when the record was last updated.   |

**Relationships**

- A `source_system` **has many** `source_table` records.

---

### 3.2 `source_table`

Represents a physical source table within a source system and includes DV-related config.

| Field                        | Type       | Required | Description                                                         |
| ---------------------------- | ---------- | -------- | ------------------------------------------------------------------- |
| source_table_id              | identifier | PK       | Unique identifier of the source table.                              |
| project_id                   | identifier | ✓ (FK)  | FK to `Project`.                                                  |
| source_system_id             | identifier | ✓ (FK)  | FK to `source_system.source_system_id`.                           |
| physical_table_name          | string     | ✓       | Physical name of the table in the source system (e.g.`CUSTOMER`). |
| alias                        | string     |          | Optional alias used in generated code/dbt models.                   |
| record_source_value          | string     |          | Value/expression used as `record_source` for this table.          |
| static_part_of_record_source | string     |          | Optional static part of `record_source` that is reused.           |
| load_date_value              | string     |          | Expression or column name used as load date value.                  |
| created_at                   | datetime   | ✓       | Timestamp when the record was created.                              |
| updated_at                   | datetime   | ✓       | Timestamp when the record was last updated.                         |

**Relationships**

- `source_table` **belongs to** one `source_system`.
- `source_table` **has many** `source_column`.
- `prejoin_definition` references `source_table` as source and target.

---

### 3.3 `source_column`

Represents a single column in a source table.

| Field                       | Type       | Required | Description                                  |
| --------------------------- | ---------- | -------- | -------------------------------------------- |
| source_column_id            | identifier | PK       | Unique identifier of the source column.      |
| source_table_id             | identifier | ✓ (FK)  | FK to `source_table.source_table_id`.      |
| source_column_physical_name | string     | ✓       | Physical column name in the source table.    |
| source_column_datatype      | string     | ✓       | Logical or physical data type of the column. |
| created_at                  | datetime   | ✓       | Timestamp when the record was created.       |
| updated_at                  | datetime   | ✓       | Timestamp when the record was last updated.  |

**Relationships**

- `source_column` **belongs to** one `source_table`.
- Used in:
  - `hub_source_mapping`
  - `link_source_mapping`
  - `link_hub_source_mapping`
  - `prejoin_definition`
  - `prejoin_extraction_column`
  - `satellite_column`

---

## 4. Hubs & Hub Mappings

These tables define DV hubs and how they map to source data.

### 4.1 `hub`

Defines a Data Vault hub entity.

| Field                            | Type       | Required | Description                                                            |
| -------------------------------- | ---------- | -------- | ---------------------------------------------------------------------- |
| hub_id                           | identifier | PK       | Unique identifier of the hub.                                          |
| project_id                       | identifier | ✓ (FK)  | FK to `Project`.                                                     |
| hub_physical_name                | string     | ✓       | Physical name of the hub (e.g.`hub_customer`).                       |
| hub_type                         | string     | ✓       | `standard` (default) or `reference`.                               |
| hub_hashkey_name                 | string     |          | Name of the hub hashkey column (used only if `hub_type = standard`). |
| create_record_tracking_satellite | boolean    | ✓       | If true, a record-tracking satellite should be generated for this hub. |
| create_effectivity_satellite     | boolean    | ✓       | If true, an effectivity satellite should be generated for this hub.    |
| created_at                       | datetime   | ✓       | Timestamp when the record was created.                                 |
| updated_at                       | datetime   | ✓       | Timestamp when the record was last updated.                            |

**Relationships**

- `hub` **has many** `hub_column`.
- `hub` is referenced by:
  - `link.hub_references` (only standard hubs).
  - `satellite.parent_entity_id` (when parent is a hub).
  - `reference_table.reference_hub_id`.
  - `pit.tracked_entity_id` (when tracking a hub).

---

### 4.2 `hub_column`

Describes columns within a hub.

| Field         | Type       | Required | Description                                                                                |
| ------------- | ---------- | -------- | ------------------------------------------------------------------------------------------ |
| hub_column_id | identifier | PK       | Unique identifier of the hub column.                                                       |
| hub_id        | identifier | ✓ (FK)  | FK to `hub.hub_id`.                                                                      |
| column_name   | string     | ✓       | Logical/target column name in the hub.                                                     |
| column_type   | string     | ✓       | `business_key` (default for standard hubs), `additional_column`, or `reference_key`. |
| sort_order    | int        | ✓       | Sorting index to define ordering of hub columns.                                           |
| created_at    | datetime   | ✓       | Timestamp when the record was created.                                                     |
| updated_at    | datetime   | ✓       | Timestamp when the record was last updated.                                                |

**Relationships**

- `hub_column` **belongs to** a `hub`.
- Used in:
  - `hub_source_mapping.hub_column_id`.
  - `link_hub_source_mapping.standard_hub_column_id`.

---

### 4.3 `hub_source_mapping`

Maps hub columns to source columns.

| Field                 | Type       | Required | Description                                                                             |
| --------------------- | ---------- | -------- | --------------------------------------------------------------------------------------- |
| hub_source_mapping_id | identifier | PK       | Unique identifier of the hub-to-source mapping row.                                     |
| hub_column_id         | identifier | ✓ (FK)  | FK to `hub_column.hub_column_id`.                                                     |
| source_column_id      | identifier | ✓ (FK)  | FK to `source_column.source_column_id`.                                               |
| is_primary_source     | boolean    | ✓       | Indicates if this mapping is the primary source for the hub (only one per hub allowed). |
| created_at            | datetime   | ✓       | Timestamp when the record was created.                                                  |
| updated_at            | datetime   | ✓       | Timestamp when the record was last updated.                                             |

**Relationships**

- `hub_source_mapping` **belongs to**:
  - one `hub_column`,
  - one `source_column`.

---

## 5. Links & Link Mappings

These tables define DV links and how they map to sources/hubs.

### 5.1 `link`

Defines a Data Vault link entity.

| Field              | Type       | Required | Description                                                  |
| ------------------ | ---------- | -------- | ------------------------------------------------------------ |
| link_id            | identifier | PK       | Unique identifier of the link.                               |
| project_id         | identifier | ✓ (FK)  | FK to `Project`.                                           |
| group_id           | identifier | (FK)     | FK to `Group` (optional).                                  |
| link_physical_name | string     | ✓       | Physical name of the link (e.g.`link_customer_order`).     |
| link_hashkey_name  | string     | ✓       | Name of the link hashkey column (e.g.`lk_customer_order`). |
| link_type          | string     | ✓       | `standard` or `non-historized`.                          |
| created_at         | datetime   | ✓       | Timestamp when the record was created.                       |
| updated_at         | datetime   | ✓       | Timestamp when the record was last updated.                  |

**Relationships**

- `link` **has many** `link_hub_references` (defining which hubs it connects).
- `link` **has many** `link_column`, `link_source_mapping`, `link_hub_source_mapping`.
- `link` is referenced by:
  - `satellite.parent_entity_id` (when parent is a link).
  - `pit.tracked_entity_id` (when tracking a link).

---

### 5.2 `link_hub_references`

Defines the hubs referenced by a link. Replaces the list field in `link`.

| Field                     | Type       | Required | Description                                                                      |
| ------------------------- | ---------- | -------- | -------------------------------------------------------------------------------- |
| link_hub_reference_id     | identifier | PK       | Unique identifier for the link-to-hub reference.                                 |
| link_id                   | identifier | ✓ (FK)  | FK to `link.link_id`.                                                          |
| hub_id                    | identifier | ✓ (FK)  | FK to `hub.hub_id`.                                                            |
| hub_hashkey_alias_in_link | string     |          | Alias for the hub hashkey in the link. Default should be the hub's hashkey name. |
| sort_order                | integer    |          | Order of appearance in the link. Lower values appear first.                      |
| created_at                | datetime   | ✓       | Timestamp when the record was created.                                           |
| updated_at                | datetime   | ✓       | Timestamp when the record was last updated.                                      |

**Relationships**

- `link_hub_references` **belongs to** one `link` and one `hub`.
- Used in `link_hub_source_mapping.link_hub_reference_id`.

---

### 5.3 `link_column`

Describes columns in a link (payload or additional).

| Field          | Type       | Required | Description                                                     |
| -------------- | ---------- | -------- | --------------------------------------------------------------- |
| link_column_id | identifier | PK       | Unique identifier of the link column.                           |
| link_id        | identifier | ✓ (FK)  | FK to `link.link_id`.                                         |
| column_name    | string     | ✓       | Logical/target column name in the link.                         |
| column_type    | string     | ✓       | `payload`, `additional_column`, or `dependent_child_key`. |
| sort_order     | integer    |          | Order of appearance. Lower values appear first.                 |
| created_at     | datetime   | ✓       | Timestamp when the record was created.                          |
| updated_at     | datetime   | ✓       | Timestamp when the record was last updated.                     |

**Relationships**

- `link_column` **belongs to** a `link`.
- Used in `link_source_mapping`.

---

### 5.4 `link_source_mapping`

Maps link columns to source columns.

| Field                  | Type       | Required | Description                                  |
| ---------------------- | ---------- | -------- | -------------------------------------------- |
| link_source_mapping_id | identifier | PK       | Unique identifier for a link column mapping. |
| link_column_id         | identifier | ✓ (FK)  | FK to `link_column.link_column_id`.        |
| source_column_id       | identifier | ✓ (FK)  | FK to `source_column.source_column_id`.    |
| created_at             | datetime   | ✓       | Timestamp when the record was created.       |
| updated_at             | datetime   | ✓       | Timestamp when the record was last updated.  |

**Relationships**

- `link_source_mapping` **belongs to**:
  - one `link_column`,
  - one `source_column`.

---

### 5.5 `link_hub_source_mapping`

Defines how link hub keys are derived from source data.

| Field                        | Type       | Required | Description                                                                                                        |
| ---------------------------- | ---------- | -------- | ------------------------------------------------------------------------------------------------------------------ |
| link_hub_source_mapping_id   | identifier | PK       | Unique identifier for a link hub mapping.                                                                          |
| link_hub_reference_id        | identifier | ✓ (FK)  | FK to `link_hub_references.link_hub_reference_id`.                                                               |
| standard_hub_column_id       | identifier | ✓ (FK)  | FK to `hub_column.hub_column_id` (must be a hub column of a standard hub).                                       |
| source_column_id             | identifier |          | FK to `source_column.source_column_id` when mapping directly from a source column.                               |
| prejoin_extraction_column_id | identifier |          | FK to `prejoin_extraction_column.prejoin_extraction_column_id` when mapping from a pre-joined extraction column. |
| created_at                   | datetime   | ✓       | Timestamp when the record was created.                                                                             |
| updated_at                   | datetime   | ✓       | Timestamp when the record was last updated.                                                                        |

> **Constraint:** Either `(source_column_id)` must be set **or** `(prejoin_extraction_column_id)` must be set, but **not both**.
> This expresses “direct from source” vs. “via pre-join extraction”.

**Relationships**

- `link_hub_source_mapping` **belongs to**:
  - one `link_hub_references` (replacing direct link FK),
  - one `hub_column` (as the hub key column),
  - either one `source_column` or one `prejoin_extraction_column`.

---

## 6. Prejoin Definitions

These tables model pre-join logic between source tables, which can be used to derive additional mapping columns.

### 6.1 `prejoin_definition`

Defines a pre-join relationship between two source tables.

| Field                              | Type       | Required | Description                                                               |
| ---------------------------------- | ---------- | -------- | ------------------------------------------------------------------------- |
| prejoin_id                         | identifier | PK       | Unique identifier of the pre-join.                                        |
| project_id                         | identifier | ✓ (FK)  | FK to `Project`.                                                        |
| source_table_id                    | identifier | ✓ (FK)  | Source-side table ID (FK to `source_table.source_table_id`).            |
| prejoin_condition_source_column_id | identifier | ✓ (FK)  | FK to `source_column.source_column_id` for the source-side join column. |
| prejoin_target_table_id            | identifier | ✓ (FK)  | Target-side table ID (FK to `source_table.source_table_id`).            |
| prejoin_condition_target_column_id | identifier | ✓ (FK)  | FK to `source_column.source_column_id` for the target-side join column. |
| prejoin_operator                   | string     | ✓       | Logical operator used to combine conditions, e.g.`AND` or `OR`.       |
| created_at                         | datetime   | ✓       | Timestamp when the record was created.                                    |
| updated_at                         | datetime   | ✓       | Timestamp when the record was last updated.                               |

**Relationships**

- `prejoin_definition` **belongs to** a `Project`.
- References two `source_table` entries (source and target).
- References two `source_column` entries (source and target columns).

---

### 6.2 `prejoin_extraction_column`

Defines which columns are extracted from a pre-joined target table.

| Field                        | Type       | Required | Description                                                                                                     |
| ---------------------------- | ---------- | -------- | --------------------------------------------------------------------------------------------------------------- |
| prejoin_extraction_column_id | identifier | PK       | Unique identifier of the pre-join extraction column.                                                            |
| prejoin_id                   | identifier | ✓ (FK)  | FK to `prejoin_definition.prejoin_id`.                                                                        |
| prejoin_source_column_id     | identifier | ✓ (FK)  | FK to `source_column.source_column_id`; must be a column from `prejoin_definition.prejoin_target_table_id`. |
| prejoin_target_column_alias  | string     |          | optional, will only influence dbt stage column names. Will overwrite physical column name.                     |
| created_at                   | datetime   | ✓       | Timestamp when the record was created.                                                                          |
| updated_at                   | datetime   | ✓       | Timestamp when the record was last updated.                                                                     |

**Relationships**

- `prejoin_extraction_column` **belongs to** a `prejoin_definition`.
- `prejoin_extraction_column` is referenced by `link_hub_source_mapping.prejoin_extraction_column_id`.

---

## 7. Satellites & Satellite Columns

Satellites capture descriptive attributes and additional logic.

### 7.1 `satellite`

Represents a Data Vault satellite attached to either a hub or a link.

| Field                   | Type       | Required | Description                                                                                                                                                           |
| ----------------------- | ---------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| satellite_id            | identifier | PK       | Unique identifier of the satellite.                                                                                                                                   |
| project_id              | identifier | ✓ (FK)  | FK to `Project`.                                                                                                                                                    |
| satellite_physical_name | string     | ✓       | Physical name of the satellite (e.g.`sat_customer_details`).                                                                                                        |
| parent_entity_id        | identifier | ✓       | Identifier of the parent entity (hub or link).                                                                                                                        |
| satellite_type          | string     | ✓       | `standard` (default for standard hub & link), `reference` (default for reference hub), `non-historized` (default for non-historized link), or `multi-active`. |
| created_at              | datetime   | ✓       | Timestamp when the record was created.                                                                                                                                |
| updated_at              | datetime   | ✓       | Timestamp when the record was last updated.                                                                                                                           |

> In implementation, `parent_entity_id` will likely be paired with a `parent_entity_type` field (e.g. `hub` / `link`) or modeled via two separate FKs to `hub` and `link` with constraints.

**Relationships**

- `satellite` is attached to exactly one parent (hub or link).
- `satellite` **has many** `satellite_column`.
- `satellite` is referenced by:
  - `reference_table_satellite_assignment.reference_satellite_id`.
  - `pit.satellite_ids` (list of satellites included in a PIT).

---

### 7.2 `satellite_column`

Maps source columns into a satellite, with extra semantics.

| Field                        | Type       | Required | Description                                                                                                                 |
| ---------------------------- | ---------- | -------- | --------------------------------------------------------------------------------------------------------------------------- |
| satellite_column_id          | identifier | PK       | Unique identifier of the satellite column.                                                                                  |
| satellite_id                 | identifier | ✓ (FK)  | FK to `satellite.satellite_id`.                                                                                           |
| source_column_id             | identifier | ✓ (FK)  | FK to `source_column.source_column_id`.                                                                                   |
| column_sort_order            | int        | ✓       | 1-based position of this column within the satellite. Unique per satellite. Auto-assigned on creation (next available integer). Controls the order of columns in generated hashdiff lists (stage `.sql`) and payload lists (satellite `.sql`/`.yml`). |
| is_multi_active_key          | boolean    | ✓       | Indicates if this column is part of the multi-active key (default:`false`).                                               |
| include_in_delta_detection   | boolean    | ✓       | If `true`, column is included in hashdiff/delta detection; if `false`, it is excluded (default: `true`).              |
| target_column_name           | string     |          | Optional target column name for renaming; default is the physical source column name.                                       |
| target_column_transformation | string     |          | Optional transformation expression used to derive this column (e.g. placeholders, functions, or COALESCE-like expressions). |
| created_at                   | datetime   | ✓       | Timestamp when the record was created.                                                                                      |
| updated_at                   | datetime   | ✓       | Timestamp when the record was last updated.                                                                                 |

> **`column_sort_order` import behaviour:** When importing via SQLite or Excel (sheets `standard_satellite`, `ref_sat`, `non_historized_satellite`, `multiactive_satellite`), the value is read from the column **`Target_Column_Sort_Order`** and stored directly. If the column is absent or blank in the source file the sort order is auto-assigned as the next integer within the satellite.

**Relationships**

- `satellite_column` belongs to one `satellite` and one `source_column`.
- `satellite_column` is referenced by `reference_table_satellite_assignment.include_columns` / `exclude_columns`.

---

## 8. Snapshot & Reference Modeling

These tables define snapshot behavior and reference modeling options.

### 8.1 `snapshot_control_table`

Stores global snapshot configuration.

| Field                     | Type       | Required | Description                                                                                            |
| ------------------------- | ---------- | -------- | ------------------------------------------------------------------------------------------------------ |
| snapshot_control_table_id | identifier | PK       | Unique identifier of the snapshot control table.                                                       |
| project_id                | identifier | ✓ (FK)  | FK to `Project`.                                                                                     |
| snapshot_start_date       | date       | ✓       | Start date of snapshot range (default: beginning of (year of today - 5 years); format `YYYY-MM-DD`). |
| snapshot_end_date         | date       | ✓       | End date of snapshot range (default: end of (year of today + 5 years); format `YYYY-MM-DD`).         |
| daily_snapshot_time       | time       | ✓       | Daily snapshot time (default:`08:00:00`; format `hh:mm:ss`).                                       |
| created_at                | datetime   | ✓       | Timestamp when the record was created.                                                                 |
| updated_at                | datetime   | ✓       | Timestamp when the record was last updated.                                                            |

---

### 8.2 `snapshot_control_logic`

Defines reusable snapshot logic patterns.

| Field                              | Type       | Required | Description                                                                                                                                                                               |
| ---------------------------------- | ---------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| snapshot_control_logic_id          | identifier | PK       | Unique identifier of the snapshot logic entry.                                                                                                                                            |
| snapshot_control_table_id          | identifier | ✓ (FK)  | FK to `snapshot_control_table.snapshot_control_table_id`.                                                                                                                               |
| snapshot_control_logic_column_name | string     | ✓       | Name of the derived/logic column to be produced in the snapshot context.                                                                                                                  |
| snapshot_component                 | string     | ✓       | One of:`daily`, `beginning_of_week`, `end_of_week`, `beginning_of_month`, `end_of_month`, `beginning_of_quarter`, `end_of_quarter`, `beginning_of_year`, `end_of_year`. |
| snapshot_duration                  | int        |          | Duration value for the snapshot window (e.g. 3, 6, 12).                                                                                                                                   |
| snapshot_unit                      | string     |          | Unit for duration:`DAY`, `WEEK`, `MONTH`, `QUARTER`, `YEAR`.                                                                                                                    |
| snapshot_forever                   | boolean    | ✓       | If `true`, `snapshot_duration` and `snapshot_unit` must be `NULL` and snapshot is open-ended.                                                                                     |
| created_at                         | datetime   | ✓       | Timestamp when the record was created.                                                                                                                                                    |
| updated_at                         | datetime   | ✓       | Timestamp when the record was last updated.                                                                                                                                               |

**Relationships**

- `snapshot_control_logic` **belongs to** `snapshot_control_table`.
- Referenced by:
  - `reference_table.snapshot_control_logic_id`
  - `pit.snapshot_control_logic_id`

---

### 8.3 `reference_table`

Represents a reference table based on a reference hub.

| Field                         | Type       | Required | Description                                                                                                        |
| ----------------------------- | ---------- | -------- | ------------------------------------------------------------------------------------------------------------------ |
| reference_table_id            | identifier | PK       | Unique identifier for the reference table.                                                                         |
| project_id                    | identifier | ✓ (FK)  | FK to `Project`.                                                                                                 |
| reference_table_physical_name | string     | ✓       | Physical name of the reference table.                                                                              |
| reference_hub_id              | identifier | ✓ (FK)  | FK to `hub.hub_id`; must refer to a hub with `hub_type = reference`.                                           |
| historization_type            | string     | ✓       | Historization strategy:`latest`, `full`, or `snapshot_based`.                                                |
| snapshot_table_id             | identifier |          | FK to `snapshot_control_table.snapshot_control_table_id` when `historization_type` requires snapshot handling. |
| snapshot_control_logic_id     | identifier |          | FK to `snapshot_control_logic.snapshot_control_logic_id` when snapshot-based logic is used.                      |
| created_at                    | datetime   | ✓       | Timestamp when the record was created.                                                                             |
| updated_at                    | datetime   | ✓       | Timestamp when the record was last updated.                                                                        |

**Relationships**

- `reference_table` references:
  - one `reference` hub,
  - optionally a `snapshot_control_table`,
  - optionally a `snapshot_control_logic`.
- `reference_table` **has many** `reference_table_satellite_assignment`.

---

### 8.4 `reference_table_satellite_assignment`

Assigns reference satellites to a reference table and controls column inclusion/exclusion.

| Field                                   | Type       | Required | Description                                                                        |
| --------------------------------------- | ---------- | -------- | ---------------------------------------------------------------------------------- |
| reference_table_satellite_assignment_id | identifier | PK       | Unique identifier for the satellite assignment.                                    |
| reference_table_id                      | identifier | ✓ (FK)  | FK to `reference_table.reference_table_id`.                                      |
| reference_satellite_id                  | identifier | ✓ (FK)  | FK to `satellite.satellite_id`; must refer to a satellite of type `reference`. |
| include_columns                         | list[id]   |          | Optional list of `satellite_column.satellite_column_id` to explicitly include.   |
| exclude_columns                         | list[id]   |          | Optional list of `satellite_column.satellite_column_id` to explicitly exclude.   |
| created_at                              | datetime   | ✓       | Timestamp when the record was created.                                             |
| updated_at                              | datetime   | ✓       | Timestamp when the record was last updated.                                        |

> **Rule of thumb:** If `include_columns` is non-empty, only those columns are included.
> If `include_columns` is empty and `exclude_columns` is set, all except the excluded ones are included.

**Relationships**

- `reference_table_satellite_assignment` **belongs to**:
  - one `reference_table`,
  - one `satellite` (of type `reference`).
- Uses many `satellite_column` entries via `include_columns` / `exclude_columns`.

---

## 9. PIT (Point-in-Time) Structures

### 9.1 `pit`

Defines Point-in-Time structures over satellites for a tracked hub or link.

| Field                                      | Type       | Required | Description                                                                                        |
| ------------------------------------------ | ---------- | -------- | -------------------------------------------------------------------------------------------------- |
| pit_id                                     | identifier | PK       | Unique identifier of the PIT definition.                                                           |
| project_id                                 | identifier | ✓ (FK)  | FK to `Project`.                                                                                 |
| pit_physical_name                          | string     | ✓       | Physical name of the PIT structure.                                                                |
| tracked_entity_id                          | identifier | ✓       | Identifier of the tracked entity (hub or link).                                                    |
| snapshot_table_id                          | identifier |          | FK to `snapshot_control_table.snapshot_control_table_id`.                                        |
| snapshot_control_logic_id                  | identifier |          | FK to `snapshot_control_logic.snapshot_control_logic_id`.                                        |
| dimension_key_column_name                  | string     |          | Optional name of the dimension key column generated in the PIT.                                    |
| pit_type                                   | string     |          | Optional PIT type (implementation-specific classification).                                        |
| custom_record_source                       | string     |          | Optional custom record source value for the PIT.                                                   |
| use_snapshot_optimization                  | boolean    | ✓       | If `true`, snapshot optimization techniques are applied (default: `true`).                     |
| include_business_objects_before_appearance | boolean    | ✓       | If `true`, includes business keys before their first appearance in the PIT (default: `false`). |
| satellite_ids                              | list[id]   | ✓       | List of `satellite.satellite_id` entries included in the PIT structure.                          |
| created_at                                 | datetime   | ✓       | Timestamp when the record was created.                                                             |
| updated_at                                 | datetime   | ✓       | Timestamp when the record was last updated.                                                        |

> As with `satellite.parent_entity_id`, `tracked_entity_id` will be implemented with additional type information or separate FKs to `hub` / `link`.

**Relationships**

- `pit` references:
  - a tracked hub or link,
  - optional `snapshot_control_table`,
  - optional `snapshot_control_logic`,
  - many `satellite` entries via `satellite_ids`.

---

This domain model specification is the reference for implementing the Django models in the TurboVault Engine.
Any structural changes (new tables, renamed fields, changed semantics) should be reflected here first and then applied consistently in the code.
