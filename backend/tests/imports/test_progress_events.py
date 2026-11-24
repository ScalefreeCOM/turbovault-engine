"""The progress events an import emits, and their details.

Every stage reports a summary when done; the execute stage reports each
entity it applies as `in_progress`, numbered 1..total, with what applying it
did. A callback that raises an `Exception` is ignored; a `BaseException`
stops the import and propagates, and the execute transaction rolls back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine.models import (
    PIT,
    Hub,
    ImportRun,
    Link,
    Project,
    ReferenceTable,
    Satellite,
    SourceColumn,
    SourceTable,
)
from engine.services.export.builder import ModelBuilder
from engine.services.imports import (
    ExcelSource,
    ImportOptions,
    JsonSource,
    import_metadata,
)

pytestmark = pytest.mark.django_db

TPCH_XLSX = Path(__file__).resolve().parents[3] / "TurboVault_TPCH_Data.xlsx"
needs_tpch = pytest.mark.skipif(
    not TPCH_XLSX.exists(), reason="bundled TPCH workbook missing"
)


class StopImport(BaseException):
    """What a caller raises from the callback to stop the import."""


def _import(project: Project, source, events=None, on_plan=None, **options):
    return import_metadata(
        project=project,
        source=source,
        options=ImportOptions(**options),
        progress=None if events is None else events.append,
        on_plan=on_plan,
    )


def _done(events, stage):
    [event] = [e for e in events if e.stage == stage and e.status == "done"]
    return event


def _applied(events):
    return [e for e in events if e.stage == "execute" and e.status == "in_progress"]


def _snapshot(project: Project) -> dict:
    """Everything the project holds, as an export."""
    return (
        ModelBuilder(project).build().model_dump(mode="json", exclude={"generated_at"})
    )


# ---------------------------------------------------------------------------
# Stage summaries
# ---------------------------------------------------------------------------


def test_each_stage_reports_its_summary_when_done(project, minimal_workbook):
    events: list = []
    planned: list = []
    report = _import(
        project,
        ExcelSource(path=minimal_workbook),
        events=events,
        on_plan=planned.append,
        skip_snapshots=True,
    )
    assert report.status == "success", report.issues

    assert [(e.stage, e.status) for e in events if e.status != "in_progress"] == [
        ("parse", "started"),
        ("parse", "done"),
        ("validate", "started"),
        ("validate", "done"),
        ("plan", "started"),
        ("plan", "done"),
        ("execute", "started"),
        ("execute", "done"),
        ("report", "done"),
    ]
    # A workbook is read as sheets of rows
    assert _done(events, "parse").detail == {
        "read": {"source_data": 1, "standard_hub": 1, "standard_satellite": 2}
    }
    found = [i for i in report.issues if i.stage in ("validate", "resolve")]
    assert _done(events, "validate").detail == {
        "errors": sum(1 for i in found if i.severity == "error"),
        "warnings": sum(1 for i in found if i.severity == "warning"),
    }
    # The plan as built, before the executor knew what changes
    [plan] = planned
    assert _done(events, "plan").detail == {
        "totals": plan.counts.totals,
        "by_entity_type": plan.counts.by_entity_type,
    }
    assert plan.counts.totals["create"] > 0
    totals = report.plan.counts.totals
    assert _done(events, "execute").detail == {
        "applied": totals["create"] + totals["update"] + totals["delete"]
    }
    assert _done(events, "execute").detail["applied"] == totals["create"] > 0


@needs_tpch
def test_a_json_source_is_read_as_entities(tmp_path):
    origin = Project.objects.create(name="tpch-origin")
    assert _import(origin, ExcelSource(path=TPCH_XLSX)).status == "success"
    export = tmp_path / "tpch.json"
    export.write_text(json.dumps(_snapshot(origin)), encoding="utf-8")

    events: list = []
    report = _import(
        Project.objects.create(name="copy"), JsonSource(path=export), events
    )
    assert report.status == "success", report.issues

    read = _done(events, "parse").detail["read"]
    assert set(read) == {
        "source_system",
        "source_table",
        "source_column",
        "hub",
        "link",
        "satellite",
        "pit",
        "reference_table",
        "snapshot_control",
        "prejoin",
    }
    # Each once, though the parser also keys some by an alias
    assert read["source_system"] == origin.source_systems.count() == 1
    assert (
        read["source_table"]
        == SourceTable.objects.filter(source_system__project=origin).count()
    )
    # The parser keys a table's columns by name: one listed twice is one
    payload = json.loads(export.read_text(encoding="utf-8"))
    assert read["source_column"] == len(
        {
            (table["table_name"], column["column_name"].lower())
            for system in payload["sources"]
            for table in system["tables"]
            for column in table["columns"]
        }
    )
    assert (
        0
        < read["source_column"]
        <= SourceColumn.objects.filter(
            source_table__source_system__project=origin
        ).count()
    )
    assert read["hub"] == Hub.objects.filter(project=origin).count() > 0
    assert read["link"] == Link.objects.filter(project=origin).count() > 0
    assert read["satellite"] == Satellite.objects.filter(project=origin).count() > 0
    assert read["pit"] == PIT.objects.filter(project=origin).count() == 1
    assert (
        read["reference_table"]
        == ReferenceTable.objects.filter(project=origin).count()
        == 1
    )


# ---------------------------------------------------------------------------
# Per-entity events
# ---------------------------------------------------------------------------


@needs_tpch
def test_execute_reports_each_entity_as_it_is_applied(project):
    events: list = []
    report = _import(project, ExcelSource(path=TPCH_XLSX), events)
    assert report.status == "success", report.issues

    applied = _applied(events)
    assert len(applied) == len(report.plan.entities) > 30
    assert [e.current for e in applied] == list(range(1, len(applied) + 1))
    assert {e.total for e in applied} == {len(applied)}
    # What applying each did, as the report names it
    assert sorted(
        (e.detail["entity_type"], e.detail["name"], e.detail["action"]) for e in applied
    ) == sorted((e.ref.type, e.ref.name, e.action) for e in report.plan.entities)
    assert {e.detail["action"] for e in applied} == {"create"}
    first = applied[0]
    assert first.detail == {
        "entity_type": "source_system",
        "name": first.detail["name"],
        "action": "create",
    }
    assert first.message == f"Created source system {first.detail['name']}"
    hub = next(e for e in applied if e.detail["entity_type"] == "hub")
    assert hub.message == f"Created hub {hub.detail['name']}"
    pit = next(e for e in applied if e.detail["entity_type"] == "pit")
    assert pit.message == f"Created PIT {pit.detail['name']}"


def test_a_reimport_reports_every_entity_unchanged(project, minimal_workbook):
    source = ExcelSource(path=minimal_workbook)
    _import(project, source, skip_snapshots=True)

    events: list = []
    report = _import(project, source, events, skip_snapshots=True)
    assert report.status == "success", report.issues

    applied = _applied(events)
    assert len(applied) == len(report.plan.entities) > 0
    assert {e.detail["action"] for e in applied} == {"unchanged"}
    hub = next(e for e in applied if e.detail["entity_type"] == "hub")
    assert hub.message == "No changes to hub hub_customer"
    assert _done(events, "execute").detail == {"applied": 0}


def test_a_dry_run_reports_what_it_would_do_and_applies_nothing(
    project, minimal_workbook
):
    events: list = []
    report = _import(
        project,
        ExcelSource(path=minimal_workbook),
        events,
        dry_run=True,
        skip_snapshots=True,
    )
    assert report.status == "success", report.issues

    applied = _applied(events)
    assert len(applied) == len(report.plan.entities) > 0
    assert {e.detail["action"] for e in applied} == {"create"}
    hub = next(e for e in applied if e.detail["entity_type"] == "hub")
    assert hub.message == "Would create hub hub_customer"
    assert _done(events, "execute").detail == {"applied": 0}
    assert not Hub.objects.filter(project=project).exists()


def test_deletes_are_applied_first(project, workbook_factory, minimal_workbook):
    import openpyxl

    _import(project, ExcelSource(path=minimal_workbook), skip_snapshots=True)
    # The same workbook without its satellite
    workbook = openpyxl.load_workbook(minimal_workbook)
    sheets = {
        name: [list(row) for row in workbook[name].iter_rows(values_only=True)]
        for name in ("source_data", "standard_hub")
    }
    events: list = []
    report = _import(
        project,
        ExcelSource(path=workbook_factory(sheets, "no_satellite.xlsx")),
        events,
        conflict_strategy="replace_all",
        skip_snapshots=True,
    )
    assert report.status == "success", report.issues

    applied = _applied(events)
    assert applied[0].detail == {
        "entity_type": "satellite",
        "name": "sat_customer_details",
        "action": "delete",
    }
    assert applied[0].message == "Deleted satellite sat_customer_details"
    assert [e.current for e in applied] == list(range(1, len(applied) + 1))
    assert _done(events, "execute").detail == {"applied": 1}


# ---------------------------------------------------------------------------
# Callbacks: none, failing, stopping
# ---------------------------------------------------------------------------


def test_without_a_callback_no_detail_is_built(project, minimal_workbook, monkeypatch):
    from engine.services import imports as imports_module
    from engine.services.imports import executor as executor_module

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("built progress detail without a callback")

    monkeypatch.setattr(imports_module, "read_counts", must_not_run)
    monkeypatch.setattr(imports_module, "_issue_counts", must_not_run)
    monkeypatch.setattr(executor_module, "emit", must_not_run)

    report = _import(project, ExcelSource(path=minimal_workbook), skip_snapshots=True)
    assert report.status == "success", report.issues
    assert Hub.objects.filter(project=project).exists()


def test_an_exception_from_the_callback_is_ignored(project, minimal_workbook):
    calls: list = []

    def broken(event):
        calls.append(event)
        raise RuntimeError("the consumer is broken")

    report = import_metadata(
        project=project,
        source=ExcelSource(path=minimal_workbook),
        options=ImportOptions(skip_snapshots=True),
        progress=broken,
    )
    assert report.status == "success", report.issues
    assert Hub.objects.filter(project=project).exists()
    assert any(e.status == "in_progress" for e in calls)


@needs_tpch
def test_a_base_exception_during_execute_rolls_back_and_propagates(
    project, minimal_workbook
):
    """The project stays as it was, though entities were already written."""
    _import(project, ExcelSource(path=minimal_workbook), skip_snapshots=True)
    before = _snapshot(project)
    tables_before = SourceTable.objects.filter(source_system__project=project).count()
    runs_before = ImportRun.objects.count()
    seen: list = []
    tables_at_stop: list[int] = []

    def stop_at_the_third(event):
        seen.append(event)
        if len(_applied(seen)) == 3:
            tables_at_stop.append(
                SourceTable.objects.filter(source_system__project=project).count()
            )
            raise StopImport()

    with pytest.raises(StopImport):
        import_metadata(
            project=project,
            source=ExcelSource(path=TPCH_XLSX),
            options=ImportOptions(),
            progress=stop_at_the_third,
        )

    # Written when it stopped, rolled back since
    assert tables_at_stop[0] > tables_before
    assert _snapshot(project) == before
    # Nothing after the stop: no further event, no report, no run recorded
    assert (seen[-1].stage, seen[-1].status) == ("execute", "in_progress")
    assert ImportRun.objects.count() == runs_before


@pytest.mark.parametrize("stage", ["parse", "plan"])
def test_a_base_exception_before_execute_propagates(project, minimal_workbook, stage):
    def stop(event):
        if (event.stage, event.status) == (stage, "done"):
            raise StopImport()

    with pytest.raises(StopImport):
        import_metadata(
            project=project,
            source=ExcelSource(path=minimal_workbook),
            options=ImportOptions(skip_snapshots=True),
            progress=stop,
        )
    assert not Hub.objects.filter(project=project).exists()
    assert not ImportRun.objects.filter(project=project).exists()
