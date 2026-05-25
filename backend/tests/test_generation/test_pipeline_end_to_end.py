"""End-to-end tests for the generation pipeline.

These tests run the full pipeline (build → validate → plan → render →
write → report) via the public `generate()` entry point. To avoid the
heavy setup of building a fully populated Django Project, they monkey-
patch the build stage to return a pre-made `ProjectExport` from the
sample fixture. Everything downstream of build runs for real.
"""

from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.django_db


def _patch_build_stage(monkeypatch, project_export):
    """Substitute build_export so the pipeline uses the sample export."""
    from engine.services.generation.stages import build as build_module
    from engine.services.generation import pipeline as pipeline_module

    def fake_build(**_kwargs):
        return project_export

    monkeypatch.setattr(build_module, "build_export", fake_build)
    monkeypatch.setattr(pipeline_module, "build_export", fake_build)


@pytest.fixture
def engine_project(django_setup, db):
    """A minimal Django Project that the pipeline can target."""
    from engine.models import Project

    return Project.objects.create(name="pipeline_e2e", description="test")


def test_dbt_end_to_end_writes_files_and_persists_run(
    django_setup, project_export, engine_project, tmp_path, monkeypatch
):
    from engine.models import GenerationRun
    from engine.services.generation import generate

    _patch_build_stage(monkeypatch, project_export)

    out = tmp_path / "dbt_out"
    report = generate(
        project=engine_project,
        output_type="dbt",
        output_path=out,
    )

    assert report.status in ("success", "partial_success")
    assert report.is_dry_run is False
    # Some files landed on disk.
    assert report.files_generated > 0
    assert any(a.path for a in report.artifacts)
    # Per-stage timings captured.
    for stage in ("build", "validate", "plan", "render", "write"):
        assert stage in report.timings_ms

    # Audit row persisted.
    run = GenerationRun.objects.get(generation_run_id=report.generation_run_id)
    assert run.status == report.status
    assert run.output_type == "dbt"
    assert run.files_generated == report.files_generated


def test_dry_run_does_not_write_files_but_still_persists_run(
    django_setup, project_export, engine_project, tmp_path, monkeypatch
):
    from engine.models import GenerationRun
    from engine.services.generation import GenerationOptions, generate

    _patch_build_stage(monkeypatch, project_export)

    report = generate(
        project=engine_project,
        output_type="dbt",
        output_path=None,
        options=GenerationOptions(dry_run=True),
    )

    assert report.is_dry_run is True
    # Plan still computed, artifacts captured (without paths).
    assert report.plan.files_planned > 0
    assert all(a.path is None for a in report.artifacts)

    run = GenerationRun.objects.get(generation_run_id=report.generation_run_id)
    assert run.is_dry_run is True


def test_json_end_to_end_writes_single_file(
    django_setup, project_export, engine_project, tmp_path, monkeypatch
):
    from engine.services.generation import generate

    _patch_build_stage(monkeypatch, project_export)

    out = tmp_path / "model.json"
    report = generate(
        project=engine_project,
        output_type="json",
        output_path=out,
    )

    assert report.status in ("success", "partial_success")
    assert out.exists()
    json_artifacts = [a for a in report.artifacts if a.kind == "json_export"]
    assert len(json_artifacts) == 1
    assert json_artifacts[0].size_bytes > 0
    assert json_artifacts[0].checksum


def test_dbml_end_to_end_writes_single_file(
    django_setup, project_export, engine_project, tmp_path, monkeypatch
):
    from engine.services.generation import generate

    _patch_build_stage(monkeypatch, project_export)

    out = tmp_path / "model.dbml"
    report = generate(
        project=engine_project,
        output_type="dbml",
        output_path=out,
    )

    assert report.status in ("success", "partial_success")
    assert out.exists()
    dbml_artifacts = [a for a in report.artifacts if a.kind == "dbml_export"]
    assert len(dbml_artifacts) == 1


def test_single_entity_preview_returns_content_without_writing(
    django_setup, project_export, engine_project, monkeypatch
):
    """The Studio metadata-editor preview use case:
    dry_run + return_content + only_entities selection on a single hub
    yields rendered sql+yml strings with no filesystem writes."""
    from engine.services.generation import (
        EntityRef,
        EntitySelection,
        GenerationOptions,
        generate,
    )

    _patch_build_stage(monkeypatch, project_export)

    if not project_export.hubs:
        pytest.skip("Sample export has no hubs")
    target = project_export.hubs[0]

    report = generate(
        project=engine_project,
        output_type="dbt",
        options=GenerationOptions(
            dry_run=True,
            return_content=True,
            entity_selection=EntitySelection(
                only_entities=[EntityRef(type="hub", name=target.hub_name)],
            ),
        ),
    )

    # Plan should only contain hub artifacts (no other entity types).
    assert "hub" in report.plan.by_entity_type
    for kind, count in report.plan.by_entity_type.items():
        if kind in ("link", "satellite", "pit", "reference_table"):
            assert count == 0, f"Selection leaked into {kind}"

    # Every emitted artifact must carry its rendered content and no path.
    written = [a for a in report.artifacts if a.kind in ("sql_model", "yaml_schema")]
    assert written, "Expected at least one sql/yaml artifact for the previewed hub"
    for a in written:
        assert a.content is not None and a.content.strip(), "Content should be populated"
        assert a.path is None, "Dry-run must not record filesystem paths"
