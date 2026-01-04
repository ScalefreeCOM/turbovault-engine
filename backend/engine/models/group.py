"""
Group model for TurboVault Engine.

Groups are used to organize Data Vault entities (hubs, links, satellites)
into logical folders in the generated output.
"""

from __future__ import annotations

import uuid

from django.db import models

from engine.models.project import Project


class Group(models.Model):
    """
    Represents a logical grouping for Data Vault entities.

    Groups are used to organize hubs, links, and satellites into
    subfolders in the generated dbt project or other outputs.
    """

    group_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the group",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="groups",
        help_text="Project this group belongs to",
    )

    group_name = models.CharField(
        max_length=255,
        help_text="Name of the group (e.g., 'sales', 'marketing', 'core')",
    )

    description = models.TextField(
        blank=True, null=True, help_text="Optional description of this group"
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the group was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the group was last updated"
    )

    class Meta:
        db_table = "group"
        unique_together = [["project", "group_name"]]
        ordering = ["group_name"]

    def __str__(self) -> str:
        return self.group_name
