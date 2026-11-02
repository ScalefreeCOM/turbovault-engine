"""
SQLMesh dialect helpers.

The dialect is rendered into both ``config.yaml`` (``model_defaults.dialect``
and the gateway ``connection.type``) and ``config.json`` (datavault4sqlmesh).
``config.json`` is rewritten on every run, but ``config.yaml`` is write-once
so filled-in connection details are never lost. That means re-generating with
a different dialect can leave the two files disagreeing; this module detects
that case so callers can warn instead of silently producing a broken project.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from engine.services.generation.errors import Code, make_issue
from engine.services.generation.types import Issue

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
            f"config.json now uses '{dialect}'."
        ),
        suggestion=(
            f"Edit {config_yaml_path}: set model_defaults.dialect (and the gateway "
            f"connection type) to '{dialect}', or delete the file and re-generate."
        ),
    )
