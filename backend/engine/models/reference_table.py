"""
Reference table models for TurboVault Engine.

Reference tables represent denormalized views of reference data built from
reference hubs and their associated reference satellites with controlled
historization strategies.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from engine.models.hubs import Hub
from engine.models.project import Project
from engine.models.satellites import Satellite, SatelliteColumn
from engine.models.snapshot_control import SnapshotControlLogic, SnapshotControlTable


class ReferenceTable(models.Model):
    """
    Reference table definition based on a reference hub.

    Represents a denormalized view combining a reference hub with its
    reference satellites, applying a specific historization strategy.
    """

    class HistorizationType(models.TextChoices):
        LATEST = "latest", "Latest"
        FULL = "full", "Full History"
        SNAPSHOT_BASED = "snapshot_based", "Snapshot-Based"

    reference_table_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the reference table",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="reference_tables",
        help_text="Project this reference table belongs to",
    )

    reference_table_physical_name = models.CharField(
        max_length=255, help_text="Physical name of the reference table"
    )

    reference_hub = models.ForeignKey(
        Hub,
        on_delete=models.CASCADE,
        related_name="reference_tables",
        limit_choices_to={"hub_type": Hub.HubType.REFERENCE},
        help_text="Reference hub this table is based on (must be a reference hub)",
    )

    historization_type = models.CharField(
        max_length=20,
        choices=HistorizationType.choices,
        default=HistorizationType.LATEST,
        help_text="Historization strategy: latest, full, or snapshot_based",
    )

    snapshot_control_table = models.ForeignKey(
        SnapshotControlTable,
        on_delete=models.SET_NULL,
        related_name="reference_tables",
        blank=True,
        null=True,
        help_text="Snapshot control table (required if historization_type is snapshot_based)",
    )

    snapshot_control_logic = models.ForeignKey(
        SnapshotControlLogic,
        on_delete=models.SET_NULL,
        related_name="reference_tables",
        blank=True,
        null=True,
        help_text="Snapshot control logic (required if historization_type is snapshot_based)",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the reference table was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the reference table was last updated"
    )

    class Meta:
        db_table = "reference_table"
        unique_together = [["project", "reference_table_physical_name"]]
        ordering = ["project", "reference_table_physical_name"]

    def clean(self) -> None:
        """
        Validate reference table configuration:
        - Reference hub must have hub_type='reference'
        - If historization_type is snapshot_based, snapshot fields are required
        - If not snapshot_based, snapshot fields must be null
        """
        super().clean()

        # Validate reference hub type
        if self.reference_hub and self.reference_hub.hub_type != Hub.HubType.REFERENCE:
            raise ValidationError(
                {
                    "reference_hub": f"Hub '{self.reference_hub.hub_physical_name}' must be a reference hub."
                }
            )

        # Validate snapshot configuration
        if self.historization_type == self.HistorizationType.SNAPSHOT_BASED:
            if not self.snapshot_control_table or not self.snapshot_control_logic:
                raise ValidationError(
                    {
                        "historization_type": "Snapshot control table and logic are required for snapshot-based historization."
                    }
                )
        else:
            if self.snapshot_control_table or self.snapshot_control_logic:
                raise ValidationError(
                    {
                        "snapshot_control_table": "Snapshot control should only be set for snapshot_based historization.",
                        "snapshot_control_logic": "Snapshot control should only be set for snapshot_based historization.",
                    }
                )

    def __str__(self) -> str:
        return f"{self.reference_table_physical_name} ({self.historization_type})"


class ReferenceTableSatelliteAssignment(models.Model):
    """
    Assignment of a reference satellite to a reference table.

    Controls which columns from the satellite are included or excluded
    in the reference table view.
    """

    assignment_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the satellite assignment",
    )

    reference_table = models.ForeignKey(
        ReferenceTable,
        on_delete=models.CASCADE,
        related_name="satellite_assignments",
        help_text="Reference table this assignment belongs to",
    )

    reference_satellite = models.ForeignKey(
        Satellite,
        on_delete=models.CASCADE,
        related_name="reference_table_assignments",
        limit_choices_to={"satellite_type": Satellite.SatelliteType.REFERENCE},
        help_text="Reference satellite to include (must be a reference satellite)",
    )

    include_columns = models.ManyToManyField(
        SatelliteColumn,
        related_name="included_in_reference_tables",
        blank=True,
        help_text="Specific columns to include (if empty, includes all except excluded)",
    )

    exclude_columns = models.ManyToManyField(
        SatelliteColumn,
        related_name="excluded_from_reference_tables",
        blank=True,
        help_text="Specific columns to exclude (only used if include_columns is empty)",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the assignment was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the assignment was last updated"
    )

    class Meta:
        db_table = "reference_table_satellite_assignment"
        unique_together = [["reference_table", "reference_satellite"]]
        ordering = ["reference_table", "reference_satellite"]

    def clean(self) -> None:
        """
        Validate satellite assignment:
        - Satellite must be type 'reference'
        - Satellite must belong to the reference table's hub
        - Cannot specify both include AND exclude columns simultaneously
        """
        super().clean()

        # Validate satellite type
        if (
            self.reference_satellite
            and self.reference_satellite.satellite_type
            != Satellite.SatelliteType.REFERENCE
        ):
            raise ValidationError(
                {
                    "reference_satellite": f"Satellite '{self.reference_satellite.satellite_physical_name}' must be a reference satellite."
                }
            )

        # Validate satellite belongs to reference hub
        if (
            self.reference_table
            and self.reference_satellite
            and self.reference_satellite.parent_hub_id
            != self.reference_table.reference_hub_id
        ):
            raise ValidationError(
                {
                    "reference_satellite": f"Satellite must belong to the reference table's hub ({self.reference_table.reference_hub.hub_physical_name})."
                }
            )

        # Note: M2M validation for include/exclude must happen in save() or via custom validation
        # because M2M fields aren't populated yet during clean()

    def save(self, *args, **kwargs):
        """Save with additional M2M validation."""
        super().save(*args, **kwargs)

        # After save, check M2M constraints
        if self.include_columns.exists() and self.exclude_columns.exists():
            raise ValidationError(
                "Cannot specify both include_columns and exclude_columns. Use one or neither."
            )

    def __str__(self) -> str:
        return f"{self.reference_table.reference_table_physical_name} - {self.reference_satellite.satellite_physical_name}"
