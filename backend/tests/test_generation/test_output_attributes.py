"""Output attributes (issue #442): what generation writes, and the rules.

Ported from #235 and adapted to the model outputs this branch stores: a
model's further config() settings parse back to the stored values in dbt's
Jinja, a PIT's stored post_hook replaces its clean-up hook, the write stage
refuses paths outside the output and files that would share a path, and the
JSON format's attributes follow one set of rules with the stored values.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_generation.test_model_outputs import (
    _generate,
    _get,
    _issues,
    _store,
    build_project,
)


@pytest.fixture
def project(django_setup, db):
    return build_project()


def _sql(root: Path, name: str) -> str:
    (path,) = root.rglob(f"{name}.sql")
    return path.read_text(encoding="utf-8")


def _config_call(sql: str) -> str:
    """The model's config() call: it ends with ") }}" on a line of its own
    (values such as hooks may contain "}}" themselves)."""
    start = sql.index("{{ config(")
    return sql[start : sql.index("\n) }}", start) + len("\n) }}")]


def _parsed_config(sql: str) -> dict:
    """The config() arguments as dbt's Jinja reads them."""
    import jinja2

    captured: dict = {}

    def config(**kwargs: object) -> str:
        captured.update(kwargs)
        return ""

    jinja2.Environment().from_string(_config_call(sql)).render(config=config)
    return captured


# ---------------------------------------------------------------------------
# What generation writes
# ---------------------------------------------------------------------------


def test_further_config_settings_read_back_as_stored(project, tmp_path):
    custom = {
        "unique_key": "hk_customer_h",
        "on_schema_change": 'it\'s "quoted" \\ {{ x }}',
        "full_refresh": False,
        "batch_size": 1000,
        "grants": {"select": ["reporter", "bi"]},
        "meta": None,
    }
    _store("hub", _get("Hub", hub_physical_name="CUSTOMER_H"), config=custom)

    report = _generate(project, tmp_path)

    assert report.status == "success", report.issues
    parsed = _parsed_config(_sql(tmp_path / "dbt", "CUSTOMER_H"))
    assert {key: parsed[key] for key in custom} == custom


def test_a_stored_post_hook_replaces_the_pits_clean_up_hook(project, tmp_path):
    pit = _get("PIT", pit_physical_name="CUSTOMER_PIT")

    report = _generate(project, tmp_path / "default")
    assert report.status == "success", report.issues
    hook = _parsed_config(_sql(tmp_path / "default" / "dbt", "CUSTOMER_PIT"))
    assert "clean_up_pit" in hook["post_hook"]

    _store("pit", pit, config={"post_hook": "{{ grant_reporting() }}"})
    report = _generate(project, tmp_path / "stored")

    assert report.status == "success", report.issues
    parsed = _parsed_config(_sql(tmp_path / "stored" / "dbt", "CUSTOMER_PIT"))
    assert parsed["post_hook"] == "{{ grant_reporting() }}"


def test_a_model_placed_like_a_sources_file_writes_nothing(project, tmp_path):
    customer = _get("SourceTable", physical_table_name="CUSTOMER")
    # The stage's .yml would be the crm system's sources file
    _store("stage", customer, model_name="source__crm", folder="models/10_sources")

    report = _generate(project, tmp_path)

    (issue,) = _issues(report, "write.path_collision")
    assert "models/10_sources/source__crm.yml" in issue.message
    assert "Nothing was written" in issue.message
    assert not list((tmp_path / "dbt").rglob("*.sql"))


def test_paths_that_differ_in_case_collide(django_setup, tmp_path):
    from engine.services.generation.stages.write import write_artifacts
    from engine.services.generation.types import GeneratedArtifact, GenerationOptions

    artifacts = [
        GeneratedArtifact(kind="sql_model", path="models/Hub.sql", content="x"),
        GeneratedArtifact(kind="sql_model", path="models/hub.sql", content="y"),
        GeneratedArtifact(kind="sql_model", path="models/other.sql", content="z"),
    ]

    written, issues = write_artifacts(
        artifacts=artifacts,
        output_type="dbt",
        output_path=tmp_path / "project",
        options=GenerationOptions(),
    )

    assert [i.code for i in issues] == ["write.path_collision"]
    assert "models/Hub.sql / models/hub.sql" in issues[0].message
    assert written == []
    assert not (tmp_path / "project" / "models" / "other.sql").exists()


def test_write_stage_refuses_paths_outside_the_output(django_setup, tmp_path):
    """Safeguard behind the input validation: a path that escapes the output
    folder is skipped with an error; the other files are still written."""
    from engine.services.generation.stages.write import write_artifacts
    from engine.services.generation.types import GeneratedArtifact, GenerationOptions

    out = tmp_path / "project"
    artifacts = [
        GeneratedArtifact(kind="sql_model", path="../escaped.sql", content="x"),
        GeneratedArtifact(kind="sql_model", path="models/ok.sql", content="y"),
    ]
    written, issues = write_artifacts(
        artifacts=artifacts,
        output_type="dbt",
        output_path=out,
        options=GenerationOptions(),
    )
    assert [i.code for i in issues] == ["write.path_outside_output"]
    assert not (tmp_path / "escaped.sql").exists()
    assert (out / "models" / "ok.sql").read_text() == "y"


# ---------------------------------------------------------------------------
# The rules for the values (stored and in the JSON format)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "fragment"),
    [
        ({"file_path": "../outside.sql"}, "must stay inside models/"),
        ({"file_path": "a/../../b.sql"}, "must stay inside models/"),
        ({"file_path": "/abs/hub.sql"}, "relative path"),
        ({"file_path": "C:/abs/hub.sql"}, "relative path"),
        ({"file_path": "raw\\hub.sql"}, "relative path"),
        ({"file_path": "raw/hub.yml"}, ".sql file"),
        ({"model_name": "a", "file_path": "raw/b.sql"}, "named after"),
        ({"model_name": "my hub"}, "can't name a dbt model"),
        ({"model_name": ".hidden"}, "can't name a dbt model"),
        ({"schema": ""}, "'schema'"),
        ({"tags": "daily"}, "valid list"),
        ({"custom_config_json": {"post-hook": "x"}}, "post-hook"),
        ({"custom_config_json": {"schema": "x"}}, "own attribute"),
        ({"unknown": 1}, "Extra inputs"),
    ],
)
def test_invalid_attributes_are_rejected(django_setup, values, fragment):
    from engine.services.export.models import ModelOutputAttributes
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match=fragment.replace("\\", "\\\\")):
        ModelOutputAttributes.model_validate(values)


def test_values_real_projects_use_are_accepted(django_setup):
    from engine.services.export.models import ModelOutputAttributes

    attributes = ModelOutputAttributes.model_validate(
        {
            "model_name": "hub_customer",
            "file_path": "raw_vault/hubs/hub_customer.sql",
            # Written through escaping literals: no identifier rule
            "schema": "{{ env_var('DV_SCHEMA', 'raw_vault') }}",
            "alias": "customer hub",
            "tags": ["pii data", "daily"],
            "custom_config_json": {"post_hook": "{{ grant() }}"},
        }
    )

    assert attributes.as_stored()["schema"] == "{{ env_var('DV_SCHEMA', 'raw_vault') }}"


def test_output_kinds_and_frameworks_are_checked(django_setup):
    from engine.services.export.models import HubDefinition
    from pydantic import ValidationError

    base = {"hub_name": "CUSTOMER_H", "hub_type": "standard"}
    with pytest.raises(ValidationError, match="unknown dbt output kind"):
        HubDefinition.model_validate(
            {**base, "generation_config": {"dbt": {"pit": {"alias": "x"}}}}
        )
    with pytest.raises(ValidationError, match="sqlmesh"):
        HubDefinition.model_validate(
            {**base, "generation_config": {"sqlmesh": {"hub": {"alias": "x"}}}}
        )


def test_a_stored_config_key_follows_the_same_rule(project):
    from django.core.exceptions import ValidationError
    from engine.models import ModelOutput

    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    output = ModelOutput(hub=hub, kind="hub", config={"post-hook": "x"})

    with pytest.raises(ValidationError, match="post-hook"):
        output.full_clean(exclude=["project"])
