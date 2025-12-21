---
trigger: manual
---

# 03 – Django Architecture & Project Structure

This rules file defines how **Django and the overall architecture** of TurboVault Engine should be structured.  
The goal is to keep the Engine clean, modular, and reusable as the core of the future TurboVault Studio web application.

---

## 1. High-Level Architecture

TurboVault Engine is a **Django-based application without HTTP views**.  
We use Django for:

- ORM and migrations,
- configuration and app wiring,
- management commands (and/or separate CLI wrapper).

The architecture is layered as follows:

1. **Domain Layer (Models)**
   - Django models that implement the domain described in `02_domain_model.md`.
   - Represents Projects, source metadata, DV entities (hubs, links, satellites, etc.), snapshot and PIT structures, and generation artifacts.

2. **Service Layer (Business Logic)**
   - Pure Python modules that implement:
     - configuration parsing and validation,
     - metadata import,
     - dbt project generation and filesystem I/O.
   - These services depend on the domain layer but not vice versa.

3. **Interface Layer (CLI / Commands)**
   - Django management commands and/or a Typer/Click CLI wrapper.
   - Thin orchestration layer that:
     - parses CLI arguments,
     - calls services,
     - reports success/failure to the user.

**Rule:**  
All new features must be implemented in terms of these layers.  
**Do not introduce** HTTP views, DRF viewsets, or templates in this project.

---

## 2. Project Layout

A typical layout for the Engine backend should look like:

```text
backend/
  manage.py
  turbovault/           # Django project config
    __init__.py
    settings.py
    urls.py             # minimal, no HTTP endpoints for Engine
    wsgi.py             # mostly unused in Engine phase
  engine/
    __init__.py
    apps.py
    models/
      __init__.py
      project.py
      source_metadata.py
      hubs.py
      links.py
      satellites.py
      prejoins.py
      snapshot_reference.py
      pit.py
      artifacts.py
    services/
      __init__.py
      config_loader.py
      import_metadata.py
      generate_dbt.py
      helpers/
        __init__.py
        dbt_layout.py
        filesystem.py
    cli/
      __init__.py
      management/
        __init__.py
        commands/
          turbovault_run.py
          turbovault_validate.py   # optional
          turbovault_describe.py   # optional
```
This is a **guiding structure**, not a strict requirement, but all code should adhere to the separation of concerns:
- **Models:** only in engine/models/.
- **Business logic / orchestration:** only in engine/services/.
- **CLI entrypoints:** only in engine/cli/management/commands/.

## 3. Domain Layer (Models)

### 3.1 Responsibilities

*   Represent the Data Vault domain as documented in `02_domain_model.md`.
*   Provide fields, relationships, and (if needed) minimal validation.
*   Remain as thin as possible in terms of business logic.

### 3.2 Rules

**Each logical group of models should live in a dedicated module, e.g.:**

*   `project.py` for `Project` and any project-level config models.
*   `source_metadata.py` for `source_system`, `source_table`, `source_column`.
*   `hubs.py` for `hub`, `hub_column`, `hub_source_mapping`.
*   `links.py` for `link`, `link_column`, `link_source_mapping`, `link_hub_source_mapping`.
*   `prejoins.py` for `prejoin_definition`, `prejoin_extraction_column`.
*   `satellites.py` for `satellite`, `satellite_column`.
*   `snapshot_reference.py` for `snapshot_control_table`, `snapshot_control_logic`, `reference_table`, `reference_table_satellite_assignment`.
*   `pit.py` for `pit`.
*   `artifacts.py` for generation artifacts (e.g. `GeneratedArtifact`).

**Models must not import or depend on:**

*   service modules (`engine.services.*`)
*   CLI modules (`engine.cli.*`)
*   web-related code (views, serializers, etc.)

**Keep model methods simple:**

*   **Acceptable:**
    *   small convenience methods
    *   simple validation in `clean()` or `save()`
    *   `__str__` / `__repr__`
*   **Not acceptable:**
    *   full data import pipelines
    *   dbt generation logic
    *   CLI I/O

## 4. Service Layer (Business Logic)

### 4.1 Responsibilities

Services implement the core behavior of TurboVault Engine:

*   **Configuration:**
    *   Load and parse `config.yml`.
    *   Validate it into typed config objects (e.g. Pydantic models, dataclasses).
*   **Metadata Import:**
    *   Read metadata from source systems (Excel files, later databases).
    *   Create/update domain models (`Project`, source tables/columns, hubs, links, satellites, etc.).
*   **dbt Generation:**
    *   Build an in-memory representation of the dbt project for a given `Project`.
    *   Write directories/files to the filesystem.
    *   Optionally create ZIP archives.
    *   Record the result in a `GeneratedArtifact`.

### 4.2 Rules

Service modules live in `engine/services/` (and optional `engine/services/helpers/`).

Services may depend on models (`engine.models.*`) and standard Django facilities (e.g. ORM, `transaction.atomic`), but:

*   **Models must not import services.**

**Keep services focused:**

*   `config_loader.py` → reading/validating config.
*   `import_metadata.py` → turning config + external metadata into domain model instances.
*   `generate_dbt.py` → turning domain model into dbt project structure on disk.

**Services should be structured as plain functions or small classes, for example:**

```python
def load_config(config_path: Path) -> Config:
    ...

def import_metadata(config: Config) -> Project:
    ...

def generate_dbt_project(project: Project, output: OutputConfig) -> Path:
    ...
```

**Prefer functional-style services that:**

*   take explicit parameters,
*   return explicit results or raise clear exceptions,
*   have minimal hidden side effects.

**Services should be written in a way that they can be:**

*   called from CLI now,
*   called from HTTP endpoints or Celery tasks later (Studio phase), without rewriting core logic.

## 5. Interface Layer (CLI / Commands)

### 5.1 Responsibilities

The CLI layer is responsible for:

*   Parsing command-line arguments.
*   Wiring together config loading, metadata import, and generation services.
*   Handling success/failure messaging and exit codes.

### 5.2 Rules

**All Django management commands live in `engine/cli/management/commands/`.**

Command names should be clear and consistent, e.g.:

*   `turbovault_run`
*   `turbovault_validate`
*   `turbovault_describe`

**Commands should be thin:**

*   Parse CLI arguments/options,
*   Call service functions,
*   Print results / errors using Django’s `self.stdout` / `self.stderr` or click/typer equivalents.
*   **Do not** contain complex business logic; any multi-step processing should be moved into services.

**Example pattern:**

```python
from pathlib import Path
from django.core.management.base import BaseCommand

from engine.services.config_loader import load_config
from engine.services.import_metadata import import_metadata
from engine.services.generate_dbt import generate_dbt_project


class Command(BaseCommand):
    help = "Run TurboVault Engine with the given configuration file."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--config",
            type=str,
            required=True,
            help="Path to the config.yml file.",
        )

    def handle(self, *args, **options) -> None:
        config_path = Path(options["config"])
        config = load_config(config_path)
        project = import_metadata(config)
        project_path = generate_dbt_project(project, config.output)

        self.stdout.write(self.style.SUCCESS(f"Generation completed: {project_path}"))
```

## 6. No HTTP / Web Layer in Engine

### 6.1 Hard Constraints

The TurboVault Engine **must not** define or depend on:

*   Django views (regular or class-based),
*   Django REST Framework viewsets, serializers, routers,
*   URL routes for an HTTP API,
*   HTML templates or static frontend assets.

**Reason:**
The Engine is intended to be a library and CLI tool. The future TurboVault Studio web application will import and use the Engine, but will live in a separate layer/project.

### 6.2 If Web-Like Behavior is Needed

If you find yourself wanting to:

*   expose an operation “as if it were an API”, or
*   design something with an HTTP mindset,

then:

*   Implement it as a service function in `engine/services/…`.
*   Document how it will be used later in Studio (e.g. in a doc comment or separate design doc).
*   **Do not** create Django views/DRF endpoints in the Engine.

## 7. Data & Project Scoping (Project-Centric Design)

### 7.1 Project as Root Aggregate

Conceptually, a `Project` is the root aggregate for almost all other entities:

*   Project → source metadata (`source_system`, `source_table`, `source_column`)
*   Project → DV objects (`hub`, `link`, `satellite`, etc.)
*   Project → snapshot, reference, PIT definitions
*   Project → generation artifacts

### 7.2 Rules

*   In implementation, most domain tables should have a project foreign key, even if not explicitly listed in the spec table.
*   All queries and service functions should be designed to operate within the context of a project.
*   Do not mix entities from different projects in a single generation run.

**Example:**

```python
def generate_dbt_project(project: Project, output: OutputConfig) -> Path:
    # Only use metadata and DV structures belonging to this project.
    ...
```

## 8. Transactions & Consistency

*   Use `transaction.atomic()` for operations that must succeed or fail as a unit:
    *   Example: metadata import that creates `Project`, `source_table`, `source_column`, etc. together.
*   Keep atomic blocks as small as practical to avoid long-running locks.
*   Avoid half-persisted states by:
    *   Doing validation prior to persistence where possible,
    *   Wrapping multi-step writes in a transaction.

## 9. Forward Compatibility with TurboVault Studio

### 9.1 Engine as a Library

The Engine should be designed so that TurboVault Studio can:

*   Add a new Django project that includes or depends on the Engine app,
*   Reuse models and services,
*   Configure a different DB backend (PostgreSQL, etc.),
*   Wrap service calls in HTTP endpoints and Celery tasks.

**Rules:**

*   Avoid tight coupling to CLI-only concerns in services (e.g. direct prints, `sys.exit`).
*   Prefer raising exceptions for error cases; let CLI or future HTTP layers handle user-facing messaging.
*   Keep settings usage minimal and explicit; avoid global state that would make import into another project difficult.

### 9.2 Separation of Concerns

If a feature feels like:

*   user management,
*   project sharing,
*   S3/Git integration,
*   or other multi-user concerns,

then:

*   It likely belongs to TurboVault Studio, not the Engine.
*   Leave hooks or placeholders where appropriate (e.g. `output_config` that could later be extended to S3), but don’t implement Studio-specific behavior here.

## 10. Summary

When implementing or modifying code in this repository, always check:

*   **Layering** – Is this code going into the right layer (models, services, CLI)?
*   **Dependencies** – Are we avoiding circular or inverted dependencies (models importing services, etc.)?
*   **Scope** – Is this functionality appropriate for the Engine phase (no HTTP, no Studio-only features)?
*   **Reusability** – Will TurboVault Studio be able to reuse this logic without major refactoring?

If the answer to any of these is “no” or “uncertain”, reconsider the design or raise it explicitly before proceeding.