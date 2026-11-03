"""Tests for the generate command's output path resolution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def _project(config_output: dict[str, Any] | None, project_directory: str = "projects/demo"):
    """Fake Project whose load_config returns a config with the given output block."""
    from engine.services.config_schema import TurboVaultConfig

    def load_config() -> TurboVaultConfig:
        if config_output is None:
            raise FileNotFoundError("config.yml")
        return TurboVaultConfig.model_validate(
            {"project": {"name": "demo"}, "output": config_output}
        )

    return SimpleNamespace(
        name="Demo", project_directory=project_directory, load_config=load_config
    )


@pytest.fixture
def workspace_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "engine.services.app_config_loader.get_project_root", lambda: tmp_path
    )
    return tmp_path


def _resolve(project, output_type: str = "sqlmesh", **flags: Path | None) -> Path | None:
    from engine.cli.commands.generate_cmd import _resolve_output_path

    return _resolve_output_path(
        output_type=output_type,
        output=flags.get("output"),
        json_output=None,
        dbml_output=None,
        sqlmesh_output=flags.get("sqlmesh_output"),
        project=project,
        dry_run=False,
    )


def test_relative_sqlmesh_output_dir_resolves_from_project_folder(workspace_root):
    project = _project({"sqlmesh_output_dir": "./custom/sqlmesh"})
    assert _resolve(project) == (workspace_root / "projects/demo/custom/sqlmesh").resolve()


def test_absolute_sqlmesh_output_dir_is_used_as_is(workspace_root, tmp_path):
    target = tmp_path / "shared" / "sqlmesh"
    project = _project({"sqlmesh_output_dir": str(target)})
    assert _resolve(project) == target


def test_unset_sqlmesh_output_dir_uses_convention(workspace_root):
    assert _resolve(_project({})) == workspace_root / "projects/demo/exports/sqlmesh"


def test_missing_config_yml_uses_convention(workspace_root):
    assert _resolve(_project(None)) == workspace_root / "projects/demo/exports/sqlmesh"


@pytest.mark.parametrize("flag", ["sqlmesh_output", "output"])
def test_cli_flags_win_over_config(workspace_root, tmp_path, flag):
    project = _project({"sqlmesh_output_dir": "./custom/sqlmesh"})
    cli_path = tmp_path / "from_cli"
    assert _resolve(project, **{flag: cli_path}) == cli_path


def test_sqlmesh_output_dir_does_not_affect_dbt(workspace_root):
    project = _project({"sqlmesh_output_dir": "./custom/sqlmesh"})
    assert _resolve(project, output_type="dbt") == workspace_root / "projects/demo/exports/dbt_project"
