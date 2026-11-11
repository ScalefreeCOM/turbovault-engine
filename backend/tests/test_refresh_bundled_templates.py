"""Migration 0020: unedited, superseded DB templates are refreshed (#442)."""

from __future__ import annotations

import hashlib
import importlib

import pytest

pytestmark = pytest.mark.django_db

OLD_PIT_SQL = "{{ datavault4dbt.pit(sat_names=['[[ sat ]]_v0']) }}\n"


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@pytest.fixture
def migration(django_setup, monkeypatch):
    module = importlib.import_module("engine.migrations.0020_refresh_bundled_templates")
    monkeypatch.setitem(
        module.SUPERSEDED_BUNDLED_HASHES,
        ("dbt", "pit", "sql"),
        frozenset({_hash(OLD_PIT_SQL)}),
    )
    return module


def _pit_template(name: str, sql: str):
    from engine.models.templates import ModelTemplate

    return ModelTemplate.objects.create(
        name=name,
        entity_type="pit",
        framework="dbt",
        sql_template_content=sql,
        yaml_template_content="custom yaml\n",
    )


def _bundled_pit_sql() -> str:
    from engine.services.generation.template_resolver import bundled_templates

    template = next(
        t
        for t in bundled_templates("dbt")
        if t.entity_type == "pit" and t.template_type == "sql"
    )
    return template.path.read_text(encoding="utf-8")


def _run(migration) -> None:
    from django.apps import apps

    migration.refresh_bundled_templates(apps, None)


def test_unedited_old_template_is_refreshed(migration):
    row = _pit_template("pit (SQL)", OLD_PIT_SQL)
    _run(migration)
    row.refresh_from_db()
    assert row.sql_template_content == _bundled_pit_sql()
    # Fields with no superseded match are left alone.
    assert row.yaml_template_content == "custom yaml\n"


def test_crlf_copy_of_old_template_is_refreshed(migration):
    row = _pit_template("pit (SQL)", OLD_PIT_SQL.replace("\n", "\r\n"))
    _run(migration)
    row.refresh_from_db()
    assert row.sql_template_content == _bundled_pit_sql()


def test_edited_template_is_kept(migration):
    edited = OLD_PIT_SQL + "-- my change\n"
    row = _pit_template("pit (custom)", edited)
    _run(migration)
    row.refresh_from_db()
    assert row.sql_template_content == edited


def test_current_bundled_versions_are_not_listed_as_superseded(django_setup):
    """Guards the generated hash table: the bundle itself is never 'old'."""
    from engine.services.generation.template_resolver import bundled_templates

    module = importlib.import_module("engine.migrations.0020_refresh_bundled_templates")
    for framework in ("dbt", "sqlmesh"):
        for template in bundled_templates(framework):
            current = module._content_hash(template.path.read_text(encoding="utf-8"))
            superseded = module.SUPERSEDED_BUNDLED_HASHES.get(
                (framework, template.entity_type, template.template_type), ()
            )
            assert current not in superseded, template.path
