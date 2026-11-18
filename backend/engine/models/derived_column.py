"""
Derived column model for TurboVault Engine.

A derived column is a column the stage computes with a SQL expression rather
than reading it from the source table, e.g. ``TRIM(first_name) || ' ' ||
TRIM(last_name)``. It belongs to one source table and, through its
``StagingColumn``, can be mapped anywhere a source column can: hub business
keys, link keys and payload, satellite payload.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from engine.models.project import Project
from engine.models.source_metadata import SourceTable


class DerivedColumn(models.Model):
    """A column computed in the stage from the source table's columns."""

    derived_column_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the derived column",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="derived_columns",
        help_text="Project this derived column belongs to",
    )

    source_table = models.ForeignKey(
        SourceTable,
        on_delete=models.CASCADE,
        related_name="derived_columns",
        help_text="Source table whose stage computes this column",
    )

    column_name = models.CharField(
        max_length=255,
        help_text="Name of the column in the stage (e.g. customer_full_name)",
    )

    expression = models.TextField(
        help_text=(
            "SQL expression that computes the value from the source table's "
            "columns, in the target platform's dialect"
        ),
    )

    datatype = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=(
            "Data type of the computed value. datavault4dbt needs it to build "
            "ghost records for an expression"
        ),
    )

    description = models.TextField(
        blank=True,
        null=True,
        help_text="Optional description, inherited by Raw Vault columns loaded from it",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the derived column was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the derived column was last updated"
    )

    class Meta:
        db_table = "derived_column"
        unique_together = [["source_table", "column_name"]]
        ordering = ["source_table", "column_name"]
        verbose_name = "Derived Column"
        verbose_name_plural = "Derived Columns"

    def clean(self) -> None:
        """A derived column needs an expression, and a name no prejoin uses.

        A derived column may take the name of a source column of its table:
        it then shadows that column. datavault4dbt's stage replaces the
        source column with the derived value, so everything that maps the
        source column reads the derived one. A column a prejoin brings in
        can't be shadowed.
        """
        super().clean()

        if not (self.expression or "").strip():
            raise ValidationError(
                {"expression": "A derived column needs an expression."}
            )

        if not self.source_table_id or not self.column_name:
            return

        name = self.column_name.lower()
        from engine.models.prejoin import PrejoinExtractionColumn

        prejoined = {
            (
                extraction.prejoin_target_column_alias
                or extraction.source_column.source_column_physical_name
            ).lower()
            for extraction in PrejoinExtractionColumn.objects.filter(
                prejoin__source_table_id=self.source_table_id
            ).select_related("source_column")
        }
        if name in prejoined:
            raise ValidationError(
                {
                    "column_name": (
                        f"'{self.column_name}' is a column a prejoin brings into "
                        f"{self.source_table.physical_table_name}'s stage."
                    )
                }
            )

    @property
    def shadowed_column(self):
        """The source column of the table this derived column replaces, if any."""
        return self.source_table.columns.filter(
            source_column_physical_name__iexact=self.column_name
        ).first()

    def __str__(self) -> str:
        return f"{self.source_table.physical_table_name}.{self.column_name}"
