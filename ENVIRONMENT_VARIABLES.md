# Environment Variables

TurboVault Engine supports the following environment variables for configuration and behavior control.

---

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

Skip the automatic creation of default snapshot control entries when initializing a new project.

**What gets created by default:**
- Snapshot control table with name `control_snap_v0`
- 5 snapshot logic patterns per project:
  - **Daily** - 1 day duration snapshots
  - **Weekly** - 7 day duration (end of week)
  - **Monthly** - 1 month duration (end of month)
  - **Quarterly** - 3 month duration (end of quarter)
  - **Yearly** - 1 year duration (end of year)

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
- Testing environments

---

### `TURBOVAULT_SKIP_TEMPLATE_POPULATION`

**Type:** Boolean (`1`, `true`, `yes`, or empty)  
**Default:** Empty (templates populated automatically)

Skip the automatic population of template files into the database during project initialization.

**What gets populated by default:**
- All SQL templates (16 entity types)
- All YAML schema templates (16 entity types)
- Templates are combined (SQL + YAML in same record)
- Total: 16 `ModelTemplate` records created

**Usage:**
```bash
# Skip template population
export TURBOVAULT_SKIP_TEMPLATE_POPULATION=1
turbovault init --config config.yml

# Or inline
TURBOVAULT_SKIP_TEMPLATE_POPULATION=true turbovault init --interactive
```

**When to use:**
- When templates are already populated in the database
- Custom template management workflows
- CI/CD environments where templates are pre-configured
- Testing scenarios

**Manual template population:**
```bash
cd backend
python manage.py populate_templates

# Overwrite existing
python manage.py populate_templates --overwrite
```

---

## Generation Behavior

### `TURBOVAULT_DEFAULT_VALIDATION_MODE`

**Type:** String (`strict` or `lenient`)  
**Default:** `strict`

Set the default validation mode for the `generate` command.

**Values:**
- `strict` - Stop on first validation error
- `lenient` - Skip invalid entities, continue with valid ones

**Usage:**
```bash
# Set lenient as default
export TURBOVAULT_DEFAULT_VALIDATION_MODE=lenient
turbovault generate --project my_project
# (uses lenient mode by default)

# Override via CLI option
turbovault generate --project my_project --mode strict
# (uses strict mode despite environment variable)
```

**When to use:**
- Development environments where you want to generate what works
- Incremental modeling workflows
- When you know certain entities are incomplete

---

## Django Configuration

### `DJANGO_SETTINGS_MODULE`

**Type:** String  
**Default:** `turbovault.settings`

Override the Django settings module (advanced usage).

**Usage:**
```bash
# Use custom settings
export DJANGO_SETTINGS_MODULE=turbovault.settings_production
turbovault serve
```

**When to use:**
- Custom Django settings for production/staging
- Multiple environment configurations
- Advanced deployment scenarios

---

## Development & Testing

### `TURBOVAULT_DEBUG`

**Type:** Boolean (`1`, `true`, `yes`, or empty)  
**Default:** Empty (debug disabled)

Enable debug mode with verbose logging and error details.

**Usage:**
```bash
# Enable debug mode
export TURBOVAULT_DEBUG=1
turbovault generate --project my_project
```

**When to use:**
- Troubleshooting generation issues
- Template debugging
- Development and testing

**Effects:**
- More verbose console output
- Detailed error stack traces
- Template rendering details
- SQL model generation logs

---

## Complete Examples

### CI/CD Pipeline Configuration

```bash
#!/bin/bash
# CI/CD script for TurboVault

# Skip interactive prompts
export TURBOVAULT_SKIP_SUPERUSER_PROMPT=1

# Templates already in database
export TURBOVAULT_SKIP_TEMPLATE_POPULATION=1

# Strict validation for production
export TURBOVAULT_DEFAULT_VALIDATION_MODE=strict

# Initialize and generate
turbovault init --config config.yml
turbovault generate --project production_datavault --zip

# Deploy generated ZIP
./deploy.sh output/production_datavault.zip
```

### Development Environment

```bash
#!/bin/bash
# Local development setup

# Create admin user interactively
unset TURBOVAULT_SKIP_SUPERUSER_PROMPT

# Create default snapshots
unset TURBOVAULT_SKIP_DEFAULT_SNAPSHOTS

# Populate templates
unset TURBOVAULT_SKIP_TEMPLATE_POPULATION

# Lenient validation for rapid iteration
export TURBOVAULT_DEFAULT_VALIDATION_MODE=lenient

# Enable debug mode
export TURBOVAULT_DEBUG=1

# Initialize project
turbovault init --interactive

# Start admin
turbovault serve --port 8000
```

### Testing Environment

```bash
#!/bin/bash
# Test suite setup

# Skip all interactive prompts
export TURBOVAULT_SKIP_SUPERUSER_PROMPT=1
export TURBOVAULT_SKIP_DEFAULT_SNAPSHOTS=1
export TURBOVAULT_SKIP_TEMPLATE_POPULATION=1

# Strict validation for tests
export TURBOVAULT_DEFAULT_VALIDATION_MODE=strict

# Run tests
pytest backend/tests/ -v
```

---

## Environment Variable Priority

When multiple configuration sources exist, priority is (highest to lowest):

1. **CLI arguments** (e.g., `--mode strict`)
2. **Environment variables** (e.g., `TURBOVAULT_DEFAULT_VALIDATION_MODE=lenient`)
3. **Default values** (built-in defaults)

**Example:**
```bash
# Environment says lenient
export TURBOVAULT_DEFAULT_VALIDATION_MODE=lenient

# But CLI overrides to strict
turbovault generate --project my_project --mode strict
# Result: Uses strict mode
```

---

## Best Practices

### Production Deployments

```bash
# Use strict validation
export TURBOVAULT_DEFAULT_VALIDATION_MODE=strict

# Skip interactive prompts
export TURBOVAULT_SKIP_SUPERUSER_PROMPT=1

# Templates pre-configured in database
export TURBOVAULT_SKIP_TEMPLATE_POPULATION=1
```

### Local Development

```bash
# Allow interactive prompts
unset TURBOVAULT_SKIP_SUPERUSER_PROMPT

# Create defaults
unset TURBOVAULT_SKIP_DEFAULT_SNAPSHOTS
unset TURBOVAULT_SKIP_TEMPLATE_POPULATION

# Lenient mode for iteration
export TURBOVAULT_DEFAULT_VALIDATION_MODE=lenient

# Debug enabled
export TURBOVAULT_DEBUG=1
```

### Automated Testing

```bash
# Skip all prompts
export TURBOVAULT_SKIP_SUPERUSER_PROMPT=1
export TURBOVAULT_SKIP_DEFAULT_SNAPSHOTS=1
export TURBOVAULT_SKIP_TEMPLATE_POPULATION=1

# Strict validation
export TURBOVAULT_DEFAULT_VALIDATION_MODE=strict
```

---

## Summary Table

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `TURBOVAULT_SKIP_SUPERUSER_PROMPT` | Boolean | Empty | Skip admin user creation prompt |
| `TURBOVAULT_SKIP_DEFAULT_SNAPSHOTS` | Boolean | Empty | Skip snapshot control creation |
| `TURBOVAULT_SKIP_TEMPLATE_POPULATION` | Boolean | Empty | Skip template population |
| `TURBOVAULT_DEFAULT_VALIDATION_MODE` | String | `strict` | Default validation mode |
| `TURBOVAULT_DEBUG` | Boolean | Empty | Enable debug mode |
| `DJANGO_SETTINGS_MODULE` | String | `turbovault.settings` | Django settings module |

---

## See Also

- [CLI Guide](CLI_GUIDE.md) - Complete CLI documentation
- [README](README.md) - Project overview
- [dbt Generation Guide](docs/06_dbt_generation.md) - Generation documentation
