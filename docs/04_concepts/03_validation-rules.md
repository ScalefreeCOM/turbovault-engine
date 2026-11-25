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
| `STG_005` | Stage | Satellites of one stage may share a hash diff name only if they hash the same columns (`validate.stage.duplicate_hashdiff`) | Give one satellite its own `hashdiff_name` |
| `REF_001` | Reference table | Each satellite it reads must get a v1 view (warning, `validate.reference_table.satellite_without_v1`) | Turn the satellite's v1 view on (`create_v1_view`, or the project's `generate_satellite_v1_views`) |

---

### Model Name Rules

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `MDL_001` | Any model | No two models of the project share a name, compared case-insensitively; pre-stages count (`validate.model.duplicate_name`) | Rename one: its model output's name, or the entity |
| `MDL_002` | Any model | A model name must name a file inside the project: no slashes or `..` (`validate.model.invalid_name`) | Rename the model or the entity |
| `MDL_003` | Any model | A stored folder must be relative to the dbt project and stay inside it (`validate.model.invalid_folder`) | Use a folder such as `models/raw_vault/hubs` |

---

### Naming Rules

Every name the Engine writes into SQL, YAML or a file path is checked before
generation and on import. The rules are TurboVault Studio's naming rules
(#451), so CLI, API and Studio users get the same checks.

- **Data Vault names** (rule A) — Hub, Link, Satellite, PIT, reference table
  and snapshot control names; hash keys (also a stage's own hash key for a
  role-playing hub source), hashdiffs and their aliases, key, alias and derived
  columns, dependent child keys; the `is_active` alias of effectivity
  satellites, the v1 load end date alias, the snapshot date alias; table
  aliases; the stage, raw vault and business vault schemas — must match
  `^[A-Za-z_][A-Za-z0-9_]*$` and be unique ignoring case. SQL reserved words
  and names longer than 63 characters (Postgres truncates them) are warnings.
- **Source names** (rule B) — physical source schemas, databases, tables and
  columns — are used as they are, so spaces, hyphens and mixed case are
  allowed. Names with control characters, invisible format characters (a
  byte-order mark left at the start of a CSV header, a zero-width space),
  Jinja markers (`{{`, `{%`, `{#`: dbt would run them inside the generated
  metadata), leading or trailing whitespace or a quote character (`"`,
  `` ` ``) are errors. Names that only work quoted are
  reported as a warning. A stage's sequence column and the further columns an
  effectivity satellite carries are stage columns taken from the source, so
  they follow this rule too. Tables and
  columns with special characters get dbt's quoting in `sources.yml`
  (`quoting.identifier` / `quote: true`). datavault4dbt escapes column names
  in its macros and may change their case (lowercase on Postgres/Redshift,
  uppercase on Snowflake/Exasol by default).
- **Display names** (rule C) — source system and subject area names — should
  contain only letters, digits, spaces, `-`, `_` and `.`. Studio rejects
  anything else; the Engine only warns, because the technical name below is
  derived safely from any display name. A name starting with `.` (a hidden
  folder, or `..`, where a folder pattern spells it out with `[[ group_name ]]`
  or `[[ source_system_name ]]`) or holding characters no generated code can
  carry is an error. The spelled placeholders replace `/` and `\` with `_`.
- **Derived technical names** — one rule turns display names into technical
  names: lowercase, German letters spelled out (`ä`→`ae`, `ö`→`oe`,
  `ü`→`ue`, `ß`→`ss`, so `Müller Straße` gives `mueller_strasse`), other
  accents dropped (`Café` gives `cafe`), every run of other characters becomes
  `_`, repeated `_` collapse to one and none is kept at either end (`Sales (EU)`
  gives `sales_eu`, not `sales_eu_`: `__` separates the parts of a stage name).
  Two source systems, or two tables of one system, that give the same technical
  name are errors (their sources and stages would overwrite each other); two
  subject areas that do are a warning (their models share a folder and tag).
  Source system `SAP-ERP` gives the dbt source `sap_erp`, the folder
  `sap_erp` and the stage `stg__sap_erp__orders`; subject area `Sales & Ops`
  gives the folder and tag `sales_ops`; project `2024 DWH` gives the dbt project
  `project_2024_dwh` (dbt project names must start with a letter).

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `NAM_001` | Any | A Data Vault name is not a plain identifier (error, `validate.name.invalid`) | Rename it using only letters, digits and `_`, starting with a letter or `_` |
| `NAM_002` | Any | Two entity names, or two columns of one stage or satellite, differ only in case (error, `validate.name.case_collision`) | Give them names that differ in more than case |
| `NAM_003` | Source | A source table or column name only works quoted: special characters, reserved word or mixed case (warning, `validate.name.source_needs_quoting`) | Check the generated stage compiles; rename in the source if it doesn't |
| `NAM_004` | Any | A Data Vault name is an SQL reserved word (warning, `validate.name.reserved_word`) | Rename it, e.g. add a prefix or suffix |
| `NAM_005` | Any | A Data Vault name is longer than 63 characters (warning, `validate.name.too_long`) | Shorten it if the project runs on Postgres |
| `NAM_006` | Source, Hub, Link | A source schema, database, table or column name, a stage's sequence column or a further column of an effectivity satellite has a control or invisible format character, a Jinja marker, leading or trailing whitespace or a quote character (error, `validate.name.invalid_source_name`) | Fix the name in the metadata; it must match the source |
| `NAM_007` | Source system, subject area | A display name has characters other than letters, digits, spaces, `-`, `_` and `.` (warning, `validate.name.unusual_display_name`) | Rename it, e.g. `Sales & Ops` → `Sales and Ops` |
| `NAM_008` | Source system, source table, subject area | Two display names give the same technical name: source systems or tables of one system (error), subject areas (warning) (`validate.name.technical_name_collision`) | Rename one of them |
| `NAM_009` | Source system, subject area | A display name starts with `.` or holds a control or invisible format character or a Jinja marker (error, `validate.name.invalid_display_name`) | Rename it |

Templates rely on these rules, so name errors keep their entities out of the
output in every error strategy. `fail_fast` stops the run. `best_effort`
leaves out each entity with a name error and every entity that depends on it
(the Satellites and Links of a Hub, the Hubs, Links and Satellites loaded from
a source table, the PITs and reference tables reading them, ...), reports each
as `validate.name.entity_left_out` (warning) and generates the rest
(`partial_success`). An invalid stage, raw vault or business vault schema
leaves nothing to generate.

The import reports the same problems as `entity.invalid_name`,
`entity.name_case_collision`, `entity.unusual_source_name`,
`entity.name_reserved_word`, `entity.name_too_long`,
`entity.invalid_source_name`, `entity.unusual_display_name` and
`entity.invalid_display_name`. In `best_effort` an import leaves out the
entities with `entity.invalid_name` or `entity.name_case_collision` and their
dependents (skips with reason `invalid_name` / `depends_on_skipped`).

---

### Generation Output Rules

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `YML_001` | Model | SQL model was generated but YAML schema is missing | Check that the corresponding YAML template exists in Django Admin → Model Templates |
| `TPL_003` | Any model | The template predates something the model needs (warning, `render.template_outdated`): a stage template that doesn't read a pre-stage model or prejoin one; a template that doesn't write the model's stored `config()` settings, its stored tags, or the stored names of the models it references (e.g. a v1 view's v0 table) | Update the template; `python manage.py populate_templates --overwrite` refreshes the workspace's copies (and replaces their customizations) |
| `PST_001` | Pre-stage | Each dbt generation reminds that the pre-stage's model belongs to the dbt project: TurboVault doesn't generate it, and its stage reads it with `ref()` (warning, `render.prestage.maintained_in_dbt`) | Nothing to fix: generate into the dbt project that contains the model |
| `PTH_002` | Model | A model's or source's file would be written outside the output folder. Last line of defence behind `MDL_002`, `MDL_003` and `NAM_001`, also with validation skipped (`render.unsafe_path`) | Rename the entity or fix the naming pattern |

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
