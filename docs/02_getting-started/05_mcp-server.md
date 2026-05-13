---
sidebar_position: 6
sidebar_label: MCP Server (AI Integration)
title: MCP Server — AI-Assisted Data Vault Modeling
---

# MCP Server — AI-Assisted Data Vault Modeling

TurboVault Engine ships with a built-in [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server. When `turbovault serve` is running, an AI assistant such as Claude Code or Claude Desktop can connect to it and model your Data Vault directly from a conversation — inspecting existing projects, proposing hubs/links/satellites from source table descriptions, committing approved proposals, validating, and generating the dbt project.

## Architecture

The MCP server is embedded in the Django process — no separate service or subprocess is needed.

```
Claude Code / Claude Desktop
          │  HTTP (Streamable MCP)
          ▼
  http://localhost:8000/mcp
          │
   Django (turbovault serve)
          │  ORM (direct DB access)
          ▼
   TurboVault SQLite / PostgreSQL
```

The server is provided by [`django-mcp-server`](https://github.com/gts360/django-mcp-server) and is registered as a Django app. All MCP tools are defined in `backend/engine/mcp.py` and auto-discovered on startup.

## Starting the Server

```bash
# In your TurboVault workspace directory
turbovault serve
```

On startup, the banner shows all three access points:

```
╭────────────── Server Starting ──────────────╮
│  Server: http://127.0.0.1:8000/             │
│  Admin:  http://127.0.0.1:8000/admin/       │
│  MCP:    http://127.0.0.1:8000/mcp          │
╰─────────────────────────────────────────────╯
```

The MCP endpoint is available at `http://127.0.0.1:8000/mcp` as long as the server is running.

## Connecting Claude Code

Add the server to your Claude Code MCP configuration:

```bash
claude mcp add --transport http turbovault http://localhost:8000/mcp
```

Verify the connection:

```bash
claude mcp list
# turbovault    http://localhost:8000/mcp    (connected)
```

Alternatively, add it manually to `~/.claude/claude_desktop_config.json` (or the equivalent Claude settings file):

```json
{
  "mcpServers": {
    "turbovault": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

## Connecting Claude Desktop

Open **Claude Desktop → Settings → Developer → MCP Servers** and add:

```json
{
  "turbovault": {
    "type": "http",
    "url": "http://localhost:8000/mcp"
  }
}
```

> **Note:** Claude Desktop must be able to reach the TurboVault server. The default `127.0.0.1:8000` works if both run on the same machine. For remote access, bind to `0.0.0.0` with `turbovault serve --host 0.0.0.0` and adjust the URL accordingly.

## Available Tools

The MCP server exposes ten tools grouped by workflow stage.

### Workspace & Project

| Tool | Description |
|------|-------------|
| `workspace_status` | Health check: DB connection, project count, workspace path |
| `project_list` | List all projects with name, description, and schema configuration |
| `project_create` | Create a new project by importing source metadata (`.xlsx`, `.db`, or `.json`) |

### Source Metadata

| Tool | Description |
|------|-------------|
| `list_sources` | List source systems, tables, and columns in a project |
| `create_source_metadata` | Idempotently create a source system, tables, and columns |

### Model Inspection

| Tool | Description |
|------|-------------|
| `list_entities` | List hubs, links, satellites, and PITs in a project |

### Model Building

| Tool | Description |
|------|-------------|
| `commit_model` | Write an approved model proposal to the project database |

### Validation & Generation

| Tool | Description |
|------|-------------|
| `validate_model` | Run validation rules and return errors and warnings |
| `export_model_json` | Export the current model as a JSON object (full `ProjectExport` format) |
| `generate_dbt` | Generate a complete dbt project from the model |

## Typical Conversation Flow

```
1. workspace_status          ← verify workspace is healthy
2. project_list              ← find the target project
3. list_entities             ← inspect existing model (hubs available for integration)
4. list_sources              ← inspect existing source metadata
5. create_source_metadata    ← register source system, tables, and columns
6. commit_model              ← write approved proposal to database
7. validate_model            ← check for errors / warnings
8. generate_dbt              ← produce the dbt project
```

Steps 5–6 can be called multiple times as you add more sources or refine the model.

## Tool Reference

### workspace_status

Returns workspace health information. Call this first to confirm the server is connected to the right database.

**Input:** none

**Output:**
```json
{
  "status": "ok",
  "workspace": "/path/to/my-workspace",
  "database_engine": "sqlite3",
  "project_count": 2
}
```

---

### project_list

Returns a list of all projects.

**Input:** none

**Output:**
```json
[
  {
    "name": "my_project",
    "description": "Sales Data Vault",
    "stage_schema": "stage",
    "rdv_schema": "rdv",
    "bdv_schema": "bdv"
  }
]
```

---

### project_create

Create a new project from a source file. The `source_path` must be an absolute path on the server machine.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | yes | Project name (must be unique) |
| `source_path` | string | yes | Absolute path to `.xlsx`, `.db`, or `.json` export |
| `description` | string | no | Optional project description |
| `stage_schema` | string | no | Staging schema name (default: `stage`) |
| `rdv_schema` | string | no | RDV schema name (default: `rdv`) |
| `bdv_schema` | string | no | BDV schema name (default: `bdv`) |

**Output:**
```json
{
  "status": "ok",
  "project": "my_project",
  "hubs": 12,
  "links": 7,
  "satellites": 24
}
```

---

### list_entities

List Data Vault entities in a project.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_name` | string | yes | Project name |
| `entity_type` | string | no | `"hubs"`, `"links"`, `"satellites"`, `"pits"`, or `"all"` (default: `"all"`) |

**Output:**
```json
{
  "hubs": [
    {"name": "HUB_CUSTOMER", "type": "standard", "hashkey": "hk_customer", "business_keys": ["CUSTOMER_ID"]}
  ],
  "links": [...],
  "satellites": [...],
  "pits": [...]
}
```

---

### list_sources

List source systems, tables, and columns in a project. Use this to understand what source metadata already exists before deciding what to register.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_name` | string | yes | Project name |

**Output:**
```json
{
  "source_systems": [
    {
      "name": "CRM",
      "schema_name": "public",
      "database_name": null,
      "tables": [
        {
          "physical_name": "customers",
          "record_source": "CRM.customers",
          "load_date": "LOAD_DATE",
          "columns": [
            {"name": "id", "datatype": "INTEGER"},
            {"name": "name", "datatype": "VARCHAR"}
          ]
        }
      ]
    }
  ]
}
```

---

### create_source_metadata

Register a source system, its tables, and their columns. Existing records are silently skipped (idempotent) — safe to call again if a run is interrupted or new columns are added later.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_name` | string | yes | Target project name |
| `source_system_name` | string | yes | Name for the source system (e.g. `CRM`) |
| `schema_name` | string | yes | Database schema (e.g. `public`, `dbo`) |
| `source_tables` | array | yes | Table descriptions (see below) |
| `database_name` | string | no | Optional database name |

Each `source_table` entry:

```json
{
  "name": "customers",
  "columns": [
    {"name": "id", "type": "INTEGER"},
    {"name": "name", "type": "VARCHAR"},
    {"name": "email", "type": "VARCHAR"},
    {"name": "country_code", "type": "CHAR(2)"},
    {"name": "created_at", "type": "TIMESTAMP"}
  ],
  "record_source": "CRM.customers",
  "load_date": "created_at"
}
```

**Output:**
```json
{
  "status": "ok",
  "source_system": "CRM",
  "source_system_created": true,
  "tables_created": 2,
  "tables_skipped": 0,
  "columns_created": 9,
  "columns_skipped": 0
}
```

---

### commit_model

Write an approved model proposal to the project database. The proposal must match the [Model Import Schema](../04_concepts/05_model-import-schema.md) format.

Existing entities with the same name are silently skipped (idempotent).

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_name` | string | yes | Target project name |
| `proposal` | object | yes | Model proposal matching the Model Import Schema |

**Output:**
```json
{
  "status": "ok",
  "hubs_created": 3,
  "links_created": 2,
  "satellites_created": 5,
  "skipped": [],
  "errors": []
}
```

---

### validate_model

Run Data Vault validation rules against the project model.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_name` | string | yes | Project name |

**Output:**
```json
{
  "valid": true,
  "errors": [],
  "warnings": [
    {"code": "HUB_002", "entity_type": "hub", "entity": "HUB_CUSTOMER", "message": "Hub has no business keys"}
  ]
}
```

See [Validation Rules](../04_concepts/03_validation-rules.md) for the full list of error codes.

---

### export_model_json

Export the current model as a full `ProjectExport` JSON object. This is the same format used by `turbovault generate --type json` and can be re-imported via `turbovault project init --source`.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_name` | string | yes | Project name |

**Output:** A JSON object containing the complete project export (hubs, links, satellites, stages, PITs, snapshot controls, etc.).

---

### generate_dbt

Generate a complete dbt project from the Data Vault model.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_name` | string | yes | Project name |
| `output_path` | string | no | Absolute output directory path (uses project default if omitted) |
| `mode` | string | no | `"strict"` (stop on error) or `"lenient"` (skip invalid entities). Default: `"strict"` |
| `dry_run` | boolean | no | If `true`, validate only — no files written. Default: `false` |

**Output:**
```json
{
  "status": "ok",
  "output_path": "/path/to/workspace/projects/my_project/exports/dbt_project",
  "total_files": 47,
  "hubs_generated": 3,
  "links_generated": 2,
  "satellites_generated": 8,
  "pits_generated": 1,
  "errors": []
}
```

## Example: Model a New Source from Scratch

The following is a complete example of an AI-assisted modeling session.

**Step 1 — Check workspace:**
> "Use workspace_status to confirm TurboVault is running, then show me the projects."

Claude calls `workspace_status` and `project_list`.

**Step 2 — Inspect existing model:**
> "Show me the existing hubs in project 'sales_dv' and any source tables already registered."

Claude calls `list_entities` and `list_sources` to understand what already exists — relevant for integrating a new source into an existing hub.

**Step 3 — Register source metadata:**
> "I have two source tables from our CRM system: `customers` (id, name, email, country_code, created_at) and `orders` (order_id, customer_id, order_date, total_amount, status). Register them."

Claude calls `create_source_metadata`:

```json
{
  "project_name": "sales_dv",
  "source_system_name": "CRM",
  "schema_name": "public",
  "source_tables": [
    {
      "name": "customers",
      "columns": [
        {"name": "id", "type": "INTEGER"},
        {"name": "name", "type": "VARCHAR"},
        {"name": "email", "type": "VARCHAR"},
        {"name": "country_code", "type": "CHAR(2)"},
        {"name": "created_at", "type": "TIMESTAMP"}
      ]
    },
    {
      "name": "orders",
      "columns": [
        {"name": "order_id", "type": "INTEGER"},
        {"name": "customer_id", "type": "INTEGER"},
        {"name": "order_date", "type": "DATE"},
        {"name": "total_amount", "type": "DECIMAL"},
        {"name": "status", "type": "VARCHAR"}
      ]
    }
  ]
}
```

**Step 4 — Commit the model:**
> "Now commit a Data Vault model for these sources."

Claude calls `commit_model` with a proposal:

```json
{
  "project_name": "sales_dv",
  "proposal": {
    "hubs": [
      {"name": "HUB_CUSTOMER", "business_keys": ["id"], "hashkey": "hk_customer", "source_table": "customers"},
      {"name": "HUB_ORDER", "business_keys": ["order_id"], "hashkey": "hk_order", "source_table": "orders"}
    ],
    "links": [
      {"name": "LNK_ORDER_CUSTOMER", "hubs": ["HUB_ORDER", "HUB_CUSTOMER"], "hashkey": "hk_order_customer"}
    ],
    "satellites": [
      {"name": "SAT_CUSTOMER_DETAILS", "parent_hub": "HUB_CUSTOMER", "columns": ["name", "email", "created_at"], "source_table": "customers"},
      {"name": "SAT_ORDER_DETAILS", "parent_hub": "HUB_ORDER", "columns": ["order_date", "total_amount", "status"], "source_table": "orders"}
    ]
  }
}
```

Because `create_source_metadata` was called first, column mappings (`HubSourceMapping`, `SatelliteColumn`) are created automatically.

**Step 5 — Validate and generate:**
> "Validate the model, then generate the dbt project."

Claude calls `validate_model` (check for errors), then `generate_dbt`.

## Security

By default, the MCP endpoint has no authentication (`DJANGO_MCP_AUTHENTICATION_CLASSES = []`). This is appropriate for local development on a loopback address.

If you expose `turbovault serve` to a network (e.g. `--host 0.0.0.0`), restrict access at the network level (firewall, VPN) or configure Django REST Framework authentication in `turbovault/settings.py`:

```python
DJANGO_MCP_AUTHENTICATION_CLASSES = ["rest_framework.authentication.BasicAuthentication"]
DJANGO_MCP_PERMISSION_CLASSES = ["rest_framework.permissions.IsAuthenticated"]
```
