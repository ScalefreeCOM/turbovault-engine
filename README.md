# TurboVault Engine

<div align="center">

**Transform source metadata into production-ready Data Vault dbt projects**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Django](https://img.shields.io/badge/django-6.0+-green.svg)](https://www.djangoproject.com/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

</div>

---

## 🎯 What is TurboVault Engine?

TurboVault Engine is a **CLI-first, Django-based automation engine** that accelerates Data Vault 2.0 implementations. It:

- **Ingests** source metadata from Excel files or database catalogs
- **Maps** metadata into a consistent Data Vault domain model (Hubs, Links, Satellites)
- **Generates** complete, production-ready dbt projects with datavault4dbt macros
- **Validates** your model before generation with comprehensive error checking

**Perfect for:** Data Engineers looking to rapidly prototype, standardize, or automate their Data Vault implementations.

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Source    │ --> │  TurboVault      │ --> │  dbt Project    │
│  Metadata   │     │  Engine          │     │  (Ready to Run) │
│  (Excel/DB) │     │                  │     │                 │
└─────────────┘     └──────────────────┘     └─────────────────┘
```

---

## ✨ Key Features

### 🏗️ Complete dbt Project Generation
- **Automatic model generation** - SQL models with datavault4dbt macros
- **YAML schemas** - Complete dbt documentation for all models
- **Organized structure** - Clean folder hierarchy (staging, raw_vault, business_vault)
- **Template customization** - Customize any template via Django Admin
- **Validation** - Pre-generation checks to catch errors early

### 📦 Data Vault Modeling
- **Hubs** - Standard and reference hubs with business keys
- **Links** - Standard and non-historized links connecting multiple hubs
- **Satellites** - Standard, multi-active, non-historized, effectivity, and reference satellites
- **PITs** - Point-in-Time table generation
- **Reference Tables** - Reference data modeling
- **Snapshot Controls** - Configurable snapshot logic for temporal tracking

### 🔧 Source Management
- **Source Systems** - Define database schemas and connections
- **Source Tables** - Map physical tables with record source and load date
- **Prejoins** - Cross-table joins for complex link mappings
- **Stage Models** - Automatic staging layer with hashkeys and hashdiffs

### 🖥️ Developer Experience
- **Modern CLI** - Built with Typer and Rich for beautiful terminal output
- **Web Initializer** - Interactive, multi-step project creation wizard
- **Django Admin** - Full web interface for model and template management
- **Config-Driven** - YAML configuration for automation and CI/CD
- **Comprehensive Testing** - pytest test suite with 20+ tests

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- pip (Python package manager)
- (Optional) Database drivers if using external databases:
  - PostgreSQL: `psycopg2-binary`
  - MySQL: `mysqlclient`
  - SQL Server: `mssql-django`
  - Oracle: `cx_Oracle`
  - Snowflake: `django-snowflake`

### Installation

**Install from PyPI** (once the package is published):

```bash
pip install turbovault-engine
```

**Install directly from GitHub** (latest development version):

```bash
pip install git+https://github.com/ScalefreeCOM/turbovault-engine.git
```

We recommend installing into a dedicated virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install turbovault-engine
```

### Initialize Your Workspace & First Project

TurboVault uses a **two-step setup**. First, create and enter a dedicated folder for your workspace:

```bash
mkdir my-turbovault-workspace
cd my-turbovault-workspace
```

**Step 1 — Initialise the workspace** (once per directory):
```bash
# Interactive (recommended for first time)
turbovault workspace init

# Or fully non-interactive:
turbovault workspace init \
  --db-engine sqlite3 --db-name db.sqlite3 \
  --stage-schema stage --rdv-schema rdv \
  --admin-username admin --admin-password changeme --admin-email admin@example.com
```

This creates `turbovault.yml`, initialises the database, runs all migrations, and populates default templates.

**Step 2 — Create a project** (once per project):
```bash
# Interactive wizard
turbovault project init --interactive

# Non-interactive with flags (great for CI/scripts)
turbovault project init --name my_project --source ./metadata.xlsx \
  --stage-schema stage --rdv-schema rdv

# Or from a config file
turbovault project init --config config.example.yml
```

### Populate and Maintain your Data Vault model

You can check, define, and change your Data Vault model via the Django Admin interface. To launch the web interface:

```bash
# Launch the web interface
turbovault serve
```

Sign in via the credentials you set up during workspace initialization.

### Generate Your dbt Project

```bash
# Generate dbt project from your Data Vault model
turbovault generate --project my_project

# Generate with custom output path
turbovault generate --project my_project --output ./my_dbt

# Generate with ZIP archive
turbovault generate --project my_project --zip

# Skip satellite v1 views
turbovault generate --project my_project --no-v1-satellites
```

---

## 📋 CLI Commands

| Command | Description |
|---------|-------------|
| `turbovault workspace init` | Initialise directory as a workspace (creates `turbovault.yml` + DB) |
| `turbovault workspace status` | Show workspace health (DB, projects, migrations) |
| `turbovault project init` | Create a new project in the workspace |
| `turbovault project list` | List all projects in the workspace |
| `turbovault generate` | Generate dbt project and/or export Data Vault model to JSON |
| `turbovault serve` | Start Django admin server for model management |
| `turbovault reset` | Reset the database |
| `turbovault --help` | Show all available commands |

### Command Examples

```bash
# --- Workspace ---
# Initialise workspace (non-interactive)
turbovault workspace init --db-engine sqlite3 --db-name db.sqlite3 \
  --stage-schema stage --rdv-schema rdv --skip-admin

# Check workspace health
turbovault workspace status

# --- Projects ---
# Interactive project creation
turbovault project init --interactive

# Create from YAML config
turbovault project init --config config.yml

# List all projects
turbovault project list

# --- Generation ---
# Generate dbt project with validation
turbovault generate --project sales_datavault

# Generate in lenient mode (skip invalid entities)
turbovault generate --project sales_datavault --mode lenient

# Generate with ZIP and no v1 satellites
turbovault generate -p sales_datavault --zip --no-v1-satellites

# Export Data Vault model to JSON
turbovault generate --type json --project sales_datavault

# Start admin on custom port
turbovault serve --port 9000
```
---

## 🗄️ Domain Model

TurboVault Engine uses a comprehensive Data Vault domain model:

### Core Entities

| Entity | Description |
|--------|-------------|
| **Project** | Top-level container for all metadata |
| **Group** | Logical grouping for organizing entities into subfolders |
| **Source System** | Database/schema source definitions |
| **Source Table** | Physical source tables with metadata |
| **Hub** | Data Vault hubs (standard or reference) |
| **Link** | Relationships between hubs (standard or non-historized) |
| **Satellite** | Descriptive attributes for hubs/links (6 types) |
| **PIT** | Point-in-Time tables for temporal joins |
| **Reference Table** | Reference data structures |
| **Snapshot Control** | Temporal snapshot configuration |

### Advanced Features

- **Prejoins** - Define cross-table joins for link mappings
- **Multi-source support** - Multiple sources feeding the same entity
- **Satellite variants** - Standard, multi-active, effectivity, non-historized, reference, record-tracking
- **Template customization** - All SQL and YAML templates customizable via Admin

---

## ⚙️ Configuration

TurboVault Engine is configured via `config.yml`:

```yaml
project:
  name: "my_datavault"
  description: "My Data Vault Implementation"

source:
  type: excel
  path: "./metadata/sources.xlsx"

# Optional: Configure external database (PostgreSQL, MySQL, etc.)
# Default is SQLite if not specified
database:
  engine: postgresql
  name: turbovault_db
  user: turbovault_user
  password: your_password
  host: localhost
  port: 5432

configuration:
  stage_schema: "stage"
  rdv_schema: "rdv"
  bdv_schema: "bdv"

output:
  dbt_project_dir: "./generated/dbt_project"
  create_zip: false
```

**Supported Databases:**
- **SQLite** (default) - No configuration needed
- **PostgreSQL** - `pip install psycopg2-binary`
- **MySQL/MariaDB** - `pip install mysqlclient`
- **SQL Server** - `pip install mssql-django`
- **Oracle** - `pip install cx_Oracle`
- **Snowflake** - `pip install django-snowflake`

See [config.example.yml](config.example.yml) for a complete example.

**Documentation:**
- [Configuration Schema Reference](03_config_schema.md) - Complete config.yml reference
- [Database Configuration Guide](DATABASE_CONFIGURATION.md) - Detailed database setup


---

## 🎨 Template Customization

All SQL and YAML templates can be customized:

1. **Start admin**: `turbovault serve`
2. **Navigate to**: Model Templates in Django Admin
3. **Edit any template** to customize generation
4. **Higher priority templates** are selected first

Templates are automatically populated from files during `turbovault workspace init`.

### Manual Template Management

```bash
# Populate templates from files
cd backend && python manage.py populate_templates

# Overwrite existing templates
python manage.py populate_templates --overwrite
```

---

## ✅ Validation

Pre-generation validation catches common errors:

| Entity | Rule | Code |
|--------|------|------|
| Hub (standard) | Must have hashkey | HUB_001 |
| Hub | Must have ≥1 business key | HUB_002 |
| Link | Must have hashkey | LNK_001 |
| Link | Must reference ≥2 hubs | LNK_002 |
| Satellite | Must have parent entity | SAT_001 |
| Model | SQL generated but YAML missing | YML_001 |

**Validation modes:**
- `--mode strict` (default): Stop on first error
- `--mode lenient`: Skip invalid, continue with valid
- `--skip-validation`: Skip all validation

---

## 📤 Export Formats

### JSON Export

```bash
# Export JSON only (no dbt generation)
turbovault generate --json-only --project my_project

# Export JSON alongside dbt project
turbovault generate --export-json --project my_project

# Specify custom JSON output path
turbovault generate --json-only --json-output ./exports/model.json

# Use compact JSON format
turbovault generate --json-only --json-format compact
```

Exports complete model to JSON with:
- Project metadata
- All hubs, links, satellites
- Stage definitions with hashkeys/hashdiffs
- PITs and reference tables
- Snapshot controls

### dbt Project

```bash
turbovault generate --project my_project
```

Generates ready-to-use dbt project with:
- SQL models using datavault4dbt macros
- YAML schemas for all models
- Complete folder structure
- packages.yml with datavault4dbt dependency

---

## 🤝 Contributing

We welcome and appreciate community contributions! To keep the project sustainable while ensuring the software remains open and accessible, we follow a **Dual-Licensing** model.

### 📜 Licensing & Open Source
This project is licensed under the **GNU Affero General Public License v3 (AGPL-3.0)**. 

The AGPL is a "strong copyleft" license. If you modify this software and provide it as a service over a network (SaaS), you **must** make your modified source code available to your users under the same license.

### ✍️ Contributor License Agreement (CLA)
To contribute code, all contributors are required to sign our **Contributor License Agreement (CLA)**. 
* **Why?** This ensures that you have the right to contribute the code and grants us the necessary rights to include your work in future versions of the project, including potential commercial or non-AGPL distributions.
* **How?** **FIXME**

### 💼 Commercial Usage & Licensing
We understand that the AGPL-3.0 may not be suitable for every organization's internal policies or proprietary products. 

If you wish to use this project in a commercial or proprietary setting without the "copyleft" requirements of the AGPL, we offer **alternative commercial licenses**. This allows you to:
* Use the software without disclosing your own source code.
* Receive dedicated support and enterprise-grade warranties.
* Support the development team.

Please contact us at **contact@scalefree.com** to discuss a commercial license tailored to your needs.

---

## 📚 Documentation

- [Architecture Overview](01_overview.md)
- [Domain Model Specification](02_domain_model.md)
- [Configuration Schema Reference](03_config_schema.md)
- [Database Configuration Guide](DATABASE_CONFIGURATION.md)
- [Import Flow Specification](04_import_flow_specification.md)
- [Export Flow Specification](05_export_flow_specification.md)
- [dbt Generation Guide](06_dbt_generation.md)
- [CLI Guide](CLI_GUIDE.md)


---

## 📄 License

This project is licensed under the **GNU Affero General Public License v3 (AGPL-3.0)** - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgements

Built with:
- [Django](https://www.djangoproject.com/) - Web framework
- [Typer](https://typer.tiangolo.com/) - CLI framework
- [Rich](https://rich.readthedocs.io/) - Terminal formatting
- [Pydantic](https://docs.pydantic.dev/) - Data validation
- [Jinja2](https://jinja.palletsprojects.com/) - Template engine
- [datavault4dbt](https://github.com/ScalefreeCOM/datavault4dbt) - dbt macros

---

<div align="center">

**Built with ❤️ by [Scalefree](https://scalefree.com)**

[Documentation](docs/) · [Report Bug](https://github.com/ScalefreeCOM/turbovault-engine/issues) · [Request Feature](https://github.com/ScalefreeCOM/turbovault-engine/issues)

</div>
