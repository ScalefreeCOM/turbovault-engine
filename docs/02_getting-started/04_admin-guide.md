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
| **Engine > Source Tables** | Physical source tables with DV config (record source, load date) |
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

All SQL and YAML generation templates can be customized:

1. Navigate to **Engine > Model Templates**
2. Find the template you want to customize (e.g. `hub_sql`, `satellite_yaml`)
3. Click to edit
4. Modify the Jinja2 template body

Higher-priority templates (lower `priority` value) are selected first. You can create multiple templates for the same entity type with different priorities and conditions.

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
