"""
Folder configuration for dbt project generation.

Defines the directory structure for generated dbt projects and provides
utilities for creating folders and resolving paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class FolderConfig:
    """
    Configuration for dbt project folder structure.

    Defines paths for all model layers and provides methods to resolve
    entity paths based on group membership.
    """

    # Base paths for each layer
    staging_path: str = "models/staging"
    raw_vault_path: str = "models/raw_vault"
    business_vault_path: str = "models/business_vault"
    control_path: str = "models/control"

    # Business vault subdirectories
    pits_subdir: str = "pits"
    reference_tables_subdir: str = "reference_tables"

    def get_staging_path(self, source_system: str, output_root: Path) -> Path:
        """
        Get the path for staging models of a source system.

        Args:
            source_system: Source system name (sanitized for filesystem)
            output_root: Root directory of the dbt project

        Returns:
            Path to the staging subdirectory for this source system.
        """
        system_name = self._sanitize_name(source_system)
        return output_root / self.staging_path / system_name

    def get_staging_base_path(self, output_root: Path) -> Path:
        """Get the base staging directory path."""
        return output_root / self.staging_path

    def get_raw_vault_path(self, group: str | None, output_root: Path) -> Path:
        """
        Get the path for raw vault models.

        Args:
            group: Optional group name. If None, entities go in base folder.
            output_root: Root directory of the dbt project

        Returns:
            Path to the raw vault directory (with group subdirectory if applicable).
        """
        base = output_root / self.raw_vault_path
        if group:
            return base / self._sanitize_name(group)
        return base

    def get_business_vault_pits_path(self, output_root: Path) -> Path:
        """Get the path for PIT models."""
        return output_root / self.business_vault_path / self.pits_subdir

    def get_business_vault_reference_tables_path(self, output_root: Path) -> Path:
        """Get the path for reference table models."""
        return output_root / self.business_vault_path / self.reference_tables_subdir

    def get_control_path(self, output_root: Path) -> Path:
        """Get the path for control models (snapshot control)."""
        return output_root / self.control_path

    def create_project_structure(self, output_root: Path) -> None:
        """
        Create the complete dbt project directory structure.

        Args:
            output_root: Root directory for the dbt project.
        """
        # Core directories
        directories = [
            output_root / self.staging_path,
            output_root / self.raw_vault_path,
            output_root / self.business_vault_path / self.pits_subdir,
            output_root / self.business_vault_path / self.reference_tables_subdir,
            output_root / self.control_path,
            output_root / "macros",
            output_root / "tests",
            output_root / "seeds",
            output_root / "analyses",
            output_root / "snapshots",
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def ensure_path_exists(self, path: Path) -> None:
        """Ensure a directory path exists, creating it if necessary."""
        path.mkdir(parents=True, exist_ok=True)

    def _sanitize_name(self, name: str) -> str:
        """
        Sanitize a name for use in filesystem paths.

        Converts to lowercase and replaces spaces with underscores.
        """
        return name.lower().replace(" ", "_").replace("-", "_")


@dataclass
class GenerationConfig:
    """
    Configuration options for dbt project generation.

    Controls behavior like satellite v1 view generation and validation mode.
    """

    # Folder structure configuration
    folder_config: FolderConfig = field(default_factory=FolderConfig)

    # Satellite v0/v1 generation
    generate_satellite_v1_views: bool = True
    satellite_v0_suffix: str = "_v0"
    satellite_v1_suffix: str = "_v1"

    # Validation mode
    mode: Literal["strict", "lenient"] = "strict"
    skip_validation: bool = False

    # Output options
    create_zip: bool = False

    # Project metadata
    project_name: str = "turbovault_project"
    profile_name: str = "default"


def get_model_filename(
    entity_name: str, suffix: str = "", extension: str = "sql"
) -> str:
    """
    Generate a model filename from entity name.

    Args:
        entity_name: Name of the entity (hub, link, satellite, etc.)
        suffix: Optional suffix (e.g., '_v0', '_v1')
        extension: File extension (default 'sql')

    Returns:
        Filename string.
    """
    return f"{entity_name}{suffix}.{extension}"
