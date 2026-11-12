"""Migration 0020: stored dbt templates get the #442 changes.

Workspaces keep the templates `turbovault init` seeded into the database, and
generation prefers them, so the bundled template changes of #442 must be
applied to those rows too.
"""

from __future__ import annotations

import importlib

import pytest

migration = importlib.import_module(
    "engine.migrations.0020_dbt_templates_output_attributes"
)

OLD_HUB_SQL = """{{ config(
[% if materialization %]
    materialized='[[ materialization ]]',
[% endif %]
    tags=['hub', 'raw_vault'[% if group %], '[[ group ]]'[% endif %]]
) }}
"""
NEW_HUB_SQL = """{{ config(
[% if materialization %]
    materialized='[[ materialization ]]',
[% endif %]
[% for key, value in (model_config or {}).items() %]
    [[ key ]]=[[ value ]],
[% endfor %]
    tags=[% if model_tags %][[ model_tags ]][% else %]['hub', 'raw_vault'[% if group %], '[[ group ]]'[% endif %]][% endif +%]
) }}
"""


def _bundled(framework_dir: str, suffix: str) -> list[tuple[str, str]]:
    from engine.services.generation.template_resolver import TEMPLATES_DIR

    return [
        (path.name.removesuffix(suffix), path.read_text(encoding="utf-8"))
        for path in sorted((TEMPLATES_DIR / "dbt" / framework_dir).glob(f"*{suffix}"))
        if path.name.removesuffix(suffix) not in {"dbt_project", "packages", "sources"}
    ]


def test_old_config_block_gets_the_hooks():
    assert migration.upgrade_sql("hub_standard", OLD_HUB_SQL) == NEW_HUB_SQL


def test_crlf_templates_keep_their_line_endings():
    old = OLD_HUB_SQL.replace("\n", "\r\n")
    assert migration.upgrade_sql("hub_standard", old) == NEW_HUB_SQL.replace(
        "\n", "\r\n"
    )


def test_hard_coded_suffixes_are_replaced():
    assert (
        migration.upgrade_sql("satellite_v1", "sat_v0: [[ satellite_name ]]_v0\n")
        == "sat_v0: [[ v0_name ]]\n"
    )
    assert (
        migration.upgrade_sql(
            "pit", "[% for sat in satellites %]\n    - [[ sat ]]_v0\n"
        )
        == "[% for sat in satellite_models %]\n    - [[ sat ]]\n"
    )
    assert (
        migration.upgrade_yaml(
            "snapshot_control_v0", "models:\n  - name: [[ name ]]_v0\n"
        )
        == "models:\n  - name: [[ model_name ]]\n"
    )


def test_customized_parts_are_left_alone():
    custom = "{{ config(tags=['mine']) }}\nsat_v0: my_own_v0\n"
    assert migration.upgrade_sql("satellite_v1", custom) == custom


@pytest.mark.parametrize(
    ("folder", "suffix", "upgrade"),
    [
        ("sql", ".sql.j2", migration.upgrade_sql),
        ("yaml", ".yml.j2", migration.upgrade_yaml),
    ],
)
def test_current_bundled_templates_are_unchanged(folder, suffix, upgrade):
    for entity_type, content in _bundled(folder, suffix):
        assert upgrade(entity_type, content) == content, entity_type


@pytest.mark.django_db
def test_migration_updates_stored_dbt_templates_only(django_setup):
    from django.apps import apps
    from engine.models import ModelTemplate

    dbt = ModelTemplate.objects.create(
        name="hub_standard (SQL)",
        framework="dbt",
        entity_type="hub_standard",
        sql_template_content=OLD_HUB_SQL,
    )
    sqlmesh = ModelTemplate.objects.create(
        name="hub_standard (Python)",
        framework="sqlmesh",
        entity_type="hub_standard",
        sql_template_content=OLD_HUB_SQL,
    )

    migration.forwards(apps, None)

    dbt.refresh_from_db()
    sqlmesh.refresh_from_db()
    assert dbt.sql_template_content == NEW_HUB_SQL
    assert sqlmesh.sql_template_content == OLD_HUB_SQL
