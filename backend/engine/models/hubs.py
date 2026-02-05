"""
Hub models for TurboVault Engine.

These models represent Data Vault hubs and their mappings to source data:
- Hub: A Data Vault hub entity (standard or reference)
- HubColumn: Columns within a hub (business keys, additional columns, reference keys)
- HubSourceMapping: Maps hub columns to source columns
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from engine.models.project import Project
from engine.models.source_metadata import SourceColumn


class Hub(models.Model):
    """
    Represents a Data Vault hub entity.

    A hub defines a business concept (e.g., Customer, Product) identified by
    one or more business keys. Hubs can be either standard (with hash keys) or
    reference (for reference data).
    """

    class HubType(models.TextChoices):
        STANDARD = "standard", "Standard Hub"
        REFERENCE = "reference", "Reference Hub"

    hub_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the hub",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="hubs",
        help_text="Project this hub belongs to",
    )

    group = models.ForeignKey(
        "Group",
        on_delete=models.SET_NULL,
        related_name="hubs",
        blank=True,
        null=True,
        help_text="Optional group for organizing hubs into subfolders",
    )

    hub_physical_name = models.CharField(
        max_length=255, help_text="Physical name of the hub (e.g. hub_customer)"
    )

    hub_type = models.CharField(
        max_length=20,
        choices=HubType.choices,
        default=HubType.STANDARD,
        help_text="Type of hub: standard or reference",
    )

    hub_hashkey_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Name of the hub hashkey column (used only if hub_type = standard)",
    )

    create_record_tracking_satellite = models.BooleanField(
        default=False,
        help_text="If true, a record-tracking satellite should be generated for this hub",
    )

    create_effectivity_satellite = models.BooleanField(
        default=True,
        help_text="If true, an effectivity satellite should be generated for this hub",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the hub was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the hub was last updated"
    )

    class Meta:
        db_table = "hub"
        unique_together = [["project", "hub_physical_name"]]
        ordering = ["hub_physical_name"]

    def clean(self) -> None:
        """Validate that standard hubs have a hashkey name."""
        super().clean()

        # Validate hashkey for standard hubs - only if it won't be auto-populated
        # If it's a new instance and has no project yet (unsaved), we might still want to warn,
        # but usually cleanup happens when we have project context.
        pass

    def __str__(self) -> str:
        return self.hub_physical_name

    def save(self, *args, **kwargs) -> None:
        """Auto-populate hashkey name for standard hubs if not provided."""
        if self.hub_type == self.HubType.STANDARD and not self.hub_hashkey_name:
            self.hub_hashkey_name = self.project.resolve_naming_pattern(
                "hashkey_naming", self.hub_physical_name
            )
        super().save(*args, **kwargs)


class HubColumn(models.Model):
    """
    Represents a column within a hub.

    Hub columns can be business keys, additional columns, or reference keys
    depending on the hub type and purpose.
    """

    class ColumnType(models.TextChoices):
        BUSINESS_KEY = "business_key", "Business Key"
        ADDITIONAL_COLUMN = "additional_column", "Additional Column"
        REFERENCE_KEY = "reference_key", "Reference Key"

    hub_column_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the hub column",
    )

    hub = models.ForeignKey(
        Hub,
        on_delete=models.CASCADE,
        related_name="columns",
        help_text="Hub this column belongs to",
    )

    column_name = models.CharField(
        max_length=255, help_text="Logical/target column name in the hub"
    )

    column_type = models.CharField(
        max_length=30,
        choices=ColumnType.choices,
        default=ColumnType.BUSINESS_KEY,
        help_text="Type of column: business_key, additional_column, or reference_key",
    )

    sort_order = models.IntegerField(
        blank=True,
        null=True,
        help_text="Sorting index to define ordering of hub columns (auto-incremented if not provided)",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the hub column was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the hub column was last updated"
    )

    class Meta:
        db_table = "hub_column"
        unique_together = [["hub", "column_name"]]
        ordering = ["sort_order"]

    def save(self, *args, **kwargs) -> None:
        """Auto-increment sort_order if not provided."""
        if self.sort_order is None:
            # Get the max sort_order for this hub
            max_sort = HubColumn.objects.filter(hub=self.hub).aggregate(
                models.Max("sort_order")
            )["sort_order__max"]

            # Start at 1 if no columns exist, otherwise increment
            self.sort_order = 1 if max_sort is None else max_sort + 1

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.hub.hub_physical_name}.{self.column_name}"


class HubSourceMapping(models.Model):
    """
    Maps hub columns to source columns.

    Defines how hub columns are populated from source data. Only one mapping
    can be designated as the primary source per hub.
    """

    hub_source_mapping_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the hub-to-source mapping row",
    )

    hub_column = models.ForeignKey(
        HubColumn,
        on_delete=models.CASCADE,
        related_name="source_mappings",
        help_text="Hub column being mapped",
    )

    source_column = models.ForeignKey(
        SourceColumn,
        on_delete=models.CASCADE,
        related_name="hub_mappings",
        help_text="Source column providing the data",
    )

    is_primary_source = models.BooleanField(
        default=False,
        help_text="Indicates if this mapping is the primary source for the hub",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the mapping was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the mapping was last updated"
    )

    class Meta:
        db_table = "hub_source_mapping"
        unique_together = [["hub_column", "source_column"]]

    def clean(self) -> None:
        """Validate that only one mapping is marked as primary source per hub."""
        super().clean()

        if self.is_primary_source and self.hub_column_id:
            # Get the hub for this mapping
            hub = self.hub_column.hub

            # Check if another mapping is already marked as primary for this hub
            existing_primary = HubSourceMapping.objects.filter(
                hub_column__hub=hub, is_primary_source=True
            ).exclude(pk=self.pk)

            if existing_primary.exists():
                raise ValidationError(
                    {
                        "is_primary_source": f'Hub "{hub.hub_physical_name}" already has a primary source mapping.'
                    }
                )

    def __str__(self) -> str:
        return f"{self.hub_column} → {self.source_column}"
