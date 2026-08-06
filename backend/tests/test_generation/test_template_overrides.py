"""Tests for caller-supplied per-generation template overrides (#383).

Covers resolver precedence (override > DB > file, SQL and YAML
independently), the engine's custom delimiters inside override content,
the reusable validation helper, and an end-to-end generation that renders
with an override without touching the global ModelTemplate table.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Resolver precedence: override > file
# ---------------------------------------------------------------------------


def test_override_sql_only_yaml_falls_through_to_file(django_setup):
    from engine.services.generation import TemplateOverride, TemplateResolver

    resolver = TemplateResolver(
        use_db_templates=False,
        templates_override={"hub_standard": TemplateOverride(sql="-- override sql")},
    )
    sql_template, yaml_template = resolver.get_templates("hub_standard")

    # Override compiled from a string has no on-disk filename; a file does.
    assert sql_template is not None
    assert sql_template.render() == "-- override sql"
    assert sql_template.filename == "<template>"
    # YAML has no override, so it resolves from the bundled file.
    assert yaml_template is not None
    assert yaml_template.filename.endswith("hub_standard.yml.j2")


def test_override_yaml_only_sql_falls_through_to_file(django_setup):
    from engine.services.generation import TemplateOverride, TemplateResolver

    resolver = TemplateResolver(
        use_db_templates=False,
        templates_override={"hub_standard": TemplateOverride(yaml="# override yaml")},
    )
    sql_template, yaml_template = resolver.get_templates("hub_standard")

    # Override compiled from a string has no on-disk filename; a file does.
    assert yaml_template is not None
    assert yaml_template.render() == "# override yaml"
    assert yaml_template.filename == "<template>"
    # SQL has no override, so it resolves from the bundled file.
    assert sql_template is not None
    assert sql_template.filename.endswith("hub_standard.sql.j2")


def test_override_content_uses_engine_delimiters(django_setup):
    from engine.services.generation import TemplateOverride, TemplateResolver

    override = TemplateOverride(
        sql="[% if flag %][[ value ]][# ignored #][% endif %]",
    )
    resolver = TemplateResolver(
        use_db_templates=False,
        templates_override={"hub_standard": override},
    )
    sql_template, _ = resolver.get_templates("hub_standard")

    assert sql_template.render(flag=True, value="rendered") == "rendered"


# ---------------------------------------------------------------------------
# Resolver precedence: override > DB (and DB left untouched)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_override_beats_db_template_per_part(django_setup):
    from engine.models.templates import ModelTemplate
    from engine.services.generation import TemplateOverride, TemplateResolver

    ModelTemplate.objects.create(
        name="db_hub",
        entity_type="hub_standard",
        sql_template_content="-- db sql",
        yaml_template_content="# db yaml",
        is_active=True,
        priority=10,
    )

    resolver = TemplateResolver(
        use_db_templates=True,
        templates_override={"hub_standard": TemplateOverride(sql="-- override sql")},
    )
    sql_template, yaml_template = resolver.get_templates("hub_standard")

    # SQL override wins over DB.
    assert sql_template.render() == "-- override sql"
    # YAML has no override, so it falls through to the DB template.
    assert yaml_template.render() == "# db yaml"


@pytest.mark.django_db
def test_no_override_uses_db_and_leaves_table_unchanged(django_setup):
    from engine.models.templates import ModelTemplate
    from engine.services.generation import TemplateResolver

    tmpl = ModelTemplate.objects.create(
        name="db_hub",
        entity_type="hub_standard",
        sql_template_content="-- db sql",
        yaml_template_content="# db yaml",
        is_active=True,
        priority=10,
    )
    before = (tmpl.sql_template_content, tmpl.yaml_template_content)

    resolver = TemplateResolver(use_db_templates=True)  # no overrides
    sql_template, yaml_template = resolver.get_templates("hub_standard")

    assert sql_template.render() == "-- db sql"
    assert yaml_template.render() == "# db yaml"

    tmpl.refresh_from_db()
    assert (tmpl.sql_template_content, tmpl.yaml_template_content) == before


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def test_validate_template_accepts_valid_template():
    from engine.services.generation import validate_template

    result = validate_template("[% if x %][[ x ]][% endif %]")

    assert result.valid is True
    assert result.error is None


def test_validate_template_reports_structured_error_without_traceback():
    from engine.services.generation import validate_template

    # Unclosed block statement is a syntax error.
    result = validate_template("[% if x %]")

    assert result.valid is False
    assert result.error is not None
    assert result.error.message
    assert result.error.line is not None
    assert "Traceback" not in result.error.message


# ---------------------------------------------------------------------------
# End-to-end generation with an override + multi-tenant safety
# ---------------------------------------------------------------------------


def _patch_build_stage(monkeypatch, project_export):
    from engine.services.generation import pipeline as pipeline_module
    from engine.services.generation.stages import build as build_module

    def fake_build(**_kwargs):
        return project_export

    monkeypatch.setattr(build_module, "build_export", fake_build)
    monkeypatch.setattr(pipeline_module, "build_export", fake_build)


@pytest.fixture
def engine_project(django_setup, db):
    from engine.models import Project

    return Project.objects.create(name="override_e2e", description="test")


@pytest.mark.django_db
def test_generation_renders_override_and_does_not_touch_global_table(
    django_setup, project_export, engine_project, monkeypatch
):
    from engine.models.templates import ModelTemplate
    from engine.services.generation import (
        EntityRef,
        EntitySelection,
        GenerationOptions,
        TemplateOverride,
        generate,
    )

    _patch_build_stage(monkeypatch, project_export)
    if not project_export.hubs:
        pytest.skip("Sample export has no hubs")
    target = project_export.hubs[0]
    marker = "-- CUSTOM OVERRIDE MARKER"

    report = generate(
        project=engine_project,
        output_type="dbt",
        options=GenerationOptions(
            dry_run=True,
            return_content=True,
            entity_selection=EntitySelection(
                only_entities=[EntityRef(type="hub", name=target.hub_name)],
            ),
            templates_override={"hub_standard": TemplateOverride(sql=marker)},
        ),
    )

    sql_artifacts = [a for a in report.artifacts if a.kind == "sql_model"]
    assert sql_artifacts, "Expected a rendered sql artifact for the previewed hub"
    # The hub sql model was rendered from the override content.
    assert any(a.content and marker in a.content for a in sql_artifacts)

    # Multi-tenant safety: nothing was written to the global template table.
    assert ModelTemplate.objects.count() == 0


@pytest.mark.django_db
def test_generation_without_override_ignores_it(
    django_setup, project_export, engine_project, monkeypatch
):
    from engine.services.generation import (
        EntityRef,
        EntitySelection,
        GenerationOptions,
        generate,
    )

    _patch_build_stage(monkeypatch, project_export)
    if not project_export.hubs:
        pytest.skip("Sample export has no hubs")
    target = project_export.hubs[0]

    report = generate(
        project=engine_project,
        output_type="dbt",
        options=GenerationOptions(
            dry_run=True,
            return_content=True,
            entity_selection=EntitySelection(
                only_entities=[EntityRef(type="hub", name=target.hub_name)],
            ),
            templates_override=None,
        ),
    )

    sql_artifacts = [a for a in report.artifacts if a.kind == "sql_model"]
    assert sql_artifacts
    assert all("-- CUSTOM OVERRIDE MARKER" not in a.content for a in sql_artifacts)
