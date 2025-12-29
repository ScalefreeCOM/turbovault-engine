"""
Snapshot control models for TurboVault Engine.

These models define snapshot behavior for reference tables and PIT structures:
- SnapshotControlTable: Global snapshot configuration with date ranges
- SnapshotControlLogic: Reusable snapshot logic patterns
"""
from __future__ import annotations

import uuid
from datetime import date, time
from typing import Optional

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.db import models

from engine.models.project import Project


def default_snapshot_start_date() -> date:
    """
    Return the beginning of the year 5 years ago.
    Default start date for snapshot control.
    """
    today = date.today()
    five_years_ago = today - relativedelta(years=5)
    return date(five_years_ago.year, 1, 1)


def default_snapshot_end_date() -> date:
    """
    Return the end of the year 5 years from now.
    Default end date for snapshot control.
    """
    today = date.today()
    five_years_ahead = today + relativedelta(years=5)
    return date(five_years_ahead.year, 12, 31)


class SnapshotControlTable(models.Model):
    """
    Stores global snapshot configuration.
    
    Defines the overall time window and daily snapshot time for
    reference table historization and PIT structures.
    """
    
    snapshot_control_table_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the snapshot control table"
    )
    
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="snapshot_controls",
        help_text="Project this snapshot control belongs to"
    )
    
    name = models.CharField(
        max_length=255,
        default="control_snap",
        help_text="Base name of the snapshot control (e.g., 'control_snap')"
    )
    
    snapshot_start_date = models.DateField(
        default=default_snapshot_start_date,
        help_text="Start date for snapshot range (default: beginning of current year - 5)"
    )
    
    snapshot_end_date = models.DateField(
        default=default_snapshot_end_date,
        help_text="End date for snapshot range (default: end of current year + 5)"
    )
    
    daily_snapshot_time = models.TimeField(
        default=time(8, 0, 0),
        help_text="Daily snapshot time (default: 08:00:00)"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the snapshot control table was created"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the snapshot control table was last updated"
    )
    
    class Meta:
        db_table = "snapshot_control_table"
        ordering = ["project", "snapshot_start_date"]
    
    def __str__(self) -> str:
        return f"Snapshot Control ({self.snapshot_start_date} to {self.snapshot_end_date})"


class SnapshotControlLogic(models.Model):
    """
    Defines reusable snapshot logic patterns.
    
    Specifies when and how long snapshots should be retained based on
    various time components (daily, weekly, monthly, etc.).
    """
    
    class SnapshotComponent(models.TextChoices):
        DAILY = 'daily', 'Daily'
        BEGINNING_OF_WEEK = 'beginning_of_week', 'Beginning of Week'
        END_OF_WEEK = 'end_of_week', 'End of Week'
        BEGINNING_OF_MONTH = 'beginning_of_month', 'Beginning of Month'
        END_OF_MONTH = 'end_of_month', 'End of Month'
        BEGINNING_OF_QUARTER = 'beginning_of_quarter', 'Beginning of Quarter'
        END_OF_QUARTER = 'end_of_quarter', 'End of Quarter'
        BEGINNING_OF_YEAR = 'beginning_of_year', 'Beginning of Year'
        END_OF_YEAR = 'end_of_year', 'End of Year'
    
    class SnapshotUnit(models.TextChoices):
        DAY = 'DAY', 'Day'
        WEEK = 'WEEK', 'Week'
        MONTH = 'MONTH', 'Month'
        QUARTER = 'QUARTER', 'Quarter'
        YEAR = 'YEAR', 'Year'
    
    snapshot_control_logic_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the snapshot logic entry"
    )
    
    snapshot_control_table = models.ForeignKey(
        SnapshotControlTable,
        on_delete=models.CASCADE,
        related_name="logic_rules",
        help_text="Snapshot control table this logic belongs to"
    )
    
    snapshot_control_logic_column_name = models.CharField(
        max_length=255,
        help_text="Column name for this snapshot logic in generated structures"
    )
    
    snapshot_component = models.CharField(
        max_length=30,
        choices=SnapshotComponent.choices,
        help_text="When to take snapshots (daily, beginning/end of week/month/quarter/year)"
    )
    
    snapshot_duration = models.IntegerField(
        blank=True,
        null=True,
        help_text="Duration value for snapshot retention (e.g., 3, 6, 12)"
    )
    
    snapshot_unit = models.CharField(
        max_length=10,
        choices=SnapshotUnit.choices,
        blank=True,
        null=True,
        help_text="Unit for duration: DAY, WEEK, MONTH, QUARTER, YEAR"
    )
    
    snapshot_forever = models.BooleanField(
        default=False,
        help_text="If true, snapshots are kept indefinitely (duration and unit must be NULL)"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the snapshot logic was created"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the snapshot logic was last updated"
    )
    
    class Meta:
        db_table = "snapshot_control_logic"
        ordering = ["snapshot_control_table", "snapshot_component"]
    
    def clean(self) -> None:
        """
        Validate snapshot duration logic:
        - If snapshot_forever is True, duration and unit must be NULL
        - If snapshot_forever is False, duration and unit should be provided
        """
        super().clean()
        
        if self.snapshot_forever:
            if self.snapshot_duration is not None or self.snapshot_unit is not None:
                raise ValidationError({
                    'snapshot_forever': 'When snapshot_forever is True, duration and unit must be NULL.'
                })
        else:
            # Warning (not error) if duration/unit not provided when not forever
            if self.snapshot_duration is None or self.snapshot_unit is None:
                raise ValidationError({
                    'snapshot_duration': 'Duration and unit should be provided when snapshot_forever is False.',
                    'snapshot_unit': 'Duration and unit should be provided when snapshot_forever is False.'
                })
    
    def __str__(self) -> str:
        if self.snapshot_forever:
            return f"{self.snapshot_component} (Forever)"
        return f"{self.snapshot_component} ({self.snapshot_duration} {self.snapshot_unit})"
