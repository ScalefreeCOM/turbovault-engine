---
sidebar_position: 2
sidebar_label: Architecture
title: Architecture
---

# Architecture

## High-Level Architecture

TurboVault Engine is built around three main layers:

1. **Domain Model (Django ORM)**  
   - Represents Projects, Sources, Hubs, Links, Satellites, ..., and Generated Artifacts.
   - Serves as a structured, queryable representation of the Data Vault design.

2. **Services / Business Logic**  
   - Implement core functionalities:
     - Parsing and validating configuration.
     - Importing metadata from external sources.
     - Generating dbt projects in memory based on model templates and writing them to disk.

3. **CLI Interface**  
   - Provides user-friendly commands (e.g. `turbovault generate`) that orchestrate domain services.
   - Runs as a Django management command and/or a dedicated CLI entry point (Typer/Click).

Internally, Django provides the core ORM, management commands, and a **dynamic web-based initialization wizard** accessible via the root URL.

### Component Breakdown

#### Domain Model (Django ORM)

The domain model is centered around a `Project` and a set of interrelated entities covering source metadata, Data Vault structures (hubs, links, satellites), pre-join logic, snapshot configuration, reference modeling, and PIT structures.

For a full specification of every entity, its fields, and its relationships, see the [Domain Model Reference](../04_concepts/01_domain-model.md).

---

#### Services / Business Logic

Key service areas (in `services/`):

- **Configuration service**
  - Parses YAML configuration files (`turbovault.yml` and project `config.yml`).
  - Validates them using Pydantic and returns typed config objects.

- **Import services**
  - Read metadata according to the source type defined in the project config:
    - Excel metadata (using `pandas` + `openpyxl`).
    - SQLite database metadata.
  - Create or update domain entities: `Project`, `SourceSystem`, `SourceTable`, `SourceColumn`, `Hub`, `Link`, `Satellite`, and their associated mapping tables.

- **Generation services**
  - Read the populated domain model for a given Project.
  - Render SQL models and YAML schemas using Jinja2 templates stored in the database.
  - Write the resulting files to disk as an organized dbt project directory.
  - Optionally create a ZIP archive and record a `GeneratedArtifact`.

- **Export services**
  - Serialize the domain model to alternative output formats (JSON, DBML) for inspection or downstream tooling.

All services are designed to be **stateless wrappers around the domain model** and I/O operations, making them suitable for reuse in CLI, Celery, and HTTP contexts.

#### CLI Interface

CLI responsibilities:

- Provide a simple entry point for users:
  - `turbovault generate --project my_project`
- Internally:
  - Initialize Django.
  - Call `config_loader` to parse the YAML.
  - Invoke `import_metadata` to persist the model.
  - Call `generate_dbt` to create the dbt project.

The CLI should be thin: it should not embed domain logic, only orchestrate service calls.

---

## Execution Flow

### Step-by-Step Flow (Standalone CLI)

0. **Workspace and Project initialization** (optional/first-time)
   - User runs:  
     `turbovault workspace init` to set up the global DB connection.
     `turbovault project init` to create a new project.
   - The Engine:
     - Starts a Django context (settings + DB).
     - Creates `turbovault.yml` for the workspace.
     - Creates a new Project directory with a `config.yml`.

1. **Configuration Loading**
   - User runs:  
     `turbovault generate --project my_project`
   - The Engine:
     - Starts a Django context (settings + DB).
     - Loads and parses the project's `config.yml` into a typed configuration object.

2. **Metadata Import**
   - Based on config:
     - If `source.type == "excel"`:
       - Read metadata sheets from the specified Excel file.
     - If `source.type == "sqlite"`:
       - Connect to the specified SQLite database and read source metadata.
   - Map this metadata to domain entities:
     - Create or update `Project`.
     - Populate `SourceTable`, `SourceColumn`, `StageTable`.
     - Populate `Hub`, `Link`, `Satellite` definitions based on the metadata.

3. **Validation (Optional / Recommended)**
   - Verify that the imported model is well-formed:
     - Each Hub has at least one business key.
     - Links connect at least two hubs.
     - Satellites have a valid parent (Hub or Link) and at least one attribute.

4. **dbt Project Generation**
   - Read the Project’s DV model from the database.
   - Construct:
     - `dbt_project.yml` (basic configuration: name, profile, model paths).
     - Generate `.sql` files for stage/hubs/links/satellites based on templates.
     - Generate `schema.yml` files with metadata and tests (where appropriate).
   - Write them to the output path specified in the config (e.g. `./output/my_dbt_project`).

5. **Output & Artifact Tracking**
   - Optionally build a ZIP archive of the dbt project directory.
   - Create or update a `GeneratedArtifact` record:
     - Status: SUCCESS or FAILED.
     - Output path and/or ZIP path.
     - Associated Project and metadata.

6. **Result for the User**
   - The user sees a success message (or error details).
   - The generated dbt project can now be used directly with `dbt`, opened in an editor, or integrated into a larger pipeline.
