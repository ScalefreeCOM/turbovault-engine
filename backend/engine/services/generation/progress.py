"""Helpers for emitting `ProgressEvent`s from inside pipeline stages."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from engine.services.generation.types import (
    PipelineStage,
    ProgressEvent,
    ProgressStatus,
)

ProgressCallback = Callable[[ProgressEvent], None]


def emit(
    callback: ProgressCallback | None,
    *,
    stage: PipelineStage,
    status: ProgressStatus,
    message: str,
    current: int | None = None,
    total: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Send one event to *callback*, if there is one.

    An ``Exception`` from the callback is swallowed: a misbehaving progress
    consumer must never fail the run. Anything else it raises (a
    ``BaseException`` such as ``KeyboardInterrupt``, or one a caller raises to
    stop the run at a safe point) propagates out of the pipeline unchanged.
    """
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
                detail=detail,
            )
        )
    except Exception:
        # Progress callback failures must never abort the pipeline.
        pass
