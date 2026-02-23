"""
Unit tests for configuration schema and output path handling.
"""

from pathlib import Path


class TestOutputConfiguration:
    """Tests for OutputConfiguration schema fields."""

    def test_all_output_dirs_default_to_none(self):
        """All three custom output dir fields default to None (convention is used instead)."""
        from engine.services.config_schema import TurboVaultConfig

        config = TurboVaultConfig.model_validate({"project": {"name": "my_project"}})

        assert config.output.dbt_project_dir is None
        assert config.output.json_output_dir is None
        assert config.output.dbml_output_dir is None

    def test_output_block_optional(self):
        """Config without an output: block is valid and uses defaults."""
        from engine.services.config_schema import TurboVaultConfig

        config = TurboVaultConfig.model_validate(
            {
                "project": {"name": "my_project"},
                "configuration": {"stage_schema": "stage", "rdv_schema": "rdv"},
            }
        )

        assert config.output is not None
        assert config.output.create_zip is False
        assert config.output.export_sources is True

    def test_dbt_project_dir_accepts_absolute_path(self, tmp_path: Path):
        """dbt_project_dir stores the given absolute path."""
        from engine.services.config_schema import TurboVaultConfig

        output_dir = tmp_path / "dbt_output"

        config = TurboVaultConfig.model_validate(
            {
                "project": {"name": "test_project"},
                "output": {"dbt_project_dir": str(output_dir)},
            }
        )

        assert config.output.dbt_project_dir == Path(str(output_dir))

    def test_json_output_dir_stored(self, tmp_path: Path):
        """json_output_dir is stored as a Path when provided."""
        from engine.services.config_schema import TurboVaultConfig

        config = TurboVaultConfig.model_validate(
            {
                "project": {"name": "test_project"},
                "output": {"json_output_dir": str(tmp_path / "json")},
            }
        )

        assert config.output.json_output_dir == tmp_path / "json"

    def test_dbml_output_dir_stored(self, tmp_path: Path):
        """dbml_output_dir is stored as a Path when provided."""
        from engine.services.config_schema import TurboVaultConfig

        config = TurboVaultConfig.model_validate(
            {
                "project": {"name": "test_project"},
                "output": {"dbml_output_dir": str(tmp_path / "dbml")},
            }
        )

        assert config.output.dbml_output_dir == tmp_path / "dbml"

    def test_all_three_output_dirs_together(self, tmp_path: Path):
        """All three output dirs can be set simultaneously."""
        from engine.services.config_schema import TurboVaultConfig

        config = TurboVaultConfig.model_validate(
            {
                "project": {"name": "test_project"},
                "output": {
                    "dbt_project_dir": str(tmp_path / "dbt"),
                    "json_output_dir": str(tmp_path / "json"),
                    "dbml_output_dir": str(tmp_path / "dbml"),
                },
            }
        )

        assert config.output.dbt_project_dir == tmp_path / "dbt"
        assert config.output.json_output_dir == tmp_path / "json"
        assert config.output.dbml_output_dir == tmp_path / "dbml"

    def test_create_zip_default_false(self):
        """create_zip defaults to False."""
        from engine.services.config_schema import TurboVaultConfig

        config = TurboVaultConfig.model_validate({"project": {"name": "p"}})
        assert config.output.create_zip is False

    def test_export_sources_default_true(self):
        """export_sources defaults to True."""
        from engine.services.config_schema import TurboVaultConfig

        config = TurboVaultConfig.model_validate({"project": {"name": "p"}})
        assert config.output.export_sources is True


class TestFindTurboVaultConfig:
    """Tests for workspace config discovery."""

    def test_finds_config_in_cwd(self, tmp_path: Path, monkeypatch):
        """find_turbovault_config finds turbovault.yml in cwd."""
        config_file = tmp_path / "turbovault.yml"
        config_file.write_text("database:\n  engine: sqlite3\n  name: db.sqlite3\n")

        monkeypatch.chdir(tmp_path)

        from engine.services.app_config_loader import find_turbovault_config

        result = find_turbovault_config()
        assert result == config_file

    def test_returns_none_when_missing(self, tmp_path: Path, monkeypatch):
        """find_turbovault_config returns None when turbovault.yml is absent."""
        monkeypatch.chdir(tmp_path)

        from engine.services.app_config_loader import find_turbovault_config

        result = find_turbovault_config()
        assert result is None

    def test_env_var_takes_priority_over_cwd(self, tmp_path: Path, monkeypatch):
        """TURBOVAULT_CONFIG_PATH env var is checked before cwd."""
        # Create config at an arbitrary location (not cwd)
        workspace = tmp_path / "my_workspace"
        workspace.mkdir()
        config_file = workspace / "turbovault.yml"
        config_file.write_text("database:\n  engine: sqlite3\n  name: db.sqlite3\n")

        # cwd has no turbovault.yml
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        monkeypatch.chdir(other_dir)

        monkeypatch.setenv("TURBOVAULT_CONFIG_PATH", str(config_file))

        # Reload to pick up cleared module-level LRU caches (if any)
        import importlib

        from engine.services import app_config_loader

        importlib.reload(app_config_loader)

        result = app_config_loader.find_turbovault_config()
        assert result == config_file

    def test_env_var_missing_file_falls_back_to_cwd(self, tmp_path: Path, monkeypatch):
        """If TURBOVAULT_CONFIG_PATH points to a non-existent file, cwd is used."""
        config_file = tmp_path / "turbovault.yml"
        config_file.write_text("database:\n  engine: sqlite3\n  name: db.sqlite3\n")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("TURBOVAULT_CONFIG_PATH", str(tmp_path / "nonexistent.yml"))

        from engine.services.app_config_loader import find_turbovault_config

        result = find_turbovault_config()
        assert result == config_file
