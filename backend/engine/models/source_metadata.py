"""
Source metadata models for TurboVault Engine.

These models represent upstream source systems and their physical schemas:
- SourceSystem: A source database/schema
- SourceTable: A physical table within a source system
- SourceColumn: A column within a source table
"""

from __future__ import annotations

import uuid

from django.db import models

from engine.models.project import Project


class SourceSystem(models.Model):
    """
    Represents a physical source system (database/schema).

    Contains metadata about the source database and schema that will be
    modeled into Data Vault structures.
    """

    source_system_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the source system",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="source_systems",
        help_text="Project this source system belongs to",
    )

    schema_name = models.CharField(
        max_length=255, help_text="Schema name in the source system"
    )

    database_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Optional database name (if applicable)",
    )

    name = models.CharField(
        max_length=255, help_text="Human-readable name for this source system"
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the source system was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the source system was last updated"
    )

    class Meta:
        db_table = "source_system"
        unique_together = [["project", "schema_name", "database_name"]]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class SourceTable(models.Model):
    """
    Represents a physical source table within a source system.

    Includes Data Vault-specific configuration such as record source values
    and load date expressions.
    """

    source_table_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the source table",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="source_tables",
        help_text="Project this source table belongs to",
    )

    source_system = models.ForeignKey(
        SourceSystem,
        on_delete=models.CASCADE,
        related_name="tables",
        help_text="Source system this table belongs to",
    )

    physical_table_name = models.CharField(
        max_length=255,
        help_text="Physical name of the table in the source system (e.g. CUSTOMER)",
    )

    alias = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Optional alias used in generated code/dbt models",
    )

    record_source_value = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Value/expression used as record_source for this table",
    )

    static_part_of_record_source = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Optional static part of record_source that is reused",
    )

    load_date_value = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Expression or column name used as load date value",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the source table was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the source table was last updated"
    )

    class Meta:
        db_table = "source_table"
        unique_together = [["source_system", "physical_table_name"]]
        ordering = ["physical_table_name"]

    def __str__(self) -> str:
        return self.physical_table_name


class SourceColumn(models.Model):
    """
    Represents a single column in a source table.

    Used throughout the domain model for mapping to hubs, links, and satellites.
    """

    source_column_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the source column",
    )

    source_table = models.ForeignKey(
        SourceTable,
        on_delete=models.CASCADE,
        related_name="columns",
        help_text="Source table this column belongs to",
    )

    source_column_physical_name = models.CharField(
        max_length=255, help_text="Physical column name in the source table"
    )

    source_column_datatype = models.CharField(
        max_length=255, help_text="Logical or physical data type of the column"
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the source column was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the source column was last updated"
    )

    class Meta:
        db_table = "source_column"
        unique_together = [["source_table", "source_column_physical_name"]]
        ordering = ["source_column_physical_name"]

    def __str__(self) -> str:
        return f"{self.source_table.physical_table_name}.{self.source_column_physical_name}"
