"""
PIT (Point-in-Time) model for TurboVault Engine.

PIT structures provide snapshots of satellite data at regular intervals,
making it efficient to query historical states for hubs or links.
"""

from __future__ import annotations

import uuid
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import models

from engine.models.project import Project
from engine.models.hubs import Hub
from engine.models.links import Link
from engine.models.satellites import Satellite
from engine.models.snapshot_control import SnapshotControlTable, SnapshotControlLogic


class PIT(models.Model):
    """
    Point-in-Time structure definition.

    Tracks satellite changes for a hub or link at specific points in time,
    providing efficient historical state queries.
    """

    class TrackedEntityType(models.TextChoices):
        HUB = "hub", "Hub"
        LINK = "link", "Link"

    pit_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the PIT structure",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="pits",
        help_text="Project this PIT belongs to",
    )

    pit_physical_name = models.CharField(
        max_length=255, help_text="Physical name of the PIT structure"
    )

    tracked_entity_type = models.CharField(
        max_length=10,
        choices=TrackedEntityType.choices,
        help_text="Type of entity being tracked (hub or link)",
    )

    tracked_hub = models.ForeignKey(
        Hub,
        on_delete=models.CASCADE,
        related_name="pits",
        blank=True,
        null=True,
        help_text="Hub being tracked (if tracked_entity_type is 'hub')",
    )

    tracked_link = models.ForeignKey(
        Link,
        on_delete=models.CASCADE,
        related_name="pits",
        blank=True,
        null=True,
        help_text="Link being tracked (if tracked_entity_type is 'link')",
    )

    snapshot_control_table = models.ForeignKey(
        SnapshotControlTable,
        on_delete=models.CASCADE,
        related_name="pits",
        help_text="Snapshot control table for this PIT",
    )

    snapshot_control_logic = models.ForeignKey(
        SnapshotControlLogic,
        on_delete=models.CASCADE,
        related_name="pits",
        help_text="Snapshot control logic for this PIT",
    )

    satellites = models.ManyToManyField(
        Satellite,
        related_name="pits",
        help_text="Satellites included in this PIT structure",
    )

    dimension_key_column_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Optional dimension key column name in the PIT",
    )

    pit_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Optional PIT type classification",
    )

    custom_record_source = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Optional custom record source value",
    )

    use_snapshot_optimization = models.BooleanField(
        default=True, help_text="Whether to apply snapshot optimization techniques"
    )

    include_business_objects_before_appearance = models.BooleanField(
        default=False,
        help_text="Whether to include business keys before their first appearance",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the PIT was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the PIT was last updated"
    )

    class Meta:
        db_table = "pit"
        unique_together = [["project", "pit_physical_name"]]
        ordering = ["project", "pit_physical_name"]
        verbose_name = "PIT"
        verbose_name_plural = "PITs"

    @property
    def tracked_entity(self):
        """Return the tracked entity (hub or link) regardless of type."""
        return (
            self.tracked_hub
            if self.tracked_entity_type == self.TrackedEntityType.HUB
            else self.tracked_link
        )

    def clean(self) -> None:
        """
        Validate PIT configuration:
        - Exactly one of tracked_hub or tracked_link must be set (XOR)
        - The set entity must match tracked_entity_type
        - Satellites must belong to the tracked entity
        """
        super().clean()

        # XOR validation for tracked entity
        has_hub = self.tracked_hub is not None
        has_link = self.tracked_link is not None

        if not (has_hub or has_link):
            raise ValidationError(
                {
                    "tracked_entity_type": "Either tracked_hub or tracked_link must be specified."
                }
            )

        if has_hub and has_link:
            raise ValidationError(
                {
                    "tracked_hub": "Cannot specify both tracked_hub and tracked_link. Choose one.",
                    "tracked_link": "Cannot specify both tracked_hub and tracked_link. Choose one.",
                }
            )

        # Validate entity type matches
        if self.tracked_entity_type == self.TrackedEntityType.HUB and not has_hub:
            raise ValidationError(
                {
                    "tracked_hub": 'tracked_hub must be set when tracked_entity_type is "hub".'
                }
            )

        if self.tracked_entity_type == self.TrackedEntityType.LINK and not has_link:
            raise ValidationError(
                {
                    "tracked_link": 'tracked_link must be set when tracked_entity_type is "link".'
                }
            )

    def save(self, *args, **kwargs):
        """Save with additional M2M validation."""
        super().save(*args, **kwargs)

        # After save, validate satellites belong to tracked entity
        if self.pk and self.satellites.exists():
            tracked_entity = self.tracked_entity
            tracked_id = tracked_entity.pk if tracked_entity else None

            invalid_satellites = []
            for sat in self.satellites.all():
                if self.tracked_entity_type == self.TrackedEntityType.HUB:
                    if sat.parent_hub_id != tracked_id:
                        invalid_satellites.append(sat.satellite_physical_name)
                else:  # LINK
                    if sat.parent_link_id != tracked_id:
                        invalid_satellites.append(sat.satellite_physical_name)

            if invalid_satellites:
                raise ValidationError(
                    f"Satellites must belong to the tracked {self.tracked_entity_type}: {', '.join(invalid_satellites)}"
                )

    def __str__(self) -> str:
        entity_name = (
            self.tracked_entity.hub_physical_name
            if self.tracked_hub
            else (
                self.tracked_entity.link_physical_name
                if self.tracked_link
                else "Unknown"
            )
        )
        return f"{self.pit_physical_name} ({entity_name})"
