"""Helpers for emitting `ProgressEvent`s from inside pipeline stages."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from engine.services.imports.domain import DomainModel
from engine.services.imports.ir import IRDocument
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


def read_counts(
    ir_doc: IRDocument | None, domain: DomainModel | None
) -> dict[str, int]:
    """What the parse stage read, as the parser models it.

    A tabular source (Excel, SQLite) is sheets of rows: rows by sheet name.
    Any other source is a domain model: entities by kind, every kind present.
    """
    if ir_doc is not None:
        return {name: len(sheet.rows) for name, sheet in ir_doc.sheets.items()}
    if domain is None:
        return {}
    systems = _unique(domain.source_systems.values())
    tables = _unique(table for system in systems for table in system.tables.values())
    return {
        "source_system": len(systems),
        "source_table": len(tables),
        "source_column": sum(len(_unique(table.columns.values())) for table in tables),
        "hub": len(_unique(domain.hubs.values())),
        "link": len(_unique(domain.links.values())),
        "satellite": len(_unique(domain.satellites.values())),
        "pit": len(_unique(domain.pits.values())),
        "reference_table": len(_unique(domain.reference_tables.values())),
        "snapshot_control": len(_unique(domain.snapshot_controls.values())),
        "prejoin": len(domain.prejoins),
    }


def _unique[T](items: Iterable[T]) -> list[T]:
    """Each object once: the domain model's dicts also key some by an alias
    (a source table by its qualified and its plain identifier)."""
    return list({id(item): item for item in items}.values())
