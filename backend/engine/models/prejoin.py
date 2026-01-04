"""
Prejoin models for TurboVault Engine.

Prejoins enable joining source tables in the staging layer,
allowing links to reference columns from joined tables.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import models

if TYPE_CHECKING:
    pass


class PrejoinDefinition(models.Model):
    """
    Defines a join between a source table and a target table in staging.

    Enables extracting columns from the target table for use in Data Vault loading.
    """

    class JoinOperator(models.TextChoices):
        AND = "AND", "AND"
        OR = "OR", "OR"

    prejoin_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the prejoin definition",
    )

    project = models.ForeignKey(
        "Project",
        on_delete=models.CASCADE,
        related_name="prejoins",
        help_text="Project this prejoin belongs to",
    )

    source_table = models.ForeignKey(
        "SourceTable",
        on_delete=models.CASCADE,
        related_name="prejoins_as_source",
        help_text="Main source table (left side of join)",
    )

    prejoin_condition_source_column = models.ManyToManyField(
        "SourceColumn",
        related_name="prejoin_conditions_as_source",
        help_text="Join column(s) from the source table",
    )

    prejoin_target_table = models.ForeignKey(
        "SourceTable",
        on_delete=models.CASCADE,
        related_name="prejoins_as_target",
        help_text="Target table to join (right side of join)",
    )

    prejoin_condition_target_column = models.ManyToManyField(
        "SourceColumn",
        related_name="prejoin_conditions_as_target",
        help_text="Join column(s) from the target table",
    )

    prejoin_operator = models.CharField(
        max_length=3,
        choices=JoinOperator.choices,
        default=JoinOperator.AND,
        help_text="Operator for combining multiple join conditions (AND/OR)",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the prejoin was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the prejoin was last updated"
    )

    class Meta:
        db_table = "prejoin_definition"
        ordering = ["source_table", "prejoin_target_table"]
        verbose_name = "Prejoin Definition"
        verbose_name_plural = "Prejoin Definitions"

    def clean(self) -> None:
        """
        Validate prejoin configuration:
        - Join condition columns must belong to their respective tables
        - Must have at least one join condition
        """
        super().clean()

        # Validate after M2M are set
        if self.pk:
            # Check source columns belong to source table
            source_cols = self.prejoin_condition_source_column.all()
            for col in source_cols:
                if col.source_table_id != self.source_table_id:
                    raise ValidationError(
                        {
                            "prejoin_condition_source_column": f"Column '{col.source_column_physical_name}' does not belong to source table '{self.source_table.physical_table_name}'"
                        }
                    )

            # Check target columns belong to target table
            target_cols = self.prejoin_condition_target_column.all()
            for col in target_cols:
                if col.source_table_id != self.prejoin_target_table_id:
                    raise ValidationError(
                        {
                            "prejoin_condition_target_column": f"Column '{col.source_column_physical_name}' does not belong to target table '{self.prejoin_target_table.physical_table_name}'"
                        }
                    )

            # Check we have at least one condition
            if source_cols.count() == 0 or target_cols.count() == 0:
                raise ValidationError(
                    "Prejoin must have at least one join condition (source and target columns)"
                )

            # Check same number of columns on both sides
            if source_cols.count() != target_cols.count():
                raise ValidationError(
                    "Join conditions must have the same number of source and target columns"
                )

    def __str__(self) -> str:
        return f"{self.source_table.physical_table_name} -> {self.prejoin_target_table.physical_table_name}"


class PrejoinExtractionColumn(models.Model):
    """
    Defines a column extracted from a prejoin target table.

    These columns can be used in link source mappings instead of direct source columns.
    """

    extraction_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the extraction column",
    )

    prejoin = models.ForeignKey(
        PrejoinDefinition,
        on_delete=models.CASCADE,
        related_name="extraction_columns",
        help_text="Prejoin definition this extraction belongs to",
    )

    source_column = models.ForeignKey(
        "SourceColumn",
        on_delete=models.CASCADE,
        related_name="prejoin_extractions",
        help_text="Column from the target table to extract",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the extraction column was created"
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the extraction column was last updated"
    )

    class Meta:
        db_table = "prejoin_extraction_column"
        unique_together = [["prejoin", "source_column"]]
        ordering = ["prejoin", "source_column"]
        verbose_name = "Prejoin Extraction Column"
        verbose_name_plural = "Prejoin Extraction Columns"

    def clean(self) -> None:
        """
        Validate extraction column:
        - Must be from the prejoin's target table
        """
        super().clean()

        if self.source_column and self.prejoin:
            if (
                self.source_column.source_table_id
                != self.prejoin.prejoin_target_table_id
            ):
                raise ValidationError(
                    {
                        "source_column": f"Extraction column '{self.source_column.source_column_physical_name}' must be from prejoin target table '{self.prejoin.prejoin_target_table.physical_table_name}'"
                    }
                )

    def __str__(self) -> str:
        return f"{self.prejoin} -> {self.source_column.source_column_physical_name}"
