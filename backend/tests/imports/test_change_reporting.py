"""What an import reports for each entity, and that it writes only that.

Importing the same source twice must write nothing the second time and report
every entity as `unchanged`. A real change, down to a new source mapping on a
hub, must make exactly that entity an `update`, with the change listed. A dry
run reports exactly what the real run then does.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from engine.models import (
    PIT,
    Hub,
    HubSourceMapping,
    LinkHubReference,
    LinkHubSourceMapping,
    Project,
    SatelliteColumn,
    SourceColumn,
    SourceSystem,
    SourceTable,
)
from engine.services.export.builder import ModelBuilder
from engine.services.imports import (
    ExcelSource,
    ImportOptions,
    JsonSource,
    SourceMetadataSource,
    import_metadata,
)
from engine.services.imports.reporting import determine_status
from engine.services.imports.types import ImportPlan, PlanCounts

pytestmark = pytest.mark.django_db

TPCH_XLSX = Path(__file__).resolve().parents[3] / "TurboVault_TPCH_Data.xlsx"
needs_tpch = pytest.mark.skipif(
    not TPCH_XLSX.exists(), reason="bundled TPCH workbook missing"
)

_WRITE = re.compile(r"^\s*(INSERT|UPDATE|DELETE)\b", re.IGNORECASE)


def _capture() -> CaptureQueriesContext:
    """Capture the queries of a block.

    The connection keeps at most 9000 logged queries across the session, and
    a capture that starts on a full log sees none at all, which would make
    "no writes" pass vacuously. So start from an empty log.
    """
    connection.queries_log.clear()
    return CaptureQueriesContext(connection)


def _writes(queries: CaptureQueriesContext) -> list[str]:
    """The statements that changed metadata (the run's own ImportRun row aside)."""
    assert len(queries) < connection.queries_limit, "the capture overflowed"
    return [
        query["sql"]
        for query in queries.captured_queries
        if _WRITE.match(query["sql"]) and '"import_run"' not in query["sql"]
    ]


def _import(project: Project, source, **options):
    return import_metadata(
        project=project, source=source, options=ImportOptions(**options)
    )


def _entities(report) -> dict[tuple[str, str], object]:
    return {
        (entity.ref.type, entity.ref.name): entity for entity in report.plan.entities
    }


def _changes(entity) -> dict[str, tuple[str, object, object]]:
    return {
        change.field: (change.kind, change.before, change.after)
        for change in entity.changes
    }


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def _minimal_sheets() -> dict[str, list[list]]:
    """One source table, one hub, one satellite (the `minimal_workbook`)."""
    return {
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
            ["sat_customer_details", "h_cust", "crm.customer", "name", "name", 1],
            ["sat_customer_details", "h_cust", "crm.customer", "email", "email", 2],
        ],
    }


def _source_metadata() -> dict:
    return {
        "format": "source_metadata",
        "format_version": 1,
        "source_systems": [
            {
                "name": "CRM",
                "schema_name": "CRM",
                "database_name": "PROD_DB",
                "description": "Customer data warehouse",
                "tables": [
                    {
                        "physical_table_name": "CUSTOMERS",
                        "alias": "customer",
                        "record_source_value": "CRM_RAW",
                        "load_date_value": "_LOAD_DATE",
                        "description": "Master customer list",
                        "columns": [
                            {
                                "physical_name": "CUSTOMER_ID",
                                "datatype": "NUMBER(38,0)",
                                "description": "PK",
                            },
                            {"physical_name": "EMAIL", "datatype": "VARCHAR(255)"},
                        ],
                    },
                    {
                        "physical_table_name": "ORDERS",
                        "columns": [
                            {"physical_name": "ORDER_ID", "datatype": "NUMBER(38,0)"}
                        ],
                    },
                ],
            }
        ],
    }


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _tpch_export(tmp_path: Path) -> Path:
    """TPCH imported from Excel, exported as JSON."""
    origin = Project.objects.create(name="tpch-origin")
    report = _import(origin, ExcelSource(path=TPCH_XLSX), skip_snapshots=False)
    assert report.status == "success", report.issues
    out = tmp_path / "tpch.json"
    out.write_text(
        json.dumps(ModelBuilder(origin).build().model_dump(mode="json"), default=str),
        encoding="utf-8",
    )
    return out


def _same_source(case: str, tmp_path: Path, workbook_factory):
    if case == "minimal workbook":
        return ExcelSource(path=workbook_factory(_minimal_sheets())), {
            "skip_snapshots": True
        }
    if case == "TPCH workbook":
        return ExcelSource(path=TPCH_XLSX), {"skip_snapshots": False}
    if case == "TPCH JSON export":
        return JsonSource(path=_tpch_export(tmp_path)), {"skip_snapshots": False}
    return (
        SourceMetadataSource(
            path=_write_json(tmp_path / "sm.json", _source_metadata())
        ),
        {},
    )


# ---------------------------------------------------------------------------
# The same source again
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    [
        "minimal workbook",
        pytest.param("TPCH workbook", marks=needs_tpch),
        pytest.param("TPCH JSON export", marks=needs_tpch),
        "source metadata",
    ],
)
def test_importing_the_same_source_again_writes_and_reports_nothing(
    case, tmp_path, workbook_factory
):
    source, options = _same_source(case, tmp_path, workbook_factory)
    project = Project.objects.create(name="twice")
    first = _import(project, source, **options)
    assert first.status == "success", first.issues
    assert first.plan.counts.totals["create"] > 0

    with _capture() as queries:
        second = _import(project, source, **options)

    assert second.status == "success", second.issues
    totals = second.plan.counts.totals
    assert (totals["create"], totals["update"], totals["delete"]) == (0, 0, 0)
    assert totals["unchanged"] > 0
    changed = [
        (entity.ref.type, entity.ref.name, entity.changes)
        for entity in second.plan.entities
        if entity.changes
    ]
    assert changed == []
    assert _writes(queries) == []
    assert second.plan.state == "applied"


def test_a_dry_run_reports_exactly_what_the_import_then_does(
    tmp_path, workbook_factory
):
    project = Project.objects.create(name="dry")
    _import(
        project,
        ExcelSource(path=workbook_factory(_minimal_sheets())),
        skip_snapshots=True,
    )

    sheets = _minimal_sheets()
    sheets["standard_satellite"].append(
        ["sat_customer_details", "h_cust", "crm.customer", "phone", "phone", 3]
    )
    changed = ExcelSource(path=workbook_factory(sheets, filename="changed.xlsx"))

    with _capture() as queries:
        dry = _import(project, changed, skip_snapshots=True, dry_run=True)
    # The dry run wrote and rolled back: the project is as it was.
    assert _writes(queries)
    assert not SourceColumn.objects.filter(source_column_physical_name="phone").exists()
    assert dry.plan.state == "simulated"

    real = _import(project, changed, skip_snapshots=True)
    assert real.plan.state == "applied"
    assert [e.model_dump() for e in dry.plan.entities] == [
        e.model_dump() for e in real.plan.entities
    ]
    assert dry.plan.counts == real.plan.counts
    assert SourceColumn.objects.filter(source_column_physical_name="phone").exists()


def test_a_first_dry_run_creates_nothing(workbook_factory):
    project = Project.objects.create(name="first-dry")
    report = _import(
        project,
        ExcelSource(path=workbook_factory(_minimal_sheets())),
        skip_snapshots=True,
        dry_run=True,
    )
    assert report.status == "success", report.issues
    assert report.plan.counts.totals["create"] == 4  # system, table, hub, satellite
    assert not SourceSystem.objects.filter(project=project).exists()
    assert not Hub.objects.filter(project=project).exists()


# ---------------------------------------------------------------------------
# One change, reported on the entity it belongs to
# ---------------------------------------------------------------------------


def test_a_new_source_for_a_hub_makes_only_that_hub_an_update(workbook_factory):
    project = Project.objects.create(name="hub-source")
    _import(
        project,
        ExcelSource(path=workbook_factory(_minimal_sheets())),
        skip_snapshots=True,
    )

    sheets = _minimal_sheets()
    sheets["source_data"].append(
        ["erp", "erp_raw", "client", "erp.client", "erp.client", "load_dt"]
    )
    sheets["standard_hub"].append(
        [
            "hub_customer",
            "h_cust",
            "hk_customer",
            "customer_id",
            "erp.client",
            "client_no",
            "FALSE",
        ]
    )
    report = _import(
        project,
        ExcelSource(path=workbook_factory(sheets, filename="second.xlsx")),
        skip_snapshots=True,
    )

    entities = _entities(report)
    hub = entities[("hub", "hub_customer")]
    assert hub.action == "update"
    assert _changes(hub) == {
        "columns.customer_id.source_mappings.client.client_no": (
            "added",
            None,
            {"is_primary_source": False},
        )
    }
    assert hub.changes[0].path == [
        "columns",
        "customer_id",
        "source_mappings",
        "client.client_no",
    ]
    assert entities[("source_table", "client")].action == "create"
    assert entities[("satellite", "sat_customer_details")].action == "unchanged"
    assert entities[("source_table", "customer")].action == "unchanged"
    # The existing primary source stays the one.
    assert (
        HubSourceMapping.objects.filter(
            hub_column__hub__project=project, is_primary_source=True
        ).count()
        == 1
    )


def test_a_new_satellite_column_is_reported_on_the_satellite_and_its_table(
    workbook_factory,
):
    project = Project.objects.create(name="sat-column")
    _import(
        project,
        ExcelSource(path=workbook_factory(_minimal_sheets())),
        skip_snapshots=True,
    )

    sheets = _minimal_sheets()
    sheets["standard_satellite"].append(
        ["sat_customer_details", "h_cust", "crm.customer", "phone", "phone_number", 3]
    )
    report = _import(
        project,
        ExcelSource(path=workbook_factory(sheets, filename="second.xlsx")),
        skip_snapshots=True,
    )

    entities = _entities(report)
    satellite = _changes(entities[("satellite", "sat_customer_details")])
    assert list(satellite) == ["columns.phone"]
    kind, _, after = satellite["columns.phone"]
    assert kind == "added"
    assert after["target_column_name"] == "phone_number"
    assert after["column_sort_order"] == 3
    assert _changes(entities[("source_table", "customer")]) == {
        "columns.phone": ("added", None, {})
    }
    assert entities[("hub", "hub_customer")].action == "unchanged"


def test_a_renamed_satellite_column_is_a_field_change(workbook_factory):
    project = Project.objects.create(name="sat-rename")
    _import(
        project,
        ExcelSource(path=workbook_factory(_minimal_sheets())),
        skip_snapshots=True,
    )

    sheets = _minimal_sheets()
    sheets["standard_satellite"][2][4] = "email_address"
    report = _import(
        project,
        ExcelSource(path=workbook_factory(sheets, filename="second.xlsx")),
        skip_snapshots=True,
    )

    satellite = _entities(report)[("satellite", "sat_customer_details")]
    assert _changes(satellite) == {
        "columns.email.target_column_name": ("changed", None, "email_address")
    }


def test_source_metadata_reports_new_columns_and_type_changes(tmp_path):
    project = Project.objects.create(name="sm-changes")
    _import(
        project,
        SourceMetadataSource(path=_write_json(tmp_path / "a.json", _source_metadata())),
    )

    payload = _source_metadata()
    columns = payload["source_systems"][0]["tables"][0]["columns"]
    columns[1]["datatype"] = "VARCHAR(500)"
    columns.append({"physical_name": "PHONE", "datatype": "VARCHAR(40)"})
    report = _import(
        project, SourceMetadataSource(path=_write_json(tmp_path / "b.json", payload))
    )

    entities = _entities(report)
    assert _changes(entities[("source_table", "CUSTOMERS")]) == {
        "columns.EMAIL.source_column_datatype": (
            "changed",
            "VARCHAR(255)",
            "VARCHAR(500)",
        ),
        "columns.PHONE": ("added", None, {"source_column_datatype": "VARCHAR(40)"}),
    }
    assert entities[("source_table", "ORDERS")].action == "unchanged"
    assert entities[("source_system", "CRM")].action == "unchanged"
    assert report.plan.counts.totals == {
        "create": 0,
        "update": 1,
        "unchanged": 2,
        "delete": 0,
        "skip": 0,
    }


def test_an_excel_import_keeps_the_types_a_database_import_collected(
    tmp_path, workbook_factory
):
    """Excel creates source columns from the mappings that name them, without a type."""
    project = Project.objects.create(name="types-kept")
    payload = {
        "format": "source_metadata",
        "format_version": 1,
        "source_systems": [
            {
                "name": "crm",
                "schema_name": "crm_raw",
                "tables": [
                    {
                        "physical_table_name": "customer",
                        "record_source_value": "crm.customer",
                        "load_date_value": "load_dt",
                        "columns": [
                            {"physical_name": "customer_id", "datatype": "VARCHAR(40)"},
                            {"physical_name": "name", "datatype": "VARCHAR(100)"},
                            {"physical_name": "email", "datatype": "VARCHAR(255)"},
                        ],
                    }
                ],
            }
        ],
    }
    _import(
        project, SourceMetadataSource(path=_write_json(tmp_path / "db.json", payload))
    )

    report = _import(
        project,
        ExcelSource(path=workbook_factory(_minimal_sheets())),
        skip_snapshots=True,
    )

    assert report.status == "success", report.issues
    assert _entities(report)[("source_table", "customer")].action == "unchanged"
    assert dict(
        SourceColumn.objects.filter(source_table__project=project).values_list(
            "source_column_physical_name", "source_column_datatype"
        )
    ) == {"customer_id": "VARCHAR(40)", "name": "VARCHAR(100)", "email": "VARCHAR(255)"}


def test_a_renamed_source_system_is_an_update_and_replace_all_deletes_nothing(
    workbook_factory,
):
    project = Project.objects.create(name="rename")
    _import(
        project,
        ExcelSource(path=workbook_factory(_minimal_sheets())),
        skip_snapshots=True,
    )

    sheets = _minimal_sheets()
    sheets["source_data"][1][0] = "crm_v2"
    report = _import(
        project,
        ExcelSource(path=workbook_factory(sheets, filename="renamed.xlsx")),
        skip_snapshots=True,
        conflict_strategy="replace_all",
    )

    assert report.status == "success", report.issues
    entities = _entities(report)
    assert _changes(entities[("source_system", "crm_v2")]) == {
        "name": ("changed", "crm", "crm_v2")
    }
    assert report.plan.counts.totals["delete"] == 0
    assert SourceSystem.objects.get(project=project).name == "crm_v2"
    assert SatelliteColumn.objects.filter(satellite__project=project).count() == 2


def test_the_primary_source_flag_follows_the_file_when_it_sets_one(workbook_factory):
    project = Project.objects.create(name="primary")
    sheets = _minimal_sheets()
    sheets["source_data"].append(
        ["erp", "erp_raw", "client", "erp.client", "erp.client", "load_dt"]
    )
    sheets["standard_hub"].append(
        [
            "hub_customer",
            "h_cust",
            "hk_customer",
            "customer_id",
            "erp.client",
            "client_no",
            "FALSE",
        ]
    )
    _import(project, ExcelSource(path=workbook_factory(sheets)), skip_snapshots=True)

    sheets["standard_hub"][1][6] = "FALSE"
    sheets["standard_hub"][2][6] = "TRUE"
    report = _import(
        project,
        ExcelSource(path=workbook_factory(sheets, filename="flipped.xlsx")),
        skip_snapshots=True,
    )

    assert _changes(_entities(report)[("hub", "hub_customer")]) == {
        "columns.customer_id.source_mappings.customer.customer_id.is_primary_source": (
            "changed",
            True,
            False,
        ),
        "columns.customer_id.source_mappings.client.client_no.is_primary_source": (
            "changed",
            False,
            True,
        ),
    }


# ---------------------------------------------------------------------------
# Links keep their hub references
# ---------------------------------------------------------------------------


@needs_tpch
def test_link_hub_references_keep_their_identity_across_imports():
    project = Project.objects.create(name="links")
    _import(project, ExcelSource(path=TPCH_XLSX), skip_snapshots=True)
    references = set(
        LinkHubReference.objects.filter(link__project=project).values_list(
            "pk", flat=True
        )
    )
    mappings = set(
        LinkHubSourceMapping.objects.filter(
            link_hub_reference__link__project=project
        ).values_list("pk", flat=True)
    )
    assert references and mappings

    _import(project, ExcelSource(path=TPCH_XLSX), skip_snapshots=True)

    assert (
        set(
            LinkHubReference.objects.filter(link__project=project).values_list(
                "pk", flat=True
            )
        )
        == references
    )
    assert (
        set(
            LinkHubSourceMapping.objects.filter(
                link_hub_reference__link__project=project
            ).values_list("pk", flat=True)
        )
        == mappings
    )


@needs_tpch
def test_a_changed_hub_reference_alias_updates_the_reference_in_place(tmp_path):
    export = _tpch_export(tmp_path)
    project = Project.objects.create(name="alias")
    _import(project, JsonSource(path=export), skip_snapshots=False)

    data = json.loads(export.read_text())
    link = next(link for link in data["links"] if len(link["hub_references"]) >= 2)
    reference = link["hub_references"][0]
    old_alias = reference["hub_hashkey_alias_in_link"]
    reference["hub_hashkey_alias_in_link"] = "hk_renamed_in_link"
    before = LinkHubReference.objects.get(
        link__project=project,
        link__link_physical_name=link["link_name"],
        hub__hub_physical_name=reference["hub_name"],
        hub_hashkey_alias_in_link=old_alias or "",
    )

    report = _import(
        project,
        JsonSource(path=_write_json(tmp_path / "alias.json", data)),
        skip_snapshots=False,
    )

    changes = _changes(_entities(report)[("link", link["link_name"])])
    assert changes == {
        "hub_references.hk_renamed_in_link.hub_hashkey_alias_in_link": (
            "changed",
            old_alias or "",
            "hk_renamed_in_link",
        )
    }
    before.refresh_from_db()
    assert before.hub_hashkey_alias_in_link == "hk_renamed_in_link"


# ---------------------------------------------------------------------------
# What can't be written
# ---------------------------------------------------------------------------


def test_an_entity_that_fails_is_rolled_back_alone_and_reported_as_skipped(
    workbook_factory,
):
    project = Project.objects.create(name="fails")
    _import(
        project,
        ExcelSource(path=workbook_factory(_minimal_sheets())),
        skip_snapshots=True,
    )

    # Swapping two sort orders collides on the satellite's (satellite, sort order) key.
    sheets = _minimal_sheets()
    sheets["standard_satellite"][1][5] = 2
    sheets["standard_satellite"][2][5] = 1
    sheets["standard_hub"][1][2] = "hk_customer_renamed"
    report = _import(
        project,
        ExcelSource(path=workbook_factory(sheets, filename="swap.xlsx")),
        skip_snapshots=True,
        error_strategy="best_effort",
    )

    assert report.status == "partial_success"
    entities = _entities(report)
    satellite = entities[("satellite", "sat_customer_details")]
    assert (satellite.action, satellite.skip_reason, satellite.changes) == (
        "skip",
        "execute_failed",
        [],
    )
    # Nothing of the satellite was written; the hub's change was.
    assert dict(
        SatelliteColumn.objects.filter(satellite__project=project).values_list(
            "staging_column__source_column__source_column_physical_name",
            "column_sort_order",
        )
    ) == {"name": 1, "email": 2}
    assert entities[("hub", "hub_customer")].action == "update"
    assert Hub.objects.get(project=project).hub_hashkey_name == "hk_customer_renamed"


@needs_tpch
def test_pits_are_skipped_without_snapshots_and_kept_by_replace_all():
    project = Project.objects.create(name="pits")
    _import(project, ExcelSource(path=TPCH_XLSX), skip_snapshots=False)
    pits = PIT.objects.filter(project=project).count()
    assert pits

    report = _import(
        project,
        ExcelSource(path=TPCH_XLSX),
        skip_snapshots=True,
        conflict_strategy="replace_all",
    )

    assert {
        entity.skip_reason
        for entity in report.plan.entities
        if entity.ref.type == "pit"
    } == {"skip_snapshots"}
    assert PIT.objects.filter(project=project).count() == pits


def test_on_plan_can_stop_the_import_before_anything_is_written(workbook_factory):
    project = Project.objects.create(name="rejected")
    seen: list[ImportPlan] = []

    class RejectedError(Exception):
        pass

    def reject(plan: ImportPlan) -> None:
        seen.append(plan)
        raise RejectedError("over the limit")

    with pytest.raises(RejectedError):
        import_metadata(
            project=project,
            source=ExcelSource(path=workbook_factory(_minimal_sheets())),
            options=ImportOptions(skip_snapshots=True),
            on_plan=reject,
        )

    assert seen[0].counts.totals["create"] == 4
    assert seen[0].state == "planned"
    assert not SourceTable.objects.filter(project=project).exists()
    run = project.import_runs.get()
    assert run.report["issues"][0]["code"] == "plan.rejected"


# ---------------------------------------------------------------------------
# Counts and status
# ---------------------------------------------------------------------------


def test_counts_from_before_unchanged_existed_still_load():
    old = {
        "by_entity_type": {"hub": {"create": 1, "update": 2, "delete": 0, "skip": 0}},
        "totals": {"create": 1, "update": 2, "delete": 0, "skip": 0},
    }
    counts = PlanCounts.model_validate(copy.deepcopy(old))
    counts.add("hub", "unchanged")
    assert counts.by_entity_type["hub"]["unchanged"] == 1
    assert counts.totals["unchanged"] == 1
    assert "unchanged" in PlanCounts().totals


def test_an_import_that_only_confirmed_entities_is_a_partial_success():
    from engine.services.imports.errors import make_issue

    plan = ImportPlan()
    plan.counts.add("hub", "unchanged")
    error = make_issue(
        severity="error", code="entity.missing_parent", stage="execute", message="x"
    )
    assert (
        determine_status(
            is_dry_run=False, issues=[error], plan=plan, executor_committed=True
        )
        == "partial_success"
    )
    assert (
        determine_status(
            is_dry_run=True, issues=[error], plan=plan, executor_committed=False
        )
        == "validation_failed"
    )
