"""
Staging column models for TurboVault Engine.

These models represent unified access to source columns, prejoin extractions
and derived columns.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from engine.models.project import Project
from engine.models.source_metadata import SourceColumn, SourceTable


class StagingColumn(models.Model):
    """
    A unified entry point for columns available in the staging layer.

    Wraps exactly one of a direct SourceColumn, a PrejoinExtractionColumn or a
    DerivedColumn, providing a consistent interface for mapping.
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
        help_text="Direct source column (exactly one of the three column kinds)",
    )

    prejoin_column = models.ForeignKey(
        "engine.PrejoinExtractionColumn",
        on_delete=models.CASCADE,
        related_name="staging_representations",
        null=True,
        blank=True,
        help_text="Prejoin extraction column (exactly one of the three column kinds)",
    )

    derived_column = models.ForeignKey(
        "engine.DerivedColumn",
        on_delete=models.CASCADE,
        related_name="staging_representations",
        null=True,
        blank=True,
        help_text="Derived column (exactly one of the three column kinds)",
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
        unique_together = [
            ["source_table", "source_column", "prejoin_column", "derived_column"]
        ]

    def clean(self) -> None:
        """Validate that exactly one column kind is set."""
        super().clean()

        kinds = sum(
            column is not None
            for column in (self.source_column, self.prejoin_column, self.derived_column)
        )
        if kinds == 0:
            raise ValidationError(
                "One of source_column, prejoin_column or derived_column must be specified."
            )
        if kinds > 1:
            raise ValidationError(
                "Only one of source_column, prejoin_column or derived_column can be specified."
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
        if self.derived_column:
            return self.derived_column.column_name
        return ""

    @property
    def datatype(self) -> str:
        """Returns the datatype of the underlying column."""
        if self.source_column:
            return self.source_column.source_column_datatype
        if self.prejoin_column:
            return self.prejoin_column.source_column.source_column_datatype
        if self.derived_column:
            return self.derived_column.datatype or ""
        return ""

    @property
    def description(self) -> str | None:
        """Description of the underlying column, inherited by Raw Vault columns."""
        if self.source_column:
            return self.source_column.description
        if self.prejoin_column:
            return self.prejoin_column.source_column.description
        if self.derived_column:
            return self.derived_column.description
        return None

    def __str__(self) -> str:
        if self.source_column:
            prefix = "[source]"
        elif self.prejoin_column:
            prefix = "[prejoin]"
        else:
            prefix = "[derived]"
        return f"{prefix} {self.source_table.physical_table_name}.{self.physical_name}"
