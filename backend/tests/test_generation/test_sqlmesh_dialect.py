"""Unit tests for the SQLMesh config.yaml dialect-mismatch check."""

from __future__ import annotations

from pathlib import Path


def _write_config_yaml(root: Path, body: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.yaml").write_text(body, encoding="utf-8")


class TestReadConfigYamlDialect:
    def test_missing_file_returns_none(self, tmp_path):
        from engine.services.generation.sqlmesh_dialect import read_config_yaml_dialect

        assert read_config_yaml_dialect(tmp_path / "config.yaml") is None

    def test_reads_model_defaults_dialect(self, tmp_path):
        from engine.services.generation.sqlmesh_dialect import read_config_yaml_dialect

        _write_config_yaml(tmp_path, "model_defaults:\n  dialect: trino\n")
        assert read_config_yaml_dialect(tmp_path / "config.yaml") == "trino"

    def test_invalid_yaml_returns_none(self, tmp_path):
        from engine.services.generation.sqlmesh_dialect import read_config_yaml_dialect

        _write_config_yaml(tmp_path, "model_defaults: [unclosed\n")
        assert read_config_yaml_dialect(tmp_path / "config.yaml") is None

    def test_no_model_defaults_returns_none(self, tmp_path):
        from engine.services.generation.sqlmesh_dialect import read_config_yaml_dialect

        _write_config_yaml(tmp_path, "gateways: {}\n")
        assert read_config_yaml_dialect(tmp_path / "config.yaml") is None


class TestCheckConfigYamlDialect:
    def test_no_existing_file_no_issue(self, tmp_path):
        from engine.services.generation.sqlmesh_dialect import check_config_yaml_dialect

        assert check_config_yaml_dialect(tmp_path, "snowflake") is None

    def test_matching_dialect_no_issue(self, tmp_path):
        from engine.services.generation.sqlmesh_dialect import check_config_yaml_dialect

        _write_config_yaml(tmp_path, "model_defaults:\n  dialect: snowflake\n")
        assert check_config_yaml_dialect(tmp_path, "snowflake") is None

    def test_mismatch_returns_warning(self, tmp_path):
        from engine.services.generation.sqlmesh_dialect import (
            CONFIG_YAML_DIALECT_MISMATCH,
            check_config_yaml_dialect,
        )

        _write_config_yaml(tmp_path, "model_defaults:\n  dialect: postgres\n")
        issue = check_config_yaml_dialect(tmp_path, "snowflake")
        assert issue is not None
        assert issue.severity == "warning"
        assert issue.code == CONFIG_YAML_DIALECT_MISMATCH
        assert "postgres" in issue.message
        assert "snowflake" in issue.message


class TestDialectNameAndRequirements:
    def test_valid_dialect_names(self):
        from engine.services.generation.sqlmesh_dialect import is_valid_dialect_name

        for name in ("postgres", "mssql", "redshift", "spark2"):
            assert is_valid_dialect_name(name), name
        for name in ("", "MSSQL", "ms sql", "sqlmesh[mssql]", "2db", "pg;drop"):
            assert not is_valid_dialect_name(name), name

    def test_default_requirement_per_dialect(self):
        from engine.services.generation.sqlmesh_dialect import default_driver_requirement

        assert default_driver_requirement("postgres") == "sqlmesh[postgres]"
        assert default_driver_requirement("duckdb") is None
        assert default_driver_requirement("mssql") is None

    def test_resolve_requirement_none_derives_and_empty_means_no_line(self):
        from engine.services.generation.sqlmesh_dialect import resolve_driver_requirement

        assert resolve_driver_requirement("postgres", None) == "sqlmesh[postgres]"
        assert resolve_driver_requirement("postgres", "") is None
        assert resolve_driver_requirement("mssql", " sqlmesh[mssql] ") == "sqlmesh[mssql]"


class TestChooseRequirement:
    def _choose(self, **kwargs):
        from engine.services.generation.sqlmesh_dialect import choose_requirement

        defaults = {
            "dialect": "mssql",
            "configured_dialect": "mssql",
            "configured_requirement": "sqlmesh[mssql]",
            "explicit_requirement": None,
        }
        return choose_requirement(**{**defaults, **kwargs})

    def test_explicit_requirement_wins(self):
        assert self._choose(explicit_requirement="pyodbc") == "pyodbc"

    def test_configured_requirement_kept_for_configured_dialect(self):
        assert self._choose() == "sqlmesh[mssql]"

    def test_configured_requirement_dropped_when_dialect_changes(self):
        assert self._choose(dialect="postgres") is None


class TestNoDialectHelpers:
    def test_none_is_reserved_not_a_dialect_name(self):
        from engine.services.generation.sqlmesh_dialect import NO_DIALECT, is_valid_dialect_name

        assert NO_DIALECT == "none"
        assert not is_valid_dialect_name("none")

    def test_mismatch_check_skipped_without_dialect(self, tmp_path):
        from engine.services.generation.sqlmesh_dialect import check_config_yaml_dialect

        _write_config_yaml(tmp_path, "model_defaults:\n  dialect: postgres\n")
        assert check_config_yaml_dialect(tmp_path, None) is None

    def test_no_default_requirement_without_dialect(self):
        from engine.services.generation.sqlmesh_dialect import default_driver_requirement

        assert default_driver_requirement(None) is None
