---
sidebar_position: 1
sidebar_label: Overview
title: Overview
---

# TurboVault Engine Overview

## Introduction

TurboVault Engine is a **CLI-first, Django-based engine** for turning source system metadata into a **Data Vault–oriented model** and a **fully structured dbt project**.

It is designed to:

- Read metadata from configurable sources (e.g. Excel files, database catalogs).
- Map this metadata into a consistent **internal Data Vault domain model** (Sources, Hubs, Links, Satellites, etc.).
- Generate a **ready-to-use dbt project** (directory + optional ZIP archive) based on this model.

TurboVault Engine is intended to be:

1. **Standalone & open-source** – directly usable by Data Warehouse Engineers from the command line.
2. **The core engine behind future Front-Ends** – all future applications will reuse the same models and services, exposing them via an HTTP API and UI.

This document gives a detailed overview of the Engine’s purpose, scope, architecture, and how it will be used both in standalone mode and inside the web application.


## Primary Use Cases

### Local Modeling & Generation by Data Engineers

A Data Warehouse Engineer can:

1. Describe their source system metadata and desired Data Vault model in a relational table format stored in Excel or a database.
2. Define project-specific configuration in the project's config.yml file.
3. Run the Engine generation locally.
4. Obtain a fully structured dbt project as output.

Typical use cases:
- Rapid prototyping of a Data Vault implementation.
- Generating a starting point for a dbt project from spreadsheet-defined metadata.
- Converting a known schema (e.g. a staging DB schema) into a DV/dbt structure.

### Batch Generation and CI/CD Integration

Because the Engine is CLI-driven and deterministic, it can be integrated into:

- CI pipelines (e.g. GitHub Actions, GitLab CI) to:
  - Validate configurations.
  - Re-generate dbt projects when metadata or mapping rules change.
- Internal tools that programmatically produce `config.yml` files and then call the Engine.

---

## Configuration Model (`config.yml`)

The Engine is driven by a `config.yml` file. While details are defined in the [Configuration Schema Reference](../03_configuration/03_project-schema.md), the high-level structure includes:

- `project`
  - Name, description, optional identifiers.
- `metadata_source`
  - Type (`excel` or `sqlite`).
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

## Standalone Usage

In its initial form, TurboVault Engine is used **exclusively as a CLI tool**.

### Installation

Example (details in README):

```bash
pip install turbovault-engine
```
### Typical Commands

Initialize a workspace:
```bash
turbovault workspace init
```

Create a new project:
```bash
turbovault project init --name my_project
```

Run a generation:
```bash
turbovault generate --project my_project
```

> **See also:** The [CLI Reference](../02_getting-started/01_cli-reference.md) documents every command, flag, and workflow example in detail.

### Local Database Usage

By default:
- A local **SQLite database** can be used to persist the domain model during a run.
- This allows inspection of the modeled entities if desired (e.g. using Django shell).

Advanced users may choose to configure a **PostgreSQL** or other database backend via standard Django settings, especially if they want persistence across multiple runs or integration with other tools.

---

## Glossary (Engine Context)

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
