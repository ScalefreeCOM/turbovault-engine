# TurboVault Engine

<div align="center">

**Transform source metadata into production-ready Data Vault dbt projects**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Django](https://img.shields.io/badge/django-5.0+-green.svg)](https://www.djangoproject.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

---

## 🎯 What is TurboVault Engine?

TurboVault Engine is a **CLI-first, Django-based automation engine** that accelerates Data Vault 2.0 implementations. It:

- **Ingests** source metadata from Excel files or database catalogs
- **Maps** metadata into a consistent Data Vault domain model (Hubs, Links, Satellites)
- **Generates** fully structured dbt projects ready for deployment

**Perfect for:** Data Engineers looking to rapidly prototype, standardize, or automate their Data Vault implementations.

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Source    │ --> │  TurboVault      │ --> │  dbt Project    │
│  Metadata   │     │  Engine          │     │  (SQL Models)   │
│  (Excel/DB) │     │                  │     │                 │
└─────────────┘     └──────────────────┘     └─────────────────┘
```

---

## ✨ Key Features

### 📦 Data Vault Modeling
- **Hubs** - Standard and reference hubs with business keys
- **Links** - Standard and non-historized links connecting multiple hubs
- **Satellites** - Standard, multi-active, non-historized, and reference satellites
- **Groups** - Organize entities into logical folders for clean project structure

### 🔧 Source Management
- **Source Systems** - Define database schemas and connections
- **Source Tables** - Map physical tables with record source and load date
- **Source Columns** - Track column metadata and data types

### 📊 Export & Generation
- **Stage Generation** - Automatic stage model definitions with hashkeys and hashdiffs
- **Multi-Source Support** - Multiple sources feeding the same entity

### 🖥️ Developer Experience
- **Modern CLI** - Built with Typer and Rich for beautiful terminal output
- **Django Admin** - Full web interface for model management
- **Config-Driven** - YAML configuration for automation and CI/CD

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- pip (Python package manager)

### Installation

```bash
# Clone the repository
git clone https://github.com/ScalefreeCOM/turbovault-engine.git
cd turbovault-engine

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e .
```

### Initialize Your First Project

```bash
# Interactive mode - guided setup wizard
turbovault init --interactive

# Or use a config file
turbovault init --config config.example.yml
```

### Explore via Django Admin

```bash
# Create a superuser for admin access
cd backend
python manage.py createsuperuser
cd ..

# Start the admin server
turbovault serve

# Open http://127.0.0.1:8000/admin/ in your browser
```

### Export Your Data Vault Model

```bash
# Export project to JSON
turbovault run --project my_project
```

---

## 📋 CLI Commands

| Command | Description |
|---------|-------------|
| `turbovault init` | Initialize a new project (interactive or config-based) |
| `turbovault serve` | Start Django admin server for model management |
| `turbovault run` | Export/generate Data Vault artifacts |
| `turbovault --help` | Show all available commands |

### Command Examples

```bash
# Interactive project initialization
turbovault init --interactive

# Initialize from YAML config
turbovault init --config config.yml

# Start admin on custom port
turbovault serve --port 9000

# Export specific project to JSON
turbovault run --project sales_datavault

# Export to custom location
turbovault run --project sales_datavault --output ./exports/
```

---

## 📁 Project Structure

```
turbovault-engine/
├── backend/                    # Django backend
│   ├── engine/                 # Main application
│   │   ├── models/             # Domain models (Hub, Link, Satellite, etc.)
│   │   ├── services/           # Business logic and export services
│   │   │   └── export/         # Export builders and exporters
│   │   ├── cli/                # CLI commands
│   │   └── admin.py            # Django admin configuration
│   └── backend/                # Django project settings
├── docs/                       # Documentation
│   ├── 01_overview.md          # Architecture overview
│   └── 02_domain_model.md      # Domain model specification
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
| **Source Table** | Physical source tables |
| **Hub** | Data Vault hubs (standard or reference) |
| **Link** | Relationships between hubs |
| **Satellite** | Descriptive attributes for hubs/links |

### Entity Relationships

```
Project
├── Groups
├── Source Systems
│   └── Source Tables
│       └── Source Columns
├── Hubs
│   ├── Hub Columns
│   │   └── Hub Source Mappings
│   └── Satellites
├── Links
│   ├── Link Columns
│   │   └── Link Source Mappings
│   └── Satellites
└── Satellites
    └── Satellite Columns
```

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

configuration:
  stage_schema: "stage"
  rdv_schema: "rdv"

output:
  dbt_project_dir: "./generated/dbt_project"
  create_zip: false
```

See [config.example.yml](config.example.yml) for a complete example.

---

## 📤 Export Format

The `turbovault run` command exports your model to JSON:

```json
{
  "project_name": "my_project",
  "hubs": [
    {
      "hub_name": "hub_customer",
      "hub_type": "standard",
      "group": "sales",
      "hashkey": {
        "hashkey_name": "hk_customer",
        "business_keys": ["customer_id"]
      },
      "source_tables": [...]
    }
  ],
  "links": [...],
  "satellites": [...],
  "stages": [...]
}
```

---

## 🗺️ Roadmap

### Current Features (v0.1)
- ✅ Project and source metadata management
- ✅ Hub, Link, Satellite domain models
- ✅ Group-based organization
- ✅ Django Admin interface
- ✅ JSON export with hashkeys and hashdiffs
- ✅ Modern CLI with Typer/Rich

### Planned Features

#### Near-Term
- 🔲 **Excel metadata import** - Bulk import from spreadsheet templates
- 🔲 **dbt project generation** - Generate complete dbt projects with SQL models
- 🔲 **Prejoin definitions** - Cross-table joins for link mappings
- 🔲 **Snapshot control** - Point-in-time and snapshot configuration

#### Medium-Term
- 🔲 **Database catalog import** - Import metadata directly from databases
- 🔲 **PIT (Point-in-Time) tables** - Generate PIT structures
- 🔲 **Reference tables** - Full reference modeling support
- 🔲 **DBML export** - Database modeling language output

#### Long-Term
- 🔲 **TurboVault Studio** - Web application with UI for modeling
- 🔲 **Git integration** - Push generated projects to repositories
- 🔲 **Cloud storage** - S3/GCS artifact storage
- 🔲 **API endpoints** - REST API for programmatic access

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
pytest
```

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

---

<div align="center">

**Built with ❤️ by [Scalefree](https://scalefree.com)**

[Documentation](docs/) · [Report Bug](https://github.com/ScalefreeCOM/turbovault-engine/issues) · [Request Feature](https://github.com/ScalefreeCOM/turbovault-engine/issues)

</div>
