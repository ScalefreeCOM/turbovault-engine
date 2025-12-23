# TurboVault CLI User Guide

## Installation

Install Turbo Vault Engine in development mode:

```bash
pip install -e .
```

This makes the `turbovault` command available in your terminal.

## Commands Overview

TurboVault CLI provides three main commands:

- `turbovault init` - Initialize a new project
- `turbovault run` - Generate dbt project (coming soon)
- `turbovault serve` - Start Django admin server

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
3. Display a summary of the project configuration

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
- RDV schema name (default: "rdv")

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
```

#### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--config PATH` | `-c` | Path to config.yml file |
| `--interactive` | `-i` | Run interactive setup wizard |
| `--help` | | Show help message |

---

### turbovault serve

Start the Django development server to access the admin interface.

#### Basic Usage

```bash
turbovault serve
```

This starts the server on `http://127.0.0.1:8000/`

Access the admin at: `http://127.0.0.1:8000/admin/`

#### Custom Port and Host

```bash
turbovault serve --port 9000 --host 0.0.0.0
```

#### Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
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

### turbovault run

Generate dbt project from your Data Vault model.

**Status:** 🚧 Coming in a future version

This command will:
- Load your project from the Django database
- Generate dbt models for stages, hubs, links, satellites
- Create dbt_project.yml and related configuration
- Optionally create a ZIP archive

**Planned usage:**
```bash
turbovault run --config config.yml
turbovault run --output ./my_dbt_project
```

---

## Complete Workflow Examples

### Example 1: Start from Scratch (No Excel)

```bash
# 1. Initialize project interactively
turbovault init --interactive
# Answer: No to "Import metadata from Excel?"

# 2. Start admin server
turbovault serve

# 3. Open browser to http://127.0.0.1:8000/admin/
# 4. Use admin interface to define your Data Vault model

# 5. Generate dbt project (future)
# turbovault run
```

### Example 2: Import from Excel

First, create a `config.yml`:

```yaml
project:
  name: "sales_datavault"
  description: "Sales Data Vault"

source:
  type: excel
  path: "./metadata/sales_sources.xlsx"

configuration:
  stage_schema: "stg"
  rdv_schema: "rdv"

output:
  dbt_project_dir: "./generated/dbt_sales"
  create_zip: false
```

Then run:

```bash
# 1. Initialize from config
turbovault init --config config.yml

# 2. (Future) Import metadata
# turbovault import --config config.yml

# 3. Review/edit in admin
turbovault serve

# 4. (Future) Generate dbt
# turbovault run --config config.yml
```

### Example 3: Multiple Projects

```bash
# Initialize first project
turbovault init --config projects/sales_config.yml

# Initialize second project
turbovault init --config projects/hr_config.yml

# Use admin to manage both
turbovault serve -p 8000
```

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
turbovault serve --help
turbovault run --help
```

### Typical Development Workflow

1. **Create config.yml** with your project settings
2. **Initialize**: `turbovault init --config config.yml`
3. **Model in Admin**: `turbovault serve` then open admin
4. **Define your Data Vault model** (hubs, links, satellites)
5. **Generate** (future): `turbovault run`

## Troubleshooting

### "Module not found" Error

Make sure you've installed the package:
```bash
pip install -e .
```

### "Project already exists" Error

When running `init` (either with `--config` or `--interactive`), if a project with the same name already exists, you'll be prompted:

```
✗ Project 'my_project' already exists!
? Do you want to delete the existing project and start fresh? (y/N)
```

Choose:
- **Yes** to delete the existing project and create a new one
- **No** to cancel initialization

**Note:** Deleting a project removes all associated data (hubs, links, satellites, etc.).

### Django Admin Login

Create a superuser first:
```bash
cd backend
python manage.py createsuperuser
```

Then use those credentials in the admin interface.

## Next Steps

- Review the [config schema documentation](config.example.yml)
- Learn about [Django models](backend/engine/models/)
- See [domain model documentation](docs/02_domain_model.md)
