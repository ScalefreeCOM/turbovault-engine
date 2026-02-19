# TurboVault Workspace Guide

## What is a TurboVault Workspace?

A **TurboVault workspace** is a directory containing:
- `turbovault.yml` - Global configuration
- `db.sqlite3` - Database (if using SQLite)
- `projects/` - Subdirectories for each project

Think of it like a **Git repository** - you must be in a workspace to run TurboVault commands.

---

## Creating a Workspace

### Option 1: Initialize New Workspace

```bash
# Navigate to where you want your workspace
cd C:\Users\yourname\Documents\

# Create workspace directory
mkdir my_turbovault
cd my_turbovault

# Initialize (creates turbovault.yml)
turbovault init --interactive
```

This creates:
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

### Option 2: Clone Existing Workspace

```bash
# Clone team's workspace from Git
git clone https://github.com/myteam/turbovault-workspace.git
cd turbovault-workspace

# You now have:
# - turbovault.yml
# - projects/*/config.yml
# 
# Database options:
# - SQLite: Each developer has local db.sqlite3
# - PostgreSQL: Everyone shares central database
```

---

## Workspace Rules

✅ **DO:**
- Run `turbovault` commands from workspace root
- Keep `turbovault.yml` in version control
- Use relative paths (`project_root: "."`)
- Share workspace via Git

❌ **DON'T:**
- Run `turbovault` from random directories
- Use absolute paths in config
- Commit `db.sqlite3` to Git (add to .gitignore)

---

## Multiple Workspaces

You can have multiple independent workspaces:

```
C:\Users\yourname\Documents\
├── customer_vault/          # Workspace 1
│   ├── turbovault.yml
│   ├── db.sqlite3
│   └── projects/
│       └── customers/
└── supplier_vault/          # Workspace 2
    ├── turbovault.yml
    ├── db.sqlite3
    └── projects/
        └── suppliers/
```

Each workspace is completely isolated - different databases, different projects.

---

## Team Collaboration

### Setup for Teams

**1. One-time: Create workspace repository**

```bash
mkdir company-datavault
cd company-datavault

# Create turbovault.yml
cat > turbovault.yml << EOF
database:
  engine: postgresql
  name: company_vault
  user: turbovault_user
  password: secret
  host: db.company.com
  port: 5432

project_root: "."

defaults:
  stage_schema: stage
  rdv_schema: rdv
EOF

# Initialize first project
turbovault init --interactive

# Create .gitignore
cat > .gitignore << EOF
db.sqlite3
*.pyc
__pycache__/
.env
EOF

# Commit and push
git init
git add .
git commit -m "Initial turbovault workspace"
git push origin main
```

**2. Team members: Clone and work**

```bash
# Clone workspace
git clone https://github.com/company/company-datavault.git
cd company-datavault

# Verify config points to shared database
cat turbovault.yml

# Start working
turbovault serve
turbovault generate --project customers
```

### Workflow

```bash
# Alice: Add new project
turbovault init --name new_project
git add projects/new_project/config.yml
git commit -m "Add new_project"
git push

# Bob: Get updates
git pull
turbovault generate --project new_project  # Works immediately!
```

---

## Database Options

### SQLite (Development)

**turbovault.yml:**
```yaml
database:
  engine: sqlite3
  name: db.sqlite3  # Local file, each developer has their own
```

Each team member has their own database - great for experiments!

### PostgreSQL (Team/Production)

**turbovault.yml:**
```yaml
database:
  engine: postgresql
  name: shared_vault
  host: db.company.com
  user: vault_user
  password: ${DB_PASSWORD}  # Use environment variable!
```

Everyone shares the same database - Data Vault models are centralized.

---

## FAQ

### "Config file not found" error?

**Cause:** You're not in a turbovault workspace.

**Solution:**
```bash
# Check current directory
pwd

# Should see turbovault.yml
ls turbovault.yml

# If not, navigate to workspace
cd /path/to/workspace
```

### Can I move my workspace?

**Yes!** Just move the entire folder. Everything is relative:

```bash
# Move workspace
mv ~/old_location/my_vault ~/new_location/my_vault
cd ~/new_location/my_vault

# Still works!
turbovault serve
```

### Can I rename my workspace folder?

**Yes!** The folder name doesn't matter:

```bash
mv my_vault customer_vault
cd customer_vault
turbovault serve  # Works fine
```

---

## Best Practices

1. **One workspace per team/domain**
   - Customer Data Vault → `customer-vault/`
   - Supplier Data Vault → `supplier-vault/`

2. **Use version control**
   ```bash
   git init
   git add turbovault.yml projects/
   git commit -m "Initial workspace"
   ```

3. **Keep it portable**
   - Use relative paths only
   - `project_root: "."`
   - Database file relative to workspace

4. **Ignore generated files**
   ```.gitignore
   db.sqlite3
   projects/*/dbt_project/
   projects/*/exports/
   ```

---

## See Also

- [configuration.md](configuration.md) - Configuration reference
- [README.md](../README.md) - General usage
