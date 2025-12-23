# Environment Variables

TurboVault Engine supports the following environment variables for configuration:

## Database & Setup

### `TURBOVAULT_SKIP_SUPERUSER_PROMPT`

**Type:** Boolean (`1`, `true`, `yes`, or empty)  
**Default:** Empty (prompts enabled)

Skip the automatic admin user creation prompt on first database initialization.

**Usage:**
```bash
# Skip admin user prompt
export TURBOVAULT_SKIP_SUPERUSER_PROMPT=1
turbovault init --config config.yml

# Or inline
TURBOVAULT_SKIP_SUPERUSER_PROMPT=true turbovault init --interactive
```

**When to use:**
- CI/CD pipelines where interactive prompts are not available
- Automated scripts
- When you want to create the admin user manually later

**Creating admin user manually:**
```bash
cd backend
python manage.py createsuperuser
```

---

### `TURBOVAULT_SKIP_DEFAULT_SNAPSHOTS`

**Type:** Boolean (`1`, `true`, `yes`, or empty)  
**Default:** Empty (default snapshots created)

Skip the automatic creation of default snapshot control entries on first database initialization.

**What gets created by default:**
- Global snapshot control table (`global_snapshot_control`)
- 6 snapshot logic patterns:
  - **Daily** - 1 day snapshots
  - **Weekly** - 7 day snapshots
  - **Monthly** - 1 month snapshots
  - **Quarterly** - 3 month snapshots
  - **Yearly** - 1 year snapshots
  - **Forever** - Infinite duration snapshots

**Usage:**
```bash
# Skip default snapshot creation
export TURBOVAULT_SKIP_DEFAULT_SNAPSHOTS=1
turbovault init --config config.yml

# Or inline
TURBOVAULT_SKIP_DEFAULT_SNAPSHOTS=true turbovault init --interactive
```

**When to use:**
- When you want to define custom snapshot controls from scratch
- CI/CD environments with pre-existing snapshot configurations
- Projects that don't use snapshot-based modeling

---

## Future Environment Variables

More environment variables will be added as the project grows:
- Database connection overrides
- Logging levels
- Export behavior configuration
