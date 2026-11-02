"""
SQLMesh dialect helpers.

The dialect is rendered into ``config.yaml`` (``model_defaults.dialect`` and
the gateway ``connection.type``), ``config.json`` (datavault4sqlmesh) and the
driver line of ``requirements.txt``. All three files are write-once so users'
edits are never lost. Re-generating with other settings therefore leaves them
as they were; this module detects kept files that disagree with the current
run so callers can warn instead of silently producing a broken project.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from engine.services.generation.errors import Code, make_issue
from engine.services.generation.types import Issue

if TYPE_CHECKING:
    from engine.services.runtime_config import EngineRuntimeConfig

logger = logging.getLogger(__name__)

# Dialects TurboVault documents as supported for SQLMesh output.
SQLMESH_DIALECTS: tuple[str, ...] = (
    "duckdb",
    "postgres",
    "snowflake",
    "databricks",
    "trino",
    "bigquery",
)

CONFIG_YAML_DIALECT_MISMATCH = "write.sqlmesh.config_yaml_dialect_mismatch"

# SQLMesh extra that installs the database driver for each supported dialect.
# DuckDB ships with SQLMesh itself, so it needs no extra.
_SQLMESH_DRIVER_EXTRAS: dict[str, str] = {
    "postgres": "postgres",
    "snowflake": "snowflake",
    "databricks": "databricks",
    "trino": "trino",
    "bigquery": "bigquery",
}

# Dialect names as SQLMesh / sqlglot spell them: lowercase letters, digits, underscores.
_DIALECT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# Value that means "no dialect" (CLI `--dialect none`); not a SQLMesh dialect.
NO_DIALECT = "none"


def is_valid_dialect_name(name: str) -> bool:
    """Return True if *name* is shaped like a SQLMesh dialect name (e.g. ``mssql``)."""
    return name != NO_DIALECT and bool(_DIALECT_NAME_RE.match(name))


def default_driver_requirement(dialect: str | None) -> str | None:
    """
    Return the requirements.txt line that installs *dialect*'s database driver.

    Returns ``sqlmesh[<extra>]`` for the supported dialects that need a driver,
    and None for DuckDB (bundled with SQLMesh), dialects without a known extra,
    or no dialect.
    """
    extra = _SQLMESH_DRIVER_EXTRAS.get(dialect) if dialect else None
    return f"sqlmesh[{extra}]" if extra else None


def dialect_not_set_warning() -> Issue:
    """Warning for a SQLMesh project generated without a dialect."""
    return make_issue(
        severity="warning",
        code=Code.SQLMESH_DIALECT_NOT_SET,
        stage="render",
        message=(
            "No SQL dialect set: the SQLMesh project is not runnable until you fill "
            "in the dialect in config.yaml (model_defaults.dialect, connection type) "
            "and config.json, and a database driver in requirements.txt."
        ),
        suggestion=(
            "Set model_defaults.dialect and the gateway connection type in "
            "config.yaml, add \"dialect\" to config.json, and add your database "
            "driver (e.g. sqlmesh[postgres]) to requirements.txt."
        ),
    )


def choose_requirement(
    *,
    dialect: str | None,
    configured_dialect: str | None,
    configured_requirement: str | None,
    explicit_requirement: str | None,
) -> str | None:
    """
    Pick the requirement setting for a generation run.

    An explicit requirement (CLI flag or manual entry) always wins. The
    project's configured requirement only applies while the configured
    dialect is kept, so switching dialect never carries over another
    dialect's driver. None means "derive from the dialect".
    """
    if explicit_requirement is not None:
        return explicit_requirement
    if dialect == configured_dialect:
        return configured_requirement
    return None


def resolve_driver_requirement(dialect: str | None, requirement: str | None) -> str | None:
    """
    Return the driver requirement line to write, or None for no line.

    *requirement* is the user's explicit choice: None means "use the default
    for the dialect", an empty string means "no driver line".
    """
    if requirement is None:
        return default_driver_requirement(dialect)
    return requirement.strip() or None


def read_config_yaml_dialect(config_yaml_path: Path) -> str | None:
    """
    Return ``model_defaults.dialect`` from an existing SQLMesh config.yaml.

    Returns None when the file is missing, unparseable, or has no dialect.
    """
    if not config_yaml_path.is_file():
        return None
    try:
        parsed = yaml.safe_load(config_yaml_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Could not read %s: %s", config_yaml_path, exc)
        return None
    if not isinstance(parsed, dict):
        return None
    model_defaults = parsed.get("model_defaults")
    if not isinstance(model_defaults, dict):
        return None
    dialect = model_defaults.get("dialect")
    return str(dialect) if dialect is not None else None


REQUIREMENTS_DRIVER_MISSING = "write.sqlmesh.requirements_driver_missing"


CONFIG_JSON_KEPT_DIFFERS = "write.sqlmesh.config_json_kept_differs"


def check_kept_scaffold_files(
    output_path: Path,
    runtime_config: EngineRuntimeConfig,
    rendered_config_json: str | None,
) -> list[Issue]:
    """
    Check existing write-once scaffold files against this run's settings.

    config.yaml, config.json and requirements.txt are never overwritten. Call
    this *before* writing: it returns warnings for files that already exist
    and disagree with what this run would have generated.
    """
    dialect = runtime_config.sqlmesh_dialect
    driver = resolve_driver_requirement(dialect, runtime_config.sqlmesh_requirement)
    checks = (
        check_config_yaml_dialect(output_path, dialect),
        check_config_json_kept(output_path, rendered_config_json),
        check_requirements_driver(output_path, driver),
    )
    return [issue for issue in checks if issue is not None]


def check_config_json_kept(output_path: Path, rendered: str | None) -> Issue | None:
    """
    Warn when an existing config.json differs from the *rendered* one.

    Only keys this run would write are compared, so keys the user added by
    hand don't trigger the warning. Returns None when the file is missing,
    unreadable, or matches.
    """
    config_json_path = output_path / "config.json"
    if rendered is None or not config_json_path.is_file():
        return None
    try:
        existing = json.loads(config_json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Could not read %s: %s", config_json_path, exc)
        return None
    expected = json.loads(rendered)
    if not isinstance(existing, dict):
        existing = {}
    differing = sorted(k for k, v in expected.items() if existing.get(k) != v)
    if not differing:
        return None
    return make_issue(
        severity="warning",
        code=CONFIG_JSON_KEPT_DIFFERS,
        stage="write",
        message=(
            "config.json already exists and was kept; it differs from the current "
            f"settings in: {', '.join(differing)}."
        ),
        suggestion=(
            f"Update {config_json_path} by hand, or delete it and re-generate."
        ),
    )


def check_requirements_driver(output_path: Path, driver: str | None) -> Issue | None:
    """
    Warn when an existing requirements.txt lacks the *driver* line.

    requirements.txt is write-once, so a project re-generated for another
    dialect keeps its old driver. Returns a warning Issue in that case,
    otherwise None (also when no driver is needed or the file is missing).
    """
    requirements_path = output_path / "requirements.txt"
    if not driver or not requirements_path.is_file():
        return None
    try:
        lines = requirements_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("Could not read %s: %s", requirements_path, exc)
        return None
    if driver in (line.strip() for line in lines):
        return None
    return make_issue(
        severity="warning",
        code=REQUIREMENTS_DRIVER_MISSING,
        stage="write",
        message=(
            f"requirements.txt already exists and was kept; it does not list the "
            f"driver '{driver}' for this dialect."
        ),
        suggestion=f"Add '{driver}' to {requirements_path}, or delete the file and re-generate.",
    )


def check_config_yaml_dialect(output_path: Path, dialect: str | None) -> Issue | None:
    """
    Warn when an existing config.yaml uses a different dialect than *dialect*.

    *output_path* is the SQLMesh project root. Returns a warning Issue on
    mismatch, otherwise None. Without a dialect there is nothing to compare.
    """
    if dialect is None:
        return None
    config_yaml_path = output_path / "config.yaml"
    existing = read_config_yaml_dialect(config_yaml_path)
    if existing is None or existing == dialect:
        return None
    return make_issue(
        severity="warning",
        code=CONFIG_YAML_DIALECT_MISMATCH,
        stage="write",
        message=(
            f"config.yaml already exists with dialect '{existing}' and was kept; "
            f"this run uses '{dialect}'."
        ),
        suggestion=(
            f"Edit {config_yaml_path}: set model_defaults.dialect (and the gateway "
            f"connection type) to '{dialect}', or delete the file and re-generate."
        ),
    )
