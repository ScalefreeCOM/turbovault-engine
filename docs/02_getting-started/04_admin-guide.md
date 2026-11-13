---
sidebar_position: 5
sidebar_label: Django Admin Guide
title: Django Admin Guide
---

# Django Admin Guide

The Django Admin is TurboVault Engine's built-in web interface for managing your Data Vault model after it has been imported. Use it to inspect, add, edit, or delete any entity — and to manage SQL/YAML generation templates.

> **See also:** [CLI Reference](01_cli-reference.md) for how to launch the admin and all other available commands.

---

## Launching the Admin

```bash
turbovault serve
```

This starts a local web server. Access it at:

- **Django Admin**: `http://127.0.0.1:8000/admin/`

Log in with the admin username and password you set during `turbovault workspace init`.

**Custom port or host:**

```bash
turbovault serve --port 9000 --host 0.0.0.0
```

---

## Admin Sections Overview

The admin is organized into the following sections:

| Section | What's managed |
|---------|----------------|
| **Engine > Projects** | Top-level project containers |
| **Engine > Groups** | Logical groupings for organizing entities into subfolders |
| **Engine > Source Systems** | Database/schema definitions of upstream sources |
| **Engine > Source Tables** | Source tables with DV config (record source, load date): physical tables, and pre-stages with their dbt SQL |
| **Engine > Source Columns** | Columns belonging to source tables |
| **Engine > Hubs** | Data Vault hub definitions (standard and reference) |
| **Engine > Hub Columns** | Business keys and reference keys within hubs |
| **Engine > Links** | Data Vault link definitions (standard and non-historized) |
| **Engine > Link Columns** | Payload columns within links |
| **Engine > Satellites** | Satellite definitions (all types) |
| **Engine > Satellite Columns** | Column mappings within satellites |
| **Engine > Reference Tables** | Reference table definitions |
| **Engine > PITs** | Point-in-Time structure definitions |
| **Engine > Snapshot Control Tables** | Snapshot date range and time configuration |
| **Engine > Snapshot Control Logic** | Snapshot frequency patterns |
| **Engine > Model Templates** | SQL and YAML generation templates |

---

## Recommended Entity Creation Order

When building a Data Vault model manually in the admin (rather than importing from Excel), follow this sequence — each entity depends on the ones above it:

```
1. Project
2. Source System
3. Source Table
4. Source Column (auto-created on import, or add manually)
5. Hubs (with Hub Columns)
6. Links (with Hub References → Hub Source Mappings)
7. Satellites (with Satellite Columns)
8. Reference Tables (optional)
9. PITs (optional)
10. Snapshot Control Tables + Logic (optional)
```

---

## Working with Pre-stages

When a table's data can't be loaded as it is (JSON to parse, a table to pivot),
add a [pre-stage](../04_concepts/01_domain-model.md#35-pre-stages): a source
table with **Table type** `Pre-stage`, in the source system whose data it
prepares.

- **Pre-stage SQL** — the complete dbt model, written to
  `models/01_prestaging/<system>/pstg__<system>__<table>.sql` as it is. Read
  inputs with `{{ source('<system>', '<TABLE>') }}`, using the names in the
  generated `sources.yml`. Leave it empty to maintain the model yourself.
- **Source columns** — add the columns the model returns, with their data
  types. Hubs, links and satellites map them like any table's columns.
- **Load date / record source** — as for any table; the load date usually is a
  column the model passes through.

The pre-stage's stage reads the model with `ref()`. A table that only
pre-stages read gets no stage of its own.

---

## Working with Hubs

Navigate to **Engine > Hubs** to see all hubs for all projects.

**Key fields:**
- `hub_physical_name` — the SQL table name (e.g. `hub_customer`)
- `hub_type` — `standard` or `reference`
- `hub_hashkey_name` — the hashkey column name (e.g. `hk_customer`)
- `create_record_tracking_satellite` / `create_effectivity_satellite` — toggles

**Hub Columns** are managed inline on the Hub detail page, or separately under **Engine > Hub Columns**. Each hub column has a type:
- `business_key` — the primary business key(s)
- `additional_column` — extra payload in the hub
- `reference_key` — used for reference hubs

**Hub Source Mappings** link hub columns to the source (staging) columns they are populated from. One mapping per hub should be marked `is_primary_source = True`.

---

## Working with Links

Navigate to **Engine > Links** to see all links.

**Key fields:**
- `link_physical_name` — e.g. `link_customer_order`
- `link_hashkey_name` — e.g. `lk_customer_order`
- `link_type` — `standard` or `non-historized`

**Hub References** are managed inline on the Link detail page — add one row per hub the link connects (minimum 2). Each hub reference can have optional alias and sort order.

**Hub Source Mappings** for the link are managed on the **LinkHubReference** detail page (click "change" on a hub reference row). These define which source/staging column maps to each hub key.

---

## Working with Satellites

Navigate to **Engine > Satellites**.

**Key fields:**
- `satellite_physical_name` — e.g. `sat_customer_details`
- `satellite_type` — `standard`, `reference`, `non_historized`, or `multi_active`
- `parent_hub` / `parent_link` — exactly one must be set
- `source_table` — the single source table driving this satellite

**Satellite Columns** are managed inline. Each column maps a source/staging column to the satellite:
- `target_column_name` — optional rename in the output
- `is_multi_active_key` — mark as part of multi-active key (for MA satellites)
- `include_in_delta_detection` — include in hashdiff calculation (default: True)

> **Tip:** The inline satellite column editor filters staging columns to only those from the satellite's assigned source table. Make sure to set `source_table` on the satellite before adding columns.

---

## Managing Templates

All generation templates can be customized, for dbt and for SQLMesh:

1. Navigate to **Engine > Model Templates**
2. Find the template you want to customize, e.g. `hub_standard (SQL)` (dbt) or `hub_standard (Python)` (SQLMesh). Use the **Framework** filter in the sidebar to list only one framework's templates.
3. Click to edit
4. Modify the Jinja2 template body in the **Model Template** section. The **YAML Template** section is only used for dbt.

Each template has a **framework** (`dbt` or `sqlmesh`), shown and editable on the template's page, and only applies to that framework's output. A dbt template never changes a SQLMesh project and vice versa. Within a framework, the active template with the **highest** `priority` value is selected. Without one, the bundled default file is used.

| Framework | Bundled defaults | Model file |
|---|---|---|
| dbt | `templates/dbt/sql/<entity>.sql.j2`, `templates/dbt/yaml/<entity>.yml.j2` | SQL + YAML |
| SQLMesh | `templates/sqlmesh/models/<entity>.py.j2` (`stage`, `hub_standard`, `link_standard`, `satellite_standard`, `satellite_v1`) | Python calling datavault4sqlmesh |

SQLMesh templates write Python, so values go through the `py` filters (`[[ name | py ]]`, `py_dict`, `py_hashed_columns`, `py_source_models(stage_schema)`), which render correct Python literals. Each bundled SQLMesh template starts with a comment listing the variables it receives. Templates use the engine's delimiters `[[ ]]`, `[% %]` and `[# #]`.

### Model names, references and config (dbt)

Models can have their own name, file path and config, from the naming patterns
or from stored [output attributes](../04_concepts/01_domain-model.md#output-attributes).
A custom dbt template must use the variables below rather than build names
itself (e.g. `[[ satellite_name ]]_v0`), or its output refers to models that
don't exist.

Every dbt model template (SQL and YAML) receives:

| Variable | Content |
|---|---|
| `model_name` | The model's name, which is also its file name. |
| `materialization` | Materialization for `config()`; empty when `dbt_project.yml` sets it. |
| `model_alias` | Relation name for `config(alias=...)`, or empty. |
| `model_schema` | Schema for `config(schema=...)`, or empty. Set to the layer's schema when the model sits outside its layer's folder. |
| `model_database` | Database for `config(database=...)`, or empty. |
| `model_tags` | Stored tags, replacing the default ones in `config()` and the YAML, or `none`. |
| `model_custom_config` | Further `config()` settings from the stored `custom_config_json`, as a mapping of key to value (empty when none). Write each as `[[ key ]]=[[ value \| config_literal ]],`; the `config_literal` filter turns a value into a literal dbt reads back unchanged. The bundled `pit` template leaves out its `clean_up_pit` post-hook when this holds a `post_hook`. |

The `prestage` YAML template writes the same variables into its `config:` block (custom values with the `yaml_json` filter), since a pre-stage's SQL is written as it is.

References to other models, by template:

| Template | Variable | Refers to |
|---|---|---|
| `satellite_v1` | `v0_name`, `v1_name` | The satellite's v0 model, and the v1 view itself. |
| `pit` | `satellite_v0_names` | The v0 models of the PIT's satellites (`satellites` holds base names). |
| `reference_table` | `satellites[].v1_name` | The v1 view of each assigned satellite. |
| `snapshot_control_v0` / `_v1` | `v0_name`, `v1_name` | The two snapshot control models. |

Stage names (`source_tables[].stage_name`, `stage_name`), a PIT's
`tracked_entity_name` and `snapshot_control_name`, and a reference table's
`reference_hub_name` already hold the resolved model names.

Templates stored in the database before these variables existed are updated
automatically by the `0020_refresh_bundled_templates` migration, unless they
were edited. An edited template has to be updated by hand: compare it with the
bundled file, or reset it with `populate_templates --overwrite` (below), which
discards the edits.

**To reset templates to defaults:**

```bash
# From the workspace root
cd backend
python manage.py populate_templates --overwrite
```

---

## Tips

- **Filtering by project**: Most list views have a "Project" filter in the right sidebar — use it to focus on a single project.
- **Search**: The search bar on each list view searches the most relevant fields (e.g. physical name, hashkey name).
- **Inline editing**: Hubs, Links, and Satellites all support editing their child records (columns, mappings) inline on the detail page, saving navigation steps.
- **Read-only fields**: Primary key fields (e.g. `hub_id`) and timestamps (`created_at`, `updated_at`) are read-only and displayed for reference only.
- **Staging columns**: Staging columns are auto-created from source columns and **cannot** be created or modified manually in the admin — they are managed by the import process.
