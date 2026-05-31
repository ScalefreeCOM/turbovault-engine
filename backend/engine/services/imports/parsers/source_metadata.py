"""Parser for the ``source_metadata`` import format.

Consumes a small, versioned JSON document that describes only source-side
metadata — systems, tables, columns. Hubs / links / satellites are
deliberately out of scope: this format is the contract used by external
producers (notably the Studio's live-database connector subsystem) that
have no knowledge of Data Vault modeling.

Why a separate parser from ``JsonSource`` / ``ProjectExport``?

* ``ProjectExport`` describes a complete TurboVault project (sources +
  hubs + links + satellites + …). Forcing live-DB metadata producers to
  emit empty hubs/links/sats would be awkward and error-prone.
* The two formats need to evolve independently. ``ProjectExport`` is
  rev-locked to the engine's own export shape; this format is a stable
  public contract versioned via ``format_version``.

Description fields are accepted on systems, tables, and columns. They are
silently dropped today because the source-metadata models don't carry
description columns yet; once they do, this parser will populate them
without a schema change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from engine.services.imports.domain import (
    DomainModel,
    DSourceColumn,
    DSourceSystem,
    DSourceTable,
)
from engine.services.imports.errors import Code, PipelineAbort, make_issue
from engine.services.imports.types import IssueLocation

# Stable public constants (consumed by docs + producers).
FORMAT_NAME: str = "source_metadata"
SUPPORTED_FORMAT_VERSIONS: tuple[int, ...] = (1,)


# ---------------------------------------------------------------------------
# v1 schema — Pydantic models with ``extra="forbid"`` so typos surface as
# validation errors instead of silently dropping data.
# ---------------------------------------------------------------------------


class _ColumnV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    physical_name: str
    datatype: str
    ordinal_position: int | None = None
    is_nullable: bool | None = None
    # Accepted but ignored until the engine's SourceColumn model grows a
    # description column. Producers should populate it today; we don't
    # want a schema change later.
    description: str | None = None


class _TableV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    physical_table_name: str
    alias: str | None = None
    record_source_value: str | None = None
    static_part_of_record_source: str | None = None
    load_date_value: str | None = None
    description: str | None = None
    columns: list[_ColumnV1] = Field(default_factory=list)


class _SystemV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    schema_name: str
    database_name: str | None = None
    description: str | None = None
    tables: list[_TableV1] = Field(default_factory=list)


class SourceMetadataV1(BaseModel):
    """Top-level payload of a ``source_metadata`` v1 document."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["source_metadata"] = "source_metadata"
    format_version: Literal[1] = 1
    source_systems: list[_SystemV1] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser entry point
# ---------------------------------------------------------------------------


def parse_source_metadata(path: Path) -> DomainModel:
    """Read and validate a source_metadata document; return a DomainModel.

    Only the source-system part of the domain is populated. The planner
    treats the empty hub/link/satellite sets as "no change" under merge
    strategy, leaving downstream entities untouched.
    """
    if not path.exists():
        raise PipelineAbort(
            make_issue(
                severity="error",
                code=Code.SOURCE_UNREADABLE,
                stage="parse",
                message=f"File not found: {path}",
                location=IssueLocation(file=str(path)),
            )
        )

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PipelineAbort(
            make_issue(
                severity="error",
                code=Code.SOURCE_UNREADABLE,
                stage="parse",
                message=f"Could not read source file: {exc}",
                location=IssueLocation(file=str(path)),
            )
        ) from exc

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise PipelineAbort(
            make_issue(
                severity="error",
                code=Code.SOURCE_INVALID_JSON,
                stage="parse",
                message=f"The file is not valid JSON: {exc.msg} (line {exc.lineno}).",
                location=IssueLocation(file=str(path), row=exc.lineno),
                suggestion="Re-collect the metadata via the connector and try again.",
            )
        ) from exc

    # Version handshake before schema validation so the operator gets a
    # targeted error message rather than a wall of Pydantic complaints.
    if isinstance(data, dict):
        version = data.get("format_version")
        if (
            version is not None
            and isinstance(version, int)
            and version not in SUPPORTED_FORMAT_VERSIONS
        ):
            raise PipelineAbort(
                make_issue(
                    severity="error",
                    code=Code.SOURCE_INVALID_JSON,
                    stage="parse",
                    message=(
                        f"Unsupported {FORMAT_NAME} format_version: {version}. "
                        f"Supported versions: {sorted(SUPPORTED_FORMAT_VERSIONS)}."
                    ),
                    location=IssueLocation(file=str(path)),
                    suggestion=(
                        "Upgrade the engine, or downgrade the producer to emit a "
                        "supported format_version."
                    ),
                )
            )

    try:
        payload = SourceMetadataV1.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else None
        msg = (
            f"JSON does not match {FORMAT_NAME} schema: {first.get('msg')}"
            if first
            else f"JSON does not match {FORMAT_NAME} schema."
        )
        raise PipelineAbort(
            make_issue(
                severity="error",
                code=Code.SOURCE_INVALID_JSON,
                stage="parse",
                message=msg,
                location=IssueLocation(file=str(path)),
                suggestion="Re-collect the metadata via the connector and try again.",
            )
        ) from exc

    return _payload_to_domain(payload)


# ---------------------------------------------------------------------------
# Payload → DomainModel
# ---------------------------------------------------------------------------


def _payload_to_domain(payload: SourceMetadataV1) -> DomainModel:
    model = DomainModel()
    for sys_def in payload.source_systems:
        system = DSourceSystem(
            name=sys_def.name,
            schema_name=sys_def.schema_name,
            database_name=sys_def.database_name,
        )
        for table_def in sys_def.tables:
            identifier = f"{sys_def.name}|{table_def.physical_table_name}"
            # ``record_source_value`` defaults to the system name when the
            # producer didn't supply one. Live-DB collectors don't know what
            # the project's convention should be; the system name is the
            # safest default the engine can apply.
            record_source = (
                table_def.record_source_value
                if table_def.record_source_value
                else sys_def.name
            )
            table = DSourceTable(
                identifier=identifier,
                physical_name=table_def.physical_table_name,
                alias=table_def.alias or "",
                record_source_value=record_source,
                static_part_of_record_source=(
                    table_def.static_part_of_record_source or ""
                ),
                load_date_value=table_def.load_date_value or "sysdate()",
            )
            for col_def in table_def.columns:
                table.columns[col_def.physical_name.lower()] = DSourceColumn(
                    name=col_def.physical_name,
                    datatype=col_def.datatype,
                )
            system.tables[identifier] = table
            # Mirror the JSON parser: also index by raw physical name so
            # any future downstream lookups can find the table without
            # constructing the synthetic identifier.
            system.tables.setdefault(table_def.physical_table_name, table)
        model.source_systems[sys_def.name] = system
    return model
