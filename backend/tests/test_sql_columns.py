"""Which columns an SQL expression reads (``src_cols_required``)."""

from __future__ import annotations

import pytest
from engine.services.sql_columns import referenced_columns

COLUMNS = ["CUSTOMER_ID", "First Name", "status", "Amount"]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        # Bare identifiers match case-insensitively; the known spelling wins.
        ("upper(customer_id)", ["CUSTOMER_ID"]),
        # Order of first appearance, each once.
        ("COALESCE(status, customer_id, STATUS)", ["status", "CUSTOMER_ID"]),
        # Quoted identifiers in every dialect's style.
        ('TRIM("First Name")', ["First Name"]),
        ("TRIM(`First Name`) || [Amount]", ["First Name", "Amount"]),
        # Not inside a string literal, even with an escaped quote.
        ("CASE WHEN status = 'it''s amount' THEN 1 END", ["status"]),
        # Not inside comments.
        ("amount -- customer_id is legacy\n/* status */ + 1", ["Amount"]),
        # Nothing known.
        ("CURRENT_TIMESTAMP", []),
        ("", []),
    ],
)
def test_referenced_columns(expression, expected):
    assert referenced_columns(expression, COLUMNS) == expected


def test_no_known_columns():
    assert referenced_columns("customer_id", []) == []
