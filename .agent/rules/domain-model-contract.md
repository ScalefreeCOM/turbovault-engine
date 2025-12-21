---
trigger: manual
---

# 04 – Domain Model Contract

This rules file defines the **Data Vault domain model contract** for TurboVault Engine.  
These rules ensure that the core data model remains **stable, consistent, and reusable** across:

- the CLI-based **TurboVault Engine** (current project), and  
- the future **TurboVault Studio** web application.

If you are generating or modifying any **models, migrations, or services that touch the domain**, you must follow these rules.

---

## 1. Domain Model Is a Shared Contract

The domain model is **not an implementation detail** – it is the shared language between:

- configuration (`config.yml`),
- in-memory services,
- Django models,
- future API/Studio layers.

Therefore:

- Treat the domain model as a **contract**.
- Avoid “helpful” renames or restructurings unless explicitly requested.

---

## 2. Core Entities (Authoritative List)

These are the **core entities** that define TurboVault’s Data Vault model.  
Their names and responsibilities are **frozen by default**:

### 2.1 Root & Context

- `Project`  
  Represents a full modeling context (one DV/dbt implementation), with metadata like name, description, and configuration.

### 2.2 Source Metadata

- `source_system`  
  Describes a physical source system (database/schema) and a human-readable name.

- `source_table`  
  Represents a physical source table and stores DV-related config (record source, load date, etc.).

- `source_column`  
  Represents a column in a source table (name, datatype).

### 2.3 Hubs & Hub Mappings

- `hub`  
  Defines a Data Vault hub entity, its type (standard/reference), hash key name, and flags for satellites.

- `hub_column`  
  Defines hub columns (business keys, additional columns, reference keys) and their ordering.

- `hub_source_mapping`  
  Maps hub columns to source columns and marks the primary source mapping.

### 2.4 Links & Link Mappings

- `link`  
  Defines a Data Vault link entity, its type (standard/non-historized), and references to standard hubs.

- `link_column`  
  Defines link columns (payload, additional columns).

- `link_source_mapping`  
  Maps link columns to source columns.

- `link_hub_source_mapping`  
  Defines how link hub keys are derived from source columns or prejoin extraction columns.

### 2.5 Prejoin Logic

- `prejoin_definition`  
  Describes a pre-join relationship between source tables (join columns, operator).

- `prejoin_extraction_column`  
  Defines columns extracted from pre-joined target tables.

### 2.6 Satellites

- `satellite`  
  Represents a satellite attached to a hub or link, with satellite type (standard, reference, non-historized, multi-active).

- `satellite_column`  
  Maps source columns into a satellite, with multi-active and delta-detection flags, renaming, and transformation.

### 2.7 Snapshot & Reference Modeling

- `snapshot_control_table`  
  Stores global snapshot configuration (date range, daily time).

- `snapshot_control_logic`  
  Stores reusable snapshot patterns (daily, month-end, etc., with duration/unit or forever).

- `reference_table`  
  Represents a reference table derived from a reference hub, with historization type and snapshot settings.

- `reference_table_satellite_assignment`  
  Assigns reference satellites and their columns to a reference table (include/exclude lists).

### 2.8 PIT (Point-in-Time)

- `pit`  
  Defines a PIT structure for a tracked hub or link, snapshot configuration, and included satellites.

---

## 3. Allowed Changes vs. Disallowed Changes

When working with the domain model, follow these rules:

### 3.1 Disallowed (Without Explicit Instruction)

- **Renaming core entities**  
  Do not rename `hub` to `HubEntity`, `source_table` to `SourceTableMetadata`, etc.
- **Renaming core fields** in a way that alters semantics (e.g. turning `hub_type` into `kind`).
- **Splitting a core entity** into multiple overlapping models that represent the same concept.
- **Merging distinct concepts** into a generic catch-all model (e.g. combining `hub` and `link` into one “Node” model).
- **Changing relationships** in a way that breaks documented semantics:
  - e.g. allowing `link` to reference non-standard hubs where the spec forbids it.
- **Introducing new “root” entities** that duplicate the role of `Project`.

If a change of this kind is genuinely needed, it must be called out explicitly as a **domain model refactor**, not done silently.

### 3.2 Allowed (With Care)

The following modifications are allowed, as long as they remain consistent with `02_domain_model.md`:

- Adding **non-breaking fields**:
  - New optional configuration attributes that don’t change existing behavior.
- Adding **indexes/constraints** that enforce already-documented rules:
  - e.g. uniqueness constraints, “only one primary mapping per hub” constraints, etc.
- Adding **helper/computed properties**:
  - e.g. model methods that derive convenience values without changing the schema contract.
- Adding **integration fields** that are clearly auxiliary:
  - e.g. internal IDs for external tools, as long as they don’t alter core meaning.

---

## 4. Relationships & Semantics (Must Respect Spec)

The semantics defined in `02_domain_model.md` are binding. In particular:

- `Project` is the **scope** for almost all entities.
- `source_system` → `source_table` → `source_column` form a hierarchy.
- `hub` is a DV entity with:
  - `hub_type` (`standard` or `reference`),
  - hash key name (for standard hubs),
  - satellites controlled by flags.
- `link` **connects standard hubs only** (as per `hub_references`).
- `satellite` attaches to **exactly one parent** (hub or link).
- `reference_table`:
  - must reference a `hub` of type `reference`,
  - can optionally reference snapshot control structures.
- `pit`:
  - tracks either a hub or a link,
  - includes a set of satellites and can use snapshot control settings.

When generating or modifying code:

- Do not introduce relationships that contradict these rules.
- If you need a new association, justify it and ensure it doesn’t violate existing semantics.

---

## 5. Naming & Implementation Expectations

### 5.1 Model Names

- Django model class names should follow from the logical entities, e.g.:

  - `class Project(models.Model):`
  - `class SourceSystem(models.Model):`
  - `class SourceTable(models.Model):`
  - `class SourceColumn(models.Model):`
  - `class Hub(models.Model):`
  - `class HubColumn(models.Model):`
  - `class HubSourceMapping(models.Model):`
  - `class Link(models.Model):`
  - `class LinkColumn(models.Model):`
  - `class LinkSourceMapping(models.Model):`
  - `class LinkHubSourceMapping(models.Model):`
  - `class PrejoinDefinition(models.Model):`
  - `class PrejoinExtractionColumn(models.Model):`
  - `class Satellite(models.Model):`
  - `class SatelliteColumn(models.Model):`
  - `class SnapshotControlTable(models.Model):`
  - `class SnapshotControlLogic(models.Model):`
  - `class ReferenceTable(models.Model):`
  - `class ReferenceTableSatelliteAssignment(models.Model):`
  - `class Pit(models.Model):`

- The **logical names** (from the spec) and the **Django class names** must be clearly aligned and traceable.

### 5.2 Field Names

- Field names should mirror the spec as much as possible:
  - e.g. `hub_type`, `hub_physical_name`, `link_physical_name`, `satellite_type`, `snapshot_start_date`, etc.
- Where Django conventions differ (e.g. `_id` suffix for foreign keys), ensure that the semantic name is still clearly preserved, e.g.:

  ```python
  hub = models.ForeignKey("Hub", on_delete=models.CASCADE, related_name="columns")
```
mapped from logical `hub_id`.

### 6. Services & Domain Model Usage

Service functions must treat the domain model as the single source of truth:

*   **Configuration (`config.yml`)** should be translated into domain entities:
    *   *not* into ad hoc custom in-memory structures that bypass models.
*   **dbt generation logic** should:
    *   query the domain model,
    *   *not* rely on parallel “shadow models” or untracked structures.
*   **Import logic** should:
    *   populate and update domain entities,
    *   *not* store metadata in separate “temporary” models unless clearly justified.
*   If a service needs additional derived structures (e.g. internal graphs, maps, caches), those should be:
    *   built on top of the domain entities,
    *   *not* used as a replacement for them.

### 7. Migration & Evolution

When the domain model truly needs to evolve:

1.  **Update the spec first:**
    *   Modify `02_domain_model.md` to reflect the new structure or semantics.
    *   Clearly mark the change (e.g. new field, new entity, changed relationship).
2.  **Then update code and migrations:**
    *   Adjust Django models to match the spec.
    *   Create appropriate migrations.
    *   Update services that depend on the changed model.
3.  **Do not silently introduce breaking schema changes** without updating the specification.

### 8. When Unsure: Prefer the Spec

If there is a conflict between:

*   convenience in a particular function
*   **vs.**
*   the rules, names, or relationships defined in the domain model specification,

**then:**

> The domain model spec wins.

When unsure how to proceed:

1.  Re-read `02_domain_model.md` and related docs.
2.  Prefer aligning with the established structure.
3.  If you still believe a change is required, treat it as a design discussion / explicit refactor, not as a quick “fix”.