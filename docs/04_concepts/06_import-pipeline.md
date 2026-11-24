---
sidebar_position: 6
sidebar_label: Import Pipeline
title: Import Pipeline
---

# Import Pipeline

The Import Pipeline is the engine subsystem that turns a metadata source
(Excel workbook, SQLite database, JSON export, or IRiS three-file export)
into Data Vault entities in a project. It is the single code path used by:

- The `turbovault import` CLI command.
- `turbovault project init --source <file>` when a source is provided.
- The web initialization wizard (`turbovault serve` → `/`).
- The future Turbovault Studio backend.

> **See also:** [`turbovault import` CLI reference](../02_getting-started/01_cli-reference.md#turbovault-import) and [`turbovault import-history`](../02_getting-started/01_cli-reference.md#turbovault-import-history).

---

## What the pipeline does

```
Source file ──▶ [1 Parse] ──▶ [2 Validate] ──▶ [3 Resolve]
                                                    │
                                                    ▼
            [6 Report] ◀── [5 Execute] ◀── [4 Plan]
```

Each stage produces typed output for the next; any stage can record
issues that show up in the final report.

| Stage | What it does |
|-------|--------------|
| **Parse** | Reads the source file into a row/sheet representation (Excel/SQLite) or a structured domain model (JSON, IRiS). Format-level problems (corrupt file, malformed JSON, missing sheets) become `source.*` issues. |
| **Validate** | Checks sheet headers against the [Excel Metadata Format](02_excel-metadata-format.md) — required columns, recognized column names, required values per row. Emits `schema.*` and `row.*` issues with sheet/row/column context. |
| **Resolve** | Cross-sheet semantic checks: every link references hubs that exist, every satellite has a parent, every column mapping points at a real source column. Emits `entity.*` issues. |
| **Plan** | Matches the resolved model against the current project state and produces an `ImportPlan`: which entities are new, which exist, which `replace_all` deletes and which are skipped. |
| **Execute** | Applies the plan inside one atomic transaction, comparing every row with what the project has and **writing only what differs**. Records each change, and turns every existing entity into `update` (something changed) or `unchanged` (it already matched). A dry run executes too, then rolls back. |
| **Report** | Persists an `ImportRun` audit row and returns a structured `ImportReport` to the caller. |

Re-imports are first-class: any project can be re-imported with the same
or a modified file at any time. Importing the same file again writes
nothing and reports every entity as `unchanged`. A modified file changes
exactly the entities it modifies, and the report lists what changed on
each, down to a new source mapping on a hub column.

---

## Conflict strategy

Controls what happens when the source file overlaps with entities that
already exist in the project.

| Strategy | New entity (in file, not in DB) | Existing entity (in both) | Existing entity (in DB, not in file) |
|----------|----------------------------------|----------------------------|---------------------------------------|
| `merge` *(default)* | **create** | **update** with new values (or **unchanged**) | **leave alone** |
| `replace_all` | **create** | **update** with new values (or **unchanged**) | **delete** (cascading to children) |
| `update_only` | skip (won't create) | **update** with new values (or **unchanged**) | leave alone |

CLI flag: `--mode merge | replace-all | update-only`.

An existing entity's children (columns, mappings) are merged: new ones are
added and changed ones updated, and ones the file doesn't list are kept,
whatever the strategy. The exceptions are the collections the file always
states in full: a link's hub references and their key mappings, a
prejoin's join columns, a reference table's satellite assignments and a
PIT's satellites. For those, the ones the file no longer lists are removed.

A source system is identified by its schema and database. A new name in
the file for the same schema renames the system rather than creating a new
one.

**Choose `merge`** to add or correct entities while preserving everything
else in the project. This is the safe default for iterative workflows.

**Choose `replace_all`** to make the project converge to exactly what is
in the file. Destructive — deletes any entity not present in the file and
all of its child rows. The Studio frontend requires explicit confirmation
for this mode.

[Pre-stages](01_domain-model.md#35-pre-stages) are the exception: only JSON
exports can describe them. A file in another format (Excel, SQLite, IRiS,
`source_metadata`), or a JSON export from before pre-stages existed, never
lists them, so `replace_all` keeps the project's pre-stages and the source
systems holding them.

**Choose `update_only`** for "just refresh the values" scenarios where
you don't want any new entities created.

---

## Error strategy

Controls what happens when individual rows or entities fail validation.

| Strategy | Behavior |
|----------|----------|
| `best_effort` *(default)* | Import everything that is valid; skip rows/entities that aren't; report every skip with full context. |
| `fail_fast` | Stop at the first validation or row-level error; no DB writes. |

CLI flag: `--on-error best-effort | fail-fast`.

**`best_effort` is the default** because users almost always prefer
partial results over an all-or-nothing failure. With `best_effort` the
final status is `partial_success` and the `issues` list in the report
tells you exactly what was skipped and why.

**`fail_fast` is available** for strict workflows (CI gates, scripted
deployments) where you want a clean all-or-nothing outcome.

### What counts as "skippable" vs "fatal"

Even in `best_effort`, the pipeline is sensible about what to skip:

| Problem | Effect under `best_effort` |
|---------|----------------------------|
| A sheet is missing a required *header* column | The whole sheet is dropped; other sheets continue. |
| A specific row is missing a required value | That row is skipped; other rows continue. |
| A link references a hub that doesn't exist | The whole link is skipped — without one of its hubs it would have a different grain. |
| A satellite references a parent hub/link that doesn't exist, or a source table that doesn't | That satellite is skipped; the parent (and other satellites) continue. |
| A reference table or PIT references a hub, link or satellite that doesn't exist | That reference table or PIT is skipped. |
| An entity depends on one that was skipped (a satellite of a skipped link, a PIT tracking it) | It is skipped too, with an `entity.depends_on_skipped` warning. |
| A column mapping points at a missing source table or column | That mapping is skipped; the entity itself is still created. |

Sheet-level structural errors are dropped wholesale because the pipeline
cannot reliably synthesize partial entities from a sheet with missing
header columns.

A skipped entity is never imported half-resolved. It appears in the plan
with `action: "skip"` and a `skip_reason` next to the error or warning
that explains it, so a dry-run shows exactly what a `best_effort` import
will leave out. Because the entity is in the source, `replace_all` never
deletes the project's existing copy of it.

The skip reasons are:

- `missing_reference`, `missing_parent`, `missing_source_table` and
  `depends_on_skipped`: something the entity needs is missing.
- `invalid_configuration`: the entity itself is inconsistent, e.g. a
  prejoin whose join columns don't line up.
- `execute_failed`: writing it failed, e.g. on a database constraint. Each
  entity is written in its own savepoint, so a failure rolls back that
  entity alone.
- `skip_snapshots`: a PIT needs a snapshot control, and the import runs
  with `skip_snapshots`. An existing PIT is kept, even under `replace_all`.
- `update_only`: the entity is new, and `update_only` never creates.

---

## Dry-run mode

Run the entire pipeline, including the execute stage, inside a transaction
that is rolled back at the end. Nothing is kept, but the report is exactly
what the real import would produce: the same actions, the same changes,
and the same issues, including the ones only writing reveals (a constraint
the data would violate).

CLI flag: `--dry-run`.

Dry-runs still persist an `ImportRun` audit row with `is_dry_run=True`,
so you can find them via `turbovault import-history`.

A dry-run takes about as long as the import itself. It holds the
database's write locks until it rolls back, which on SQLite means
the whole database for that moment.

Use a dry-run when:

- You want to preview the impact of a `replace_all` before committing.
- You want to see what a modified file changes before writing it.
- You want to know whether a file is valid without touching the
  database.
- You want a structured machine-readable validation result for CI.

---

## Stopping before the write

`import_metadata(..., on_plan=callback)` calls `callback` with a copy of
the plan once it is built, before anything is written. The plan's
`state` is `planned` there: creates, deletes and skips are final, and
entities that exist are still `update` (the executor finds out whether
they change). Raising from the callback stops the import. The run is
recorded with a `plan.rejected` issue, and the exception reaches the
caller. The Studio uses this to enforce its quotas on the entities an
import would create.

---

## Live progress

`import_metadata(..., progress=callback)` calls `callback` with a
`ProgressEvent` as the import runs. Every stage emits `started` and
`done`; the execute stage also emits one `in_progress` event per entity it
applies, with `current` (1-based) and `total`. A caller can drive a progress
bar from these; the Studio forwards each `message` into `Job.current_step`
and turns the events into a run's detailed log and progress bars.

```python
def on_progress(event: ProgressEvent) -> None:
    print(f"[{event.stage}] {event.status}: {event.message}", event.detail or "")

import_metadata(project=p, source=ExcelSource(path=path), progress=on_progress)
```

For the bundled TPC-H workbook this prints, among others:

```
[parse] done: Parse complete {'read': {'source_data': 8, 'standard_hub': 13, 'standard_link': 12, 'standard_satellite': 26, ...}}
...
[execute] in_progress: Created source system TPCH {'entity_type': 'source_system', 'name': 'TPCH', 'action': 'create'}
[execute] in_progress: Created source table Customer {'entity_type': 'source_table', 'name': 'Customer', 'action': 'create'}
...
[execute] done: Execute complete {'applied': 39}
[report] done: Import success
```

### Event details

`ProgressEvent.detail` holds small JSON values (strings, numbers, booleans,
`None`, and lists and dicts of those). `message` is a short sentence for
people; read `detail` in code.

| Stage | Status | `detail` |
|-------|--------|----------|
| `parse` | `done` | `{"read": {<kind>: count}}`: what the source holds, as the parser models it. An Excel workbook or SQLite database is read as sheets of rows: the keys are its sheet names (`source_data`, `standard_hub`, …), the counts their rows; the validate stage turns them into entities. Every other source is read as entities, with every key present: `source_system`, `source_table`, `source_column`, `hub`, `link`, `satellite`, `pit`, `reference_table`, `snapshot_control`, `prejoin`. |
| `validate` | `done` | `{"errors": n, "warnings": n}`: the issues the validate stage found. |
| `plan` | `done` | `{"totals": {...}, "by_entity_type": {...}}`: the planned actions, as the plan's `counts` has them before the executor ran. |
| `execute` | `in_progress` | One per entity applied: `{"entity_type", "name", "action"}`. |
| `execute` | `done` | `{"applied": n}`: the entities the import created, updated or deleted. `0` for a dry run, and for a `fail_fast` import that rolled back. |

The other events carry no `detail`, and only `in_progress` events carry
`current` and `total`.

- **Execute** events follow each entity as it is applied: deletes first,
  then the rest in plan order. Planned skips aren't applied and get no
  event, so `total` is the number of entities the executor applies.
  `action` is what applying the entity did, as the report's plan names it:
  `create`, `update`, `unchanged`, `delete`, or `skip` if writing it
  failed. Messages read "Created hub CUSTOMER_H", "Updated …",
  "No changes to …", "Deleted …", "Skipped …".
- **A dry run** reports the same actions, since it applies the plan before
  rolling back, and says "Would create hub CUSTOMER_H".
- **Without a callback** nothing is built for it: the CLI and other callers
  pay nothing.

### Stopping an import from the callback

An `Exception` raised by the callback is ignored: a broken progress consumer
never fails an import. Any other `BaseException` (the Studio raises one to
stop a run at a safe point, and `KeyboardInterrupt` is one too) propagates
out of `import_metadata()` unchanged. Raised during the execute stage, it
rolls the import's transaction back, so the project stays as it was. The
import then has no report and no `ImportRun` row.

---

## The project's settings

`import_metadata(..., runtime_config=config)` passes the project's
settings (`EngineRuntimeConfig`) for callers that keep them outside the
project's `config.yml`, as the Studio does. Its naming patterns name the hash
keys and hash diffs the import derives, and a dbt project import stores a
model's name only where it differs from what they give. Without it the
import reads the project's `config.yml`, else the defaults.

A dbt project import also suggests settings, and applies none of them. These
are the values most of the project's models follow, plus copies of its
`dbt_project.yml` and package files:

- naming patterns, layer schemas and materializations, folder patterns
- the tables' default record source, load date and static part
- stage options, the delivery method and default tags
- the dbt project's `dbt_project.yml` and packages

The report lists them in `project_settings.suggestions`, keyed by setting.
Each one has its value and how many models follow it, and gets a
`dbt.setting_suggested` info. Models, tables and source systems store only
what differs from the settings the import was given. After you apply the
suggestions, importing again stores less. The CLI offers to apply them after a
dry run (`--apply-settings`). `EngineRuntimeConfig.with_settings()` applies
them to a runtime config.

---

## The ImportReport

Every invocation of the pipeline returns an `ImportReport`. The same
object is serialized into `output_metadata` on the Studio's `Job` model
and into `ImportRun.report` for CLI history.

Top-level fields:

| Field | Meaning |
|-------|---------|
| `import_run_id` | UUID of the persisted `ImportRun`. |
| `project_id` | The target project. |
| `status` | `success` \| `partial_success` \| `validation_failed` \| `failed`. |
| `is_dry_run` | `true` if the run was rolled back. |
| `options` | The full `ImportOptions` used (conflict strategy, error strategy, dry-run, etc.). |
| `plan` | Entity-by-entity actions and changes, with per-action counts. |
| `issues` | Every issue produced anywhere in the pipeline (see below). |
| `timings_ms` | Per-stage durations. |

### The plan

Each entity in `plan.entities` has an `action`:

| Action | Meaning |
|--------|---------|
| `create` | New: the import creates it. |
| `update` | It exists, and the import changed something about it. `changes` lists what. |
| `unchanged` | It exists and already matches the source. Nothing is written. |
| `delete` | `replace_all` deletes it: it's in the project, not in the source. |
| `skip` | Left out, with a `skip_reason` (see above). |

`plan.counts` counts them per entity type and in total. `plan.state` says
how far the plan got:

- `planned`: matched only. This is what `on_plan` sees and what a run
  that aborted before executing reports.
- `simulated`: a dry run.
- `applied`: a real run.

Each change carries a `path` and a `kind`:

```json
{
  "field": "columns.customer_id.source_mappings.orders.customer_no",
  "path": ["columns", "customer_id", "source_mappings", "orders.customer_no"],
  "kind": "added",
  "before": null,
  "after": {"is_primary_source": false}
}
```

The path is pairs of (collection, key) down to a child row, followed by a
field name for a changed value:

- An even-length path names a child row that was `added` or `removed`, for
  example `["hub_references", "hk_customer"]`.
- An odd-length path names a field that `changed`, for example
  `["columns", "EMAIL", "source_column_datatype"]` or just `["description"]`.

Keys are raw names and may contain dots; `field` is the path joined for
display. Values are plain JSON: a group, hub or table reads by its name.
A new entity lists no changes.

### Status semantics

- **`success`** — no error-severity issues.
- **`partial_success`** — there were errors, but the executor committed
  and applied at least one entity (created, updated, deleted or confirmed
  unchanged). The "import what's valid, skip the rest" outcome.
- **`validation_failed`** — there were errors and nothing was written.
  Used for dry-runs that uncover problems, for `fail_fast` aborts at
  validation, and for `best_effort` runs where every entity in the file
  ended up skipped.
- **`failed`** — an unexpected runtime error during execution.

### Issues

Each issue carries:

```json
{
  "severity": "error" | "warning" | "info",
  "code": "schema.missing_column",
  "message": "Sheet 'standard_hub' is missing required column(s): source_table_identifier.",
  "stage": "validate",
  "location": {
    "file": "metadata.xlsx",
    "sheet": "standard_hub",
    "row": 5,
    "column": "source_column_physical_name"
  },
  "entity": {
    "type": "hub",
    "name": "hub_customer"
  },
  "suggestion": "Add the listed column(s) to the header row."
}
```

`location` is populated for parse/validate issues; `entity` is populated
for resolve/execute issues; both may be present for the most useful
context. Issues of a dbt project import locate a model by its dbt node
(`"node_id": "model.shop.hub_customer"`), its file (`file`) and the macro
parameter concerned (`"parameter": "src_hashdiff"`).

### Issue codes

Codes are stable and machine-readable. Frontends use them to localize
messages and link to fix-it docs.

| Stage | Code | Meaning |
|-------|------|---------|
| Parse | `source.unreadable` | The file could not be opened. |
| Parse | `source.unsupported_format` | File extension does not match a supported source. |
| Parse | `source.empty` | The file contains no content (no sheets / no tables). |
| Parse | `source.invalid_json` | JSON file is malformed or not a Turbovault export. |
| Validate | `schema.missing_sheet` | A required sheet is absent. |
| Validate | `schema.missing_column` | A required header column is missing from a present sheet. |
| Validate | `schema.unknown_sheet` | A sheet name is not recognized (warning). |
| Validate | `schema.unknown_column` | A column name in a known sheet is not recognized (warning by default). |
| Validate | `row.required_value_missing` | A required cell is empty. |
| Validate | `row.invalid_type` | A cell value cannot be coerced to the expected type. |
| Validate | `row.invalid_enum_value` | A cell value is not one of the allowed options. |
| Resolve | `entity.duplicate_name` | The same physical name appears twice. |
| Resolve | `entity.missing_parent` | A satellite's parent hub/link is not defined anywhere. |
| Resolve | `entity.missing_reference` | A link, reference table or PIT references a hub/link that is not defined. |
| Resolve | `entity.missing_source_table` | A mapping references a source table identifier that does not exist. |
| Resolve | `entity.missing_source_column` | A mapping references a column that is not present in its source table. |
| Resolve, Execute | `entity.invalid_configuration` | An entity is internally inconsistent, or one of its model settings can't be stored (left out; the entity is imported). |
| Resolve | `entity.depends_on_skipped` | An entity is left out because something it depends on was skipped (warning). |
| Plan | `plan.would_create` / `would_update` / `would_delete` / `would_skip` | Dry-run hints — informational only. |
| Plan | `plan.rejected` | The caller's `on_plan` callback stopped the import before anything was written. |
| Execute | `execute.constraint_violation` | A database constraint blocked a write. |
| Execute | `execute.unexpected_error` | An unexpected runtime error during execute. |
| Internal | `internal.bug` | An unreachable code path was hit. Please file a bug. |

The CLI's Issues table renders every issue with its location and a
short message. The Studio frontend uses the same codes to render the
job's error UI.

---

## Audit trail: ImportRun

Every pipeline invocation — including dry-runs and failed runs — is
persisted as an `ImportRun` row on the project, except an import its
progress callback [stopped](#stopping-an-import-from-the-callback). List
recent runs with:

```bash
turbovault import-history --project my_project
turbovault import-history --project my_project --limit 50
turbovault import-history --interactive            # pick the project
```

Each row carries:

| Field | Meaning |
|-------|---------|
| `started_at` / `finished_at` | When the run began and ended. |
| `status` | Terminal status (same values as `ImportReport.status`). |
| `is_dry_run` | Whether it was a dry-run. |
| `source_type` / `source_name` | What was imported. |
| `conflict_strategy` / `error_strategy` | The mode used. |
| `error_count` / `warning_count` | Quick severity totals. |
| `report` | Full serialized `ImportReport` JSON for deep inspection. |

The Studio frontend can link directly from a finished `Job` to its
underlying `ImportRun` for richer error rendering than the truncated
`user_error_message` field allows.

---

## Source format reference

| Source | Where to find the format spec |
|--------|-------------------------------|
| Excel | [Excel Metadata Format](02_excel-metadata-format.md) |
| SQLite | Same column/sheet layout as Excel; tables match Excel sheet names. |
| JSON | [JSON Import (Round-Trip)](04_json-import.md) — produced by `turbovault generate --type json`. |
| IRiS | A directory holding the `Source_*` / `DataVault_*` / `Mappings_*` workbooks produced by `turbovault generate --type iris`. Reconstructs the hubs, links, satellites and mappings the files contain. See [IRiS Import (Round-Trip)](../00_index.md#iris-import-round-trip). |
| dbt | A datavault4dbt project's artifacts (`DbtSource`): its folder, or its `manifest.json` (schema v12) with optional `catalog`, `dbt_project` and `packages` files. The import reads files only, never runs dbt or connects to a warehouse, and reports which artifacts it found (`dbt.*` codes). Stages become source tables, or pre-stages when they read a model of the project; Hubs, Links and Satellites map their columns to the stage's source, derived and prejoined columns; effectivity and record-tracking satellites become their Hub's or Link's. A model's name is stored only where it differs from the project's naming patterns. What can't be mapped is reported on its model (`location.node_id`) and planned as a skip; under `fail_fast`, mapping errors stop the import before anything is written. A project that maps to no TurboVault entity imports nothing (`dbt.nothing_to_import`), so `replace_all` can't empty a project. A dbt project TurboVault generated imports back to the metadata it came from: TurboVault's default descriptions and generated renames aren't taken for the project's own. Walkthrough: [Importing a dbt Project](../02_getting-started/06_dbt-project-import.md). See the [dbt project import specification](https://github.com/ScalefreeCOM/turbovault-engine/blob/main/backend/docs/07_dbt_project_import_specification.md). |

For source-specific format issues (missing sheets, wrong column names),
read the parse/validate sections above and the format reference for
your source type.

---

## Cookbook

### Re-import the same file safely

```bash
turbovault import --project my_project --source ./metadata.xlsx
```

`merge` is the default — the second run will pick up any corrections you
made to the file and update existing entities. Nothing gets duplicated;
nothing gets deleted.

### Preview what an import would do without touching the DB

```bash
turbovault import --project my_project --source ./metadata.xlsx --dry-run
```

The report shows the planned diff. An `ImportRun` is still written so
you can revisit the dry-run in `turbovault import-history`.

### Make the project match the file exactly

```bash
turbovault import --project my_project --source ./metadata.xlsx --mode replace-all
```

Anything in the project that isn't in the file gets deleted (with
cascade). Always preview this with `--dry-run` first.

### CI gate: fail the build on any validation issue

```bash
turbovault import --project my_project --source ./metadata.xlsx \
  --on-error fail-fast --dry-run
```

Exits with code `0` only when the file is fully valid. Code `2` if
validation finds errors.

### Inspect what was skipped after a partial import

```bash
turbovault import-history --project my_project --limit 1
```

For the most recent run, the human-readable table shows status, error
count, and warning count. For full detail, query the `ImportRun.report`
JSON directly from the Django ORM.

---

## Exit codes (CLI)

| Code | Meaning |
|------|---------|
| `0` | `success` |
| `1` | `partial_success` — some entities skipped, others written |
| `2` | `validation_failed` or `failed` — nothing was written |

These map cleanly to typical CI conventions: `0` = OK, `1` = OK with
warnings to triage, `2` = block.
