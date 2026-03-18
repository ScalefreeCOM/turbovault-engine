---
sidebar_position: 3
sidebar_label: Step-by-Step Example
title: Step-by-Step Example (TPC-H)
---

# Step-by-Step Example (TPC-H)

This guide walks you through a complete example of using TurboVault Engine with the provided TPC-H sample data. You will initialize a workspace, import the TPC-H metadata, generate a dbt project, and create a DBML visualization of the model.

## Prerequisites

Make sure you have installed TurboVault Engine. If not, refer to the [Workspace Setup](02_workspace-setup.md) guide.

You will need the two sample files provided in the repository root:
- `TurboVault_TPCH_Data.xlsx` (contains the Data Vault modeling metadata)
- `TurboVault_TPCH_Data.db` (a sample SQLite database containing the raw TPC-H data schema)

## 1. Initialize the Workspace

First, create a new directory for your TurboVault workspace and initialize it:

```bash
mkdir tpch-workspace
cd tpch-workspace
turbovault workspace init
```

Follow the interactive prompts or run it non-interactively. This will create your `turbovault.yml` configuration and the local Engine database.

## 2. Copy the Sample Data

Copy the TPC-H sample files into your new workspace:

```bash
# Assuming the files are in the directory above
cp ../TurboVault_TPCH_Data.xlsx .
cp ../TurboVault_TPCH_Data.db .
```

*(Note: The `config.yml` or the interactive prompt will ask for the path to the Excel file. Having it in the workspace folder keeps things tidy.)*

## 3. Initialize the Project

Next, create a new project that points to the TPC-H Excel metadata file. We'll use the interactive wizard:

```bash
turbovault project init --interactive
```

When prompted, provide:
* **Project Name**: `tpch_dv`
* **Metadata File**: `./TurboVault_TPCH_Data.xlsx`
* **Stage Schema**: `stage`
* **RDV Schema**: `rdv`

Alternatively, you can initialize it directly with flags:

```bash
turbovault project init --name tpch_dv --source ./TurboVault_TPCH_Data.xlsx --stage-schema stage --rdv-schema rdv
```

This step reads the Excel file, validates the metadata, and imports all Hubs, Links, and Satellites into the TurboVault domain model.

## 4. Generate the dbt Project

With the metadata imported, you can now generate the fully functioning dbt project:

```bash
turbovault generate --project tpch_dv --type dbt
```

*(Note: `dbt` is the default generation type, so `turbovault generate --project tpch_dv` works too.)*

You will see output indicating that models, macros, and YAML configuration files have been successfully generated inside your `output/tpch_dv/` folder. This folder is a complete dbt project using `datavault4dbt` macros, ready to be executed against your data platform.

## 5. Generate a DBML Visualization

It's often helpful to visualize your Data Vault model. TurboVault Engine can export the model directly to DBML format (Database Markup Language), which you can render in tools like [dbdiagram.io](https://dbdiagram.io).

```bash
turbovault generate --project tpch_dv --type dbml
```

This will create a `.dbml` file in your output directory representing the Hubs, Links, and Satellites structure of the TPC-H model.

## Summary

In these few steps, you have:
1. Set up a TurboVault workspace.
2. Imported a comprehensive Data Vault model from Excel (`TurboVault_TPCH_Data.xlsx`).
3. Generated a production-ready dbt project.
4. Exported a DBML diagram of your architecture.
