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

Core entities include (names may be further refined in [the data model](/docs/04_concepts/01_domain-model.md)):

The TurboVault Engine domain model is centered around a `Project` and a set of interrelated tables that capture source metadata, Data Vault design, pre-join logic, snapshot configuration, reference modeling, and PIT structures.

---

#### Project

- **Project** – Represents a full modeling context (e.g. a specific Data Vault implementation) with high-level metadata like name, description, and configuration settings.

---

#### Source Metadata

- **source_system** – Describes a physical source system, including database and schema information and a human-readable name.

- **source_table** – Represents a physical source table within a source system and stores additional configuration such as record source values, static parts of record source, and load date expressions.

- **source_column** – Represents a single column of a source table, including its physical name and data type.

---

#### Hubs & Hub Mappings

- **hub** – Defines a Data Vault hub entity, including its physical name, type (standard or reference), hash key name (for standard hubs), and flags indicating whether to create record-tracking and effectivity satellites.

- **hub_column** – Describes columns within a hub (business keys, additional columns, or reference keys) and their ordering via a sort index.

- **hub_source_mapping** – Maps hub columns to source columns and identifies which mapping is the primary source for a hub (only one primary per hub).

---

#### Links & Link Mappings

- **link** – Defines a Data Vault link entity, including its physical name, type (standard or non-historized), and the list of standard hubs it connects.

- **link_column** – Describes payload or additional columns that belong to a link.

- **link_source_mapping** – Maps link columns to source columns used to populate those columns in the link.

- **link_hub_source_mapping** – Maps link hub key columns to source columns or prejoin extraction columns, defining how hub keys for the link are derived from source data, with rules around either direct source mapping or prejoin-based mapping.

---

#### Prejoin Definitions

- **prejoin_definition** – Describes a pre-join relationship between two source tables, including source and target columns participating in the join and the logical operator (AND/OR) used to combine conditions.

- **prejoin_extraction_column** – Defines which column values are extracted from the pre-joined target table and made available as reusable extraction columns in link and hub mappings.

---

#### Satellites & Satellite Columns

- **satellite** – Represents a Data Vault satellite and defines its physical name, parent entity (hub or link), and satellite type (standard, reference, non-historized, or multi-active).

- **satellite_column** – Maps source columns into a satellite, with flags for multi-active keys, inclusion in delta detection, and optional target column naming or transformation expressions.

---

#### Snapshot & Reference Modeling

- **snapshot_control_table** – Stores global snapshot configuration such as overall snapshot start and end dates and the daily snapshot execution time.

- **snapshot_control_logic** – Defines reusable snapshot logic patterns (e.g. daily, end-of-month, beginning-of-quarter) with duration and unit, or open-ended “forever” snapshots when configured accordingly.

- **reference_table** – Represents a reference table derived from a reference hub, including historization strategy (latest, full, snapshot-based) and links to snapshot control tables and logic.

- **reference_table_satellite_assignment** – Assigns reference satellites to a reference table and specifies which satellite columns are included or excluded when building the reference structure.

---

#### PIT (Point-in-Time) Structures

- **pit** – Defines a Point-In-Time (PIT) structure over one or more satellites for a tracked hub or link, including snapshot configuration, optional dimension key naming, PIT type, custom record source, snapshot optimization flags, and which satellites it consolidates.

#### Services / Business Logic

Key service modules (in `services/`):

- `config_loader.py`
  - Parses YAML configuration.
  - Validates it (e.g. using Pydantic) and returns typed config objects.

- `import_metadata.py`
  - Reads metadata according to source definitions in config:
    - Excel metadata (using libraries like `pandas` + `openpyxl`).
    - SQLite database metadata.
  - Populates or updates:
    - `Project`, `SourceTable`, `SourceColumn`, `StageTable`, `Hub`, `Link`, `Satellite`.

- `generate_dbt.py`
  - Reads the populated domain model for a given Project.
  - Builds an in-memory representation of the dbt project (files, directories, content).
  - Writes the project to disk and optionally creates a ZIP archive.
  - Updates `GeneratedArtifact` with results.

These services are designed to be **stateless wrappers around the domain model** and I/O operations, making them suitable for reuse in CLI, Celery, and HTTP contexts.

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
