# 01 – TurboVault Engine Overview

## 1. Introduction

TurboVault Engine is a **CLI-first, Django-based engine** for turning source system metadata into a **Data Vault–oriented model** and a **fully structured dbt project**.

It is designed to:

- Read metadata from configurable sources (e.g. Excel files, database catalogs).
- Map this metadata into a consistent **internal Data Vault domain model** (Sources, Hubs, Links, Satellites, etc.).
- Generate a **ready-to-use dbt project** (directory + optional ZIP archive) based on this model.

TurboVault Engine is intended to be:

1. **Standalone & open-source** – directly usable by Data Warehouse Engineers from the command line.
2. **The core engine behind TurboVault Studio** – the future web application will reuse the same models and services, exposing them via an HTTP API and UI.

This document gives a detailed overview of the Engine’s purpose, scope, architecture, and how it will be used both in standalone mode and inside the web application.

---

## 2. Goals and Non-Goals

### 2.1 Goals

TurboVault Engine aims to:

- Provide a **robust, explicit Data Vault metadata model** (Django ORM) that can serve as a single source of truth.
- Offer a **repeatable, config-driven pipeline** for:
  - Importing metadata from external sources (Excel, databases, etc.).
  - Populating the internal domain model.
  - Generating a dbt project from that model.
- Be **installable as a Python package** and runnable via a simple CLI:
  - Example: `turbovault run --config config.yml`
- Be architected in a way that is **directly reusable** for:
  - A future web backend (TurboVault Studio).
  - Celery-based background tasks.
  - Potential integrations in other tools.
- Be **open-source** from the start, with a clear and approachable structure.

### 2.2 Non-Goals (at Pre-MVP / Engine Level)

The following are explicitly out of scope for the initial Engine (Pre-MVP) and are deferred to later phases or to TurboVault Studio:

- **User management & authentication**  
  No multi-user system, logins, or authorization; the Engine is a local tool operated by a single user.
- **HTTP API / Web UI**  
  No REST endpoints or user interface; the Engine is accessed via CLI and configuration files.
- **Cloud storage & Git integration**  
  No S3 uploads, no Git push; output is purely local (directory + optional ZIP). Studio will later handle S3/Git.
- **Highly dynamic runtime configuration management**  
  The entrypoint is a **static `config.yml`** file. Dynamic per-request configuration is not required at this stage.
- **Vendor-specific dbt optimizations**  
  The Engine focuses on generic dbt project structure; highly tuned SQL patterns per warehouse can be added later.

---

## 3. Primary Use Cases

### 3.1 Local Modeling & Generation by Data Engineers

A Data Warehouse Engineer can:

1. Describe their source system metadata and desired Data Vault model in a relational table format stored in Excel or a database.
2. Define project-specific configuration in a config.yml file.
3. Run the Engine locally.
4. Obtain a fully structured dbt project as output.

Typical use cases:
- Rapid prototyping of a Data Vault implementation.
- Generating a starting point for a dbt project from spreadsheet-defined metadata.
- Converting a known schema (e.g. a staging DB schema) into a DV/dbt structure.

### 3.2 Batch Generation and CI/CD Integration

Because the Engine is CLI-driven and deterministic, it can be integrated into:

- CI pipelines (e.g. GitHub Actions, GitLab CI) to:
  - Validate configurations.
  - Re-generate dbt projects when metadata or mapping rules change.
- Internal tools that programmatically produce `config.yml` files and then call the Engine.

### 3.3 Core Component for TurboVault Studio

TurboVault Studio (the future web application) will:

- Reuse TurboVault Engine’s **domain model and services**.
- Replace metadata store and `config.yml` with a web-based configuration experience (forms, wizards).
- Invoke the same import & generation logic through:
  - HTTP endpoints.
  - Background tasks.

The Engine thus acts as the **platform foundation** for Studio.

---

## 4. High-Level Architecture

### 4.1 Architectural Overview

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
   - Provides user-friendly commands (e.g. `turbovault run`) that orchestrate domain services.
   - Runs as a Django management command and/or a dedicated CLI entry point (Typer/Click).

Internally, Django is used **without any HTTP views** in the Engine phase. Only ORM, management commands, and configuration loading are used.

### 4.2 Component Breakdown

#### 4.2.1 Domain Model (Django ORM)

Core entities include (names may be further refined in `02_domain_model.md`):

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

#### 4.2.2 Services / Business Logic

Key service modules (in `services/`):

- `config_loader.py`
  - Parses YAML configuration.
  - Validates it (e.g. using Pydantic) and returns typed config objects.

- `import_metadata.py`
  - Reads metadata according to source definitions in config:
    - Excel metadata (using libraries like `pandas` + `openpyxl`).
    - Database metadata (optionally using DB drivers and information schema).
  - Populates or updates:
    - `Project`, `SourceTable`, `SourceColumn`, `StageTable`, `Hub`, `Link`, `Satellite`.

- `generate_dbt.py`
  - Reads the populated domain model for a given Project.
  - Builds an in-memory representation of the dbt project (files, directories, content).
  - Writes the project to disk and optionally creates a ZIP archive.
  - Updates `GeneratedArtifact` with results.

These services are designed to be **stateless wrappers around the domain model** and I/O operations, making them suitable for reuse in CLI, Celery, and HTTP contexts.

#### 4.2.3 CLI Interface

CLI responsibilities:

- Provide a simple entry point for users:
  - `turbovault run --config config.yml`
- Internally:
  - Initialize Django.
  - Call `config_loader` to parse the YAML.
  - Invoke `import_metadata` to persist the model.
  - Call `generate_dbt` to create the dbt project.

The CLI should be thin: it should not embed domain logic, only orchestrate service calls.

---

## 5. Execution Flow

### 5.1 Step-by-Step Flow (Standalone CLI)

0. **Project initialization** (optional)
   - User runs:  
     `turbovault init` and is guided through the process of creating a new project.
   - The Engine:
     - Starts a Django context (settings + DB).
     - Creates a new Project.
     - Stores the user settings in a config.yml

1. **Configuration Loading**
   - User runs:  
     `turbovault run --config config.yml`
   - The Engine:
     - Starts a Django context (settings + DB).
     - Loads and parses `config.yml` into a typed configuration object.

2. **Metadata Import**
   - Based on config:
     - If `source.type == "excel"`:
       - Read metadata sheets from the specified Excel file.
     - If `source.type == "database"`:
       - Connect to the configured database and query table/column metadata.
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

---

## 6. Configuration Model (`config.yml`)

The Engine is driven by a `config.yml` file. While details are defined in `03_config_schema.md`, the high-level structure includes:

- `project`
  - Name, description, optional identifiers.
- `metadata_source`
  - Type (`excel`, later `database`).
  - Connection details or file paths.
  - Optional filters (schemas, tables to include/exclude).
- `modeling`
  - Rules for:
    - Stage table creation (LDTS, RSRC, hash key defaults)
    - ...
- `output`
  - Target directory for the dbt project.
  - Project name and dbt profile name.
  - Whether to create a ZIP.

The configuration model is central: in standalone mode, this is the only interface the user needs to learn.

---

## 7. Standalone Usage

In its initial form, TurboVault Engine is used **exclusively as a CLI tool**.

### 7.1 Installation

Example (details in README):

```bash
pip install turbovault-engine
```
### 7.2 Typical Commands

Initialize a sample config:
```bash
turbovault init-config --output config.yml
```

Run a generation:
```bash
turbovault run --config config.yml
```

Optional convenience commands might include:

Validate configuration only:
```bash
turbovault validate --config config.yml
```

Print a summary of the inferred model:
```bash
turbovault describe --config config.yml
```

### 7.3 Local Database Usage

By default:
- A local **SQLite database** can be used to persist the domain model during a run.
- This allows inspection of the modeled entities if desired (e.g. using Django shell).

Advanced users may choose to configure a **PostgreSQL** or other database backend via standard Django settings, especially if they want persistence across multiple runs or integration with other tools.

---

## 10. Glossary (Engine Context)

- **Data Vault (DV)**  
  A modeling approach for Data Warehouses, focusing on separating business keys (Hubs), relationships (Links), and descriptive attributes (Satellites).

- **Project**  
  A logical container for all metadata related to a single Data Vault/dbt implementation.

- **Source Metadata**  
  Information about upstream tables and columns (e.g. from Excel or a source DB).

- **Hub**  
  A Data Vault entity representing a business concept defined by one or more business keys (e.g. Customer, Account).

- **Link**  
  A Data Vault entity representing a relationship between hubs (e.g. Customer-Account relationship).

- **Satellite**  
  A Data Vault entity storing descriptive attributes for a Hub or Link (e.g. customer name, address).

- **dbt Project**  
  A directory structure with configuration and SQL models used by dbt to build a data transformation pipeline.

- **Generated Artifact**  
  A recorded generation run of a dbt project by the Engine.