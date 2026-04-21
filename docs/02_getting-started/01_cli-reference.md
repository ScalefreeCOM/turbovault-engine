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
| `turbovault model` | Create and inspect Data Vault entities (hubs, links, satellites, PITs) |
| `turbovault generate` | Generate dbt project or export model to JSON / DBML |
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

### turbovault generate

Generate a complete dbt project from your Data Vault model.

#### Basic Usage

```bash
turbovault generate --project my_project
```

This will:
1. Export your Data Vault model
2. Validate the model (optional)
3. Generate SQL models with datavault4dbt macros
4. Generate YAML schemas for all models
5. Create organized folder structure
6. Output ready-to-use dbt project

**Output location:** `./output/{project_name}/`

#### Generate to Custom Directory

```bash
turbovault generate --project sales_datavault --output ./my_dbt_projects/sales
```

#### Generate with ZIP Archive

```bash
turbovault generate --project sales_datavault --zip
```

Creates both the folder and a `.zip` file.

#### Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--project NAME` | `-p` | Project name (or interactive selection) | Interactive |
| `--output PATH` | `-o` | Output directory path (only for type=dbt) | `exports/dbt_project/` |
| `--mode MODE` | `-m` | Validation mode: `strict` or `lenient` | `strict` |
| `--zip` | `-z` | Create ZIP archive after generation (only for type=dbt) | `false` |
| `--skip-validation` | | Skip pre-generation validation | `false` |
| `--dry-run` | | Validate model only, no files written — exits 0 if valid | `false` |
| `--no-v1-satellites` | | Skip generating satellite _v1 views (only for type=dbt) | `false` |
| `--type TYPE` | `-t` | Export type: `dbt`, `json`, or `dbml` | Interactive |
| `--json-output PATH` | | JSON output file path (only for type=json) | Auto-generated |
| `--json-format FORMAT` | | JSON format: `compact` or `pretty` (only for type=json) | `pretty` |
| `--dbml-output PATH` | | DBML output file path (only for type=dbml) | Auto-generated |
| `--help` | | Show help message | |

> **See also:** [Configuration Overview](../03_configuration/01_overview.md) for the full output path priority order (CLI flag → config.yml → convention default) and [Project Config Reference](../03_configuration/03_project-schema.md) for all config.yml fields.

#### Validation Modes

**Strict mode (default):**
- Stops generation on first validation error
- Ensures all entities are correctly configured
- Recommended for production

**Lenient mode:**
- Skips invalid entities
- Continues with valid entities
- Useful for incremental development

```bash
# Use lenient mode
turbovault generate --project my_project --mode lenient
```

#### Skip Satellite V1 Views

By default, each satellite generates two models:
- `sat_*_v0.sql` - Core satellite with incremental logic
- `sat_*_v1.sql` - View with load_end_date

Skip v1 generation:
```bash
turbovault generate --project my_project --no-v1-satellites
```

**Examples:**
```bash
# Interactive type selection (default)
turbovault generate -p sales_datavault

# Generate dbt project
turbovault generate --type dbt -p sales_datavault

# Generate with custom output and ZIP
turbovault generate --type dbt -p sales_datavault -o ./dbt_output --zip

# Generate in lenient mode without v1 satellites
turbovault generate --type dbt -p sales_datavault --mode lenient --no-v1-satellites

# Skip validation entirely (not recommended)
turbovault generate --type dbt -p sales_datavault --skip-validation

# Dry run: validate and report counts without writing any files
turbovault generate --type dbt -p sales_datavault --dry-run

# Export to JSON
turbovault generate --type json -p sales_datavault

# Export JSON to custom path with pretty formatting
turbovault generate --type json --json-output ./exports/model.json --json-format pretty -p sales_datavault

# Export compact JSON format
turbovault generate --type json --json-format compact -p sales_datavault
```

#### Export Types

The `generate` command supports three export types via the `--type` flag:

**`dbt` - Generate dbt project (default if not specified):**
```bash
turbovault generate --type dbt --project my_project
```
Creates a complete dbt project with all models, macros, and configuration.

**`json` - Export Data Vault model to JSON:**
```bash
turbovault generate --type json --project my_project
```
Exports the complete Data Vault model as a structured JSON export for inspection or integration with other tools.

The JSON export includes:
- Project metadata
- Sources and stages
- Hubs, links, satellites
- PITs and reference tables
- Snapshot controls

**`dbml` - Export Data Vault model as DBML diagram:**
```bash
turbovault generate --type dbml --project my_project
```
Exports the model as [DBML (Database Markup Language)](https://dbml.dbdiagram.io/), which can be rendered in tools like [dbdiagram.io](https://dbdiagram.io) to visualize the entity relationships.

**Interactive selection:** If `--type` is not provided, you'll be prompted to choose:
```bash
turbovault generate --project my_project
# ? Select export type:
#   > dbt - Generate dbt project
#     json - Export Data Vault model to JSON
#     dbml - Export Data Vault model as DBML diagram
```

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

The landing page (`/`) provides a guided wizard for creating new projects, which is the recommended starting point for first-time users.

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

### Example 3: Migrate a Project via JSON Export

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

### Example 4: Full Non-Interactive Setup (CI/CD)

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

### Example 5: Team Workflow

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
turbovault generate --help
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

