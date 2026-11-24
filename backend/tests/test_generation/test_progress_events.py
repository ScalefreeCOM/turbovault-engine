"""The progress events a generation emits, and their details.

Every stage reports a summary when done; render and write report each file
as `in_progress`, numbered 1..total. A callback that raises an `Exception`
is ignored; a `BaseException` stops the run and propagates. Without a
callback nothing is built for it.

The TPCH workbook is imported into a project, and the pipeline runs for real
from the build stage on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.django_db

TPCH_XLSX = Path(__file__).resolve().parents[3] / "TurboVault_TPCH_Data.xlsx"
needs_tpch = pytest.mark.skipif(
    not TPCH_XLSX.exists(), reason="bundled TPCH workbook missing"
)


class StopRun(BaseException):
    """What a caller raises from the callback to stop the run."""


@pytest.fixture
def tpch_project(django_setup, db):
    from engine.models import Project
    from engine.services.imports import ExcelSource, import_metadata

    project = Project.objects.create(name="tpch_progress")
    report = import_metadata(project=project, source=ExcelSource(path=TPCH_XLSX))
    assert report.status == "success", report.issues
    return project


def _generate(project, output_type="dbt", output_path=None, events=None, **options):
    from engine.services.generation import GenerationOptions, generate

    return generate(
        project=project,
        output_type=output_type,
        output_path=output_path,
        options=GenerationOptions(**options),
        progress=None if events is None else events.append,
    )


def _done(events, stage):
    [event] = [e for e in events if e.stage == stage and e.status == "done"]
    return event


def _items(events, stage):
    return [e for e in events if e.stage == stage and e.status == "in_progress"]


def _relative(path: str, root: Path) -> str:
    return Path(path).relative_to(root).as_posix()


def _files_on_disk(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


# ---------------------------------------------------------------------------
# Stage summaries
# ---------------------------------------------------------------------------


@needs_tpch
def test_each_stage_reports_its_summary_when_done(tpch_project, tmp_path):
    from engine.models import (
        PIT,
        Hub,
        Link,
        ReferenceTable,
        Satellite,
        SourceSystem,
        SourceTable,
    )

    events: list = []
    out = tmp_path / "dbt"
    report = _generate(tpch_project, output_path=out, events=events)
    assert report.status == "success", report.issues

    assert [(e.stage, e.status) for e in events if e.status != "in_progress"] == [
        ("build", "started"),
        ("build", "done"),
        ("validate", "started"),
        ("validate", "done"),
        ("plan", "started"),
        ("plan", "done"),
        ("render", "started"),
        ("render", "done"),
        ("write", "started"),
        ("write", "done"),
        ("report", "done"),
    ]

    entities = _done(events, "build").detail["entities"]
    assert set(entities) == {
        "source",
        "source_table",
        "prestage",
        "stage",
        "hub",
        "link",
        "satellite",
        "pit",
        "reference_table",
        "snapshot_control",
    }
    project = tpch_project
    assert entities["source"] == SourceSystem.objects.filter(project=project).count()
    assert (
        entities["source_table"]
        == SourceTable.objects.filter(source_system__project=project).count()
    )
    assert entities["hub"] == Hub.objects.filter(project=project).count() > 0
    assert entities["link"] == Link.objects.filter(project=project).count() > 0
    assert entities["satellite"] == Satellite.objects.filter(project=project).count()
    assert entities["pit"] == PIT.objects.filter(project=project).count()
    assert (
        entities["reference_table"]
        == ReferenceTable.objects.filter(project=project).count()
    )

    validate_issues = [i for i in report.issues if i.stage == "validate"]
    assert _done(events, "validate").detail == {
        "errors": sum(1 for i in validate_issues if i.severity == "error"),
        "warnings": sum(1 for i in validate_issues if i.severity == "warning"),
    }
    assert _done(events, "plan").detail == {
        "files_planned": report.plan.files_planned,
        "by_entity_type": report.plan.by_entity_type,
    }
    assert _done(events, "render").detail == {"files": len(report.artifacts)}

    sizes = {_relative(a.path, out): a.size_bytes for a in report.artifacts}
    assert _done(events, "write").detail == {
        "files": len(sizes),
        "size_bytes": sum(sizes.values()),
    }
    assert sum(sizes.values()) == sum((out / path).stat().st_size for path in sizes)
    # Stage events carry no counters; only per-file events do.
    assert all(
        e.current is None and e.total is None
        for e in events
        if e.status != "in_progress"
    )


# ---------------------------------------------------------------------------
# Per-file events
# ---------------------------------------------------------------------------


@needs_tpch
def test_render_and_write_report_each_file_numbered_to_the_total(
    tpch_project, tmp_path
):
    events: list = []
    out = tmp_path / "dbt"
    report = _generate(tpch_project, output_path=out, events=events)
    assert report.status == "success", report.issues

    rendered = _items(events, "render")
    assert len(rendered) > 100
    assert [e.current for e in rendered] == list(range(1, len(rendered) + 1))
    assert {e.total for e in rendered} == {len(rendered)}
    # One per artifact, carrying its fields; the path relative to the output.
    assert [e.detail for e in rendered] == [
        {
            "path": _relative(a.path, out),
            "kind": a.kind,
            "entity_type": a.entity_type,
            "entity_name": a.entity_name,
        }
        for a in report.artifacts
    ]
    hub = next(e for e in rendered if e.detail["entity_type"] == "hub_standard")
    assert hub.message == f"Rendered {hub.detail['path']}"
    assert hub.detail["kind"] == "sql_model"
    assert hub.detail["path"].endswith(f"/{hub.detail['entity_name']}.sql")

    written = _items(events, "write")
    assert len(written) == len(rendered)
    assert [e.current for e in written] == list(range(1, len(written) + 1))
    assert {e.total for e in written} == {len(written)}
    for event in written:
        assert set(event.detail) == {"path", "size_bytes"}
        assert event.message == f"Wrote {event.detail['path']}"
        assert (out / event.detail["path"]).stat().st_size == event.detail["size_bytes"]
    assert {e.detail["path"] for e in written} == {
        _relative(a.path, out) for a in report.artifacts
    }
    # Every in-progress event is plain JSON
    for event in rendered + written:
        assert event.model_dump(mode="json") == event.model_dump()


@needs_tpch
def test_a_dry_run_renders_every_file_and_writes_none(tpch_project):
    events: list = []
    report = _generate(tpch_project, events=events, dry_run=True)
    assert report.status == "success", report.issues

    rendered = _items(events, "render")
    assert len(rendered) == len(report.artifacts) > 0
    assert [e.current for e in rendered] == list(range(1, len(rendered) + 1))
    assert all(e.detail["path"] for e in rendered)

    assert _items(events, "write") == []
    assert _done(events, "write").detail == {"files": 0, "size_bytes": 0}


@needs_tpch
def test_write_once_files_that_exist_are_kept_not_counted(tpch_project, tmp_path):
    out = tmp_path / "sqlmesh"
    _generate(tpch_project, output_type="sqlmesh", output_path=out)

    events: list = []
    report = _generate(
        tpch_project, output_type="sqlmesh", output_path=out, events=events
    )
    assert not report.has_errors, report.issues

    written = _items(events, "write")
    paths = {e.detail["path"] for e in written}
    # config.yaml, config.json and requirements.txt are written once
    assert paths.isdisjoint({"config.yaml", "config.json", "requirements.txt"})
    assert {"models/__init__.py", "README.md"} <= paths
    assert [e.current for e in written] == list(range(1, len(written) + 1))
    assert {e.total for e in written} == {len(written)}
    assert _done(events, "write").detail == {
        "files": len(written),
        "size_bytes": sum(e.detail["size_bytes"] for e in written),
    }
    # The render stage still renders them
    assert len(_items(events, "render")) == len(written) + 3


@needs_tpch
def test_a_json_export_is_one_file(tpch_project, tmp_path):
    events: list = []
    report = _generate(
        tpch_project,
        output_type="json",
        output_path=tmp_path / "model.json",
        events=events,
    )
    assert report.status == "success", report.issues

    [rendered] = _items(events, "render")
    assert (rendered.current, rendered.total) == (1, 1)
    assert rendered.detail == {
        "path": None,
        "kind": "json_export",
        "entity_type": None,
        "entity_name": None,
    }
    assert rendered.message == "Rendered json export"

    [written] = _items(events, "write")
    size = (tmp_path / "model.json").stat().st_size
    assert written.detail == {"path": "model.json", "size_bytes": size}
    assert _done(events, "write").detail == {"files": 1, "size_bytes": size}


# ---------------------------------------------------------------------------
# Callbacks: none, failing, stopping
# ---------------------------------------------------------------------------


@needs_tpch
def test_without_a_callback_no_detail_is_built(tpch_project, tmp_path, monkeypatch):
    from engine.services.generation import pipeline as pipeline_module
    from engine.services.generation.stages import render as render_module
    from engine.services.generation.stages import write as write_module

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("built progress detail without a callback")

    # Inside the pipeline an exception becomes an internal.bug issue, so a
    # success shows the summaries weren't built.
    monkeypatch.setattr(pipeline_module, "entity_counts", must_not_run)
    monkeypatch.setattr(pipeline_module, "_issue_counts", must_not_run)
    monkeypatch.setattr(pipeline_module, "_write_summary", must_not_run)
    monkeypatch.setattr(render_module, "emit", must_not_run)
    monkeypatch.setattr(write_module, "emit", must_not_run)

    report = _generate(tpch_project, output_path=tmp_path / "dbt")
    assert report.status == "success", report.issues
    assert report.files_generated > 100


@needs_tpch
def test_an_exception_from_the_callback_is_ignored(tpch_project, tmp_path):
    calls: list = []

    def broken(event):
        calls.append(event)
        raise RuntimeError("the consumer is broken")

    from engine.services.generation import generate

    report = generate(
        project=tpch_project,
        output_type="dbt",
        output_path=tmp_path / "dbt",
        progress=broken,
    )
    assert report.status == "success", report.issues
    assert report.files_generated > 100
    assert len(calls) > 2 * report.files_generated


@needs_tpch
@pytest.mark.parametrize(
    "stage, status",
    [("build", "done"), ("render", "in_progress"), ("write", "in_progress")],
)
def test_a_base_exception_from_the_callback_stops_the_run(
    tpch_project, tmp_path, stage, status
):
    from engine.models import GenerationRun
    from engine.services.generation import generate

    out = tmp_path / "dbt"
    seen: list = []

    def stop_at_the_third(event):
        seen.append(event)
        matching = [e for e in seen if (e.stage, e.status) == (stage, status)]
        if len(matching) == (3 if status == "in_progress" else 1):
            raise StopRun()

    runs_before = GenerationRun.objects.count()
    with pytest.raises(StopRun):
        generate(
            project=tpch_project,
            output_type="dbt",
            output_path=out,
            progress=stop_at_the_third,
        )

    # Nothing after the stop: no further event, no report, no run recorded
    assert (seen[-1].stage, seen[-1].status) == (stage, status)
    assert GenerationRun.objects.count() == runs_before
    if stage == "write":
        # The files written before the stop, and only those
        assert _files_on_disk(out) == {e.detail["path"] for e in _items(seen, "write")}
        assert len(_items(seen, "write")) == 3
    else:
        assert not out.exists() or _files_on_disk(out) == set()
