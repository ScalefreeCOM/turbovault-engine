# Generation Issue Codes

Every diagnostic produced by the generation pipeline carries a stable
machine-readable `code`. Frontends use these codes to localize and
deep-link errors; the CLI groups them in summary tables.

## Build stage

| Code | Cause | Suggestion shown to user |
|------|-------|--------------------------|
| `build.project_load_failed` | Project metadata could not be read from the database, or the project's `config.yml` exists but is invalid (e.g. an unknown materialization). Nothing is generated — the run does not fall back to default settings. | Confirm the project exists and migrations are up to date; fix the `config.yml` field named in the message. |
| `build.export_inconsistent` | The Pydantic export model could not be assembled (missing references, type mismatch). | Review the project in the metadata editor for missing relationships. |

## Validate stage

| Code | Cause | Suggestion |
|------|-------|------------|
| `validate.source.no_schema` | A source system has no `schema_name`. | Set a schema name on the source system. |
| `validate.source.no_tables` | A source system has no tables. | Add at least one source table or remove the system. |
| `validate.stage.no_source_table` | A stage definition has no source table backing it. | Re-link the stage to a source table. |
| `validate.stage.no_keys` | A stage has neither hashkeys nor hashdiffs to compute. | Confirm hubs / links / satellites reference this stage. |
| `validate.stage.derived_column_no_datatype` | A derived column or column transformation computes an SQL expression but has no data type, and neither does its source column (warning). datavault4dbt needs it to build ghost records; dbt fails to compile the stage without it. | Set a data type on the derived column or transformation, or on the source column. |
| `validate.stage.uses_load_column` | A hash key or satellite maps the column the stage's record source or load date is read from (warning). datavault4dbt turns that column into the stage's `rsrc`/`ldts` and doesn't pass it on, so the model fails. | Map another column, or set the datavault4dbt variable `copy_rsrc_ldts_input_columns` to keep it. |
| `validate.stage.duplicate_hashdiff` | Two satellites of one stage name their hash diff alike but hash different columns, e.g. through a stored hash diff name. The stage can compute only one column of that name. | Give one satellite its own hash diff name. |
| `validate.stage.duplicate_hashkey` (warning) | Two hubs or links that one stage loads name their hash key alike but hash different columns. The stage computes the column once, for the first (hubs by name, then links by name); the other gets that hash. | Give one of them its own hash key name. |
| `validate.reference_table.satellite_without_v1` | A reference table reads the v1 view of a satellite that gets none (its own `create_v1_view`, or the project's `generate_satellite_v1_views`) (warning). | Turn the satellite's v1 view on. |
| `validate.model.duplicate_name` | Two models of the project have one name (compared case-insensitively), e.g. a stored stage name equal to a hub's; pre-stages count, being models of the dbt project. dbt refuses duplicate model names. | Rename one of them: its model output's name, or the entity. |
| `validate.model.invalid_name` | A model name can't name a file inside the project (slashes, `..`). Generation writes nothing for it. | Rename the model or the entity. |
| `validate.model.invalid_folder` | A model's stored folder leaves the dbt project (absolute path, drive letter, `..`). Generation writes nothing for it. | Use a folder relative to the dbt project, e.g. `models/raw_vault/hubs`. |
| `validate.hub.missing_hashkey` | A standard hub has no hashkey column name. | Set a hashkey naming pattern on the project or the hub. |
| `validate.hub.no_business_keys` | A hub has no business-key columns. | Add at least one business-key column. |
| `validate.hub.no_source_tables` | A hub has no source mappings (warning). | Map the hub's business keys to at least one source column. |
| `validate.link.missing_hashkey` | A link has no hashkey column name. | Set a hashkey on the link. |
| `validate.link.too_few_hubs` | A link references fewer than two hubs (warning). | A link should connect at least two hubs. |
| `validate.link.no_sources` | A link has no source mappings (warning). | Map the link's foreign hashkeys to source columns. |
| `validate.satellite.no_parent` | A satellite has neither a parent hub nor a parent link. | Set `parent_hub` or `parent_link`. |
| `validate.satellite.no_stage` | A satellite has no associated stage. | Confirm the satellite's source table feeds a stage. |
| `validate.satellite.no_columns` | A satellite has no columns (warning). | Add at least one satellite column. |
| `validate.satellite.no_hashdiff` | A standard satellite has no hashdiff column name (warning). | Set a hashdiff naming pattern. |
| `validate.pit.no_satellites` | A PIT references no satellites. | Add at least one satellite to the PIT. |
| `validate.pit.no_snapshot_logic` | A PIT has no snapshot-control logic. | Pick a snapshot control logic column. |
| `validate.pit.no_tracked_entity` | A PIT has neither a tracked hub nor link. | Set `tracked_hub` or `tracked_link`. |
| `validate.snapshot.no_name` | A snapshot control has no name. | Provide a name for the snapshot control. |
| `validate.snapshot.no_start_date` | A snapshot control has no start date. | Set the snapshot range's start date. |
| `validate.snapshot.no_logic_patterns` | A snapshot control has no logic patterns (warning). | Add at least one snapshot logic pattern. |

## Plan stage

| Code | Cause | Suggestion |
|------|-------|------------|
| `plan.unsupported_output_type` | The requested `output_type` is not one of dbt / json / dbml. | Use one of the supported output types. |
| `plan.empty_project` | The selection (or empty project) leaves nothing to generate. | Widen the selection or add entities to the project. |

## Render stage

| Code | Cause | Suggestion |
|------|-------|------------|
| `render.template_not_found` | A required Jinja template could not be located. | Populate templates via `populate_templates` or check the custom template overrides. |
| `render.template_outdated` | A template predates something its model needs (warning), e.g. a workspace's copy seeded before it existed. The stage template doesn't read a stage's pre-stage model or prejoin one (the stage would read the pre-stage as a dbt source, which doesn't exist). Or a template ignores the model's stored model output: it doesn't write the stored `config()` settings (`model_config`) or tags (`model_tags`), names a model other than the stored one, or doesn't reference the stored name of a model it reads (a v1 view's v0 table, a PIT's satellites and snapshot control, a reference table's v1 views, a snapshot logic's table). | Update the template: `python manage.py populate_templates --overwrite` refreshes the workspace's copies (and replaces their customizations). |
| `render.template_render_failed` | A template raised during render (Jinja syntax, undefined variable). | Check the template for the listed entity. |
| `render.entity_skipped` | Best-effort skipped an entity due to a render error (info). | See the preceding `render.template_*` error for the root cause. |
| `render.invalid_global_vars` | The caller-supplied `global_vars` mapping could not be serialized into the `vars:` block. Nothing is generated, so an earlier run's output is left untouched rather than half-replaced. | Fix the reported key — `global_vars` must be a mapping with string keys and YAML-serializable values. |
| `render.invalid_profiles` | `generate_profiles_yml` is on but `profiles` is not a mapping or holds a value that cannot be written as YAML. The engine does not check the dbt profile shape (targets, outputs, adapter fields) — that is the caller's concern. Nothing is generated. | Pass `profiles` as a mapping of YAML-serializable values. |
| `render.invalid_materialization` | A layer materialization (`control_`, `staging_`, `raw_vault_`, `business_vault_materialization`) or a `model_materializations` entry is not a dbt materialization name, or names an unknown model kind. Nothing is generated. | Use a name such as `table`, `view`, `incremental`, `ephemeral`, or a custom materialization's name. |
| `render.prestage.maintained_in_dbt` | The project has a pre-stage (warning, once per pre-stage, dbt output only). Its model belongs to the dbt project: TurboVault doesn't generate it, and its stage reads it with `ref()`, which only resolves in the dbt project that contains the model. Generating into an existing dbt project (spec D17), it is reported only when that project has no model, seed or snapshot of the name. | Generate into the dbt project that contains the model, or add the model to it. |
| `render.project_files_kept` (info) | The output folder holds a dbt project whose `dbt_project.yml` TurboVault didn't write (dbt output only, spec D17). Its `dbt_project.yml`, `packages.yml` (and `profiles.yml`) aren't written. Its folder settings apply; a model carries its layer's schema and materialization in `config()` where they give it none. | Generate with `--write-project-files` (`write_project_files=True`) to replace them. |
| `render.project_needs_package` | In an existing dbt project: its packages lack datavault4dbt, or a package of the project's settings (`dbt_packages`), which the generated models need. | Add the listed entries to its `packages.yml`. |
| `render.project_needs_vars` | In an existing dbt project: its `dbt_project.yml` doesn't set variables the project's settings have (`global_vars`). | Add them to its `vars:`. |
| `render.literal_secret_in_profile` | A secret key in `profiles` — one ending in `password`, `passphrase`, `secret`, `token`, `private_key`, `access_key` or `api_key`, or `pass` / `keyfile_json` — holds a literal value, or an `env_var` reference with a non-empty default (dbt uses the default whenever the variable is unset). Nothing is generated; the value is never echoed. | Reference the secret via `{{ env_var('...') }}` (optionally `\| as_native`), without a default or with an empty one. An inline `keyfile_json` mapping is allowed when its own secret fields are references. |

## Write stage

| Code | Cause | Suggestion |
|------|-------|------------|
| `write.io_error` | A file could not be written (permission, disk full). | Resolve the filesystem issue and re-run. |
| `write.path_collision` | Two artifacts tried to write to the same path. | Rename one of the colliding entities or report a bug. |
| `write.zip_failed` | The optional ZIP archive could not be created. | Re-run without `--zip`; the dbt tree on disk is still valid. |
| `write.stale_file` | A file TurboVault generated into the folder before (its record, `.turbovault/generated.json`) and no longer generates, e.g. after renaming an entity. Kept. | Delete it, or generate with `--remove-stale-files`. |
| `write.stale_file_removed` (info) | Such a file, unchanged since TurboVault wrote it, deleted (`remove_stale_files`). | — |
| `write.stale_file_changed` | Such a file was changed since TurboVault wrote it: kept, and from now on the project's own (not reported again). | Delete it if it isn't needed. |
| `write.files_replaced` (info) | Files of the folder TurboVault hadn't written were replaced by its own (e.g. the models of an imported dbt project, generated back into it). | — |
| `write.model_defined_twice` | dbt output: a model TurboVault wrote is also defined (another model file of its name) or described (another YAML entry for it) elsewhere in the dbt project; dbt fails on either. | Remove one of them. |
| `write.source_defined_twice` | dbt output: a source table TurboVault's source definitions declare is declared in another YAML file of the project too. | Remove one of them, or skip TurboVault's sources (`output.export_sources: false`). |

## Internal

| Code | Meaning |
|------|---------|
| `internal.bug` | An unreachable code path was hit. Please file a bug. |
