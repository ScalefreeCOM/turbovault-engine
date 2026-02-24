# TurboVault Configuration Guide

## Overview

TurboVault uses a **YAML-only configuration system** with two types of config files:

1. **`turbovault.yml`** — Global workspace settings (database connection, schema defaults)
2. **`projects/<name>/config.yml`** — Per-project settings (schemas, naming patterns, output overrides)

---

## Quick Start

### 1. Initialise a Workspace

Run once in your working directory to create `turbovault.yml` and set up the database:

```bash
turbovault workspace init

# Or fully non-interactive:
turbovault workspace init --db-engine sqlite3 --db-name db.sqlite3 \
  --stage-schema stage --rdv-schema rdv --skip-admin
```

### 2. Create a Project

```bash
turbovault project init --interactive

# Or non-interactive with flags:
turbovault project init --name my_project --source ./data.xlsx \
  --stage-schema stage --rdv-schema rdv
```

This creates:
```
projects/my_project/
├── config.yml      # Project-specific settings
└── exports/        # All generated export artifacts (created lazily per type)
```

> **Note:** The `exports/` sub-folders are created on demand the first time you run
> `turbovault generate` with the respective export type.

### 3. Generate Exports

```bash
# dbt project → projects/my_project/exports/dbt_project/
turbovault generate --project my_project

# JSON export → projects/my_project/exports/json/
turbovault generate --project my_project --type json

# DBML / ER diagram → projects/my_project/exports/dbml/
turbovault generate --project my_project --type dbml
```

### 4. Edit Configuration

Edit `projects/my_project/config.yml` to customise schemas, naming patterns, or output paths.
Changes take effect immediately — no reload needed.

---

## Global Config (`turbovault.yml`)

### Location

`turbovault.yml` is searched for in the current working directory. Run all TurboVault
commands from the directory that contains this file (your **workspace root**).

### Complete Example

```yaml
# Database configuration (required)
database:
  engine: postgresql  # Options: sqlite3, postgresql, mysql, mssql, snowflake
  name: turbovault_db
  user: myuser
  password: mypassword
  host: localhost
  port: 5432

# Global defaults applied to new projects (optional)
defaults:
  stage_schema: stage
  rdv_schema: rdv
  hashdiff_naming: "hd_[[ satellite_name ]]"
  hashkey_naming: "hd_[[ entity_name ]]"
```

> **Note:** `turbovault.yml` is created automatically by `turbovault workspace init`.

### Database Engines

#### SQLite (Default)
```yaml
database:
  engine: sqlite3
  name: db.sqlite3  # Relative to workspace root (where turbovault.yml lives)
```

#### PostgreSQL
```yaml
database:
  engine: postgresql
  name: turbovault_db
  user: postgres
  password: secret
  host: localhost
  port: 5432
```

#### MySQL
```yaml
database:
  engine: mysql
  name: turbovault_db
  user: root
  password: secret
  host: localhost
  port: 3306
```

#### SQL Server
```yaml
database:
  engine: mssql
  name: turbovault_db
  user: sa
  password: YourPassword123
  host: localhost
  port: 1433
  options:
    driver: "ODBC Driver 17 for SQL Server"
```

#### Snowflake
```yaml
database:
  engine: snowflake
  name: turbovault_db
  user: myuser
  password: secret
  host: myaccount.snowflakecomputing.com
```

---

## Project Config (`projects/<name>/config.yml`)

### Complete Example

```yaml
# Project metadata
project:
  name: customer_mdm
  description: Customer Master Data Management

# Source metadata import (optional)
source:
  type: excel
  path: ./metadata/sources.xlsx

# Data Vault configuration
configuration:
  # Schema names (required)
  stage_schema: stage_customer
  rdv_schema: rdv_customer

  # Database names (optional)
  stage_database: raw_vault
  rdv_database: core_vault

  # Naming patterns (optional – uses defaults if omitted)
  hashdiff_naming: "hd_[[ satellite_name ]]"
  hashkey_naming: "hd_[[ entity_name ]]"
  satellite_v0_naming: "[[ satellite_name ]]_v0"
  satellite_v1_naming: "[[ satellite_name ]]_v1"

# Output configuration (all fields optional)
output:
  create_zip: false          # Create a ZIP archive of the generated dbt project
  export_sources: true       # Include source system definitions in JSON export

  # Custom output directories (optional)
  # When omitted, the generate command uses the convention-based defaults below.
  # dbt_project_dir: ./custom/dbt_output
  # json_output_dir: ./custom/json_exports
  # dbml_output_dir: ./custom/dbml_exports
```

### Required Fields

Only these are required — everything else has sensible defaults:

```yaml
project:
  name: my_project

configuration:
  stage_schema: stage
  rdv_schema: rdv
```

### Output Paths

TurboVault uses **convention-based output directories** inside your project folder.
You can override any of them in `config.yml` or with CLI flags.

| Export type | Default path | Config key | CLI flag |
|---|---|---|---|
| dbt project | `exports/dbt_project/` | `output.dbt_project_dir` | `--output` |
| JSON export | `exports/json/` | `output.json_output_dir` | `--json-output` |
| DBML / ER diagram | `exports/dbml/` | `output.dbml_output_dir` | `--dbml-output` |

**Priority order** (highest → lowest):

1. CLI flag (`--output`, `--json-output`, `--dbml-output`)
2. Config value in `config.yml` (`output.dbt_project_dir`, etc.)
3. Convention default (`exports/<type>/` inside the project folder)

**Example: custom output dirs in `config.yml`:**

```yaml
output:
  dbt_project_dir: /shared/dbt/customer_mdm
  json_output_dir: ./exports/json
  dbml_output_dir: ./exports/dbml
```

Both relative and absolute paths are supported.

### Naming Patterns

Naming patterns use placeholders:

| Placeholder | Description | Example |
|---|---|---|
| `{entity_name}` | Hub/link/satellite name | `customer` → `hk_customer` |

**Default patterns:**
- `hashdiff_naming`: `hd_[[ satellite_name ]]`
- `hashkey_naming`: `hd_[[ entity_name ]]`
- `satellite_v0_naming`: `[[ satellite_name ]]_v0`
- `satellite_v1_naming`: `[[ satellite_name ]]_v1`

---

## Configuration Loading

### How It Works

1. **Global config** (`turbovault.yml`) is loaded once at Django startup
2. **Project configs** (`config.yml`) are loaded on-demand from YAML — always fresh
3. **No caching** — edit YAML and changes apply on the next command run
4. **No database storage** — YAML is the single source of truth for configuration

### `turbovault serve` and the Database

`turbovault serve` launches the Django admin as a subprocess. It automatically
passes the workspace path to Django via the `TURBOVAULT_CONFIG_PATH` environment
variable, so the admin always connects to the database defined in **your workspace's
`turbovault.yml`** regardless of how the process is started.

---

## Workspace Folder Structure

```
{WORKSPACE_ROOT}/
├── turbovault.yml              # Global workspace config (database, defaults)
├── db.sqlite3                  # SQLite database (when using sqlite3 engine)
└── projects/
    ├── customer_mdm/
    │   ├── config.yml          # Project config (schemas, naming, output overrides)
    │   └── exports/            # All generated artifacts
    │       ├── dbt_project/    # Generated dbt project (created on first generate --type dbt)
    │       ├── json/           # JSON exports    (created on first generate --type json)
    │       └── dbml/           # DBML exports    (created on first generate --type dbml)
    └── supplier_vault/
        ├── config.yml
        └── exports/
            └── ...
```

**Key points:**
- Only `exports/` is created at `project init` time — sub-folders are created lazily on first use
- Each project is fully self-contained under its own folder
- `config.yml` is the source of truth for all project-level settings
- Generated files never leave the project folder (unless you set a custom absolute path)

---

## Multi-User Setup

For teams sharing a database:

**User A's `turbovault.yml`:**
```yaml
database:
  engine: postgresql
  name: shared_db
  host: db.company.com
  user: alice
  password: secret
```

**User B's `turbovault.yml`:**
```yaml
database:
  engine: postgresql
  name: shared_db
  host: db.company.com
  user: bob
  password: secret
```

- Both share the same database (metadata, models)
- Each generates output into their own local project folders
- Database stores only relative paths (`projects/customer_mdm`)

---

## Common Workflows

### Initialise New Workspace

```bash
turbovault workspace init --db-engine sqlite3 --db-name db.sqlite3 \
  --stage-schema stage --rdv-schema rdv --skip-admin
```

### Create a Project

```bash
turbovault project init --name customer_mdm --stage-schema stage --rdv-schema rdv
```

### Create from Existing Config File

```bash
turbovault project init --config ./my_config.yml
```

### Generate dbt Project

```bash
# Default: exports/dbt_project/ inside the project folder
turbovault generate --project customer_mdm

# Custom output directory via CLI flag
turbovault generate --project customer_mdm --output /shared/dbt/customer_mdm
```

### Export to JSON

```bash
# Default: exports/json/ inside the project folder
turbovault generate --project customer_mdm --type json

# Custom output file
turbovault generate --project customer_mdm --type json --json-output ./my_export.json
```

### Export to DBML

```bash
# Default: exports/dbml/ inside the project folder
turbovault generate --project customer_mdm --type dbml

# Custom output file
turbovault generate --project customer_mdm --type dbml --dbml-output ./erd.dbml
```

---

## Troubleshooting

### "Not a TurboVault workspace"

**Cause:** `turbovault.yml` not found in the current directory.

**Solution:** Either change to your workspace directory, or run `turbovault workspace init`
to initialise a new workspace here.

### "Config file not found"

**Cause:** Project exists in the database but `config.yml` is missing from the project folder.

**Solution:** TurboVault auto-creates a minimal config. Check the logs for the generated file location.

### "Cannot locate config.yml"

**Cause:** `project_directory` not set in the database record.

**Solution:** For old projects, set it manually:
```python
project.project_directory = "projects/customer_mdm"
project.save()
```

### Changes not taking effect

**Cause:** Editing the wrong config file.

**Solution:** Ensure you're editing `projects/<name>/config.yml`, not `turbovault.yml`.

### `turbovault serve` connects to wrong database

**Cause:** Running `turbovault serve` from outside the workspace directory, or an old
installation where `TURBOVAULT_CONFIG_PATH` is not passed to the subprocess.

**Solution:** Always run `turbovault serve` from your workspace root (the directory
containing `turbovault.yml`). The current version passes the workspace path automatically.

### Database connection error

**Cause:** Incorrect database config in `turbovault.yml`.

**Solution:** Verify database credentials and connectivity, then re-run `turbovault workspace init --overwrite`.

---

## Best Practices

✅ **DO:**
- Run all TurboVault commands from your workspace root
- Keep `projects/<name>/config.yml` in version control
- Use descriptive project names (they become folder names)
- Set clear schema names per environment

❌ **DON'T:**
- Put passwords in version-controlled configs (use environment variables or a secrets manager)
- Edit generated dbt files manually — re-run `generate` instead
- Share `turbovault.yml` between users when database credentials differ

---

## See Also

- [README.md](../README.md) — General usage and quick start
- [CLI_GUIDE.md](CLI_GUIDE.md) — Full CLI command reference
- [workspace.md](workspace.md) — Workspace setup and management
