"""
Project configuration and folder management utilities.

Provides functions to initialize project folders, create config.yml files,
and load configurations for projects.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

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
        - {PROJECT_ROOT}/{project_directory}/exports/

    Note:
        exports/dbt_project/, exports/json/, and exports/dbml/ are created
        lazily on first use by the generate command.
    """

    # Determine project directory path (relative to PROJECT_ROOT)
    project_name_slug = project.name.lower().replace(" ", "_").replace("-", "_")
    relative_dir = f"projects/{project_name_slug}"

    # Resolve to absolute path
    project_root = get_project_root()
    project_path = project_root / relative_dir

    logger.info(f"Creating project folder: {project_path}")

    # Create directory structure — only exports/ is created eagerly.
    # dbt_project/, json/, and dbml/ sub-folders are created on first generation.
    project_path.mkdir(parents=True, exist_ok=True)
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
            "bdv_schema": config.configuration.bdv_schema,
            "profile_name": config.configuration.profile_name,
            "control_schema": config.configuration.control_schema,
            "control_materialization": config.configuration.control_materialization,
            "staging_materialization": config.configuration.staging_materialization,
            "raw_vault_materialization": (
                config.configuration.raw_vault_materialization
            ),
            "business_vault_materialization": (
                config.configuration.business_vault_materialization
            ),
            "model_specific_materializations": (
                config.configuration.model_specific_materializations
            ),
        },
        # Output paths are determined by convention (exports/ subfolder).
        # create_zip / export_sources are still project-level preferences.
        "output": {
            "create_zip": config.output.create_zip,
            "export_sources": config.output.export_sources,
        },
    }
    # The dbt project's name, when it isn't the project's (an imported one's)
    if config.output.dbt_project_name and (
        config.output.dbt_project_name != config.project.name
    ):
        config_dict["output"]["dbt_project_name"] = config.output.dbt_project_name

    if config.configuration.model_materializations:
        config_dict["configuration"]["model_materializations"] = dict(
            config.configuration.model_materializations
        )

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
    for pattern_key in (
        "record_tracking_satellite_naming",
        "effectivity_satellite_naming",
        "stage_naming",
        "prestage_naming",
    ):
        if value := getattr(config.configuration, pattern_key):
            config_dict["configuration"][pattern_key] = value

    # Stage options and the delivery method, where they differ from the defaults
    if not config.configuration.include_source_columns:
        config_dict["configuration"]["include_source_columns"] = False
    if not config.configuration.enable_ghost_records:
        config_dict["configuration"]["enable_ghost_records"] = False
    if config.configuration.folders:
        config_dict["configuration"]["folders"] = dict(config.configuration.folders)
    if not config.configuration.use_model_folders:
        config_dict["configuration"]["use_model_folders"] = False
    if not config.configuration.add_default_tags:
        config_dict["configuration"]["add_default_tags"] = False
    if config.configuration.use_delivery_method:
        config_dict["configuration"]["use_delivery_method"] = True
    if config.configuration.delivery_method != "multi_batch":
        config_dict["configuration"][
            "delivery_method"
        ] = config.configuration.delivery_method

    # The dbt project the CLI imports from, and its dbt_project.yml settings
    if config.dbt_project:
        dbt_project: dict = {}
        if config.dbt_project.path is not None:
            dbt_project["path"] = str(config.dbt_project.path)
        for key in ("vars", "models", "settings", "packages"):
            if value := getattr(config.dbt_project, key):
                dbt_project[key] = value
        if dbt_project:
            config_dict["dbt_project"] = dbt_project

    # Add source if present
    if config.source:
        config_dict["source"] = {
            "type": config.source.type.value,
            "path": str(config.source.path),
        }

    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)

    logger.debug(f"Wrote config to {config_path}")


# Where a project setting (a runtime config field) goes in config.yml, when
# not under configuration:.
_SETTING_LOCATIONS: dict[str, tuple[str, ...]] = {
    "dbt_project_name": ("output", "dbt_project_name"),
    "global_vars": ("dbt_project", "vars"),
    "dbt_project_models": ("dbt_project", "models"),
    "dbt_project_settings": ("dbt_project", "settings"),
    "dbt_packages": ("dbt_project", "packages"),
}


def setting_location(key: str) -> tuple[str, ...]:
    """Where a project setting goes in config.yml.

    ``key`` is a runtime config field (``EngineRuntimeConfig``), as an
    import suggests it; a dotted key is an entry of a mapping field
    (``folders.raw_vault`` -> ``configuration.folders.raw_vault``).
    """
    name, _, entry = key.partition(".")
    location = _SETTING_LOCATIONS.get(name, ("configuration", name))
    return (*location, entry) if entry else location


def apply_settings(config_path: Path, values: Mapping[str, Any]) -> None:
    """Write project settings into a config.yml, keeping all else in it.

    ``values`` are keyed like an import's suggested settings
    (``ImportReport.project_settings``, spec D28): see ``setting_location``.
    The result is checked first; an invalid one raises ``ValueError`` (a
    pydantic ``ValidationError``) and leaves the file as it is.
    """
    from engine.services.config_schema import TurboVaultConfig

    document = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    for key, value in values.items():
        *parents, name = setting_location(key)
        node = document
        for parent in parents:
            if not isinstance(node.get(parent), dict):
                node[parent] = {}
            node = node[parent]
        node[name] = copy.deepcopy(value)
    TurboVaultConfig.model_validate(document)
    config_path.write_text(
        yaml.safe_dump(
            document, sort_keys=False, default_flow_style=False, allow_unicode=True
        ),
        encoding="utf-8",
    )


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
                "bdv_schema": app_config.defaults.bdv_schema,
            },
            "output": {
                "create_zip": False,
                "export_sources": True,
            },
        }

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(minimal_config, f, default_flow_style=False)

        logger.info(f"Created minimal config at {config_path}")

    return config_path
