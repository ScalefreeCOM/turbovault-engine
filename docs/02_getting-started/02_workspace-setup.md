---
sidebar_position: 4
sidebar_label: Workspace Setup
title: Workspace Setup
---

# TurboVault Workspace Guide

## What is a TurboVault Workspace?

A **TurboVault workspace** is a directory containing:
- `turbovault.yml` — Global configuration (database, schema defaults)
- `db.sqlite3` — SQLite database (or connection to an external DB)
- `projects/` — One subdirectory per project

Think of it like a **Git repository**: run `turbovault workspace init` once in your target folder, then create as many projects as you need with `turbovault project init`.

---

## Two-Step Setup

```
turbovault workspace init    # Step 1: set up the workspace (once per folder)
turbovault project init      # Step 2: create a project inside it
```

---

## Step 1 — Creating a Workspace

### Interactive mode

```bash
cd my_turbovault
turbovault workspace init
```

You will be prompted for database engine, schema names, and an optional admin user.

### Non-interactive mode (CI / scripts)

```bash
turbovault workspace init \
  --db-engine sqlite3 \
  --db-name db.sqlite3 \
  --stage-schema stage \
  --rdv-schema rdv \
  --skip-admin
```

For PostgreSQL:

```bash
turbovault workspace init \
  --db-engine postgresql \
  --db-name company_vault \
  --db-host db.company.com \
  --db-port 5432 \
  --db-user turbovault_user \
  --db-password secret \
  --stage-schema stage \
  --rdv-schema rdv \
  --admin-username admin \
  --admin-password changeme \
  --admin-email admin@company.com
```

**What this creates:**

```
my_turbovault/
├── turbovault.yml         # Created by workspace init
├── db.sqlite3             # Created by workspace init
└── projects/              # Created when you add projects
```

---

## Step 2 — Creating a Project

Once a workspace exists, create projects inside it:

### Interactive mode

```bash
turbovault project init --interactive
```

### Non-interactive mode

```bash
turbovault project init \
  --name my_project \
  --source ./metadata.xlsx \
  --stage-schema stage \
  --rdv-schema rdv
```

### From a config file

```bash
turbovault project init --config config.yml
```

**What this creates:**

```
my_turbovault/
├── turbovault.yml
├── db.sqlite3
└── projects/
    └── my_project/
        ├── config.yml
        ├── dbt_project/
        └── exports/
```

---

## Workspace Commands

| Command | Description |
|---|---|
| `turbovault workspace init` | Initialise directory as a workspace |
| `turbovault workspace status` | Show DB connection, project count, migration status |

```bash
turbovault workspace status

# Output:
#   Config file:     turbovault.yml
#   Database:        sqlite3 / db.sqlite3
#   DB status:       Connected
#   Projects:        2
#   Migrations:      Up to date
```

---

## Project Commands

| Command | Description |
|---|---|
| `turbovault project init` | Create a new project in the workspace |
| `turbovault project list` | List all projects in the workspace |

```bash
turbovault project list

# Output:
# ┌─────────────┬─────────────┬──────────────────────┐
# │ Name        │ Description │ Directory            │
# ├─────────────┼─────────────┼──────────────────────┤
# │ TestProject │ —           │ projects/testproject │
# └─────────────┴─────────────┴──────────────────────┘
```

---

## Workspace Rules

✅ **DO:**
- Run `turbovault` commands from workspace root
- Keep `turbovault.yml` in version control
- Run `turbovault workspace init` before any other command

❌ **DON'T:**
- Run `turbovault project init` from a directory without `turbovault.yml`
- Use absolute paths in config
- Commit `db.sqlite3` to Git (add to `.gitignore`)

---

## Multiple Workspaces

Each workspace is completely isolated — different databases, different projects:

```
C:\Users\yourname\Documents\
├── customer_vault\           # Workspace 1
│   ├── turbovault.yml
│   ├── db.sqlite3
│   └── projects\
│       └── customers\
└── supplier_vault\           # Workspace 2
    ├── turbovault.yml
    ├── db.sqlite3
    └── projects\
        └── suppliers\
```

---

## Team Collaboration

### One-time: Create workspace repository

```bash
mkdir company-datavault
cd company-datavault

turbovault workspace init \
  --db-engine postgresql \
  --db-name company_vault \
  --db-host db.company.com \
  --db-port 5432 \
  --db-user vault_user \
  --db-password secret \
  --admin-username admin \
  --admin-password changeme \
  --admin-email admin@company.com

# Create .gitignore
echo "db.sqlite3" > .gitignore

git init
git add turbovault.yml .gitignore
git commit -m "Initial turbovault workspace"
git push origin main
```

### Team members: Clone and work

```bash
git clone https://github.com/company/company-datavault.git
cd company-datavault

turbovault workspace status    # verify DB connection
turbovault project list        # see existing projects
turbovault serve               # open Django Admin
```

### Day-to-day workflow

```bash
# Alice: Add a new project
turbovault project init --name new_project
git add projects/new_project/config.yml
git commit -m "Add new_project"
git push

# Bob: Get updates and generate
git pull
turbovault generate --project new_project
```

---

## Database Options

### SQLite (Development)

**turbovault.yml:**
```yaml
database:
  engine: sqlite3
  name: db.sqlite3    # Local file, each developer has their own
```

### PostgreSQL (Team/Production)

**turbovault.yml:**
```yaml
database:
  engine: postgresql
  name: shared_vault
  host: db.company.com
  user: vault_user
  password: ${DB_PASSWORD}    # Use an environment variable!
```

---

## FAQ

### "Not a TurboVault workspace!" error?

You're running a command from a directory without `turbovault.yml`.

```bash
turbovault workspace init    # initialise first
```

### Can I move my workspace?

**Yes!** Move the entire folder — everything uses relative paths:

```bash
mv ~/old_location/my_vault ~/new_location/my_vault
cd ~/new_location/my_vault
turbovault serve    # still works
```

### Can I rename my workspace folder?

**Yes!** The folder name doesn't matter.

---

## Best Practices

1. **Use version control**
   ```bash
   git init
   git add turbovault.yml projects/
   git commit -m "Initial workspace"
   ```

2. **Ignore generated files**
   ```.gitignore
   db.sqlite3
   projects/*/dbt_project/
   projects/*/exports/
   ```
