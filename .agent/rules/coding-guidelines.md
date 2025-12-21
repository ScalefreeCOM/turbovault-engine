---
trigger: always_on
---

# Python Style & Coding Guidelines

This rules file defines how **Python code** should be written in the TurboVault Engine repository.  
The goal is to keep the codebase **consistent, readable, and easy to work with for AI + humans**.

These rules apply to all Python files in this project unless explicitly overridden.

---

## 1. Language & General Style

- Use **Python 3.x** (modern features are allowed and encouraged).
- Prefer **explicit, readable code** over clever one-liners.
- Follow **PEP 8** conventions unless otherwise stated.
- New code **must be type-annotated** (see section 2).

Where possible, write code that would be compatible with tools like:

- **black** for formatting,
- **ruff/flake8** for linting,
- **mypy** (or similar) for static type checking.

---

## 2. Type Hints

- All **public functions** and methods must include type hints for:
  - parameters,
  - return values.
- Internal helpers should also be typed whenever it is straightforward to do so.
- Use `from __future__ import annotations` where it makes forward references easier (if applicable).
- Prefer precise types over `Any`:
  - Use `list[str]`, `dict[str, Any]`, `Optional[Foo]`, `Mapping[...]` etc.
- When returning multiple values, prefer:
  - A small typed dataclass or NamedTuple over a raw untyped tuple, when clarity matters.

Example:

```python
def import_metadata(config: Config) -> Project:
    ...
```

and not:
```
def import_metadata(config):
    ...
```

### 3. Imports & Module Structure

Group imports in the following order:
1.  Standard library
2.  Third-party libraries
3.  Local application imports

Use absolute imports within the project, not relative dot imports, unless there is a clear reason.

**Example:**

```python
# Good
import dataclasses
from typing import Any, Optional
import yaml
from django.db import transaction
from engine.models.source import SourceTable
from engine.services.config_loader import Config

# Avoid
from .models import *
from ..services import *
```
* **Do not use** `from module import *`.
* **Keep module responsibilities cohesive:**
    * Models in `engine/models/...`
    * Services in `engine/services/...`
    * CLI wiring in `engine/cli/...`

### 4. Naming Conventions
Use consistent, descriptive names:

* **Modules & files:** `snake_case`, meaningful names (e.g. `config_loader.py`, `generate_dbt.py`).
* **Classes:** `PascalCase` (e.g. `Config`, `DbtProjectBuilder`).
* **Functions & methods:** `snake_case` (e.g. `load_config_from_path`).
* **Variables:** `snake_case` (e.g. `source_tables`, `hub_mappings`).
* **Avoid** vague names like `data`, `obj`, `foo` when a more specific name is available.

**Prefer:**
```python
hub_columns_by_id: dict[int, HubColumn]
```
**Over:**
```python
d = {}
```
## 5. Functions, Methods & Complexity

*   **Keep functions focused and short.**
*   If a function grows too large or starts doing multiple things (e.g. parsing + validation + persistence), split it into smaller helpers.
*   **Avoid deep nesting:**
    *   Use early returns to simplify control flow where appropriate.
*   **Prefer pure functions where possible**, especially in services that:
    *   accept simple inputs,
    *   return values or raise exceptions,
    *   and have minimal side effects aside from well-defined DB operations / file writes.

## 6. Error Handling & Exceptions

*   **Fail early and loudly** for unexpected conditions; don’t silently swallow exceptions.
*   Prefer custom, domain-specific exceptions where helpful, e.g. `ConfigValidationError`, `MetadataImportError`.
*   **Catch exceptions only when:**
    *   you can add meaningful context, or
    *   you can handle/recover properly.
*   When catching exceptions, log or re-raise with context; do not leave `except Exception: pass` patterns.

**Example:**

```python
try:
    config = load_config(path)
except yaml.YAMLError as exc:
    raise ConfigValidationError(f"Invalid YAML in {path}") from exc
```

## 7. Docstrings & Comments

*   **Public functions and classes should have short docstrings that explain:**
    *   what they do,
    *   what arguments they expect,
    *   what they return or raise (if non-obvious).

**Example:**

```python
def generate_dbt_project(project: Project, output: OutputConfig) -> Path:
    """
    Generate a dbt project for the given project and write it to the output path.

    Returns the path to the generated project directory.
    Raises GenerationError if generation fails.
    """
```

*   Use comments to explain **why** something is done, not just **what** is done.
*   Avoid redundant comments that simply restate the code.

## 8. Django & ORM Usage

*   **Models:**
    *   Keep business logic in services, not in model methods, except for simple validation or convenience accessors.
    *   Use explicit fields and relations; avoid generic foreign keys unless absolutely necessary.
    *   Respect the domain model defined in `02_domain_model.md` (field names, relationships, semantics).
*   **Queries:**
    *   Prefer using the ORM over raw SQL when possible.
    *   Keep queries explicit; avoid hidden side effects.
    *   When writing more complex queries, consider adding comments or small helper methods in services.
*   **Transactions:**
    *   Use `transaction.atomic()` for units of work that must succeed or fail together.
    *   Keep transaction blocks as small as possible.

## 9. Configuration & Constants

*   Do not hard-code environment-specific values (paths, secrets, etc.) in code.
*   Use Django settings, environment variables, or configuration objects (e.g. `Config` dataclass) to pass such values.
*   Group related constants logically, e.g. snapshot component names, hub/link types.

**Example:**

```python
class HubType(str, Enum):
    STANDARD = "standard"
    REFERENCE = "reference"
```

## 10. Logging

*   Prefer using Python’s `logging` module over `print` for non-trivial code paths.
*   Use log levels appropriately:
    *   `logging.debug` for detailed internal state,
    *   `logging.info` for high-level process steps (e.g. “Starting metadata import…”),
    *   `logging.warning` / `logging.error` for problems.
*   Logging should be:
    *   helpful for debugging,
    *   not excessively verbose in normal operation.

## 11. CLI-Specific Guidelines

*   CLI commands should:
    *   parse arguments,
    *   call services,
    *   handle success/failure messaging,
    *   exit with appropriate status codes if needed.
*   **Do not place complex business logic or heavy branching directly in CLI commands:**
    *   Extract that into service functions and call them from the CLI layer.

**Example pattern:**

```python
def handle(self, *args: Any, **options: Any) -> None:
    config_path = Path(options["config"])
    config = load_config(config_path)
    project = import_metadata(config)
    generate_dbt_project(project, config.output)
    self.stdout.write(self.style.SUCCESS("Generation completed."))
```

## 12. Code Review Mindset

When generating or modifying code, the assistant should:

*   Prefer small, cohesive changes over large, cross-cutting edits.
*   When asked, self-review generated code:
    *   Check for missing imports,
    *   Check for obvious type mismatches,
    *   Check that function/variable names align with these guidelines.
*   If unsure between multiple patterns, choose the one that:
    *   is easiest to read,
    *   aligns with standard Django/Python practices,
    *   and fits into the existing project structure.