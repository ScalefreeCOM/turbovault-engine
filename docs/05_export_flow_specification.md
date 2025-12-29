# 05 – Export Flow Specification: dbt Project Generation

This document specifies the design and implementation plan for generating dbt projects from the TurboVault Engine domain model.

---

## 1. Overview

The dbt project generation transforms the intermediate export representation (currently JSON) into a complete, ready-to-use dbt project. This involves:

1. **Templating System** – Customizable Jinja2 templates for all model types
2. **File Generation** – SQL models and YAML configuration files
3. **Folder Structure** – Organized directories for stages, raw vault, business vault, and control
4. **Validation** – Pre-generation validation and error handling

---

## 2. Current State

The existing export pipeline:

```
Django Models → ModelBuilder → Pydantic Export Models → JSON Exporter
```

The new generation pipeline extends this:

```
Django Models → ModelBuilder → Pydantic Export Models → dbt Project Generator
                                                              ↓
                                                    ┌─────────────────────────┐
                                                    │  Template Engine        │
                                                    │  (Jinja2 + DB Templates)│
                                                    └─────────────────────────┘
                                                              ↓
                                                    ┌─────────────────────────┐
                                                    │  File Writer            │
                                                    │  (SQL, YAML, folders)   │
                                                    └─────────────────────────┘
```

---

## 3. Templating System Design

### 3.1 Overview

The templating system uses **Jinja2** templates stored either:
- As **database-backed templates** (Django models) for runtime customization
- As **file-based default templates** for fallback when no DB template exists

This hybrid approach allows:
- **Admin UI customization** through Django Admin
- **Version-controlled defaults** in the codebase
- **Per-project template overrides** (future enhancement)

### 3.2 Template Django Models

New models in `engine/models/templates.py` (separate from core domain models):

```python
class TemplateCategory(models.Model):
    """Categories for organizing templates."""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)


class ModelTemplate(models.Model):
    """Customizable Jinja2 templates for dbt model generation."""
    
    class EntityType(models.TextChoices):
        # Staging
        STAGE = 'stage', 'Stage'
        
        # Raw Vault - Hubs
        HUB_STANDARD = 'hub_standard', 'Hub (Standard)'
        HUB_REFERENCE = 'hub_reference', 'Hub (Reference)'
        
        # Raw Vault - Links
        LINK_STANDARD = 'link_standard', 'Link (Standard)'
        LINK_NON_HISTORIZED = 'link_non_historized', 'Link (Non-Historized)'
        
        # Raw Vault - Satellites
        SATELLITE_STANDARD = 'satellite_standard', 'Satellite (Standard)'
        SATELLITE_NON_HISTORIZED = 'satellite_non_historized', 'Satellite (Non-Historized)'
        SATELLITE_REFERENCE = 'satellite_reference', 'Satellite (Reference)'
        SATELLITE_MULTI_ACTIVE = 'satellite_multi_active', 'Satellite (Multi-Active)'
        SATELLITE_EFFECTIVITY = 'satellite_effectivity', 'Effectivity Satellite'
        SATELLITE_RECORD_TRACKING = 'satellite_record_tracking', 'Record Tracking Satellite'
        
        # Business Vault
        PIT = 'pit', 'PIT'
        REFERENCE_TABLE = 'reference_table', 'Reference Table'
        
        # Control
        SNAPSHOT_CONTROL_TABLE = 'snapshot_control_table', 'Snapshot Control Table'
        SNAPSHOT_CONTROL_LOGIC = 'snapshot_control_logic', 'Snapshot Control Logic'
    
    class TemplateType(models.TextChoices):
        SQL = 'sql', 'SQL Model'
        YAML = 'yaml', 'YAML Schema'
    
    name = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=50, choices=EntityType.choices)
    template_type = models.CharField(max_length=10, choices=TemplateType.choices)
    category = models.ForeignKey(TemplateCategory, on_delete=models.SET_NULL, null=True)
    
    # The Jinja2 template content
    sql_template_content = models.TextField(
        blank=True,
        help_text="Jinja2 template for SQL model file"
    )
    yaml_template_content = models.TextField(
        blank=True,
        help_text="Jinja2 template for YAML schema file"
    )
    
    # Priority for template selection (higher = preferred)
    priority = models.IntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['entity_type', 'name']
```

### 3.3 Template Resolver

The template resolver determines which template to use based on entity type:

```python
class TemplateResolver:
    """Resolves templates with fallback to file-based defaults."""
    
    def get_available_variants(self, entity_type: str) -> list[str]:
        """
        Get list of available template variants for an entity type.
        Used by Admin UI to show selectable options.
        """
    
    def get_template(
        self,
        entity_type: str,
        template_type: str = 'sql'
    ) -> tuple[Template, Template]:
        """
        Get SQL and YAML templates for an entity type.
        
        Priority:
        1. Active DB template matching entity_type (highest priority)
        2. File-based template from templates/ directory
        
        Returns:
            Tuple of (sql_template, yaml_template)
        """
```

### 3.4 Template Context by Entity Type

| Entity Type | Context Variables |
|-------------|-------------------|
| **Stage** | `stage_name`, `source_table`, `source_schema`, `source_system`, `record_source`, `load_date`, `hashkeys[]`, `hashdiffs[]`, `prejoins[]`, `multi_active_config`, `columns[]` |
| **Hub (Standard)** | `hub_name`, `hashkey`, `business_key_columns[]`, `additional_columns[]`, `source_tables[]` |
| **Hub (Reference)** | `hub_name`, `business_key_columns[]`, `source_tables[]` |
| **Link (Standard)** | `link_name`, `hashkey`, `hub_references[]`, `business_key_columns[]`, `source_tables[]` |
| **Link (Non-Historized)** | `link_name`, `hashkey`, `hub_references[]`, `payload_columns[]`, `source_tables[]` |
| **Satellite (All Types)** | `satellite_name`, `satellite_type`, `parent_entity`, `parent_entity_type`, `stage_name`, `hashdiff_name`, `columns[]` |
| **PIT** | `pit_name`, `tracked_entity_type`, `tracked_entity_name`, `satellites[]`, `snapshot_logic_column` |
| **Reference Table** | `table_name`, `reference_hub_name`, `historization_type`, `satellites[]` |
| **Snapshot Control Table** | `name`, `start_date`, `end_date`, `daily_time` → generates `{{ name }}_v0` |
| **Snapshot Control Logic** | `name` (from parent), `column_name`, `component`, `duration`, `unit`, `forever` → generates `{{ name }}_v1` |

### 3.5 Default File-Based Templates

Location: `engine/services/generation/templates/`

```
templates/
├── sql/
│   ├── stage.sql.j2
│   ├── hub_standard.sql.j2
│   ├── hub_reference.sql.j2
│   ├── link_standard.sql.j2
│   ├── link_non_historized.sql.j2
│   ├── satellite_standard.sql.j2
│   ├── satellite_non_historized.sql.j2
│   ├── satellite_reference.sql.j2
│   ├── satellite_multi_active.sql.j2
│   ├── satellite_effectivity.sql.j2
│   ├── satellite_record_tracking.sql.j2
│   ├── satellite_v1.sql.j2              # Load-end-date view wrapper
│   ├── pit.sql.j2
│   ├── reference_table.sql.j2
│   ├── snapshot_control_table.sql.j2
│   └── snapshot_control_logic.sql.j2
└── yaml/
    ├── sources.yml.j2
    ├── stage.yml.j2
    ├── hub_standard.yml.j2
    ├── hub_reference.yml.j2
    ├── link_standard.yml.j2
    ├── link_non_historized.yml.j2
    ├── satellite_standard.yml.j2
    ├── satellite_non_historized.yml.j2
    ├── satellite_reference.yml.j2
    ├── satellite_multi_active.yml.j2
    ├── satellite_v1.yml.j2              # Load-end-date view schema
    ├── pit.yml.j2
    ├── reference_table.yml.j2
    ├── snapshot_control_table.yml.j2
    ├── snapshot_control_logic.yml.j2
    └── dbt_project.yml.j2
```

---

## 4. Satellite Dual-Model Generation (_v0 and _v1)

### 4.1 Overview

Every satellite generates **two models** by default:
1. **`<satellite_name>_v0`** – The core satellite model (always generated)
2. **`<satellite_name>_v1`** – A view on top of `_v0` that adds `load_end_date` column

### 4.2 Project Configuration

New project configuration option in `Project.config`:

```python
# In project config JSON
{
    "generation": {
        "generate_satellite_v1_views": true,  # Default: true
        "satellite_v1_suffix": "_v1",         # Default: "_v1"
        "satellite_v0_suffix": "_v0"          # Default: "_v0"
    }
}
```

### 4.3 V1 View Logic

The `_v1` model is a simple dbt view that wraps the `_v0` satellite:

```sql
-- satellite_v1.sql.j2
{{ config(materialized='view') }}

SELECT
    *,
    LEAD(ldts) OVER (
        PARTITION BY {{ parent_hashkey }}
        ORDER BY ldts
    ) AS load_end_date
FROM {{ ref('{{ satellite_name }}_v0') }}
```

### 4.4 Generated Files Per Satellite

For a satellite `sat_customer_details`:

| File | Description |
|------|-------------|
| `sat_customer_details_v0.sql` | Core satellite model |
| `sat_customer_details_v0.yml` | Schema for core satellite |
| `sat_customer_details_v1.sql` | Load-end-date view |
| `sat_customer_details_v1.yml` | Schema for view |

---

## 5. File Generation Specification

### 5.1 Files to Generate

| File Type | Description | One Per |
|-----------|-------------|---------|
| `dbt_project.yml` | Project configuration | Project |
| `packages.yml` | dbt packages (datavault4dbt) | Project |
| `sources.yml` | All source definitions | Project (in staging base) |
| `<model>.sql` | SQL model file | Entity |
| `<model>.yml` | Model schema/tests | Entity (one YAML per model) |

### 5.2 YAML File Specifications

#### 5.2.1 `dbt_project.yml`

```yaml
name: '{{ project_name }}'
version: '1.0.0'
config-version: 2

profile: '{{ profile_name }}'

model-paths: ["models"]
analysis-paths: ["analyses"]
test-paths: ["tests"]
seed-paths: ["seeds"]
macro-paths: ["macros"]
snapshot-paths: ["snapshots"]

clean-targets:
  - "target"
  - "dbt_packages"

models:
  {{ project_name }}:
    staging:
      +schema: stage
      +materialized: view
    raw_vault:
      +schema: rdv
      +materialized: incremental
    business_vault:
      +schema: bdv
      +materialized: table
    control:
      +schema: control
      +materialized: table
```

#### 5.2.2 `sources.yml` (single file in staging base)

One `sources.yml` file in the staging base directory containing **all** source systems:

```yaml
version: 2

sources:
  {% for source_system in source_systems %}
  - name: {{ source_system.name }}
    database: {{ source_system.database_name }}
    schema: {{ source_system.schema_name }}
    tables:
      {% for table in source_system.tables %}
      - name: {{ table.table_name }}
        description: "Source table from {{ source_system.name }}"
        columns:
          {% for column in table.columns %}
          - name: {{ column.column_name }}
            data_type: {{ column.datatype }}
          {% endfor %}
      {% endfor %}
  {% endfor %}
```

#### 5.2.3 Model YAML (per model, entity-type specific)

Each entity type has its own YAML template with appropriate tests:

```yaml
# Example: hub_standard.yml.j2
version: 2

models:
  - name: {{ hub_name }}
    description: "Standard hub for {{ hub_name }}"
    config:
      tags: ['hub', 'raw_vault'{% if group %}, '{{ group }}'{% endif %}]
    columns:
      - name: {{ hashkey.hashkey_name }}
        description: "Hash key for {{ hub_name }}"
        data_tests:
          - unique
          - not_null
      {% for bk in business_key_columns %}
      - name: {{ bk }}
        description: "Business key column"
        data_tests:
          - not_null
      {% endfor %}
      - name: ldts
        description: "Load date timestamp"
      - name: rsrc
        description: "Record source"
```

---

## 6. Folder Structure

### 6.1 Complete Structure

```
output/
└── {{ project_name }}/
    ├── dbt_project.yml
    ├── packages.yml
    ├── models/
    │   ├── staging/
    │   │   ├── sources.yml                         # Single file with ALL sources
    │   │   ├── {{ source_system_1 }}/
    │   │   │   ├── stg__{{ source_system }}_{{ table }}.sql
    │   │   │   └── stg__{{ source_system }}_{{ table }}.yml
    │   │   └── {{ source_system_2 }}/
    │   │       └── ...
    │   │
    │   ├── raw_vault/
    │   │   ├── hub_{{ ungrouped }}.sql             # Ungrouped entities in base folder
    │   │   ├── hub_{{ ungrouped }}.yml
    │   │   ├── sat_{{ ungrouped }}_v0.sql
    │   │   ├── sat_{{ ungrouped }}_v0.yml
    │   │   ├── {{ group_1 }}/                      # Groups as subdirectories
    │   │   │   ├── hub_{{ name }}.sql
    │   │   │   ├── hub_{{ name }}.yml
    │   │   │   ├── link_{{ name }}.sql
    │   │   │   ├── link_{{ name }}.yml
    │   │   │   ├── sat_{{ name }}_v0.sql
    │   │   │   ├── sat_{{ name }}_v0.yml
    │   │   │   ├── sat_{{ name }}_v1.sql           # Load-end-date view
    │   │   │   └── sat_{{ name }}_v1.yml
    │   │   └── {{ group_2 }}/
    │   │       └── ...
    │   │
    │   ├── business_vault/
    │   │   ├── pits/
    │   │   │   ├── pit_{{ name }}.sql
    │   │   │   └── pit_{{ name }}.yml
    │   │   └── reference_tables/
    │   │       ├── ref_{{ name }}.sql
    │   │       └── ref_{{ name }}.yml
    │   │
    │   └── control/
    │       ├── {{ name }}_v0.sql                    # Snapshot control table
    │       ├── {{ name }}_v0.yml
    │       ├── {{ name }}_v1.sql                    # Snapshot control logic
    │       └── {{ name }}_v1.yml
    │
    └── macros/
        └── (optional custom macros)
```

### 6.2 Folder Structure Rules

| Layer | Grouping Strategy |
|-------|-------------------|
| **Staging** | Subdirectory per source system; single `sources.yml` at base |
| **Raw Vault** | Subdirectory per `group`; all entity types mixed within group; ungrouped entities placed directly in `raw_vault/` base folder |
| **Business Vault** | Subdirectories for `pits/` and `reference_tables/` |
| **Control** | Flat structure for snapshot control tables and logic |

### 6.3 Folder Config

```python
@dataclass
class FolderConfig:
    """Configuration for dbt project folder structure."""
    
    staging_path: str = "models/staging"
    raw_vault_path: str = "models/raw_vault"
    business_vault_path: str = "models/business_vault"
    control_path: str = "models/control"
    
    # Business vault subdirectories
    pits_subdir: str = "pits"
    reference_tables_subdir: str = "reference_tables"
    
    # Note: Ungrouped entities go directly in base folders (no subdirectory)
```

---

## 7. Validation & Error Handling

### 7.1 Pre-Generation Validation

| Validation Rule | Entity | Severity |
|-----------------|--------|----------|
| Hub must have at least one business key column | Hub | ERROR |
| Standard hub must have hashkey name | Hub | ERROR |
| Link must reference at least 2 hubs | Link | ERROR |
| Link must have hashkey name | Link | ERROR |
| Satellite must have parent (hub or link) | Satellite | ERROR |
| Satellite must have at least one column | Satellite | WARNING |
| Satellite must have source_table assigned | Satellite | ERROR |
| PIT must have at least one satellite | PIT | ERROR |
| PIT must have snapshot logic column | PIT | ERROR |
| Stage must have source table defined | Stage | ERROR |
| Hashdiff must have at least one column | Stage | WARNING |
| Source system must have schema name | Source | ERROR |
| Snapshot control table must have name | Snapshot | ERROR |
| Snapshot control logic must have column name | Snapshot | ERROR |
| Template must be valid Jinja2 | Template | ERROR |

### 7.2 Validation Result Model

```python
@dataclass
class ValidationResult:
    """Result of pre-generation validation."""
    is_valid: bool
    errors: list[ValidationError]
    warnings: list[ValidationWarning]

@dataclass
class ValidationError:
    entity_type: str
    entity_name: str
    field: str
    message: str
    code: str  # e.g., "HUB_001"

@dataclass
class ValidationWarning:
    entity_type: str
    entity_name: str
    field: str
    message: str
    code: str
```

### 7.3 Error Handling Strategy

1. **Strict Mode (default)**: Stop generation on first ERROR
2. **Lenient Mode**: Skip invalid entities, continue with valid ones
3. **Warnings**: Always logged, never stop generation

### 7.4 Generation Report

```python
@dataclass
class GenerationReport:
    """Summary of dbt project generation."""
    success: bool
    project_path: Path
    generated_at: datetime
    
    # Counts
    stages_generated: int
    hubs_generated: int
    links_generated: int
    satellites_generated: int  # Counts _v0 models
    satellite_views_generated: int  # Counts _v1 models
    pits_generated: int
    reference_tables_generated: int
    snapshot_controls_generated: int
    
    # Issues
    errors: list[GenerationError]
    warnings: list[str]
    skipped_entities: list[SkippedEntity]
    validation_result: ValidationResult
```

---

## 8. Service Architecture

### 8.1 New Service Modules

Location: `engine/services/generation/`

```
engine/services/generation/
├── __init__.py
├── generator.py          # Main DbtProjectGenerator class
├── template_resolver.py  # Template loading with DB/file fallback
├── file_writer.py        # File/folder creation utilities
├── validators.py         # Pre-generation validation
├── context_builders.py   # Build template contexts from Pydantic models
└── templates/
    ├── sql/
    │   └── ...
    └── yaml/
        └── ...
```

### 8.2 Main Generator Interface

```python
class DbtProjectGenerator:
    """Generate a dbt project from export data."""
    
    def __init__(
        self,
        output_path: Path,
        template_resolver: TemplateResolver | None = None,
        folder_config: FolderConfig | None = None,
        mode: GenerationMode = GenerationMode.STRICT
    ) -> None:
        ...
    
    def generate(
        self,
        project_export: ProjectExport,
        project_config: dict | None = None
    ) -> GenerationReport:
        """
        Generate complete dbt project.
        
        Steps:
        1. Validate export data
        2. Create folder structure
        3. Generate dbt_project.yml and packages.yml
        4. Generate sources.yml (single file with all sources)
        5. Generate stage models
        6. Generate raw vault models (hubs, links, satellites with _v0/_v1)
        7. Generate business vault models (PITs, reference tables)
        8. Generate control models (snapshot control tables and logic)
        9. Return generation report
        """
```

---

## 9. CLI Integration

### 9.1 CLI Command

```bash
# Generate dbt project
turbovault generate --project "Pizza Delivery Empire" --output ./output

# With options
turbovault generate \
    --project "Pizza Delivery Empire" \
    --output ./output \
    --mode lenient \
    --zip \
    --no-v1-satellites
```

### 9.2 CLI Options

| Option | Description | Default |
|--------|-------------|---------|
| `--project` | Project name or ID | Required |
| `--output` | Output directory path | `./output` |
| `--mode` | `strict` or `lenient` | `strict` |
| `--zip` | Create ZIP archive | `false` |
| `--skip-validation` | Skip pre-generation validation | `false` |
| `--no-v1-satellites` | Skip generating satellite _v1 views | `false` |
| `--template-dir` | Override template directory | None |

---

## 10. Pydantic Model Extensions

### 10.1 Snapshot Control Export Model Enhancement

The `SnapshotControlDefinition` Pydantic model includes computed properties for deriving model file names:

```python
class SnapshotControlDefinition(BaseModel):
    """
    Snapshot control table definition.
    
    During dbt generation, this produces two models:
    - `{name}_v0`: The snapshot control table model (base metadata)
    - `{name}_v1`: The snapshot control logic model (logic patterns)
    """
    
    name: str  # Base name (e.g., 'control_snap')
    start_date: str
    end_date: str
    daily_time: str
    logic_patterns: list[SnapshotLogicPattern]
    
    @property
    def v0_name(self) -> str:
        """Model name for snapshot control table: {base_name}_v0"""
        base_name = self.name.removesuffix("_v0").removesuffix("_v1")
        return f"{base_name}_v0"
    
    @property
    def v1_name(self) -> str:
        """Model name for snapshot control logic: {base_name}_v1"""
        base_name = self.name.removesuffix("_v0").removesuffix("_v1")
        return f"{base_name}_v1"
```

**Usage:**
- The `v0_name` property provides the model filename for the control table (base config)
- The `v1_name` property provides the model filename for the control logic
- Both v0 and v1 models are derived from the same `SnapshotControlDefinition` export data

---

## 11. Implementation Phases

### Phase 1: Foundation
- [ ] Create `ModelTemplate` and `TemplateCategory` Django models
- [ ] Implement `TemplateResolver` with file-based fallback
- [ ] Create default file-based templates for all entity types (including satellite _v1)
- [ ] Implement `FolderConfig` and folder creation utilities
- [ ] Add `physical_name` to snapshot control export models

### Phase 2: Core Generation
- [ ] Implement `DbtProjectGenerator` class
- [ ] Implement context builders for each entity type
- [ ] Generate `dbt_project.yml` and `packages.yml`
- [ ] Generate single `sources.yml` file with all sources
- [ ] Generate stage models (SQL + YAML)

### Phase 3: Raw Vault
- [ ] Generate hub models (standard + reference) with entity-specific YAML
- [ ] Generate link models (standard + non-historized) with entity-specific YAML
- [ ] Generate satellite models (all 4 types + effectivity + record tracking)
- [ ] Implement satellite _v0/_v1 dual-model generation
- [ ] Implement group-based folder organization (groups at raw_vault level)

### Phase 4: Business Vault & Control
- [ ] Generate PIT models
- [ ] Generate reference table models
- [ ] Generate snapshot control table models
- [ ] Generate snapshot control logic models

### Phase 5: Validation & Polish
- [ ] Implement pre-generation validators
- [ ] Implement `GenerationReport`
- [ ] Add error handling and recovery
- [ ] CLI integration

### Phase 6: Testing & Documentation
- [ ] Unit tests for template rendering
- [ ] Integration tests with sample data
- [ ] Documentation and examples

---

## 12. Dependencies

### 12.1 Python Packages

```
jinja2>=3.1.0      # Template engine
pyyaml>=6.0        # YAML generation
```

### 12.2 dbt Packages (in generated project)

```yaml
# packages.yml
packages:
  - package: datavault4dbt/datavault4dbt
    version: [">=0.9.0", "<1.0.0"]
```

---

## 13. Acceptance Criteria

The implementation is complete when:

1. ✅ All entity types generate as SQL models with entity-type-specific YAML schemas
2. ✅ Satellites generate dual models (_v0 core + _v1 load-end-date view)
3. ✅ Single `sources.yml` contains all source system definitions
4. ✅ Raw vault groups entities by `group` field (not by entity type)
5. ✅ Snapshot control tables and logic are generated in `models/control/`
6. ✅ Templates are customizable via Django Admin with selectable variants
7. ✅ Pre-generation validation catches common errors
8. ✅ Generation report summarizes what was created
9. ✅ CLI command works end-to-end
10. ✅ Generated project can be run with `dbt compile` without errors
