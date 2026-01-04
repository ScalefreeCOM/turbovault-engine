"""
Configuration loader service for TurboVault Engine.

Provides functions to load and validate config.yml files using Pydantic schemas.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic import ValidationError

from engine.services.config_schema import TurboVaultConfig


class ConfigValidationError(Exception):
    """Custom exception for configuration validation errors."""

    def __init__(self, message: str, errors: list[Dict[str, Any]] | None = None):
        super().__init__(message)
        self.errors = errors or []


def load_config_from_path(config_path: Path | str) -> TurboVaultConfig:
    """
    Load and validate TurboVault configuration from a YAML file.

    Args:
        config_path: Path to the config.yml file

    Returns:
        Validated TurboVaultConfig object

    Raises:
        FileNotFoundError: If config file doesn't exist
        ConfigValidationError: If config is invalid or YAML is malformed

    Example:
        >>> config = load_config_from_path("config.yml")
        >>> print(config.project.name)
        'my_project'
    """
    config_path = Path(config_path)

    # Check file exists
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            f"Please create a config.yml file. See config.example.yml for reference."
        )

    # Load YAML
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_dict = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigValidationError(
            f"Failed to parse YAML in {config_path}:\n{str(e)}"
        ) from e
    except Exception as e:
        raise ConfigValidationError(
            f"Failed to read config file {config_path}: {str(e)}"
        ) from e

    # Validate and parse
    return load_config_from_dict(config_dict, source_file=str(config_path))


def load_config_from_dict(
    config_dict: Dict[str, Any], source_file: str | None = None
) -> TurboVaultConfig:
    """
    Load and validate TurboVault configuration from a dictionary.

    Useful for testing or programmatic config creation.

    Args:
        config_dict: Dictionary containing config data
        source_file: Optional source file name for error messages

    Returns:
        Validated TurboVaultConfig object

    Raises:
        ConfigValidationError: If config is invalid

    Example:
        >>> config_dict = {
        ...     "project": {"name": "test"},
        ...     "output": {"dbt_project_dir": "./dbt"}
        ... }
        >>> config = load_config_from_dict(config_dict)
    """
    try:
        config = TurboVaultConfig.model_validate(config_dict)
        return config
    except ValidationError as e:
        # Format validation errors for better readability
        error_messages = []
        for error in e.errors():
            loc = ".".join(str(x) for x in error["loc"])
            msg = error["msg"]
            error_messages.append(f"  - {loc}: {msg}")

        source_info = f" in {source_file}" if source_file else ""
        raise ConfigValidationError(
            f"Configuration validation failed{source_info}:\n"
            + "\n".join(error_messages),
            errors=e.errors(),
        ) from e


def validate_config(config: TurboVaultConfig) -> list[str]:
    """
    Perform additional validation checks on a loaded config.

    Returns a list of warnings (non-fatal issues).

    Args:
        config: Loaded and validated config object

    Returns:
        List of warning messages
    """
    warnings = []

    # Check if source file exists (if Excel source is configured)
    if config.source and hasattr(config.source, "path"):
        if not config.source.path.exists():
            warnings.append(
                f"Source file does not exist: {config.source.path}\n"
                f"  This file will be needed before metadata import."
            )

    # Check if output directory parent exists
    output_dir = config.output.dbt_project_dir
    if not output_dir.parent.exists():
        warnings.append(
            f"Parent directory for dbt project does not exist: {output_dir.parent}\n"
            f"  It will be created during generation."
        )

    return warnings
