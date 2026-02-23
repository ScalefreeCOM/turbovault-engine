# TurboVault Configuration Guide

## Overview

TurboVault uses a **YAML-only configuration system** with two types of config files:

1. **`turbovault.yml`** - Global application settings (database, project root, admin credentials)
2. **`projects/<name>/config.yml`** - Per-project configurations (schemas, naming patterns, output settings)

---

## Quick Start

### 1. Create Global Config

Run TurboVault for the first time - it will auto-create `~/.turbovault.yml`:

```yaml
database:
  engine: sqlite3
  name: db.sqlite3

project_root: .
```

### 2. Initialize a Project

```bash
turbovault init --interactive

# Or non-interactive with flags:
turbovault init --name my_project --source ./data.xlsx --stage-schema stage --rdv-schema rdv

```

This creates:
```
projects/my_project/
  ├── config.yml      # Project-specific config
  ├── dbt_project/    # Generated dbt files
  └── exports/        # Exports and artifacts
```

### 3. Edit Configuration

Edit `projects/my_project/config.yml` to customize schemas, naming patterns, etc.
Changes take effect immediately - no reload needed!

---

## Global Config (`turbovault.yml`)

### Location

TurboVault searches for config in this order:
1. `./turbovault.yml` (current directory)
2. `~/.turbovault.yml` (user home)

The first file found is used.

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

# Project root directory (optional, defaults to current directory)
project_root: /home/user/turbovault_workspace

# Auto-create admin user on first startup (optional)
admin:
  username: admin
  password: changeme123
  email: admin@example.com

# Global defaults for new projects (optional)
defaults:
  stage_schema: stage
  rdv_schema: rdv
  hashdiff_naming: "hd_{entity_name}"
  hashkey_naming: "hk_{entity_name}"
```

### Database Engines

#### SQLite (Default)
```yaml
database:
  engine: sqlite3
  name: db.sqlite3  # Relative to project_root
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
  account: myaccount
  user: myuser
  password: secret
  database: turbovault_db
  schema: public
  warehouse: compute_wh
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
  
  # Database names (optional, uses default if not specified)
  stage_database: raw_vault
  rdv_database: core_vault
  
  # Naming patterns (optional, uses defaults if not specified)
  hashdiff_naming: "hd_{entity_name}"
  hashkey_naming: "hk_{entity_name}"
  satellite_v0_naming: "sat_{entity_name}_v0"
  satellite_v1_naming: "sat_{entity_name}_v1"

# Output configuration
output:
  dbt_project_dir: ./dbt_project    # Where to generate dbt files
  create_zip: true                   # Create ZIP archive
  export_sources: true               # Include source definitions
```

### Required Fields

Only these are required:
```yaml
project:
  name: my_project

configuration:
  stage_schema: stage
  rdv_schema: rdv

output:
  dbt_project_dir: ./dbt_project
```

All other fields have sensible defaults.

### Naming Patterns

Naming patterns use placeholders:

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `{entity_name}` | Hub/link/satellite name | `customer` → `hk_customer` |

**Default patterns:**
- `hashdiff_naming`: `hd_{entity_name}`
- `hashkey_naming`: `hk_{entity_name}`
- `satellite_v0_naming`: `sat_{entity_name}_v0`
- `satellite_v1_naming`: `sat_{entity_name}_v1`

---

## Configuration Loading

### How It Works

1. **Global config** loaded once at Django startup
2. **Project configs** loaded on-demand from YAML (always fresh)
3. **No caching** - edit YAML, changes apply immediately
4. **No database storage** - YAML is the single source of truth

### In Code

```python
from engine.models import Project

# Get project
project = Project.objects.get(name="customer_mdm")

# Load config from YAML
config = project.load_config()

# Access values
print(config.configuration.stage_schema)
print(config.output.dbt_project_dir)
```

---

## Project Folder Structure

```
{PROJECT_ROOT}/
├── turbovault.yml          # Global config
├── projects/
│   ├── customer_mdm/
│   │   ├── config.yml      # Project config
│   │   ├── dbt_project/    # Generated dbt files
│   │   ├── exports/        # JSON/ZIP exports
│   │   └── metadata/       # Optional: source files
│   └── supplier_vault/
│       ├── config.yml
│       └── ...
└── db.sqlite3              # SQLite database (if using SQLite)
```

**Key points:**
- `PROJECT_ROOT` defined in `turbovault.yml`
- Each project has its own folder  
- Config.yml is the source of truth for project settings
- Generated files stay within project folder

---

## Multi-User Setup

For teams sharing a database:

**User A's turbovault.yml:**
```yaml
database:
  engine: postgresql
  name: shared_db
  host: db.company.com
  
project_root: /home/alice/turbovault
```

**User B's turbovault.yml:**
```yaml
database:
  engine: postgresql
  name: shared_db
  host: db.company.com
  
project_root: /home/bob/my_vault
```

- Both share the same database (metadata, models)
- Each has their own project folders locally
- Database stores only relative paths (`projects/customer_mdm`)
- Resolved to absolute paths at runtime

---

## Common Workflows

### Initialize New Project

```bash
turbovault init --interactive
```

### Initialize from Existing Config

```bash
turbovault init --config ./my_config.yml
```

### Generate dbt Project

```bash
turbovault generate --project customer_mdm
```

### Export to JSON

```bash
turbovault generate --project customer_mdm --type json
```

---

## Troubleshooting

### "Config file not found"

**Cause:** Project exists in database but config.yml is missing

**Solution:** TurboVault auto-creates minimal config. Check logs for the generated file location.

### "Cannot locate config.yml"

**Cause:** `project_directory` not set in database

**Solution:** This shouldn't happen for new projects. For old projects, set it manually:
```python
project.project_directory = "projects/customer_mdm"
project.save()
```

### Changes not taking effect

**Cause:** Editing wrong config file

**Solution:** Ensure you're editing `projects/<name>/config.yml`, not `turbovault.yml`

### Database connection error

**Cause:** Incorrect database config in `turbovault.yml`

**Solution:** Verify database credentials and connectivity

---

## Best Practices

✅ **DO:**
- Store `turbovault.yml` in user home (`~/.turbovault.yml`)
- Keep project configs in version control
- Use descriptive project names
- Set clear schema names per environment

❌ **DON'T:**
- Put passwords in version-controlled configs (use env vars)
- Edit generated dbt files manually
- Share `turbovault.yml` between users (each needs their own)

---

## Migration from Old System

**If you have projects from before the YAML-only refactor:**

1. **Fresh start** (recommended):
   ```bash
   turbovault reset  # Clears database
   turbovault init --interactive  # Start fresh
   ```

2. **Manual migration** (if needed):
   - Extract old config from database
   - Create `projects/<name>/config.yml` manually
   - Set `project.project_directory` in database
   - Test with `turbovault generate`

---

## See Also

- [README.md](../README.md) - General usage
- [turbovault.example.yml](../turbovault.example.yml) - Global config example
- [config.example.yml](../config.example.yml) - Project config example
