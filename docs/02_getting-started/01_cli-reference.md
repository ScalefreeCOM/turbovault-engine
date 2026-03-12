---
sidebar_position: 3
sidebar_label: CLI Reference
title: CLI Reference
---

# TurboVault CLI User Guide

## Installation

Install TurboVault Engine in development mode:

```bash
pip install -e .
```

This makes the `turbovault` command available in your terminal.

## Commands Overview

TurboVault uses a **two-step setup**: initialise the workspace once, then create projects inside it.

| Command | Description |
|---|---|
| `turbovault workspace init` | Initialise directory as a workspace |
| `turbovault workspace status` | Show DB connection, project count, migration status |
| `turbovault project init` | Create a new Data Vault project in the workspace |
| `turbovault project list` | List all projects in the workspace |
| `turbovault generate` | Generate dbt project / export Data Vault model to JSON |
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
| `--source PATH` | `-s` | Source metadata file (`.xlsx` or `.db`) | — |
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
| `--output PATH` | `-o` | Output directory path (only for type=dbt) | `./output/{project}` |
| `--mode MODE` | `-m` | Validation mode: `strict` or `lenient` | `strict` |
| `--zip` | `-z` | Create ZIP archive after generation (only for type=dbt) | `false` |
| `--skip-validation` | | Skip pre-generation validation | `false` |
| `--no-v1-satellites` | | Skip generating satellite _v1 views (only for type=dbt) | `false` |
| `--type TYPE` | `-t` | Export type: `dbt` or `json` | Interactive |
| `--json-output PATH` | | JSON output file path (only for type=json) | Auto-generated |
| `--json-format FORMAT` | | JSON format: `compact` or `pretty` (only for type=json) | `pretty` |
| `--help` | | Show help message | |

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

# Export to JSON
turbovault generate --type json -p sales_datavault

# Export JSON to custom path with pretty formatting
turbovault generate --type json --json-output ./exports/model.json --json-format pretty -p sales_datavault

# Export compact JSON format
turbovault generate --type json --json-format compact -p sales_datavault
```

#### Export Types

The `generate` command supports two export types via the `--type` flag:

**`dbt` - Generate dbt project (default if not specified):**
```bash
turbovault generate --type dbt --project my_project
```
Creates a complete dbt project with all models, macros, and configuration.

**`json` - Export Data Vault model to JSON:**
```bash
turbovault generate --type json --project my_project
```
Exports the complete Data Vault model as JSON for inspection or integration.

**Interactive selection:** If `--type` is not provided, you'll be prompted to choose:
```bash
turbovault generate --project my_project
# ? Select export type:
#   > dbt - Generate dbt project
#     json - Export Data Vault model to JSON
```

The JSON export includes:
- Project metadata
- Sources and stages
- Hubs, links, satellites
- PITs and reference tables
- Snapshot controls

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

### Example 3: Full Non-Interactive Setup (CI/CD)

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

### Example 4: Team Workflow

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

