"""
Staging column models for TurboVault Engine.

These models represent unified access to source columns and prejoin extractions.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from engine.models.project import Project
from engine.models.source_metadata import SourceTable, SourceColumn


class StagingColumn(models.Model):
    """
    A unified entry point for columns available in the staging layer.

    Wraps either a direct SourceColumn or a PrejoinExtractionColumn,
    providing a consistent interface for mapping.
    """

    staging_column_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the staging column",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="staging_columns",
        help_text="Project this column belongs to",
    )

    source_table = models.ForeignKey(
        SourceTable,
        on_delete=models.CASCADE,
        related_name="staging_columns",
        help_text="The base source table this column is associated with in staging",
    )

    source_column = models.ForeignKey(
        SourceColumn,
        on_delete=models.CASCADE,
        related_name="staging_representations",
        null=True,
        blank=True,
        help_text="Direct source column (XOR with prejoin_column)",
    )

    prejoin_column = models.ForeignKey(
        "engine.PrejoinExtractionColumn",
        on_delete=models.CASCADE,
        related_name="staging_representations",
        null=True,
        blank=True,
        help_text="Prejoin extraction column (XOR with source_column)",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the staging column was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the staging column was last updated"
    )

    class Meta:
        db_table = "staging_column"
        verbose_name = "Staging Column"
        verbose_name_plural = "Staging Columns"
        unique_together = [["source_table", "source_column", "prejoin_column"]]

    def clean(self) -> None:
        """Validate XOR: exactly one of source_column or prejoin_column."""
        super().clean()

        has_source = self.source_column is not None
        has_prejoin = self.prejoin_column is not None

        if not (has_source or has_prejoin):
            raise ValidationError(
                "Either source_column or prejoin_column must be specified."
            )

        if has_source and has_prejoin:
            raise ValidationError(
                "Cannot specify both source_column and prejoin_column."
            )
            
    @property
    def physical_name(self) -> str:
        """Returns the physical name of the underlying column."""
        if self.source_column:
            return self.source_column.source_column_physical_name
        if self.prejoin_column:
            # If alias exists, use it, otherwise use physical name from prejoin's source_column
            return (
                self.prejoin_column.prejoin_target_column_alias 
                or self.prejoin_column.source_column.source_column_physical_name
            )
        return ""

    @property
    def datatype(self) -> str:
        """Returns the datatype of the underlying column."""
        if self.source_column:
            return self.source_column.source_column_datatype
        if self.prejoin_column:
            return self.prejoin_column.source_column.source_column_datatype
        return ""

    def __str__(self) -> str:
        prefix = "[source]" if self.source_column else "[prejoin]"
        return f"{prefix} {self.source_table.physical_table_name}.{self.physical_name}"
