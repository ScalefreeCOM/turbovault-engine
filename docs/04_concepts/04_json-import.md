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

## Usage

### CLI

Pass the `.json` file directly with the `--source` flag. The file extension is detected automatically:

```bash
# Export
turbovault generate --type json --project my_project --json-output ./my_project.json

# Import (new project name, same or different workspace)
turbovault project init --name my_project_copy --source ./my_project.json
```

Interactive wizard also supports JSON:

```bash
turbovault project init --interactive
# Select "JSON export file (.json)" when prompted for source type
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

Snapshot controls embedded in the JSON export are restored as-is. The automatic creation of default snapshot controls (which happens for new empty projects) is skipped when the source type is `json`.

## What Is Not Preserved

- **Project-level configuration** (`stage_schema`, `rdv_schema`, naming patterns, etc.) is stored in `config.yml`, not in the JSON export. You will need to configure these separately for the new project, either via CLI flags or `config.yml`.
- **Django Admin customizations** such as custom model templates are workspace-level settings and are not included in the export.
- **Generated dbt output** — only the metadata model is exported, not the previously generated SQL or YAML files.

## Generating the JSON Export

See [`turbovault generate --type json`](../02_getting-started/01_cli-reference.md#turbovault-generate) for the full set of options controlling the JSON output path and format.
