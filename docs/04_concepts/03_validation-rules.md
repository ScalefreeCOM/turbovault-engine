---
sidebar_position: 11
sidebar_label: Validation Rules
title: Validation Rules
---

# Validation Rules

TurboVault Engine validates your Data Vault model at **two different stages**:

1. **Import time** — when a metadata source (Excel, SQLite, JSON) is imported into a project, the [Import Pipeline](06_import-pipeline.md) runs schema, row-level, and cross-entity checks. Problems show up as structured `Issue` objects with stable codes like `schema.missing_column` and `entity.missing_parent` and exact source-file locations.
2. **Generation time** — when you run `turbovault generate`, the [Generation Pipeline](07_generation-pipeline.md) runs the model-level invariants documented on this page. Problems become `Issue` objects with stable codes like `validate.hub.missing_hashkey` and an entity-scoped location.

If your error code starts with `schema.`, `row.`, `source.`, or `entity.`, it came from the import pipeline — see [Import Pipeline → Issue codes](06_import-pipeline.md#issue-codes).

If your error code starts with `validate.`, it came from the generation pipeline — see [Generation Pipeline → Issue code taxonomy](07_generation-pipeline.md#issue-code-taxonomy) for the dot-separated codes. The legacy alphanumeric codes (`HUB_001`, `LNK_002`, …) listed below are still emitted in `Issue.location.field` for backwards-compatible dashboards — read on for what each one means and how to fix it.

> **See also:** [CLI Reference — turbovault generate](../02_getting-started/01_cli-reference.md#turbovault-generate) for the `--mode strict` / `--mode lenient` / `--skip-validation` flags, and [Generation Pipeline](07_generation-pipeline.md) for the surrounding pipeline behaviour.

---

## Running Validation

Validation runs automatically as part of `turbovault generate`. You can control its behavior with the `--mode` flag:

```bash
# Default: stop on first error
turbovault generate --project my_project --mode strict

# Skip invalid entities and continue with valid ones
turbovault generate --project my_project --mode lenient

# Skip validation entirely (not recommended for production)
turbovault generate --project my_project --skip-validation
```

---

## Validation Error Codes

### Hub Rules

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `HUB_001` | Standard Hub | Must have a hashkey name set | Set `hub_hashkey_name` in Django Admin → Hubs |
| `HUB_002` | Hub | Must have at least 1 business key column | Add a `HubColumn` of type `business_key` in Django Admin → Hub Columns |

---

### Link Rules

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `LNK_001` | Link | Must have a hashkey name set | Set `link_hashkey_name` in Django Admin → Links |
| `LNK_002` | Link | Must reference at least 2 hubs | Add Hub References in Django Admin → Links (minimum 2 inline rows) |

---

### Satellite Rules

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `SAT_001` | Satellite | Must have a parent entity (hub or link) | Set either `parent_hub` or `parent_link` in Django Admin → Satellites |

---

### Pre-stage Rules

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `PST_001` | Pre-stage | Must not be materialized as `ephemeral`: its stage reads the pre-stage's columns from the database (error, `validate.prestage.ephemeral`) | Remove `materialized='ephemeral'` from the pre-stage's `config()`, or set `view` / `table` |
| `PST_002` | Pre-stage | Every `source()` it reads must be a source the project defines (warning, `validate.prestage.unknown_source`). Not checked when the project doesn't generate its sources (`export_sources` off) | Fix the source or table name; dbt matches both exactly, and the message suggests the right spelling when only the case differs |

---

### Naming Rules

Every name the Engine writes into SQL, YAML or a file path is checked before
generation. TurboVault Studio applies the same rules.

- **Data Vault names** — Hub, Link, Satellite, PIT, reference table and
  snapshot control names; hash keys, hashdiffs, key, alias and derived
  columns — must match `^[A-Za-z_][A-Za-z0-9_]*$` and be unique ignoring case.
- **Source names** — physical source tables and columns — are used as they
  are. Names that only work quoted are reported as a warning. Tables and
  columns with special characters get dbt's quoting in `sources.yml`
  (`quoting.identifier` / `quote: true`). datavault4dbt escapes column names
  in its macros and may change their case (lowercase on Postgres/Redshift,
  uppercase on Snowflake/Exasol by default).
- **Derived technical names** — one rule turns display names into technical
  names: lowercase, accents dropped, every run of other characters becomes
  `_`. Source system `SAP-ERP` gives the dbt source `sap_erp`, the folder
  `sap_erp` and the stage `stg__sap_erp__orders`; subject area `Sales & Ops`
  gives the folder and tag `sales_ops`; project `2024 DWH` gives the dbt project
  `project_2024_dwh` (dbt project names must start with a letter).

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `NAM_001` | Any | A Data Vault name is not a plain identifier (error, `validate.name.invalid`) | Rename it using only letters, digits and `_`, starting with a letter or `_` |
| `NAM_002` | Any | Two entity names, or two columns of one stage or satellite, differ only in case (error, `validate.name.case_collision`) | Give them names that differ in more than case |
| `NAM_003` | Source | A source table or column name only works quoted: special characters, reserved word or mixed case (warning, `validate.name.source_needs_quoting`) | Check the generated stage compiles; rename in the source if it doesn't |

The import reports the same problems as `entity.invalid_name`,
`entity.name_case_collision` and `entity.unusual_source_name`.

---

### Generation Output Rules

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `YML_001` | Model | SQL model was generated but YAML schema is missing | Check that the corresponding YAML template exists in Django Admin → Model Templates |
| `PTH_002` | Model | A model's file would not be a plain file inside `models/`: its name (from an entity name or naming pattern) is not a plain identifier, or its folder leaves `models/`. Checked even with validation skipped; nothing is generated (`render.unsafe_path`) | Rename the entity or fix the naming pattern |
| `TPL_003` | Stage | The stage template doesn't read a pre-stage model or prejoin one: it predates pre-stages (warning, `render.template_outdated`) | Update the stage template; `python manage.py populate_templates --overwrite` refreshes the workspace's copies (and replaces their customizations) |

---

## Working with Validation Errors

### Reading Error Output

When validation fails in strict mode, you will see output like:

```
✗ Validation failed:
  [HUB_001] Hub 'hub_customer': missing hashkey name
  [LNK_002] Link 'link_customer_order': only 1 hub referenced (minimum is 2)
```

Each error includes:
- The error **code** for quick lookup
- The **entity name** that failed
- A **short description** of what is wrong

### Fix Cycle

1. Read the error message — note the entity name and code
2. Open Django Admin (`turbovault serve`)
3. Navigate to the entity and fix the issue
4. Re-run `turbovault generate`

### Using Lenient Mode During Development

When iterating on a partial model, use `--mode lenient` to generate output for entities that are valid and skip those that aren't:

```bash
turbovault generate --project my_project --mode lenient
```

This is useful when you are building your model incrementally and want to see partial output before everything is complete. **Switch back to strict mode before deploying to production.**
