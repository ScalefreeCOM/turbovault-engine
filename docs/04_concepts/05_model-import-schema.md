---
sidebar_position: 5
sidebar_label: Model Import Schema
title: Model Import Schema
---

# Model Import Schema

The Model Import Schema is a lightweight JSON format that describes a Data Vault model as a flat list of hubs, links, and satellites. It is consumed by:

- [`turbovault model import-json`](../02_getting-started/01_cli-reference.md#turbovault-model-import-json) — bulk-import from the command line
- The MCP server's `commit_model` tool — AI-assisted model creation via Claude

This format is intentionally minimal: it captures entity names and relationships, but does **not** require source column mappings or staging metadata. Column-level detail can be added later in the Django Admin interface.

## Schema Reference

### Top-Level Structure

```json
{
  "hubs": [ ... ],
  "links": [ ... ],
  "satellites": [ ... ],
  "reasoning": "optional free-text explanation",
  "reference_candidates": ["column_a", "column_b"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `hubs` | array | Hub definitions (see below) |
| `links` | array | Link definitions (see below) |
| `satellites` | array | Satellite definitions (see below) |
| `reasoning` | string | Free-text rationale (informational, ignored by importer) |
| `reference_candidates` | array of strings | Column names identified as lookup/reference data (informational only) |

### Hub

```json
{
  "name": "HUB_CUSTOMER",
  "business_keys": ["CUSTOMER_ID"],
  "hashkey": "hk_customer",
  "hub_type": "standard",
  "source_table": "raw_customers",
  "group": "crm"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Physical hub name, e.g. `HUB_CUSTOMER` |
| `business_keys` | array of strings | no | Business key column names |
| `hashkey` | string | no | Hashkey column name (can be set later in Admin) |
| `hub_type` | string | no | `"standard"` (default) or `"reference"` |
| `source_table` | string | no | Source table name (informational) |
| `group` | string | no | Group for subfolder organisation |

### Link

```json
{
  "name": "LNK_ORDER_CUSTOMER",
  "hubs": ["HUB_ORDER", "HUB_CUSTOMER"],
  "hashkey": "hk_order_customer",
  "link_type": "standard",
  "group": "sales"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Physical link name, e.g. `LNK_ORDER_CUSTOMER` |
| `hubs` | array of strings | no | Physical names of the referenced hubs |
| `hashkey` | string | no | Hashkey column name |
| `link_type` | string | no | `"standard"` (default) or `"non_historized"` |
| `group` | string | no | Group for subfolder organisation |

Hub references are resolved by name within the project. If a referenced hub does not exist, the reference is skipped with a warning — the link itself is still created.

### Satellite

```json
{
  "name": "SAT_CUSTOMER_DETAILS",
  "satellite_type": "standard",
  "parent_hub": "HUB_CUSTOMER",
  "columns": ["FIRST_NAME", "LAST_NAME", "EMAIL"],
  "source_table": "raw_customers",
  "group": "crm"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Physical satellite name, e.g. `SAT_CUSTOMER_DETAILS` |
| `satellite_type` | string | no | `"standard"` (default), `"non_historized"`, `"multi_active"`, or `"reference"` |
| `parent_hub` | string | no* | Parent hub physical name (XOR with `parent_link`) |
| `parent_link` | string | no* | Parent link physical name (XOR with `parent_hub`) |
| `columns` | array of strings | no | Column names (informational — staging mappings require source metadata) |
| `source_table` | string | no | Source table name (informational) |
| `group` | string | no | Group for subfolder organisation |

*Exactly one of `parent_hub` or `parent_link` must be provided. The schema validator rejects satellites that have both or neither.

## Full Example

```json
{
  "hubs": [
    {
      "name": "HUB_CUSTOMER",
      "business_keys": ["CUSTOMER_ID"],
      "hashkey": "hk_customer",
      "hub_type": "standard"
    },
    {
      "name": "HUB_ORDER",
      "business_keys": ["ORDER_ID"],
      "hashkey": "hk_order",
      "hub_type": "standard"
    },
    {
      "name": "HUB_PRODUCT",
      "business_keys": ["PRODUCT_CODE"],
      "hashkey": "hk_product",
      "hub_type": "reference"
    }
  ],
  "links": [
    {
      "name": "LNK_ORDER_CUSTOMER",
      "hubs": ["HUB_ORDER", "HUB_CUSTOMER"],
      "hashkey": "hk_order_customer",
      "link_type": "standard"
    },
    {
      "name": "LNK_ORDER_PRODUCT",
      "hubs": ["HUB_ORDER", "HUB_PRODUCT"],
      "hashkey": "hk_order_product",
      "link_type": "standard"
    }
  ],
  "satellites": [
    {
      "name": "SAT_CUSTOMER_DETAILS",
      "satellite_type": "standard",
      "parent_hub": "HUB_CUSTOMER",
      "columns": ["FIRST_NAME", "LAST_NAME", "EMAIL", "PHONE"]
    },
    {
      "name": "SAT_ORDER_DETAILS",
      "satellite_type": "standard",
      "parent_hub": "HUB_ORDER",
      "columns": ["ORDER_DATE", "TOTAL_AMOUNT", "STATUS"]
    },
    {
      "name": "SAT_ORDER_CUSTOMER_EFFECTIVITY",
      "satellite_type": "effectivity",
      "parent_link": "LNK_ORDER_CUSTOMER"
    }
  ],
  "reasoning": "CUSTOMER and ORDER are core business entities. PRODUCT is reference data. The ORDER→CUSTOMER relationship is modelled as a link with an effectivity satellite.",
  "reference_candidates": ["PRODUCT_CODE", "STATUS"]
}
```

## Import Behaviour

- **Idempotent**: entities with the same physical name in the same project are silently skipped. Running the same import twice has no side effect.
- **Partial imports**: entities imported successfully are committed even if other entities in the same file encounter errors. Each entity is processed independently inside a single database transaction.
- **No source column mappings**: the import creates structural metadata (hubs, links, satellites). Column-level staging mappings (hashkeys, hashdiffs, source columns) must be configured afterwards in the Django Admin.

## Differences from the JSON Export Format

The Model Import Schema is **not** the same as the JSON export produced by `turbovault generate --type json`.

| | Model Import Schema | JSON Export (`ProjectExport`) |
|-|--------------------|-----------------------------|
| Purpose | Lightweight model proposal | Full round-trip backup/restore |
| Source column mappings | No | Yes |
| Stage definitions | No | Yes |
| Snapshot controls | No | Yes |
| PITs | No | Yes |
| Used by | `model import-json`, MCP `commit_model` | `project init --source model.json` |

Use the JSON export format if you need to migrate or restore a complete project. Use the Model Import Schema for incremental model additions or AI-assisted modeling.
