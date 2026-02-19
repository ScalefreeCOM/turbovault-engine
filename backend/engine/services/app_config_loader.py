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


def find_turbovault_config() -> Path | None:
    """
    Find the turbovault.yml configuration file.

    Only searches in the current directory - turbovault must be run from
    a turbovault workspace (similar to how Git requires being in a repo).

    Returns:
        Path to turbovault.yml if found in current directory, None otherwise
    """
    # Only check current directory
    cwd_config = Path.cwd() / "turbovault.yml"
    if cwd_config.exists():
        return cwd_config

    return None


def ensure_turbovault_config() -> Path:
    """
    Ensure turbovault.yml exists in current directory, creating it with defaults if not.

    This makes the current directory a "turbovault workspace" - similar to 'git init'.

    Returns:
        Path to the turbovault.yml file
    """
    config_path = find_turbovault_config()

    if config_path is None:
        # Create default config in current directory
        config_path = Path.cwd() / "turbovault.yml"
        logger.info(f"Initializing turbovault workspace in {Path.cwd()}")

        default_config = {
            "database": {"engine": "sqlite3", "name": "db.sqlite3"},
            "project_root": ".",  # Current directory
            "defaults": {"stage_schema": "stage", "rdv_schema": "rdv"},
        }

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(default_config, f, default_flow_style=False, sort_keys=False)

        logger.info(f"Created turbovault.yml in {Path.cwd()}")

    return config_path


def load_application_config() -> ApplicationConfig:
    """
    Load and validate the application configuration from turbovault.yml.

    Returns:
        Validated ApplicationConfig object

    Raises:
        AppConfigError: If config is invalid or cannot be loaded
    """
    config_path = ensure_turbovault_config()

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
