"""
GenerationRun model for TurboVault Engine.

Each invocation of the generation pipeline (dbt build, JSON export, DBML
export — real or dry-run) is persisted as a GenerationRun. The full
structured GenerationReport is stored in JSON so the CLI can display
history and Studio can deep-link issues from its Job model.
"""

from __future__ import annotations

import uuid

from django.db import models

from engine.models.project import Project


class GenerationRun(models.Model):
    """A single execution of the generation pipeline."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        PARTIAL_SUCCESS = "partial_success", "Partial success"
        FAILED = "failed", "Failed"
        VALIDATION_FAILED = "validation_failed", "Validation failed"

    generation_run_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the generation run",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="generation_runs",
        help_text="Project this generation targeted",
    )

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        help_text="Terminal status of the generation",
    )

    is_dry_run = models.BooleanField(
        default=False,
        help_text="True if no files were written to disk",
    )

    output_type = models.CharField(
        max_length=16,
        help_text="Output format: dbt, json, or dbml",
    )

    output_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Destination path requested by the caller (empty for dry-run / preview)",
    )

    error_strategy = models.CharField(
        max_length=32,
        default="best_effort",
        help_text="fail_fast or best_effort",
    )

    report = models.JSONField(
        default=dict,
        help_text="Full serialized GenerationReport (plan, artifacts, issues, timings)",
    )

    error_count = models.PositiveIntegerField(default=0)
    warning_count = models.PositiveIntegerField(default=0)
    files_generated = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(help_text="When the generation pipeline began")
    finished_at = models.DateTimeField(
        null=True, blank=True, help_text="When the generation pipeline terminated"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "generation_run"
        indexes = [
            models.Index(fields=["project", "-started_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["output_type"]),
        ]
        ordering = ["-started_at"]

    def __str__(self) -> str:
        kind = "dry-run" if self.is_dry_run else "generation"
        return f"{kind} of {self.output_type} for {self.project.name} ({self.status})"
