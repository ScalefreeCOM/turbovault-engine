"""Unit tests for SQLMesh project config rendering (ticket 424).

Covers _render_config_yaml, _render_config_json, and the EngineRuntimeConfig
SQLMesh fields. All functions under test are pure — no Django or DB needed.
"""

from __future__ import annotations

import json

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runtime_config(**kwargs):
    from engine.services.runtime_config import EngineRuntimeConfig

    return EngineRuntimeConfig(**kwargs)


def _render_yaml(**kwargs):
    from engine.services.generation.renderers.sqlmesh_renderer import _render_config_yaml

    return _render_config_yaml(_runtime_config(**kwargs))


def _render_json(**kwargs):
    from engine.services.generation.renderers.sqlmesh_renderer import _render_config_json

    return _render_config_json(_runtime_config(**kwargs))


# ---------------------------------------------------------------------------
# config.yaml
# ---------------------------------------------------------------------------


class TestRenderConfigYaml:
    def test_defaults_produce_parseable_yaml(self):
        parsed = yaml.safe_load(_render_yaml())
        assert parsed is not None

    def test_default_gateway_name_in_output(self):
        content = _render_yaml()
        assert "local:" in content
        assert "default_gateway: local" in content

    def test_custom_gateway_propagated(self):
        content = _render_yaml(sqlmesh_gateway="prod")
        assert "prod:" in content
        assert "default_gateway: prod" in content

    def test_connection_block_contains_only_the_type(self):
        """The hull carries no connection values: the user fills them in.

        Guarantees no credentials, hosts or placeholders are ever generated.
        """
        for dialect in ("duckdb", "postgres", "snowflake", "databricks", "trino", "bigquery"):
            parsed = yaml.safe_load(_render_yaml(sqlmesh_dialect=dialect))
            assert parsed["gateways"]["local"]["connection"] == {"type": dialect}, dialect

    def test_fill_in_note_lists_connection_parameters_per_type(self):
        content = _render_yaml()
        assert "# Fill in the connection details" in content
        assert "# add connection parameters here" in content
        for line in (
            "#   postgres:    type, host, port, user, password, database",
            "#   snowflake:   type, account, user, password, database, warehouse, role",
            "#   databricks:  type, server_hostname, http_path, access_token, catalog",
            "#   trino:       type, host, port, user, catalog",
            "#   bigquery:    type, project, dataset",
            "#   duckdb:      type: duckdb / database: ':memory:'",
        ):
            assert line in content

    def test_dialect_appears_in_model_defaults(self):
        parsed = yaml.safe_load(_render_yaml(sqlmesh_dialect="snowflake"))
        assert parsed["model_defaults"]["dialect"] == "snowflake"

    def test_start_date_is_a_string_not_a_date_object(self):
        """If unquoted, YAML parses 2020-01-01 as datetime.date — it must be quoted."""
        parsed = yaml.safe_load(_render_yaml(sqlmesh_start="2020-01-01"))
        assert isinstance(parsed["model_defaults"]["start"], str)
        assert parsed["model_defaults"]["start"] == "2020-01-01"

    def test_output_is_deterministic(self):
        rc = _runtime_config()
        from engine.services.generation.renderers.sqlmesh_renderer import _render_config_yaml

        assert _render_config_yaml(rc) == _render_config_yaml(rc)


class TestConfigYamlWriteOnce:
    """config.yaml is written once; a user's filled-in file survives regeneration."""

    @staticmethod
    def _write(output_path, content: str):
        from engine.services.generation.stages.write import write_artifacts
        from engine.services.generation.types import GeneratedArtifact, GenerationOptions

        artifact = GeneratedArtifact(
            kind="sqlmesh_config", path="config.yaml", content=content, overwrite=False
        )
        return write_artifacts(
            artifacts=[artifact],
            output_type="sqlmesh",
            output_path=output_path,
            options=GenerationOptions(),
        )

    def test_new_project_gets_hull_and_fill_in_warning(self, tmp_path):
        hull = _render_yaml(sqlmesh_dialect="postgres")
        _, issues = self._write(tmp_path, hull)
        assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == hull
        assert [i.code for i in issues] == ["write.sqlmesh.config_yaml_created"]

    def test_existing_user_config_is_not_overwritten(self, tmp_path):
        user_config = (
            "gateways:\n  local:\n    connection:\n      type: postgres\n"
            "      host: db.example.com\n"
        )
        (tmp_path / "config.yaml").write_text(user_config, encoding="utf-8")
        _, issues = self._write(tmp_path, _render_yaml(sqlmesh_dialect="postgres"))
        assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == user_config
        assert issues == []


# ---------------------------------------------------------------------------
# config.json
# ---------------------------------------------------------------------------


class TestRenderConfigJson:
    def test_output_is_valid_json(self):
        parsed = json.loads(_render_json())
        assert isinstance(parsed, dict)

    def test_default_config_contains_dialect_key(self):
        parsed = json.loads(_render_json())
        assert "dialect" in parsed
        assert parsed["dialect"] == "duckdb"

    def test_custom_dialect_reflected_in_json(self):
        parsed = json.loads(_render_json(sqlmesh_dialect="snowflake"))
        assert parsed["dialect"] == "snowflake"

    def test_supplied_dv_config_keys_merged_verbatim(self):
        dv_config = (
            ("hash", "SHA1"),
            ("use_trim", True),
            ("ldts_alias", "load_datetime"),
        )
        parsed = json.loads(_render_json(sqlmesh_dv_config=dv_config))
        assert parsed["hash"] == "SHA1"
        assert parsed["use_trim"] is True
        assert parsed["ldts_alias"] == "load_datetime"

    def test_empty_dv_config_produces_only_dialect_key(self):
        parsed = json.loads(_render_json())
        assert list(parsed.keys()) == ["dialect"]

    def test_output_ends_with_newline(self):
        assert _render_json().endswith("\n")

    def test_quote_identifiers_left_to_datavault4sqlmesh_default(self):
        # datavault4sqlmesh normalizes identifier case itself, so no dialect
        # needs quoting turned off.
        for dialect in ("duckdb", "postgres", "snowflake", "databricks", "trino", "bigquery"):
            parsed = json.loads(_render_json(sqlmesh_dialect=dialect))
            assert "quote_identifiers" not in parsed, dialect

    def test_explicit_quote_identifiers_is_passed_through(self):
        parsed = json.loads(
            _render_json(
                sqlmesh_dialect="postgres",
                sqlmesh_dv_config=(("quote_identifiers", False),),
            )
        )
        assert parsed["quote_identifiers"] is False

    def test_dialect_consistent_between_config_yaml_and_config_json(self):
        from engine.services.generation.renderers.sqlmesh_renderer import (
            _render_config_json,
            _render_config_yaml,
        )

        rc = _runtime_config(sqlmesh_dialect="bigquery")
        yaml_dialect = yaml.safe_load(_render_config_yaml(rc))["model_defaults"]["dialect"]
        json_dialect = json.loads(_render_config_json(rc))["dialect"]
        assert yaml_dialect == json_dialect == "bigquery"

    def test_output_is_deterministic(self):
        rc = _runtime_config(sqlmesh_dv_config=(("hash", "MD5"), ("use_trim", False)))
        from engine.services.generation.renderers.sqlmesh_renderer import _render_config_json

        assert _render_config_json(rc) == _render_config_json(rc)


# ---------------------------------------------------------------------------
# EngineRuntimeConfig SQLMesh fields
# ---------------------------------------------------------------------------


class TestEngineRuntimeConfigSqlmeshFields:
    def test_default_sqlmesh_field_values(self):
        from engine.services.runtime_config import EngineRuntimeConfig

        rc = EngineRuntimeConfig()
        assert rc.sqlmesh_dialect == "duckdb"
        assert rc.sqlmesh_gateway == "local"
        assert rc.sqlmesh_start == "2020-01-01"
        assert rc.sqlmesh_dv_config == ()

    def test_legacy_connection_type_key_is_ignored(self):
        """Old config.yml files may still set the removed connection_type key."""
        from engine.services.config_schema import SQLMeshConfig

        sm = SQLMeshConfig(dialect="postgres", connection_type="postgres")
        assert sm.dialect == "postgres"
        assert not hasattr(sm, "connection_type")

    def test_sqlmesh_dv_config_dict_property_converts_tuple(self):
        from engine.services.runtime_config import EngineRuntimeConfig

        rc = EngineRuntimeConfig(
            sqlmesh_dv_config=(("hash", "MD5"), ("use_trim", False))
        )
        assert rc.sqlmesh_dv_config_dict == {"hash": "MD5", "use_trim": False}

    def test_empty_dv_config_dict_is_empty(self):
        from engine.services.runtime_config import EngineRuntimeConfig

        assert EngineRuntimeConfig().sqlmesh_dv_config_dict == {}

    def test_config_stays_hashable_with_dv_config(self):
        from engine.services.runtime_config import EngineRuntimeConfig

        rc = EngineRuntimeConfig(sqlmesh_dv_config=(("hash", "MD5"),))
        # frozen dataclass must remain hashable even with tuple-of-pairs field
        assert isinstance(hash(rc), int)

    def test_dv_config_included_in_equality(self):
        from engine.services.runtime_config import EngineRuntimeConfig

        with_config = EngineRuntimeConfig(sqlmesh_dv_config=(("hash", "MD5"),))
        without_config = EngineRuntimeConfig()
        assert with_config != without_config

    def test_sqlmesh_fields_isolated_from_dbt_fields(self):
        """Changing SQLMesh settings must not alter dbt-specific attributes."""
        from engine.services.runtime_config import EngineRuntimeConfig

        rc = EngineRuntimeConfig(
            project_name="test",
            sqlmesh_dialect="snowflake",
            sqlmesh_gateway="prod",
        )
        # dbt_project_name is independent of sqlmesh_* fields
        assert rc.dbt_project_name is None
        assert rc.sqlmesh_dialect == "snowflake"
        assert rc.sqlmesh_gateway == "prod"
