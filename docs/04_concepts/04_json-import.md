---
sidebar_position: 4
sidebar_label: JSON Import
title: JSON Import (Round-Trip)
---

# JSON Import (Round-Trip)

TurboVault Engine can export the full Data Vault model as a structured JSON file and re-import that file into any workspace. This enables:

- **Project migration** — move a project from one workspace or database to another
- **Backup and restore** — snapshot a project at a point in time and restore it later
- **Environment promotion** — promote a model from development to production
- **Collaboration** — share a complete model definition as a single portable file

## How It Works

```
Workspace A                          Workspace B
──────────                           ──────────
turbovault generate                  turbovault project init
  --type json          →  model.json →  --source model.json
  --project my_project                  --name my_project
```

The JSON export contains every piece of metadata stored in the project:

| Section | Content |
|---------|---------|
| `sources` | Source systems, tables, and columns |
| `hubs` | Hub definitions with business/reference keys and source mappings |
| `links` | Link definitions with hub references and source mappings |
| `satellites` | Satellite definitions with all column mappings |
| `stages` | Stage definitions including hashkeys, hashdiffs, and prejoins |
| `snapshot_controls` | Snapshot control tables and logic patterns |
| `reference_tables` | Reference table definitions |
| `pits` | Point-in-Time structure definitions |

Every entity also carries the settings of its dbt models: `model_outputs`
holds what the project stores (see [Model settings](#model-settings)), and
`output`, `v0_output`, `v1_output` and the like hold the models as they are
generated. The import reads `model_outputs`; the generated models, like the
`stages` and `prestages` lists, are derived and not read back.

## Usage

### CLI

Pass the `.json` file directly with the `--source` flag. The file extension is detected automatically:

```bash
# Export
turbovault generate --type json --project my_project --json-output ./my_project.json

# Import as a brand-new project
turbovault project init --name my_project_copy --source ./my_project.json

# Re-import into an existing project (merge by default; safe to repeat)
turbovault import --project my_project_copy --source ./my_project.json

# Preview the impact of a JSON import without writing anything
turbovault import --project my_project_copy --source ./my_project.json --dry-run
```

Interactive wizards also support JSON:

```bash
turbovault project init --interactive
# Select "JSON export file (.json)" when prompted for source type

turbovault import --interactive
# Pick the project and provide the .json file when prompted
```

### config.yml

```yaml
project:
  name: "my_project_copy"

source:
  type: json
  path: "./my_project.json"
```

Then run:

```bash
turbovault project init --config config.yml
```

## Round-Trip Fidelity

Importing a JSON export and re-exporting to JSON produces structurally identical output. All entity relationships, naming patterns, column sort orders, and source mappings are preserved exactly.

Descriptions and derived columns round-trip too. A Raw Vault column's export
shows both its own `description` and the `source_description` it inherits;
only its own is imported, so an inherited description stays inherited. An
export from before derived columns existed has no `derived_columns` on its
tables, and importing it leaves the project's derived columns alone.

Pre-stages round-trip as source tables with `table_type: "prestage"`. They
carry no SQL: the model belongs to the dbt project. A `prestage_sql` field in
files exported while pre-stages had SQL is ignored. An export from before
pre-stages existed has no `table_type`, and importing it leaves the project's
table types alone; a `replace_all` import of such a file doesn't delete
pre-stages either. The export's `prestages` and `stages` lists are derived from
the tables and are not read back.

### Options and settings

The options of stages, hubs, links, satellites, PITs and snapshot controls
round-trip: the stage options and delivery method of source systems and
tables, missing columns, a satellite's hash diff alias and v1 view options,
the high-water mark switches, effectivity satellite options, a link's union
strategy, a PIT's snapshot optimization and custom record source, and a
snapshot control's `sdts_alias` and end date.

A value the file leaves empty is cleared in the project: `"sequence_column":
null` removes the table's sequence column, `"create_v1_view": null` makes the
satellite follow the project's setting again. A field the file doesn't have
at all, because an older version exported it, leaves the project's value
alone.

A satellite's `hashdiff_name` is the stage's hash diff column as generated:
the satellite's own name, or the one the `hashdiff_naming` pattern gives. The
import stores it only where it differs from what the importing project's
pattern gives, so the satellite keeps following the pattern.

### Model settings

`model_outputs` maps each of an entity's dbt models with stored settings to
those settings, by kind: `stage` and `prestage` on a source table; `hub`,
`effectivity_satellite` and `record_tracking_satellite` on hubs and links;
`satellite_v0` and `satellite_v1` on satellites; `pit`, `reference_table`,
`snapshot_control_v0` and `snapshot_control_v1`. Each holds the stored
`model_name`, `folder`, `alias`, `schema_name`, `database_name`,
`materialized`, `tags` and further `config` keys; a value that is `null`
follows TurboVault's defaults.

```json
"model_outputs": {
  "stage": {
    "model_name": "stg_crm_customer",
    "folder": "models/staging/crm",
    "materialized": "view",
    "tags": ["crm"],
    "config": {"on_schema_change": "sync_all_columns"},
    "alias": null, "schema_name": null, "database_name": null
  }
}
```

The import gives each entity exactly the settings its `model_outputs` lists:
a model the file leaves out goes back to the defaults. A setting that can't be
stored, such as a folder outside the dbt project or a model name another model
already has, is reported as `entity.invalid_configuration` and left as it is;
the entity itself is imported.

### Snapshot controls

Snapshot controls are restored with their dates, daily time, `sdts_alias`,
logic patterns and model settings, before the PITs and reference tables that
read them. A control is matched by its base name: `control_snap`,
`control_snap_v0` and `control_snap_v1` are one control. PITs and reference
tables find their control by its model, also when a stored model name renamed
it. The import adds and updates logic patterns but never removes one, and it
never deletes a snapshot control, `replace_all` included: PITs and reference
tables the file doesn't describe may read them.

`project init` from a JSON export doesn't create the default snapshot
controls: the export carries its own. An import with `--skip-snapshots`
leaves snapshot controls and PITs out.

## What Is Not Preserved

- **Project-level configuration** (`stage_schema`, `rdv_schema`, naming patterns, etc.) is stored in `config.yml`, not in the JSON export. You will need to configure these separately for the new project, either via CLI flags or `config.yml`.
- **Django Admin customizations** such as custom model templates are workspace-level settings and are not included in the export.
- **Generated dbt output** — only the metadata model is exported, not the previously generated SQL or YAML files.

## Generating the JSON Export

See [`turbovault generate --type json`](../02_getting-started/01_cli-reference.md#turbovault-generate) for the full set of options controlling the JSON output path and format.

## How JSON imports run

JSON imports flow through the same [Import Pipeline](06_import-pipeline.md) as Excel and SQLite, so the conflict strategy (`merge` / `replace-all` / `update-only`), error strategy (`best-effort` / `fail-fast`), and `--dry-run` flag all behave identically.

For a JSON file produced by `turbovault generate --type json`, validation issues are rare in practice — the export schema is structured and round-trip safe. The most common issues you might see are:

| Code | Trigger |
|------|---------|
| `source.invalid_json` | The file is not valid JSON or does not match the Turbovault export schema. |
| `entity.missing_reference` | The JSON references a hub, satellite or other entity that doesn't exist (rare; can happen when manually editing exports). |
| `entity.invalid_configuration` | A model setting in `model_outputs` can't be stored: an invalid model name or folder, or a model name another model of the project has. The entity is imported without it. |

The full catalog lives in [Import Pipeline → Issue codes](06_import-pipeline.md#issue-codes).
