"""Shared fixtures for import pipeline tests."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from engine.models import Project


@pytest.fixture
def project(db) -> Project:
    return Project.objects.create(name="Test Project", description="Pipeline tests")


@pytest.fixture
def workbook_factory(tmp_path: Path):
    """Build an Excel workbook from a dict of {sheet_name: [headers, *rows]}."""

    def _factory(sheets: dict[str, list[list]], filename: str = "metadata.xlsx") -> Path:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for name, rows in sheets.items():
            ws = wb.create_sheet(name)
            for row in rows:
                ws.append(row)
        out = tmp_path / filename
        wb.save(str(out))
        return out

    return _factory


@pytest.fixture
def minimal_workbook(workbook_factory) -> Path:
    """A workbook with one source table, one hub, and one satellite."""
    return workbook_factory(
        {
            "source_data": [
                [
                    "source_system",
                    "source_schema_physical_name",
                    "source_table_physical_name",
                    "source_table_identifier",
                    "record_source_column",
                    "load_date_column",
                ],
                ["crm", "crm_raw", "customer", "crm.customer", "crm.customer", "load_dt"],
            ],
            "standard_hub": [
                [
                    "target_hub_table_physical_name",
                    "hub_identifier",
                    "target_primary_key_physical_name",
                    "business_key_physical_name",
                    "source_table_identifier",
                    "source_column_physical_name",
                    "is_primary_source",
                ],
                [
                    "hub_customer",
                    "h_cust",
                    "hk_customer",
                    "customer_id",
                    "crm.customer",
                    "customer_id",
                    "TRUE",
                ],
            ],
            "standard_satellite": [
                [
                    "target_satellite_table_physical_name",
                    "parent_identifier",
                    "source_table_identifier",
                    "source_column_physical_name",
                    "target_column_physical_name",
                    "target_column_sort_order",
                ],
                [
                    "sat_customer_details",
                    "h_cust",
                    "crm.customer",
                    "name",
                    "name",
                    1,
                ],
                [
                    "sat_customer_details",
                    "h_cust",
                    "crm.customer",
                    "email",
                    "email",
                    2,
                ],
            ],
        }
    )
