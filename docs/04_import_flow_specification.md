# Import Flow Specification

This document maps the Domain Model to the Import Flow logic.

## 1. Project

| Column          | Import Logic        |
| :-------------- | :------------------ |
| `project_id`  | Auto-generated UUID |
| `description` | Based on file name  |
| `config`      | Empty JSON          |
| `created_at`  | Current timestamp   |
| `updated_at`  | Current timestamp   |

> **Note:** This object is created by the import flow. One Excel file = one Project.

## 2. Source System

| Column               | Import Logic                                                  |
| :------------------- | :------------------------------------------------------------ |
| `source_system_id` | Auto-generated UUID                                           |
| `project_id`       | Use `project_id` from Project                               |
| `schema_name`      | Table `source_data`, column `source_schema_physical_name` |
| `database_name`    | Empty (does not exist in old metadata)                        |
| `name`             | Table `source_data`, column `source_system`               |
| `created_at`       | Current timestamp                                             |
| `updated_at`       | Current timestamp                                             |

## 3. Source Table

| Column                           | Import Logic                                                               |
| :------------------------------- | :------------------------------------------------------------------------- |
| `source_table_id`              | Auto-generated UUID                                                        |
| `project_id`                   | Use `project_id` from Project                                            |
| `source_system_id`             | Join `source_data` on `source_system` name to get `source_system_id` |
| `physical_table_name`          | Table `source_data`, column `source_table_physical_name`               |
| `alias`                        | Empty                                                                      |
| `record_source_value`          | Table `source_data`, column `Record_source_column`                     |
| `static_part_of_record_source` | Table `source_data`, column `static_part_of_record_source_column`      |
| `load_date_value`              | Table `source_data`, column `load_date_column`                         |
| `created_at`                   | Current timestamp                                                          |
| `updated_at`                   | Current timestamp                                                          |

## 4. Source Column

| Column                          | Import Logic                                                                                                                                                                                                                      |
| :------------------------------ | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `source_column_id`            | Auto-generated UUID                                                                                                                                                                                                               |
| `source_table_id`             | Join `source_table` on `physical_table_name` to get `source_table_id`                                                                                                                                                       |
| `source_column_physical_name` | Scan multiple tables (`standard_hub`, `standard_link`, `standard_satellite`, etc.) for `source_column_physical_name` (or similar columns like `prejoin_extraction_column_name`). Create distinct list per source table. |
| `source_column_datatype`      | Empty (no info in old metadata)                                                                                                                                                                                                   |
| `created_at`                  | Current timestamp                                                                                                                                                                                                                 |
| `updated_at`                  | Current timestamp                                                                                                                                                                                                                 |

## 5. Hub

**Scope:** Standard Hubs & Reference Hubs

| Hub Type            | Column                               | Import Logic                                                        |
| :------------------ | :----------------------------------- | :------------------------------------------------------------------ |
| **Standard**  | `hub_id`                           | Auto-generated UUID                                                 |
|                     | `project_id`                       | Use `project_id` from Project                                     |
|                     | `hub_physical_name`                | Table `standard_hub`, column `target_hub_table_physical_name`   |
|                     | `hub_type`                         | `'standard'`                                                      |
|                     | `hub_hashkey_name`                 | Table `standard_hub`, column `target_primary_key_physical_name` |
|                     | `create_record_tracking_satellite` | Table `standard_hub`, column `record_tracking_satellite`        |
|                     | `create_effectivity_satellite`     | `False`                                                           |
|                     | `created_at` / `updated_at`      | Current timestamp                                                   |
| **Reference** | `hub_id`                           | Auto-generated UUID                                                 |
|                     | `project_id`                       | Use `project_id` from Project                                     |
|                     | `hub_physical_name`                | Table `ref_hub`, column `target_reference_table_physical_name`  |
|                     | `hub_type`                         | `'reference'`                                                     |
|                     | `hub_hashkey_name`                 | Empty                                                               |
|                     | `create_record_tracking_satellite` | `False`                                                           |
|                     | `create_effectivity_satellite`     | `False`                                                           |
|                     | `created_at` / `updated_at`      | Current timestamp                                                   |

## 6. Hub Column

**Scope:** Standard Hubs & Reference Hubs

| Hub Type            | Column                          | Import Logic                                                                   |
| :------------------ | :------------------------------ | :----------------------------------------------------------------------------- |
| **Standard**  | `hub_column_id`               | Auto-generated UUID                                                            |
|                     | `hub_id`                      | Use `hub_id` from Hub                                                        |
|                     | `column_name`                 | `business_key_physical_name` (if empty, use `source_column_physical_name`) |
|                     | `column_type`                 | `'business_key'`                                                             |
|                     | `sort_order`                  | Natural order from input file (1-based increment per hub)                      |
|                     | `created_at` / `updated_at` | Current timestamp                                                              |
| **Reference** | `hub_column_id`               | Auto-generated UUID                                                            |
|                     | `hub_id`                      | Use `hub_id` from Hub                                                        |
|                     | `column_name`                 | Table `ref_hub`, column `source_column_physical_name`                      |
|                     | `column_type`                 | `'reference_key'`                                                            |
|                     | `sort_order`                  | Natural order from input file (1-based increment per hub)                      |
|                     | `created_at` / `updated_at` | Current timestamp                                                              |

## 7. Hub Source Mapping

| Hub Type            | Column                          | Import Logic                                              |
| :------------------ | :------------------------------ | :-------------------------------------------------------- |
| **Standard**  | `hub_source_mapping_id`       | Auto-generated UUID                                       |
|                     | `hub_column_id`               | Use `hub_column_id` from Hub Column                     |
|                     | `source_column_id`            | Join `source_column` on `source_column_physical_name` |
|                     | `is_primary_source`           | Table `standard_hub`, column `is_primary_source`      |
|                     | `created_at` / `updated_at` | Current timestamp                                         |
| **Reference** | `hub_source_mapping_id`       | Auto-generated UUID                                       |
|                     | `hub_column_id`               | Use `hub_column_id` from Hub Column                     |
|                     | `source_column_id`            | Join `source_column` on `source_column_physical_name` |
|                     | `is_primary_source`           | `True`                                                  |
|                     | `created_at` / `updated_at` | Current timestamp                                         |

## 8. Link

**Scope:** Standard Links & Non-Historized Links

| Link Type                | Column                          | Import Logic                                                                                                                                   |
| :----------------------- | :------------------------------ | :--------------------------------------------------------------------------------------------------------------------------------------------- |
| **Standard**       | `link_id`                     | Auto-generated UUID                                                                                                                            |
|                          | `project_id`                  | Use `project_id` from Project                                                                                                                |
|                          | `link_physical_name`          | Table `standard_link`, column `target_link_table_physical_name`                                                                            |
|                          | `link_hashkey_name`           | Table `standard_link` , distinct value or first value if there are multiple values, of the column `Target_Primary_Key_Physical_Name`       |
|                          | `link_type`                   | `'standard'`                                                                                                                                 |
|                          | `created_at` / `updated_at` | Current timestamp                                                                                                                              |
| **Non-Historized** | `link_id`                     | Auto-generated UUID                                                                                                                            |
|                          | `project_id`                  | Use `project_id` from Project                                                                                                                |
|                          | `link_physical_name`          | Table `non_historized_link`, column `target_link_table_physical_name`                                                                      |
|                          | `link_hashkey_name`           | Table `non_historized_link` , distinct value or first value if there are multiple values, of the column `Target_Primary_Key_Physical_Name` |
|                          | `link_type`                   | `'non_historized'`                                                                                                                           |
|                          | `created_at` / `updated_at` | Current timestamp                                                                                                                              |

## 9. Link Hub References

| Link Type      | Column                          | Import Logic                                                                                                                                                                                                                                                                                                                                                                                                                             |
| -------------- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Standard       | link_hub_reference_id           | Auto-generated UUID                                                                                                                                                                                                                                                                                                                                                                                                                      |
|                | link_id                         | Use `link_id` from Link                                                                                                                                                                                                                                                                                                                                                                                                                |
|                | hub_id                          | Get `hub_id` from a Hub, based on column `hub_identifier` inside table `standard_link` and looking that up in the table `standard_hub` to get the new django `hub_id` . <br /><br />If one link has the same `hub_identifier` multiple times, check if this Hub has multiple Business Keys inside `standard_hub`. If yes, treat these multiple references as just one. If not, create multiple link hub references.      |
|                | hub_hashkey_alias_in_link       | Table `standard_link` column `Target_column_physical_name`, but only if it is different than the value inside column `Hub_primary_key_physical_name`. Otherwise, keep empty.                                                                                                                                                                                                                                                      |
|                | sort_order                      | Table `standard_link` column `Target_Column_Sort_Order`                                                                                                                                                                                                                                                                                                                                                                              |
|                | `created_at` / `updated_at` | Current timestamp                                                                                                                                                                                                                                                                                                                                                                                                                        |
| Non-Historized | link_hub_reference_id           | Auto-generated UUID                                                                                                                                                                                                                                                                                                                                                                                                                      |
|                | link_id                         | Use `link_id` from Link                                                                                                                                                                                                                                                                                                                                                                                                                |
|                | hub_id                          | Get `hub_id` from a Hub, based on column `hub_identifier` inside table `non_historized_link` and looking that up in the table `standard_hub` to get the new django `hub_id` . <br /><br />If one link has the same `hub_identifier` multiple times, check if this Hub has multiple Business Keys inside `standard_hub`. If yes, treat these multiple references as just one. If not, create multiple link hub references. |
|                | hub_hashkey_alias_in_link       | Table `non_historized_link` column `Target_column_physical_name`, but only if it is different than the value inside column `Hub_primary_key_physical_name`. Otherwise, keep empty.                                                                                                                                                                                                                                                 |
|                | sort_order                      | Table `non_historized_link` column `Target_Column_Sort_Order`                                                                                                                                                                                                                                                                                                                                                                        |
|                | `created_at` / `updated_at` | Current timestamp                                                                                                                                                                                                                                                                                                                                                                                                                        |


## 9. Link Column


| Link Type      | Column                          | Import Logic                                                                                                                                                                                               |
| -------------- | :------------------------------ | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Non Historized | `link_column_id`              | Auto-generated UUID                                                                                                                                                                                        |
|                | `link_id`                     | Use `link_id` from Link                                                                                                                                                                                  |
|                | `column_name`                 | Logic:`COALESCE(Target_column_physical_name, Prejoin_Target_Column_Alias, Prejoin_Extraction_Column_Name, source_column_physical_name)` from `non_historized_link` (where `hub_identifier` is empty) |
|                | `column_type`                 | `'payload'` if column `Target_Primary_Key_Physical_Name` in `non_historized_link` is empty, if it is populated, ``dependent_child_key``                                                             |
|                | `sort_order`                  | Natural order from input file (1-based increment per link)                                                                                                                                                 |
|                | `created_at` / `updated_at` | Current timestamp                                                                                                                                                                                          |
| Standard       | `link_column_id`              | Auto-generated UUID                                                                                                                                                                                        |
|                | `link_id`                     | Use `link_id` from Link                                                                                                                                                                                  |
|                | `column_name`                 | Logic:`COALESCE(Target_column_physical_name, Prejoin_Target_Column_Alias, Prejoin_Extraction_Column_Name, source_column_physical_name)` from `standard_link` (where `hub_identifier` is empty)       |
|                | `column_type`                 | `dependent_child_key`  if column `Target_Primary_Key_Physical_Name `in `standard_link` is not empty.                                                                                                |

In general, link columns should only be populated for input rows, where column `hub_identifier` is empty (within `standard_link` and/or `non_historized_link` )

## 10. Link Source Mapping

| Column                          | Import Logic                                                                                                |
| :------------------------------ | :---------------------------------------------------------------------------------------------------------- |
| `link_source_mapping_id`      | Auto-generated UUID                                                                                         |
| `link_column_id`              | Use `link_column_id` from Link Column                                                                     |
| `source_column_id`            | Join `source_column` on `source_column_physical_name` from `non_historized_link` or `standard_link` |
| `created_at` / `updated_at` | Current timestamp                                                                                           |

## 11. Link Hub Source Mapping

**Scope:** Standard Links & Non-Historized Links

| Link Type                | Column                           | Import Logic                                                                                                 |
| :----------------------- | :------------------------------- | :----------------------------------------------------------------------------------------------------------- |
| **Standard**       | `link_hub_source_mapping_id`   | Auto-generated UUID                                                                                          |
|                          | `link_hub_reference_id`        | Use `link_hub_reference_id` for the Link Hub Reference created                                             |
|                          | `standard_hub_column_id`       | Find Hub Column via `hub_identifier` and `target_column_sort_order`                                      |
|                          | `source_column_id`             | Join `source_column` on `source_column_physical_name` (ONLY if `prejoin_target_column_alias` is empty) |
|                          | `prejoin_extraction_column_id` | Use `prejoin_extraction_column_id` based on `prejoin_extraction_column_name`                             |
|                          | `created_at` / `updated_at`  | Current timestamp                                                                                            |
| **Non-Historized** | `link_hub_source_mapping_id`   | Auto-generated UUID                                                                                          |
|                          | `link_hub_reference_id`        | Use `link_hub_reference_id` for the Link Hub Reference created                                             |
|                          | `standard_hub_column_id`       | Find Hub Column via `hub_identifier` and `target_column_sort_order`                                      |
|                          | `source_column_id`             | Join `source_column` on `source_column_physical_name` (ONLY if `prejoin_target_column_alias` is empty) |
|                          | `prejoin_extraction_column_id` | Use `prejoin_extraction_column_id` if `prejoin_extraction_column_name` is not empty                      |
|                          | `created_at` / `updated_at`  | Current timestamp                                                                                            |

## 12. Prejoin Definition

| Type                     | Column                                 | Import Logic                                                                                           |
| :----------------------- | :------------------------------------- | :----------------------------------------------------------------------------------------------------- |
| **Standard**       | `prejoin_id`                         | Auto-generated UUID                                                                                    |
|                          | `project_id`                         | Use `project_id` from Project                                                                        |
|                          | `source_table_id`                    | Join `source_table` via `source_table_identifier`                                                  |
|                          | `prejoin_condition_source_column_id` | Join `source_column` via `source_column_physical_name` (if `prejoin_table_identifier` not empty) |
|                          | `prejoin_target_table_id`            | Join `source_table` via `prejoin_table_identifier`                                                 |
|                          | `prejoin_condition_target_column_id` | Join `source_column` via `prejoin_table_column_name` (if `prejoin_table_identifier` not empty)   |
|                          | `prejoin_operator`                   | `'AND'` (Default)                                                                                    |
|                          | `created_at` / `updated_at`        | Current timestamp                                                                                      |
| **Non-Historized** |                                        | Same logic using `non_historized_link` table                                                         |

## 13. Prejoin Extraction Column

| Type                     | Column                           | Import Logic                                                  |
| :----------------------- | :------------------------------- | :------------------------------------------------------------ |
| **Standard**       | `prejoin_extraction_column_id` | Auto-generated UUID                                           |
|                          | `prejoin_id`                   | Use `prejoin_id` from Prejoin Definition                    |
|                          | `prejoin_source_column_id`     | Join `source_column` via `prejoin_extraction_column_name` |
|                          | `created_at` / `updated_at`  | Current timestamp                                             |
| **Non-Historized** |                                  | Same logic using `non_historized_link` table                |

## 14. Satellite

| Sat Type                 | Column                          | Import Logic                                                                          |
| :----------------------- | :------------------------------ | :------------------------------------------------------------------------------------ |
| **Standard**       | `satellite_id`                | Auto-generated UUID                                                                   |
|                          | `project_id`                  | Use `project_id` from Project                                                       |
|                          | `satellite_physical_name`     | `standard_satellite.target_satellite_table_physical_name`                           |
|                          | `parent_entity_id`            | Find Hub/Link via `parent_identifier`                                               |
|                          | `satellite_type`              | `'standard'`                                                                        |
|                          | `created_at` / `updated_at` | Current timestamp                                                                     |
| **Reference**      | `satellite_id`                | Auto-generated UUID                                                                   |
|                          | `project_id`                  | Use `project_id` from Project                                                       |
|                          | `satellite_physical_name`     | `ref_sat.Target_Reference_table_physical_name`                                      |
|                          | `parent_entity_id`            | Find Hub via `parent_identifier`                                                    |
|                          | `satellite_type`              | `'reference'`                                                                       |
|                          | `created_at` / `updated_at` | Current timestamp                                                                     |
| **Non-Historized** | `satellite_id`                | Auto-generated UUID                                                                   |
|                          | `project_id`                  | Use `project_id` from Project                                                       |
|                          | `satellite_physical_name`     | `non_historized_satellite.target_satellite_table_physical_name`                     |
|                          | `parent_entity_id`            | Find Hub/Link via `non_historized_link.nh_link_identifier` or `parent_identifier` |
|                          | `satellite_type`              | `'non_historized'`                                                                  |
|                          | `created_at` / `updated_at` | Current timestamp                                                                     |
| **Multi-Active**   | `satellite_id`                | Auto-generated UUID                                                                   |
|                          | `project_id`                  | Use `project_id` from Project                                                       |
|                          | `satellite_physical_name`     | `multiactive_satellite.target_satellite_table_physical_name`                        |
|                          | `parent_entity_id`            | Find Hub/Link via `parent_identifier`                                               |
|                          | `satellite_type`              | `'multi_active'`                                                                    |
|                          | `created_at` / `updated_at` | Current timestamp                                                                     |

## 15. Satellite Column

| Sat Type                 | Column                         | Import Logic                                                                                                  |
| :----------------------- | :----------------------------- | :------------------------------------------------------------------------------------------------------------ |
| **Standard**       | `satellite_column_id`        | Auto-generated UUID                                                                                           |
|                          | `satellite_id`               | Use `satellite_id` from Satellite                                                                           |
|                          | `source_column_id`           | Join `source_column` via `source_column_physical_name`                                                    |
|                          | `is_multi_active_key`        | `False`                                                                                                     |
|                          | `include_in_delta_detection` | `True`                                                                                                      |
|                          | `target_column_name`         | `target_column_physical_name` (or `source_column_physical_name`)                                          |
| **Multi-Active**   | `source_column_id`           | Use `source_column_physical_name`. NOTE: Split `Multi_Active_Attributes` by `;` and create new columns. |
|                          | `is_multi_active_key`        | `True` for multi-active key, `False` for others                                                           |
|                          | `include_in_delta_detection` | `False` for multi-active key, `True` for others                                                           |
|                          | `target_column_name`         | Use `target_column_physical_name` or split attribute name                                                   |
| **Non-Historized** | `is_multi_active_key`        | `False`                                                                                                     |
|                          | `include_in_delta_detection` | `False`                                                                                                     |
| **Reference**      | `is_multi_active_key`        | `False`                                                                                                     |
|                          | `include_in_delta_detection` | `True`                                                                                                      |

## 16. Snapshot Control Table

| Column                          | Import Logic                      |
| :------------------------------ | :-------------------------------- |
| `snapshot_control_table_id`   | Auto-generated UUID               |
| `project_id`                  | Use `project_id` from Project   |
| `snapshot_start_date`         | `YYYY-01-01` (Current Year - 5) |
| `snapshot_end_date`           | `YYYY-12-31` (Current Year + 5) |
| `daily_snapshot_time`         | `08:00:00`                      |
| `created_at` / `updated_at` | Current timestamp                 |

## 17. Snapshot Control Logic

| Column                                 | Import Logic                                 |
| :------------------------------------- | :------------------------------------------- |
| `snapshot_control_logic_id`          | Auto-generated UUID                          |
| `snapshot_control_table_id`          | Use `snapshot_control_table_id` from above |
| `snapshot_control_logic_column_name` | `'is_active'`                              |
| `snapshot_component`                 | `'beginning_of_monthl'`                    |
| `snapshot_duration`                  | `1`                                        |
| `snapshot_unit`                      | `'YEAR'`                                   |
| `snapshot_forever`                   | `False`                                    |
| `created_at` / `updated_at`        | Current timestamp                            |

## 18. Reference Table

| Column                            | Import Logic                                       |
| :-------------------------------- | :------------------------------------------------- |
| `reference_table_id`            | Auto-generated UUID                                |
| `project_id`                    | Use `project_id` from Project                    |
| `reference_table_physical_name` | `ref_table.target_Reference_table_physical_name` |
| `reference_hub_id`              | Find Hub via `referenced_hub`                    |
| `historization_type`            | `ref_table.historized`                           |
| `snapshot_table_id`             | Use default `snapshot_control_table_id`          |
| `snapshot_control_logic_id`     | Use default `snapshot_control_logic_id`          |
| `created_at` / `updated_at`   | Current timestamp                                  |

## 19. Reference Table Satellite Assignment

| Column                                      | Import Logic                                                         |
| :------------------------------------------ | :------------------------------------------------------------------- |
| `reference_table_satellite_assignment_id` | Auto-generated UUID                                                  |
| `reference_table_id`                      | Use `reference_table_id` from Reference Table                      |
| `reference_satellite_id`                  | Find Satellite via `referenced_satellite`                          |
| `include_columns`                         | List of `satellite_column_id` (from `ref_table.include_columns`) |
| `exclude_columns`                         | List of `satellite_column_id` (from `ref_table.exclude_columns`) |
| `created_at` / `updated_at`             | Current timestamp                                                    |

## 20. PIT

| Column                                         | Import Logic                                                                                                                                     |
| :--------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------- |
| `pit_id`                                     | Auto-generated UUID                                                                                                                              |
| `project_id`                                 | Use `project_id` from Project                                                                                                                  |
| `pit_physical_name`                          | `pit.pit_physical_table_name`                                                                                                                  |
| `tracked_entity_id`                          | Find Hub or Link sorted by `tracked_entity` (check Hub name first, then Link name)                                                             |
| `snapshot_table_id`                          | Use default `snapshot_control_table_id`                                                                                                        |
| `snapshot_control_logic_id`                  | Use default `snapshot_control_logic_id`                                                                                                        |
| `dimension_key_column_name`                  | `pit.dimension_key_name`                                                                                                                       |
| `pit_type`                                   | `pit.pit_type`                                                                                                                                 |
| `custom_record_source`                       | `pit.custom_record_source`                                                                                                                     |
| `use_snapshot_optimization`                  | `True`                                                                                                                                         |
| `include_business_objects_before_appearance` | `False`                                                                                                                                        |
| `satellite_ids`                              | List of `satellite_id` (split `pit.satellite_identifiers` by `,` and find matches in Standard, Multi-Active, or Non-Historized Satellites) |
| `created_at` / `updated_at`                | Current timestamp                                                                                                                                |
