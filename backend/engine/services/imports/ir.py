"""
Intermediate Representation produced by source parsers.

Parsers for tabular sources (Excel, SQLite) emit an `IRDocument`: a
source-agnostic representation of sheets/tables and their rows. The
validation and resolution stages consume this representation.

JSON imports skip this layer because the JSON format is already structured;
the JSON parser produces a `domain.DomainModel` directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class IRRow:
    """A single row in a sheet.

    `row_number` is 1-based and points at the spreadsheet/table row a user
    would see — header is row 1, first data row is row 2.
    """

    row_number: int
    values: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key.lower(), default)


@dataclass(slots=True)
class IRSheet:
    """One sheet/table from a tabular source."""

    name: str
    headers: list[str]  # already lowercased
    rows: list[IRRow] = field(default_factory=list)

    def has_column(self, column: str) -> bool:
        return column.lower() in self.headers


@dataclass(slots=True)
class IRDocument:
    """Top-level container for a parsed tabular source."""

    source_name: str
    sheets: dict[str, IRSheet] = field(default_factory=dict)

    def has_sheet(self, name: str) -> bool:
        return name in self.sheets

    def get_sheet(self, name: str) -> IRSheet | None:
        return self.sheets.get(name)
