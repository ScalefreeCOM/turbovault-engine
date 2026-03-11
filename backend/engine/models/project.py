"""
Project model for TurboVault Engine.

The Project entity is the top-level container for all Data Vault modeling work.
All domain entities (source metadata, hubs, links, satellites, etc.) are scoped to a Project.
"""

from __future__ import annotations

import uuid

from django.db import models


class Project(models.Model):
    """
    Represents a full modeling context for a Data Vault implementation.

    A Project contains all metadata for source systems, Data Vault structures,
    and generated artifacts.
    """

    project_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for the project",
    )

    name = models.CharField(
        max_length=255, help_text="Human-readable name of the project"
    )

    description = models.TextField(
        blank=True, null=True, help_text="Optional longer description of the project"
    )

    project_directory = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text="Relative path to project directory (e.g., 'projects/customer_mdm')",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the project was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the project was last updated"
    )

    class Meta:
        db_table = "project"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name

    def get_config_path(self):
        """
        Get absolute path to this project's config.yml.

        Returns:
            Path object pointing to config.yml

        Raises:
            ValueError: If project_directory is not set
        """

        from engine.services.app_config_loader import resolve_project_path

        if not self.project_directory:
            raise ValueError(
                f"Project '{self.name}' has no project_directory set. "
                "Cannot locate config.yml."
            )

        return resolve_project_path(self.project_directory) / "config.yml"

    def load_config(self):
        """
        Load and return this project's configuration from YAML.

        Returns:
            TurboVaultConfig: Validated project configuration

        Raises:
            FileNotFoundError: If config.yml doesn't exist
            ConfigValidationError: If config is invalid
        """
        from engine.services.config_loader import load_config_from_path

        config_path = self.get_config_path()
        return load_config_from_path(config_path)

    def get_naming_pattern(self, pattern_key: str) -> str:
        """
        Resolve a naming pattern for satellites, hashkeys, or hashdiffs.

        Loads the configuration from YAML and retrieves the naming pattern.
        If not found in config, returns a hardcoded default.

        Args:
            pattern_key: The key of the pattern to retrieve.
                         (e.g., 'satellite_v0_naming', 'hashkey_naming')

        Returns:
            The naming pattern string with placeholders.

        Examples:
            >>> project.get_naming_pattern('satellite_v0_naming')
            '[[ satellite_name ]]_v0'
        """
        # Load from YAML config
        try:
            config = self.load_config()
            pattern_value = getattr(config.configuration, pattern_key, None)
            if pattern_value:
                return pattern_value
        except Exception:
            pass  # Config loading failed, use defaults

        # Hardcoded defaults
        defaults = {
            "satellite_v0_naming": "[[ satellite_name ]]_v0",
            "satellite_v1_naming": "[[ satellite_name ]]_v1",
            "hashkey_naming": "hd_[[ entity_name ]]",
            "hashdiff_naming": "hd_[[ satellite_name ]]",
        }

        return defaults.get(pattern_key, f"{{{pattern_key}}}")

    def resolve_naming_pattern(self, pattern_key: str, entity_name: str) -> str:
        """
        Resolve a naming pattern from the project config with placeholder replacement.

        Placeholders:
        - [[ entity_name ]] or [[ satellite_name ]]
        """
        pattern = self.get_naming_pattern(pattern_key)

        # Replace placeholders
        # We accept entity_name or satellite_name for flexibility
        resolved = pattern.replace("[[ entity_name ]]", entity_name).replace(
            "[[ satellite_name ]]", entity_name
        )

        return resolved

    def get_schema(self, schema_type: str) -> str:
        """
        Get the schema name for a specific schema type.

        Args:
            schema_type: The type of schema to retrieve.
                         ('stage', 'rdv', 'bdv')

        Returns:
            The schema name string.

        Raises:
            ValueError: If the schema type is not found in the configuration.
        """
        try:
            config = self.load_config()
            schema_name = getattr(config.configuration, f"{schema_type}_schema", None)
            if schema_name:
                return schema_name
        except Exception:
            pass  # Config loading failed, use defaults

        defaults = {
            "stage": "stage",
            "rdv": "rdv",
            "bdv": "bdv",
        }

        return defaults.get(schema_type, f"{schema_type}")
