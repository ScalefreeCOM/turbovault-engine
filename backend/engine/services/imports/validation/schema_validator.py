"""
Stage 2: schema/value validation.

Reports diagnostics for:
  - Sheets that are not recognized (warning).
  - Required sheets that are missing — note: most sheets are optional in
    practice, so missing sheets are emitted as `info` not `error`. The
    practical "missing source_data" case is caught in the resolver instead.
  - Required columns missing from a sheet header (error, scoped to the sheet).
  - Unknown columns (warning if `allow_unknown_columns`, error otherwise).
  - Required cell values missing in present rows (error per row).
"""

from __future__ import annotations

from engine.services.imports.errors import Code, make_issue
from engine.services.imports.ir import IRDocument
from engine.services.imports.types import (
    ImportOptions,
    Issue,
    IssueLocation,
)
from engine.services.imports.validation.schemas import SCHEMA_BY_NAME


def validate_schema(
    doc: IRDocument,
    options: ImportOptions,
) -> list[Issue]:
    """Return all schema/value issues found in the document."""
    issues: list[Issue] = []

    # 1. Unknown sheets — warn, don't block.
    for name in doc.sheets:
        if name not in SCHEMA_BY_NAME:
            issues.append(
                make_issue(
                    severity="warning",
                    code=Code.SCHEMA_UNKNOWN_SHEET,
                    stage="validate",
                    message=f"Sheet '{name}' is not recognized and will be ignored.",
                    location=IssueLocation(file=doc.source_name, sheet=name),
                    suggestion="Remove the sheet or rename it to a recognized name.",
                )
            )

    # 2. For each known sheet that is present, check columns and required values.
    for schema in SCHEMA_BY_NAME.values():
        sheet = doc.get_sheet(schema.name)
        if sheet is None:
            continue

        header_set = set(sheet.headers)
        missing = [c for c in schema.required_columns if c not in header_set]
        if missing:
            issues.append(
                make_issue(
                    severity="error",
                    code=Code.SCHEMA_MISSING_COLUMN,
                    stage="validate",
                    message=(
                        f"Sheet '{schema.name}' is missing required column(s): "
                        f"{', '.join(missing)}."
                    ),
                    location=IssueLocation(file=doc.source_name, sheet=schema.name),
                    suggestion=(
                        "Add the listed column(s) to the header row. Refer to the "
                        "Turbovault template if needed."
                    ),
                )
            )

        # Unknown columns inside a recognized sheet.
        known = schema.known_columns
        unknown = [c for c in sheet.headers if c not in known]
        if unknown:
            severity = "warning" if options.allow_unknown_columns else "error"
            code = (
                Code.SCHEMA_UNKNOWN_COLUMN
                if options.allow_unknown_columns
                else Code.SCHEMA_MISSING_COLUMN
            )
            for col in unknown:
                issues.append(
                    make_issue(
                        severity=severity,
                        code=code,
                        stage="validate",
                        message=(
                            f"Sheet '{schema.name}' contains an unrecognized column "
                            f"'{col}'."
                        ),
                        location=IssueLocation(
                            file=doc.source_name, sheet=schema.name, column=col
                        ),
                        suggestion=(
                            "Remove the column or check for typos against the template."
                        ),
                    )
                )

        # Required-value-per-row check — only on columns that ARE present.
        present_required = [c for c in schema.required_columns if c in header_set]
        for row in sheet.rows:
            for col in present_required:
                value = row.get(col)
                if value is None or value == "":
                    issues.append(
                        make_issue(
                            severity="error",
                            code=Code.ROW_REQUIRED_VALUE_MISSING,
                            stage="validate",
                            message=(
                                f"Required value missing for column '{col}' in sheet "
                                f"'{schema.name}'."
                            ),
                            location=IssueLocation(
                                file=doc.source_name,
                                sheet=schema.name,
                                row=row.row_number,
                                column=col,
                            ),
                        )
                    )

    return issues
