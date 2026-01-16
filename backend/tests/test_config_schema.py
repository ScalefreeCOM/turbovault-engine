"""
Unit tests for configuration schema normalization.
"""

from pathlib import Path


def test_output_dir_expands_user_home(monkeypatch, tmp_path):
    """dbt_project_dir should expand ~ to the user home directory."""
    from engine.services.config_schema import TurboVaultConfig

    monkeypatch.setenv("HOME", str(tmp_path))

    config = TurboVaultConfig.model_validate(
        {
            "project": {"name": "test_project"},
            "output": {"dbt_project_dir": "~/dbt"},
        }
    )

    assert config.output.dbt_project_dir == (tmp_path / "dbt").resolve()


def test_output_dir_is_absolute(tmp_path):
    """dbt_project_dir should resolve to an absolute path."""
    from engine.services.config_schema import TurboVaultConfig

    output_dir = tmp_path / "relative" / "dbt"

    config = TurboVaultConfig.model_validate(
        {
            "project": {"name": "test_project"},
            "output": {"dbt_project_dir": str(output_dir)},
        }
    )

    assert config.output.dbt_project_dir.is_absolute()
    assert config.output.dbt_project_dir == Path(str(output_dir)).resolve()
