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
| 4 | [dbt project import](#4-dbt-project-import) | In progress | Upload artifacts, pass the project's settings, options, review the report |
| 5 | [Model names, paths and configs](#5-model-names-paths-and-configs) | In progress | Edit a generated model's name, folder, schema, materialization, tags, config; stage/pre-stage naming patterns |
| 6 | [Hash diff name and alias](#6-hash-diff-name-and-alias) | In progress | Two Satellite fields |
| 7 | [Stage options and missing columns](#7-stage-options-and-missing-columns) | In progress | Project defaults, source system and table overrides; flag a column as missing |
| 8 | [Derived columns that shadow a source column](#8-derived-columns-that-shadow-a-source-column) | In progress | Allow a derived column with a source column's name |
| 9 | [Satellite v1 options](#9-satellite-v1-options) | In progress | Satellite fields for its v1 view |
| 10 | [Hub, Link, PIT and snapshot control options; delivery method](#10-hub-link-pit-and-snapshot-control-options-delivery-method) | In progress | Fields on Hubs, Links, mappings, Satellites, source systems/tables, PITs and snapshot controls; two project settings |
| 11 | [Custom models](#11-custom-models) | Postponed | List, view and edit custom models |
| 12 | [Layer folders renumbered](#12-layer-folders-renumbered) | In progress | Use the new folder names wherever Studio shows or builds model paths |
| 13 | [JSON export and import of the new settings; snapshot controls](#13-json-export-and-import-of-the-new-settings-snapshot-controls) | In progress | Show the new `snapshot_control` plan entities; keep `model_outputs` when Studio builds or edits exports |
| 14 | [Links select their dependent child keys](#14-links-select-their-dependent-child-keys) | In progress | Template editor: new variable `dependent_child_keys`; tell users their links gain columns |
| 15 | [Snapshot control logic as datavault4dbt reads it](#15-snapshot-control-logic-as-datavault4dbt-reads-it) | In progress | Offer the components datavault4dbt computes; show `SNAP_002`; template editor variables |
| 16 | [An imported dbt_project.yml comes back](#16-an-imported-dbt_projectyml-comes-back) | In progress | Store two new project settings and pass them to generation; reconcile with the manual dbt_project.yml |
| 17 | [Default tags setting](#17-default-tags-setting) | In progress | A project switch; the tag field of a model's settings now adds tags |
| 18 | [Folder structure; model folders setting; layers without schema](#18-folder-structure-model-folders-setting-layers-without-schema) | In progress | Folder pattern settings with placeholders; the model folders switch; "no custom schema" per layer |
| 19 | [Project settings a dbt project suggests; packages](#19-project-settings-a-dbt-project-suggests-packages) | In progress | Show the suggestions after a dry run, apply the accepted ones to the project's settings; store the packages |
| 20 | [Round trip: what a dbt import reads back; generation fixes](#20-round-trip-what-a-dbt-import-reads-back-generation-fixes) | In progress | None required; generated output changes in two places (stage hash key order, models without settings) |
| 21 | [Generating into an existing dbt project](#21-generating-into-an-existing-dbt-project) | In progress | Nothing for zip downloads; new generation options and issue codes; the record file in generated output |

Background for items 4–21: [`07_dbt_project_import_specification.md`](07_dbt_project_import_specification.md).

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
These are the default naming patterns: projects can change them (`stage_naming`, `prestage_naming`), and a
pre-stage or stage can store its own model name (item 5).

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
| `render.prestage.maintained_in_dbt` | warning | dbt output only, once per pre-stage (`entity.type` `prestage`, `entity.name` the model name): the model belongs to the dbt project; generate into the dbt project that contains it. The message names the stage that reads it. When generating into an existing dbt project (item 21), only the pre-stages it lacks are reported. | Show prominently around generation, e.g. "This project needs N models from your dbt project", listing them |
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

### Related

- Item 5 (in progress): a pre-stage stores its model's name as a `ModelOutput` of kind `prestage` (name
  only), so imported pre-stages keep their original names.

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

**Status:** In progress (dbt import branch), complete for the pull request (spec Phases 2–5). It covers:

- the `DbtSource` in the import pipeline, with artifact detection and its issues, and the CLI;
- the mapping of stages, pre-stages (also from seeds, snapshots and other packages' models), Hubs, Links,
  Satellites, snapshot controls, PITs, reference tables and groups;
- the models' folders and settings, the project's `dbt_project.yml` and packages, and the suggested project
  settings (item 19);
- generating back into the dbt project (item 21), with a round trip test that runs in CI (item 20).

The user guide is `docs/02_getting-started/06_dbt-project-import.md`.

### API

```python
from engine.services.imports import DbtSource, ImportOptions, import_metadata

report = import_metadata(
    project=project,
    source=DbtSource(
        path=upload_dir / "manifest.json",      # or a dbt project folder
        catalog=upload_dir / "catalog.json",    # optional
        dbt_project=upload_dir / "dbt_project.yml",  # optional
        packages=upload_dir / "packages.yml",   # optional: or dependencies.yml / package-lock.yml
        import_descriptions=True,
        import_tags=True,
    ),
    options=ImportOptions(conflict_strategy="merge", dry_run=True),
    runtime_config=project_settings,  # EngineRuntimeConfig built from Studio's settings
)
```

- **`runtime_config` (new, all imports):** pass the project's settings, as for generation. Their naming patterns
  name the hash keys and hash diffs, and a dbt import stores a model's name only where it differs from what the
  patterns give (spec D22). Without it the Engine reads the project's `config.yml`, which Studio projects don't
  have, so the Engine's default patterns would apply.

- Files named `catalog.json`, `dbt_project.yml`, `packages.yml` beside an uploaded `manifest.json` are found
  without passing them (a manifest in `target/` also finds the project files one level up); explicit paths
  win.
- `IssueLocation` gained `node_id` (the dbt unique id, e.g. `model.shop.hub_customer`) and `parameter` (the
  macro parameter); `file` holds the model's file path.
- Parse-stage issues (codes in `engine/services/imports/codes.md`, "dbt project import"):
  `dbt.artifacts_located` (info: what was found), `dbt.catalog_missing` (warning), `dbt.project_file_missing`
  (warning), `dbt.packages_missing` (info), `dbt.resource_not_imported` (info, per resource type with its
  count), and the aborting errors `dbt.manifest_missing`, `dbt.unsupported_manifest_version`,
  `dbt.artifact_too_large`, `dbt.nothing_to_import` (a project mapping to no entity imports nothing; above all,
  `replace_all` can't empty a project).
- Mapping issues (same file, "Mapping the models"), each on a model's `node_id`, file and parameter:
  `dbt.model_render_failed`, `dbt.macro_unsupported`, `dbt.value_invalid`, `dbt.value_unresolved`,
  `dbt.parameter_ignored`, `dbt.parameter_given_twice`, `dbt.parameter_unsupported`,
  `dbt.reference_unresolved`, `dbt.link_hub_ambiguous`, `dbt.hash_inputs_differ`, `dbt.column_unknown`,
  `dbt.prestage_maintained_in_dbt`, `dbt.setting_suggested` (item 19), `dbt.model_not_mapped`, and
  `entity.depends_on_skipped` for entities left out because one they need is. Suggested grouping in the review
  step: errors (skipped models), warnings (imported differently), infos (models staying in the dbt project).
- Entities that can't be mapped are planned as `skip` with a reason (`missing_source_table`,
  `missing_reference`, `missing_parent`, `depends_on_skipped`, `invalid_configuration`); `replace_all` keeps the
  project's copy of them. With `error_strategy="fail_fast"`, any mapping error stops the import before anything
  is written.
- **What the mapping produces** (relevant for the review screen):
  - A stage reading a dbt source becomes that source table; its system is the dbt source (dbt sources sharing
    a schema become one system, with a warning). Record source and load date are set on the system when all its
    tables share them, and not stored at all when they equal what the project's defaults give.
  - A stage reading a model, seed or snapshot creates a pre-stage (table type `prestage`) whose stored
    `prestage` model name is that model. Several stages reading one model get one pre-stage each, all naming the
    same model.
  - Stage derived columns become derived columns of the table; Hub, Link and Satellite columns map to them, to
    prejoined columns or to source columns, matched by name.
  - Effectivity and record-tracking satellites set their Hub's or Link's flags and options.
  - Snapshot controls come with their logic rules (one per logic column and component), PITs and reference
    tables with their snapshot control and trigger column. The plan lists `snapshot_control` entities (item 13).
  - Groups come from TurboVault's folder structure and the models' tags (spec §7.6), else from the project's
    subject folders (`models/rdv/<subject>/`, item 19).
  - A model's name is stored as a `ModelOutput` only where it differs from the naming patterns; so are its
    folder and settings (materialization, schema, alias, tags, further config keys), only where they differ
    from what TurboVault generates (spec §9.1, as implemented).
- **Suggested project settings (new, `ImportReport.project_settings`, `ProjectSettings`):** the import reports,
  without applying them, the project settings the dbt project suggests: naming patterns, schemas, folders,
  defaults, its `dbt_project.yml` and packages. Shape, keys and flow: item 19.

Imports an existing datavault4dbt project from its dbt artifacts. The Engine never runs dbt or connects to the
warehouse.

- **Inputs:**
  - `manifest.json` (required, schema v12).
  - `catalog.json`, `dbt_project.yml`, `packages.yml` / `dependencies.yml` / `package-lock.yml`
    (optional).
  - Or a local dbt project folder (CLI and local use): the Engine finds the files in it and reports each as
    found or missing. A missing catalog or `dbt_project.yml` is a warning. Studio uploads the files.
  - Never `profiles.yml`.
- **Folder-level settings (spec D20):** with `dbt_project.yml` uploaded, each imported model keeps only the
  settings that differ from the original project's folder-level configuration (the `models:` block of its
  `dbt_project.yml`). That block comes back with the import as the project setting `dbt_project_models`
  (planned runtime config field). Studio either passes it on to generation, which writes it into
  `dbt_project.yml`, or puts it into the project's manual `dbt_project.yml`. Without `dbt_project.yml`, each
  model stores its effective settings.
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

**Status:** In progress (dbt import branch). Engine docs: domain model §10, generation pipeline ("Model
names, folders and settings"), validation rules, project schema (naming patterns).

Every generated dbt model can keep its own name, folder, alias, schema, database, materialization, tags and
further `config()` keys. The dbt import (item 4) fills them from the original project; Studio users can edit
them. Empty means "as TurboVault derives it", and a project without stored values generates exactly as
before (verified byte for byte on the TPC-H sample).

### Data model: `ModelOutput` (new table `model_output`, migration `0021_model_outputs`)

One row per entity and kind of model, only where something differs from the defaults.

| `kind` | Entity field | Name derived from (when `model_name` is empty) |
|--------|--------------|------------------------------------------------|
| `stage` | `source_table` | project pattern `stage_naming` (new) |
| `prestage` | `source_table` | project pattern `prestage_naming` (new); the name of the dbt project's model the stage reads |
| `hub` | `hub` | the hub's physical name (`model_name` not allowed) |
| `effectivity_satellite` | `hub` | `effectivity_satellite_naming` |
| `record_tracking_satellite` | `hub` or `link` | `record_tracking_satellite_naming` |
| `link` | `link` | the link's physical name (`model_name` not allowed) |
| `satellite_v0`, `satellite_v1` | `satellite` | `satellite_v0_naming`, `satellite_v1_naming` |
| `pit` | `pit` | the PIT's physical name (`model_name` not allowed) |
| `reference_table` | `reference_table` | its physical name (`model_name` not allowed) |
| `snapshot_control_v0`, `snapshot_control_v1` | `snapshot_control` | `<name>_v0`, `<name>_v1` |

| Field | Type | Notes |
|-------|------|-------|
| `project` | FK | Set from the entity on save; read-only in forms. |
| `kind` | choice | Labels: "Stage", "Pre-stage", "Hub", "Link", "Satellite (v0)", "Satellite (v1 view)", "Effectivity satellite", "Record-tracking satellite", "PIT", "Reference table", "Snapshot control table (v0)", "Snapshot control logic (v1)". |
| `source_table` / `hub` / `link` / `satellite` / `pit` / `reference_table` / `snapshot_control` | FK, nullable | Exactly one is set (database check constraint `model_output_one_entity`); unique per entity and `kind`. |
| `model_name` | text, nullable | The model's (and file's) name. |
| `folder` | text, nullable | Relative to the dbt project, e.g. `models/raw_vault/hubs`; stored with `/` and without outer slashes. |
| `alias`, `schema_name`, `database_name`, `materialized` | text, nullable | `config(alias=…, schema=…, database=…, materialized=…)`. |
| `tags` | JSON list of strings, nullable | The model's own tags, **added** to TurboVault's default tags (spec D26; was "replace"). The project setting `add_default_tags` (item 17) turns the default tags off. |
| `config` | JSON object, nullable | Further `config()` keys written as they are, e.g. `unique_key`, `post_hook`, `on_schema_change`. |

`ModelOutput.clean()` messages (show them on the field):

- `kind`: "A Satellite (v0) model belongs to a satellite, not a hub." · "A pre-stage's model belongs to the dbt
  project: only its name is stored."
- `model_name`: "A Hub model is named by its physical name: rename the entity instead." · "'stg customer'
  can't name a dbt model: use letters, digits and underscores, without spaces, dots or slashes" · "Another
  model of the project is named 'x'."
- `folder`: "Folder '/models' must be relative to the dbt project" · "Folder '../x' must stay inside the dbt
  project (no '..' or '.')"
- `tags`: "Tags are a list of strings." · `config`: "Set 'schema' in its own field (schema_name), not in
  config." (also for `materialized`, `alias`, `database`, `tags`).

Helpers: `engine.models.model_output.model_name_error(name)`, `folder_error(folder)`,
`normalize_folder(folder)` return the same checks for live form validation.

### Generation

- **Names everywhere.** Every reference follows the resolved names: stages in hubs, links and satellites, a
  v0 table in its v1 view, satellites and the snapshot control in a PIT, v1 views in a reference table, a
  pre-stage in its stage. This also fixes custom `satellite_v0_naming`/`satellite_v1_naming` patterns, which
  the templates ignored before (they appended `_v0`/`_v1`).
- **Folders.** A model goes to its stored folder, else its layer folder. A satellite's v1 view without a
  folder follows its v0 table, effectivity and record-tracking satellites their parent, a snapshot control's
  v1 its v0. A model whose folder lies outside its layer's folder gets the layer's `materialized` and `schema`
  in its own `config()` (dbt_project.yml only configures the layer folders). A folder outside `models/` adds
  its top folder to `model-paths`.
- **`config()`.** Stored settings override the template defaults: `materialized`, `alias`, `schema`,
  `database`, `tags`, then the further keys. Example with `alias`, `schema_name`, `tags`, `config` stored:

  ```
  {{ config(
      alias='customer_hub',
      schema='raw',
      tags=['crm', 'core'],
      unique_key='hk_customer_h'
  ) }}
  ```
- **Option** `GenerationOptions.use_model_folders` (default `true`): `false` writes every model to its layer
  folder (names and settings stay). Suggested as a toggle "Use the stored folders" in the generate dialog.
- **New runtime config** (`EngineRuntimeConfig`, CLI `config.yml`): `stage_naming` (default
  `stg__[[ source_system ]]__[[ source_table ]]`) and `prestage_naming` (default
  `pstg__[[ source_system ]]__[[ source_table ]]`). `[[ source_system ]]` is the source system's dbt name
  (lowercase, spaces as `_`), `[[ source_table ]]` the physical table name in lowercase.
- **Export (JSON):** definitions carry the resolved models (derived, not read back by the JSON import):
  `stages[].output`, `hubs[].output` / `effectivity_satellite_output` / `record_tracking_satellite_output`,
  `links[].output` / `record_tracking_satellite_output`, `satellites[].v0_output` / `v1_output`,
  `pits[].output` and `satellite_models`, `reference_tables[].output` and `satellites[].model_name`,
  `snapshot_controls[].v0_output` / `v1_output`. Each output: `model_name`, `folder`, `alias`, `schema_name`,
  `database_name`, `materialized`, `tags`, `config`. (Round-tripping the stored rows through the JSON format
  comes with the dbt import's domain model, Phase 4.)

### Templates

- SQL templates write the block with `[[ model_config(materialized=materialization, tags=[...]) ]]`, YAML
  templates the tags with `[[ model_tags([...]) ]]`. The bundled `satellite_v1` templates use `v0_name` /
  `v1_name`, `pit` uses `satellite_models`, `reference_table` uses `sat.model_name`.
- `model_config` and `model_tags` are also globals of the template environment that write the defaults, so
  rendering a template outside generation still works.
- **Model preview (entity detail pages).** The preview must show what generation writes. Preferred: run the
  pipeline for the entity, `generate(project=…, output_type="dbt", output_path=None,
  options=GenerationOptions(dry_run=True, return_content=True, entity_selection=EntitySelection(…)))`, and
  show the artifacts' `content`: stored names, folders (`path`), `config()` settings and every reference are
  applied. If Studio renders the templates itself instead, it must pass the model's context,
  `**ModelConfig(output, layer).context()` from `engine.services.generation.model_config` (with the
  entity's output from the export, e.g. `HubDefinition.output`), plus `v0_name`/`v1_name` for v1 views; else
  the preview shows the defaults while generation writes the stored settings.
- Workspace copies of the templates made before this change keep working while nothing is stored. When a
  model has stored settings or names they ignore, generation reports `render.template_outdated` (warning)
  on the model. **Studio:** if Studio keeps its own template copies, update them from the bundled ones.

### Issues to show

| Code | Severity | Meaning | Suggested UI |
|------|----------|---------|--------------|
| `validate.model.duplicate_name` | error | Two models share a name (case-insensitive; pre-stages count). The message names both entities. | Show on the model name field |
| `validate.model.invalid_name` | error | A name would leave the project folder (slashes, `..`); nothing is written for it | Show on the name |
| `validate.model.invalid_folder` | error | A folder leaves the project; nothing is written for it | Show on the folder field |
| `render.template_outdated` | warning | See above and item 3 | Link to the template editor |

### Suggested UI

- A "dbt models" section on the source table, Hub, Link, Satellite, PIT, reference table and snapshot control
  forms: one row per kind of model the entity has, showing the resolved name (placeholder: the derived one)
  and editable name, folder, alias, schema, database, materialization, tags and extra config (key/value).
- Project settings: naming pattern fields for stages and pre-stages, with a preview of a resulting name.
- A pre-stage shows only the model name.
- The Django admin of the Engine has the same inlines, for reference.

---

## 6. Hash diff name and alias

**Status:** In progress (dbt import branch), migration `0022_satellite_and_stage_options`. Engine docs:
domain model §7.1.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `Satellite.hashdiff_name` | text, nullable | empty | The stage's hash diff column. Empty: the project's `hashdiff_naming` pattern (placeholder: the derived name, e.g. `hd_CUSTOMER_S`). |
| `Satellite.hashdiff_alias` | text, nullable | empty | The column's name inside the Satellite when it differs, e.g. a uniform `hashdiff` in every Satellite. |

- Generation: the stage's `hashed_columns` uses the name; the v0 model writes
  `src_hashdiff: {source_column: <name>, alias: <alias>}` when an alias is set; the v1 view reads the alias.
- `Satellite.clean()`: a non-historized Satellite can't have either ("A non-historized satellite has no hash
  diff: clear the hash diff name and alias.").
- New issue `validate.stage.duplicate_hashdiff` (error): two Satellites of one stage share a hash diff name
  but hash different columns. Show on the hash diff name.
- **Studio:** two optional fields on the Satellite form (hidden for non-historized Satellites).

---

## 7. Stage options and missing columns

**Status:** In progress (dbt import branch), migration `0022_satellite_and_stage_options`. Engine docs:
domain model §3.1–3.3, project schema.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `EngineRuntimeConfig.include_source_columns` / CLI `configuration.include_source_columns` | bool | `true` | Project default. |
| `EngineRuntimeConfig.enable_ghost_records` / CLI `configuration.enable_ghost_records` | bool | `true` | Project default. |
| `SourceSystem.include_source_columns`, `SourceSystem.enable_ghost_records` | bool, nullable | empty | Empty: the project's. |
| `SourceTable.include_source_columns`, `SourceTable.enable_ghost_records` | bool, nullable | empty | Empty: the system's, then the project's. |
| `SourceTable.sequence_column` | text, nullable | empty | datavault4dbt `sequence`. |
| `SourceColumn.is_missing` | bool | `false` | The source no longer has the column. |

- Generation writes an option only where it differs from datavault4dbt's default (`true`), so nothing changes
  for projects that set nothing. A missing column goes to the stage's `missing_columns` (name: data type) and
  stays mappable; `sources.yml` leaves it out.
- **Studio:** project settings for the two defaults; tri-state controls (inherit / on / off) on the source
  system and source table forms, plus the sequence column; a "missing in source" toggle on columns, which
  keeps the column's data type editable (the stage needs it).

---

## 8. Derived columns that shadow a source column

**Status:** In progress (dbt import branch). Breaking change to derived columns (unreleased).

- A derived column may take the name of a source column of its table (case-insensitive): it **shadows** it.
  datavault4dbt's stage replaces the source column with the derived value. Property
  `DerivedColumn.shadowed_column` returns the source column it replaces.
- `DerivedColumn.clean()` now only rejects a prejoined column's name ("'X' is a column a prejoin brings into
  CUSTOMER's stage.").
- Everything that maps the shadowed source column reads the derived value. A Hub or Link transformation of it
  builds on the derived value (`UPPER((TRIM(C_NAME)))`) instead of conflicting (planned validation dropped).
- JSON import: a table may list a source column and a derived column of the same name; both are created.
- **Studio:** drop the client-side "name already used" check for source columns (keep it for prejoined
  columns); in column pickers, show a shadowed source column as "replaced by derived column"; a mapping of
  either reads the derived value.

---

## 9. Satellite v1 options

**Status:** In progress (dbt import branch), migration `0022_satellite_and_stage_options`. Engine docs:
domain model §7.1.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `Satellite.create_v1_view` | bool, nullable | empty | Whether the Satellite gets a v1 view. Empty: the project's `generate_satellite_v1_views` (generation option). Standard, multi-active and reference Satellites only. |
| `Satellite.v1_ledts_alias` | text, nullable | empty | The view's load end date column. Empty: datavault4dbt's `ledts_alias` variable. |
| `Satellite.v1_add_is_current_flag` | bool | `true` | As always generated. |
| `Satellite.v1_include_payload` | bool | `true` | Standard Satellites only. |

- New export helper `SatelliteDefinition.gets_v1_view(project_default)`; the plan, validation and SQLMesh output
  use it too (the plan now also counts the v1 views of reference Satellites, which it missed before).
- New issue `validate.reference_table.satellite_without_v1` (warning): a reference table reads a Satellite
  without a v1 view.
- **Studio:** a "v1 view" section on the Satellite form (tri-state "v1 view: project default / on / off").

---

## 10. Hub, Link, PIT and snapshot control options; delivery method

**Status:** In progress (dbt import branch), migration `0023_hub_link_pit_snapshot_options`. Engine docs:
domain model §3.1–3.2 (delivery method), §4.1, §4.3, §5.1, §8.1, §8.3, §9.1; project schema.

### New fields

| Model / field | Type | Default | Notes |
|---------------|------|---------|-------|
| `Hub.disable_hwm`, `Link.disable_hwm`, `Satellite.disable_hwm` | bool | `false` | Load without the high-water mark (every run reads all of the stage). Not for non-historized Satellites. |
| `Hub.effectivity_is_active_alias`, `Link.effectivity_is_active_alias` | text, nullable | empty | Name of the effectivity Satellite's `is_active` column. |
| `Hub.effectivity_disable_hwm`, `Link.effectivity_disable_hwm` | bool | `false` | For the effectivity Satellite. |
| `Hub.effectivity_additional_columns`, `Link.effectivity_additional_columns` | JSON list, nullable | empty | Further stage columns the effectivity Satellite carries. |
| `Link.create_effectivity_satellite` | bool | `false` | **New: effectivity Satellites on Links.** Tracks the Link's hash key in its first source's stage; named by `effectivity_satellite_naming` (`order_customer_es`); `ModelOutput` kind `effectivity_satellite` now also on Links. |
| `Link.union_strategy` | choice `all` / `distinct`, nullable | empty | Non-historized Links only (datavault4dbt default `all`). |
| `HubSourceMapping.stage_hashkey_name` | text, nullable | empty | **Role-playing:** the stage's hash key this mapping loads, when it isn't the Hub's. Mappings of one table with different hash keys become separate sources of the Hub (`source_models` entries with `hk_column`); the stage computes each hash key. Example: the user Hub loaded from a commits stage twice, as `hk_author_h` (author_id) and `hk_committer_h` (committer_id). |
| `SourceSystem.delivery_method`, `SourceTable.delivery_method` | choice `single_batch` / `multi_batch`, nullable | empty | Inherits table → system → project. See below. |
| `PIT.use_snapshot_optimization` | **now nullable** | empty (was `true`) | Written only when set (datavault4dbt `snapshot_optimization`, default off). **Migration 0023 empties all existing values**: they were never written, so generation stays the same. |
| `PIT.custom_record_source` | text | — | Existing field, **now written** as `custom_rsrc`. |
| `SnapshotControlTable.snapshot_end_date` | **now nullable** | empty (was end of current year + 5) | Empty: the snapshot range runs up to the current date (datavault4dbt's default). When set, written as `end_date`: the snapshot table then holds dates up to that day, including future ones. **Migration 0023 empties all existing values**: they were never written, and writing the old default would add five years of future snapshots to every PIT. New snapshot controls (CLI defaults, import defaults) get none. |
| `SnapshotControlTable.sdts_alias` | text, nullable | empty | Name of the snapshot date column. |

### Generation changes

- Hub and Link **additional columns** (`HubColumn` / `LinkColumn` of type `additional_column`, which existed
  but were never generated) are now written as `additional_columns`. The stage provides them under the
  column's name: a mapping from a differently named stage column becomes a renaming derived column.
  datavault4dbt needs each additional column in every source stage of the Hub/Link.
- **Snapshot-based reference tables** were generated as `historized: 'latest'` (a bug); they now write
  `historized: 'snapshot'`, `snapshot_relation` (the snapshot control's v1 model) and
  `snapshot_trigger_column` (the logic column).
- Everything else is written only when set; projects that set nothing generate exactly as before.

### Delivery method (issue #468)

| Setting | Where | Default |
|---------|-------|---------|
| `use_delivery_method` | `EngineRuntimeConfig` / CLI `configuration` | `false` |
| `delivery_method` | `EngineRuntimeConfig` / CLI `configuration` (project default) | `multi_batch` |
| `delivery_method` | source system, source table | inherit |

With the switch on, models loading only single-batch data write `source_is_single_batch: true`: standard,
multi-active, non-historized and reference Satellites (from their stage), non-historized Links (only when every
source stage is single-batch), effectivity Satellites (from the stage they read; they always write the
parameter, `false` otherwise). With the switch off nothing changes.

### Suggested UI

- Hub/Link forms: "Loading" section (`disable_hwm`; Links: union strategy for non-historized Links) and an
  "Effectivity satellite" section (create, `is_active` column name, high-water mark, additional columns).
- Hub source mappings: an optional "stage hash key" per mapping, shown as a role ("loads the Hub as
  hk_author_h").
- Satellite form: `disable_hwm` (hidden for non-historized).
- Source system/table forms: delivery method (inherit / single batch / multi batch); project settings: the
  switch and the default.
- PIT form: snapshot optimization as tri-state (default / on / off); custom record source.
- Snapshot control form: optional end date ("empty: up to today"), snapshot date column name.

---

## 11. Custom models

**Status:** Postponed (spec D19): not part of the dbt import pull request. Optional on import.

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

---

## 13. JSON export and import of the new settings; snapshot controls

**Status:** In progress (dbt import branch). Engine docs: JSON import ("Options and settings", "Model
settings", "Snapshot controls").

A JSON export now restores everything items 5–10 added, and its snapshot controls. Exporting a project and
importing the file into an empty project gives the same stored values; importing it into the project itself
changes nothing.

### Export format

- **`model_outputs`** (new) on source tables, hubs, links, satellites, PITs, reference tables and snapshot
  controls: the stored settings of the entity's models by kind (`stage`, `hub`, `satellite_v1`, ...), each with
  the `ModelOutput` fields (`model_name`, `folder`, `alias`, `schema_name`, `database_name`, `materialized`,
  `tags`, `config`), all nullable. Models without stored values are left out, so most entities have `{}`.
- The resolved models (`output`, `v0_output`, `v1_output`, `effectivity_satellite_output`, ...) stay as they
  are. They are what generation uses and are not read back.

### Import rules

- A field the file has is restored, an empty value included: `"sequence_column": null` clears the table's
  sequence column, `"create_v1_view": null` makes the satellite follow the project's setting. A field the file
  doesn't have (an export from an older Engine) leaves the project's value alone. This covers the stage
  options and delivery method of systems and tables, `is_missing`, the hub source's `hk_column` (stored as the
  mapping's `stage_hashkey_name`), the hub/link/satellite high-water mark and effectivity options, the link's
  `union_strategy`, the satellite's hash diff alias and v1 options, the PIT's `use_snapshot_optimization` and
  `include_business_objects_before_appearance`, and the snapshot control's `sdts_alias` and end date.
- An entity gets exactly the `model_outputs` the file lists: a kind the file leaves out is removed. A stored
  setting that fails `ModelOutput.clean()` (bad name or folder, a name another model has) is reported as
  `entity.invalid_configuration`, with the `clean()` message, and not stored; the entity is still imported.
- `hashdiff_name` in the export is the generated hash diff column. The import stores it on the satellite only
  where it differs from the importing project's `hashdiff_naming` pattern.
- The PIT's `custom_record_source` is now read (a JSON import used to clear it).

### Snapshot controls

- Before, a JSON import never stored the export's snapshot controls (PITs got a new control with default
  dates instead). Now they are created and updated, with dates, daily time, `sdts_alias`, logic patterns and
  `model_outputs`, before the reference tables and PITs.
- Matched by base name: `control_snap`, `control_snap_v0` and `control_snap_v1` are one control; an existing
  control keeps its name. Logic patterns are added and updated, never removed. Snapshot controls are never
  deleted, not even by `replace_all`, since PITs and reference tables may read them.
- PITs and reference tables find their control by its v1 model name, also when `model_outputs` renamed it.
  Snapshot-based reference tables now get their snapshot control and logic set on import (they had none).
- **Plan:** a new entity type `snapshot_control` (`create`, `update`, `unchanged`, or `skip` with
  `skip_snapshots` / `update_only`). Change paths: the control's own fields (`snapshot_start_date`,
  `snapshot_end_date`, `daily_snapshot_time`, `sdts_alias`), `logic_rules.<column>` (added) and
  `logic_rules.<column>.<field>` (changed).
- Change paths for model outputs on every entity: `model_outputs.<kind>` (added or removed) and
  `model_outputs.<kind>.<field>` (changed).
- `project init` from a JSON export creates no default snapshot controls and now imports the export's
  controls and PITs. Before, it ran the import with `skip_snapshots`, which left every PIT out.

### Studio

- If Studio shows the import plan by entity type, add `snapshot_control` ("Snapshot control").
- If Studio builds or edits JSON exports itself, carry `model_outputs` through unchanged.

---

## 14. Links select their dependent child keys

**Status:** In progress (dbt import branch). Spec D23. Changes generated output.

datavault4dbt has no dependent child key concept: a link lists such keys in `foreign_hashkeys` after the hub
hash keys, as plain columns, and the link hash key hashes them. TurboVault hashed a link's dependent child keys
into the link hash key but didn't select them, so the link table lacked the columns.

- Generated links (`link`, `nh_link`) now write each dependent child key into `foreign_hashkeys` after the hub
  hash keys, and their YAML describes it ("Dependent child key" unless the column has a description). The link
  hash key is unchanged.
- A dependent child key named differently from its stage column (e.g. link column `DCK_COMMENT` mapped from
  `O_COMMENT`) gets a renaming derived column in the stage, so the link can select it by its name.
- The export's `LinkDefinition` gained `dependent_child_keys` (names, in order); `foreign_hashkeys` still holds
  the hub hash keys only (the SQLMesh output is unchanged).
- A workspace's copy of a link template from before this change doesn't write them: generation warns with
  `TPL_003` for links that have dependent child keys.
- **Studio:** if the template editor lists variables, add `dependent_child_keys`. Projects with dependent child
  keys get new link columns on their next generation (the TPC-H sample: `LINEITEM_NL`, `ORDERS_CUSTOMERS_L`);
  incremental links need a full refresh or a schema change to add them.

---

## 15. Snapshot control logic as datavault4dbt reads it

**Status:** In progress (dbt import branch). Spec D24. Changes generated output; fixes snapshot controls that
datavault4dbt partly ignored.

datavault4dbt's `control_snap_v1` reads `log_logic` intervals: `daily`, `weekly`, `monthly`, `yearly` (computed
from the snapshot's day and the beginning of its week, month and year). TurboVault wrote its component names
(`beginning_of_month`, `end_of_week`, ...) as keys, which datavault4dbt ignores: only `daily` took effect, and a
control without a daily rule produced an invalid model.

- **Generation:** `daily` → `daily`, `beginning_of_week` → `weekly`, `beginning_of_month` → `monthly`,
  `beginning_of_year` → `yearly`. Logic rules are grouped by their column name: one column named like the
  `datavault4dbt.snapshot_trigger_column` variable (default `is_active`) is written as a mapping, several columns
  as a list of `{column: {...}}` entries (datavault4dbt 1.18 reads lists, 1.0 doesn't). The v1 model's YAML
  lists each logic column once and names the snapshot date column after `sdts_alias`.
- **Components without an interval** (end of week, month, year; beginning and end of quarter) and a second rule
  with the same interval in one column are left out with the generation warning `SNAP_002` (entity type
  `snapshot_control`, the control's name).
- A workspace copy of the `snapshot_control_v1` template that still writes component names gets `TPL_003`.
  New template variables: `log_logic_columns` (list of `{name, intervals: [{name, duration, unit, forever}]}`)
  and `log_logic_mapping` (bool).
- **Default snapshot control** (new projects, and the import's fallback for PITs): one `is_active` column with
  daily snapshots for 3 months, weekly for 1 year, monthly for 5 years and yearly forever. It was five columns
  (`snap_daily` ... `snap_yearly`) of end-of-period components. Stored controls aren't changed.
- **Studio:** in the logic editor, offer (or mark as generated) only `daily`, beginning of week, beginning of
  month and beginning of year, at most once per column; explain that rules sharing a column name form one logic
  column, and that PITs pick a column by its name (`snapshot_trigger_column`). Show `SNAP_002` warnings.

---

## 16. An imported dbt_project.yml comes back

**Status:** In progress (dbt import branch). Spec D20, D25. The import reports the settings in
`ImportReport.project_settings` (item 4); the CLI writes them into `config.yml` on request.

A project imported from a dbt project keeps that project's `dbt_project.yml`, and generation writes it back, so
the generated file matches the original in content (comments and formatting aside).

- **Runtime config (`EngineRuntimeConfig`), new fields:**
  - `dbt_project_models: dict` — the project's `models:` block without the project-name level (folder-level
    `+materialized`, `+schema`, `+tags`, hooks, nested folders).
  - `dbt_project_settings: dict` — every other top-level setting: `version`, the paths, `clean-targets`,
    `require-dbt-version`, `seeds:`, `snapshots:`, `on-run-start`/`on-run-end`, `dispatch`, `quoting`, other
    packages' `models:` entries (under `models`), ...
  - The imported project's `name`, `profile` and `vars` go to the existing `dbt_project_name`, `profile_name`
    and `global_vars`.
- **Generation:** `version`, paths and `clean-targets` replace the defaults; TurboVault's model paths are added to
  the imported `model-paths`; the `models:` block is the imported one with TurboVault's layer folders merged in
  (their `+schema`/`+materialized` win for those folders); other settings follow as they are. Without these
  fields, `dbt_project.yml` is unchanged.
- **Template:** `dbt_project.yml.j2` gained the variables `project_version`, `analysis_paths`, `test_paths`,
  `seed_paths`, `macro_paths`, `snapshot_paths`, `clean_targets`, `models_block` and `extra_block` (all
  optional; Studio's prefill rendering with the old variables still works). A workspace copy that doesn't write
  the imported settings gets `TPL_003`.
- **CLI:** `config.yml` keeps them under `dbt_project:` (`vars`, `models`, `settings`, and `packages`, item 19);
  `dbt_project.path` is now optional.
- **Studio:** store the two new settings with the project and pass them in the runtime config. Studio's manual
  `dbt_project.yml` overrides the generated file anyway; when a project has imported settings, consider
  prefilling the manual file from a generation with them, or showing them read-only.

---

## 17. Default tags setting

**Status:** In progress (dbt import branch). Spec D26.

- **New project setting `add_default_tags`** (runtime config, `config.yml` `configuration.add_default_tags`),
  default `true`: generated models carry TurboVault's default tags (`hub`, `raw_vault`, the group, ...). Off:
  they carry only their own tags (`ModelOutput.tags`), and a model without any has no tags.
- **`ModelOutput.tags` now adds** to the default tags instead of replacing them. A single model can no longer drop
  the default tags; the setting turns them off for every model. An empty list means the same as null.
- **dbt imports** store only the tags a model has beyond its folder's (imported `dbt_project.yml`) and, with the
  setting on, TurboVault's defaults. The import suggests turning the setting off (item 4, suggested project
  settings), so an imported project keeps exactly its models' tags; users can turn it on later.
- Workspace template copies that write fixed tags get `TPL_003` while the setting is off.
- **Studio:** a switch in the project settings ("Add TurboVault's default tags"); the tag field of a model's
  settings reads "Additional tags".

---

## 18. Folder structure; model folders setting; layers without schema

**Status:** In progress (dbt import branch). Spec D27. The defaults generate exactly the files they did.

### Folder patterns (new project setting)

- **Runtime config `folders: dict[str, str]`** (`config.yml` `configuration.folders`): a folder pattern per layer
  (`control`, `sources`, `prestaging`, `staging`, `raw_vault`, `business_vault`) and, optionally, per kind of
  model (`stage`, `hub`, `link`, `satellite`, `satellite_v1`, `effectivity_satellite`,
  `record_tracking_satellite`, `reference_table`, `pit`, `snapshot_control`). Unset keys keep TurboVault's layout:
  `models/00_control`, `models/10_sources`, `models/15_prestaging`, `models/20_staging/[[ source_system ]]`,
  `models/30_raw_vault/[[ group ]]`, `models/40_business_vault`, and `models/40_business_vault/pits/[[ group ]]`
  for PITs. A kind without a pattern uses its layer's; v1 views, effectivity and record-tracking satellites
  follow their v0 or parent unless they have their own.
- **Placeholders:** `[[ group ]]` (lowercase, spaces/dashes as `_`), `[[ group_name ]]` (as named),
  `[[ source_system ]]`, `[[ source_system_name ]]`. A folder whose placeholder has no value is left out (no
  group: the layer's folder). The source system is a stage's table's. For other models it comes from the
  tables they load (a hub's primary source tables, a link's source tables, a satellite's table); PITs, reference
  tables, effectivity and record-tracking satellites take their hub's or link's. Several systems: the most common
  one, then the first by name (`folder_config.main_source_system`). Only the default stage pattern uses it.
- **Validation** (`engine.services.generation.folder_config.folder_pattern_error(pattern)`, and
  `FOLDER_KEYS`): known keys and placeholders, relative, no `..`, at least a model path and a folder. Messages:
  "Unknown folders: ...", "Folder pattern '...' uses unknown placeholders: ...", "... must be relative to the
  dbt project", "... must stay inside the dbt project", "... needs a model path and a folder (e.g.
  models/raw_vault)".
- **Generation:** `dbt_project.yml` configures each layer on its pattern's fixed part (nested keys for deeper
  folders), `model-paths` gains the patterns' top folders, and a model outside its layer's folder (or in one two
  layers share) carries its layer's settings in `config()`. Entity previews (Studio's model preview) aren't
  affected: they render the SQL/YAML only.
- **Studio:** a "Folder structure" section in the project settings: one input per layer with the default as
  placeholder text, and an "advanced" list for per-kind patterns; show the placeholders and validate live.

### Model folders (new project setting)

- **Runtime config `use_model_folders: bool`** (default `true`; `config.yml` `configuration.use_model_folders`):
  models with a stored folder (`ModelOutput.folder`, e.g. from a dbt import) go there. Off: every model goes to
  its folder pattern (TurboVault's structure) and keeps the settings its original folder gave it through an
  imported `dbt_project.yml` (written into its `config()` where they differ); `dbt_project.yml` then keeps only
  the imported settings for every model, not the imported folders'.
- `GenerationOptions.use_model_folders` is now `bool | None` (None: the project's setting; it was `True`).
- **Studio:** a switch "Use the models' own folders" (on by default), worth showing for imported projects.

### Layers without a custom schema

- `stage_schema`, `rdv_schema`, `bdv_schema`, `control_schema` may be **null** (runtime config `None`): no
  `+schema` for that layer, so its models build into the target's schema (dbt projects without custom schemas).
  An empty string still means TurboVault's default name. SQLMesh output uses the layer's name for such a layer.
- **Studio:** a "No custom schema" option per layer schema.

---

## 19. Project settings a dbt project suggests; packages

**Status:** In progress (dbt import branch). Spec D22, D28 (§8, §8.1). Replaces the first shape of
`ProjectSettings` on this branch (`naming`, `dbt_project_name`, ... fields): never released.

A dbt import infers the settings most of the project's models follow and copies the dbt project's own files. It
applies nothing: it suggests what differs from the project's settings, and stores on each entity only what
differs from the settings it was given.

### Report

- **`ImportReport.project_settings: ProjectSettings | None`** with `suggestions: dict[str, SettingSuggestion]`,
  keyed by `EngineRuntimeConfig` field; a dotted key sets one entry of a mapping field
  (`folders.raw_vault`, `model_materializations.pit`). `SettingSuggestion`: `value` (the field's value, may be
  `null`: e.g. `rdv_schema: null`, no custom schema), `matching` and `total` (how many models, names, tables or
  stages follow it; both `null` for a value copied from the dbt project's files).
- **Keys:** `hashkey_naming`, `hashdiff_naming`, `satellite_v0_naming`, `satellite_v1_naming`,
  `effectivity_satellite_naming`, `record_tracking_satellite_naming`, `stage_naming`, `prestage_naming`;
  `stage_schema`, `rdv_schema`, `bdv_schema`, `control_schema`; `staging_materialization`,
  `raw_vault_materialization`, `business_vault_materialization`, `control_materialization`,
  `model_materializations.<kind>`; `default_record_source_value`, `default_load_date_value`,
  `default_static_part_of_record_source`; `include_source_columns`, `enable_ghost_records`;
  `use_delivery_method`, `delivery_method`; `add_default_tags`; `folders.<layer or kind>` (item 18); copied:
  `dbt_project_name`, `profile_name`, `global_vars`, `dbt_project_models`, `dbt_project_settings` (item 16) and
  `dbt_packages` (below).
- **Issue:** one `dbt.setting_suggested` info per suggestion ("The dbt project suggests rdv_schema: 'edw' (5 of
  5 models follow it); the project's is 'rdv'"). Replaces `dbt.naming_inferred` and `dbt.project_setting`.
- **Applying:** `EngineRuntimeConfig.with_settings(values)` returns a copy with `{key: value}` applied (dotted
  keys too; an unknown key raises `ValueError`). The CLI writes them into `config.yml` with
  `engine.services.project_config.apply_settings(path, values)` (keeps everything else in the file; validates
  first) and `setting_location(key)` (where a key goes in `config.yml`).
- **Suggested flow (the CLI's):** a dry run with the project's runtime config; show the suggestions (setting,
  value, "n of m follow it" or "from the dbt project"), let the user pick; save the accepted ones in the
  project's settings; run the import with the new runtime config. Importing again then suggests nothing more,
  and entities store less: on the corpus, stored folders and schemas mostly drop to none.
- **`dbt_project_models` and the layer settings:** the suggested block keeps the layer blocks TurboVault
  wouldn't write with the project's current settings, so it is right whichever other suggestions are applied.
  Applied together with the folders and schemas, those layer blocks become redundant. The import compares the
  stored block without them, so it doesn't suggest a shorter block afterwards.

### What entities store now (relative to the settings in effect)

- A table's record source, load date and static part where they differ from what it inherits (the project's
  defaults with `[[ source_system ]]` / `[[ source_table ]]` filled in); the same values on all of a source
  system's tables go to the system.
- A table's delivery method where it differs from the project's `delivery_method` (with `single_batch` as the
  project's, multi-batch tables store `multi_batch`).
- Groups: a project without group tags or TurboVault's folders gets them from its subject folders (below
  `models/<layer>/`, folders holding several kinds of entity; `hubs/`, `satellites/`, ... are none).

### Packages (new project setting)

- **Runtime config `dbt_packages: list[dict]`** (`config.yml` `dbt_project.packages`): the dbt project's
  packages, as `packages.yml` lists them. A dbt import suggests them from `packages.yml` or `dependencies.yml`,
  else the pinned versions of `package-lock.yml`.
- **Generation** writes them into `packages.yml`, adding TurboVault's datavault4dbt entry when none of them is
  datavault4dbt (a premium package entry counts). Empty: `packages.yml` is TurboVault's own, unchanged.
- **Template:** `packages.yml.j2` gained the optional variable `packages_block`; a workspace copy that doesn't
  write the imported packages gets `TPL_003`.
- **Studio:** store the list with the project and pass it in the runtime config; a read-only list (or a YAML
  editor) in the project's dbt settings.

---

## 20. Round trip: what a dbt import reads back; generation fixes

**Status:** In progress (dbt import branch). Spec §12 (Phase 4c). A TurboVault project, generated, parsed by
dbt and imported, generates the same files again.

### What a dbt import does differently now

- **TurboVault's default descriptions aren't imported:** for example `Standard hub for CUSTOMER_H`, or
  `Source table from CRM`. Entities from a generated project get no description, so generation writes
  the defaults again. Real descriptions are imported as before.
- **A source system's spelling:** a generated `sources.yml` names a source in lowercase (`crm`), and its
  default table description keeps the system's name (`Source table from CRM`). The import names the system
  `CRM`.
- **Columns that differ in case only** (`C_NAME`, `C_name`; quoted identifiers) stay separate columns.
  Before, they merged into one.
- **A dependent child key renamed for its link (spec D23)** maps to the column the stage hashes, and the
  renaming derived column isn't imported (generation writes it again). Before, such a link was left out with
  `dbt.link_hub_ambiguous`.
- **Multi-active satellites** keep their keys' place among the columns, taken from the stage's hash diff.
  **Non-historized satellites** come in without delta detection, so the stage gets no hash diff for them.
- **Snapshot control logic columns** keep the spelling their YAML documents (`IS_ACTIVE`), and so do PITs
  reading them.
- **Logic rules are matched by column and component** (all imports, also JSON). A column with several
  intervals (daily, weekly, ...) used to keep only one rule after an import; it now keeps one per component.
  Rules are still never removed by an import.
- **A link column the link hash key hashes is a dependent child key**, also when `payload` lists it. It used to
  become two columns of one name, flipping between the two on every import.
- **Systems of pre-stages** (seeds, models reading no sources) are named by their stages and kept apart, each
  in a schema of its name. A system is where it lives, and dbt gives these none. A dbt source of the name moves
  the system to its own schema.
- **Re-importing the same artifacts changes nothing**, checked on real projects.
- **Suggested settings (item 19)** leave out what TurboVault writes anyway: its layer blocks in the
  `models:` block (compared with the project's current settings), the default paths and version in
  `dbt_project.yml`, and its own datavault4dbt entry in `packages.yml`.

### Generation changes

- **A stage's hash keys are ordered:** the hubs it loads, by name, then the hub keys its links reference,
  then the link keys. The database order used before changed between imports. Stages with several hash keys
  may change order once.
- **Each hash key once per stage:** hubs or links that name their hash keys alike used to make the stage list
  the key twice. That is a duplicate YAML key, and datavault4dbt kept the last. The stage now computes it
  once, for the first (hubs by name, then links by name). New validation warning
  `validate.stage.duplicate_hashkey` (legacy code `STG_006`) when they hash different columns: show it like
  `validate.stage.duplicate_hashdiff`. The TPC-H sample has one, on two of its test links.
- **A model with no settings gets no `config()` block.** dbt rejects an empty `{{ config() }}`, which such a
  model got with default tags off. `model_config()` now renders nothing for it.
- `[[ source_system ]]` / `[[ source_system_name ]]` work in every folder pattern (item 18).

---

## 21. Generating into an existing dbt project

**Status:** In progress (dbt import branch). Spec D17, §9.7.

Generating into an empty folder writes a complete dbt project, as before; Studio's generation into a temporary
folder for a ZIP download is unchanged. Generating into a folder that holds a dbt project whose
`dbt_project.yml` TurboVault didn't write behaves differently:

- **Kept project files:** TurboVault writes models, their YAML and source definitions, but not
  `dbt_project.yml`, `packages.yml` or `profiles.yml`.
- **Folder settings:** the project's folder settings apply. A model carries its layer's schema and
  materialization in `config()` where they give it none.
- **The report** lists what the models need from the project's files.

This is the way back for a project imported from a dbt project, and the only one when its stages read that
project's models (pre-stages).

- **The record:** every generated folder gets `.turbovault/generated.json`, listing the files TurboVault wrote
  and their checksums. ZIP downloads include it. Keep it: it lets a later generation into the unzipped folder
  tell TurboVault's own files apart and report the ones it no longer generates.
- **New options** (`GenerationOptions`):
  - `write_project_files: bool | None = None`: None is automatic, True always writes the project files,
    False never does.
  - `remove_stale_files: bool = False`: deletes the files generated before and no longer generated, if
    unchanged since.
- **Skipping sources:** use the existing runtime config `export_sources`.
- **New issue codes** (`engine/services/generation/codes.md`), with the severity to show:

  | Code | Severity |
  |------|----------|
  | `render.project_files_kept` | info |
  | `render.project_needs_package` | warning |
  | `render.project_needs_vars` | warning |
  | `write.stale_file` | warning |
  | `write.stale_file_removed` | info |
  | `write.stale_file_changed` | warning |
  | `write.files_replaced` | info |
  | `write.sources_kept` | info |
  | `write.model_defined_twice` | warning |
  | `write.source_defined_twice` | warning |

- **Studio:** nothing required for ZIP downloads. If Studio ever writes into a user's repository (e.g. a Git
  integration), pass `write_project_files=None` and show the issues above, and offer "remove files TurboVault
  no longer generates" as `remove_stale_files`.

