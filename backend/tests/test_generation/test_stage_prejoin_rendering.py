"""Rendering tests for the stage template's `prejoined_columns` block.

`src_name`/`src_table` become a dbt `source()` reference. The template used to
emit the *stage's* own source system as `src_name`, ignoring
`prejoin.target_source_system` (added to `PrejoinDefinitionExport` in #198 and
populated by `builder.py::_get_prejoins_for_source_table`). A prejoin whose
target lives in another source system therefore rendered
`source('<stage system>', '<target table>')` — a source that does not exist, so
the model failed to compile. Same-system prejoins were unaffected, which is why
nothing caught it.

This only became reachable once prejoins actually survived import and started
generating; before that `stages[].prejoins[]` was always empty on the
import path.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from engine.services.export.models import ProjectExport

pytestmark = pytest.mark.django_db


STAGE_NAME = "stg__webshop__order"


@pytest.fixture
def prejoin_export(django_setup: object) -> ProjectExport:
    """A stage in source system `webshop` with two prejoins:

    order (webshop) -> kunden (crm)          : crosses source systems
    order (webshop) -> order_status (webshop): stays inside one system

    The cross-system prejoin also has one extraction column with no alias, so
    the alias fallback is covered at the same time.
    """
    from engine.services.export.models import (
        PrejoinCondition,
        PrejoinDefinitionExport,
        PrejoinExtractionColumn,
        ProjectExport,
        SourceColumnDef,
        SourceSystemDef,
        SourceTableDef,
        StageDefinition,
    )

    return ProjectExport(
        project_name="prejoin_render",
        sources=[
            SourceSystemDef(
                name="webshop",
                schema_name="webshop_raw",
                tables=[
                    SourceTableDef(
                        table_name="order",
                        record_source="webshop.order",
                        load_date="load_dt",
                        columns=[
                            SourceColumnDef(column_name="order_id", datatype="STRING"),
                            SourceColumnDef(
                                column_name="kunden_ref", datatype="STRING"
                            ),
                        ],
                    )
                ],
            ),
            SourceSystemDef(
                name="crm",
                schema_name="crm_raw",
                tables=[
                    SourceTableDef(
                        table_name="kunden",
                        record_source="crm.kunden",
                        load_date="load_dt",
                        columns=[
                            SourceColumnDef(
                                column_name="kunden_ref", datatype="STRING"
                            ),
                            SourceColumnDef(column_name="sysid", datatype="STRING"),
                        ],
                    )
                ],
            ),
        ],
        stages=[
            StageDefinition(
                stage_name=STAGE_NAME,
                source_table="order",
                source_schema="webshop_raw",
                source_system="webshop",
                record_source="webshop.order",
                load_date="load_dt",
                multi_active_config=None,
                columns=[
                    SourceColumnDef(column_name="order_id", datatype="STRING"),
                    SourceColumnDef(column_name="kunden_ref", datatype="STRING"),
                ],
                prejoins=[
                    PrejoinDefinitionExport(
                        target_table="kunden",
                        target_source_system="crm",
                        join_conditions=PrejoinCondition(
                            source_columns=["kunden_ref"],
                            target_columns=["kunden_ref"],
                            operator="AND",
                        ),
                        extraction_columns=[
                            # No alias: must fall back to the source column name.
                            PrejoinExtractionColumn(
                                source_column_name="sysid",
                                target_column_alias=None,
                            ),
                            PrejoinExtractionColumn(
                                source_column_name="kundennummer",
                                target_column_alias="kunden_nr",
                            ),
                        ],
                    ),
                    PrejoinDefinitionExport(
                        target_table="order_status",
                        # Omitted on purpose: same-system prejoins leave this
                        # null and must keep using the stage's own system.
                        target_source_system=None,
                        join_conditions=PrejoinCondition(
                            source_columns=["status_code"],
                            target_columns=["code"],
                            operator="AND",
                        ),
                        extraction_columns=[
                            PrejoinExtractionColumn(
                                source_column_name="label",
                                target_column_alias="status_label",
                            )
                        ],
                    ),
                ],
            )
        ],
    )


def _render_stage(project_export: ProjectExport) -> str:
    """Render the stage template the way the generation pipeline does."""
    from engine.services.generation.template_resolver import TemplateResolver

    template = TemplateResolver().get_sql_template("stage")
    assert template is not None
    return template.render(**project_export.stages[0].model_dump())


def _prejoin_block(sql: str, src_table: str) -> str:
    """The `prejoined_columns` entry that targets `src_table`."""
    entries = sql.split("    - extract_columns:")
    for entry in entries[1:]:
        if f"src_table: '{src_table}'" in entry:
            return entry
    raise AssertionError(f"no prejoin block rendered for {src_table!r}:\n{sql}")


def test_cross_system_prejoin_renders_the_targets_source_system(
    prejoin_export: ProjectExport,
) -> None:
    """The regression: `src_name` must be the *target's* system, not the stage's.

    `kunden` lives in `crm`, so the rendered dbt source reference has to be
    source('crm', 'kunden'). Emitting the stage's own `webshop` here produces a
    source that does not exist and the model fails to compile.
    """
    sql = _render_stage(prejoin_export)
    block = _prejoin_block(sql, "kunden")

    assert "src_name: 'crm'" in block
    assert "src_name: 'webshop'" not in block


def test_same_system_prejoin_still_renders_the_stages_source_system(
    prejoin_export: ProjectExport,
) -> None:
    """Backwards compatibility: when `target_source_system` is null the stage's
    own source system remains the correct answer."""
    sql = _render_stage(prejoin_export)
    block = _prejoin_block(sql, "order_status")

    assert "src_name: 'webshop'" in block


def test_prejoin_alias_falls_back_to_the_source_column_name(
    prejoin_export: ProjectExport,
) -> None:
    """`target_column_alias` is optional in the export schema. When it is null
    the template must not emit the literal string `None` as a column alias."""
    sql = _render_stage(prejoin_export)
    block = _prejoin_block(sql, "kunden")

    aliases = block.split("aliases:")[1].split("src_name:")[0]
    assert "- None" not in aliases
    assert "- sysid" in aliases
    assert "- kunden_nr" in aliases


def test_a_stale_database_template_still_wins_over_the_fixed_file(
    prejoin_export: ProjectExport,
) -> None:
    """Operational caveat, pinned so it is not a surprise.

    Since #196 generation prefers database templates (`use_db_templates=True`).
    `populate_templates` seeds those rows *from* the `.j2` files, so the file is
    the single source of truth — but a workspace that seeded before this fix
    holds a stale copy, and the DB copy takes precedence. Fixing the file alone
    does not retroactively fix such a workspace; it needs
    `populate_templates --overwrite`.
    """
    import io

    from django.core.management import call_command
    from engine.models.templates import ModelTemplate
    from engine.services.generation.template_resolver import (
        TEMPLATES_DIR,
        TemplateResolver,
    )

    current = (TEMPLATES_DIR / "sql" / "stage.sql.j2").read_text(encoding="utf-8")
    stale = current.replace(
        "[[ (prejoin.target_source_system or source_system) | lower",
        "[[ source_system | lower",
    )
    assert stale != current, "failed to reconstruct the pre-fix template"

    # Exactly what `populate_templates` would have seeded before the fix:
    # same name and priority, so --overwrite updates this row in place.
    ModelTemplate.objects.create(
        name="stage (SQL)",
        entity_type="stage",
        sql_template_content=stale,
        priority=0,
        is_active=True,
    )

    stage_kwargs = prejoin_export.stages[0].model_dump()

    template = TemplateResolver().get_sql_template("stage")
    assert template is not None
    # The stale DB copy wins: the bug is still visible despite the fixed file.
    assert "src_name: 'webshop'" in _prejoin_block(
        template.render(**stage_kwargs), "kunden"
    )

    # Re-seeding from the fixed file is what repairs such a workspace.
    call_command("populate_templates", "--overwrite", stdout=io.StringIO())

    refreshed = TemplateResolver().get_sql_template("stage")
    assert refreshed is not None
    assert "src_name: 'crm'" in _prejoin_block(
        refreshed.render(**stage_kwargs), "kunden"
    )


def test_generated_stage_model_contains_the_corrected_source_reference(
    django_setup: object,
    prejoin_export: ProjectExport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end through the real pipeline and onto disk, so the assertion
    covers whatever template path generation actually resolves."""
    from engine.models import Project
    from engine.services.generation import generate
    from engine.services.generation import pipeline as pipeline_module
    from engine.services.generation.stages import build as build_module

    def fake_build(**_kwargs: object) -> ProjectExport:
        return prejoin_export

    monkeypatch.setattr(build_module, "build_export", fake_build)
    monkeypatch.setattr(pipeline_module, "build_export", fake_build)

    project = Project.objects.create(name="prejoin_render_e2e")
    out = tmp_path / "dbt_out"
    report = generate(project=project, output_type="dbt", output_path=out)
    assert report.status in ("success", "partial_success"), report

    stage_files = list(out.rglob(f"{STAGE_NAME}.sql"))
    assert stage_files, f"stage model was not generated under {out}"
    sql = stage_files[0].read_text(encoding="utf-8")

    assert "prejoined_columns:" in sql
    assert "src_name: 'crm'" in sql
    assert "- None" not in sql
