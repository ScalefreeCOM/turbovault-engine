"""Tests for the bundled SQLMesh model templates (ticket 425).

The SQLMesh renderer renders every model through a TemplateResolver
(framework="sqlmesh"): per-run override > DB template > bundled
templates/sqlmesh/models/<entity>.py.j2.
"""

from __future__ import annotations

import pytest

# entity type of the template -> GeneratedArtifact.entity_type of its model file
SQLMESH_ENTITY_TYPES = {
    "stage": "stage",
    "hub_standard": "hub",
    "link_standard": "link",
    "satellite_standard": "satellite",
    "satellite_v1": "satellite_v1",
}


def _render(project_export, resolver=None, **runtime_kwargs):
    from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh
    from engine.services.generation.types import GenerationOptions
    from engine.services.runtime_config import EngineRuntimeConfig

    artifacts, issues = render_sqlmesh(
        project_export, EngineRuntimeConfig(**runtime_kwargs), GenerationOptions(), resolver
    )
    return artifacts, issues


def _models(artifacts):
    return [a for a in artifacts if a.kind == "sqlmesh_model"]


# ---------------------------------------------------------------------------
# Bundled templates
# ---------------------------------------------------------------------------


def test_every_supported_entity_has_a_bundled_template():
    from engine.services.generation.template_resolver import bundled_model_templates

    bundled = {entity for entity, _ in bundled_model_templates("sqlmesh")}
    assert bundled == set(SQLMESH_ENTITY_TYPES)


def test_bundled_entity_types_are_model_template_entity_types(django_setup):
    """Each template is named after a ModelTemplate.EntityType, so DB templates
    and overrides keyed by that name reach it (e.g. satellite_v1)."""
    from engine.models.templates import ModelTemplate
    from engine.services.generation.template_resolver import bundled_model_templates

    valid = {choice[0] for choice in ModelTemplate.EntityType.choices}
    for entity, _ in bundled_model_templates("sqlmesh"):
        assert entity in valid, entity


@pytest.mark.parametrize("entity_type", sorted(SQLMESH_ENTITY_TYPES))
def test_bundled_template_passes_validation(entity_type):
    from engine.services.generation.template_resolver import model_templates_dir
    from engine.services.generation.template_validation import validate_template

    path = model_templates_dir("sqlmesh") / f"{entity_type}.py.j2"
    result = validate_template(path.read_text(encoding="utf-8"), check_python_syntax=True)
    assert result.valid, result.error


def test_rendered_models_are_valid_python(django_setup, project_export):
    artifacts, _ = _render(project_export)
    models = _models(artifacts)
    assert {a.entity_type for a in models} == set(SQLMESH_ENTITY_TYPES.values())
    for artifact in models:
        compile(artifact.content, artifact.path, "exec")
        assert artifact.content.endswith(")\n"), artifact.path
        assert not artifact.content.endswith("\n\n"), artifact.path


def test_stage_template_writes_every_optional_argument(django_setup):
    """Covers the stage branches the TPC-H comparison doesn't: column refs for
    load date / record source, and column_overrides."""
    from engine.services.export.models import (
        ProjectExport,
        SourceColumnDef,
        StageDefinition,
    )

    export = ProjectExport(
        project_name="test",
        stages=[
            StageDefinition(
                stage_name="stg__crm__customer",
                source_table="Customer",
                source_schema="CRM_RAW",
                source_system="crm",
                load_date="LOAD_DTS",
                record_source="REC_SRC",
                columns=[SourceColumnDef(column_name="amount", datatype="DECIMAL(18,2)")],
            )
        ],
    )
    artifacts, _ = _render(export, sqlmesh_dialect="postgres")
    (stage,) = [a for a in artifacts if a.entity_type == "stage"]

    assert stage.content == (
        "from datavault4sqlmesh import stage_model\n"
        "\n"
        "stage_model(\n"
        "    name='stage.stg__crm__customer',\n"
        "    source_table='customer',\n"
        "    source_schema='crm_raw',\n"
        "    load_date_col='LOAD_DTS',\n"
        "    record_source_col='REC_SRC',\n"
        "    column_overrides={\n"
        "        'amount': 'DECIMAL(18,2)',\n"
        "    },\n"
        ")\n"
    )


def test_python_literals_survive_autoescaping_of_string_templates(django_setup, project_export):
    """DB templates / overrides are compiled from strings, which this Jinja
    setup autoescapes; the py filters must still write plain quotes."""
    from engine.services.generation.template_resolver import (
        TemplateResolver,
        model_templates_dir,
    )
    from engine.services.generation.types import TemplateOverride

    bundled = (model_templates_dir("sqlmesh") / "hub_standard.py.j2").read_text(
        encoding="utf-8"
    )
    resolver = TemplateResolver(
        use_db_templates=False,
        framework="sqlmesh",
        templates_override={"sqlmesh": {"hub_standard": TemplateOverride(sql=bundled)}},
    )
    from_string, _ = _render(project_export, resolver)
    from_file, _ = _render(project_export)

    hub = lambda arts: next(a.content for a in arts if a.entity_type == "hub")  # noqa: E731
    assert hub(from_string) == hub(from_file)
    assert "&#39;" not in hub(from_string)


# ---------------------------------------------------------------------------
# Overrides and DB templates reach every SQLMesh entity type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entity_type", sorted(SQLMESH_ENTITY_TYPES))
def test_sqlmesh_override_applies_to_each_entity_type(django_setup, project_export, entity_type):
    from engine.services.generation.template_resolver import TemplateResolver
    from engine.services.generation.types import TemplateOverride

    resolver = TemplateResolver(
        use_db_templates=False,
        framework="sqlmesh",
        templates_override={
            "sqlmesh": {entity_type: TemplateOverride(sql="# override [[ name ]]")}
        },
    )
    artifacts, _ = _render(project_export, resolver)
    by_type = {a.entity_type: a for a in _models(artifacts)}

    overridden = by_type[SQLMESH_ENTITY_TYPES[entity_type]]
    assert overridden.content.startswith("# override ")
    assert overridden.content.endswith("\n")
    for other_entity, artifact_type in SQLMESH_ENTITY_TYPES.items():
        if other_entity != entity_type:
            assert not by_type[artifact_type].content.startswith("# override"), other_entity


def test_dbt_override_does_not_change_sqlmesh_output(django_setup, project_export):
    from engine.services.generation.template_resolver import TemplateResolver
    from engine.services.generation.types import TemplateOverride

    resolver = TemplateResolver(
        use_db_templates=False,
        framework="sqlmesh",
        templates_override={
            "dbt": {entity: TemplateOverride(sql="-- dbt only") for entity in SQLMESH_ENTITY_TYPES}
        },
    )
    with_dbt_override, _ = _render(project_export, resolver)
    plain, _ = _render(project_export)
    assert [a.content for a in _models(with_dbt_override)] == [a.content for a in _models(plain)]


@pytest.mark.django_db
def test_sqlmesh_db_template_is_used_for_sqlmesh_only(django_setup, project_export):
    from engine.models.templates import ModelTemplate
    from engine.services.generation.template_resolver import TemplateResolver

    ModelTemplate.objects.create(
        name="custom v1",
        framework="sqlmesh",
        entity_type="satellite_v1",
        sql_template_content="# db v1 [[ v1_name ]]",
        is_active=True,
    )
    artifacts, _ = _render(
        project_export, TemplateResolver(use_db_templates=True, framework="sqlmesh")
    )
    v1 = next(a for a in artifacts if a.entity_type == "satellite_v1")
    assert v1.content.startswith("# db v1 ")

    dbt_sql, _ = TemplateResolver(use_db_templates=True, framework="dbt").get_templates(
        "satellite_v1"
    )
    assert dbt_sql is not None and "satellite_v1.sql.j2" in (dbt_sql.filename or "")


def test_missing_template_raises_clear_error(django_setup, project_export, tmp_path):
    from engine.services.generation.renderers.sqlmesh_renderer import SQLMeshTemplateError
    from engine.services.generation.template_resolver import TemplateResolver

    empty_root = tmp_path / "templates"
    (empty_root / "sqlmesh" / "models").mkdir(parents=True)
    resolver = TemplateResolver(
        templates_dir=empty_root, use_db_templates=False, framework="sqlmesh"
    )
    with pytest.raises(SQLMeshTemplateError, match="No SQLMesh template"):
        _render(project_export, resolver)


def test_broken_override_raises_clear_error(django_setup, project_export):
    from engine.services.generation.renderers.sqlmesh_renderer import SQLMeshTemplateError
    from engine.services.generation.template_resolver import TemplateResolver
    from engine.services.generation.types import TemplateOverride

    resolver = TemplateResolver(
        use_db_templates=False,
        framework="sqlmesh",
        templates_override={
            "sqlmesh": {"hub_standard": TemplateOverride(sql="[[ name | no_such_filter ]]")}
        },
    )
    with pytest.raises(SQLMeshTemplateError):
        _render(project_export, resolver)


def test_crlf_template_files_render_lf_output(django_setup, project_export, tmp_path):
    """Windows checkouts store the templates with CRLF; output must not change."""
    import shutil

    from engine.services.generation.template_resolver import TEMPLATES_DIR, TemplateResolver

    root = tmp_path / "templates"
    shutil.copytree(TEMPLATES_DIR, root)
    for path in (root / "sqlmesh" / "models").glob("*.py.j2"):
        lf = path.read_bytes().replace(b"\r\n", b"\n")
        path.write_bytes(lf.replace(b"\n", b"\r\n"))

    crlf_resolver = TemplateResolver(templates_dir=root, use_db_templates=False, framework="sqlmesh")
    from_crlf, _ = _render(project_export, crlf_resolver)
    from_bundled, _ = _render(project_export)

    assert [a.content for a in _models(from_crlf)] == [a.content for a in _models(from_bundled)]
    assert not any("\r" in a.content for a in _models(from_crlf))
