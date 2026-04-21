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

The MCP server exposes nine tools grouped by workflow stage.

### Workspace & Project

| Tool | Description |
|------|-------------|
| `workspace_status` | Health check: DB connection, project count, workspace path |
| `project_list` | List all projects with name, description, and schema configuration |
| `project_create` | Create a new project by importing source metadata (`.xlsx`, `.db`, or `.json`) |

### Model Inspection

| Tool | Description |
|------|-------------|
| `list_entities` | List hubs, links, satellites, and PITs in a project |

### Model Building

| Tool | Description |
|------|-------------|
| `propose_model_from_source` | Return the schema template and source table summaries so Claude can reason about and propose a Data Vault model |
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
3. list_entities             ← inspect existing model (if any)
4. propose_model_from_source ← Claude analyses source tables, proposes model
5.  ↳ user reviews and refines iteratively (no DB writes yet)
6. commit_model              ← write approved proposal to database
7. validate_model            ← check for errors / warnings
8. generate_dbt              ← produce the dbt project
```

Steps 4–5 can loop as many times as needed before committing.

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

### propose_model_from_source

This tool does **not** write anything. It returns the empty proposal schema and a summary of the source tables so that Claude can reason about the Data Vault model and fill in the proposal. The filled-in proposal is then passed to `commit_model`.

**Input:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source_tables` | array | yes | Source table descriptions (see below) |

Each `source_table` entry:

```json
{
  "name": "customers",
  "columns": [
    {"name": "id", "type": "integer", "is_pk": true},
    {"name": "name", "type": "varchar"},
    {"name": "email", "type": "varchar"},
    {"name": "country_code", "type": "char(2)"},
    {"name": "created_at", "type": "timestamp"}
  ],
  "record_source": "CRM",
  "load_date_column": "created_at"
}
```

**Output:** Returns the `schema_template` (the shape of the proposal Claude must fill in) and the original `source_tables` for reference:

```json
{
  "instructions": "Analyse the source_tables below and produce a Data Vault model...",
  "schema_template": {
    "hubs": [{"name": "HUB_<ENTITY>", "business_keys": ["<natural_key_column>"], ...}],
    "links": [...],
    "satellites": [...],
    "reasoning": "<explain your modeling decisions here>",
    "reference_candidates": ["<column_names_that_look_like_lookup_data>"]
  },
  "source_tables": [...]
}
```

Claude fills in the template and calls `commit_model` with the completed proposal.

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
> "Use workspace_status to confirm TurboVault is running."

**Step 2 — Describe your sources:**
> "I have two source tables from our CRM system: `customers` (id, name, email, country_code, created_at) and `orders` (order_id, customer_id, order_date, total_amount, status). Use propose_model_from_source to design a Data Vault model."

Claude calls `propose_model_from_source` with the table descriptions and returns a proposal:

```json
{
  "hubs": [
    {"name": "HUB_CUSTOMER", "business_keys": ["id"], "hashkey": "hk_customer"},
    {"name": "HUB_ORDER", "business_keys": ["order_id"], "hashkey": "hk_order"}
  ],
  "links": [
    {"name": "LNK_ORDER_CUSTOMER", "hubs": ["HUB_ORDER", "HUB_CUSTOMER"], "hashkey": "hk_order_customer"}
  ],
  "satellites": [
    {"name": "SAT_CUSTOMER_DETAILS", "parent_hub": "HUB_CUSTOMER", "columns": ["name", "email", "created_at"]},
    {"name": "SAT_ORDER_DETAILS", "parent_hub": "HUB_ORDER", "columns": ["order_date", "total_amount", "status"]}
  ],
  "reference_candidates": ["country_code", "status"],
  "reasoning": "id and order_id are natural business keys. The customer→order relationship is a standard link. country_code and status look like lookup data."
}
```

**Step 3 — Refine (optional):**
> "Add a reference hub for country codes."

Claude updates the proposal and calls `commit_model` once approved.

**Step 4 — Validate and generate:**
> "Validate the model, then generate the dbt project."

Claude calls `validate_model` (check for errors), then `generate_dbt`.

## Security

By default, the MCP endpoint has no authentication (`DJANGO_MCP_AUTHENTICATION_CLASSES = []`). This is appropriate for local development on a loopback address.

If you expose `turbovault serve` to a network (e.g. `--host 0.0.0.0`), restrict access at the network level (firewall, VPN) or configure Django REST Framework authentication in `turbovault/settings.py`:

```python
DJANGO_MCP_AUTHENTICATION_CLASSES = ["rest_framework.authentication.BasicAuthentication"]
DJANGO_MCP_PERMISSION_CLASSES = ["rest_framework.permissions.IsAuthenticated"]
```
