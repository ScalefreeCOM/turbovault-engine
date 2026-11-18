# Import Issue Codes

Every diagnostic produced by the import pipeline carries a stable
machine-readable `code`. The frontend uses these codes to localize and
deep-link errors; the CLI groups them in summary tables.

## Parse stage

| Code | Cause | Suggestion shown to user |
|------|-------|--------------------------|
| `source.unreadable` | The file cannot be opened (permissions, corruption). | Confirm the file exists and is not open in another program. |
| `source.unsupported_format` | The selected source type does not match the file format. | Re-select the correct source type or upload a matching file. |
| `source.empty` | The file contains no parsable content. | Confirm the file has the expected sheets/tables. |
| `source.invalid_json` | The JSON file is malformed or not a Turbovault export. | Re-export the project as JSON and re-upload. |

## dbt project import

| Code | Severity | Cause | Suggestion shown to user |
|------|----------|-------|--------------------------|
| `dbt.manifest_missing` | error (abort) | No `manifest.json` in the dbt project folder (`target/manifest.json` or `manifest.json`). | Run `dbt parse` (no warehouse connection needed) or pass the manifest's path. |
| `dbt.unsupported_manifest_version` | error (abort) | The manifest isn't schema v12 (dbt 1.8 or later, dbt Cloud, dbt Fusion). | Regenerate it with a current dbt version (`dbt parse`). |
| `dbt.artifact_too_large` | error (abort) | An artifact is larger than 512 MB. | — |
| `dbt.artifacts_located` | info | Which artifacts the import found (manifest, catalog, `dbt_project.yml`, package files). | — |
| `dbt.catalog_missing` | warning | No `catalog.json`: column data types come from the YAML properties only. | Run `dbt docs generate` (it queries the warehouse) and import again. |
| `dbt.project_file_missing` | warning | No `dbt_project.yml`: `var()` calls fall back to their defaults, its settings can't come back into the generated `dbt_project.yml`, and folder-level settings can't be told apart from a model's own (models store what differs from TurboVault's layer settings). | Pass the project's `dbt_project.yml`. |
| `dbt.packages_missing` | info | No package file: the datavault4dbt version is unknown, both argument formats are read. | — |
| `dbt.resource_not_imported` | info | Resources the import doesn't read, with their count (seeds, tests, dbt snapshots, analyses, exposures, ...). Seeds and snapshots stages read are pre-stages and counted apart. | — |
| `dbt.nothing_to_import` | error (abort) | No datavault4dbt model maps to TurboVault: nothing is planned (a `replace_all` never deletes everything because of an empty project). | Check that the project uses datavault4dbt macros. |

Mapping the models. Each issue locates the model by its dbt node id
(`location.node_id`), its file and the macro parameter concerned; an entity
left out is planned as a skip, so `replace_all` keeps the project's copy.

| Code | Severity | Cause | Suggestion shown to user |
|------|----------|-------|--------------------------|
| `dbt.model_render_failed` | error (model skipped) | A model that calls a Data Vault package can't be rendered. | Check that the model's Jinja parses with dbt; macros of other packages and `var()` calls without a value are the usual causes. |
| `dbt.macro_unsupported` | error (model skipped) | A Data Vault macro the import doesn't map (`xts`, other packages' macros). | — (the model stays in the dbt project) |
| `dbt.value_invalid` | error / warning | A metadata block that isn't valid YAML, or a parameter of the wrong shape (e.g. `source_model` naming nothing). The model or the value is left out. | Fix the model's metadata. |
| `dbt.value_unresolved` | warning | A parameter depends on a value the import can't know: `var()` without a value, `env_var()`, an unknown function. | Pass `dbt_project.yml` for the `vars`. |
| `dbt.parameter_ignored` | info | A parameter the macro doesn't know (also YAML lines that are SQL comments); datavault4dbt ignores it too. | — |
| `dbt.parameter_given_twice` | info | A parameter given in `yaml_metadata` and separately: the `yaml_metadata` value applies, as in datavault4dbt. | — |
| `dbt.parameter_unsupported` | warning (error where the model is skipped; info for a column the link hash key hashes beyond the Hubs' keys without `foreign_hashkeys` listing it, which becomes a dependent child key the generated link selects) | Something TurboVault generates differently, imported leniently: a source `identifier`, several dbt sources on one schema, several `rsrc_static` patterns, a per-source `link_hk`, an effectivity or record-tracking satellite reading other stages than TurboVault uses. A stage reading a source another stage reads is skipped. | Read the warning: it names what the generated model does. |
| `dbt.reference_unresolved` | error (entity skipped) | An entity loads from a stage, or hangs on a hash key, that isn't imported or isn't in the manifest. | Check the model's `source_model(s)` / `parent_hashkey`. |
| `dbt.link_hub_ambiguous` | error (link skipped) | A link's foreign hash key matches no imported Hub, or several. An aliased key is matched by the Hubs a stage loads under it, the Hub it names, or the one Hub the link already references. | Name the foreign hash key like the Hub's hash key, or import the Hub. |
| `dbt.hash_inputs_differ` | warning | A stage computes a hash key from other columns than the business keys the Hub or Link maps; TurboVault computes it from the mapped keys. | Check the stage's `hashed_columns`. |
| `dbt.column_unknown` | warning | Columns a model uses that neither the catalog nor the YAML describe: created without a data type (one issue per table). | Provide `catalog.json`, or describe the columns in YAML. |
| `dbt.prestage_maintained_in_dbt` | warning | A stage reads a model, seed, dbt snapshot or another package's model (the message says which): it becomes a pre-stage whose model stays in the dbt project, so the project must be generated into that dbt project. | — |
| `dbt.setting_suggested` | info | The dbt project suggests a project setting that differs from the project's (one issue each): a value most of its models follow (naming patterns, layer schemas and materializations, the tables' default record source, load date and static part, stage options, the delivery method, default tags, folder patterns), with how many follow it, or a copy of its `dbt_project.yml` and package files. Also in the report's `project_settings.suggestions`, keyed by runtime config field. | Apply it (CLI: `--apply-settings`) so new entities follow the dbt project; importing again stores less on its models. |
| `dbt.model_not_mapped` | info | A model without a Data Vault call TurboVault maps (marts, Business Vault, unrelated models), or a v1 view of a satellite that isn't imported. It stays in the dbt project. | — |
| `entity.depends_on_skipped` | warning | An entity needs a stage, Hub or Link that is left out (its error is reported there). | Fix the first error. |

## Schema validation

| Code | Cause | Suggestion |
|------|-------|------------|
| `schema.missing_sheet` | A required sheet/table is absent. | Add the sheet using the Turbovault template. |
| `schema.missing_column` | A required column is missing from a sheet. | Add the listed column to the sheet header row. |
| `schema.unknown_sheet` | A sheet name is not recognized. | Remove or rename the sheet. |
| `schema.unknown_column` | A column header is not recognized. | Remove or rename the column (warning only). |

## Row validation

| Code | Cause | Suggestion |
|------|-------|------------|
| `row.required_value_missing` | A required cell is empty. | Fill the cell at the indicated row. |
| `row.invalid_type` | A cell value cannot be coerced to the expected type. | Correct the value at the indicated row. |
| `row.invalid_enum_value` | A cell value is not one of the allowed options. | Use one of the listed values. |

## Resolution / semantic

| Code | Cause | Suggestion |
|------|-------|------------|
| `entity.duplicate_name` | The same physical name appears twice. | Rename one of the entities to a unique name. |
| `entity.missing_parent` | A satellite's parent hub/link is not defined. | Add the parent entity or fix the parent reference. |
| `entity.missing_reference` | A link, reference table or PIT references a hub/link that is not defined. | Add the hub or remove the reference. |
| `entity.missing_source_column` | A mapping references a source column that does not exist. | Add the column to the source table or fix the mapping. |
| `entity.missing_source_table` | A mapping references a source table identifier that does not exist. | Add the source table or fix the identifier. |
| `entity.invalid_configuration` | An entity is internally inconsistent (e.g. satellite with both hub & link parent), or one of its stored model settings (`model_outputs`) can't be stored: an invalid model name or folder, or a name another model has. That setting is left out; the entity is imported. | Correct the entity definition or the model setting. |
| `entity.depends_on_skipped` | *Warning.* An entity is left out because an entity it depends on can't be imported (a satellite of a skipped link, a PIT tracking a skipped satellite). | Fix the problem reported for that entity. |

An entity that can't be imported is left out rather than imported
half-resolved, and appears in the plan as a skip with one of these
`skip_reason` values:

| `skip_reason` | Meaning |
|---------------|---------|
| `missing_reference` | A link, reference table or PIT references a hub/link that is not defined, or a prejoin joins on or extracts a column that doesn't exist. |
| `missing_parent` | A satellite's parent hub/link is not defined. |
| `missing_source_table` | A satellite's or prejoin's source table is not defined. |
| `depends_on_skipped` | Something the entity depends on was skipped. |
| `invalid_configuration` | The entity is inconsistent, e.g. a prejoin whose source and target join columns don't line up. |
| `execute_failed` | Writing the entity failed (see the `execute.*` issue). Only that entity was rolled back. |
| `skip_snapshots` | A PIT, while the import runs with `skip_snapshots`: it needs a snapshot control. An existing PIT is kept. |
| `update_only` | The entity is new and the strategy is `update_only`. |

## Plan stage

These are *info-level* events emitted in dry-run mode so the UI can render
the planned diff. They never block.

| Code | Meaning |
|------|---------|
| `plan.would_create` | The entity would be created. |
| `plan.would_update` | The entity would be updated (with field diffs). |
| `plan.would_delete` | The entity would be deleted (replace_all only). |
| `plan.would_skip` | The entity would be skipped (e.g. update_only with no match). |
| `plan.rejected` | *Error.* The caller's `on_plan` callback stopped the import before anything was written. |

## Execute stage

| Code | Cause | Suggestion |
|------|-------|------------|
| `execute.constraint_violation` | A database constraint blocked the write. | Resolve the conflict and re-run. |
| `execute.unexpected_error` | An unexpected error occurred during write. | Re-run; contact support if it persists. |

## Internal

| Code | Meaning |
|------|---------|
| `internal.bug` | A code path the pipeline considers unreachable was hit. Please file a bug. |
