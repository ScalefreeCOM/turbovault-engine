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


def _is_bundled_sqlmesh_template(template, entity_type: str) -> bool:
    """True if *template* is the bundled templates/sqlmesh/models/<entity>.py.j2."""
    filename = (getattr(template, "filename", None) or "").replace("\\", "/")
    return filename.endswith(f"/sqlmesh/models/{entity_type}.py.j2")


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


@pytest.mark.parametrize(
    "entity_type",
    ["stage", "hub_standard", "link_standard", "satellite_standard", "satellite_v1"],
)
def test_sqlmesh_resolver_loads_bundled_sqlmesh_templates(django_setup, entity_type):
    """SQLMesh model templates come from templates/sqlmesh/models/*.py.j2 —
    never from the dbt files. SQLMesh has no YAML templates."""
    from engine.services.generation import TemplateResolver

    resolver = TemplateResolver(use_db_templates=False, framework="sqlmesh")
    sql_template, yaml_template = resolver.get_templates(entity_type)

    assert _is_bundled_sqlmesh_template(sql_template, entity_type)
    assert yaml_template is None


def test_sqlmesh_resolver_has_no_template_for_unsupported_entity(django_setup):
    """Entity types SQLMesh output doesn't support have no SQLMesh template,
    and the resolver must not fall through to the dbt one."""
    from engine.services.generation import TemplateResolver

    resolver = TemplateResolver(use_db_templates=False, framework="sqlmesh")
    sql_template, yaml_template = resolver.get_templates("pit")

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

    # The dbt override must not bleed in: the bundled sqlmesh file is used.
    assert _is_bundled_sqlmesh_template(sql_template, "hub_standard")


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
    # No sqlmesh override: the bundled sqlmesh file template is used.
    assert _is_bundled_sqlmesh_template(sql_template, "hub_standard")


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

    # DB template is dbt-only; sqlmesh resolver falls back to its own file.
    assert _is_bundled_sqlmesh_template(sql_template, "hub_standard")


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
# Bundled template layout and DB seeding
# ---------------------------------------------------------------------------


def test_bundled_templates_live_only_in_framework_directories():
    """No flat templates/sql or templates/yaml copies: a second copy next to
    templates/dbt/ silently drifts (edits to it are never rendered)."""
    from engine.services.generation.template_resolver import TEMPLATES_DIR

    top_level = {p.name for p in TEMPLATES_DIR.iterdir() if not p.name.startswith(".")}
    assert top_level <= {"dbt", "sqlmesh"}, top_level
    assert any((TEMPLATES_DIR / "dbt" / "sql").glob("*.sql.j2"))
    assert any((TEMPLATES_DIR / "dbt" / "yaml").glob("*.yml.j2"))


def test_framework_templates_dir_helper():
    from pathlib import Path

    from engine.services.generation.template_resolver import (
        TEMPLATES_DIR,
        framework_templates_dir,
    )

    assert framework_templates_dir("dbt") == TEMPLATES_DIR / "dbt"
    assert framework_templates_dir("sqlmesh", Path("custom")) == Path("custom") / "sqlmesh"


@pytest.mark.django_db
def test_populate_templates_seeds_dbt_templates_as_framework_dbt(django_setup):
    import io

    from django.core.management import call_command
    from engine.models.templates import ModelTemplate
    from engine.services.generation.template_resolver import TEMPLATES_DIR

    call_command("populate_templates", stdout=io.StringIO())

    seeded = ModelTemplate.objects.filter(name="hub_standard (SQL)")
    assert seeded.count() == 1
    row = seeded.get()
    assert row.framework == "dbt"
    expected = (TEMPLATES_DIR / "dbt" / "sql" / "hub_standard.sql.j2").read_text(
        encoding="utf-8"
    )
    assert row.sql_template_content == expected


@pytest.mark.django_db
def test_populate_templates_overwrite_leaves_sqlmesh_templates_alone(django_setup):
    """--overwrite updates the dbt row only, never a same-named SQLMesh row."""
    import io

    from django.core.management import call_command
    from engine.models.templates import ModelTemplate

    sqlmesh_row = ModelTemplate.objects.create(
        name="hub_standard (SQL)",
        framework="sqlmesh",
        entity_type="hub_standard",
        sql_template_content="# custom sqlmesh hub",
        is_active=True,
    )

    call_command("populate_templates", "--overwrite", stdout=io.StringIO())

    sqlmesh_row.refresh_from_db()
    assert sqlmesh_row.sql_template_content == "# custom sqlmesh hub"
    assert ModelTemplate.objects.filter(
        name="hub_standard (SQL)", framework="dbt"
    ).exists()


@pytest.mark.django_db
def test_populate_templates_seeds_sqlmesh_templates(django_setup):
    import io

    from django.core.management import call_command
    from engine.models.templates import ModelTemplate
    from engine.services.generation.template_resolver import bundled_model_templates

    call_command("populate_templates", stdout=io.StringIO())

    for entity_type, path in bundled_model_templates("sqlmesh"):
        row = ModelTemplate.objects.get(
            framework="sqlmesh", entity_type=entity_type, name=f"{entity_type} (Python)"
        )
        assert row.sql_template_content == path.read_text(encoding="utf-8")
        assert row.yaml_template_content == ""


@pytest.mark.django_db
def test_seeded_db_templates_render_like_the_bundled_files(django_setup, project_export):
    """After seeding, both frameworks resolve to DB copies of the bundled files,
    so the generated SQLMesh models are unchanged."""
    import io

    from django.core.management import call_command
    from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh
    from engine.services.generation.template_resolver import TemplateResolver
    from engine.services.generation.types import GenerationOptions
    from engine.services.runtime_config import EngineRuntimeConfig

    def models(resolver):
        artifacts, _ = render_sqlmesh(
            project_export, EngineRuntimeConfig(), GenerationOptions(), resolver
        )
        return [a.content for a in artifacts if a.kind == "sqlmesh_model"]

    from_files = models(TemplateResolver(use_db_templates=False, framework="sqlmesh"))
    call_command("populate_templates", stdout=io.StringIO())
    db_resolver = TemplateResolver(use_db_templates=True, framework="sqlmesh")
    sql_template, _ = db_resolver.get_templates("hub_standard")
    assert sql_template.filename in (None, "<template>")  # really the DB copy
    assert models(db_resolver) == from_files


@pytest.mark.django_db
def test_ensure_templates_populated_seeds_both_frameworks(django_setup, monkeypatch):
    from engine.cli.utils.db_utils import ensure_templates_populated
    from engine.models.templates import ModelTemplate

    monkeypatch.delenv("TURBOVAULT_SKIP_TEMPLATE_POPULATION", raising=False)
    ModelTemplate.objects.all().delete()
    ensure_templates_populated()

    dbt_hub = ModelTemplate.objects.get(framework="dbt", name="hub_standard (SQL)")
    assert dbt_hub.has_sql_template and dbt_hub.has_yaml_template  # YAML merged in
    sqlmesh_hub = ModelTemplate.objects.get(framework="sqlmesh", name="hub_standard (Python)")
    assert sqlmesh_hub.has_sql_template and not sqlmesh_hub.has_yaml_template
    assert not ModelTemplate.objects.filter(framework="sqlmesh", name__endswith="(YAML)").exists()


# ---------------------------------------------------------------------------
# Resolution precedence per framework: override > DB > file
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("framework", ["dbt", "sqlmesh"])
def test_resolution_precedence_per_framework(django_setup, framework):
    from engine.models.templates import ModelTemplate
    from engine.services.generation import TemplateOverride, TemplateResolver

    def resolve(**kwargs):
        sql_template, _ = TemplateResolver(framework=framework, **kwargs).get_templates(
            "hub_standard"
        )
        return sql_template

    # 1. Nothing else: the bundled file of this framework.
    file_template = resolve(use_db_templates=True)
    suffix = ".py.j2" if framework == "sqlmesh" else ".sql.j2"
    assert file_template.filename.replace("\\", "/").endswith(
        f"/{framework}/{'models' if framework == 'sqlmesh' else 'sql'}/hub_standard{suffix}"
    )

    # 2. An active DB template of this framework beats the file; the
    #    higher-priority one wins, inactive and other-framework rows are ignored.
    other = "dbt" if framework == "sqlmesh" else "sqlmesh"
    ModelTemplate.objects.create(
        name="low", framework=framework, entity_type="hub_standard",
        sql_template_content="-- db low", priority=1, is_active=True,
    )
    ModelTemplate.objects.create(
        name="high", framework=framework, entity_type="hub_standard",
        sql_template_content="-- db high", priority=5, is_active=True,
    )
    ModelTemplate.objects.create(
        name="inactive", framework=framework, entity_type="hub_standard",
        sql_template_content="-- db inactive", priority=9, is_active=False,
    )
    ModelTemplate.objects.create(
        name="other framework", framework=other, entity_type="hub_standard",
        sql_template_content="-- other framework", priority=99, is_active=True,
    )
    assert resolve(use_db_templates=True).render() == "-- db high"
    assert resolve(use_db_templates=False).filename == file_template.filename

    # 3. A per-run override for this framework beats the DB template.
    override = {framework: {"hub_standard": TemplateOverride(sql="-- override")}}
    assert resolve(use_db_templates=True, templates_override=override).render() == "-- override"

    # 4. An override for the other framework changes nothing.
    other_override = {other: {"hub_standard": TemplateOverride(sql="-- other override")}}
    assert (
        resolve(use_db_templates=True, templates_override=other_override).render()
        == "-- db high"
    )


# ---------------------------------------------------------------------------
# Migration 0018: existing rows become framework="dbt"
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_migration_0018_sets_existing_rows_to_dbt(django_setup):
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    before = [("engine", "0017_source_value_inheritance")]
    after = [("engine", "0018_modeltemplate_framework")]

    executor = MigrationExecutor(connection)
    executor.migrate(before)
    old_apps = executor.loader.project_state(before).apps
    OldModelTemplate = old_apps.get_model("engine", "ModelTemplate")
    assert "framework" not in {f.name for f in OldModelTemplate._meta.get_fields()}
    OldModelTemplate.objects.create(
        name="pre-existing", entity_type="hub_standard", sql_template_content="-- old"
    )

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(after)
    new_apps = executor.loader.project_state(after).apps
    NewModelTemplate = new_apps.get_model("engine", "ModelTemplate")
    assert NewModelTemplate.objects.get(name="pre-existing").framework == "dbt"

    # Leave the test DB fully migrated for the tests that follow.
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())


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


@pytest.mark.parametrize(
    "template",
    [
        "x = [[ hashed_columns | py_hashed_columns ]]\n",
        "x = [[ (n + 1) | py ]]\n",
    ],
)
def test_validate_template_python_check_does_not_raise_without_context(template):
    """Valid templates that can't render without context return a result
    instead of raising UndefinedError."""
    from engine.services.generation import validate_template

    result = validate_template(template, check_python_syntax=True)
    assert result.valid is True
    assert result.error is None


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


# ---------------------------------------------------------------------------
# Admin: framework is visible, filterable and editable
# ---------------------------------------------------------------------------


def test_model_template_admin_exposes_framework(django_setup):
    from django.contrib import admin
    from django.contrib.auth.models import User
    from django.test import RequestFactory

    from engine.models import ModelTemplate

    model_admin = admin.site._registry[ModelTemplate]
    assert "framework" in model_admin.list_display
    assert "framework" in model_admin.list_filter

    request = RequestFactory().get("/")
    # Unsaved superuser: get_form checks permissions, which needs no DB for it.
    request.user = User(is_superuser=True, is_active=True)
    form_class = model_admin.get_form(request)
    assert "framework" in form_class.base_fields
