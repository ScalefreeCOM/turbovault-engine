# dbt Project Generation

TurboVault Engine can generate complete, ready-to-use dbt projects from your Data Vault model using the `turbovault generate` command.

## Quick Start

```bash
# Generate dbt project from your Data Vault model
turbovault generate --project "My Project"

# Generate to a specific directory
turbovault generate --project "My Project" --output ./my_dbt_project

# Generate with ZIP archive
turbovault generate --project "My Project" --zip
```

## CLI Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--project` | `-p` | Project name (required or interactive) | Interactive |
| `--output` | `-o` | Output directory path | `./output/{project_name}` |
| `--mode` | `-m` | Validation mode: `strict` or `lenient` | `strict` |
| `--zip` | `-z` | Create ZIP archive after generation | `false` |
| `--skip-validation` | | Skip pre-generation validation | `false` |
| `--no-v1-satellites` | | Skip generating satellite _v1 views | `false` |

## Generated Project Structure

```
output/my_project/
├── dbt_project.yml         # dbt project configuration
├── packages.yml            # dbt packages (datavault4dbt)
├── models/
│   ├── staging/
│   │   ├── sources.yml     # All source definitions
│   │   ├── {source_system}/
│   │   │   ├── stg__*.sql      # Stage models
│   │   │   └── stg__*.yml      # Stage schemas
│   ├── raw_vault/
│   │   ├── {group}/            # Grouped by domain
│   │   │   ├── hub_*.sql/yml   # Hub models
│   │   │   ├── link_*.sql/yml  # Link models
│   │   │   ├── sat_*_v0.sql/yml  # Satellite v0 models
│   │   │   └── sat_*_v1.sql/yml  # Satellite v1 views
│   ├── business_vault/
│   │   ├── pits/
│   │   │   └── pit_*.sql/yml   # Point-in-Time models
│   │   └── reference_tables/
│   │       └── ref_*.sql/yml   # Reference table models
│   └── control/
│       ├── control_snap_v0.sql/yml  # Snapshot control table
│       └── control_snap_v1.sql/yml  # Snapshot control logic
├── macros/
├── tests/
├── seeds/
├── analyses/
└── snapshots/
```

## Validation

Pre-generation validation catches common errors before generating files:

### Errors (block generation in strict mode)
| Entity | Rule | Code |
|--------|------|------|
| Hub (standard) | Must have hashkey | HUB_001 |
| Hub | Must have ≥1 business key | HUB_002 |
| Link | Must have hashkey | LNK_001 |
| Link | Must reference ≥2 hubs | LNK_002 |
| Satellite | Must have parent entity | SAT_001 |
| Satellite | Must have stage assigned | SAT_002 |
| Stage | Must have source_table | STG_001 |
| Source | Must have schema_name | SRC_001 |

### Warnings (logged but don't block)
| Entity | Rule | Code |
|--------|------|------|
| Hub | No source tables defined | HUB_003 |
| Satellite | No payload columns | SAT_003 |
| Model | SQL generated but YAML missing | YML_001 |

### Validation Modes

- **Strict mode** (default): Stop on first error
- **Lenient mode**: Skip invalid entities, continue with valid ones

```bash
# Use lenient mode to generate what's valid
turbovault generate --project "My Project" --mode lenient
```

## Satellite v0 and v1 Models

The generator creates two models for each satellite:

1. **v0 model** (`sat_*_v0.sql`): Core incremental satellite using `datavault4dbt.sat_v0()`
2. **v1 model** (`sat_*_v1.sql`): View with load_end_date using `datavault4dbt.sat_v1()`

To skip v1 generation:

```bash
turbovault generate --project "My Project" --no-v1-satellites
```

## Custom Templates

Templates can be customized via Django Admin:

1. Start the admin server: `turbovault serve`
2. Navigate to **Model Templates**
3. Create custom templates for specific entity types

The generator checks database templates first, then falls back to file-based defaults.

## Using the Generated Project

After generation:

```bash
cd output/my_project

# Install dbt packages
dbt deps

# Compile to check for errors
dbt compile

# Run models
dbt run
```

## Example Output

```
[1/5] Building export for project: pizza_delivery_empire
[2/5] Validating export data...
⚠ Found 1 warning(s):
  ⚠ [HUB_003] hub:hub_country - Hub has no source tables defined
[3/5] Configuring generator...
[4/5] Generating dbt project to: ./output/pizza_delivery_empire
[5/5] Generation complete!

╭─────────────── Generation Summary ───────────────╮
│ ✓ Success                                        │
│                                                  │
│ Output path: C:\...\output\pizza_delivery_empire │
│ Total files: 68                                  │
│                                                  │
│ Stages: 7                                        │
│ Hubs: 5                                          │
│ Links: 3                                         │
│ Satellites (v0): 8                               │
│ Satellite views (v1): 7                          │
│ PITs: 1                                          │
│ Reference tables: 1                              │
│ Snapshot controls: 1                             │
╰──────────────────────────────────────────────────╯

✓ dbt project generated at: C:\...\output\pizza_delivery_empire
```
