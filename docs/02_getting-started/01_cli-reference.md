---
sidebar_position: 3
sidebar_label: CLI Reference
title: CLI Reference
---

# TurboVault CLI User Guide

## Installation

Install TurboVault Engine from PyPI:

```bash
pip install turbovault-engine
```

This makes the `turbovault` command available in your terminal.

> **Note for contributors:** If you are working on the engine locally, install in editable mode instead: `pip install -e .`

## Commands Overview

TurboVault uses a **two-step setup**: initialise the workspace once, then create projects inside it.

| Command | Description |
|---------|-------------|
| `turbovault workspace init` | Initialise directory as a workspace |
| `turbovault workspace status` | Show DB connection, project count, migration status |
| `turbovault project init` | Create a new Data Vault project in the workspace |
| `turbovault project list` | List all projects in the workspace |
| `turbovault import` | Run the import pipeline against an existing project (merge / replace / dry-run) |
| `turbovault import-history` | Show recent import runs for a project |
| `turbovault model` | Create and inspect Data Vault entities (hubs, links, satellites, PITs) |
| `turbovault generate` | Generate dbt project / JSON / DBML / IRiS export (supports selection, dry-run, single-entity preview) |
| `turbovault generation-history` | Show recent generation runs for a project |
| `turbovault serve` | Start Django admin server |
| `turbovault reset` | Reset the workspace database |


## Command Reference

### turbovault workspace init

Initialise the current directory as a TurboVault workspace. Run this **once per workspace** before creating any projects.

Creates `turbovault.yml`, initialises the database, populates default templates, and optionally creates an admin user.

#### Non-Interactive Mode (Flags)

```bash
turbovault workspace init \
  --db-engine sqlite3 \
  --db-name db.sqlite3 \
  --stage-schema stage \
  --rdv-schema rdv \
  --skip-admin
```

With PostgreSQL and admin user:

```bash
turbovault workspace init \
  --db-engine postgresql \
  --db-name company_vault \
  --db-host db.company.com \
  --db-port 5432 \
  --db-user vault_user \
  --db-password secret \
  --admin-username admin \
  --admin-password changeme \
  --admin-email admin@company.com
```

#### Interactive Mode

```bash
turbovault workspace init
# or
turbovault workspace init --interactive
```

Prompts for database engine, connection settings, schema defaults, and optional admin user.

#### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--db-engine STR` | Database backend (`sqlite3`, `postgresql`, `mysql`, `mssql`, `snowflake`) | prompted |
| `--db-name STR` | Database name or SQLite file path | prompted |
| `--db-host STR` | Database host (non-SQLite only) | — |
| `--db-port INT` | Database port (non-SQLite only) | — |
| `--db-user STR` | Database user (non-SQLite only) | — |
| `--db-password STR` | Database password (non-SQLite only) | — |
| `--stage-schema STR` | Default staging schema name | `stage` |
| `--rdv-schema STR` | Default RDV schema name | `rdv` |
| `--admin-username STR` | Admin username (skips prompt) | prompted |
| `--admin-email STR` | Admin email (skips prompt) | prompted |
| `--admin-password STR` | Admin password (skips prompt) | prompted |
| `--skip-admin` | Skip admin user creation entirely | `false` |
| `--overwrite` | Overwrite existing `turbovault.yml` | `false` |
| `--interactive`, `-i` | Force interactive prompts | `false` |

> **See also:** [Database Configuration Guide](../03_configuration/02_database.md) for detailed setup instructions for PostgreSQL, MySQL, SQL Server, and other backends.

---

### turbovault workspace status

Show the health of the current workspace.

```bash
turbovault workspace status

# Output:
#   Config file:     turbovault.yml
#   Database:        sqlite3 / db.sqlite3
#   DB status:       Connected
#   Projects:        2
#   Migrations:      Up to date
```

---

### turbovault project init

Create a new Data Vault project inside an existing workspace.

Requires `turbovault workspace init` to have been run first.

#### Non-Interactive Mode (Flags)

```bash
turbovault project init --name my_project --source ./metadata.xlsx \
  --stage-schema stage --rdv-schema rdv
```

#### Interactive Mode

```bash
turbovault project init --interactive
```

Prompts for project name, description, source metadata, schema names, naming patterns, and ZIP option.

#### From a Config File

```bash
turbovault project init --config config.yml
```

#### Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--name NAME` | `-n` | Project name | prompted |
| `--description STR` | | Project description | — |
| `--source PATH` | `-s` | Source metadata file (`.xlsx`, `.db`, or `.json` export) | — |
| `--stage-schema STR` | | Staging schema name | `stage` |
| `--rdv-schema STR` | | Raw Data Vault schema name | `rdv` |
| `--stage-database STR` | | Optional staging database name | — |
| `--rdv-database STR` | | Optional RDV database name | — |
| `--hashdiff-naming STR` | | Hashdiff naming pattern | `hd_[[ satellite_name ]]` |
| `--hashkey-naming STR` | | Hashkey naming pattern | `hd_[[ entity_name ]]` |
| `--zip` | | Create ZIP of generated dbt project | `false` |
| `--overwrite` | | Overwrite existing project | `false` |
| `--interactive` | `-i` | Run interactive setup wizard | `false` |
| `--config PATH` | `-c` | Load settings from a `config.yml` | — |

---

### turbovault project list

List all projects in the current workspace.

```bash
turbovault project list

# Output:
# ┌─────────────┬─────────────┬──────────────────────┐
# │ Name        │ Description │ Directory            │
# ├─────────────┼─────────────┼──────────────────────┤
# │ TestProject │ —           │ projects/testproject │
# └─────────────┴─────────────┴──────────────────────┘
```

---

### turbovault import

Run the import pipeline against an **existing** project. This is the
standalone counterpart to `project init --source ...` — use it whenever
you want to re-import a file, validate a file without writing, or
import into a project that already has metadata.

The default mode is **`merge`** with **`best-effort`** error handling:
add or update entities from the file, leave anything not in the file
alone, and skip individual rows that fail validation (reporting each one
with full sheet/row/column context). See [Import Pipeline](../04_concepts/06_import-pipeline.md)
for the full behavior reference.

#### Non-Interactive Mode (Flags)

```bash
# Merge: update existing entities, add new ones (default)
turbovault import --project my_project --source ./metadata.xlsx

# Replace: drop anything in the project that isn't in the file
turbovault import --project my_project --source ./metadata.xlsx --mode replace-all

# Strict: stop at the first validation error, no DB writes
turbovault import --project my_project --source ./metadata.xlsx --on-error fail-fast

# Dry-run: parse + validate + plan, but never touch the database
turbovault import --project my_project --source ./metadata.xlsx --dry-run
```

#### Interactive Mode

```bash
turbovault import
# or
turbovault import --interactive
```

Prompts for project (chosen from a list of existing projects), source
file, conflict strategy, error strategy, dry-run, and snapshot control
behavior.

If only one of `--project` / `--source` is supplied, the command exits
with a clear error rather than running half-blind — pass both or pass
neither.

#### Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--source PATH` | `-s` | Path to the source metadata file (`.xlsx`, `.db`/`.sqlite`, or `.json`) | prompted |
| `--project NAME` | `-p` | Target project name (must exist) | prompted |
| `--mode STR` | | Conflict strategy: `merge`, `replace-all`, or `update-only` | `merge` |
| `--on-error STR` | | Error strategy: `best-effort` or `fail-fast` | `best-effort` |
| `--dry-run` | | Validate + plan only; do not write to the database | `false` |
| `--skip-snapshots` | | Skip creating a default snapshot control table | `false` |
| `--interactive` | `-i` | Run the interactive import wizard | `false` |

#### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | `success` — no errors |
| `1` | `partial_success` — some entities skipped, others written |
| `2` | `validation_failed` or `failed` — nothing was written |

These map cleanly to typical CI conventions.

#### What gets reported

The CLI prints two tables and a status line:

```
Import Plan
┌──────────────────┬────────┬────────┬────────┬──────┐
│ Entity           │ Create │ Update │ Delete │ Skip │
├──────────────────┼────────┼────────┼────────┼──────┤
│ source_system    │      1 │      0 │      0 │    0 │
│ hub              │      2 │      1 │      0 │    0 │
│ satellite        │      3 │      0 │      0 │    1 │
│ Total            │      6 │      1 │      0 │    1 │
└──────────────────┴────────┴────────┴────────┴──────┘

Issues (1)
┌─────────┬─────────────────────────┬──────────────────────────────┬───────────────────────────────────┐
│ Sev     │ Code                    │ Location                     │ Message                           │
├─────────┼─────────────────────────┼──────────────────────────────┼───────────────────────────────────┤
│ ERROR   │ entity.missing_parent   │ standard_satellite row 5     │ Satellite 'sat_orphan' parent     │
│         │                         │ <satellite sat_orphan>       │ 'no_such_hub' was not defined.    │
└─────────┴─────────────────────────┴──────────────────────────────┴───────────────────────────────────┘

⚠ Import partially succeeded: wrote 6 entities, skipped 2 due to 1 error(s)
  and 0 warning(s). See the Issues table above for details on each skipped item.
```

> **See also:** [Import Pipeline](../04_concepts/06_import-pipeline.md) for the
> complete issue-code catalog, conflict-strategy semantics, and dry-run behavior.

---

### turbovault import-history

List recent import runs for a project, newest first. Every invocation of
the import pipeline — including dry-runs and failed runs — is recorded
as an `ImportRun` and shows up here.

```bash
turbovault import-history --project my_project
turbovault import-history --project my_project --limit 50

# Interactive: pick the project from a list
turbovault import-history
turbovault import-history --interactive
```

If your workspace has exactly one project, `turbovault import-history`
uses it automatically (no prompt). Pass `--interactive` to always show
the picker.

#### Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--project NAME` | `-p` | Project to show history for | prompted |
| `--limit INT` | `-l` | Maximum rows to display | `20` |
| `--interactive` | `-i` | Pick the project interactively | `false` |

#### Output

```
Import history for 'my_project'
┌────────────────────┬─────────────────┬──────────┬──────┬───────────────────────┬────────┬──────────┬──────────┐
│ Started            │ Status          │ Mode     │ Dry? │ Source                │ Errors │ Warnings │ ID       │
├────────────────────┼─────────────────┼──────────┼──────┼───────────────────────┼────────┼──────────┼──────────┤
│ 2026-05-23T14:02:11│ partial_success │ merge    │ no   │ excel: metadata.xlsx  │      1 │        0 │ 8c19f5a2 │
│ 2026-05-23T13:55:08│ success         │ merge    │ yes  │ excel: metadata.xlsx  │      0 │        0 │ 1e0bd72f │
│ 2026-05-23T11:48:00│ success         │ replace_all │ no│ excel: metadata.xlsx  │      0 │        2 │ a4f2c907 │
└────────────────────┴─────────────────┴──────────┴──────┴───────────────────────┴────────┴──────────┴──────────┘
```

The `ID` column is a short prefix of the `ImportRun.import_run_id` UUID;
full IDs are also stored in `ImportReport.import_run_id` for deep links
from the Studio frontend.

---

### turbovault generate

Generate a dbt project, JSON export, DBML diagram, or [IRiS](https://ignition-data.com/iris) export from
your Data Vault model. The `dbt`, `json`, and `dbml` types run the
unified [Generation Pipeline](../04_concepts/07_generation-pipeline.md)
end-to-end and return a structured report with per-entity plan counts,
severity-coded issues, and per-stage timings. The `iris` type is served
by a standalone exporter that writes a directory of Excel workbooks
instead of going through the pipeline.

#### Basic Usage

```bash
turbovault generate --project my_project
```

If `--type` is omitted you'll be prompted to choose. With flags only:

```bash
turbovault generate --project sales_datavault --type dbt
```

**Default output location:**

| Output type | Default path |
|-------------|--------------|
| `dbt` | `<workspace>/projects/<project>/exports/dbt_project/` |
| `json` | `<workspace>/projects/<project>/exports/<project_slug>.json` |
| `dbml` | `<workspace>/projects/<project>/exports/<project_slug>.dbml` |
| `iris` | `<workspace>/projects/<project>/exports/iris/` |

Explicit `--output`, `--json-output`, `--dbml-output`, or `--iris-output`
always wins. If the project has no `project_directory` configured (ad-hoc
/ test projects), the fallback is `./output/<slug>` (`./output/<slug>_iris`
for `iris`) under the current directory.

#### Generate to Custom Directory

```bash
turbovault generate --project sales_datavault --output ./my_dbt_projects/sales
```

#### Generate with ZIP Archive

```bash
turbovault generate --project sales_datavault --zip
```

Creates both the folder and a sibling `.zip` archive.

#### Selective Generation

You can narrow the scope of a run by entity type, group, or an explicit
allowlist. All filters are optional and repeatable.

```bash
# Only emit hubs and links
turbovault generate --project sales_datavault \
    --include-type hub --include-type link

# Skip all satellites
turbovault generate --project sales_datavault --exclude-type satellite

# Only emit the 'sales' group
turbovault generate --project sales_datavault --include-group sales

# Emit a single hub (e.g. CI verification, single-model preview)
turbovault generate --project sales_datavault --only hub:hub_customer
```

`--only` is an explicit allowlist — when set, it overrides every
include/exclude rule. See [Generation Pipeline → Selective generation](../04_concepts/07_generation-pipeline.md#selective-generation) for the precise semantics.

#### Dry-run

`--dry-run` runs the full pipeline (build → validate → plan → **render
in memory**) but skips writing files. Render-time problems (template
not found, undefined Jinja variable) are surfaced even though nothing
lands on disk. A `GenerationRun` audit row is still recorded.

```bash
turbovault generate --project sales_datavault --dry-run
```

#### Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--project NAME` | `-p` | Project name (or interactive picker) | Interactive |
| `--type TYPE` | `-t` | Export type: `dbt`, `json`, `dbml`, or `iris` | Interactive |
| `--output PATH` | `-o` | Output directory (dbt) or file (json/dbml) | Workspace convention (see above) |
| `--mode MODE` | `-m` | Error strategy: `strict` (fail-fast) or `lenient` (best-effort) | `strict` |
| `--skip-validation` | | Bypass the validate stage entirely | `false` |
| `--dry-run` | | Run build/validate/plan/render; skip write | `false` |
| `--zip` | `-z` | Create ZIP archive after dbt generation | `false` |
| `--no-v1-satellites` | | Skip generating satellite `_v1` views (dbt only) | `false` |
| `--json-output PATH` | | Alias for `--output` when `--type json` | — |
| `--dbml-output PATH` | | Alias for `--output` when `--type dbml` | — |
| `--iris-output PATH` | | Output directory for the IRiS Excel files when `--type iris` | — |
| `--include-type TYPE` | | Only emit these entity types (repeatable) | — |
| `--exclude-type TYPE` | | Skip these entity types (repeatable) | — |
| `--include-group NAME` | | Only emit entities in these groups (repeatable) | — |
| `--exclude-group NAME` | | Skip entities in these groups (repeatable) | — |
| `--only TYPE:NAME` | | Explicit allowlist of entities (repeatable) | — |

#### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | `success` — no errors, all artifacts written |
| `1` | `partial_success` — some entities skipped, others written |
| `2` | `validation_failed` or `failed` — nothing was written |

These map cleanly to typical CI conventions: `0` = OK, `1` = OK with
warnings to triage, `2` = block.

#### Error Strategies

**Strict (default):**
- `--mode strict` — maps to `fail_fast`.
- Aborts at the first error in any stage; no files written.
- Recommended for CI gates and production runs.

**Lenient:**
- `--mode lenient` — maps to `best_effort`.
- Records the issue, skips the entity, keeps going.
- Useful when iterating on a partial model.

#### What gets reported

The CLI prints two tables and a status line:

```
                     Plan
┌─────────────────────────┬───────┐
│ Entity type             │ Files │
├─────────────────────────┼───────┤
│ hub                     │     6 │
│ link                    │     2 │
│ project                 │     3 │
│ satellite               │    14 │
│ stage                   │     8 │
│ Total files planned     │    33 │
└─────────────────────────┴───────┘

                                Issues (1)
┌────────┬──────────┬───────────────────────────────┬──────────────────────┬────────────────────────────────┐
│ Sev    │ Stage    │ Code                          │ Entity               │ Message                        │
├────────┼──────────┼───────────────────────────────┼──────────────────────┼────────────────────────────────┤
│ WARN   │ validate │ validate.satellite.no_columns │ satellite:sat_legacy │ Satellite has no payload cols. │
└────────┴──────────┴───────────────────────────────┴──────────────────────┴────────────────────────────────┘

✓ Generation completed successfully. 33 file(s) written.
Run ID: 7d0c2f8a-...
```

> **See also:** [Generation Pipeline](../04_concepts/07_generation-pipeline.md) for the
> full issue-code catalog, conflict-strategy semantics, and dry-run behavior.

#### Examples

```bash
# Interactive type selection (default)
turbovault generate -p sales_datavault

# dbt project with ZIP, no v1 satellite views
turbovault generate --type dbt -p sales_datavault --zip --no-v1-satellites

# Lenient mode: import what's valid, report what was skipped
turbovault generate --type dbt -p sales_datavault --mode lenient

# Preview without writing anything
turbovault generate --type dbt -p sales_datavault --dry-run

# Single-hub preview (no other files emitted)
turbovault generate --type dbt -p sales_datavault --only hub:hub_customer --dry-run

# JSON export of just the marketing group
turbovault generate --type json -p sales_datavault --include-group marketing

# DBML for visualisation
turbovault generate --type dbml -p sales_datavault
```

---

### turbovault generation-history

List recent generation runs for a project, newest first. Every
invocation of the generation pipeline — including dry-runs and failed
runs — is recorded as a `GenerationRun` and shows up here.

```bash
turbovault generation-history --project my_project
turbovault generation-history --project my_project --limit 50
turbovault generation-history --project my_project --type dbt

# Interactive: pick the project from a list
turbovault generation-history
turbovault generation-history --interactive
```

If your workspace has exactly one project, `turbovault generation-history`
uses it automatically (no prompt). Pass `--interactive` to always show
the picker.

#### Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--project NAME` | `-p` | Project to show history for | prompted |
| `--type TYPE` | `-t` | Filter to one output type (`dbt`, `json`, `dbml`) | all |
| `--limit INT` | `-l` | Maximum rows to display | `20` |
| `--interactive` | `-i` | Pick the project interactively | `false` |

#### Output

```
              Generation history for 'sales_datavault'
┌──────────────────────┬─────────────────┬──────┬──────┬─────────────┬───────┬────────┬──────────┬──────────┐
│ Started              │ Status          │ Type │ Dry? │ Mode        │ Files │ Errors │ Warnings │ ID       │
├──────────────────────┼─────────────────┼──────┼──────┼─────────────┼───────┼────────┼──────────┼──────────┤
│ 2026-05-24T11:42:01  │ success         │ dbt  │ no   │ best_effort │    33 │      0 │        1 │ 7d0c2f8a │
│ 2026-05-24T10:08:15  │ partial_success │ dbt  │ no   │ best_effort │    32 │      1 │        0 │ 4b9ef1c2 │
│ 2026-05-24T09:55:22  │ success         │ json │ no   │ best_effort │     1 │      0 │        0 │ 2a8c0a40 │
│ 2026-05-23T17:30:14  │ validation_fail │ dbt  │ yes  │ fail_fast   │     0 │      2 │        0 │ 9f1d3e7a │
└──────────────────────┴─────────────────┴──────┴──────┴─────────────┴───────┴────────┴──────────┴──────────┘
```

The `ID` column is a short prefix of `GenerationRun.generation_run_id`;
the full UUID is stored in `GenerationReport.generation_run_id` for
deep-linking from the Studio frontend.

---

### turbovault model

Manage Data Vault model entities directly from the command line. The `model` subcommands complement the Django Admin interface — they are useful for scripted workflows, CI pipelines, and AI-assisted modeling via the MCP server.

All `model` commands require an initialised workspace (`turbovault workspace init`) with at least one project.

#### Subcommands at a glance

| Subcommand | Description |
|------------|-------------|
| `turbovault model create-hub` | Create a new hub |
| `turbovault model create-link` | Create a new link |
| `turbovault model create-satellite` | Create a new satellite |
| `turbovault model create-pit` | Create a new PIT (Point-in-Time) structure |
| `turbovault model list` | List entities in a project |
| `turbovault model validate` | Validate the model |
| `turbovault model import-json` | Bulk-import a model proposal from JSON |

---

#### turbovault model create-hub

Create a new hub in the project.

```bash
turbovault model create-hub --name HUB_CUSTOMER \
  --business-keys CUSTOMER_ID \
  --hashkey hk_customer \
  --project my_project
```

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--name NAME` | `-n` | Hub physical name (required) | — |
| `--project NAME` | `-p` | Project name (auto-selected if only one exists) | — |
| `--business-keys STR` | | Comma-separated business key column names | — |
| `--hashkey STR` | | Hashkey column name (leave blank to set later in Admin) | — |
| `--type STR` | | Hub type: `standard` or `reference` | `standard` |
| `--group STR` | | Group name for subfolder organisation | — |

---

#### turbovault model create-link

Create a new link connecting two or more existing hubs.

```bash
turbovault model create-link --name LNK_ORDER_CUSTOMER \
  --hubs HUB_ORDER,HUB_CUSTOMER \
  --hashkey hk_order_customer \
  --project my_project
```

If a referenced hub is not found in the project, the hub reference is skipped with a warning (the link itself is still created).

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--name NAME` | `-n` | Link physical name (required) | — |
| `--project NAME` | `-p` | Project name | — |
| `--hubs STR` | | Comma-separated hub physical names to reference | — |
| `--hashkey STR` | | Hashkey column name | — |
| `--type STR` | | Link type: `standard` or `non_historized` | `standard` |
| `--group STR` | | Group name | — |

---

#### turbovault model create-satellite

Create a new satellite attached to a hub or link.

```bash
# Hub satellite
turbovault model create-satellite --name SAT_CUSTOMER_DETAILS \
  --parent-hub HUB_CUSTOMER \
  --project my_project

# Link satellite
turbovault model create-satellite --name SAT_ORDER_CUSTOMER_EFFECTIVITY \
  --parent-link LNK_ORDER_CUSTOMER \
  --type effectivity \
  --project my_project
```

`--parent-hub` and `--parent-link` are mutually exclusive — exactly one must be provided.

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--name NAME` | `-n` | Satellite physical name (required) | — |
| `--project NAME` | `-p` | Project name | — |
| `--parent-hub STR` | | Parent hub physical name (XOR with `--parent-link`) | — |
| `--parent-link STR` | | Parent link physical name (XOR with `--parent-hub`) | — |
| `--type STR` | | Satellite type: `standard`, `non_historized`, `multi_active`, `effectivity`, `reference` | `standard` |
| `--group STR` | | Group name | — |

---

#### turbovault model create-pit

Create a new PIT (Point-in-Time) table structure.

PITs require an existing `SnapshotControlTable` and `SnapshotControlLogic`. If they do not exist yet, create them via the Admin interface first (`turbovault serve`).

```bash
turbovault model create-pit --name PIT_CUSTOMER \
  --hub HUB_CUSTOMER \
  --snapshot-table as_of_dates \
  --snapshot-logic standard_logic \
  --satellites SAT_CUSTOMER_DETAILS,SAT_CUSTOMER_ADDRESS \
  --project my_project
```

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--name NAME` | `-n` | PIT physical name (required) | — |
| `--project NAME` | `-p` | Project name | — |
| `--hub STR` | | Hub to track (XOR with `--link`) | — |
| `--link STR` | | Link to track (XOR with `--hub`) | — |
| `--snapshot-table STR` | | Snapshot control table name (required) | — |
| `--snapshot-logic STR` | | Snapshot control logic name (required) | — |
| `--satellites STR` | | Comma-separated satellite names to include | — |

---

#### turbovault model list

List all Data Vault entities in a project, displayed as Rich tables.

```bash
# List all entity types
turbovault model list --project my_project

# List only hubs
turbovault model list --project my_project --type hubs

# List only satellites
turbovault model list --project my_project --type satellites
```

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--project NAME` | `-p` | Project name | — |
| `--type STR` | `-t` | `hubs`, `links`, `satellites`, `pits`, or `all` | `all` |

---

#### turbovault model validate

Validate the Data Vault model for a project and print any errors or warnings.

Runs the same validation engine as `turbovault generate --mode strict`. Exits with code `0` if valid, `1` if there are errors.

```bash
# Human-readable output
turbovault model validate --project my_project

# JSON output for scripting / CI
turbovault model validate --project my_project --json
```

JSON output format:
```json
{
  "project": "my_project",
  "valid": true,
  "errors": [],
  "warnings": [
    {"code": "HUB_002", "entity_type": "hub", "entity": "HUB_CUSTOMER", "message": "..."}
  ]
}
```

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--project NAME` | `-p` | Project name | — |
| `--json` | | Output results as JSON (useful for CI / scripting) | `false` |

---

#### turbovault model import-json

Bulk-import a Data Vault model from a JSON file matching the [Model Import Schema](../04_concepts/05_model-import-schema.md). This is the primary way to apply an AI-generated model proposal from the MCP server.

Existing entities with the same name are silently skipped (idempotent). Use `--dry-run` to validate the schema without writing anything.

```bash
# Import a proposal
turbovault model import-json --file ./proposal.json --project my_project

# Validate the schema only (no DB writes)
turbovault model import-json --file ./proposal.json --dry-run
```

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--file PATH` | `-f` | Path to model proposal JSON file (required) | — |
| `--project NAME` | `-p` | Project name (not required for `--dry-run`) | — |
| `--dry-run` | | Validate JSON structure without writing to the database | `false` |

> **See also:** [Model Import Schema](../04_concepts/05_model-import-schema.md) for the full JSON format reference, and [MCP Server](05_mcp-server.md) for AI-assisted model generation.

---

### turbovault serve

Start the Django development server to access the admin interface.

#### Basic Usage

```bash
turbovault serve
```

This starts the server on `http://127.0.0.1:8000/`

**Access points:**
- Admin: `http://127.0.0.1:8000/admin/`
- Home / Web Initializer: `http://127.0.0.1:8000/`
- MCP (AI tools): `http://127.0.0.1:8000/mcp`

The landing page (`/`) provides a guided wizard for creating new projects, which is the recommended starting point for first-time users.

> **See also:** [MCP Server guide](05_mcp-server.md) for connecting Claude Code or Claude Desktop.

#### Custom Port and Host

```bash
turbovault serve --port 9000 --host 0.0.0.0
```

#### Options

| Option | Short | Description | Default |
|--------|-------|-------------|------------|
| `--port INT` | `-p` | Port to run server on | 8000 |
| `--host STR` | `-h` | Host to bind to | 127.0.0.1 |
| `--help` | | Show help message | |

**Examples:**
```bash
# Run on port 9000
turbovault serve --port 9000

# Make accessible from other machines
turbovault serve --host 0.0.0.0

# Custom port and host
turbovault serve -p 3000 -h localhost
```

---

### turbovault reset

Reset the database by deleting all data and reinitializing.

#### Basic Usage

```bash
turbovault reset
```

**Warning:** This will:
1. Delete the database file
2. Run migrations to recreate tables
3. Prompt to create a new admin user
4. Populate templates

Use with caution - all data will be lost!

#### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--help` | | Show help message |

**Example:**
```bash
# Reset database (will prompt for confirmation)
turbovault reset
```

---

## Complete Workflow Examples

### Example 1: Quick Start (SQLite)

```bash
# 1. Initialise workspace
turbovault workspace init --db-engine sqlite3 --db-name db.sqlite3 \
  --stage-schema stage --rdv-schema rdv \
  --admin-username admin --admin-password changeme --admin-email admin@example.com

# 2. Create a project
turbovault project init --name my_project

# 3. Open admin to define your Data Vault model
turbovault serve
# Navigate to http://127.0.0.1:8000/admin/

# 4. Generate dbt project
turbovault generate --project my_project

# 5. Run the generated dbt project
cd projects/my_project/dbt_project
dbt deps && dbt compile && dbt run
```

### Example 2: Import Metadata from Excel

```bash
# Workspace already exists:
turbovault project init \
  --name sales_datavault \
  --source ./metadata/sales_sources.xlsx \
  --stage-schema stage \
  --rdv-schema rdv
```

### Example 3: Iteratively Refining Imported Metadata

The `import` command lets you re-import a file as many times as you need
to refine your Data Vault model. The default `merge` strategy means
existing entities get updated with your corrections — no duplicates, no
data loss.

```bash
# Initial import via project init
turbovault project init --name sales_datavault --source ./metadata.xlsx

# Edit the Excel file to fix a hashkey name or add a new hub...

# Re-import — updates existing entities, adds any new ones
turbovault import --project sales_datavault --source ./metadata.xlsx

# Preview the impact of a destructive replace before committing
turbovault import --project sales_datavault --source ./metadata.xlsx \
  --mode replace-all --dry-run

# Inspect the run history (newest first)
turbovault import-history --project sales_datavault
```

### Example 4: Migrate a Project via JSON Export

Use `turbovault generate --type json` to export a project, then re-import it into another workspace or under a new name:

```bash
# In the source workspace — export the model
turbovault generate --type json --project sales_datavault \
  --json-output ./sales_datavault_export.json

# In the target workspace — import from the JSON export
turbovault project init \
  --name sales_datavault \
  --source ./sales_datavault_export.json
```

The file extension (`.json`) is detected automatically — no extra flags required.

### Example 5: Full Non-Interactive Setup (CI/CD)

```bash
# Step 1: workspace
turbovault workspace init \
  --db-engine postgresql \
  --db-name company_vault \
  --db-host db.company.com \
  --db-user vault_user \
  --db-password "$DB_PASSWORD" \
  --skip-admin

# Step 2: project
turbovault project init \
  --name ci_project \
  --config config.yml

# Step 3: generate + archive
turbovault generate --project ci_project --mode strict --zip
```

### Example 6: Team Workflow

```bash
# Alice: set up workspace on shared DB and push
turbovault workspace init --db-engine postgresql --db-host db.company.com ...
git init && git add turbovault.yml .gitignore && git commit -m "Init workspace"
git push

# Alice: add a project
turbovault project init --name customer_vault
git add projects/customer_vault/config.yml
git commit -m "Add customer_vault project"
git push

# Bob: clone and start working
git clone https://github.com/company/company-datavault.git
cd company-datavault
turbovault generate --project customer_vault
```

---

## Tips and Tricks

### Check Current Version

```bash
turbovault --version
```

### Get Help

```bash
# General help
turbovault --help

# Command-specific help
turbovault workspace --help
turbovault workspace init --help
turbovault project --help
turbovault project init --help
turbovault import --help
turbovault import-history --help
turbovault generate --help
turbovault generation-history --help
turbovault serve --help
turbovault reset --help
```

### List Available Projects

When running `generate` without `--project`, you'll get an interactive list:

```bash
turbovault generate
# ? Select a project:
#   > sales_datavault
#     hr_datavault
#     marketing_datavault
```

### Template Management

```bash
# Populate templates from files (manual)
cd backend
python manage.py populate_templates

# Overwrite existing templates with file versions
python manage.py populate_templates --overwrite
```

### Validation Tips

```bash
# Check for validation errors without generating
turbovault generate --project my_project --mode strict
# If errors, fix in admin and regenerate

# Generate what you can (skip invalid)
turbovault generate --project my_project --mode lenient
```

---

## Troubleshooting

### "Module not found" Error

Make sure you've installed the package:
```bash
pip install -e .
```

### "Project already exists" Error

When running `init`, if a project with the same name already exists:

```
✗ Project 'my_project' already exists!
? Do you want to delete the existing project and start fresh? (y/N)
```

Choose:
- **Yes** to delete and recreate
- **No** to cancel

**Note:** Deleting removes all associated data (hubs, links, satellites, etc.).

### "No templates found" Warning

If you see warnings about missing templates:

```bash
# Populate templates from files
cd backend
python manage.py populate_templates
```

This is automatically done during `turbovault project init` but can be run manually if needed.

### Generation Validation Errors

If generation fails with validation errors:

1. Review the error messages (they include error codes like HUB_001, LNK_001)
2. Fix the issues in Django Admin
3. Re-run generation

Or use lenient mode to skip invalid entities:
```bash
turbovault generate --project my_project --mode lenient
```

### Django Admin Login

Create a superuser if you skipped the initial prompt:
```bash
cd backend
python manage.py createsuperuser
```

Then use those credentials in the admin interface.

### Permission Errors on Generated Files

On Windows, if you get permission errors:
```bash
# Close any applications with files open in output directory
# Then regenerate
turbovault generate --project my_project --output ./new_output
```

