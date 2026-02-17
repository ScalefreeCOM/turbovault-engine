"""
Satellite models for TurboVault Engine.

These models represent Data Vault satellites that capture descriptive attributes:
- Satellite: A Data Vault satellite attached to a hub or link
- SatelliteColumn: Columns within a satellite with delta detection and transformation options
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from engine.models.hubs import Hub
from engine.models.project import Project
from engine.models.source_metadata import SourceColumn


class Satellite(models.Model):
    """
    Represents a Data Vault satellite entity.

    A satellite captures descriptive/context attributes for a hub or link.
    It can be standard, reference, non-historized, or multi-active.
    """

    class SatelliteType(models.TextChoices):
        STANDARD = "standard", "Standard"
        REFERENCE = "reference", "Reference"
        NON_HISTORIZED = "non_historized", "Non-Historized"
        MULTI_ACTIVE = "multi_active", "Multi-Active"

    satellite_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the satellite",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="satellites",
        help_text="Project this satellite belongs to",
    )

    group = models.ForeignKey(
        "Group",
        on_delete=models.SET_NULL,
        related_name="satellites",
        blank=True,
        null=True,
        help_text="Optional group for organizing satellites into subfolders",
    )

    satellite_physical_name = models.CharField(
        max_length=255,
        help_text="Physical name of the satellite (e.g. sat_customer_details)",
    )

    satellite_type = models.CharField(
        max_length=20,
        choices=SatelliteType.choices,
        default=SatelliteType.STANDARD,
        help_text="Type of satellite",
    )

    # Polymorphic parent: exactly one must be set
    parent_hub = models.ForeignKey(
        Hub,
        on_delete=models.CASCADE,
        related_name="satellites",
        blank=True,
        null=True,
        help_text="Parent hub (if satellite belongs to a hub)",
    )

    parent_link = models.ForeignKey(
        "Link",
        on_delete=models.CASCADE,
        related_name="satellites",
        blank=True,
        null=True,
        help_text="Parent link (if satellite belongs to a link)",
    )

    source_table = models.ForeignKey(
        "SourceTable",
        on_delete=models.CASCADE,
        related_name="satellites",
        blank=True,
        null=True,
        help_text="Source table that feeds this satellite (all columns must come from this table)",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the satellite was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the satellite was last updated"
    )

    class Meta:
        db_table = "satellite"
        unique_together = [["project", "satellite_physical_name"]]
        ordering = ["satellite_physical_name"]

    def clean(self) -> None:
        """Validate that exactly one parent is set (hub XOR link)."""
        super().clean()

        # Exactly one parent must be set (hub XOR link)
        if not (bool(self.parent_hub) ^ bool(self.parent_link)):
            raise ValidationError(
                "Satellite must have exactly one parent: either parent_hub OR parent_link, not both."
            )

    def __str__(self) -> str:
        return self.satellite_physical_name


class SatelliteColumn(models.Model):
    """
    Represents a column within a satellite.

    Satellite columns map source columns to the satellite with options for:
    - Multi-active key designation
    - Delta detection inclusion/exclusion
    - Column renaming
    - Column transformation (future)
    """

    satellite_column_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the satellite column",
    )

    satellite = models.ForeignKey(
        Satellite,
        on_delete=models.CASCADE,
        related_name="columns",
        help_text="Satellite this column belongs to",
    )

    staging_column = models.ForeignKey(
        "engine.StagingColumn",
        on_delete=models.CASCADE,
        related_name="satellite_columns",
        help_text="Unified staging column for this satellite column",
    )

    is_multi_active_key = models.BooleanField(
        default=False,
        help_text="If true, this column is part of the multi-active key (for multi-active satellites)",
    )

    include_in_delta_detection = models.BooleanField(
        default=True,
        help_text="If false, this column is excluded from hashdiff calculation",
    )

    target_column_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Optional target column name (if different from source column name)",
    )

    target_column_transformation = models.TextField(
        blank=True,
        null=True,
        help_text="Optional transformation expression for derived columns (future use)",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the satellite column was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the satellite column was last updated"
    )

    class Meta:
        db_table = "satellite_column"
        unique_together = [["satellite", "staging_column"]]
        ordering = ["satellite", "staging_column"]

    def clean(self) -> None:
        """Validate that staging column comes from satellite's source table."""
        super().clean()

        if self.staging_column and self.satellite:
            if self.staging_column.source_table != self.satellite.source_table:
                raise ValidationError(
                    {
                        "staging_column": f"Staging column must come from satellite's source table ({self.satellite.source_table.physical_table_name})"
                    }
                )

    def __str__(self) -> str:
        target = self.target_column_name or self.staging_column.physical_name
        return f"{self.satellite.satellite_physical_name}.{target}"
