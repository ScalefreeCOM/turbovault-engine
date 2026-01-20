# TurboVault Engine

<div align="center">

**Transform source metadata into production-ready Data Vault dbt projects**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Django](https://img.shields.io/badge/django-6.0+-green.svg)](https://www.djangoproject.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

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

```bash
# Clone the repository
git clone https://github.com/ScalefreeCOM/turbovault-engine.git
cd turbovault-engine

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Option 1: Automated setup (recommended)
# Windows PowerShell:
.\scripts\setup-dev.ps1

# Linux/Mac:
chmod +x scripts/setup-dev.sh
./scripts/setup-dev.sh

# Option 2: Manual installation
pip install -e ".[dev]"
pre-commit install  # Optional but recommended
```

> **Note:** The database, admin user, and templates will be automatically set up the first time you run any TurboVault command. No manual setup required!

### 🐳 Docker Installation (Alternative)

Use Docker for a pre-configured environment:

```bash
# Option 1: Pull from GitHub Container Registry (after first release)
docker pull ghcr.io/scalefreec om/turbovault-engine:latest

# Run commands
docker run ghcr.io/scalefreec om/turbovault-engine:latest turbovault --help

# Option 2: Build locally
git clone https://github.com/ScalefreeCOM/turbovault-engine.git
cd turbovault-engine
docker build -t turbovault-engine .
docker run turbovault-engine turbovault --help
```

**Development with Docker Compose:**

```bash
# Start Django admin server
docker-compose up

# Access at http://localhost:8000/admin
# Data persists in Docker volume
```

### Initialize Your First Project

```bash
# Interactive mode - guided setup wizard
turbovault init --interactive

# Or use a config file
turbovault init --config config.example.yml
```

**On first run, TurboVault will:**
1. ✅ Create the database
2. ✅ Run all migrations
3. ✅ Populate template database from files
4. ✅ Create default snapshot controls
5. ✅ Prompt you to create an admin user (optional)

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

**Generated project structure:**
```
output/my_project/
├── dbt_project.yml
├── packages.yml
├── models/
│   ├── staging/
│   │   ├── sources.yml
│   │   └── {source_system}/
│   │       ├── stg__*.sql
│   │       └── stg__*.yml
│   ├── raw_vault/
│   │   └── {group}/
│   │       ├── hub_*.sql/yml
│   │       ├── link_*.sql/yml
│   │       ├── sat_*_v0.sql/yml
│   │       └── sat_*_v1.sql/yml
│   ├── business_vault/
│   │   ├── pits/
│   │   └── reference_tables/
│   └── control/
│       ├── control_snap_v0.sql/yml
│       └── control_snap_v1.sql/yml
├── macros/
├── tests/
├── seeds/
├── analyses/
└── snapshots/
```

### Use the Generated Project

```bash
cd output/my_project

# Install dbt packages (datavault4dbt)
dbt deps

# Compile to check for errors
dbt compile

# Run your Data Vault models
dbt run
```

---

## 📋 CLI Commands

| Command | Description |
|---------|-------------|
| `turbovault init` | Initialize a new project (interactive or config-based) |
| `turbovault generate` | Generate dbt project from Data Vault model |
| `turbovault run` | Export Data Vault model to JSON |
| `turbovault serve` | Start Django admin server for model management |
| `turbovault reset` | Reset the database |
| `turbovault --help` | Show all available commands |

### Command Examples

```bash
# Interactive project initialization
turbovault init --interactive

# Initialize from YAML config
turbovault init --config config.yml

# Generate dbt project with validation
turbovault generate --project sales_datavault

# Generate in lenient mode (skip invalid entities)
turbovault generate --project sales_datavault --mode lenient

# Generate with ZIP and no v1 satellites
turbovault generate -p sales_datavault --zip --no-v1-satellites

# Export specific project to JSON
turbovault run --project sales_datavault --output ./exports/

# Start admin on custom port
turbovault serve --port 9000
```

---

## 📁 Project Structure

```
turbovault-engine/
├── backend/                    # Django backend
│   ├── engine/                 # Main application
│   │   ├── models/             # Domain models (Hub, Link, Satellite, etc.)
│   │   ├── services/           # Business logic and services
│   │   │   ├── export/         # Export builders and exporters
│   │   │   └── generation/     # dbt project generation
│   │   │       ├── templates/  # SQL and YAML templates
│   │   │       ├── generator.py
│   │   │       ├── validators.py
│   │   │       └── template_resolver.py
│   │   ├── cli/                # CLI commands
│   │   └── admin.py            # Django admin configuration
│   ├── tests/                  # Test suite
│   └── turbovault/             # Django project settings
├── docs/                       # Documentation
│   ├── 01_overview.md          # Architecture overview
│   ├── 02_domain_model.md      # Domain model specification
│   ├── 05_export_flow_specification.md  # Generation spec
│   └── 06_dbt_generation.md    # Generation usage guide
├── config.example.yml          # Example configuration file
├── CLI_GUIDE.md                # Detailed CLI documentation
└── pyproject.toml              # Python package configuration
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
- [Configuration Schema Reference](docs/03_config_schema.md) - Complete config.yml reference
- [Database Configuration Guide](docs/DATABASE_CONFIGURATION.md) - Detailed database setup


---

## 🎨 Template Customization

All SQL and YAML templates can be customized:

1. **Start admin**: `turbovault serve`
2. **Navigate to**: Model Templates in Django Admin
3. **Edit any template** to customize generation
4. **Higher priority templates** are selected first

Templates are automatically populated from files during project initialization.

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

## 🧪 Testing

Run the test suite:

```bash
# Run all tests
python -m pytest backend/tests/ -v

# Run specific test file
python -m pytest backend/tests/test_validators.py -v

# Run with coverage
python -m pytest backend/tests/ --cov=engine.services.generation
```

**Test coverage:**
- 10 validator unit tests
- 10 generator integration tests
- All tests passing ✅

---

## 📤 Export Formats

### JSON Export

```bash
turbovault run --project my_project
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

## 🗺️ Roadmap

### ✅ Completed Features (v0.2)
- ✅ Project and source metadata management
- ✅ Hub, Link, Satellite domain models (6 satellite types)
- ✅ Prejoin definitions for complex links
- ✅ PIT and Reference table support
- ✅ Snapshot control configuration
- ✅ **Complete dbt project generation**
- ✅ **Template customization via Django Admin**
- ✅ **Pre-generation validation**
- ✅ **Comprehensive test suite**
- ✅ **Rich CLI with progress indicators**
- ✅ **Automatic template population**

### 📋 Planned Features

#### Near-Term
- 🔲 **Excel metadata import** - Bulk import from spreadsheet templates
- 🔲 **Database catalog import** - Import metadata directly from databases
- 🔲 **DBML export** - Database modeling language output
- 🔲 **Template versioning** - Track template changes over time

#### Medium-Term
- 🔲 **Multi-project workspaces** - Manage multiple projects
- 🔲 **Model comparison** - Diff and merge capabilities
- 🔲 **CI/CD integration** - GitHub Actions workflow templates
- 🔲 **Data lineage tracking** - Source-to-target mapping

#### Long-Term
- 🔲 **TurboVault Studio** - Web application with UI for modeling
- 🔲 **Git integration** - Push generated projects to repositories
- 🔲 **Cloud storage** - S3/GCS artifact storage
- 🔲 **API endpoints** - REST API for programmatic access
- 🔲 **Team collaboration** - Multi-user support with permissions

---

## 🤝 Contributing

Contributions are welcome! Please see our contributing guidelines (coming soon).

### Development Setup

```bash
# Clone and install dev dependencies
git clone https://github.com/ScalefreeCOM/turbovault-engine.git
cd turbovault-engine
pip install -e ".[dev]"

# Run migrations
cd backend
python manage.py migrate

# Run tests
cd ..
python -m pytest backend/tests/ -v
```

---

## 📚 Documentation

- [Architecture Overview](docs/01_overview.md)
- [Domain Model Specification](docs/02_domain_model.md)
- [Configuration Schema Reference](docs/03_config_schema.md)
- [Database Configuration Guide](docs/DATABASE_CONFIGURATION.md)
- [Import Flow Specification](docs/04_import_flow_specification.md)
- [Export Flow Specification](docs/05_export_flow_specification.md)
- [dbt Generation Guide](docs/06_dbt_generation.md)
- [CLI Guide](docs/CLI_GUIDE.md)


---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

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
