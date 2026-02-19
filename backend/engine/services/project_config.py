"""
Project configuration and folder management utilities.

Provides functions to initialize project folders, create config.yml files,
and load configurations for projects.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from engine.services.app_config_loader import get_project_root, resolve_project_path
from engine.services.config_loader import load_config_from_path

logger = logging.getLogger(__name__)


def initialize_project_folder(project, config) -> Path:
    """
    Create project folder structure and config.yml for a new project.

    Args:
        project: Project model instance
        config: TurboVaultConfig object with project configuration

    Returns:
        Path to the created project directory

    Creates:
        - {PROJECT_ROOT}/{project_directory}/
        - {PROJECT_ROOT}/{project_directory}/config.yml
        - {PROJECT_ROOT}/{project_directory}/dbt_project/ (placeholder)
        - {PROJECT_ROOT}/{project_directory}/exports/ (placeholder)
    """

    # Determine project directory path (relative to PROJECT_ROOT)
    project_name_slug = project.name.lower().replace(" ", "_").replace("-", "_")
    relative_dir = f"projects/{project_name_slug}"

    # Resolve to absolute path
    project_root = get_project_root()
    project_path = project_root / relative_dir

    logger.info(f"Creating project folder: {project_path}")

    # Create directory structure
    project_path.mkdir(parents=True, exist_ok=True)
    (project_path / "dbt_project").mkdir(exist_ok=True)
    (project_path / "exports").mkdir(exist_ok=True)

    # Create config.yml from the loaded config
    config_path = project_path / "config.yml"
    write_project_config(config_path, config)

    # Update project with directory path
    project.project_directory = relative_dir
    project.save()

    logger.info(f"✓ Project folder created at: {project_path}")
    logger.info(f"✓ Config saved to: {config_path}")

    return project_path


def write_project_config(config_path: Path, config) -> None:
    """
    Write a TurboVaultConfig to a config.yml file.

    Args:
        config_path: Path where config.yml should be written
        config: TurboVaultConfig object to serialize
    """
    config_dict = {
        "project": {
            "name": config.project.name,
            "description": config.project.description or "",
        },
        "configuration": {
            "stage_schema": config.configuration.stage_schema,
            "rdv_schema": config.configuration.rdv_schema,
        },
        "output": {
            "dbt_project_dir": str(config.output.dbt_project_dir),
            "create_zip": config.output.create_zip,
            "export_sources": config.output.export_sources,
        },
    }

    # Add optional fields if present
    if config.configuration.stage_database:
        config_dict["configuration"][
            "stage_database"
        ] = config.configuration.stage_database
    if config.configuration.rdv_database:
        config_dict["configuration"]["rdv_database"] = config.configuration.rdv_database

    # Add naming patterns if defined
    if config.configuration.hashdiff_naming:
        config_dict["configuration"][
            "hashdiff_naming"
        ] = config.configuration.hashdiff_naming
    if config.configuration.hashkey_naming:
        config_dict["configuration"][
            "hashkey_naming"
        ] = config.configuration.hashkey_naming
    if config.configuration.satellite_v0_naming:
        config_dict["configuration"][
            "satellite_v0_naming"
        ] = config.configuration.satellite_v0_naming
    if config.configuration.satellite_v1_naming:
        config_dict["configuration"][
            "satellite_v1_naming"
        ] = config.configuration.satellite_v1_naming

    # Add source if present
    if config.source:
        config_dict["source"] = {
            "type": config.source.type,
            "path": str(config.source.path),
        }

    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)

    logger.debug(f"Wrote config to {config_path}")


def load_project_config(project):
    """
    Load configuration for a project from its config.yml.

    Args:
        project: Project model instance

    Returns:
        TurboVaultConfig: Validated project configuration

    Raises:
        FileNotFoundError: If config.yml doesn't exist
        ConfigValidationError: If config is invalid
    """
    config_path = project.get_config_path()
    return load_config_from_path(config_path)


def get_project_config_path(project) -> Path:
    """
    Get absolute path to a project's config.yml.

    Args:
        project: Project model instance

    Returns:
        Absolute path to config.yml
    """
    if not project.project_directory:
        raise ValueError(
            f"Project '{project.name}' has no project_directory set. "
            "Cannot locate config.yml."
        )

    project_path = resolve_project_path(project.project_directory)
    return project_path / "config.yml"


def ensure_project_config_exists(project) -> Path:
    """
    Ensure project config.yml exists, creating a minimal one if not.

    This is used for auto-repair when a project exists in DB but
    config.yml is missing.

    Args:
        project: Project model instance

    Returns:
        Path to config.yml (created if necessary)
    """
    config_path = get_project_config_path(project)

    if not config_path.exists():
        # Auto-repair: Create minimal config from project name/description
        logger.warning(f"Auto-creating missing config.yml for project '{project.name}'")

        project_path = config_path.parent
        project_path.mkdir(parents=True, exist_ok=True)

        # Load defaults from global config
        from engine.services.app_config_loader import load_application_config

        app_config = load_application_config()

        minimal_config = {
            "project": {
                "name": project.name,
                "description": project.description or "",
            },
            "configuration": {
                "stage_schema": app_config.defaults.stage_schema,
                "rdv_schema": app_config.defaults.rdv_schema,
            },
            "output": {"dbt_project_dir": "./dbt_project"},
        }

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(minimal_config, f, default_flow_style=False)

        logger.info(f"Created minimal config at {config_path}")

    return config_path
