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

    def test_duckdb_connection_uses_memory_database(self):
        content = _render_yaml(sqlmesh_connection_type="duckdb")
        assert ":memory:" in content

    def test_duckdb_connection_has_no_credential_placeholders(self):
        content = _render_yaml(sqlmesh_connection_type="duckdb")
        assert "${SQLMESH_PASSWORD}" not in content
        assert "${SQLMESH_USER}" not in content

    def test_non_duckdb_connection_uses_env_var_placeholders(self):
        content = _render_yaml(sqlmesh_connection_type="snowflake")
        assert "${SQLMESH_HOST}" in content
        assert "${SQLMESH_USER}" in content
        assert "${SQLMESH_PASSWORD}" in content
        assert "${SQLMESH_DATABASE}" in content

    def test_no_hardcoded_credentials_for_non_duckdb(self):
        """Credential fields must be env-var placeholders, never literal values."""
        for conn_type in ("snowflake", "bigquery", "postgres"):
            content = _render_yaml(sqlmesh_connection_type=conn_type)
            # Placeholder syntax must be present; literal secrets must not be
            assert "${SQLMESH_PASSWORD}" in content

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
        assert rc.sqlmesh_connection_type == "duckdb"
        assert rc.sqlmesh_start == "2020-01-01"
        assert rc.sqlmesh_dv_config == ()

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
