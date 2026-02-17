"""
Service for managing StagingColumn synchronization.
"""

from __future__ import annotations

from engine.models.project import Project
from engine.models.source_metadata import SourceColumn
from engine.models.prejoin import PrejoinExtractionColumn
from engine.models.staging import StagingColumn


def get_or_create_staging_column(column_instance: SourceColumn | PrejoinExtractionColumn) -> StagingColumn:
    """
    Ensures a StagingColumn exists for the given SourceColumn or PrejoinExtractionColumn.
    """
    if isinstance(column_instance, SourceColumn):
        staging_col, _ = StagingColumn.objects.get_or_create(
            project=column_instance.source_table.project,
            source_table=column_instance.source_table,
            source_column=column_instance,
            prejoin_column=None,
        )
        return staging_col
    
    if isinstance(column_instance, PrejoinExtractionColumn):
        # Prejoin columns are logically associated with the source_table of their prejoin definition
        staging_col, _ = StagingColumn.objects.get_or_create(
            project=column_instance.prejoin.project,
            source_table=column_instance.prejoin.source_table,
            source_column=None,
            prejoin_column=column_instance,
        )
        return staging_col
    
    raise ValueError(f"Unsupported column type: {type(column_instance)}")


def sync_staging_columns(project: Project) -> None:
    """
    Synchronizes all SourceColumns and PrejoinExtractionColumns for a project 
    into the StagingColumn unified entity.
    """
    # Sync SourceColumns
    for col in SourceColumn.objects.filter(source_table__project=project):
        get_or_create_staging_column(col)
        
    # Sync PrejoinExtractionColumns
    for col in PrejoinExtractionColumn.objects.filter(prejoin__project=project):
        get_or_create_staging_column(col)
