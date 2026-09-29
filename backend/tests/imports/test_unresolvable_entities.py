"""Entities that can't be imported are left out, with what depends on them.

A link missing one of its hubs, a satellite without its parent or source
table, a reference table or PIT pointing at something undefined: each is
reported as an error and planned as a skip with its reason, instead of being
imported half-resolved. Whatever depends on it is skipped too, with a
warning. The dry-run shows all of it before anything is written.
"""

from __future__ import annotations

import pytest
from engine.models import Hub, Link, Satellite
from engine.services.imports import ExcelSource, ImportOptions, import_metadata

SOURCE_DATA = [
    [
        "source_system",
        "source_schema_physical_name",
        "source_table_physical_name",
        "source_table_identifier",
    ],
    ["crm", "crm_raw", "orders", "crm.orders"],
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
        "customer_id",
        "crm.orders",
        "customer_id",
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
]

SATELLITE_HEADER = [
    "target_satellite_table_physical_name",
    "satellite_identifier",
    "parent_identifier",
    "source_table_identifier",
    "source_column_physical_name",
]

PIT_HEADER = ["pit_physical_table_name", "tracked_entity", "satellite_identifiers"]


def _link_rows(customer_hub: str = "h_cust") -> list[list]:
    return [
        LINK_HEADER,
        [
            "link_order_customer",
            "l_oc",
            "h_ord",
            "hk_order_customer",
            "hk_order",
            "crm.orders",
            "order_id",
        ],
        [
            "link_order_customer",
            "l_oc",
            customer_hub,
            "hk_order_customer",
            "hk_customer",
            "crm.orders",
            "customer_id",
        ],
    ]


def _sheets(
    *, customer_hub: str = "h_cust", **overrides: list[list]
) -> dict[str, list[list]]:
    sheets = {
        "source_data": SOURCE_DATA,
        "standard_hub": HUBS,
        "standard_link": _link_rows(customer_hub),
        "standard_satellite": [
            SATELLITE_HEADER,
            ["sat_order", "s_ord", "h_ord", "crm.orders", "status"],
            ["sat_order_customer", "s_oc", "l_oc", "crm.orders", "channel"],
        ],
        "pit": [PIT_HEADER, ["pit_order_customer", "l_oc", "s_oc"]],
    }
    sheets.update(overrides)
    return sheets


def _run(project, path, **options):
    return import_metadata(
        project=project,
        source=ExcelSource(path=path),
        options=ImportOptions(skip_snapshots=True, **options),
    )


def _planned(report) -> dict[tuple[str, str], tuple[str, str | None]]:
    return {
        (entity.ref.type, entity.ref.name): (entity.action, entity.skip_reason)
        for entity in report.plan.entities
    }


def _issues(report, code: str) -> list:
    return [issue for issue in report.issues if issue.code == code]


@pytest.mark.django_db
class TestLinkWithAnUndefinedHub:
    def test_dry_run_plans_the_link_and_its_dependents_as_skips(
        self, project, workbook_factory
    ):
        path = workbook_factory(_sheets(customer_hub="h_missing"))

        report = _run(project, path, dry_run=True, error_strategy="best_effort")

        planned = _planned(report)
        assert planned[("link", "link_order_customer")] == ("skip", "missing_reference")
        assert planned[("satellite", "sat_order_customer")] == (
            "skip",
            "depends_on_skipped",
        )
        assert planned[("pit", "pit_order_customer")] == ("skip", "depends_on_skipped")
        # The rest of the file is still planned normally.
        assert planned[("hub", "hub_customer")] == ("create", None)
        assert planned[("satellite", "sat_order")] == ("create", None)
        assert report.plan.counts.totals["skip"] == 3

        [missing] = _issues(report, "entity.missing_reference")
        assert missing.severity == "error"
        assert missing.entity.name == "link_order_customer"
        assert "h_missing" in missing.message
        dependents = _issues(report, "entity.depends_on_skipped")
        assert {(i.severity, i.entity.type, i.entity.name) for i in dependents} == {
            ("warning", "satellite", "sat_order_customer"),
            ("warning", "pit", "pit_order_customer"),
        }
        assert "its parent link 'link_order_customer'" in next(
            i.message for i in dependents if i.entity.type == "satellite"
        )
        # Nothing is written, and errors still fail the dry-run.
        assert report.status == "validation_failed"
        assert not Hub.objects.filter(project=project).exists()

    def test_best_effort_imports_the_rest_and_leaves_the_link_out(
        self, project, workbook_factory
    ):
        path = workbook_factory(_sheets(customer_hub="h_missing"))

        report = _run(project, path, error_strategy="best_effort")

        assert report.status == "partial_success"
        assert set(
            Hub.objects.filter(project=project).values_list(
                "hub_physical_name", flat=True
            )
        ) == {
            "hub_order",
            "hub_customer",
        }
        # Not a half-connected link: no link at all.
        assert not Link.objects.filter(project=project).exists()
        assert list(
            Satellite.objects.filter(project=project).values_list(
                "satellite_physical_name", flat=True
            )
        ) == ["sat_order"]

    def test_fail_fast_writes_nothing(self, project, workbook_factory):
        path = workbook_factory(_sheets(customer_hub="h_missing"))

        report = _run(project, path, error_strategy="fail_fast")

        assert report.status == "validation_failed"
        assert report.plan.entities == []
        assert not Hub.objects.filter(project=project).exists()

    def test_replace_all_keeps_the_projects_copy(self, project, workbook_factory):
        _run(project, workbook_factory(_sheets(), filename="valid.xlsx"))
        assert Link.objects.filter(
            project=project, link_physical_name="link_order_customer"
        ).exists()
        broken = workbook_factory(
            _sheets(customer_hub="h_missing"), filename="broken.xlsx"
        )

        report = _run(
            project,
            broken,
            conflict_strategy="replace_all",
            error_strategy="best_effort",
        )

        planned = _planned(report)
        assert planned[("link", "link_order_customer")] == ("skip", "missing_reference")
        assert planned[("satellite", "sat_order_customer")] == (
            "skip",
            "depends_on_skipped",
        )
        assert report.plan.counts.totals["delete"] == 0
        link = Link.objects.get(
            project=project, link_physical_name="link_order_customer"
        )
        assert link.hub_references.count() == 2
        assert Satellite.objects.filter(
            project=project, satellite_physical_name="sat_order_customer"
        ).exists()


@pytest.mark.django_db
class TestSatellites:
    def test_undefined_parent(self, project, workbook_factory):
        path = workbook_factory(
            _sheets(
                standard_satellite=[
                    SATELLITE_HEADER,
                    ["sat_orphan", "s_orphan", "h_nowhere", "crm.orders", "status"],
                ],
                pit=[PIT_HEADER, ["pit_orphan", "h_ord", "s_orphan"]],
            )
        )

        report = _run(project, path, dry_run=True)

        planned = _planned(report)
        assert planned[("satellite", "sat_orphan")] == ("skip", "missing_parent")
        # A PIT naming the satellite by its identifier follows it out.
        assert planned[("pit", "pit_orphan")] == ("skip", "depends_on_skipped")
        assert _issues(report, "entity.missing_parent")[0].severity == "error"

    def test_undefined_source_table(self, project, workbook_factory):
        path = workbook_factory(
            _sheets(
                standard_satellite=[
                    SATELLITE_HEADER,
                    ["sat_order", "s_ord", "h_ord", "crm.nowhere", "status"],
                ],
                pit=[PIT_HEADER],
            )
        )

        report = _run(project, path, dry_run=True)

        assert _planned(report)[("satellite", "sat_order")] == (
            "skip",
            "missing_source_table",
        )


@pytest.mark.django_db
def test_reference_table_with_an_undefined_hub(project, workbook_factory):
    path = workbook_factory(
        _sheets(
            pit=[PIT_HEADER],
            ref_table=[
                ["target_reference_table_physical_name", "referenced_hub"],
                ["ref_country", "h_country"],
            ],
        )
    )

    report = _run(project, path, dry_run=True)

    assert _planned(report)[("reference_table", "ref_country")] == (
        "skip",
        "missing_reference",
    )


@pytest.mark.django_db
def test_a_mapping_to_an_unknown_source_table_drops_only_the_mapping(
    project, workbook_factory
):
    """The hub itself is valid without that mapping, so it is imported."""
    hubs = [
        *HUBS,
        [
            "hub_customer",
            "h_cust",
            "hk_customer",
            "customer_id",
            "crm.nowhere",
            "cust_no",
        ],
    ]
    path = workbook_factory(_sheets(standard_hub=hubs))

    report = _run(project, path, error_strategy="best_effort")

    assert _issues(report, "entity.missing_source_table")
    assert _planned(report)[("hub", "hub_customer")] == ("create", None)
    # Nothing is left out for it; the PIT is, because snapshots are off.
    assert [
        (entity.ref.type, entity.skip_reason)
        for entity in report.plan.entities
        if entity.action == "skip"
    ] == [("pit", "skip_snapshots")]
    assert Hub.objects.filter(
        project=project, hub_physical_name="hub_customer"
    ).exists()
