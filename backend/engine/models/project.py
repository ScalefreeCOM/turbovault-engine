"""
Project model for TurboVault Engine.

The Project entity is the top-level container for all Data Vault modeling work.
All domain entities (source metadata, hubs, links, satellites, etc.) are scoped to a Project.
"""
from __future__ import annotations

import uuid
from typing import Any

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
        help_text="Unique identifier for the project"
    )
    
    name = models.CharField(
        max_length=255,
        help_text="Human-readable name of the project"
    )
    
    description = models.TextField(
        blank=True,
        null=True,
        help_text="Optional longer description of the project"
    )
    
    config = models.JSONField(
        blank=True,
        null=True,
        help_text="Optional JSON for project-level configuration parameters"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the project was created"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the project was last updated"
    )
    
    class Meta:
        db_table = "project"
        ordering = ["-created_at"]
    
    def __str__(self) -> str:
        return self.name
