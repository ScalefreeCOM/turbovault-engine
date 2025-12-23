"""
Link models for TurboVault Engine.

These models represent Data Vault links and their mappings:
- Link: A Data Vault link connecting multiple hubs
- LinkColumn: Columns within a link (business_key, payload, or additional)
- LinkSourceMapping: Maps link columns to source columns (like HubSourceMapping)
"""
from __future__ import annotations

import uuid

from django.db import models

from engine.models.project import Project
from engine.models.hubs import Hub
from engine.models.source_metadata import SourceColumn


class Link(models.Model):
    """
    Represents a Data Vault link entity.
    
    A link connects multiple hubs (typically 2) and captures the relationship
    between business entities. Links can be standard or non-historized.
    """
    
    class LinkType(models.TextChoices):
        STANDARD = 'standard', 'Standard'
        NON_HISTORIZED = 'non_historized', 'Non-Historized'
    
    link_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the link"
    )
    
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="links",
        help_text="Project this link belongs to"
    )
    
    group = models.ForeignKey(
        'Group',
        on_delete=models.SET_NULL,
        related_name="links",
        blank=True,
        null=True,
        help_text="Optional group for organizing links into subfolders"
    )
    
    link_physical_name = models.CharField(
        max_length=255,
        help_text="Physical name of the link (e.g. link_customer_order)"
    )
    
    link_hashkey_name = models.CharField(
        max_length=255,
        help_text="Name of the link hashkey column (e.g. lk_customer_order)"
    )
    
    link_type = models.CharField(
        max_length=20,
        choices=LinkType.choices,
        default=LinkType.STANDARD,
        help_text="Type of link: standard or non-historized"
    )
    
    hub_references = models.ManyToManyField(
        Hub,
        related_name="links",
        limit_choices_to={'hub_type': Hub.HubType.STANDARD},
        help_text="Hubs connected by this link (must be standard hubs)"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the link was created"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the link was last updated"
    )
    
    class Meta:
        db_table = "link"
        unique_together = [["project", "link_physical_name"]]
        ordering = ["link_physical_name"]
    
    def __str__(self) -> str:
        return self.link_physical_name


class LinkColumn(models.Model):
    """
    Represents a column within a link.
    
    Link columns can be:
    - business_key: References a hub's business key (for link hashkey composition)
    - payload: Descriptive data about the relationship
    - additional_column: Other metadata columns
    
    This mirrors HubColumn structure for consistency.
    """
    
    class ColumnType(models.TextChoices):
        BUSINESS_KEY = 'business_key', 'Business Key'
        PAYLOAD = 'payload', 'Payload'
        ADDITIONAL_COLUMN = 'additional_column', 'Additional Column'
    
    link_column_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the link column"
    )
    
    link = models.ForeignKey(
        Link,
        on_delete=models.CASCADE,
        related_name="columns",
        help_text="Link this column belongs to"
    )
    
    column_name = models.CharField(
        max_length=255,
        help_text="Logical/target column name in the link"
    )
    
    column_type = models.CharField(
        max_length=20,
        choices=ColumnType.choices,
        help_text="Type of column: business_key, payload, or additional_column"
    )
    
    sort_order = models.IntegerField(
        default=0,
        help_text="Order of column for hashkey composition"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the link column was created"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the link column was last updated"
    )
    
    class Meta:
        db_table = "link_column"
        unique_together = [["link", "column_name"]]
        ordering = ["link", "sort_order", "column_name"]
    
    def __str__(self) -> str:
        return f"{self.link.link_physical_name}.{self.column_name}"


class LinkSourceMapping(models.Model):
    """
    Maps link columns to source columns.
    
    This defines where the data for a link column comes from in the source.
    Similar to HubSourceMapping, allows multiple source mappings per column.
    """
    
    link_source_mapping_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the link source mapping"
    )
    
    link_column = models.ForeignKey(
        LinkColumn,
        on_delete=models.CASCADE,
        related_name="source_mappings",
        help_text="Link column being mapped"
    )
    
    source_column = models.ForeignKey(
        SourceColumn,
        on_delete=models.PROTECT,
        related_name="link_column_mappings",
        help_text="Source column providing the data"
    )
    
    is_primary_source = models.BooleanField(
        default=True,
        help_text="If true, this is the primary source for multi-source links"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the mapping was created"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the mapping was last updated"
    )
    
    class Meta:
        db_table = "link_source_mapping"
        unique_together = [["link_column", "source_column"]]
        ordering = ["link_column"]
    
    def __str__(self) -> str:
        return f"{self.link_column} <- {self.source_column}"
