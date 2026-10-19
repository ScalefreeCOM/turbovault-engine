"""End-to-end tests for the configurable dbt_project.yml and optional profiles.yml.

Covers the runtime_config → GenerationConfig → template handoff for the
profile, control schema and per-layer materializations, and the opt-in
profiles.yml artifact (kind, plan count, zip inclusion, secret rejection).
"""

from __future__ import annotations

import zipfile

import pytest
import yaml

pytestmark = pytest.mark.django_db


# The dbt_project.yml the engine generated before these settings existed.
# With default settings the output must stay byte-identical to this.
EXPECTED_DEFAULT_DBT_PROJECT_YML = """\
name: 'pipeline_e2e'
version: '1.0.0'
config-version: 2

profile: 'default'

model-paths: ["models"]
analysis-paths: ["analyses"]
test-paths: ["tests"]
seed-paths: ["seeds"]
macro-paths: ["macros"]
snapshot-paths: ["snapshots"]

clean-targets:
  - "target"
  - "dbt_packages"

models:
  pipeline_e2e:
    00_control:
      +schema: control
      +materialized: table
    02_staging:
      +schema: stage
      +materialized: view
    03_raw_vault:
      +schema: rdv
      +materialized: incremental
    04_business_vault:
      +schema: bdv
      +materialized: table
"""

PROFILES = {
    "scalefree_dv": {
        "target": "dev",
        "outputs": {
            "dev": {
                "type": "postgres",
                "host": "localhost",
                "port": 5432,
                "user": "{{ env_var('DBT_USER') }}",
                "password": "{{ env_var('DBT_PASSWORD') }}",
                "dbname": "analytics",
                "schema": "dv",
                "threads": 4,
            }
        },
    }
}


def _patch_build_stage(monkeypatch, project_export):
    """Substitute build_export so the pipeline uses the fixture export."""
    from engine.services.generation import pipeline as pipeline_module
    from engine.services.generation.stages import build as build_module

    def fake_build(**_kwargs):
        return project_export

    monkeypatch.setattr(build_module, "build_export", fake_build)
    monkeypatch.setattr(pipeline_module, "build_export", fake_build)


@pytest.fixture
def engine_project(django_setup, db):
    from engine.models import Project

    return Project.objects.create(name="pipeline_e2e", description="test")


@pytest.fixture
def run(django_setup, project_export, engine_project, tmp_path, monkeypatch):
    """Run the dbt pipeline with the given runtime-config overrides."""
    from engine.services.generation import GenerationOptions, generate
    from engine.services.runtime_config import EngineRuntimeConfig

    _patch_build_stage(monkeypatch, project_export)

    def _run(create_zip: bool = False, **overrides):
        out = tmp_path / "dbt_out"
        report = generate(
            project=engine_project,
            output_type="dbt",
            output_path=out,
            runtime_config=EngineRuntimeConfig(
                project_name="pipeline_e2e", **overrides
            ),
            options=GenerationOptions(create_zip=create_zip),
        )
        return report, out

    return _run


def _project_count(report) -> int:
    return report.plan.by_entity_type["project"]


class TestDbtProjectYml:
    def test_defaults_are_byte_identical(self, run):
        report, out = run()
        assert report.status in ("success", "partial_success")
        content = (out / "dbt_project.yml").read_text(encoding="utf-8")
        assert content == EXPECTED_DEFAULT_DBT_PROJECT_YML

    def test_overrides_render_valid_yaml(self, run):
        report, out = run(
            profile_name="scalefree_dv",
            control_schema="meta",
            control_materialization="view",
            staging_materialization="ephemeral",
            raw_vault_materialization="table",
            business_vault_materialization="view",
        )
        assert report.status in ("success", "partial_success")

        parsed = yaml.safe_load((out / "dbt_project.yml").read_text(encoding="utf-8"))
        assert parsed["profile"] == "scalefree_dv"
        layers = parsed["models"]["pipeline_e2e"]
        assert layers["00_control"] == {"+schema": "meta", "+materialized": "view"}
        assert layers["02_staging"]["+materialized"] == "ephemeral"
        assert layers["03_raw_vault"]["+materialized"] == "table"
        assert layers["04_business_vault"]["+materialized"] == "view"


class TestProfilesYml:
    def test_omitted_when_flag_off(self, run):
        report, out = run(profiles=PROFILES)  # mapping alone is not enough
        assert not (out / "profiles.yml").exists()
        assert not any(a.kind == "dbt_profiles" for a in report.artifacts)

    def test_rendered_as_artifact_and_counted(self, run):
        baseline, _ = run()
        report, out = run(
            profile_name="scalefree_dv", generate_profiles_yml=True, profiles=PROFILES
        )

        assert report.status in ("success", "partial_success")
        parsed = yaml.safe_load((out / "profiles.yml").read_text(encoding="utf-8"))
        assert parsed == PROFILES

        profile_artifacts = [a for a in report.artifacts if a.kind == "dbt_profiles"]
        assert len(profile_artifacts) == 1
        assert profile_artifacts[0].path.replace("\\", "/").endswith("profiles.yml")

        assert _project_count(report) == _project_count(baseline) + 1
        assert report.plan.files_planned == baseline.plan.files_planned + 1

    def test_included_in_zip(self, run):
        report, out = run(
            create_zip=True,
            profile_name="scalefree_dv",
            generate_profiles_yml=True,
            profiles=PROFILES,
        )
        zip_path = out.with_suffix(".zip")
        assert zip_path.exists()
        with zipfile.ZipFile(zip_path) as zf:
            assert "dbt_out/profiles.yml" in zf.namelist()

    def test_literal_secret_writes_nothing(self, run):
        profiles = {
            "p": {
                "target": "dev",
                "outputs": {"dev": {"type": "postgres", "password": "hunter2"}},
            }
        }
        report, out = run(
            profile_name="p", generate_profiles_yml=True, profiles=profiles
        )

        issues = [
            i for i in report.issues if i.code == "render.literal_secret_in_profile"
        ]
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert "hunter2" not in issues[0].message
        assert report.status == "validation_failed"
        assert report.files_generated == 0
        assert not (out / "dbt_project.yml").exists()

    def test_invalid_structure_reported(self, run):
        report, _ = run(generate_profiles_yml=True, profiles={})
        assert any(i.code == "render.invalid_profiles" for i in report.issues)
        assert report.files_generated == 0


def test_runtime_config_stays_hashable_with_profiles(django_setup):
    from engine.services.runtime_config import EngineRuntimeConfig

    config = EngineRuntimeConfig(project_name="p", profiles=PROFILES)
    assert hash(config) == hash(EngineRuntimeConfig(project_name="p"))
