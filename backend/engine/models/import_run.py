"""
ImportRun model for TurboVault Engine.

Each invocation of the import pipeline (dry-run or real) is persisted as an
ImportRun. The full structured ImportReport is stored in JSON so the CLI can
display history and Studio can deep-link issues from its Job model.
"""

from __future__ import annotations

import uuid

from django.db import models

from engine.models.project import Project


class ImportRun(models.Model):
    """A single execution of the metadata import pipeline."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        PARTIAL_SUCCESS = "partial_success", "Partial success"
        FAILED = "failed", "Failed"
        VALIDATION_FAILED = "validation_failed", "Validation failed"

    import_run_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the import run",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="import_runs",
        help_text="Project this import targeted",
    )

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        help_text="Terminal status of the import",
    )

    is_dry_run = models.BooleanField(
        default=False,
        help_text="True if this was a validate-only run with no DB writes",
    )

    source_type = models.CharField(
        max_length=16,
        help_text="Source format: excel, sqlite, or json",
    )

    source_name = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Original filename or display name of the source",
    )

    conflict_strategy = models.CharField(
        max_length=32,
        default="merge",
        help_text="merge, replace_all, or update_only",
    )

    error_strategy = models.CharField(
        max_length=32,
        default="fail_fast",
        help_text="fail_fast or best_effort",
    )

    report = models.JSONField(
        default=dict,
        help_text="Full serialized ImportReport (issues, plan, counts, timings)",
    )

    error_count = models.PositiveIntegerField(default=0)
    warning_count = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(help_text="When the import pipeline began")
    finished_at = models.DateTimeField(
        null=True, blank=True, help_text="When the import pipeline terminated"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "import_run"
        indexes = [
            models.Index(fields=["project", "-started_at"]),
            models.Index(fields=["status"]),
        ]
        ordering = ["-started_at"]

    def __str__(self) -> str:
        kind = "dry-run" if self.is_dry_run else "import"
        return f"{kind} of {self.source_type} into {self.project.name} ({self.status})"
