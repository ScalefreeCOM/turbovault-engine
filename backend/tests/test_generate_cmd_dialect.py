"""Tests for the generate command's SQLMesh dialect resolution."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def no_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if questionary prompts (it raises OSError without a TTY)."""

    def _fail(*args, **kwargs):
        raise AssertionError("prompted for the dialect")

    monkeypatch.setattr("engine.cli.commands.generate_cmd.questionary.select", _fail)
    monkeypatch.setattr("engine.cli.commands.generate_cmd.questionary.text", _fail)


def _resolve(monkeypatch, *, isatty: bool, configured: dict, dialect=None, requirement=None):
    from engine.cli.commands.generate_cmd import _resolve_sqlmesh_runtime_config
    from engine.services.runtime_config import EngineRuntimeConfig

    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: isatty))
    monkeypatch.setattr(
        "engine.services.runtime_config.resolve_runtime_config",
        lambda project: EngineRuntimeConfig(**configured),
    )
    return _resolve_sqlmesh_runtime_config(object(), dialect, requirement)


def test_no_tty_uses_configured_dialect(monkeypatch, no_prompt):
    config = _resolve(
        monkeypatch,
        isatty=False,
        configured={"sqlmesh_dialect": "postgres", "sqlmesh_requirement": "sqlmesh[postgres]==0.1"},
    )
    assert config.sqlmesh_dialect == "postgres"
    assert config.sqlmesh_requirement == "sqlmesh[postgres]==0.1"


def test_no_tty_null_dialect_stays_none(monkeypatch, no_prompt):
    config = _resolve(monkeypatch, isatty=False, configured={"sqlmesh_dialect": None})
    assert config.sqlmesh_dialect is None


def test_no_tty_requirement_flag_still_applies(monkeypatch, no_prompt):
    config = _resolve(
        monkeypatch,
        isatty=False,
        configured={"sqlmesh_dialect": "postgres"},
        requirement="psycopg2-binary",
    )
    assert config.sqlmesh_dialect == "postgres"
    assert config.sqlmesh_requirement == "psycopg2-binary"


def test_dialect_flag_wins_without_tty(monkeypatch, no_prompt):
    config = _resolve(
        monkeypatch, isatty=False, configured={"sqlmesh_dialect": "postgres"}, dialect="snowflake"
    )
    assert config.sqlmesh_dialect == "snowflake"


def test_tty_still_prompts(monkeypatch):
    prompted = []

    def _select(*args, **kwargs):
        prompted.append(kwargs.get("default"))
        return SimpleNamespace(ask=lambda: "duckdb")

    monkeypatch.setattr("engine.cli.commands.generate_cmd.questionary.select", _select)
    config = _resolve(monkeypatch, isatty=True, configured={"sqlmesh_dialect": "postgres"})
    assert prompted == ["postgres"]
    assert config.sqlmesh_dialect == "duckdb"
