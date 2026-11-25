"""Links and PITs from a workbook or SQLite file: what the sheets say, all of it.

The link sheets' prejoin columns bring a column in from another table, as
datavault4dbt's ``prejoined_columns`` do: the row's source column joins the
prejoined table's ``prejoin_table_column_name``, which gives
``prejoin_extraction_column_name``, staged as ``prejoin_target_column_alias``.
Rows a link can't use, links that connect too few hubs and PITs spread over
several rows are reported instead of being dropped or half-read in silence.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from engine.cli.commands.import_cmd import _render_report
from engine.models import (
    PIT,
    Hub,
    Link,
    LinkHubSourceMapping,
    PrejoinDefinition,
    SourceColumn,
)
from engine.services.generation.validators import _validate_link
from engine.services.imports import (
    ExcelSource,
    ImportOptions,
    SqliteSource,
    import_metadata,
)
from engine.services.imports.ir import IRRow
from engine.services.imports.validation.resolver import _rows_phrase

TPCH_DB = Path(__file__).resolve().parents[3] / "TurboVault_TPCH_Data.db"

SOURCE_DATA = [
    [
        "source_system",
        "source_schema_physical_name",
        "source_table_physical_name",
        "source_table_identifier",
    ],
    ["crm", "crm_raw", "orders", "crm.orders"],
    ["crm", "crm_raw", "customers", "crm.customers"],
]

HUBS = [
    [
        "target_hub_table_physical_name",
        "hub_identifier",
        "target_primary_key_physical_name",
        "business_key_physical_name",
        "source_table_identifier",
        "source_column_physical_name",
    ],
    ["hub_order", "h_ord", "hk_order", "order_id", "crm.orders", "order_id"],
    [
        "hub_customer",
        "h_cust",
        "hk_customer",
        "customer_no",
        "crm.customers",
        "customer_no",
    ],
]

LINK_HEADER = [
    "target_link_table_physical_name",
    "link_identifier",
    "hub_identifier",
    "target_primary_key_physical_name",
    "target_column_physical_name",
    "source_table_identifier",
    "source_column_physical_name",
    "prejoin_table_identifier",
    "prejoin_table_column_name",
    "prejoin_extraction_column_name",
    "prejoin_target_column_alias",
]

ORDER_ROW = [
    "link_order_customer",
    "l_oc",
    "h_ord",
    "hk_order_customer",
    "hk_order",
    "crm.orders",
    "order_id",
    None,
    None,
    None,
    None,
]


def _customer_row(**overrides) -> list:
    """The customer's key, taken from customers through orders.customer_id."""
    row = {
        "target_link_table_physical_name": "link_order_customer",
        "link_identifier": "l_oc",
        "hub_identifier": "h_cust",
        "target_primary_key_physical_name": "hk_order_customer",
        "target_column_physical_name": "hk_customer",
        "source_table_identifier": "crm.orders",
        "source_column_physical_name": "customer_id",
        "prejoin_table_identifier": "crm.customers",
        "prejoin_table_column_name": "id",
        "prejoin_extraction_column_name": "customer_no",
        "prejoin_target_column_alias": "customer_no_of_order",
    }
    row.update(overrides)
    return [row[column] for column in LINK_HEADER]


def _sheets(*link_rows: list, **overrides: list[list]) -> dict[str, list[list]]:
    sheets = {
        "source_data": SOURCE_DATA,
        "standard_hub": HUBS,
        "standard_link": [LINK_HEADER, *(link_rows or (ORDER_ROW, _customer_row()))],
    }
    sheets.update(overrides)
    return sheets


def _run(project, path, **options):
    options.setdefault("skip_snapshots", True)
    return import_metadata(
        project=project,
        source=ExcelSource(path=path),
        options=ImportOptions(**options),
    )


def _issues(report, code: str) -> list:
    return [issue for issue in report.issues if issue.code == code]


def _hub_key_columns(project, link_name: str) -> dict[str, str]:
    """Hub -> the staged column its key in the link is hashed from."""
    return {
        m.link_hub_reference.hub.hub_physical_name: m.staging_column.physical_name
        for m in LinkHubSourceMapping.objects.filter(
            link_hub_reference__link__project=project,
            link_hub_reference__link__link_physical_name=link_name,
        ).select_related(
            "link_hub_reference__hub",
            "staging_column__source_column",
            "staging_column__prejoin_column__source_column",
        )
    }


# ---------------------------------------------------------------------------
# Prejoins
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_link_takes_a_hub_key_through_its_prejoin(project, workbook_factory):
    report = _run(project, workbook_factory(_sheets()))

    assert report.status == "success", report.issues
    prejoin = PrejoinDefinition.objects.get(project=project)
    assert prejoin.source_table.physical_table_name == "orders"
    assert prejoin.prejoin_target_table.physical_table_name == "customers"
    assert [
        c.source_column_physical_name
        for c in prejoin.prejoin_condition_source_column.all()
    ] == ["customer_id"]
    assert [
        c.source_column_physical_name
        for c in prejoin.prejoin_condition_target_column.all()
    ] == ["id"]
    assert [
        (e.source_column.source_column_physical_name, e.prejoin_target_column_alias)
        for e in prejoin.extraction_columns.all()
    ] == [("customer_no", "customer_no_of_order")]
    assert _hub_key_columns(project, "link_order_customer") == {
        "hub_order": "order_id",
        "hub_customer": "customer_no_of_order",
    }
    # The staged name is no column of orders: none is invented for it.
    assert not SourceColumn.objects.filter(
        source_table__physical_table_name="orders",
        source_column_physical_name="customer_no_of_order",
    ).exists()


@pytest.mark.django_db
def test_a_prejoin_imported_again_changes_nothing(project, workbook_factory):
    path = workbook_factory(_sheets())
    _run(project, path)

    again = _run(project, path)

    totals = again.plan.counts.totals
    assert (totals["create"], totals["update"], totals["delete"]) == (0, 0, 0)
    assert PrejoinDefinition.objects.filter(project=project).count() == 1


@pytest.mark.django_db
def test_a_prejoined_payload_column(project, workbook_factory):
    nh_link = [
        LINK_HEADER,
        [
            "nl_order",
            "nl_o",
            "h_ord",
            "hk_order_nl",
            "hk_order",
            "crm.orders",
            "order_id",
            None,
            None,
            None,
            None,
        ],
        [
            "nl_order",
            "nl_o",
            None,
            None,
            "customer_segment",
            "crm.orders",
            "customer_id",
            "crm.customers",
            "id",
            "segment",
            None,
        ],
    ]
    report = _run(project, workbook_factory(_sheets(non_historized_link=nh_link)))

    assert report.status == "success", report.issues
    link = Link.objects.get(project=project, link_physical_name="nl_order")
    column = link.columns.get(column_name="customer_segment")
    staging = column.source_mappings.get().staging_column
    assert staging.prejoin_column is not None
    assert staging.physical_name == "segment"


@pytest.mark.django_db
def test_an_incomplete_prejoin_is_an_error_and_brings_nothing_in(
    project, workbook_factory
):
    path = workbook_factory(
        _sheets(ORDER_ROW, _customer_row(prejoin_table_column_name=None))
    )

    report = _run(project, path)

    [issue] = _issues(report, "entity.invalid_configuration")
    assert issue.severity == "error"
    assert "without prejoin_table_column_name" in issue.message
    assert issue.location.column == "prejoin_table_column_name"
    assert not PrejoinDefinition.objects.filter(project=project).exists()
    assert "hub_customer" not in _hub_key_columns(project, "link_order_customer")


@pytest.mark.django_db
def test_a_prejoin_of_an_unknown_table_is_an_error(project, workbook_factory):
    path = workbook_factory(
        _sheets(ORDER_ROW, _customer_row(prejoin_table_identifier="crm.nowhere"))
    )

    report = _run(project, path)

    [issue] = _issues(report, "entity.missing_source_table")
    assert issue.message == (
        "Link 'link_order_customer' prejoins unknown source table 'crm.nowhere'."
    )
    assert not PrejoinDefinition.objects.filter(project=project).exists()


@pytest.mark.django_db
def test_two_tables_are_prejoined_one_way(project, workbook_factory):
    second_link = [
        "link_order_customer_2",
        "l_oc2",
        "h_cust",
        "hk_order_customer_2",
        "hk_customer",
        "crm.orders",
        "customer_ref",
        "crm.customers",
        "legacy_id",
        "customer_no",
        "customer_no_of_order",
    ]
    path = workbook_factory(_sheets(ORDER_ROW, _customer_row(), second_link))

    report = _run(project, path)

    # The second link also connects one hub only: that is a warning of its own.
    [issue] = [
        issue
        for issue in _issues(report, "entity.invalid_configuration")
        if issue.severity == "error"
    ]
    assert issue.entity.name == "link_order_customer_2"
    assert "joins these tables on orders.customer_id = customers.id" in issue.message
    prejoin = PrejoinDefinition.objects.get(project=project)
    assert [
        c.source_column_physical_name
        for c in prejoin.prejoin_condition_target_column.all()
    ] == ["id"]


@pytest.mark.django_db
def test_a_link_left_out_leaves_its_prejoin_out(project, workbook_factory):
    path = workbook_factory(
        _sheets(_customer_row(), [*ORDER_ROW[:2], "h_missing", *ORDER_ROW[3:]])
    )

    report = _run(project, path)

    assert ("link", "link_order_customer") in {
        (e.ref.type, e.ref.name) for e in report.plan.entities if e.action == "skip"
    }
    assert not PrejoinDefinition.objects.filter(project=project).exists()


@pytest.mark.django_db
@pytest.mark.skipif(not TPCH_DB.exists(), reason="bundled TPCH database missing")
def test_the_tpch_samples_prejoin_link_hashes_the_region_name(project):
    """nation_test_link connects the Region Hub through nation.N_REGIONKEY."""
    report = import_metadata(
        project=project,
        source=SqliteSource(path=TPCH_DB),
        options=ImportOptions(skip_snapshots=True),
    )

    # The sample has a row of its own to fix (a payload row of a non-historized
    # link without its source column); nothing about the prejoins.
    assert not [i for i in report.issues if "prejoin" in i.message], report.issues
    keys = _hub_key_columns(project, "nation_test_link")
    region = next(name for name in keys if "region" in name.lower())
    assert keys[region] == "REGION_NAME"
    prejoin = PrejoinDefinition.objects.get(
        project=project, prejoin_target_table__physical_table_name__iexact="region"
    )
    assert [
        (e.source_column.source_column_physical_name, e.prejoin_target_column_alias)
        for e in prejoin.extraction_columns.all()
    ] == [("R_NAME", "REGION_NAME")]


# ---------------------------------------------------------------------------
# Hub keys and hubs
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rows_beyond_a_hubs_keys_are_reported(project, workbook_factory):
    surplus = [
        "link_order_customer",
        "l_oc",
        "h_ord",
        "hk_order_customer",
        "hk_order",
        "crm.orders",
        "order_ref",
        None,
        None,
        None,
        None,
    ]
    path = workbook_factory(_sheets(ORDER_ROW, surplus, _customer_row()))

    report = _run(project, path)

    [issue] = _issues(report, "entity.invalid_configuration")
    assert issue.severity == "warning"
    assert issue.message == (
        "Link 'link_order_customer' maps 2 columns to Hub 'hub_order', which has "
        "1 key: row 3 is not imported."
    )
    assert issue.location.row == 3
    assert _hub_key_columns(project, "link_order_customer")["hub_order"] == "order_id"


@pytest.mark.django_db
def test_links_without_the_hubs_or_key_they_need_are_imported_and_reported(
    project, workbook_factory
):
    """A standard link with one hub is allowed, with a warning. A non-historized
    link may connect any number of hubs, none too, if it has a dependent child
    key to hash (its row names the link's hash key)."""
    header = [
        "target_link_table_physical_name",
        "nh_link_identifier",
        "hub_identifier",
        "target_primary_key_physical_name",
        "target_column_physical_name",
        "source_table_identifier",
        "source_column_physical_name",
    ]
    path = workbook_factory(
        _sheets(
            ORDER_ROW,
            non_historized_link=[
                header,
                ["nl_none", "nl_n", None, None, "amount", "crm.orders", "amount"],
                [
                    "nl_payment",
                    "nl_p",
                    None,
                    "hk_payment_nl",
                    "payment_id",
                    "crm.orders",
                    "payment_id",
                ],
                ["nl_payment", "nl_p", None, None, "amount", "crm.orders", "amount"],
                ["nl_one", "nl_1", "h_ord", None, "hk_order", "crm.orders", "order_id"],
                ["nl_one", "nl_1", None, None, "amount", "crm.orders", "amount"],
            ],
        )
    )

    report = _run(project, path)

    messages = {
        issue.entity.name: issue.message
        for issue in _issues(report, "entity.invalid_configuration")
    }
    assert messages == {
        "link_order_customer": (
            "Link 'link_order_customer' connects only one hub; a link usually "
            "connects two or more."
        ),
        "nl_none": (
            "Non-historized link 'nl_none' connects no hubs and has no dependent "
            "child key, so its hash key has nothing to hash."
        ),
    }
    assert all(
        issue.severity == "warning"
        for issue in _issues(report, "entity.invalid_configuration")
    )
    # Imported as the file has them, to complete in the project.
    assert set(
        Link.objects.filter(project=project).values_list(
            "link_physical_name", flat=True
        )
    ) == {"link_order_customer", "nl_none", "nl_payment", "nl_one"}


def test_the_generation_check_says_how_many_hubs_a_link_connects():
    class _Link:
        link_type = "standard"
        link_name = "link_order"
        hashkey = type("HK", (), {"hashkey_name": "hk_link_order"})()
        foreign_hashkeys = ["hk_order"]
        source_tables: list = []

    result = _validate_link(_Link())  # type: ignore[arg-type]

    [warning] = [w for w in result.warnings if w.code == "LNK_002"]
    assert warning.message == (
        "A standard Link usually connects two or more Hubs; this one connects one"
    )


# ---------------------------------------------------------------------------
# PITs
# ---------------------------------------------------------------------------

SATELLITES = [
    [
        "target_satellite_table_physical_name",
        "satellite_identifier",
        "parent_identifier",
        "source_table_identifier",
        "source_column_physical_name",
    ],
    ["sat_order", "s_ord", "h_ord", "crm.orders", "status"],
    ["sat_order_amount", "s_amt", "h_ord", "crm.orders", "amount"],
]

PIT_HEADER = [
    "pit_physical_table_name",
    "tracked_entity",
    "satellite_identifiers",
    "dimension_key_name",
]


@pytest.mark.django_db
def test_a_pit_over_several_rows_is_one_pit_with_the_satellites_of_all(
    project, workbook_factory
):
    path = workbook_factory(
        _sheets(
            standard_satellite=SATELLITES,
            pit=[
                PIT_HEADER,
                ["pit_order", "h_ord", "s_ord", "hk_order_d"],
                ["pit_order", "h_ord", "s_amt;s_ord", None],
            ],
        )
    )

    report = _run(project, path, skip_snapshots=False)

    assert not _issues(report, "entity.invalid_configuration"), report.issues
    pit = PIT.objects.get(project=project, pit_physical_name="pit_order")
    assert list(
        pit.satellites.order_by("satellite_physical_name").values_list(
            "satellite_physical_name", flat=True
        )
    ) == ["sat_order", "sat_order_amount"]
    assert pit.dimension_key_column_name == "hk_order_d"


@pytest.mark.django_db
def test_a_pit_tracking_an_unknown_entity_is_one_error(project, workbook_factory):
    path = workbook_factory(
        _sheets(
            standard_satellite=SATELLITES,
            pit=[
                PIT_HEADER,
                ["pit_order", "Hub Order", "s_ord", None],
                ["pit_order", "Hub Order", "s_ord", None],
                ["pit_order", "Hub Order", "s_amt", None],
            ],
        )
    )

    report = _run(project, path)

    [issue] = _issues(report, "entity.missing_reference")
    assert (
        issue.message
        == "PIT 'pit_order' tracks unknown entity 'Hub Order' (in 3 rows)."
    )
    assert issue.location.row == 2
    # Said, never guessed: no hub is matched to the display name.
    assert "hub_order" not in (issue.suggestion or "")


@pytest.mark.django_db
def test_a_pit_whose_rows_track_different_entities_is_left_out(
    project, workbook_factory
):
    path = workbook_factory(
        _sheets(
            standard_satellite=SATELLITES,
            pit=[
                PIT_HEADER,
                ["pit_order", "h_ord", "s_ord", None],
                ["pit_order", "l_oc", "s_ord", None],
            ],
        )
    )

    report = _run(project, path)

    [issue] = _issues(report, "entity.invalid_configuration")
    assert issue.severity == "error"
    assert issue.location.row == 3
    assert ("pit", "pit_order", "invalid_configuration") in {
        (e.ref.type, e.ref.name, e.skip_reason)
        for e in report.plan.entities
        if e.action == "skip"
    }


@pytest.mark.django_db
def test_a_pit_setting_that_differs_between_rows_is_said(project, workbook_factory):
    path = workbook_factory(
        _sheets(
            standard_satellite=SATELLITES,
            pit=[
                PIT_HEADER,
                ["pit_order", "h_ord", "s_ord", "hk_order_d"],
                ["pit_order", "h_ord", "s_ord", "hk_other_d"],
            ],
        )
    )

    report = _run(project, path, skip_snapshots=False)

    [issue] = _issues(report, "entity.invalid_configuration")
    assert issue.severity == "warning"
    assert issue.message == (
        "PIT 'pit_order' has dimension_key_name 'hk_order_d' in row 2 but "
        "'hk_other_d' in row 3; 'hk_order_d' is used."
    )


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_ignored_sheet_says_how_many_rows_it_drops(project, workbook_factory):
    path = workbook_factory(
        _sheets(review_notes=[["note"], ["check hub_order"], ["check hub_customer"]])
    )

    report = _run(project, path)

    [issue] = _issues(report, "schema.unknown_sheet")
    assert issue.message == (
        "Sheet 'review_notes' is not recognized and will be ignored (2 rows)."
    )


@pytest.mark.django_db
def test_issues_name_the_file_by_the_name_the_caller_gives(project, workbook_factory):
    path = workbook_factory(
        _sheets(ORDER_ROW, _customer_row(prejoin_table_identifier="crm.nowhere")),
        filename="metadata.xlsx",
    )

    report = import_metadata(
        project=project,
        source=ExcelSource(path=path, display_name="orders model.xlsx"),
        options=ImportOptions(skip_snapshots=True),
    )

    assert report.source_name == "orders model.xlsx"
    assert {issue.location.file for issue in report.issues} == {"orders model.xlsx"}


@pytest.mark.django_db
def test_a_column_taken_again_under_another_name_is_the_same_column(
    project, workbook_factory
):
    """Same join, same column: the same values. The stage names them once."""
    second_link = [
        "link_order_customer_2",
        "l_oc2",
        "h_cust",
        "hk_order_customer_2",
        "hk_customer",
        "crm.orders",
        "customer_id",
        "crm.customers",
        "id",
        "customer_no",
        "customer_no_again",
    ]
    path = workbook_factory(_sheets(ORDER_ROW, _customer_row(), second_link))

    report = _run(project, path)

    [issue] = [
        issue
        for issue in _issues(report, "entity.invalid_configuration")
        if "earlier row takes it" in issue.message
    ]
    assert issue.severity == "warning"
    assert issue.message == (
        "Link 'link_order_customer_2' takes customers.customer_no as "
        "'customer_no_again', but an earlier row takes it as 'customer_no_of_order'; "
        "the link uses 'customer_no_of_order', the same column."
    )
    assert _hub_key_columns(project, "link_order_customer_2") == {
        "hub_customer": "customer_no_of_order"
    }


@pytest.mark.parametrize(
    ("numbers", "phrase"),
    [
        ([7], "row 7"),
        ([7, 9], "rows 7 and 9"),
        (list(range(4, 14)), "rows 4–13"),
        ([4, 5, 6, 9, 11, 12, 13], "rows 4–6, 9 and 11–13"),
    ],
)
def test_rows_are_named_compactly(numbers, phrase):
    rows = [IRRow(row_number=number, values={}) for number in numbers]
    assert _rows_phrase(rows) == phrase


# ---------------------------------------------------------------------------
# The CLI's summary
# ---------------------------------------------------------------------------


def _summary(report, capsys) -> str:
    _render_report(report)
    return " ".join(capsys.readouterr().out.split())


@pytest.mark.django_db
def test_the_cli_says_what_a_dry_run_with_errors_would_import(
    project, workbook_factory, capsys
):
    path = workbook_factory(
        _sheets(ORDER_ROW, _customer_row(prejoin_table_identifier="crm.nowhere"))
    )
    report = _run(project, path, dry_run=True)
    assert report.status == "validation_failed"

    out = _summary(report, capsys)

    assert "Dry run: the import would partially succeed." in out
    assert "Nothing was written." in out
    assert "aborted" not in out


@pytest.mark.django_db
def test_the_cli_says_a_fail_fast_dry_run_stopped(project, workbook_factory, capsys):
    path = workbook_factory(
        _sheets(ORDER_ROW, _customer_row(prejoin_table_identifier="crm.nowhere"))
    )
    report = _run(project, path, dry_run=True, error_strategy="fail_fast")

    out = _summary(report, capsys)

    assert "Import aborted at validation: 1 error(s)." in out


# ---------------------------------------------------------------------------
# Source columns
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_column_written_in_two_cases_is_one_column(project, workbook_factory):
    path = workbook_factory(
        _sheets(
            ORDER_ROW,
            _customer_row(),
            standard_satellite=[
                [
                    "target_satellite_table_physical_name",
                    "satellite_identifier",
                    "parent_identifier",
                    "source_table_identifier",
                    "source_column_physical_name",
                ],
                # The hub sheet writes it order_id; this sheet ORDER_ID.
                ["sat_order", "s_ord", "h_ord", "crm.orders", "ORDER_ID"],
            ],
        )
    )

    report = _run(project, path)

    assert report.status == "success", report.issues
    names = list(
        SourceColumn.objects.filter(
            source_table__physical_table_name="orders",
            source_column_physical_name__iexact="order_id",
        ).values_list("source_column_physical_name", flat=True)
    )
    assert names == ["order_id"]
    again = _run(project, path)
    totals = again.plan.counts.totals
    assert (totals["create"], totals["update"], totals["delete"]) == (0, 0, 0)


# ---------------------------------------------------------------------------
# Effectivity satellites
# ---------------------------------------------------------------------------

EFFECTIVITY_HEADER = [
    "target_satellite_table_physical_name",
    "effectivity_satellite_identifier",
    "parent_identifier",
    "source_table_identifier",
    "source_column_physical_name",
    "target_column_physical_name",
]


def _effectivity(*rows: list) -> list[list]:
    return [EFFECTIVITY_HEADER, *rows]


@pytest.mark.django_db
def test_an_effectivity_satellite_becomes_its_parents_flag(project, workbook_factory):
    second_link = [
        "link_order_order",
        "l_oo",
        "h_ord",
        "hk_order_order",
        "hk_order",
        "crm.orders",
        "order_id",
        None,
        None,
        None,
        None,
    ]
    path = workbook_factory(
        _sheets(
            ORDER_ROW,
            _customer_row(),
            second_link,
            effectivity_satellite=_effectivity(
                ["eff_order", "e_ord", "h_ord", "crm.orders", "deleted_at", "ddts"],
                ["eff_order", "e_ord", "h_ord", "crm.orders", "updated_at", "udts"],
                ["eff_order_customer", "e_oc", "l_oc", "crm.orders", "x", "ddts"],
                ["eff_order_customer_2", "e_oc2", "l_oc", "crm.orders", "y", "ddts"],
            ),
        )
    )

    report = _run(project, path)

    assert not _issues(report, "schema.unknown_sheet")
    hub = Hub.objects.get(project=project, hub_physical_name="hub_order")
    assert hub.create_effectivity_satellite
    links = dict(
        Link.objects.filter(project=project).values_list(
            "link_physical_name", "create_effectivity_satellite"
        )
    )
    # The sheet describes the links' effectivity in full.
    assert links == {"link_order_customer": True, "link_order_order": False}
    messages = {
        issue.entity.name: issue.message
        for issue in _issues(report, "entity.imported_differently")
    }
    assert messages == {
        "hub_order": (
            "Effectivity satellite 'eff_order' is imported as hub 'hub_order''s "
            "effectivity satellite. The Engine names it by the project's naming "
            "pattern; the sheet's name and columns are not imported."
        ),
        "link_order_customer": (
            "Effectivity satellites 'eff_order_customer' and 'eff_order_customer_2' "
            "are imported as link 'link_order_customer''s effectivity satellite. "
            "The Engine names it by the project's naming pattern; the sheet's name "
            "and columns are not imported."
        ),
    }
    again = _run(project, path)
    totals = again.plan.counts.totals
    assert (totals["create"], totals["update"], totals["delete"]) == (0, 0, 0)


@pytest.mark.django_db
def test_an_effectivity_satellite_of_an_unknown_parent_is_left_out(
    project, workbook_factory
):
    path = workbook_factory(
        _sheets(
            effectivity_satellite=_effectivity(
                ["eff_ghost", "e_g", "h_ghost", "crm.orders", "deleted_at", "ddts"]
            )
        )
    )

    report = _run(project, path)

    [issue] = _issues(report, "entity.missing_parent")
    assert issue.message == (
        "Effectivity satellite 'eff_ghost' parent 'h_ghost' was not defined."
    )
    assert ("satellite", "eff_ghost", "missing_parent") in {
        (e.ref.type, e.ref.name, e.skip_reason)
        for e in report.plan.entities
        if e.action == "skip"
    }


@pytest.mark.django_db
def test_a_pit_does_not_track_an_effectivity_satellite(project, workbook_factory):
    path = workbook_factory(
        _sheets(
            standard_satellite=SATELLITES,
            effectivity_satellite=_effectivity(
                ["eff_order", "e_ord", "h_ord", "crm.orders", "deleted_at", "ddts"]
            ),
            pit=[PIT_HEADER, ["pit_order", "h_ord", "s_ord;e_ord", None]],
        )
    )

    report = _run(project, path, skip_snapshots=False)

    [issue] = [
        issue
        for issue in _issues(report, "entity.imported_differently")
        if issue.entity.type == "pit"
    ]
    assert issue.message == (
        "PIT 'pit_order' lists effectivity satellite 'eff_order', which is "
        "imported as their parent's effectivity satellite: the PIT tracks it no "
        "more."
    )
    pit = PIT.objects.get(project=project, pit_physical_name="pit_order")
    assert list(pit.satellites.values_list("satellite_physical_name", flat=True)) == [
        "sat_order"
    ]
