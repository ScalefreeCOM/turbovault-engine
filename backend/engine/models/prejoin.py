"""
Prejoin models for TurboVault Engine.

Prejoins allow joining source tables before mapping them to Data Vault entities,
enabling attributes from multiple source tables to be combined.
"""
from __future__ import annotations

import uuid
from django.db import models
from engine.models.project import Project
from engine.models.source_metadata import SourceTable, SourceColumn


class PrejoinDefinition(models.Model):
    """
    Definition of a join between two source tables.
    """
    
    class Operator(models.TextChoices):
        AND = 'AND', 'AND'
        OR = 'OR', 'OR'
    
    prejoin_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the prejoin definition"
    )
    
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="prejoins",
        help_text="Project this prejoin belongs to"
    )
    
    source_table = models.ForeignKey(
        SourceTable,
        on_delete=models.CASCADE,
        related_name="prejoins_as_source",
        help_text="Main source table (left side of join)"
    )
    
    prejoin_target_table = models.ForeignKey(
        SourceTable,
        on_delete=models.CASCADE,
        related_name="prejoins_as_target",
        help_text="Target table to join (right side of join)"
    )
    
    prejoin_condition_source_column = models.ManyToManyField(
        SourceColumn,
        related_name="prejoin_conditions_as_source",
        help_text="Join column(s) from the source table"
    )
    
    prejoin_condition_target_column = models.ManyToManyField(
        SourceColumn,
        related_name="prejoin_conditions_as_target",
        help_text="Join column(s) from the target table"
    )
    
    prejoin_operator = models.CharField(
        max_length=3,
        choices=Operator.choices,
        default=Operator.AND,
        help_text="Operator for combining multiple join conditions (AND/OR)"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the prejoin was created"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the prejoin was last updated"
    )
    
    class Meta:
        db_table = "prejoin_definition"
        ordering = ["source_table", "prejoin_target_table"]
        verbose_name = "Prejoin Definition"
        verbose_name_plural = "Prejoin Definitions"

    def __str__(self) -> str:
        return f"{self.source_table} -> {self.prejoin_target_table}"


class PrejoinExtractionColumn(models.Model):
    """
    A column extracted from the target table of a prejoin.
    """
    
    extraction_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the extraction column"
    )
    
    prejoin = models.ForeignKey(
        PrejoinDefinition,
        on_delete=models.CASCADE,
        related_name="extraction_columns",
        help_text="Prejoin definition this extraction belongs to"
    )
    
    source_column = models.ForeignKey(
        SourceColumn,
        on_delete=models.CASCADE,
        related_name="prejoin_extractions",
        help_text="Column from the target table to extract"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the extraction column was created"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the extraction column was last updated"
    )
    
    class Meta:
        db_table = "prejoin_extraction_column"
        unique_together = [["prejoin", "source_column"]]
        ordering = ["prejoin", "source_column"]
        verbose_name = "Prejoin Extraction Column"
        verbose_name_plural = "Prejoin Extraction Columns"

    def __str__(self) -> str:
        return f"{self.prejoin} [{self.source_column}]"
