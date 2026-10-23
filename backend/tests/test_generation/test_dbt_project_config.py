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


class TestRejectedInputWritesNothing:
    """A rejected project-level input must leave earlier output untouched,
    also in best_effort mode and with create_zip (no zip of stale files)."""

    @pytest.mark.parametrize(
        "overrides, code",
        [
            (
                {
                    "profile_name": "p",
                    "generate_profiles_yml": True,
                    "profiles": {
                        "p": {
                            "target": "dev",
                            "outputs": {
                                "dev": {"type": "postgres", "password": "hunter2"}
                            },
                        }
                    },
                },
                "render.literal_secret_in_profile",
            ),
            (
                {"generate_profiles_yml": True, "profiles": {}},
                "render.invalid_profiles",
            ),
            (
                {"global_vars": {"datavault4dbt.hash": object()}},
                "render.invalid_global_vars",
            ),
        ],
    )
    def test_best_effort_with_zip(
        self,
        overrides,
        code,
        django_setup,
        project_export,
        engine_project,
        tmp_path,
        monkeypatch,
    ):
        from engine.services.generation import GenerationOptions, generate
        from engine.services.runtime_config import EngineRuntimeConfig

        _patch_build_stage(monkeypatch, project_export)
        out = tmp_path / "dbt_out"

        # An earlier, successful run left a project on disk.
        generate(
            project=engine_project,
            output_type="dbt",
            output_path=out,
            runtime_config=EngineRuntimeConfig(project_name="pipeline_e2e"),
        )
        assert (out / "dbt_project.yml").exists()

        report = generate(
            project=engine_project,
            output_type="dbt",
            output_path=out,
            runtime_config=EngineRuntimeConfig(
                project_name="pipeline_e2e", **overrides
            ),
            options=GenerationOptions(error_strategy="best_effort", create_zip=True),
        )

        assert [i.code for i in report.issues if i.severity == "error"] == [code]
        assert report.status == "validation_failed"
        assert report.artifacts == []
        assert "write" not in report.timings_ms
        assert not out.with_suffix(".zip").exists()


class TestYamlQuoting:
    def test_profile_name_with_quote_round_trips(self, run):
        report, out = run(profile_name="team's_profile")
        assert report.status in ("success", "partial_success")
        parsed = yaml.safe_load((out / "dbt_project.yml").read_text(encoding="utf-8"))
        assert parsed["profile"] == "team's_profile"

    @pytest.mark.parametrize("name", ["off", "yes", "null", "123", "a: b", "x #y"])
    def test_schema_names_stay_strings(self, run, name):
        report, out = run(control_schema=name, stage_schema=name)
        assert report.status in ("success", "partial_success")
        parsed = yaml.safe_load((out / "dbt_project.yml").read_text(encoding="utf-8"))
        layers = parsed["models"]["pipeline_e2e"]
        assert layers["00_control"]["+schema"] == name
        assert layers["02_staging"]["+schema"] == name

    def test_plain_custom_names_stay_unquoted(self, run):
        """Names YAML already reads correctly keep their previous form."""
        _, out = run(profile_name="tpch_dv", control_schema="meta", stage_schema="stg")
        content = (out / "dbt_project.yml").read_text(encoding="utf-8")
        assert "profile: 'tpch_dv'" in content
        assert "+schema: meta\n" in content
        assert "+schema: stg\n" in content


def _model_sql_by_type(report) -> dict[str, list[str]]:
    """SQL content of every generated model, grouped by kind.

    The kind is the entity type's first part, so `hub_standard` counts as
    `hub` and `satellite_standard` / `satellite_effectivity` count as
    `satellite`. `satellite_v1` is kept apart: it has its own materialization.
    """
    from pathlib import Path

    models: dict[str, list[str]] = {}
    for artifact in report.artifacts:
        if artifact.kind == "sql_model" and artifact.path:
            content = Path(artifact.path).read_text(encoding="utf-8")
            entity_type = artifact.entity_type
            kind = (
                entity_type
                if entity_type == "satellite_v1"
                else entity_type.split("_")[0]
            )
            models.setdefault(kind, []).append(content)
    return models


class TestModelMaterialization:
    """Models inherit their layer's materialization from dbt_project.yml.
    Models that differ from their layer by nature keep their own in config()
    while `model_specific_materializations` is on (the default)."""

    def test_layer_models_carry_no_materialization(self, run):
        report, _ = run()
        models = _model_sql_by_type(report)
        for kind in ("stage", "hub", "link", "satellite"):
            assert models[kind], kind
            for content in models[kind]:
                assert "materialized=" not in content, kind

    def test_v1_satellites_stay_views_by_default(self, run):
        """Derived views must not inherit the raw vault's incremental."""
        report, _ = run()
        v1_models = _model_sql_by_type(report)["satellite_v1"]
        assert v1_models
        for content in v1_models:
            assert "materialized='view'," in content

    def test_layer_setting_takes_effect_without_model_config(self, run):
        """The point of the setting: nothing in the model overrides the layer."""
        report, out = run(staging_materialization="ephemeral")
        parsed = yaml.safe_load((out / "dbt_project.yml").read_text(encoding="utf-8"))
        assert parsed["models"]["pipeline_e2e"]["02_staging"]["+materialized"] == (
            "ephemeral"
        )
        for content in _model_sql_by_type(report)["stage"]:
            assert "materialized=" not in content

    def test_specific_models_keep_their_own_under_custom_layers(self, run):
        report, _ = run(raw_vault_materialization="table")
        models = _model_sql_by_type(report)
        for kind in ("hub", "link", "satellite"):
            for content in models[kind]:
                assert "materialized=" not in content, kind
        for content in models["satellite_v1"]:
            assert "materialized='view'," in content

    def test_switched_off_every_model_follows_its_layer(self, run):
        report, _ = run(model_specific_materializations=False)
        models = _model_sql_by_type(report)
        assert models["satellite_v1"]
        for kind, contents in models.items():
            for content in contents:
                assert "materialized=" not in content, kind

    def test_custom_materialization_name_accepted(self, run):
        report, out = run(business_vault_materialization="my_custom_mat")
        assert report.status in ("success", "partial_success")
        parsed = yaml.safe_load((out / "dbt_project.yml").read_text(encoding="utf-8"))
        assert (
            parsed["models"]["pipeline_e2e"]["04_business_vault"]["+materialized"]
            == "my_custom_mat"
        )

    @pytest.mark.parametrize("value", ["view'", "table, schema='x'", "", "1table"])
    def test_invalid_materialization_writes_nothing(self, run, value):
        report, out = run(staging_materialization=value)
        errors = [i for i in report.issues if i.severity == "error"]
        assert [i.code for i in errors] == ["render.invalid_materialization"]
        assert "staging_materialization" in errors[0].message
        assert report.status == "validation_failed"
        assert not (out / "dbt_project.yml").exists()


class TestSpecificMaterializations:
    """The model kinds that keep their own materialization, and their values.
    The fixture project has no PITs, reference tables or snapshot controls, so
    their mapping is checked on the generator directly."""

    EXPECTED = {
        "satellite_v1": "view",
        "reference_table": "view",
        "pit": "incremental",
        "snapshot_control_v0": "incremental",
        "snapshot_control_v1": "view",
    }

    def _generator(self, tmp_path, **config):
        from engine.services.generation.folder_config import GenerationConfig
        from engine.services.generation.generator import DbtProjectGenerator

        return DbtProjectGenerator(
            output_path=tmp_path, config=GenerationConfig(**config)
        )

    def test_values_on_by_default(self, django_setup, tmp_path):
        generator = self._generator(tmp_path)
        for kind, value in self.EXPECTED.items():
            assert generator._specific_materialization(kind) == value, kind

    def test_none_when_switched_off(self, django_setup, tmp_path):
        generator = self._generator(tmp_path, model_specific_materializations=False)
        for kind in self.EXPECTED:
            assert generator._specific_materialization(kind) is None, kind

    def test_templates_write_the_value_only_when_given(self, django_setup):
        """Each specific model's template carries the conditional line."""
        from engine.services.generation.template_resolver import TEMPLATES_DIR

        for kind in self.EXPECTED:
            source = (TEMPLATES_DIR / "sql" / f"{kind}.sql.j2").read_text(
                encoding="utf-8"
            )
            assert "[% if materialization %]" in source, kind
            assert "materialized='[[ materialization ]]'," in source, kind


class TestCustomModelMaterializations:
    def test_override_reaches_the_model(self, run):
        report, _ = run(model_materializations={"satellite_v1": "table"})
        for content in _model_sql_by_type(report)["satellite_v1"]:
            assert "materialized='table'," in content

    def test_override_ignored_when_switched_off(self, run):
        report, _ = run(
            model_specific_materializations=False,
            model_materializations={"satellite_v1": "table"},
        )
        for content in _model_sql_by_type(report)["satellite_v1"]:
            assert "materialized=" not in content

    def test_kinds_left_out_keep_their_default(self, django_setup, tmp_path):
        from engine.services.generation.folder_config import GenerationConfig
        from engine.services.generation.generator import DbtProjectGenerator

        generator = DbtProjectGenerator(
            output_path=tmp_path,
            config=GenerationConfig(model_materializations={"pit": "view"}),
        )
        assert generator._specific_materialization("pit") == "view"
        assert generator._specific_materialization("satellite_v1") == "view"

    @pytest.mark.parametrize(
        "overrides, field",
        [
            ({"hub": "table"}, "model_materializations.hub"),
            ({"satellite_v1": "view'"}, "model_materializations.satellite_v1"),
        ],
    )
    def test_invalid_override_writes_nothing(self, run, overrides, field):
        report, out = run(model_materializations=overrides)
        errors = [i for i in report.issues if i.severity == "error"]
        assert [i.code for i in errors] == ["render.invalid_materialization"]
        assert field in errors[0].message
        assert not (out / "dbt_project.yml").exists()


class TestNoRedundantModelMaterialization:
    """A model's own materialization is only written when it differs from its
    layer's; otherwise the config() block carries none."""

    def test_v1_equal_to_raw_vault_layer_is_left_out(self, run):
        report, _ = run(raw_vault_materialization="view")
        for content in _model_sql_by_type(report)["satellite_v1"]:
            assert "materialized=" not in content

    def test_override_equal_to_layer_is_left_out(self, run):
        report, _ = run(model_materializations={"satellite_v1": "incremental"})
        for content in _model_sql_by_type(report)["satellite_v1"]:
            assert "materialized=" not in content

    @pytest.mark.parametrize(
        "kind, layer_field",
        [
            ("reference_table", "raw_vault_materialization"),
            ("pit", "business_vault_materialization"),
            ("snapshot_control_v0", "control_materialization"),
            ("snapshot_control_v1", "control_materialization"),
        ],
    )
    def test_every_specific_model_compares_with_its_layer(
        self, django_setup, tmp_path, kind, layer_field
    ):
        from engine.services.config_schema import MODEL_MATERIALIZATION_DEFAULTS
        from engine.services.generation.folder_config import GenerationConfig
        from engine.services.generation.generator import DbtProjectGenerator

        default = MODEL_MATERIALIZATION_DEFAULTS[kind]
        same = DbtProjectGenerator(
            output_path=tmp_path, config=GenerationConfig(**{layer_field: default})
        )
        assert same._specific_materialization(kind) is None
        other = "table" if default != "table" else "view"
        different = DbtProjectGenerator(
            output_path=tmp_path, config=GenerationConfig(**{layer_field: other})
        )
        assert different._specific_materialization(kind) == default
