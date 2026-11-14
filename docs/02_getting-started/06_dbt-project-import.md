---
sidebar_position: 6
sidebar_label: Importing a dbt Project
title: Importing a dbt Project
---

# Importing a dbt Project

TurboVault imports an existing **datavault4dbt** project from its dbt artifacts. You then keep modelling
its Data Vault in TurboVault and generate it back into the same dbt project. This guide walks through the
loop:

1. Import the project, with the settings it suggests.
2. Work on the Data Vault in TurboVault.
3. Generate back into the dbt project.

## What you need

- A dbt project that builds its Data Vault with datavault4dbt (1.x or 2.x).
- Its `manifest.json`, schema v12 (dbt Core 1.8 or later, dbt Cloud, dbt Fusion). `dbt parse` writes it to
  `target/manifest.json` without connecting to the warehouse.
- Optionally, its `catalog.json` (`dbt docs generate`, which queries the warehouse). It gives the column data
  types; without it they come from the YAML properties only.
- Optionally, `dbt_project.yml` and the package files (`packages.yml`, `dependencies.yml`,
  `package-lock.yml`). In the project folder the import finds them itself.

TurboVault only reads these files. It never runs your models, never connects to the warehouse, and never
reads `profiles.yml`.

## 1. Create a project

```bash
turbovault project init --name shop --no-snapshot-controls
```

`--no-snapshot-controls` leaves out TurboVault's default snapshot control: the dbt project brings its own.

## 2. Preview the import

```bash
turbovault import --project shop --source ../shop_dbt --dry-run
```

The source is the dbt project's folder, or its `manifest.json`. If the folder has no manifest yet,
`--dbt-parse` runs `dbt parse` first. That needs dbt, the project's adapter and its installed packages.

The dry run imports everything and rolls it back. The CLI shows:

- **which artifacts it found:** a missing catalog or `dbt_project.yml` is a warning;
- **the plan:** entities created, updated, unchanged or skipped;
- **the issues:** each one names the model, its file and the parameter, with a `dbt.*` code
  ([list](https://github.com/ScalefreeCOM/turbovault-engine/blob/main/backend/engine/services/imports/codes.md));
- **the settings the dbt project suggests:** see below.

### What is imported

| In the dbt project | In TurboVault |
|--------------------|---------------|
| Stage reading a dbt source | That source table, with the stage's record source, load date, derived columns, prejoins and options |
| Stage reading a model, seed, dbt snapshot or another package's model | A **pre-stage**: a source table whose model stays in the dbt project |
| `hub`, `ref_hub`, `link`, `nh_link` | Hubs and Links, with their columns mapped to the stage's columns |
| `sat_v0`, `ma_sat_v0`, `nh_sat`, `ref_sat_v0` and their v1 views | Satellites |
| `eff_sat_v0`, `rec_track_sat` | Options of their Hub or Link |
| `control_snap_v0` / `_v1`, `pit`, `ref_table` | Snapshot controls, PITs, reference tables |
| Group tags or subject folders (`models/rdv/<subject>/`) | Groups |
| Model names, folders, schemas, materializations, tags and further `config()` keys | The model's settings, where they differ from what TurboVault generates |

Not imported, and reported:

- models without a Data Vault macro (marts, business logic);
- datavault4dbt macros or parameters TurboVault doesn't support;
- tests, analyses and exposures.

Models the import doesn't map stay in your dbt project untouched.

### The settings the dbt project suggests

The import compares the dbt project with your project's settings and suggests what most of its models
follow:

- naming patterns, layer schemas and materializations, folder patterns;
- the tables' default record source and load date, stage options, the delivery method;
- whether to add TurboVault's default tags.

It also suggests copying the dbt project's `dbt_project.yml` and packages. The CLI shows each suggestion with
how many models follow it.

Nothing is applied by itself. Applied, the suggestions make new entities follow the dbt project's style, and
the imported models store only what differs from them.

## 3. Import

```bash
turbovault import --project shop --source ../shop_dbt --apply-settings
```

`--apply-settings` writes the suggested settings into the project's `config.yml` before importing.
`--keep-settings` imports with the settings you have. Without either, the CLI asks in a terminal. It edits
`config.yml` in place and keeps everything else in it.

Importing the same artifacts again writes nothing that hasn't changed. With the settings applied, a second
import suggests nothing more.

## 4. Work on the Data Vault

From here the project is a TurboVault project like any other: add sources, Hubs, Links and Satellites,
change their settings, rename models.

The imported models keep their names and folders. New entities follow the project's naming and folder
patterns (see [Folder structure](../03_configuration/03_project-schema.md#folder-structure)).

## 5. Generate back into the dbt project

```bash
turbovault generate --project shop --type dbt --output ../shop_dbt
```

The folder holds a dbt project whose `dbt_project.yml` TurboVault didn't write, so TurboVault:

- **writes its models, their YAML and the source definitions.** The first time, the report notes the project's
  own files it replaced.
- **keeps `dbt_project.yml`, `packages.yml` and `profiles.yml`.** The project's folder settings apply. A model
  carries its layer's schema and materialization in `config()` where those give it none. The report lists any
  package or variable the models need that the project lacks.
- **reports models, model YAML and source tables the project defines twice.** dbt needs one of each, so remove
  the other.
- **records the files it wrote** in `.turbovault/generated.json`. Commit it with the project. Later runs report
  the files TurboVault no longer generates, for example after you rename an entity. `--remove-stale-files`
  deletes them, if unchanged since TurboVault wrote them.

Set `dbt_project.path` in the project's `config.yml` to make the dbt project the default for both commands:

```yaml
dbt_project:
  path: ../shop_dbt
```

```bash
turbovault import --project shop --format dbt
turbovault generate --project shop --type dbt
```

Then check the result with dbt:

```bash
cd ../shop_dbt && dbt parse
```

### Other ways to generate

- **Into TurboVault's structure:** `--standard-folders` places the models in the project's folder patterns
  instead of their original folders. They keep the settings their original folders gave them. The report then
  lists the original files the project still defines: remove them.
- **As a separate dbt project:** generate into an empty folder (`--output ./shop_new`) to get a complete project
  with TurboVault's own `dbt_project.yml`, carrying the imported settings. A project whose stages read
  pre-stages can only run inside the dbt project that has their models.

## Good to know

- **Pre-stages** are models, seeds, dbt snapshots or package models your stages read. Their SQL stays in the
  dbt project. TurboVault generates no file for them and reports them, so generate into the dbt project that
  has them.
- **Ambiguous references are left out** and reported. For example, a link whose foreign hash key two Hubs
  share is skipped with `dbt.link_hub_ambiguous`; `replace-all` keeps the project's copy of skipped entities.
- **Round trip:** a project TurboVault generated imports back to the metadata it came from, and generating
  that again gives the same files. The CI checks this with dbt on every change.

The full behaviour is in the
[dbt project import specification](https://github.com/ScalefreeCOM/turbovault-engine/blob/main/backend/docs/07_dbt_project_import_specification.md).
