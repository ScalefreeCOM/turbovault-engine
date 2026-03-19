---
sidebar_position: 7
sidebar_label: Project Config
title: Project Config
---

# Configuration Schema Reference

This document is the **complete field-by-field reference** for the `config.yml` project configuration file. For a conceptual introduction and quick-start examples, see the [Configuration Overview](./01_overview.md).

## Overview

The `config.yml` file is the primary way to configure TurboVault Engine. It defines:
- Project metadata and settings
- Source metadata import options
- Database connection (optional)
- Data Vault configuration
- Output and export options

## File Structure

```yaml
project:           # Project identification (required)
source:            # Metadata import source (optional)
database:          # Database configuration (optional)
configuration:     # Data Vault settings (optional, has defaults)
output:            # Generation output settings (required)
```

---

## Configuration Sections

### `project` (Required)

Project metadata and identification.

**Fields:**

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `name` | string | Yes | Project name, used as dbt project name if not overridden | `"my_datavault"` |
| `description` | string | No | Project description | `"Sales Data Vault"` |

**Example:**

```yaml
project:
  name: "customer_datavault"
  description: "Customer 360 Data Vault Implementation"
```

**Validation:**
- `name` cannot be empty or only whitespace
- `name` is automatically trimmed

---

### `source` (Optional)

Configuration for importing source metadata from external sources.

**Currently Supported Types:**
- `excel` - Import from Excel spreadsheet
- `sqlite` - Import from SQLite database

**Fields for Excel Source:**

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `type` | string | Yes | Must be `"excel"` | `"excel"` |
| `path` | string | Yes | Path to Excel file (relative or absolute) | `"./metadata/sources.xlsx"` |

**Fields for SQLite Source:**

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `type` | string | Yes | Must be `"sqlite"` | `"sqlite"` |
| `path` | string | Yes | Path to SQLite database file | `"./metadata/sources.sqlite"` |

**Example:**

```yaml
source:
  type: excel
  path: "./metadata/source_metadata.xlsx"
```

**Behavior:**
- If `source` is not provided, start with an empty project
- Source file doesn't need to exist at config load time (warning only)
- Relative paths are resolved from the config file location

---

### `database` (Optional)

> **Important Note**: Database configuration should typically be defined at the workspace level in `turbovault.yml` (created via `turbovault workspace init`), not in the project's `config.yml`. This allows all projects in a workspace to share the same database connection. It is documented here for completeness.

Database connection configuration. If not specified, SQLite is used by default.

**Fields:**

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `engine` | string | Yes | Database backend engine | `"postgresql"` |
| `name` | string | Yes | Database name (or file path for SQLite) | `"turbovault_db"` |
| `user` | string | Conditional* | Database username | `"turbovault_user"` |
| `password` | string | Conditional* | Database password | `"secretpassword"` |
| `host` | string | Conditional* | Database host | `"localhost"` |
| `port` | integer | No | Database port (uses default if omitted) | `5432` |
| `options` | object | No | Additional database-specific options | See examples below |

\* Required for all engines except `sqlite3`

**Supported Engines:**

| Engine Value | Database | Default Port | Driver Package |
|-------------|----------|--------------|----------------|
| `sqlite3` | SQLite | N/A | Built-in |
| `postgresql` | PostgreSQL | 5432 | `psycopg2-binary` |
| `mysql` | MySQL/MariaDB | 3306 | `mysqlclient` |
| `mssql` | SQL Server | 1433 | `mssql-django` |
| `oracle` | Oracle | 1521 | `cx_Oracle` |
| `snowflake` | Snowflake | N/A | `django-snowflake` |

**Examples:**

**Default SQLite (no configuration needed):**
```yaml
# No database section = SQLite with default path
```

**Custom SQLite:**
```yaml
database:
  engine: sqlite3
  name: "./data/custom.db"
```

**PostgreSQL:**
```yaml
database:
  engine: postgresql
  name: turbovault_db
  user: turbovault_user
  password: your_password
  host: localhost
  port: 5432
  options:
    sslmode: require
    connect_timeout: 10
```

**MySQL:**
```yaml
database:
  engine: mysql
  name: turbovault_db
  user: turbovault_user
  password: your_password
  host: localhost
  port: 3306
  options:
    charset: utf8mb4
    init_command: "SET sql_mode='STRICT_TRANS_TABLES'"
```

**SQL Server:**
```yaml
database:
  engine: mssql
  name: turbovault_db
  user: turbovault_user
  password: your_password
  host: localhost
  port: 1433
  options:
    driver: "ODBC Driver 17 for SQL Server"
```

**Oracle:**
```yaml
database:
  engine: oracle
  name: xe
  user: turbovault_user
  password: your_password
  host: localhost
  port: 1521
```

**Snowflake:**
```yaml
database:
  engine: snowflake
  name: turbovault_db
  user: turbovault_user
  password: your_password
  host: your_account.snowflakecomputing.com
  options:
    account: your_account
    warehouse: COMPUTE_WH
    database: TURBOVAULT_DB
    schema: PUBLIC
```

**Validation:**
- For non-SQLite engines, `user`, `password`, and `host` are required
- Missing required database drivers will generate a warning with installation instructions

**See Also:** [Database Configuration Guide](/docs/03_configuration/02_database.md) for detailed setup instructions.

---

### `configuration` (Optional)

Project-level Data Vault configuration. If not provided, defaults are used.

**Fields:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `stage_schema` | string | No | `"stage"` | Schema name for staging layer |
| `stage_database` | string | No | `null` | Database name for staging layer (optional) |
| `rdv_schema` | string | No | `"rdv"` | Schema name for Raw Data Vault layer |
| `rdv_database` | string | No | `null` | Database name for Raw Data Vault layer (optional) |
| `bdv_schema` | string | No | `"bdv"` | Schema name for Business Data Vault layer |
| `bdv_database` | string | No | `null` | Database name for Business Data Vault layer (optional) |
| `hashdiff_naming` | string | No | `"hd_[[ satellite_name ]]"` | Naming pattern for hashdiff columns |
| `hashkey_naming` | string | No | `"hk_[[ entity_name ]]"` | Naming pattern for hub/link hashkey columns |
| `satellite_v0_naming` | string | No | `"[[ satellite_name ]]_v0"` | Naming pattern for v0 satellite models |
| `satellite_v1_naming` | string | No | `"[[ satellite_name ]]_v1"` | Naming pattern for v1 satellite models |

**Example:**

```yaml
configuration:
  stage_schema: "stg"
  stage_database: "dw_raw"
  rdv_schema: "raw_vault"
  bdv_schema: "business_vault"
  hashdiff_naming: "hd_[[ satellite_name ]]"
  hashkey_naming: "hk_[[ entity_name ]]"
  satellite_v0_naming: "[[ satellite_name ]]_v0"
  satellite_v1_naming: "[[ satellite_name ]]_v1"
```

**Minimal Example (use defaults):**
```yaml
configuration:
  stage_schema: "stage"
  rdv_schema: "rdv"
  bdv_schema: "bdv"
```

**Validation:**
- Schema names must be valid SQL identifiers
- Only letters, numbers, underscores, and hyphens are allowed
- Schema names cannot be empty

---

### `output` (Optional)

dbt project generation and export configuration. All fields are optional — when omitted, TurboVault uses **convention-based output directories** inside the project folder.

**Fields:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `dbt_project_dir` | string | No | `exports/dbt_project/` | Override directory where the dbt project is generated |
| `json_output_dir` | string | No | `exports/json/` | Override directory for JSON exports |
| `dbml_output_dir` | string | No | `exports/dbml/` | Override directory for DBML exports |
| `create_zip` | boolean | No | `false` | Whether to create a ZIP archive of the generated dbt project |
| `export_sources` | boolean | No | `true` | Include source system definitions in export |

**Example:**

```yaml
output:
  create_zip: true
  export_sources: true
```

**Minimal Example (use all convention defaults):**
```yaml
# output section can be omitted entirely
```

**Override specific output paths:**
```yaml
output:
  dbt_project_dir: "/shared/dbt/customer_mdm"
  json_output_dir: "./exports/json"
  dbml_output_dir: "./exports/dbml"
```

**Path Resolution:**
- Paths are automatically resolved to absolute paths
- `~` (home directory) is expanded
- Relative paths are resolved from the project folder location

**Priority order** (highest → lowest):
1. CLI flag (`--output`, `--json-output`, `--dbml-output`)
2. Config value in `config.yml` (`output.dbt_project_dir`, etc.)
3. Convention default (`exports/<type>/` inside the project folder)

---

## Complete Configuration Example

### Minimal Configuration

```yaml
project:
  name: "minimal_project"

output:
  dbt_project_dir: "./dbt_output"
```

### Full Configuration with PostgreSQL

```yaml
project:
  name: "enterprise_datavault"
  description: "Enterprise Customer 360 Data Vault"

source:
  type: excel
  path: "./metadata/source_definitions.xlsx"

database:
  engine: postgresql
  name: turbovault_production
  user: dv_admin
  password: ${DB_PASSWORD}  # Use environment variable (requires external tool)
  host: db.example.com
  port: 5432
  options:
    sslmode: require
    connect_timeout: 10

configuration:
  stage_schema: "stg"
  stage_database: "dw_staging"
  rdv_schema: "rdv"
  rdv_database: "dw_core"
  bdv_schema: "bdv"
  bdv_database: "dw_core"
  hashdiff_naming: "hd_[[ satellite_name ]]"
  hashkey_naming: "hk_[[ entity_name ]]"

output:
  dbt_project_dir: "/shared/dbt/enterprise_dv"
  create_zip: true
  export_sources: true
```

---

## Validation

TurboVault validates your configuration when loading:

### Schema Validation (Pydantic)
- **Type checking** - Ensures fields have correct types
- **Required fields** - Verifies all required fields are present
- **Value constraints** - Checks valid values (e.g., valid engine types)
- **Cross-field validation** - Validates dependencies between fields

### Additional Validation
- **File existence** - Warns if source files don't exist
- **Path resolution** - Resolves and validates paths
- **Database drivers** - Warns if required drivers aren't installed
- **SQL identifiers** - Validates schema names

### Validation Errors

If validation fails, you'll see detailed error messages:

```
Configuration validation failed in config.yml:
  - project.name: Field required
  - output.dbt_project_dir: Field required
  - database.user: Database engine 'postgresql' requires the following fields: user, password, host
```

---

## Environment-Specific Configuration

Manage multiple environments with separate config files:

```bash
# Development
config.dev.yml

# Staging
config.staging.yml

# Production
config.prod.yml
```

**Usage:**
```bash
# Copy the desired environment config to the active config location
cp config.dev.yml config.yml

# Alternatively use project folders for environments
turbovault generate --project my_project_dev
```

---

## Best Practices

### 1. Version Control

**Do commit:**
- `config.example.yml` - Template with placeholders
- Environment-specific configs with defaults

**Don't commit:**
- Passwords or secrets
- Production database credentials
- Personal development configs

**Use `.gitignore`:**
```gitignore
config.local.yml
config.prod.yml
.env
```

### 2. Security

- **Never commit passwords** - Use environment variables or secret managers
- **Use separate database users** - Don't use admin/root accounts
- **Restrict permissions** - Grant only necessary privileges
- **Enable SSL/TLS** - For production databases

### 3. Organization

- **Descriptive project names** - Use meaningful, readable names
- **Consistent naming** - Follow a naming convention for schemas/databases
- **Document decisions** - Use the `description` field
- **Separate concerns** - Different configs for different environments

### 4. Performance

- **Use PostgreSQL for production** - Better concurrency and performance
- **Enable connection pooling** - For high-traffic scenarios
- **Optimize database location** - Colocate database with application when possible

---

## Troubleshooting

### Config File Not Found

**Error:**
```
Config file not found: config.yml
Please create a config.yml file. See config.example.yml for reference.
```

**Solution:** Create a `config.yml` file based on the example.

### Invalid YAML Syntax

**Error:**
```
Failed to parse YAML in config.yml:
mapping values are not allowed here
```

**Solution:** Check YAML syntax (indentation, colons, quotes).

### Unknown Fields

**Error:**
```
Configuration validation failed:
  - Extra inputs are not permitted
```

**Solution:** Remove unknown fields or check spelling.

### Database Connection Issues

See the [Database Configuration Guide](/docs/03_configuration/02_database.md) for detailed troubleshooting.

---

## Further Reading

- [Database Configuration Guide](/docs/03_configuration/02_database.md)
