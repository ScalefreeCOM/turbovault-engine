# TurboVault CLI User Guide

## Installation

Install TurboVault Engine in development mode:

```bash
pip install -e .
```

This makes the `turbovault` command available in your terminal.

> **Automatic Setup:** TurboVault automatically detects if the database is not initialized and runs all necessary migrations, creates default snapshot controls, and populates templates on first use. No manual setup required!

## Commands Overview

TurboVault CLI provides the following main commands:

- `turbovault init` - Initialize a new project
- `turbovault generate` - Generate dbt project and/or export Data Vault model to JSON
- `turbovault serve` - Start Django admin server (and Web Initializer)
- `turbovault reset` - Reset the database
- `turbovault --help` - Show help for all commands

## Command Reference

### turbovault init

Initialize a new TurboVault project in the Django database.

#### Usage with Config File

```bash
turbovault init --config config.yml
```

This will:
1. Load and validate your config.yml
2. Create the project in the Django database
3. Create default snapshot controls
4. Populate templates into the database
5. Display a summary of the project configuration

**Example:**
```bash
turbovault init --config examples/my_project_config.yml
```

#### Interactive Mode

```bash
turbovault init --interactive
```

This launches an interactive wizard that prompts you for:
- Project name
- Project description (optional)
- Whether to import from Excel
- Excel file path (if applicable)
- Stage schema name (default: "stage")
- Stage database (optional)
- RDV schema name (default: "rdv")
- RDV database (optional)
- dbt project output directory
- Whether to create a ZIP archive

**Example:**
```bash
turbovault init --interactive

# You'll be prompted:
? Project name: sales_datavault
? Project description (optional): Sales Data Vault implementation
? Import metadata from Excel? Yes
? Path to Excel file: ./metadata/sales_sources.xlsx
? Stage schema name: stage
? RDV schema name: rdv
? dbt project output directory: ./generated/dbt_project
? Create ZIP archive of generated project? No
```

#### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--config PATH` | `-c` | Path to config.yml file |
| `--interactive` | `-i` | Run interactive setup wizard |
| `--help` | | Show help message |

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

### Example 1: Quick Start - Generate dbt Project

```bash
# 1. Initialize project interactively
turbovault init --interactive

# 2. Start admin server to define your model
turbovault serve

# 3. Define your Data Vault model in admin interface
# - Navigate to http://127.0.0.1:8000/admin/
# - Create hubs, links, satellites

# 4. Generate dbt project
turbovault generate --project my_project

# 5. Use the generated dbt project
cd output/my_project
dbt deps
dbt compile
dbt run
```

### Example 2: Complete Development Workflow

```bash
# 1. Create config.yml
cat > config.yml << EOF
project:
  name: "sales_datavault"
  description: "Sales Data Vault"

configuration:
  stage_schema: "stg"
  rdv_schema: "rdv"

output:
  dbt_project_dir: "./generated/dbt_sales"
  create_zip: false
EOF

# 2. Initialize from config
turbovault init --config config.yml

# 3. Model in admin (or programmatically)
turbovault serve

# 4. Export to JSON for review (optional)
turbovault generate --json-only --project sales_datavault --json-format pretty

# 5. Generate dbt project
turbovault generate --project sales_datavault --zip

# 6. Deploy generated project
cd generated/dbt_sales
dbt deps
dbt run
```

### Example 3: Template Customization Workflow

```bash
# 1. Initialize project
turbovault init --interactive

# 2. Start admin server
turbovault serve

# 3. Customize templates
# - Navigate to Model Templates in admin
# - Edit SQL or YAML templates
# - Save changes

# 4. Generate with custom templates
turbovault generate --project my_project

# Templates from database override file-based defaults
```

### Example 4: CI/CD Pipeline Example

```bash
# Skip interactive prompts
export TURBOVAULT_SKIP_SUPERUSER_PROMPT=1
export TURBOVAULT_SKIP_TEMPLATE_POPULATION=0

# Initialize project
turbovault init --config config.yml

# Generate and validate
turbovault generate --project ci_project --mode strict --zip

# Archive is ready for deployment
ls output/ci_project.zip
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
turbovault init --help
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

This is automatically done during `turbovault init` but can be run manually if needed.

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

---

## Next Steps

- Review the [README](README.md) for overview
- Study [dbt generation documentation](docs/06_dbt_generation.md)
- Learn about [environment variables](ENVIRONMENT_VARIABLES.md)
- Explore [domain model documentation](docs/02_domain_model.md)
- Check [template customization guide](docs/06_dbt_generation.md#custom-templates)
