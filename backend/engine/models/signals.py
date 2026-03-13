"""
Django signals for TurboVault Engine models.
"""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from engine.models.prejoin import PrejoinExtractionColumn
from engine.models.source_metadata import SourceColumn
from engine.services.staging_service import get_or_create_staging_column


@receiver(post_save, sender=SourceColumn)
def sync_staging_on_source_column_save(sender, instance, created, **kwargs) -> None:
    """Automatically create/update StagingColumn when a SourceColumn is saved."""
    get_or_create_staging_column(instance)


@receiver(post_save, sender=PrejoinExtractionColumn)
def sync_staging_on_prejoin_column_save(sender, instance, created, **kwargs) -> None:
    """Automatically create/update StagingColumn when a PrejoinExtractionColumn is saved."""
    get_or_create_staging_column(instance)
