---
sidebar_position: 7
sidebar_label: Generation Pipeline
title: Generation Pipeline
---

# Generation Pipeline

The Generation Pipeline is the engine subsystem that turns the **stored
metadata** of a project into one of three artifacts:

- a complete **dbt project** (a tree of SQL models and YAML schemas),
- a **JSON export** of the full Data Vault model, or
- a **DBML diagram** for entity-relationship visualisation.

It is the single code path used by:

- The `turbovault generate` CLI command.
- The Turbovault Studio backend.
- Direct Python callers via `engine.services.generation.generate()`.

> **See also:** [`turbovault generate` CLI reference](../02_getting-started/01_cli-reference.md#turbovault-generate) and [`turbovault generation-history`](../02_getting-started/01_cli-reference.md#turbovault-generation-history). The shape of the pipeline mirrors the [Import Pipeline](06_import-pipeline.md); reading that page first is the fastest way to understand this one.

---

## What the pipeline does

```
   Project (Django ORM)
        │
        ▼
   [1 Build]  ──▶  [2 Validate]  ──▶  [3 Plan]
        │                                  │
        ▼                                  ▼
   [6 Report]  ◀── [5 Write]  ◀── [4 Render]
```

Each stage produces typed output for the next, records its duration in
`timings_ms`, and can emit `Issue`s into the final report.

| Stage | What it does |
|-------|--------------|
| **Build** | Reads the Django ORM into a target-agnostic `ProjectExport` Pydantic model (via the existing `ModelBuilder`). Failure here is fatal — nothing downstream can do anything without an export. |
| **Validate** | Runs the model-level invariants from the [Validation Rules](03_validation-rules.md) catalog. Every violation becomes an `Issue` with `stage="validate"`, a stable `validate.*` code, and an `entity` reference. Skipped if `options.skip_validation=True`. |
| **Plan** | Walks the `ProjectExport`, applies the [entity selection filter](#selective-generation), and produces a `GenerationPlan` — per-entity-type counts of artifacts the pipeline will emit. |
| **Render** | Produces `GeneratedArtifact` objects **in memory**. dbt rendering wraps the existing `DbtProjectGenerator`; JSON/DBML rendering wraps the existing exporters. Render-time problems (template not found, Jinja error) become `render.*` issues. |
| **Write** | Persists each rendered artifact to disk under the resolved `output_path`. Skipped in dry-run mode. Optional ZIP archive for dbt. |
| **Report** | Persists a `GenerationRun` audit row and returns a structured `GenerationReport` to the caller. |

The same pipeline runs for all three output types — only the plan,
renderer, and writer specialise per type.

---

## Output types

| `output_type` | Plan emits | Renderer | Writer behaviour |
|---------------|------------|----------|------------------|
| `dbt` | One SQL + one YAML file per entity, plus `dbt_project.yml`, `packages.yml`, `sources.yml`. Standard / multi-active satellites also get a `_v1` view when enabled. | `DbtProjectGenerator` (via a temp directory the writer then relocates). | Writes the tree under `output_path/`; optionally creates a sibling `.zip`. |
| `json` | One artifact, regardless of project size. | `JSONExporter`. | Writes a single `.json` file at `output_path`. |
| `dbml` | One artifact, regardless of project size. | `DBMLExporter`. | Writes a single `.dbml` file at `output_path`. |

For all output types the report's `artifacts` list is the single source
of truth for what was produced.

---

## Error strategy

Controls what happens when individual entities fail to render.

| Strategy | Behaviour |
|----------|-----------|
| `best_effort` *(default)* | Skip the failing entity, record a `render.*` issue, keep going. Final status is `partial_success` if anything was written. |
| `fail_fast` | Abort at the first error in any stage; nothing is written. |

CLI flag: `--mode lenient` (maps to `best_effort`) or `--mode strict`
(maps to `fail_fast`).

---

## Dry-run mode

`options.dry_run=True` runs stages 1–4 (build, validate, plan, render),
then **stops before the write stage**. The artifacts are still produced
in memory so render-time problems (template not found, undefined Jinja
variable) are surfaced — something the old `--dry-run` did not catch.

CLI flag: `--dry-run`.

A dry-run still persists a `GenerationRun` row with `is_dry_run=True`,
so you can browse the planned diff via `turbovault generation-history`.

Use a dry-run when:

- You want to preview the impact of generation without touching disk.
- You want a structured machine-readable validation result for CI.
- You want to confirm a destructive scenario before committing to it.

---

## Selective generation

The pipeline supports narrowing the scope of a run via
`options.entity_selection`. This is used by the Studio's metadata editor
to render the SQL/YAML for a **single entity** (e.g. previewing one
hub's generated code inline), and by CLI users who only want to refresh
part of their project.

```python
class EntitySelection(BaseModel):
    include_entity_types: set[str] | None = None   # {"hub", "link"}
    exclude_entity_types: set[str] | None = None   # {"satellite"}
    include_groups: set[str] | None = None         # {"sales"}
    exclude_groups: set[str] | None = None
    only_entities: list[EntityRef] | None = None   # explicit (type, name) allowlist
```

All criteria AND together; within each criterion the values OR together.
`only_entities`, when set, is an explicit allowlist that overrides every
include/exclude rule. An entirely empty selection means "emit everything"
— the default.

### Stage-by-stage semantics

- **Plan** consults the selection and only counts (and later only
  renders) entities that pass the filter.
- **Validate** runs over the full `ProjectExport` (so cross-entity
  invariants are still checked), but only `Issue`s targeting selected
  entities reach the report. Previewing one hub doesn't pollute the
  output with unrelated satellite errors elsewhere in the project.
- **Render** walks only the planned entities. For a single-entity dbt
  selection this typically produces 1–2 artifacts (`sql_model` +
  `yaml_schema`).

### CLI flags

All of these are optional and repeatable:

```bash
turbovault generate --type dbt \
    --include-type hub --include-type link \
    --exclude-type satellite \
    --include-group sales \
    --exclude-group experimental \
    --only hub:hub_customer \
    --only link:lnk_customer_order
```

### In-memory previews

`options.return_content=True` makes the renderer attach the rendered
string to each `GeneratedArtifact.content` field. Combine with
`dry_run=True` and an `only_entities` selection to get a single hub's
generated SQL+YAML as strings without ever touching disk — exactly what
the Studio's metadata editor uses for the preview pane.

```python
report = generate(
    project=project,
    output_type="dbt",
    options=GenerationOptions(
        dry_run=True,
        return_content=True,
        entity_selection=EntitySelection(
            only_entities=[EntityRef(type="hub", name="hub_customer")],
        ),
    ),
)
# report.artifacts[0].content holds the rendered SQL string.
```

---

## Where files land

When `--output` is not supplied, the CLI defaults to the workspace's
conventional `exports/` folder under the project directory:

| Output type | Default path |
|-------------|--------------|
| `dbt` | `<workspace>/projects/<project>/exports/dbt_project/` |
| `json` | `<workspace>/projects/<project>/exports/<project_slug>.json` |
| `dbml` | `<workspace>/projects/<project>/exports/<project_slug>.dbml` |

Explicit `--output`, `--json-output`, or `--dbml-output` always wins.
The fallback `./output/<slug>` is only used when the project has no
`project_directory` configured (e.g. ad-hoc or test projects).

---

## The GenerationReport

Every invocation of the pipeline returns a `GenerationReport`. The same
object is serialized into `engine_report` on the Studio's `Job` model
and into `GenerationRun.report` for CLI history.

Top-level fields:

| Field | Meaning |
|-------|---------|
| `generation_run_id` | UUID of the persisted `GenerationRun`. |
| `project_id` | The target project. |
| `output_type` | `dbt` \| `json` \| `dbml`. |
| `status` | `success` \| `partial_success` \| `validation_failed` \| `failed`. |
| `is_dry_run` | `true` if the write stage was skipped. |
| `options` | The full `GenerationOptions` used. |
| `plan` | Counts of artifacts per entity type. |
| `artifacts` | Every artifact produced. For dry-runs `path` is `None`. |
| `issues` | Every issue produced anywhere in the pipeline. |
| `timings_ms` | Per-stage durations. |

### Status semantics

- **`success`** — no error-severity issues; all artifacts written.
- **`partial_success`** — errors recorded but at least one artifact
  landed. The "lenient" outcome.
- **`validation_failed`** — errors recorded and nothing was written
  (strict mode at validate stage, dry-run with errors, or a selection
  that left the plan empty).
- **`failed`** — an unexpected runtime error.

### Artifacts

Each `GeneratedArtifact` carries:

```json
{
  "kind": "sql_model",
  "entity_type": "hub",
  "entity_name": "hub_customer",
  "path": "/abs/path/to/raw_vault/hub_customer.sql",
  "size_bytes": 412,
  "checksum": "a1b2c3...",
  "content": null
}
```

`kind` is one of `sql_model`, `yaml_schema`, `project_yml`,
`packages_yml`, `sources_yml`, `dbt_profiles`, `zip`, `json_export`,
or `dbml_export`. `content` is populated only when
`options.return_content=True`.

### Issues

Each issue carries:

```json
{
  "severity": "error" | "warning" | "info",
  "code": "validate.hub.missing_hashkey",
  "message": "Standard hub must have a hashkey defined",
  "stage": "validate",
  "location": {
    "entity_type": "hub",
    "entity_name": "hub_customer",
    "field": "hashkey"
  },
  "entity": {
    "type": "hub",
    "name": "hub_customer",
    "group": "sales"
  },
  "suggestion": "Set a hashkey naming pattern on the project or the hub."
}
```

Note that `location` here is **entity- and field-scoped**, not
file/sheet/row-scoped: the generation pipeline reads from the Django
ORM, not from a source file, so file coordinates would be misleading.

### Issue code taxonomy

Codes are stable, dot-separated, and documented in
[`codes.md`](https://github.com/ScalefreeCOM/turbovault-engine/blob/main/backend/engine/services/generation/codes.md).

```
build.project_load_failed             build.export_inconsistent

validate.source.no_schema             validate.source.no_tables
validate.stage.no_source_table        validate.stage.no_keys
validate.hub.missing_hashkey          validate.hub.no_business_keys      validate.hub.no_source_tables
validate.link.missing_hashkey         validate.link.too_few_hubs         validate.link.no_sources
validate.satellite.no_parent          validate.satellite.no_stage        validate.satellite.no_columns       validate.satellite.no_hashdiff
validate.pit.no_satellites            validate.pit.no_snapshot_logic     validate.pit.no_tracked_entity
validate.snapshot.no_name             validate.snapshot.no_start_date    validate.snapshot.no_logic_patterns

plan.unsupported_output_type          plan.empty_project

render.template_not_found             render.template_render_failed      render.entity_skipped

write.io_error                        write.path_collision               write.zip_failed

internal.bug
```

The legacy alphanumeric codes (`HUB_001`, `LNK_001`, …) from the older
generation pipeline still surface through `Issue.location.field`
for backwards-compatible dashboards.

---

## Audit trail: GenerationRun

Every pipeline invocation — including dry-runs and failed runs — is
persisted as a `GenerationRun` row on the project. List recent runs:

```bash
turbovault generation-history --project my_project
turbovault generation-history --project my_project --limit 50
turbovault generation-history --interactive            # pick the project
turbovault generation-history --project my_project --type dbt
```

Each row carries:

| Field | Meaning |
|-------|---------|
| `started_at` / `finished_at` | When the run began and ended. |
| `status` | Terminal status (same values as `GenerationReport.status`). |
| `is_dry_run` | Whether it was a dry-run. |
| `output_type` | `dbt` / `json` / `dbml`. |
| `output_path` | Destination the caller requested (empty for dry-runs). |
| `error_strategy` | The mode used. |
| `files_generated` | Total artifacts persisted. |
| `error_count` / `warning_count` | Quick severity totals. |
| `report` | Full serialized `GenerationReport` JSON for deep inspection. |

The Studio frontend can link directly from a finished generation `Job`
to its underlying `GenerationRun` for richer drill-down UX in the
forthcoming Generation overhaul.

---

## Live progress

The pipeline accepts an optional `progress` callback that fires
`ProgressEvent`s at each stage transition (`started` → `done`). The CLI
uses these to render a progress indicator; the Studio's Celery task
forwards each event's `message` into `Job.current_step` so polling
clients see live "Building project export" / "Validating model" /
"Rendering dbt" / "Writing files" / … updates instead of a single
static "Preparing generation".

```python
def on_progress(event: ProgressEvent) -> None:
    print(f"[{event.stage}] {event.status}: {event.message}")

generate(project=p, output_type="dbt", progress=on_progress)
```

---

## Cookbook

### Generate a full dbt project to the conventional location

```bash
turbovault generate --project my_project --type dbt --zip
```

Outputs `<workspace>/projects/my_project/exports/dbt_project/` plus a
sibling `dbt_project.zip`.

### Preview what a run would do without writing anything

```bash
turbovault generate --project my_project --type dbt --dry-run
```

A `GenerationRun` row is still written so you can revisit the dry-run
plan in `turbovault generation-history`.

### Generate only the sales group's models

```bash
turbovault generate --project my_project --type dbt \
    --include-group sales
```

### Generate the SQL+YAML for one hub (e.g. CI verification of one change)

```bash
turbovault generate --project my_project --type dbt \
    --only hub:hub_customer
```

### CI gate: fail the build on any model-level issue

```bash
turbovault generate --project my_project --type dbt \
    --mode strict --dry-run
```

Exits with code `0` only when the project is fully valid and renderable.
Code `2` if validation or render uncovers errors.

---

## Exit codes (CLI)

| Code | Meaning |
|------|---------|
| `0` | `success` |
| `1` | `partial_success` — some entities skipped, others written |
| `2` | `validation_failed` or `failed` — nothing was written |

These map cleanly to typical CI conventions: `0` = OK, `1` = OK with
warnings to triage, `2` = block.
