"""
Unit tests for configuration schema and output path handling.
"""

from pathlib import Path

import pytest


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
                "configuration": {
                    "stage_schema": "stage",
                    "rdv_schema": "rdv",
                    "bdv_schema": "bdv",
                },
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


class TestDbtProjectSettings:
    """dbt project settings in config.yml feed EngineRuntimeConfig."""

    def test_defaults_match_generated_project(self):
        from engine.services.config_schema import TurboVaultConfig
        from engine.services.runtime_config import EngineRuntimeConfig

        config = TurboVaultConfig(project={"name": "p"})
        runtime = EngineRuntimeConfig.from_turbovault_config(config)

        assert runtime.profile_name == "default"
        assert runtime.control_schema == "control"
        assert runtime.control_materialization == "table"
        assert runtime.staging_materialization == "view"
        assert runtime.raw_vault_materialization == "incremental"
        assert runtime.business_vault_materialization == "table"

    def test_values_flow_into_runtime_config(self):
        from engine.services.config_schema import TurboVaultConfig
        from engine.services.runtime_config import EngineRuntimeConfig

        config = TurboVaultConfig(
            project={"name": "p"},
            configuration={
                "profile_name": "tpch_dv",
                "control_schema": "meta",
                "staging_materialization": "ephemeral",
                "business_vault_materialization": "view",
            },
        )
        runtime = EngineRuntimeConfig.from_turbovault_config(config)

        assert runtime.profile_name == "tpch_dv"
        assert runtime.control_schema == "meta"
        assert runtime.staging_materialization == "ephemeral"
        assert runtime.business_vault_materialization == "view"

    def test_profiles_are_not_set_through_config_yml(self):
        """Like global_vars, profiles.yml is driven by embedded callers only:
        config.yml has no such setting, so the runtime config keeps it off."""
        from engine.services.config_schema import TurboVaultConfig
        from engine.services.runtime_config import EngineRuntimeConfig

        config = TurboVaultConfig(
            project={"name": "p"},
            output={
                "generate_profiles_yml": True,
                "profiles": {"p": {"target": "dev", "outputs": {"dev": {}}}},
            },
        )
        runtime = EngineRuntimeConfig.from_turbovault_config(config)

        assert runtime.generate_profiles_yml is False
        assert runtime.profiles == {}
        assert not hasattr(config.output, "profiles")

    def test_unknown_materialization_rejected(self):
        import pytest
        from engine.services.config_schema import TurboVaultConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TurboVaultConfig(
                project={"name": "p"},
                configuration={"raw_vault_materialization": "merge"},
            )

    def test_invalid_control_schema_rejected(self):
        import pytest
        from engine.services.config_schema import TurboVaultConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TurboVaultConfig(
                project={"name": "p"}, configuration={"control_schema": "a b"}
            )


class TestModelSpecificMaterializations:
    def test_defaults_to_true(self):
        from engine.services.config_schema import TurboVaultConfig
        from engine.services.runtime_config import EngineRuntimeConfig

        config = TurboVaultConfig(project={"name": "p"})
        assert config.configuration.model_specific_materializations is True
        runtime = EngineRuntimeConfig.from_turbovault_config(config)
        assert runtime.model_specific_materializations is True

    def test_switch_off_flows_into_runtime_config(self):
        from engine.services.config_schema import TurboVaultConfig
        from engine.services.runtime_config import EngineRuntimeConfig

        config = TurboVaultConfig(
            project={"name": "p"},
            configuration={"model_specific_materializations": False},
        )
        runtime = EngineRuntimeConfig.from_turbovault_config(config)
        assert runtime.model_specific_materializations is False


class TestModelMaterializations:
    def test_defaults_to_empty(self):
        from engine.services.config_schema import TurboVaultConfig

        config = TurboVaultConfig(project={"name": "p"})
        assert config.configuration.model_materializations == {}

    def test_flows_into_runtime_config(self):
        from engine.services.config_schema import TurboVaultConfig
        from engine.services.runtime_config import EngineRuntimeConfig

        config = TurboVaultConfig(
            project={"name": "p"},
            configuration={"model_materializations": {"satellite_v1": "table"}},
        )
        runtime = EngineRuntimeConfig.from_turbovault_config(config)
        assert runtime.model_materializations == {"satellite_v1": "table"}

    @pytest.mark.parametrize(
        "value",
        [{"hub": "table"}, {"satellite_v1": "merge"}],
    )
    def test_unknown_kind_or_materialization_rejected(self, value):
        from engine.services.config_schema import TurboVaultConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TurboVaultConfig(
                project={"name": "p"}, configuration={"model_materializations": value}
            )

    def test_written_to_config_yml_only_when_set(self, tmp_path):
        import yaml
        from engine.services.config_schema import TurboVaultConfig
        from engine.services.project_config import write_project_config

        plain = tmp_path / "plain.yml"
        write_project_config(plain, TurboVaultConfig(project={"name": "p"}))
        assert (
            "model_materializations"
            not in yaml.safe_load(plain.read_text(encoding="utf-8"))["configuration"]
        )

        custom = tmp_path / "custom.yml"
        write_project_config(
            custom,
            TurboVaultConfig(
                project={"name": "p"},
                configuration={"model_materializations": {"pit": "table"}},
            ),
        )
        assert yaml.safe_load(custom.read_text(encoding="utf-8"))["configuration"][
            "model_materializations"
        ] == {"pit": "table"}
