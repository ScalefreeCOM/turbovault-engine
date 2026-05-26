"""SQLite parser: sqlite3 database → IRDocument.

The SQLite source format mirrors the Excel format one-to-one (each sheet is
a table named the same as the Excel sheet, with the same lowercased column
headers). So the output IR is identical to what Excel produces.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from engine.services.imports.errors import Code, PipelineAbort, make_issue
from engine.services.imports.ir import IRDocument, IRRow, IRSheet
from engine.services.imports.parsers.base import clean
from engine.services.imports.types import IssueLocation


def parse_sqlite(path: Path) -> IRDocument:
    """Read a SQLite database file into an IRDocument."""
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
        conn = sqlite3.connect(str(path))
    except sqlite3.DatabaseError as exc:
        raise PipelineAbort(
            make_issue(
                severity="error",
                code=Code.SOURCE_UNREADABLE,
                stage="parse",
                message=f"Could not open SQLite database: {exc}",
                location=IssueLocation(file=str(path)),
                suggestion="Confirm the file is a valid SQLite database.",
            )
        ) from exc

    doc = IRDocument(source_name=path.name)
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = [row[0] for row in cur.fetchall()]
        if not table_names:
            raise PipelineAbort(
                make_issue(
                    severity="error",
                    code=Code.SOURCE_EMPTY,
                    stage="parse",
                    message="The database contains no tables.",
                    location=IssueLocation(file=str(path)),
                )
            )

        for table_name in table_names:
            sheet = _read_table(conn, table_name)
            if sheet is not None:
                doc.sheets[table_name] = sheet
    finally:
        conn.close()

    return doc


def _read_table(conn: sqlite3.Connection, table_name: str) -> IRSheet | None:
    try:
        cur = conn.execute(f"SELECT * FROM [{table_name}]")
    except sqlite3.OperationalError:
        return None

    description = cur.description
    if not description:
        return None

    headers = [d[0].lower() for d in description]
    sheet = IRSheet(name=table_name, headers=headers)

    # In SQLite there is no "header row" to skip — row numbers start at 1
    # in the data, but for user-facing diagnostics we still want a number
    # that matches the equivalent Excel sheet, so we start at 2.
    for offset, raw in enumerate(cur.fetchall(), start=2):
        values = {col: clean(raw[i]) for i, col in enumerate(headers)}
        # Skip fully empty rows.
        if all(v is None for v in values.values()):
            continue
        sheet.rows.append(IRRow(row_number=offset, values=values))

    return sheet
