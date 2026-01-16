"""
Link models for TurboVault Engine.

These models represent Data Vault links and their mappings:
- Link: A Data Vault link entity
- LinkHubReference: References to hubs connected by a link
- LinkColumn: Columns within a link (payload or additional)
- LinkSourceMapping: Maps link columns to source columns
- LinkHubSourceMapping: Maps link hub references to source/prejoin columns
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Max

from engine.models.hubs import Hub, HubColumn
from engine.models.project import Project
from engine.models.source_metadata import SourceColumn


class Link(models.Model):
    """
    Represents a Data Vault link entity.

    A link connects multiple hubs via LinkHubReferences.
    """

    class LinkType(models.TextChoices):
        STANDARD = "standard", "Standard"
        NON_HISTORIZED = "non_historized", "Non-Historized"

    link_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the link",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="links",
        help_text="Project this link belongs to",
    )

    group = models.ForeignKey(
        "Group",
        on_delete=models.SET_NULL,
        related_name="links",
        blank=True,
        null=True,
        help_text="Optional group for organizing links into subfolders",
    )

    link_physical_name = models.CharField(
        max_length=255, help_text="Physical name of the link (e.g. customer_order_l)"
    )

    link_hashkey_name = models.CharField(
        max_length=255,
        default="",
        help_text="Name of the link hashkey column (e.g. hk_customer_order_l)",
    )

    link_type = models.CharField(
        max_length=20,
        choices=LinkType.choices,
        default=LinkType.STANDARD,
        help_text="Type of link: standard or non-historized",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the link was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the link was last updated"
    )

    class Meta:
        db_table = "link"
        unique_together = [["project", "link_physical_name"]]
        ordering = ["link_physical_name"]

    def __str__(self) -> str:
        return self.link_physical_name


class LinkHubReference(models.Model):
    """
    Defines the hubs referenced by a link.
    """

    link_hub_reference_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for the link-to-hub reference",
    )

    link = models.ForeignKey(
        Link,
        on_delete=models.CASCADE,
        related_name="hub_references",
        help_text="Link this reference belongs to",
    )

    hub = models.ForeignKey(
        Hub,
        on_delete=models.CASCADE,
        related_name="link_references",
        help_text="Hub referenced by the link",
    )

    hub_hashkey_alias_in_link = models.CharField(
        max_length=255,
        blank=True,
        help_text="Alias for the hub hashkey in the link. Default should be the hub's hashkey name.",
    )

    sort_order = models.IntegerField(
        default=0,
        help_text="Order of appearance in the link. Leave as 0 to auto-assign next available number.",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the record was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the record was last updated"
    )

    class Meta:
        db_table = "link_hub_references"
        ordering = ["link", "sort_order", "hub"]
        verbose_name = "Link Hub Reference"
        verbose_name_plural = "Link Hub References"

    def save(self, *args, **kwargs):
        """Auto-assign sort_order if not provided."""
        if self.sort_order == 0:
            max_order = LinkHubReference.objects.filter(link=self.link).aggregate(
                Max("sort_order")
            )["sort_order__max"]
            self.sort_order = (max_order or 0) + 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        alias = self.hub_hashkey_alias_in_link or self.hub.hub_physical_name
        return (
            f"{self.link.link_physical_name} -> {alias} ({self.hub.hub_physical_name})"
        )


class LinkColumn(models.Model):
    """
    Represents a column within a link.

    Link columns can be:
    - dependant_child_key: Columns that should be used for link hashkey calculation, but are not pointing to another hub.
    - payload: Descriptive data about the relationship
    - additional_column: Other metadata columns

    This mirrors HubColumn structure for consistency.
    """

    class ColumnType(models.TextChoices):
        PAYLOAD = "payload", "Payload"
        ADDITIONAL_COLUMN = "additional_column", "Additional Column"
        DEPENDANT_CHILD_KEY = "dependant_child_key", "Dependant Child Key"

    link_column_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the link column",
    )

    link = models.ForeignKey(
        Link,
        on_delete=models.CASCADE,
        related_name="columns",
        help_text="Link this column belongs to",
    )

    column_name = models.CharField(
        max_length=255, help_text="Logical/target column name in the link"
    )

    column_type = models.CharField(
        max_length=20,
        choices=ColumnType.choices,
        help_text="Type of column: payload or additional_column",
    )

    sort_order = models.IntegerField(
        default=0,
        help_text="Order of appearance in the link structure. Leave as 0 to auto-assign next available number.",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the link column was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the link column was last updated"
    )

    class Meta:
        db_table = "link_column"
        unique_together = [["link", "column_name"]]
        ordering = ["link", "sort_order", "column_name"]
        verbose_name = "Link Column"
        verbose_name_plural = "Link Columns"

    def save(self, *args, **kwargs):
        """Auto-assign sort_order if not provided."""
        if self.sort_order == 0:
            max_order = LinkColumn.objects.filter(link=self.link).aggregate(
                Max("sort_order")
            )["sort_order__max"]
            self.sort_order = (max_order or 0) + 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.link.link_physical_name}.{self.column_name}"


class LinkSourceMapping(models.Model):
    """
    Maps link columns to source columns.
    """

    link_source_mapping_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for a link column mapping",
    )

    link_column = models.ForeignKey(
        LinkColumn,
        on_delete=models.CASCADE,
        related_name="source_mappings",
        help_text="Link column being mapped",
    )

    source_column = models.ForeignKey(
        SourceColumn,
        on_delete=models.CASCADE,
        related_name="link_column_mappings",
        help_text="Source column mapped to this link column",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the mapping was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the mapping was last updated"
    )

    class Meta:
        db_table = "link_source_mapping"
        ordering = ["link_column"]
        verbose_name = "Link Source Mapping"
        verbose_name_plural = "Link Source Mappings"

    def __str__(self) -> str:
        return f"{self.link_column} <- {self.source_column}"


class LinkHubSourceMapping(models.Model):
    """
    Defines how link hub keys are derived from source data.

    Maps a LinkHubReference + StandardHubColumn to a SourceColumn OR PrejoinExtractionColumn.
    """

    link_hub_source_mapping_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for a link hub mapping",
    )

    link_hub_reference = models.ForeignKey(
        LinkHubReference,
        on_delete=models.CASCADE,
        related_name="source_mappings",
        help_text="Link hub reference being mapped",
    )

    standard_hub_column = models.ForeignKey(
        HubColumn,
        on_delete=models.CASCADE,
        related_name="link_hub_mappings",
        help_text="Hub column of the referenced standard hub",
    )

    source_column = models.ForeignKey(
        SourceColumn,
        on_delete=models.CASCADE,
        related_name="link_hub_mappings",
        blank=True,
        null=True,
        help_text="Direct source column (XOR with prejoin_extraction_column)",
    )

    prejoin_extraction_column = models.ForeignKey(
        "engine.PrejoinExtractionColumn",
        on_delete=models.CASCADE,
        related_name="link_hub_mappings",
        blank=True,
        null=True,
        help_text="Prejoin extraction column (XOR with source_column)",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the mapping was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the mapping was last updated"
    )

    class Meta:
        db_table = "link_hub_source_mapping"
        ordering = ["link_hub_reference", "standard_hub_column"]
        verbose_name = "Link Hub Source Mapping"
        verbose_name_plural = "Link Hub Source Mappings"

    def clean(self) -> None:
        """Validate XOR: exactly one of source_column or prejoin_extraction_column."""
        super().clean()

        has_source = self.source_column is not None
        has_prejoin = self.prejoin_extraction_column is not None

        if not (has_source or has_prejoin):
            raise ValidationError(
                {
                    "source_column": "Either source_column or prejoin_extraction_column must be specified."
                }
            )

        if has_source and has_prejoin:
            raise ValidationError(
                {
                    "source_column": "Cannot specify both source_column and prejoin_extraction_column."
                }
            )

    def __str__(self) -> str:
        target = f"{self.link_hub_reference} ({self.standard_hub_column.column_name})"
        if self.source_column:
            return f"{target} <- {self.source_column}"
        elif self.prejoin_extraction_column:
            return f"{target} <- [prejoin] {self.prejoin_extraction_column}"
        return f"{target} <- (no source)"
