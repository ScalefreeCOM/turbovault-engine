"""Tests for framework-aware template resolution (ticket 425).

Covers:
- File-based defaults resolved from templates/<framework>/ directories
- Override API keyed by {framework: {entity_type: TemplateOverride}}
- Overrides for one framework never apply to the other
- Python syntax check for SQLMesh templates in validate_template()
- Migration default: existing ModelTemplate rows carry framework="dbt"
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# File-based template resolution per framework
# ---------------------------------------------------------------------------


def test_dbt_resolver_loads_from_dbt_directory(django_setup):
    """File-based templates for dbt live under templates/dbt/ and are found."""
    from engine.services.generation import TemplateResolver

    resolver = TemplateResolver(use_db_templates=False, framework="dbt")
    sql_template, yaml_template = resolver.get_templates("hub_standard")

    assert sql_template is not None
    assert "hub_standard.sql.j2" in (sql_template.filename or "")
    assert yaml_template is not None
    assert "hub_standard.yml.j2" in (yaml_template.filename or "")


def test_sqlmesh_resolver_returns_none_for_missing_templates(django_setup):
    """SQLMesh has no bundled file-based templates yet — resolver returns None
    rather than falling through to dbt templates."""
    from engine.services.generation import TemplateResolver

    resolver = TemplateResolver(use_db_templates=False, framework="sqlmesh")
    sql_template, yaml_template = resolver.get_templates("hub_standard")

    # No sqlmesh file templates exist; must not return the dbt files.
    assert sql_template is None
    assert yaml_template is None


def test_dbt_file_templates_resolved_from_dbt_subdirectory(django_setup):
    """After restructuring, dbt templates are loaded from templates/dbt/sql/
    and templates/dbt/yaml/ — file paths confirm the correct directory."""
    from engine.services.generation import TemplateResolver

    resolver = TemplateResolver(use_db_templates=False, framework="dbt")
    sql_template, yaml_template = resolver.get_templates("hub_standard")

    assert sql_template is not None
    # Path must come from the dbt sub-directory, not the old flat layout.
    assert sql_template.filename and "/dbt/sql/" in sql_template.filename.replace("\\", "/")
    assert yaml_template is not None
    assert yaml_template.filename and "/dbt/yaml/" in yaml_template.filename.replace("\\", "/")


# ---------------------------------------------------------------------------
# Override API: framework-keyed isolation
# ---------------------------------------------------------------------------


def test_dbt_override_applied_to_dbt_resolver(django_setup):
    from engine.services.generation import TemplateOverride, TemplateResolver

    resolver = TemplateResolver(
        use_db_templates=False,
        framework="dbt",
        templates_override={"dbt": {"hub_standard": TemplateOverride(sql="-- dbt override")}},
    )
    sql_template, _ = resolver.get_templates("hub_standard")
    assert sql_template is not None
    assert sql_template.render() == "-- dbt override"


def test_dbt_override_not_visible_to_sqlmesh_resolver(django_setup):
    """An override scoped to 'dbt' must not appear in a sqlmesh resolver."""
    from engine.services.generation import TemplateOverride, TemplateResolver

    override_map = {"dbt": {"hub_standard": TemplateOverride(sql="-- dbt override")}}

    sqlmesh_resolver = TemplateResolver(
        use_db_templates=False,
        framework="sqlmesh",
        templates_override=override_map,
    )
    sql_template, _ = sqlmesh_resolver.get_templates("hub_standard")

    # sqlmesh has no file template and the dbt override must not bleed in.
    assert sql_template is None


def test_sqlmesh_override_not_visible_to_dbt_resolver(django_setup):
    """An override scoped to 'sqlmesh' must not appear in a dbt resolver."""
    from engine.services.generation import TemplateOverride, TemplateResolver

    override_map = {"sqlmesh": {"hub_standard": TemplateOverride(sql="-- sqlmesh override")}}

    dbt_resolver = TemplateResolver(
        use_db_templates=False,
        framework="dbt",
        templates_override=override_map,
    )
    sql_template, _ = dbt_resolver.get_templates("hub_standard")

    # dbt resolver must see the bundled file template (real filename from disk),
    # not the sqlmesh override (which would show up as "<template>").
    assert sql_template is not None
    assert sql_template.filename and "hub_standard.sql.j2" in sql_template.filename


def test_both_framework_overrides_coexist_independently(django_setup):
    """Overrides for dbt and sqlmesh in the same dict don't interfere."""
    from engine.services.generation import TemplateOverride, TemplateResolver

    override_map = {
        "dbt": {"hub_standard": TemplateOverride(sql="-- dbt override")},
        "sqlmesh": {"hub_standard": TemplateOverride(sql="-- sqlmesh override")},
    }

    dbt_resolver = TemplateResolver(
        use_db_templates=False, framework="dbt", templates_override=override_map
    )
    sqlmesh_resolver = TemplateResolver(
        use_db_templates=False, framework="sqlmesh", templates_override=override_map
    )

    dbt_sql, _ = dbt_resolver.get_templates("hub_standard")
    sqlmesh_sql, _ = sqlmesh_resolver.get_templates("hub_standard")

    assert dbt_sql is not None and dbt_sql.render() == "-- dbt override"
    assert sqlmesh_sql is not None and sqlmesh_sql.render() == "-- sqlmesh override"


def test_no_override_for_framework_returns_none_overrides(django_setup):
    """A resolver for a framework with no overrides in the map behaves as if
    templates_override=None was passed."""
    from engine.services.generation import TemplateOverride, TemplateResolver

    override_map = {"dbt": {"hub_standard": TemplateOverride(sql="-- dbt override")}}

    # sqlmesh not in override_map at all
    resolver = TemplateResolver(
        use_db_templates=False,
        framework="sqlmesh",
        templates_override=override_map,
    )
    sql_template, _ = resolver.get_templates("hub_standard")
    assert sql_template is None  # no file template + no override


# ---------------------------------------------------------------------------
# DB templates are framework-scoped
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_db_template_for_dbt_not_visible_to_sqlmesh_resolver(django_setup):
    from engine.models.templates import ModelTemplate
    from engine.services.generation import TemplateResolver

    ModelTemplate.objects.create(
        name="dbt_hub",
        framework="dbt",
        entity_type="hub_standard",
        sql_template_content="-- dbt db template",
        is_active=True,
    )

    resolver = TemplateResolver(use_db_templates=True, framework="sqlmesh")
    sql_template, _ = resolver.get_templates("hub_standard")

    # DB template is dbt-only; sqlmesh resolver must not find it.
    assert sql_template is None


@pytest.mark.django_db
def test_db_template_for_sqlmesh_not_visible_to_dbt_resolver(django_setup):
    from engine.models.templates import ModelTemplate
    from engine.services.generation import TemplateResolver

    ModelTemplate.objects.create(
        name="sm_hub",
        framework="sqlmesh",
        entity_type="hub_standard",
        sql_template_content="-- sqlmesh db template",
        is_active=True,
    )

    resolver = TemplateResolver(use_db_templates=True, framework="dbt")
    sql_template, _ = resolver.get_templates("hub_standard")

    # dbt resolver must return the bundled file template (real filename), not
    # the sqlmesh DB row (which would appear as "<template>").
    assert sql_template is not None
    assert sql_template.filename and "hub_standard.sql.j2" in sql_template.filename


# ---------------------------------------------------------------------------
# validate_template: Python syntax check
# ---------------------------------------------------------------------------


def test_validate_template_python_check_passes_for_valid_python_template():
    from engine.services.generation import validate_template

    # A SQLMesh model template where string variables are properly quoted.
    template = (
        'from datavault4sqlmesh import hub_model\n\n'
        'hub_model(\n'
        '    name="[[ name ]]",\n'
        '    hashkey="[[ hashkey ]]",\n'
        ')\n'
    )
    result = validate_template(template, check_python_syntax=True)
    assert result.valid is True
    assert result.error is None


def test_validate_template_python_check_catches_structural_python_error():
    from engine.services.generation import validate_template

    # Missing comma after first argument — Python syntax error in static part.
    template = (
        'from datavault4sqlmesh import hub_model\n\n'
        'hub_model(\n'
        '    name="[[ name ]]"\n'  # missing trailing comma
        '    hashkey="[[ hashkey ]]",\n'
        ')\n'
    )
    result = validate_template(template, check_python_syntax=True)
    assert result.valid is False
    assert result.error is not None
    assert result.error.line is not None


def test_validate_template_python_check_skipped_by_default():
    """Without check_python_syntax=True, a structurally broken Python template
    passes Jinja validation — the Python check is opt-in."""
    from engine.services.generation import validate_template

    # Not valid Python after rendering, but valid Jinja.
    template = "hub_model(name=[[ name ]],"  # trailing comma, no closing paren
    result = validate_template(template)  # default: check_python_syntax=False
    assert result.valid is True


def test_validate_template_jinja_error_reported_before_python_check():
    from engine.services.generation import validate_template

    # Jinja syntax error: unclosed block.
    result = validate_template("[% if x %]", check_python_syntax=True)
    assert result.valid is False
    assert result.error is not None
    # Line number should be present.
    assert result.error.line is not None


# ---------------------------------------------------------------------------
# Migration default: existing ModelTemplate rows carry framework="dbt"
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_new_model_template_defaults_to_dbt(django_setup):
    from engine.models.templates import ModelTemplate

    tmpl = ModelTemplate.objects.create(
        name="default_fw_test",
        entity_type="hub_standard",
        sql_template_content="-- test",
    )
    assert tmpl.framework == "dbt"


@pytest.mark.django_db
def test_model_template_framework_choices_are_dbt_and_sqlmesh(django_setup):
    from engine.models.templates import ModelTemplate

    choices = {value for value, _ in ModelTemplate.Framework.choices}
    assert choices == {"dbt", "sqlmesh"}
