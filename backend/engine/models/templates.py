"""
Template models for TurboVault Engine dbt project generation.

These models allow customization of dbt model templates through the Django admin.
Templates are stored as Jinja2 content and used during dbt project generation.
"""

from __future__ import annotations

import uuid

from django.db import models


class TemplateCategory(models.Model):
    """Categories for organizing templates."""

    category_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the template category",
    )

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Category name (e.g., 'DataVault4dbt', 'Custom')",
    )

    description = models.TextField(
        blank=True, help_text="Description of this template category"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "template_category"
        verbose_name_plural = "Template categories"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ModelTemplate(models.Model):
    """
    Customizable Jinja2 templates for dbt model generation.

    Each template defines how a specific entity type is rendered as SQL and YAML.
    Templates can be customized via Django Admin and take precedence over
    file-based defaults.
    """

    class EntityType(models.TextChoices):
        """Entity types that can be templated."""

        # Staging
        STAGE = "stage", "Stage"

        # Raw Vault - Hubs
        HUB_STANDARD = "hub_standard", "Hub (Standard)"
        HUB_REFERENCE = "hub_reference", "Hub (Reference)"

        # Raw Vault - Links
        LINK_STANDARD = "link_standard", "Link (Standard)"
        LINK_NON_HISTORIZED = "link_non_historized", "Link (Non-Historized)"

        # Raw Vault - Satellites
        SATELLITE_STANDARD = "satellite_standard", "Satellite (Standard)"
        SATELLITE_NON_HISTORIZED = (
            "satellite_non_historized",
            "Satellite (Non-Historized)",
        )
        SATELLITE_REFERENCE = "satellite_reference", "Satellite (Reference)"
        SATELLITE_MULTI_ACTIVE = "satellite_multi_active", "Satellite (Multi-Active)"
        SATELLITE_EFFECTIVITY = "satellite_effectivity", "Effectivity Satellite"
        SATELLITE_RECORD_TRACKING = (
            "satellite_record_tracking",
            "Record Tracking Satellite",
        )
        SATELLITE_V1 = "satellite_v1", "Satellite V1 (Load-End-Date View)"

        # Business Vault
        PIT = "pit", "PIT"
        REFERENCE_TABLE = "reference_table", "Reference Table"

        # Control
        SNAPSHOT_CONTROL_V0 = "snapshot_control_v0", "Snapshot Control Table (V0)"
        SNAPSHOT_CONTROL_V1 = "snapshot_control_v1", "Snapshot Control Logic (V1)"

    template_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the template",
    )

    name = models.CharField(
        max_length=100, help_text="Template name for identification"
    )

    entity_type = models.CharField(
        max_length=50,
        choices=EntityType.choices,
        help_text="Entity type this template applies to",
    )

    category = models.ForeignKey(
        TemplateCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="templates",
        help_text="Category for organizing templates",
    )

    description = models.TextField(
        blank=True, help_text="Description of this template variant"
    )

    # Template content fields
    sql_template_content = models.TextField(
        blank=True,
        help_text="Jinja2 template for SQL model file. Leave blank to use file-based default.",
    )

    yaml_template_content = models.TextField(
        blank=True,
        help_text="Jinja2 template for YAML schema file. Leave blank to use file-based default.",
    )

    # Priority for template selection (higher = preferred)
    priority = models.IntegerField(
        default=0,
        help_text="Priority for template selection. Higher values are preferred.",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Whether this template is active and available for selection",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "model_template"
        unique_together = ["entity_type", "name"]
        ordering = ["entity_type", "-priority", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_entity_type_display()})"

    @property
    def has_sql_template(self) -> bool:
        """Check if this template has SQL content defined."""
        return bool(self.sql_template_content.strip())

    @property
    def has_yaml_template(self) -> bool:
        """Check if this template has YAML content defined."""
        return bool(self.yaml_template_content.strip())
