# Generation Issue Codes

Every diagnostic produced by the generation pipeline carries a stable
machine-readable `code`. Frontends use these codes to localize and
deep-link errors; the CLI groups them in summary tables.

## Build stage

| Code | Cause | Suggestion shown to user |
|------|-------|--------------------------|
| `build.project_load_failed` | Project metadata could not be read from the database. | Confirm the project exists and migrations are up to date. |
| `build.export_inconsistent` | The Pydantic export model could not be assembled (missing references, type mismatch). | Review the project in the metadata editor for missing relationships. |

## Validate stage

| Code | Cause | Suggestion |
|------|-------|------------|
| `validate.source.no_schema` | A source system has no `schema_name`. | Set a schema name on the source system. |
| `validate.source.no_tables` | A source system has no tables. | Add at least one source table or remove the system. |
| `validate.stage.no_source_table` | A stage definition has no source table backing it. | Re-link the stage to a source table. |
| `validate.stage.no_keys` | A stage has neither hashkeys nor hashdiffs to compute. | Confirm hubs / links / satellites reference this stage. |
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
| `render.template_render_failed` | A template raised during render (Jinja syntax, undefined variable). | Check the template for the listed entity. |
| `render.entity_skipped` | Best-effort skipped an entity due to a render error (info). | See the preceding `render.template_*` error for the root cause. |

## Write stage

| Code | Cause | Suggestion |
|------|-------|------------|
| `write.io_error` | A file could not be written (permission, disk full). | Resolve the filesystem issue and re-run. |
| `write.path_collision` | Two artifacts tried to write to the same path. | Rename one of the colliding entities or report a bug. |
| `write.zip_failed` | The optional ZIP archive could not be created. | Re-run without `--zip`; the dbt tree on disk is still valid. |

## Internal

| Code | Meaning |
|------|---------|
| `internal.bug` | An unreachable code path was hit. Please file a bug. |
