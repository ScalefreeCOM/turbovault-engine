"""
Folder configuration for dbt project generation.

Defines the directory structure for generated dbt projects and provides
utilities for creating folders and resolving paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal


@dataclass
class FolderConfig:
    """
    Configuration for dbt project folder structure.

    Defines paths for all model layers and provides methods to resolve
    entity paths based on group membership.
    """

    # Base paths for each layer
    control_path: str = "models/00_control"
    source_path: str = "models/01_sources"
    staging_path: str = "models/02_staging"
    raw_vault_path: str = "models/03_raw_vault"
    business_vault_path: str = "models/04_business_vault"

    # Business vault subdirectories
    pits_subdir: str = "pits"

    def source_file(self, source_system: str) -> PurePosixPath:
        """Path of a source system's sources YAML, relative to the project root."""
        return (
            PurePosixPath(self.source_path)
            / f"source__{self.sanitize_name(source_system)}.yml"
        )

    def staging_dir(self, source_system: str) -> PurePosixPath:
        """Folder of a source system's stage models, relative to the project root."""
        return PurePosixPath(self.staging_path) / self.sanitize_name(source_system)

    def raw_vault_dir(self, group: str | None) -> PurePosixPath:
        """Folder of raw vault models, in a subfolder per group if given."""
        base = PurePosixPath(self.raw_vault_path)
        return base / self.sanitize_name(group) if group else base

    def pits_dir(self, group: str | None) -> PurePosixPath:
        """Folder of PIT models, in a subfolder per group if given."""
        base = PurePosixPath(self.business_vault_path) / self.pits_subdir
        return base / self.sanitize_name(group) if group else base

    def control_dir(self) -> PurePosixPath:
        """Folder of the snapshot control models."""
        return PurePosixPath(self.control_path)

    def layer_dir(self, layer: str) -> PurePosixPath:
        """The folder of a layer, as configured in dbt_project.yml.

        Raises KeyError for an unknown layer.
        """
        return PurePosixPath(
            {
                "staging": self.staging_path,
                "raw_vault": self.raw_vault_path,
                "business_vault": self.business_vault_path,
                "control": self.control_path,
            }[layer]
        )

    def create_project_structure(self, output_root: Path) -> None:
        """
        Create the complete dbt project directory structure.

        Args:
            output_root: Root directory for the dbt project.
        """
        # Core directories
        directories = [
            output_root / self.source_path,
            output_root / self.staging_path,
            output_root / self.raw_vault_path,
            output_root / self.business_vault_path / self.pits_subdir,
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

    def sanitize_name(self, name: str) -> str:
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
    satellite_v0_naming: str = "[[ satellite_name ]]_v0"
    satellite_v1_naming: str = "[[ satellite_name ]]_v1"
    record_tracking_satellite_naming: str = "[[ satellite_name ]]_ts"
    effectivity_satellite_naming: str = "[[ satellite_name ]]_es"

    # Write models with their stored output attributes (file path, model name,
    # config), e.g. those of the project they were imported from. Off: every
    # model gets Turbovault's standard folders and naming patterns.
    use_original_paths: bool = True

    # Schemas
    stage_schema: str = "stage"
    rdv_schema: str = "rdv"
    bdv_schema: str = "bdv"

    def resolve_entity_name(self, pattern: str, entity_name: str) -> str:
        """Resolve a naming pattern with placeholder replacement."""
        return pattern.replace("[[ entity_name ]]", entity_name).replace(
            "[[ satellite_name ]]", entity_name
        )

    # Validation mode
    mode: Literal["strict", "lenient"] = "strict"
    skip_validation: bool = False

    # Output options
    create_zip: bool = False

    # Project metadata
    project_name: str = "turbovault_project"
    profile_name: str = "default"

    # datavault4dbt global variables rendered into the dbt_project.yml vars: block
    global_vars: dict[str, Any] = field(default_factory=dict)

    # Per-layer settings of the dbt_project.yml models: block
    control_schema: str = "control"
    control_materialization: str = "table"
    staging_materialization: str = "view"
    raw_vault_materialization: str = "incremental"
    business_vault_materialization: str = "table"
    # Keep the own materialization of models that differ from their layer
    model_specific_materializations: bool = True
    # Overrides of those own materializations, keyed by model kind
    model_materializations: dict[str, str] = field(default_factory=dict)

    # Optional profiles.yml, rendered from a caller-supplied mapping
    generate_profiles_yml: bool = False
    profiles: dict[str, Any] = field(default_factory=dict)
