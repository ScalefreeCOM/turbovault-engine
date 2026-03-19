---
sidebar_position: 11
sidebar_label: Validation Rules
title: Validation Rules
---

# Validation Rules

TurboVault Engine validates your Data Vault model before generating any output. This page lists all validation rules, their error codes, what triggers them, and how to fix them.

> **See also:** [CLI Reference — Validation Modes](../02_getting-started/01_cli-reference.md#validation-modes) for how to control validation behavior during generation.

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

---

### Generation Output Rules

| Code | Entity | Rule | How to Fix |
|------|--------|------|------------|
| `YML_001` | Model | SQL model was generated but YAML schema is missing | Check that the corresponding YAML template exists in Django Admin → Model Templates |

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
