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
| `entity.invalid_configuration` | An entity is internally inconsistent (e.g. satellite with both hub & link parent). | Correct the entity definition. |
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
