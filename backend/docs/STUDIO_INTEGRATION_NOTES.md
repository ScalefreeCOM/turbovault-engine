# TurboVault Engine — Studio Integration Notes

The one handover document for the TurboVault Studio team: every change to the Engine's data model,
generation, import/export and issue codes that Studio may need to reflect in its UI. Each Engine pull
request that changes something Studio-relevant updates this file.

**Status markers:** **Released** (in an Engine release) · **Merged** (on `main`, not yet released) ·
**In review** (open pull request) · **In progress** (on the dbt import branch `feat/dbt-project-import`,
which becomes one pull request) · **Planned** (decided, not implemented; field names may still change; the
section is completed when the Engine change lands).

| # | Change | Status | Studio work |
|---|--------|--------|-------------|
| 1 | [Pre-stages](#1-pre-stages) | Merged (Engine PR #232, unreleased); reworked on the dbt import branch | Create and edit pre-stages: table type, columns; show the "generate into your dbt project" warning |
| 2 | [Snapshot control model names](#2-snapshot-control-model-names) | Merged (Engine PR #232, unreleased) | Template editor: new template variables |
| 3 | [Outdated stage template warning](#3-outdated-stage-template-warning) | Merged (Engine PR #232, unreleased) | Show the warning; keep Studio-stored stage templates current |
| 4 | [dbt project import](#4-dbt-project-import) | Planned | Upload artifacts, options, review the report |
| 5 | [Model names, paths and configs](#5-model-names-paths-and-configs) | Planned | Edit a generated model's name, path, schema, materialization, tags, config |
| 6 | [Hash diff name and alias](#6-hash-diff-name-and-alias) | Planned | Two Satellite fields |
| 7 | [Stage options and missing columns](#7-stage-options-and-missing-columns) | Planned | Project defaults and source table overrides; flag a column as missing |
| 8 | [Derived columns that shadow a source column](#8-derived-columns-that-shadow-a-source-column) | Planned | Allow a derived column with a source column's name |
| 9 | [Satellite v1 options](#9-satellite-v1-options) | Planned | Satellite fields for its v1 view |
| 10 | [Smaller additions](#10-smaller-additions) | Planned | A few fields on Hubs, PITs and snapshot controls |
| 11 | [Custom models](#11-custom-models) | Planned | List, view and edit custom models |
| 12 | [Layer folders renumbered](#12-layer-folders-renumbered) | In progress | Use the new folder names wherever Studio shows or builds model paths |

Background for items 4–11: [`07_dbt_project_import_specification.md`](07_dbt_project_import_specification.md).

---

## 1. Pre-stages

**Status:** Merged with Engine PR #232 (unreleased), then reworked on the dbt import branch (in progress):
pre-stages no longer store SQL. This section describes the reworked state; [Changes since PR #232](#changes-since-pr-232)
lists the differences. Engine docs: domain model §3.5, generation pipeline, validation rules, JSON import,
admin guide.

### What it is

Some data can't be loaded into the Raw Vault from its source table as it is: JSON to parse, a table to
pivot or unpivot, rows to deduplicate. The dbt project prepares such data in a model of its own, a
**pre-stage**, and TurboVault loads from that model. In the Engine a pre-stage is a **source table of type
`prestage`**. In every other respect it is a source table: it belongs to a source system, has columns, record
source and load date, derived columns and prejoins, and Hubs, Links and Satellites map its columns like any
table's.

**The model belongs to the dbt project and its developers, not to TurboVault.** TurboVault stores no SQL for
it and generates no file; the pre-stage only describes the model's output so the Raw Vault can be mapped onto
it. The generated stage reads the model with `ref()`, so the generated project works only inside the dbt
project that contains the model. (Decided after PR #232: TurboVault doesn't take responsibility for these
models, and SQLMesh or future output types couldn't run dbt models anyway.)

### Data model

| Model / field | Type | Default | Notes |
|---------------|------|---------|-------|
| `SourceTable.table_type` | choice: `physical`, `prestage` | `physical` | Labels: "Physical table", "Pre-stage". Property `is_prestage`. |
| `SourceTable.physical_table_name` | text | — | For a pre-stage: the name its model and stage are named after. Unique per source system, like any table. |
| `SourceColumn` (existing) | — | — | The model's **output columns** (name, data type, description). Needed for mapping. |

- Migration `0019_prestages` adds `table_type`; existing tables become `physical`.
- Migration `0020_prestages_maintained_in_dbt` removes `SourceTable.prestage_sql` and the `prestage` template
  entity type, and deletes workspace copies of the pre-stage templates (`ModelTemplate` rows with
  `entity_type = "prestage"`).
- A column's staging column (what mappings point to) is created by a `post_save` signal on
  `SourceColumn`. **Bulk inserts skip it**: save columns individually, or call
  `engine.services.staging_service.get_or_create_staging_column` for each.

### Generated dbt project

| File | Content |
|------|---------|
| `models/20_staging/<system>/stg__<system>__<table>.sql` | The stage reads the pre-stage with `source_model: 'pstg__<system>__<table>'` (dbt `ref()`). |
| `models/10_sources/source__<system>.yml` | Leaves pre-stages out. A system with only pre-stages gets no sources file. |
| `dbt_project.yml` | A `15_prestaging` block whenever the project has pre-stages: the staging layer's schema and materialization (`ephemeral` becomes `view`). The dbt project's models placed in `models/15_prestaging/` get these settings. |

Nothing is generated for the pre-stage itself. `<system>` and `<table>` are lowercased, spaces become `_`.
These names become configurable with item 5.

Behaviour to explain in the UI:

- **Generate into the dbt project.** The stage's `ref()` only resolves in the dbt project that contains the
  model; anywhere else dbt fails to compile it. Every dbt generation warns once per pre-stage.
- **Inputs keep their stages.** TurboVault doesn't know what the model reads, so every table gets its stage,
  including the tables only the model reads.
- **Prejoins onto a pre-stage** read the model with `ref_model`.
- **Views or tables only.** datavault4dbt's stage reads its input's columns from the database, where an
  ephemeral model doesn't exist. The model's materialization is the dbt project's business; TurboVault no
  longer checks it.

### Issues to show

| Code | Severity | Meaning | Suggested UI |
|------|----------|---------|--------------|
| `render.prestage.maintained_in_dbt` | warning | dbt output only, once per pre-stage (`entity.type` `prestage`, `entity.name` the model name): the model belongs to the dbt project; generate into the dbt project that contains it. The message names the stage that reads it. | Show prominently around generation, e.g. "This project needs N models from your dbt project", listing them |
| `render.sqlmesh.unsupported.prestage` | warning | SQLMesh output can't read the dbt model; it skips the pre-stage's stage | Note that pre-stages are dbt-only |
| `render.sqlmesh.prestage_dependent_skipped` | warning | SQLMesh output skipped a Hub, Link or Satellite loaded from a pre-stage's stage | List under the entity |
| `render.template_outdated` | warning | See item 3 | — |

The generation report has no artifacts with `entity_type: "prestage"`, and the dbt plan's `by_entity_type`
has no `prestage` entry. The single-file outputs (JSON, DBML) still count pre-stages as entities.

### Import and export

- **JSON export:** `sources[].tables[]` has `table_type` (`"physical"` | `"prestage"`). The export also
  carries the derived lists `prestages[]` (`model_name`, `table_name`, `source_system`, `description`,
  `columns`: the models the dbt project must contain), `stages[].prestage_model` and
  `stages[].prejoins[].target_model`. The import doesn't read these derived lists.
- **JSON import:**
  - Sets the table type.
  - An export from before pre-stages existed leaves table types unchanged.
  - A `prestage_sql` field (files exported while pre-stages had SQL) is ignored.
  - An unknown `table_type` fails with `source.invalid_json`.
  - Re-importing the same file changes nothing.
- **Excel, SQLite, IRiS, `source_metadata` imports** can't describe pre-stages. They leave them untouched,
  and `replace_all` keeps pre-stages and the source systems holding them.
- **IRiS export** keeps a pre-stage as a table, so its mappings stay valid.
- **dbt project import (item 4)** creates pre-stages for the project's own models that its stages read, and
  its report warns that the project must be generated back into that dbt project.
- **MCP `list_sources`** reports `table_type` per table.

### Suggested UI

- **Source table form:** a *Type* choice (Physical table / Pre-stage). For a pre-stage, show the model name
  the stage reads (`pstg__<system>__<table>`; editable with item 5) and a note that the model lives in the
  dbt project. No SQL editor.
- **Columns:** the model's output columns with data types. Mapping needs them; consider filling them from
  the warehouse or from the dbt project's `catalog.json` once the model exists.
- **Record source / load date:** usually a column the model passes through. A fixed record source naming
  the raw table (e.g. `!CRM.CUSTOMER_RAW`) keeps the original source in `rsrc`.
- **Table lists:** a type badge and a type filter.
- **Generation:** surface `render.prestage.maintained_in_dbt` before the user downloads or deploys the
  output. Generating a standalone project for a project with pre-stages gives a dbt project that doesn't
  compile until the models are added.

### Changes since PR #232

- Removed: `SourceTable.prestage_sql`, `SourceTable.clean()`'s SQL check, the `prestage` template entity type
  and the bundled pre-stage SQL and YAML templates. **Studio:** drop the SQL editor, the "maintained outside
  TurboVault" option and the pre-stage preview: every pre-stage is maintained in the dbt project.
- No pre-stage files are generated (they were `models/15_prestaging/<system>/pstg__….sql` and `.yml`). The
  `15_prestaging` block in `dbt_project.yml` is written whenever the project has pre-stages (was: when one has
  SQL).
- A table that only pre-stages read gets its stage again: without the SQL, TurboVault can't tell.
- Issue codes: `validate.prestage.ephemeral` and `validate.prestage.unknown_source` are gone;
  `render.prestage.maintained_in_dbt` is new.
- JSON export: `prestages[].sql` and `sources[].tables[].prestage_sql` are gone.
- The layer folders are renumbered (`10_sources`, `15_prestaging`, `20_staging`, …): see item 12.

### Planned changes affecting pre-stages

- Item 5: the model name becomes configurable, so imported pre-stages keep their original names.

---

## 2. Snapshot control model names

**Status:** Merged, Engine PR #232 (fix), unreleased.

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

**Status:** Merged, Engine PR #232, unreleased.

Workspace copies of the templates (seeded by `workspace init`, stored as `ModelTemplate` rows) take
precedence over the bundled files. A stage template copied before pre-stages existed reads every table as a
dbt source; for a pre-stage, dbt would fail to find that source.

- When a rendered stage doesn't contain its pre-stage's model name (or a prejoined pre-stage's), generation
  reports `render.template_outdated` (warning) on the stage.
- **Studio:** show the warning. If Studio stores its own template copies, update them from the bundled
  `stage` template (it gained the `prestage_model` and `prejoin.target_model` branches).

---

## 4. dbt project import

**Status:** In progress (dbt import branch): artifact reading and call extraction are built; the import
itself comes with spec Phases 4 and 5.

Imports an existing datavault4dbt project from its dbt artifacts. The Engine never runs dbt or connects to the
warehouse.

- **Inputs:**
  - `manifest.json` (required, schema v12).
  - `catalog.json`, `dbt_project.yml`, `packages.yml` / `dependencies.yml` / `package-lock.yml`
    (optional).
  - Or a local dbt project folder (CLI and local use): the Engine finds the files in it and reports each as
    found or missing. A missing catalog or `dbt_project.yml` is a warning. Studio uploads the files.
  - Never `profiles.yml`.
- **Pre-stages:** the models upstream of the stages become pre-stages (item 1); their SQL stays in the dbt
  project. The report warns that the project must be generated back into that dbt project
  (`dbt.prestage_maintained_in_dbt`). Show this before the user confirms the import.
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

---

## 12. Layer folders renumbered

**Status:** In progress (dbt import branch). Breaking change.

Generated dbt projects number their layer folders in tens, leaving room for layers in between:

| Layer | Before | Now |
|-------|--------|-----|
| Control (snapshot controls) | `models/00_control` | `models/00_control` |
| Sources | `models/01_sources` | `models/10_sources` |
| Pre-staging (the dbt project's own pre-stage models) | `models/01_prestaging` | `models/15_prestaging` |
| Staging | `models/02_staging` | `models/20_staging` |
| Raw Vault | `models/03_raw_vault` | `models/30_raw_vault` |
| Business Vault | `models/04_business_vault` | `models/40_business_vault` |

- `dbt_project.yml` configures the new folder names. SQLMesh output is unchanged.
- Projects that keep their own `dbt_project.yml`, or select models by path (`dbt run -s path:models/03_raw_vault`),
  must switch to the new names.
- The bundled `dbt_project.yml` template renders the new keys. Its `15_prestaging` block appears when the
  `prestaging_materialization` variable is set: the Engine sets it to the staging materialization (`view` for
  `ephemeral`) when the project has pre-stages.
- **Studio:** use the new names wherever Studio shows, filters or links generated paths (file tree, previews,
  its `dbt_project.yml` prefill). Consider telling existing users once, since their path selectors break.
