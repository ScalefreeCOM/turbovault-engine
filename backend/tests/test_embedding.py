from __future__ import annotations

import engine as engine_module
import pytest
from engine.apps import EngineCoreConfig, EngineStandaloneConfig
from engine.models import Project
from engine.services.export.builder import ModelBuilder
from engine.services.runtime_config import EngineRuntimeConfig

pytestmark = pytest.mark.django_db


def test_engine_core_config_does_not_run_standalone_admin_setup(monkeypatch):
    called = False

    def fake_admin_setup():
        nonlocal called
        called = True

    monkeypatch.setattr(
        "engine.utils.admin_utils.create_admin_user_if_configured",
        fake_admin_setup,
    )

    EngineCoreConfig("engine", engine_module).ready()

    assert called is False
    assert issubclass(EngineStandaloneConfig, EngineCoreConfig)


def test_model_builder_accepts_runtime_config_without_project_directory():
    project = Project.objects.create(name="Embedded Vault")
    runtime_config = EngineRuntimeConfig(
        project_name="Embedded Vault",
        stage_schema="landing",
        rdv_schema="core",
        bdv_schema="business",
    )

    project_export = ModelBuilder(project, runtime_config=runtime_config).build()

    assert project_export.project_name == "Embedded Vault"
    assert project_export.stage_schema == "landing"
    assert project_export.rdv_schema == "core"
    assert project_export.bdv_schema == "business"
