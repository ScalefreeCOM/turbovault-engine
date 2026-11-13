---
sidebar_position: 11
sidebar_label: Validation Rules
title: Validation Rules
---

# Validation Rules

TurboVault Engine validates your Data Vault model at **two different stages**:

1. **Import time** — when a metadata source (Excel, SQLite, JSON) is imported into a project, the [Import Pipeline](06_import-pipeline.md) runs schema, row-level, and cross-entity checks. Problems show up as structured `Issue` objects with stable codes like `schema.missing_column` and `entity.missing_parent` and exact source-file locations.
2. **Generation time** — when you run `turbovault generate`, the [Generation Pipeline](07_generation-pipeline.md) runs the model-level invariants documented on this page. Problems become `Issue` objects with stable codes like `validate.hub.missing_hashkey` and an entity-scoped location.

If your error code starts with `schema.`, `row.`, `source.`, or `entity.`, it came from the import pipeline — see [Import Pipeline → Issue codes](06_import-pipeline.md#issue-codes).

If your error code starts with `validate.`, it came from the generation pipeline — see [Generation Pipeline → Issue code taxonomy](07_generation-pipeline.md#issue-code-taxonomy) for the dot-separated codes. The legacy alphanumeric codes (`HUB_001`, `LNK_002`, …) listed below are still emitted in `Issue.location.field` for backwards-compatible dashboards — read on for what each one means and how to fix it.

> **See also:** [CLI Reference — turbovault generate](../02_getting-started/01_cli-reference.md#turbovault-generate) for the `--mode strict` / `--mode lenient` / `--skip-validation` flags, and [Generation Pipeline](07_generation-pipeline.md) for the surrounding pipeline behaviour.

---

## Running Validation

Validation runs automatically as part of `turbovault generate`. You can control its behavior with the `--mode` flag:

```bash
# Default: stop on first error
turbovault generate --project my_project --mode strict

# Skip invalid entities and continue with valid ones
turbovault generate --project my_project --mode lenient

# Skip validation entirely (not recommended for production)
turbovault generate --project my_project --skip-validation
```

---

## Validation Error Codes

### Hub Rules

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `HUB_001` | Standard Hub | Must have a hashkey name set | Set `hub_hashkey_name` in Django Admin → Hubs |
| `HUB_002` | Hub | Must have at least 1 business key column | Add a `HubColumn` of type `business_key` in Django Admin → Hub Columns |

---

### Link Rules

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `LNK_001` | Link | Must have a hashkey name set | Set `link_hashkey_name` in Django Admin → Links |
| `LNK_002` | Link | Must reference at least 2 hubs | Add Hub References in Django Admin → Links (minimum 2 inline rows) |

---

### Satellite Rules

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `SAT_001` | Satellite | Must have a parent entity (hub or link) | Set either `parent_hub` or `parent_link` in Django Admin → Satellites |
| `STG_005` | Stage | Satellites of one stage may share a hash diff name only if they hash the same columns (`validate.stage.duplicate_hashdiff`) | Give one satellite its own `hashdiff_name` |
| `REF_001` | Reference table | Each satellite it reads must get a v1 view (warning, `validate.reference_table.satellite_without_v1`) | Turn the satellite's v1 view on (`create_v1_view`, or the project's `generate_satellite_v1_views`) |

---

### Model Name Rules

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `MDL_001` | Any model | No two models of the project share a name, compared case-insensitively; pre-stages count (`validate.model.duplicate_name`) | Rename one: its model output's name, or the entity |
| `MDL_002` | Any model | A model name must name a file inside the project: no slashes or `..` (`validate.model.invalid_name`) | Rename the model or the entity |
| `MDL_003` | Any model | A stored folder must be relative to the dbt project and stay inside it (`validate.model.invalid_folder`) | Use a folder such as `models/raw_vault/hubs` |

---

### Generation Output Rules

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `YML_001` | Model | SQL model was generated but YAML schema is missing | Check that the corresponding YAML template exists in Django Admin → Model Templates |
| `TPL_003` | Any model | The template predates something the model needs (warning, `render.template_outdated`): a stage template that doesn't read a pre-stage model or prejoin one; a template that doesn't write the model's stored `config()` settings, its stored tags, or the stored names of the models it references (e.g. a v1 view's v0 table) | Update the template; `python manage.py populate_templates --overwrite` refreshes the workspace's copies (and replaces their customizations) |
| `PST_001` | Pre-stage | Each dbt generation reminds that the pre-stage's model belongs to the dbt project: TurboVault doesn't generate it, and its stage reads it with `ref()` (warning, `render.prestage.maintained_in_dbt`) | Nothing to fix: generate into the dbt project that contains the model |

---

## Working with Validation Errors

### Reading Error Output

When validation fails in strict mode, you will see output like:

```
✗ Validation failed:
  [HUB_001] Hub 'hub_customer': missing hashkey name
  [LNK_002] Link 'link_customer_order': only 1 hub referenced (minimum is 2)
```

Each error includes:
- The error **code** for quick lookup
- The **entity name** that failed
- A **short description** of what is wrong

### Fix Cycle

1. Read the error message — note the entity name and code
2. Open Django Admin (`turbovault serve`)
3. Navigate to the entity and fix the issue
4. Re-run `turbovault generate`

### Using Lenient Mode During Development

When iterating on a partial model, use `--mode lenient` to generate output for entities that are valid and skip those that aren't:

```bash
turbovault generate --project my_project --mode lenient
```

This is useful when you are building your model incrementally and want to see partial output before everything is complete. **Switch back to strict mode before deploying to production.**
