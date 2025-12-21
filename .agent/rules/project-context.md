---
trigger: always_on
---

# 01 – Project Context: TurboVault Engine

This rules file defines the **high-level context and intent** of the TurboVault Engine.  
All code and design decisions in this repository should be consistent with the constraints below.

---

## 1. What TurboVault Engine Is

- TurboVault Engine is a **CLI-first, Django-based engine** that:
  - Ingests source metadata (e.g. from Excel files or database tables),
  - Maps it into a **Data Vault–oriented domain model**, and
  - Generates a complete **dbt project** (directory + optional ZIP) from that model.

- It is intended to be:
  - **Standalone & open-source**, usable directly from the command line by Data Warehouse / BI engineers.
  - The **core backend engine** for a future web application called **TurboVault Studio**, which will reuse this engine’s models and services.

- The main entry point for users is a **config-driven CLI command**, for example:
  - `turbovault run --config config.yml`

---

## 2. Scope and Responsibilities (Engine Phase)

When working on this project, assume we are in the **Engine (Pre-MVP) phase** with the following scope:

- **In scope:**
  - Defining and maintaining a **stable domain model** for:
    - Projects and configuration context,
    - Source systems, tables, and columns,
    - Hubs, links, satellites and their mappings,
    - Pre-join definitions and extraction columns,
    - Snapshot control, reference modeling, and PIT structures.
  - Implementing **services** that:
    - Parse and validate a `config.yml`,
    - Import external metadata into the domain model,
    - Generate dbt project structures (files and folders),
    - Optionally zip the generated dbt project.
  - Implementing a **CLI interface** that orchestrates these services.

- **Out of scope (for the Engine itself):**
  - No **HTTP API** or web views (no DRF, no Django templates, no REST endpoints).
  - No **user authentication**, authorization, or role management.
  - No **S3 or cloud storage** – output is local filesystem only in this phase.
  - No **Git integration** or repository manipulation (no commit/push).
  - No **frontend** (React/Next.js) code in this project.

If a feature idea clearly belongs to a future web application (TurboVault Studio), prefer to **mention it as a future extension** rather than implementing it here.

---

## 3. Domain Model as a Contract

The Data Vault domain model is a **contract** shared between the CLI Engine and the future Studio.  
Core entities include (non-exhaustive list):

- `Project`
- `source_system`, `source_table`, `source_column`
- `hub`, `hub_column`, `hub_source_mapping`
- `link`, `link_column`, `link_source_mapping`, `link_hub_source_mapping`
- `prejoin_definition`, `prejoin_extraction_column`
- `satellite`, `satellite_column`
- `snapshot_control_table`, `snapshot_control_logic`
- `reference_table`, `reference_table_satellite_assignment`
- `pit`

Rules:

- **Do not rename** these models or their core fields unless there is an explicit instruction to change the domain model.
- **Do not introduce alternative models** that represent the same concept (e.g. no second “Table” model).
- **Respect relationships and semantics** as defined in the domain model documentation (e.g. `02_domain_model.md`).

When in doubt about how an entity should behave or relate to others, prefer to **align with the existing domain spec** rather than inventing new structure.

---

## 4. Architectural Structure

The codebase should follow a clear layering:

- **Django models (domain):**
  - Live under something like `engine/models/`.
  - Represent the entities listed above.
  - Should contain minimal business logic (mostly structure and simple validation).

- **Services (business logic):**
  - Live under something like `engine/services/`.
  - Implement:
    - `config` parsing and validation,
    - metadata import from Excel/DB into models,
    - dbt project generation (in-memory representation + filesystem writes).
  - May depend on models, but models should **not** import services.

- **CLI / management commands (or Typer/Click CLI):**
  - Live under something like `engine/cli/`.
  - Should be **thin orchestration layers**:
    - Parse CLI args,
    - Call services,
    - Report success/errors.
  - Must not contain heavy business logic.

Rules:

- Prefer adding new behavior as a **service function** that consumes domain objects and/or IDs instead of embedding logic directly in commands.
- Avoid introducing any HTTP-layer concepts here (no serializers, no viewsets, no URL routing beyond what is minimally required for Django itself).

---

## 5. Usage & Interaction Pattern

The main interaction pattern with TurboVault Engine is:

1. **User edits `config.yml`** to describe:
   - Project metadata,
   - Source metadata source(s) (Excel or database),
   - Data Vault modeling rules/config (hubs, links, satellites, etc.),
   - Output configuration (dbt project path, project/profile names, ZIP option).

2. **User runs the CLI**, e.g.:
   - `turbovault run --config config.yml`

3. **Engine behavior**:
   - Initialize Django (settings, DB).
   - Parse and validate the config.
   - Import metadata into the domain model.
   - Generate the dbt project structure.
   - Write it to disk and optionally create a ZIP.
   - Persist a record of the generation run (e.g. `GeneratedArtifact`).

4. **User consumes the output**:
   - Opens the generated dbt project locally.
   - Integrates it into their data platform and version control manually.

When adding new features, ensure they **fit into this flow** and do not assume a web server, multiple concurrent users, or cloud infrastructure.

---

## 6. Forward Compatibility with TurboVault Studio

TurboVault Studio (future webapp) will:

- Reuse this Engine as a **library**:
  - Same Django models,
  - Same import and generation services.
- Add:
  - Users, projects, permissions, and sharing,
  - HTTP API endpoints and background workers,
  - S3/Git integration and a UI.

Therefore:

- Keep the Engine **clean and modular**, so it can be imported into another project.
- Avoid Studio-specific concerns here; instead, design Engine services so they can be:
  - Called from CLI now,
  - Called from HTTP endpoints or Celery tasks later.

If a suggested change would make the Engine **harder to reuse** in a multi-user web context, prefer a design that keeps the core logic clean and independent.

---
More detailed context about the project can be found in docs/01_overview.md