"""Helpers for emitting `ProgressEvent`s from inside pipeline stages."""

from __future__ import annotations

from collections.abc import Callable

from engine.services.imports.types import PipelineStage, ProgressEvent, ProgressStatus

ProgressCallback = Callable[[ProgressEvent], None]


def emit(
    callback: ProgressCallback | None,
    *,
    stage: PipelineStage,
    status: ProgressStatus,
    message: str,
    current: int | None = None,
    total: int | None = None,
) -> None:
    """Safe emit: never raises if the callback misbehaves."""
    if callback is None:
        return
    try:
        callback(
            ProgressEvent(
                stage=stage,
                status=status,
                message=message,
                current=current,
                total=total,
            )
        )
    except Exception:
        # Progress callback failures must never abort the pipeline.
        pass
