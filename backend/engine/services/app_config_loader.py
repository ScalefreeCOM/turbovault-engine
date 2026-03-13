"""
Application configuration loader for TurboVault Engine.

Provides functions to load and manage the global turbovault.yml configuration.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from engine.services.app_config_schema import ApplicationConfig

logger = logging.getLogger(__name__)


class AppConfigError(Exception):
    """Exception raised for application configuration errors."""

    pass


class WorkspaceNotFoundError(AppConfigError):
    """Raised when a command is run outside a TurboVault workspace."""

    pass


def find_turbovault_config() -> Path | None:
    """
    Find the turbovault.yml configuration file.

    Search order:
      1. ``TURBOVAULT_CONFIG_PATH`` environment variable (absolute path to
         turbovault.yml) — used by ``turbovault serve`` to pass the workspace
         path to the Django subprocess without changing its working directory.
      2. Current working directory — the standard interactive case.

    Returns:
        Path to turbovault.yml if found, None otherwise
    """
    import os

    env_path = os.environ.get("TURBOVAULT_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        logger.warning(
            "TURBOVAULT_CONFIG_PATH is set to '%s' but the file does not exist.",
            env_path,
        )

    cwd_config = Path.cwd() / "turbovault.yml"
    if cwd_config.exists():
        return cwd_config
    return None


def require_workspace() -> Path:
    """
    Assert that the current directory is a TurboVault workspace.

    Raises WorkspaceNotFoundError with a clear, actionable message if
    turbovault.yml is not found so that every CLI command can guard
    itself with a single call at the top.

    Returns:
        Absolute path to turbovault.yml

    Raises:
        WorkspaceNotFoundError: If turbovault.yml is not found in cwd
    """
    config_path = find_turbovault_config()
    if config_path is None:
        raise WorkspaceNotFoundError(
            f"Not a TurboVault workspace!\n\n"
            f"  No turbovault.yml found in {Path.cwd()}\n\n"
            f"  Run 'turbovault workspace init' to initialise this directory as a workspace."
        )
    return config_path


def create_workspace_config(
    *,
    db_engine: str = "sqlite3",
    db_name: str = "db.sqlite3",
    db_host: str | None = None,
    db_port: int | None = None,
    db_user: str | None = None,
    db_password: str | None = None,
    stage_schema: str = "stage",
    rdv_schema: str = "rdv",
    bdv_schema: str = "bdv",
    overwrite: bool = False,
) -> Path:
    """
    Create turbovault.yml in the current directory from explicit parameters.

    This is the entry point for 'turbovault workspace init'. It does NOT
    initialise the database — that is done separately by initialise_workspace_db().

    Args:
        db_engine: Database engine (sqlite3, postgresql, mysql, mssql, snowflake)
        db_name: Database name or file path for SQLite
        db_host: Database host (non-SQLite only)
        db_port: Database port (non-SQLite only)
        db_user: Database user (non-SQLite only)
        db_password: Database password (non-SQLite only)
        stage_schema: Default staging schema name
        rdv_schema: Default raw vault schema name
        bdv_schema: Default business vault schema name
        overwrite: If True, overwrite existing turbovault.yml

    Returns:
        Path to the created turbovault.yml

    Raises:
        AppConfigError: If turbovault.yml already exists and overwrite=False
    """
    config_path = Path.cwd() / "turbovault.yml"

    if config_path.exists() and not overwrite:
        raise AppConfigError(
            f"turbovault.yml already exists in {Path.cwd()}. "
            "Use --overwrite to replace it."
        )

    config_dict: dict = {
        "database": {"engine": db_engine, "name": db_name},
        "defaults": {
            "stage_schema": stage_schema,
            "rdv_schema": rdv_schema,
            "bdv_schema": bdv_schema,
        },
    }

    if db_engine != "sqlite3":
        if db_host:
            config_dict["database"]["host"] = db_host
        if db_port:
            config_dict["database"]["port"] = db_port
        if db_user:
            config_dict["database"]["user"] = db_user
        if db_password:
            config_dict["database"]["password"] = db_password

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Created turbovault.yml in {Path.cwd()}")
    return config_path


def load_application_config() -> ApplicationConfig:
    """
    Load and validate the application configuration from turbovault.yml.

    Loads from the current directory only. Call require_workspace() first
    if you want a clear error when not in a workspace.

    Returns:
        Validated ApplicationConfig object

    Raises:
        AppConfigError: If config is invalid or cannot be loaded
    """
    config_path = find_turbovault_config()
    if config_path is None:
        # Fallback: use defaults (no turbovault.yml present — settings.py path)
        return ApplicationConfig()

    try:
        with open(config_path, encoding="utf-8") as f:
            config_dict = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise AppConfigError(
            f"Failed to parse turbovault.yml at {config_path}:\n{str(e)}"
        ) from e
    except Exception as e:
        raise AppConfigError(
            f"Failed to read turbovault.yml at {config_path}: {str(e)}"
        ) from e

    try:
        config = ApplicationConfig.model_validate(config_dict)
        return config
    except ValidationError as e:
        error_messages = []
        for error in e.errors():
            loc = ".".join(str(x) for x in error["loc"])
            msg = error["msg"]
            error_messages.append(f"  - {loc}: {msg}")

        raise AppConfigError(
            f"turbovault.yml validation failed at {config_path}:\n"
            + "\n".join(error_messages)
        ) from e


def get_project_root() -> Path:
    """
    Get the absolute project root path.

    Returns the project_root from turbovault.yml, or the directory
    containing turbovault.yml if not specified.

    Returns:
        Absolute path to the project root directory
    """
    config = load_application_config()

    if config.project_root:
        return Path(config.project_root).resolve()

    # Default: directory containing turbovault.yml
    config_path = find_turbovault_config()
    if config_path:
        return config_path.parent.resolve()

    # Fallback to current directory
    return Path.cwd().resolve()


def resolve_project_path(project_directory: str) -> Path:
    """
    Resolve a project's absolute directory path.

    Combines PROJECT_ROOT with the relative project_directory.

    Args:
        project_directory: Relative path to project directory (e.g., "projects/customer_mdm")

    Returns:
        Absolute path to the project directory
    """
    project_root = get_project_root()
    return project_root / project_directory
