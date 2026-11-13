"""An imported dbt project's dbt_project.yml settings in the generated one.

The project keeps the imported project's models: block (folder-level
materializations, schemas, tags, hooks), its variables and its other
top-level settings. Generation writes them back: TurboVault's layer folders
keep their settings, its model paths are added, and everything else comes
out as it went in. Without imported settings the file is TurboVault's own.
"""

from __future__ import annotations

import pytest
import yaml


@pytest.fixture
def generate(django_setup, project_export, tmp_path):
    def run(**settings):
        from engine.services.generation import DbtProjectGenerator, TemplateResolver
        from engine.services.generation.folder_config import GenerationConfig

        report = DbtProjectGenerator(
            output_path=tmp_path / "dbt",
            template_resolver=settings.pop("resolver", None)
            or TemplateResolver(use_db_templates=False),
            config=GenerationConfig(project_name="analytics", **settings),
        ).generate(project_export)
        content = (tmp_path / "dbt" / "dbt_project.yml").read_text(encoding="utf-8")
        return report, content, yaml.safe_load(content)

    return run


IMPORTED_MODELS = {
    "+materialized": "view",
    "staging": {"+schema": "stage", "+tags": ["staging"]},
    "raw_vault": {
        "+schema": "rdv",
        "+materialized": "incremental",
        "+on_schema_change": "append_new_columns",
        "hubs": {"+tags": ["hub"]},
    },
    "30_raw_vault": {"+persist_docs": {"relation": True}},
}
IMPORTED_SETTINGS = {
    "version": "2.4.1",
    "model-paths": ["models", "marts"],
    "seed-paths": ["data"],
    "clean-targets": ["target", "dbt_packages", "logs"],
    "require-dbt-version": [">=1.8.0", "<2.0.0"],
    "on-run-start": ["{{ create_udfs() }}"],
    "seeds": {"analytics": {"+schema": "seeds"}},
    "models": {"elementary": {"+schema": "elementary"}},
}


def test_without_imported_settings_the_file_is_turbovaults(generate):
    _, _, data = generate()

    assert data["version"] == "1.0.0"
    assert data["clean-targets"] == ["target", "dbt_packages"]
    assert list(data["models"]) == ["analytics"]
    assert data["models"]["analytics"]["30_raw_vault"] == {
        "+schema": "rdv",
        "+materialized": "incremental",
    }
    assert "seeds" not in data


def test_the_imported_settings_come_back(generate):
    report, _, data = generate(
        dbt_project_models=IMPORTED_MODELS,
        dbt_project_settings=IMPORTED_SETTINGS,
        global_vars={"datavault4dbt.hash": "SHA2"},
    )

    assert data["version"] == "2.4.1"
    assert data["seed-paths"] == ["data"]
    assert data["clean-targets"] == ["target", "dbt_packages", "logs"]
    assert data["model-paths"] == ["models", "marts"]
    assert data["require-dbt-version"] == [">=1.8.0", "<2.0.0"]
    assert data["on-run-start"] == ["{{ create_udfs() }}"]
    assert data["seeds"] == {"analytics": {"+schema": "seeds"}}
    assert data["vars"] == {"datavault4dbt.hash": "SHA2"}
    project = data["models"]["analytics"]
    # The imported folders as they were
    assert project["+materialized"] == "view"
    assert project["raw_vault"] == IMPORTED_MODELS["raw_vault"]
    assert project["staging"] == IMPORTED_MODELS["staging"]
    # TurboVault's layers keep their settings, merged into an imported entry
    assert project["30_raw_vault"] == {
        "+persist_docs": {"relation": True},
        "+schema": "rdv",
        "+materialized": "incremental",
    }
    assert project["00_control"]["+schema"] == "control"
    # Other packages' entries stay
    assert data["models"]["elementary"] == {"+schema": "elementary"}
    assert not [w for w in report.warnings if w.code == "TPL_003"]


def test_an_outdated_template_drops_the_imported_settings_with_a_warning(
    generate, tmp_path
):
    import shutil

    from engine.services.generation import TemplateResolver
    from engine.services.generation.template_resolver import TEMPLATES_DIR

    templates = tmp_path / "templates"
    shutil.copytree(TEMPLATES_DIR, templates)
    (templates / "dbt" / "yaml" / "dbt_project.yml.j2").write_text(
        "name: '[[ project_name ]]'\nmodels:\n  [[ project_name ]]: {}\n",
        encoding="utf-8",
    )
    resolver = TemplateResolver(templates_dir=templates, use_db_templates=False)

    report, _, _ = generate(
        dbt_project_models=IMPORTED_MODELS,
        dbt_project_settings=IMPORTED_SETTINGS,
        resolver=resolver,
    )

    (warning,) = [w for w in report.warnings if w.code == "TPL_003"]
    assert "raw_vault" in warning.message


def test_config_yml_keeps_the_settings(tmp_path):
    from engine.services.config_schema import TurboVaultConfig
    from engine.services.project_config import write_project_config
    from engine.services.runtime_config import EngineRuntimeConfig

    config = TurboVaultConfig(
        project={"name": "shop"},
        dbt_project={
            "vars": {"datavault4dbt.hash": "SHA2"},
            "models": IMPORTED_MODELS,
            "settings": IMPORTED_SETTINGS,
        },
    )
    path = tmp_path / "config.yml"
    write_project_config(path, config)

    written = yaml.safe_load(path.read_text(encoding="utf-8"))["dbt_project"]
    assert "path" not in written
    reloaded = TurboVaultConfig(**yaml.safe_load(path.read_text(encoding="utf-8")))
    runtime = EngineRuntimeConfig.from_turbovault_config(reloaded)
    assert runtime.global_vars == {"datavault4dbt.hash": "SHA2"}
    assert runtime.dbt_project_models == IMPORTED_MODELS
    assert runtime.dbt_project_settings == IMPORTED_SETTINGS
