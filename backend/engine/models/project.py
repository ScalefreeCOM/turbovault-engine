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

    config = models.JSONField(
        blank=True,
        null=True,
        help_text="Optional JSON for project-level configuration parameters",
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

    def get_naming_pattern(self, pattern_key: str) -> str:
        """Get the raw naming pattern from config or its default."""
        defaults = {
            "hashdiff_naming": "hd_[[ satellite_name ]]",
            "hashkey_naming": "hk_[[ entity_name ]]",
            "satellite_v0_naming": "[[ satellite_name ]]_v0",
            "satellite_v1_naming": "[[ satellite_name ]]_v1",
        }
        return (self.config or {}).get(pattern_key) or defaults.get(pattern_key, "")

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
