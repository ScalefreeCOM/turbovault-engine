# TurboVault Engine — Studio Integration Notes

The one handover document for the TurboVault Studio team: every change to the Engine's data model,
generation, import/export and issue codes that Studio may need to reflect in its UI. Each Engine pull
request that changes something Studio-relevant updates this file.

**Status markers:** **Released** (in an Engine release) · **In review** (open pull request) ·
**Planned** (decided, not implemented; field names may still change; the section is completed when the
Engine change lands).

| # | Change | Status | Studio work |
|---|--------|--------|-------------|
| 1 | [Pre-stages](#1-pre-stages) | In review (Engine PR #232) | Create and edit pre-stages: table type, SQL editor, columns; show their warnings; preview |
| 2 | [Snapshot control model names](#2-snapshot-control-model-names) | In review (Engine PR #232) | Template editor: new template variables |
| 3 | [Outdated stage template warning](#3-outdated-stage-template-warning) | In review (Engine PR #232) | Show the warning; keep Studio-stored stage templates current |
| 4 | [dbt project import](#4-dbt-project-import) | Planned | Upload artifacts, options, review the report |
| 5 | [Model names, paths and configs](#5-model-names-paths-and-configs) | Planned | Edit a generated model's name, path, schema, materialization, tags, config |
| 6 | [Hash diff name and alias](#6-hash-diff-name-and-alias) | Planned | Two Satellite fields |
| 7 | [Stage options and missing columns](#7-stage-options-and-missing-columns) | Planned | Project defaults and source table overrides; flag a column as missing |
| 8 | [Derived columns that shadow a source column](#8-derived-columns-that-shadow-a-source-column) | Planned | Allow a derived column with a source column's name |
| 9 | [Satellite v1 options](#9-satellite-v1-options) | Planned | Satellite fields for its v1 view |
| 10 | [Smaller additions](#10-smaller-additions) | Planned | A few fields on Hubs, PITs and snapshot controls |
| 11 | [Custom models](#11-custom-models) | Planned | List, view and edit custom models |

Background for items 4–11: [`07_dbt_project_import_specification.md`](07_dbt_project_import_specification.md).

---

## 1. Pre-stages

**Status:** In review, Engine PR #232. Engine docs: domain model §3.5, generation pipeline, validation rules,
JSON import, admin guide.

### What it is

Some data can't be loaded into the Raw Vault from its source table as it is: JSON to parse, a table to
pivot or unpivot, rows to deduplicate. A **pre-stage** is a dbt model that prepares that data before the
stage. In the Engine it is a **source table of type `prestage`** whose SQL is the dbt model. In every
other respect it is a source table: it belongs to a source system, has columns, record source and load
date, derived columns and prejoins, and Hubs, Links and Satellites map its columns like any table's.

### Data model

| Model / field | Type | Default | Notes |
|---------------|------|---------|-------|
| `SourceTable.table_type` | choice: `physical`, `prestage` | `physical` | Labels: "Physical table", "Pre-stage". Property `is_prestage`. |
| `SourceTable.prestage_sql` | text, nullable | empty | The complete dbt model (`{{ source() }}` / `{{ ref() }}` / `{{ config() }}` / any dbt Jinja), written to the project as it is (trailing whitespace trimmed). **Empty**: the model is maintained outside TurboVault; its stage still reads it. |
| `SourceTable.physical_table_name` | text | — | For a pre-stage: the name its model and stage are named after. Unique per source system, like any table. |
| `SourceColumn` (existing) | — | — | The pre-stage's **output columns** (name, data type, description). Needed for mapping, and written to the model's YAML. |
| `ModelTemplate.EntityType.PRESTAGE` | `prestage` | — | Template entity type for the pre-stage's SQL and YAML templates. |

- Migration `0019_prestages`. Existing tables become `physical`.
- `SourceTable.clean()` rejects SQL on a physical table: a `ValidationError` on `prestage_sql`
  ("Only a pre-stage has SQL. Set the table type to pre-stage, or clear the SQL.").
- A column's staging column (what mappings point to) is created by a `post_save` signal on
  `SourceColumn`. **Bulk inserts skip it**: save columns individually, or call
  `engine.services.staging_service.get_or_create_staging_column` for each.

### Generated dbt project

| File | Content |
|------|---------|
| `models/01_prestaging/<system>/pstg__<system>__<table>.sql` | `prestage_sql` as it is. Only when the pre-stage has SQL. |
| `models/01_prestaging/<system>/pstg__<system>__<table>.yml` | Model name, description (the table's, else "Pre-stage model for …"), tags `['prestage', '<system>']`, columns with `data_type` and description. |
| `models/02_staging/<system>/stg__<system>__<table>.sql` | The stage reads the pre-stage with `source_model: 'pstg__<system>__<table>'` (dbt `ref()`). |
| `models/01_sources/source__<system>.yml` | Leaves pre-stages out. A system with only pre-stages gets no sources file. |
| `dbt_project.yml` | A `01_prestaging` block (staging layer's schema and materialization; `ephemeral` becomes `view`). Only when at least one pre-stage has SQL. |

`<system>` and `<table>` are lowercased, spaces become `_`. These names become configurable with item 5.

Behaviour to explain in the UI:

- **Inputs get no stage.** A table that pre-stages read (`source()` or `ref()` in their SQL) and that loads
  nothing into the Raw Vault itself gets no stage.
- **Prejoins onto a pre-stage** read the model with `ref_model`.
- **No SQL:** no files are written, and the stage still reads `pstg__<system>__<table>`. The user must
  provide a model of that name, e.g. by hand or from a dbt package.
- **Materialization:** a model's own `{{ config(materialized=…) }}` overrides the layer's. It must not be
  `ephemeral`, because the stage reads the pre-stage's columns from the database.

### Issues to show

| Code | Severity | Meaning | Suggested UI |
|------|----------|---------|--------------|
| `validate.prestage.ephemeral` | error | The SQL configures `materialized='ephemeral'` | Show on the pre-stage's SQL field |
| `validate.prestage.unknown_source` | warning | The SQL reads a `source()` the project doesn't define. The message suggests the right spelling when only the case differs (dbt matches names exactly). Skipped when the project doesn't generate its sources. | Show on the SQL field; offer the suggested spelling |
| `render.sqlmesh.unsupported.prestage` | warning | SQLMesh output skips the pre-stage | Note that pre-stages are dbt-only |
| `render.sqlmesh.prestage_dependent_skipped` | warning | SQLMesh output skipped a Hub, Link or Satellite loaded from a pre-stage's stage | List under the entity |
| `render.template_outdated` | warning | See item 3 | — |

Generation report: artifacts have `entity_type: "prestage"` (`kind` `sql_model` / `yaml_schema`); the plan
counts `by_entity_type["prestage"]` (two files per pre-stage with SQL).

### Preview

`generate(..., options=GenerationOptions(dry_run=True, return_content=True))` returns the pre-stage's SQL and
YAML as artifacts with `entity_type == "prestage"` and `entity_name == "pstg__…"`. Pre-stages are always
rendered; entity selection doesn't filter them, like stages.

### Templates

Context of both `prestage` templates: `model_name`, `table_name`, `source_system`, `prestage_sql` (passed as
`Markup`, so the autoescaping of DB-stored templates leaves quotes alone), `description`, `columns`
(`column_name`, `datatype`, `description`). The bundled SQL template writes `[[ prestage_sql ]]`.

### Import and export

- **JSON export:** `sources[].tables[]` gains `table_type` (`"physical"` | `"prestage"`) and `prestage_sql`
  (string or null). It also carries the derived lists `prestages[]` (`model_name`, `table_name`,
  `source_system`, `sql`, `description`, `columns`), `stages[].prestage_model` and
  `stages[].prejoins[].target_model`. The import doesn't read these derived lists.
- **JSON import:**
  - Sets type and SQL. A `prestage_sql` of `null` clears the SQL.
  - An export from before pre-stages existed leaves table types and SQL unchanged.
  - An unknown `table_type` fails with `source.invalid_json`.
  - Re-importing the same file changes nothing.
- **Excel, SQLite, IRiS, `source_metadata` imports** can't describe pre-stages. They leave them untouched,
  and `replace_all` keeps pre-stages and the source systems holding them.
- **IRiS export** keeps a pre-stage as a table (its mappings stay valid) and warns that the SQL isn't
  carried.
- **MCP `list_sources`** reports `table_type` per table.

### Suggested UI

- **Source table form:**
  - A *Type* choice (Physical table / Pre-stage).
  - For a pre-stage, a SQL editor with dbt Jinja highlighting, plus a hint to read inputs with
    `{{ source('<system>', '<TABLE>') }}` using the names in the generated sources, or `{{ ref('<model>') }}`.
  - An option "maintained outside TurboVault" (empty SQL) that shows the model name the stage will read.
- **Columns:** the pre-stage's output columns with data types. Mapping needs them; consider a "fill from
  the warehouse" action once the model exists.
- **Record source / load date:** usually a column the pre-stage passes through. A fixed record source naming
  the raw table (e.g. `!CRM.CUSTOMER_RAW`) keeps the original source in `rsrc`.
- **Table lists:** a type badge and a type filter.
- **Preview:** the generated model and the stage that reads it.

### Planned changes affecting pre-stages

- Item 5: the model name becomes configurable, so imported pre-stages keep their original names.
- The ephemeral check will apply only to pre-stages a stage reads directly; models that only other
  pre-stages read may be ephemeral.

---

## 2. Snapshot control model names

**Status:** In review, Engine PR #232 (fix).

A snapshot control stored with a `_v0` / `_v1` suffix (e.g. `control_snap_v0`) got YAML describing
`control_snap_v0_v0` / `control_snap_v0_v1`, matching no model, so its tests never ran. The model files were
named correctly.

- The `snapshot_control_v0` / `_v1` templates receive `name` = the **base name** (suffix stripped), plus
  `v0_name` and `v1_name` (the model names). The bundled templates use `v0_name` / `v1_name`.
- Stored template copies that still write `[[ name ]]_v0` now produce the right names too.
- **Studio:** if Studio shows template variables, add `v0_name` and `v1_name`. If Studio renders these
  templates itself, pass the same context.

---

## 3. Outdated stage template warning

**Status:** In review, Engine PR #232.

Workspace copies of the templates (seeded by `workspace init`, stored as `ModelTemplate` rows) take
precedence over the bundled files. A stage template copied before pre-stages existed reads every table as a
dbt source; for a pre-stage, dbt would fail to find that source.

- When a rendered stage doesn't contain its pre-stage's model name (or a prejoined pre-stage's), generation
  reports `render.template_outdated` (warning) on the stage.
- **Studio:** show the warning. If Studio stores its own template copies, update them from the bundled
  `stage` template (it gained the `prestage_model` and `prejoin.target_model` branches).

---

## 4. dbt project import

**Status:** Planned (spec Phases 2, 4, 5).

Imports an existing datavault4dbt project from its dbt artifacts. The Engine never runs dbt or connects to the
warehouse.

- **Inputs:**
  - `manifest.json` (required, schema v12).
  - `catalog.json`, `dbt_project.yml`, `packages.yml` / `dependencies.yml` / `package-lock.yml`
    (optional).
  - Or a project directory / archive holding them.
  - Never `profiles.yml`.
- **Options:** conflict strategy and dry run as for every import; import descriptions and tags (default on);
  keep unmapped models as custom models (item 11, default off).
- **Report:** per model imported / imported with changes / skipped, each issue with the model's node id,
  file path, parameter and a `dbt.*` code (spec §11). Also the naming patterns inferred, and counts of
  resources not imported (seeds, tests, …).
- **Suggested UI:**
  - An upload step (files or archive).
  - A dry-run review: entities to create or update, skipped models with reasons, warnings.
  - A confirm step.
  - Afterwards, the report linked from the import run.

---

## 5. Model names, paths and configs

**Status:** Planned (spec §9.1, Phase 3).

Every generated dbt model can keep its own name, alias, path, schema, database, materialization, tags and
other config keys. The import fills them from the original project; empty means "derived as today".

- One record per entity and output kind:
  - source table: stage / pre-stage
  - Hub: hub / effectivity Satellite / record-tracking Satellite
  - Link: link / record-tracking Satellite
  - Satellite: v0 / v1
  - PIT, reference table
  - snapshot control: v0 / v1
- Every reference between models follows the stored names.
- New project naming patterns for stages and pre-stages replace the fixed `stg__…` / `pstg__…`.
- A generation option switches back to TurboVault's standard structure.
- **Studio:** a "dbt model" section on each entity, with fields per output (model name, file path, schema,
  materialization, tags, extra config); naming pattern fields for stages and pre-stages in the project
  settings.

---

## 6. Hash diff name and alias

**Status:** Planned (spec §9.2).

- **Satellite hash diff name:** the stage's hash diff column. Default: the project's `hashdiff_naming`
  pattern; editable per Satellite.
- **Satellite hash diff alias:** the column's name inside the Satellite when it differs, e.g. a uniform
  `hashdiff` column in every Satellite (datavault4dbt `src_hashdiff: {source_column, alias}`).
- **Studio:** two optional fields on the Satellite form; show the derived default as placeholder.

---

## 7. Stage options and missing columns

**Status:** Planned (spec §9.3).

- **Project defaults, overridable per source table:**
  - `include_source_columns` (default true)
  - `enable_ghost_records` (default true)
  - `sequence` (a column name, default none)
- **Missing columns:** columns that disappeared from the source but must stay in the stage as NULL (so
  Satellites and hash diffs keep working). Proposed as a flag on the source column (name + data type stay),
  mappable like other columns.
- **Studio:** project settings for the defaults; a "stage options" section on the source table form; a
  "missing in source" toggle on columns.

---

## 8. Derived columns that shadow a source column

**Status:** Planned (spec §9.4). Breaking change to derived columns.

A derived column may use the name of a source column of its table: the stage computes it in place of the
source column. Today the Engine rejects that name. A Hub/Link column transformation on the same column
conflicts and fails validation. **Studio:** drop the corresponding client-side check, and show the new
validation error.

---

## 9. Satellite v1 options

**Status:** Planned (spec §9.5).

Per Satellite:
- the load-end-date column name of its v1 view (`ledts_alias`; default: the project's datavault4dbt setting)
- whether v1 adds an `is_current` flag (default true, as today)
- whether v1 includes the payload (default true)
- whether the Satellite gets a v1 view at all (default: the project's setting)

**Studio:** a "v1 view" section on the Satellite form.

---

## 10. Smaller additions

**Status:** Planned (spec §9.6).

- **Hub:** the effectivity Satellite's `is_active` column name.
- **Hub sources:** load a Hub from a differently named hash key column of a stage (role-playing sources,
  e.g. author and committer from one stage). The data model is designed in Phase 3.
- **PIT:** the stored `custom_record_source` is written to the generated PIT (`custom_rsrc`). Show the
  field if Studio hides it today.
- **Snapshot control:** the stored end date is written to the generated model (`end_date`), plus an optional
  snapshot date column name (`sdts_alias`).

---

## 11. Custom models

**Status:** Planned (spec Phase 6, #461). Optional on import.

Models the import can't map (Business Vault, marts, …), kept with their SQL, YAML properties and output
attributes, and written back unchanged. Generation warns when a custom model refers to a model that no longer
exists. SQLMesh output skips them. **Studio:** list, view and edit custom models (SQL editor, properties,
output attributes); show broken references.
