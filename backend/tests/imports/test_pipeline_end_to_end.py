"""End-to-end tests for the import pipeline.

Each test runs the full parse → validate → resolve → plan → execute → report
pipeline against a small Excel fixture and asserts both the database state
and the structured ImportReport.
"""

from __future__ import annotations

import pytest

from engine.models import (
    Hub,
    HubColumn,
    HubSourceMapping,
    ImportRun,
    Satellite,
    SatelliteColumn,
    SourceColumn,
    SourceSystem,
    SourceTable,
)
from engine.services.imports import (
    ExcelSource,
    ImportOptions,
    import_metadata,
)


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_creates_expected_entities(project, minimal_workbook):
    report = import_metadata(
        project=project,
        source=ExcelSource(path=minimal_workbook),
        options=ImportOptions(conflict_strategy="merge", skip_snapshots=True),
    )

    assert report.status == "success"
    assert report.error_count == 0

    # Source layer
    assert SourceSystem.objects.filter(project=project, name="crm").count() == 1
    assert (
        SourceTable.objects.filter(
            source_system__project=project, physical_table_name="customer"
        ).count()
        == 1
    )
    # Source columns are created on-demand by mappings:
    # customer_id (hub key), name + email (sat columns).
    cols = set(
        SourceColumn.objects.filter(
            source_table__source_system__project=project
        ).values_list("source_column_physical_name", flat=True)
    )
    assert {"customer_id", "name", "email"} <= cols

    # Hub
    hub = Hub.objects.get(project=project, hub_physical_name="hub_customer")
    assert hub.hub_type == "standard"
    assert hub.hub_hashkey_name == "hk_customer"
    bk = HubColumn.objects.get(hub=hub, column_name="customer_id")
    assert bk.column_type == "business_key"
    mapping = HubSourceMapping.objects.get(hub_column=bk)
    assert mapping.is_primary_source is True

    # Satellite
    sat = Satellite.objects.get(
        project=project, satellite_physical_name="sat_customer_details"
    )
    assert sat.satellite_type == "standard"
    assert sat.parent_hub_id == hub.hub_id
    assert SatelliteColumn.objects.filter(satellite=sat).count() == 2


# ---------------------------------------------------------------------------
# Re-import (the bug the user called out)
# ---------------------------------------------------------------------------


def test_reimport_same_file_does_not_duplicate(project, minimal_workbook):
    # First import
    report1 = import_metadata(
        project=project,
        source=ExcelSource(path=minimal_workbook),
        options=ImportOptions(conflict_strategy="merge", skip_snapshots=True),
    )
    assert report1.status == "success"

    # Second import (this used to fail in the old code)
    report2 = import_metadata(
        project=project,
        source=ExcelSource(path=minimal_workbook),
        options=ImportOptions(conflict_strategy="merge", skip_snapshots=True),
    )
    assert report2.status == "success", report2.issues

    assert Hub.objects.filter(project=project, hub_physical_name="hub_customer").count() == 1
    assert (
        Satellite.objects.filter(
            project=project, satellite_physical_name="sat_customer_details"
        ).count()
        == 1
    )
    assert SatelliteColumn.objects.filter(satellite__project=project).count() == 2


def test_reimport_with_updated_fields_picks_up_changes(project, workbook_factory):
    base_sheets = {
        "source_data": [
            [
                "source_system",
                "source_schema_physical_name",
                "source_table_physical_name",
                "source_table_identifier",
            ],
            ["crm", "crm_raw", "customer", "crm.customer"],
        ],
        "standard_hub": [
            [
                "target_hub_table_physical_name",
                "hub_identifier",
                "target_primary_key_physical_name",
                "business_key_physical_name",
                "source_table_identifier",
                "source_column_physical_name",
            ],
            [
                "hub_customer",
                "h_cust",
                "hk_customer",
                "customer_id",
                "crm.customer",
                "customer_id",
            ],
        ],
    }
    first = workbook_factory(base_sheets, filename="first.xlsx")
    import_metadata(
        project=project,
        source=ExcelSource(path=first),
        options=ImportOptions(skip_snapshots=True),
    )
    hub = Hub.objects.get(project=project, hub_physical_name="hub_customer")
    assert hub.hub_hashkey_name == "hk_customer"

    # Now change the hashkey name; re-import should update.
    base_sheets["standard_hub"][1][2] = "hk_customer_new"
    second = workbook_factory(base_sheets, filename="second.xlsx")
    report = import_metadata(
        project=project,
        source=ExcelSource(path=second),
        options=ImportOptions(skip_snapshots=True),
    )
    assert report.status == "success"

    hub.refresh_from_db()
    assert hub.hub_hashkey_name == "hk_customer_new"


# ---------------------------------------------------------------------------
# Conflict strategies
# ---------------------------------------------------------------------------


def test_replace_all_deletes_entities_not_in_file(project, minimal_workbook, workbook_factory):
    # Import the full minimal workbook (hub + satellite)
    import_metadata(
        project=project,
        source=ExcelSource(path=minimal_workbook),
        options=ImportOptions(skip_snapshots=True),
    )
    assert Satellite.objects.filter(project=project).count() == 1

    # Import a workbook that has the hub but not the satellite
    hub_only = workbook_factory(
        {
            "source_data": [
                [
                    "source_system",
                    "source_schema_physical_name",
                    "source_table_physical_name",
                    "source_table_identifier",
                ],
                ["crm", "crm_raw", "customer", "crm.customer"],
            ],
            "standard_hub": [
                [
                    "target_hub_table_physical_name",
                    "hub_identifier",
                    "target_primary_key_physical_name",
                    "business_key_physical_name",
                    "source_table_identifier",
                    "source_column_physical_name",
                ],
                [
                    "hub_customer",
                    "h_cust",
                    "hk_customer",
                    "customer_id",
                    "crm.customer",
                    "customer_id",
                ],
            ],
        },
        filename="hub_only.xlsx",
    )

    report = import_metadata(
        project=project,
        source=ExcelSource(path=hub_only),
        options=ImportOptions(conflict_strategy="replace_all", skip_snapshots=True),
    )
    assert report.status == "success", report.issues

    assert Hub.objects.filter(project=project).count() == 1
    assert Satellite.objects.filter(project=project).count() == 0


def test_update_only_skips_unknown_entities(project, workbook_factory):
    # Project starts empty
    wb = workbook_factory(
        {
            "source_data": [
                [
                    "source_system",
                    "source_schema_physical_name",
                    "source_table_physical_name",
                    "source_table_identifier",
                ],
                ["crm", "crm_raw", "customer", "crm.customer"],
            ],
            "standard_hub": [
                [
                    "target_hub_table_physical_name",
                    "hub_identifier",
                    "target_primary_key_physical_name",
                    "business_key_physical_name",
                    "source_table_identifier",
                    "source_column_physical_name",
                ],
                [
                    "hub_customer",
                    "h_cust",
                    "hk_customer",
                    "customer_id",
                    "crm.customer",
                    "customer_id",
                ],
            ],
        }
    )

    report = import_metadata(
        project=project,
        source=ExcelSource(path=wb),
        options=ImportOptions(conflict_strategy="update_only", skip_snapshots=True),
    )
    # Nothing exists yet — all entities should be skipped
    assert report.status == "success"
    assert Hub.objects.filter(project=project).count() == 0
    assert report.plan.counts.totals.get("skip", 0) > 0


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_dry_run_does_not_write(project, minimal_workbook):
    report = import_metadata(
        project=project,
        source=ExcelSource(path=minimal_workbook),
        options=ImportOptions(dry_run=True, skip_snapshots=True),
    )
    assert report.is_dry_run is True
    assert report.status == "success"
    assert report.plan.counts.totals.get("create", 0) > 0

    assert Hub.objects.filter(project=project).count() == 0
    assert Satellite.objects.filter(project=project).count() == 0
    # ImportRun is still persisted for audit purposes
    assert ImportRun.objects.filter(project=project, is_dry_run=True).exists()


# ---------------------------------------------------------------------------
# Validation diagnostics
# ---------------------------------------------------------------------------


def test_missing_required_column_yields_structured_issue(project, workbook_factory):
    bad = workbook_factory(
        {
            "standard_hub": [
                # missing source_table_identifier (required)
                ["target_hub_table_physical_name", "source_column_physical_name"],
                ["hub_broken", "col1"],
            ],
        }
    )

    report = import_metadata(
        project=project,
        source=ExcelSource(path=bad),
        options=ImportOptions(skip_snapshots=True),
    )

    assert report.status == "validation_failed"
    schema_issues = [i for i in report.issues if i.code == "schema.missing_column"]
    assert schema_issues
    issue = schema_issues[0]
    assert issue.severity == "error"
    assert issue.location is not None
    assert issue.location.sheet == "standard_hub"
    assert "source_table_identifier" in issue.message
    # No DB writes
    assert Hub.objects.filter(project=project).count() == 0


def test_missing_parent_entity_reported_with_location(project, workbook_factory):
    # Satellite references a parent that isn't defined anywhere
    bad = workbook_factory(
        {
            "source_data": [
                [
                    "source_system",
                    "source_schema_physical_name",
                    "source_table_physical_name",
                    "source_table_identifier",
                ],
                ["crm", "crm_raw", "customer", "crm.customer"],
            ],
            "standard_satellite": [
                [
                    "target_satellite_table_physical_name",
                    "parent_identifier",
                    "source_table_identifier",
                    "source_column_physical_name",
                ],
                ["sat_orphan", "nonexistent_hub", "crm.customer", "name"],
            ],
        }
    )

    report = import_metadata(
        project=project,
        source=ExcelSource(path=bad),
        options=ImportOptions(skip_snapshots=True),
    )

    missing_parent = [i for i in report.issues if i.code == "entity.missing_parent"]
    assert missing_parent
    issue = missing_parent[0]
    assert issue.entity is not None
    assert issue.entity.name == "sat_orphan"
    assert issue.location is not None
    assert issue.location.sheet == "standard_satellite"


# ---------------------------------------------------------------------------
# Error strategy
# ---------------------------------------------------------------------------


def test_default_is_best_effort_writes_valid_skips_invalid(project, workbook_factory):
    """Default behavior (no explicit error_strategy): import what's valid,
    skip the broken bits, report partial_success.

    This is the user's stated expectation: 'default to import everything
    possible and then show what has been skipped and why.'
    """
    wb = workbook_factory(
        {
            "source_data": [
                [
                    "source_system",
                    "source_schema_physical_name",
                    "source_table_physical_name",
                    "source_table_identifier",
                ],
                ["crm", "crm_raw", "customer", "crm.customer"],
            ],
            "standard_hub": [
                [
                    "target_hub_table_physical_name",
                    "hub_identifier",
                    "target_primary_key_physical_name",
                    "business_key_physical_name",
                    "source_table_identifier",
                    "source_column_physical_name",
                ],
                # Good hub — should be imported
                [
                    "hub_customer",
                    "h_cust",
                    "hk_customer",
                    "customer_id",
                    "crm.customer",
                    "customer_id",
                ],
            ],
            "standard_satellite": [
                [
                    "target_satellite_table_physical_name",
                    "parent_identifier",
                    "source_table_identifier",
                    "source_column_physical_name",
                ],
                # Bad satellite — references parent that doesn't exist
                ["sat_orphan", "no_such_hub", "crm.customer", "name"],
                # Good satellite — should be imported
                ["sat_customer_details", "h_cust", "crm.customer", "name"],
            ],
        }
    )

    # NO explicit error_strategy — should default to best_effort
    report = import_metadata(
        project=project,
        source=ExcelSource(path=wb),
        options=ImportOptions(skip_snapshots=True),
    )

    # Good entities were written
    assert Hub.objects.filter(project=project, hub_physical_name="hub_customer").exists()
    assert Satellite.objects.filter(
        project=project, satellite_physical_name="sat_customer_details"
    ).exists()
    # Bad entity was skipped
    assert not Satellite.objects.filter(
        project=project, satellite_physical_name="sat_orphan"
    ).exists()

    # Status reflects partial success — NOT validation_failed
    assert report.status == "partial_success"
    # User can see exactly what was skipped and why
    missing_parent = [i for i in report.issues if i.code == "entity.missing_parent"]
    assert len(missing_parent) == 1
    issue = missing_parent[0]
    assert issue.entity is not None
    assert issue.entity.name == "sat_orphan"
    assert "no_such_hub" in issue.message


def test_default_skips_sheet_with_missing_header_column(project, workbook_factory):
    """A sheet missing required header columns is dropped entirely under the
    new default; other sheets continue. The structured error tells the user
    which sheet was unimportable and why.
    """
    wb = workbook_factory(
        {
            "source_data": [
                [
                    "source_system",
                    "source_schema_physical_name",
                    "source_table_physical_name",
                    "source_table_identifier",
                ],
                ["crm", "crm_raw", "customer", "crm.customer"],
            ],
            "standard_hub": [
                # Missing source_table_identifier (required) — whole sheet is unusable
                ["target_hub_table_physical_name", "source_column_physical_name"],
                ["hub_broken", "col1"],
            ],
        }
    )

    report = import_metadata(
        project=project,
        source=ExcelSource(path=wb),
        options=ImportOptions(skip_snapshots=True),
    )

    # The good source_data sheet still produced a source system
    assert SourceSystem.objects.filter(project=project, name="crm").exists()
    # No hub was written from the broken sheet
    assert Hub.objects.filter(project=project).count() == 0

    schema_issues = [i for i in report.issues if i.code == "schema.missing_column"]
    assert schema_issues
    assert schema_issues[0].location.sheet == "standard_hub"


def test_fail_fast_still_works_when_opted_in(project, workbook_factory):
    """`fail_fast` is still available for callers who want strict semantics."""
    wb = workbook_factory(
        {
            "standard_hub": [
                ["target_hub_table_physical_name", "source_column_physical_name"],
                ["hub_broken", "col1"],
            ],
        }
    )

    report = import_metadata(
        project=project,
        source=ExcelSource(path=wb),
        options=ImportOptions(error_strategy="fail_fast", skip_snapshots=True),
    )
    assert report.status == "validation_failed"
    # No DB writes at all
    assert SourceSystem.objects.filter(project=project).count() == 0
    assert Hub.objects.filter(project=project).count() == 0


def test_best_effort_continues_past_resolution_errors(project, workbook_factory):
    """A workbook with one good hub + one bad satellite should still write the hub."""
    wb = workbook_factory(
        {
            "source_data": [
                [
                    "source_system",
                    "source_schema_physical_name",
                    "source_table_physical_name",
                    "source_table_identifier",
                ],
                ["crm", "crm_raw", "customer", "crm.customer"],
            ],
            "standard_hub": [
                [
                    "target_hub_table_physical_name",
                    "hub_identifier",
                    "target_primary_key_physical_name",
                    "business_key_physical_name",
                    "source_table_identifier",
                    "source_column_physical_name",
                ],
                [
                    "hub_customer",
                    "h_cust",
                    "hk_customer",
                    "customer_id",
                    "crm.customer",
                    "customer_id",
                ],
            ],
            "standard_satellite": [
                [
                    "target_satellite_table_physical_name",
                    "parent_identifier",
                    "source_table_identifier",
                    "source_column_physical_name",
                ],
                # parent_identifier is bogus — satellite is unimportable
                ["sat_orphan", "no_such_hub", "crm.customer", "name"],
            ],
        }
    )

    report = import_metadata(
        project=project,
        source=ExcelSource(path=wb),
        options=ImportOptions(
            conflict_strategy="merge",
            error_strategy="best_effort",
            skip_snapshots=True,
        ),
    )

    # Hub was created; satellite was rejected.
    assert Hub.objects.filter(project=project, hub_physical_name="hub_customer").exists()
    assert not Satellite.objects.filter(
        project=project, satellite_physical_name="sat_orphan"
    ).exists()
    # Errors are recorded in the report
    assert report.error_count >= 1
    assert report.status in ("partial_success", "validation_failed")


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


def test_ref_sat_parent_resolves_via_parent_table_identifier(project, workbook_factory):
    """ref_sat sheets use `parent_table_identifier` (e.g. RH0001) to point at
    the reference hub, not `parent_identifier`. Regression for the bug where
    every reference satellite reported 'parent None was not defined'.
    """
    wb = workbook_factory(
        {
            "source_data": [
                [
                    "source_system",
                    "source_schema_physical_name",
                    "source_table_physical_name",
                    "source_table_identifier",
                ],
                ["tpch", "tpch_raw", "nation", "tpch.nation"],
            ],
            "ref_hub": [
                [
                    "target_reference_table_physical_name",
                    "reference_hub_identifier",
                    "source_table_identifier",
                    "source_column_physical_name",
                ],
                ["nation_rh", "RH0001", "tpch.nation", "n_nationkey"],
            ],
            "ref_sat": [
                [
                    "target_reference_table_physical_name",
                    "parent_table_identifier",
                    "source_table_identifier",
                    "source_column_physical_name",
                ],
                ["nation_rs", "RH0001", "tpch.nation", "n_name"],
                ["nation_rs", "RH0001", "tpch.nation", "n_regionkey"],
            ],
        }
    )

    report = import_metadata(
        project=project,
        source=ExcelSource(path=wb),
        options=ImportOptions(skip_snapshots=True),
    )

    # No missing-parent errors should fire.
    missing_parent = [i for i in report.issues if i.code == "entity.missing_parent"]
    assert not missing_parent, missing_parent

    sat = Satellite.objects.filter(
        project=project, satellite_physical_name="nation_rs"
    ).first()
    assert sat is not None
    assert sat.satellite_type == "reference"
    # Parent should be the reference hub
    assert sat.parent_hub is not None
    assert sat.parent_hub.hub_physical_name == "nation_rh"
    # Both columns should land on the satellite
    assert SatelliteColumn.objects.filter(satellite=sat).count() == 2


def test_multiactive_satellite_with_explicit_regular_sort_orders(project, workbook_factory):
    """Regression: a multi-active satellite with regular columns that carry
    EXPLICIT `target_column_sort_order` values and MA-key attributes that
    don't. The MA keys must NOT collide with the regular columns' sort
    orders on the `(satellite, column_sort_order)` unique constraint.

    The bug was that the resolver auto-assigned sort_orders to MA keys
    based on the running max; if a later regular row had an explicit
    sort_order equal to that auto-assigned MA-key sort_order, the executor
    blew up with a UNIQUE constraint violation.
    """
    wb = workbook_factory(
        {
            "source_data": [
                [
                    "source_system",
                    "source_schema_physical_name",
                    "source_table_physical_name",
                    "source_table_identifier",
                ],
                ["tpch", "tpch_raw", "customer", "tpch.customer"],
            ],
            "standard_hub": [
                [
                    "target_hub_table_physical_name",
                    "hub_identifier",
                    "target_primary_key_physical_name",
                    "business_key_physical_name",
                    "source_table_identifier",
                    "source_column_physical_name",
                ],
                [
                    "hub_customer",
                    "h_cust",
                    "hk_customer",
                    "customer_id",
                    "tpch.customer",
                    "customer_id",
                ],
            ],
            "multiactive_satellite": [
                [
                    "target_satellite_table_physical_name",
                    "parent_identifier",
                    "source_table_identifier",
                    "source_column_physical_name",
                    "target_column_sort_order",
                    "multi_active_attributes",
                ],
                # Regular column with explicit sort=1
                [
                    "customer_n_ms",
                    "h_cust",
                    "tpch.customer",
                    "c_name",
                    1,
                    "mkt_segment",
                ],
                # Regular column with explicit sort=2 — would have collided
                # with the MA key before the fix.
                [
                    "customer_n_ms",
                    "h_cust",
                    "tpch.customer",
                    "c_nationkey",
                    2,
                    "mkt_segment",
                ],
                # Regular column with explicit sort=3
                [
                    "customer_n_ms",
                    "h_cust",
                    "tpch.customer",
                    "c_phone",
                    3,
                    "mkt_segment",
                ],
            ],
        }
    )

    report = import_metadata(
        project=project,
        source=ExcelSource(path=wb),
        options=ImportOptions(skip_snapshots=True),
    )

    assert report.status == "success", report.issues
    constraint_errors = [
        i for i in report.issues if i.code == "execute.constraint_violation"
    ]
    assert not constraint_errors, constraint_errors

    sat = Satellite.objects.get(
        project=project, satellite_physical_name="customer_n_ms"
    )
    columns = list(SatelliteColumn.objects.filter(satellite=sat).order_by("column_sort_order"))
    # 3 regular columns + 1 MA key, no duplicates
    assert len(columns) == 4
    sort_orders = [c.column_sort_order for c in columns]
    assert len(set(sort_orders)) == 4  # all unique
    # MA key should land AFTER the explicit-sort-order columns
    ma = next(c for c in columns if c.is_multi_active_key)
    assert ma.column_sort_order > 3


def test_multiactive_satellite_dedups_repeated_ma_attributes(project, workbook_factory):
    """`multi_active_attributes` is repeated on every row of a multi-active
    satellite because the Excel template requires it on each column row.
    The resolver must dedup so the executor doesn't trip on
    `UNIQUE(satellite, column_sort_order)`.

    Regression for: 'Database constraint blocked satellite ... UNIQUE
    constraint failed: satellite_column.satellite_id,
    satellite_column.column_sort_order'.
    """
    wb = workbook_factory(
        {
            "source_data": [
                [
                    "source_system",
                    "source_schema_physical_name",
                    "source_table_physical_name",
                    "source_table_identifier",
                ],
                ["tpch", "tpch_raw", "customer", "tpch.customer"],
            ],
            "standard_hub": [
                [
                    "target_hub_table_physical_name",
                    "hub_identifier",
                    "target_primary_key_physical_name",
                    "business_key_physical_name",
                    "source_table_identifier",
                    "source_column_physical_name",
                ],
                [
                    "hub_customer",
                    "h_cust",
                    "hk_customer",
                    "customer_id",
                    "tpch.customer",
                    "customer_id",
                ],
            ],
            "multiactive_satellite": [
                [
                    "target_satellite_table_physical_name",
                    "parent_identifier",
                    "source_table_identifier",
                    "source_column_physical_name",
                    "multi_active_attributes",
                ],
                # Three column rows for the same satellite, each repeating
                # the SAME two MA attrs — exactly what the Excel format wants.
                [
                    "customer_n_ms",
                    "h_cust",
                    "tpch.customer",
                    "n_name",
                    "discount_level;discount_country",
                ],
                [
                    "customer_n_ms",
                    "h_cust",
                    "tpch.customer",
                    "n_regionkey",
                    "discount_level;discount_country",
                ],
                [
                    "customer_n_ms",
                    "h_cust",
                    "tpch.customer",
                    "n_comment",
                    "discount_level;discount_country",
                ],
            ],
        }
    )

    report = import_metadata(
        project=project,
        source=ExcelSource(path=wb),
        options=ImportOptions(skip_snapshots=True),
    )

    constraint_errors = [
        i for i in report.issues if i.code == "execute.constraint_violation"
    ]
    assert not constraint_errors, constraint_errors
    assert report.status == "success", report.issues

    sat = Satellite.objects.filter(
        project=project, satellite_physical_name="customer_n_ms"
    ).first()
    assert sat is not None
    assert sat.satellite_type == "multi_active"

    # Three regular columns + two MA-key columns, no duplicates.
    columns = list(SatelliteColumn.objects.filter(satellite=sat))
    assert len(columns) == 5
    ma_keys = [c for c in columns if c.is_multi_active_key]
    assert len(ma_keys) == 2
    assert {c.staging_column.physical_name for c in ma_keys} == {
        "discount_level",
        "discount_country",
    }


def test_import_run_persisted_with_report(project, minimal_workbook):
    report = import_metadata(
        project=project,
        source=ExcelSource(path=minimal_workbook),
        options=ImportOptions(skip_snapshots=True),
    )
    run = ImportRun.objects.get(import_run_id=report.import_run_id)
    assert run.project_id == project.project_id
    assert run.status == "success"
    assert run.source_type == "excel"
    assert run.is_dry_run is False
    assert "plan" in run.report
    assert "issues" in run.report
