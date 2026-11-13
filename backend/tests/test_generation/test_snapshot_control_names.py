"""Snapshot control models: the YAML names them like their SQL files.

A snapshot control may be stored with a _v0/_v1 suffix: the TPC-H workbook
calls it control_snap_v0. Its models are control_snap_v0 and control_snap_v1
all the same, so the YAML must describe those, not control_snap_v0_v0, which
matches no model (dbt warns and the YAML's tests never attach).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def generate_control(django_setup, project_export, tmp_path):
    """Generate the project with one snapshot control named `name`."""

    def run(name: str, resolver=None) -> Path:
        from engine.services.export.models import (
            SnapshotControlDefinition,
            SnapshotLogicPattern,
        )
        from engine.services.generation import DbtProjectGenerator, TemplateResolver

        export = project_export.model_copy(
            update={
                "snapshot_controls": [
                    SnapshotControlDefinition(
                        name=name,
                        start_date="2020-01-01",
                        end_date="2030-12-31",
                        daily_time="08:00:00",
                        logic_patterns=[
                            SnapshotLogicPattern(
                                column_name="is_daily", component="daily", forever=True
                            )
                        ],
                    )
                ]
            }
        )
        output = tmp_path / name
        DbtProjectGenerator(
            output_path=output,
            template_resolver=resolver or TemplateResolver(use_db_templates=False),
        ).generate(export)
        return output / "models" / "00_control"

    return run


def _model_names(path: Path) -> list[str]:
    schema = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [model["name"] for model in schema["models"]]


@pytest.mark.parametrize("name", ["control_snap", "control_snap_v0", "control_snap_v1"])
def test_the_yaml_names_the_models_like_their_files(generate_control, name):
    control = generate_control(name)

    assert sorted(path.name for path in control.iterdir()) == [
        "control_snap_v0.sql",
        "control_snap_v0.yml",
        "control_snap_v1.sql",
        "control_snap_v1.yml",
    ]
    assert _model_names(control / "control_snap_v0.yml") == ["control_snap_v0"]
    assert _model_names(control / "control_snap_v1.yml") == ["control_snap_v1"]


def test_the_logic_model_reads_the_control_table(generate_control):
    sql = (generate_control("control_snap_v0") / "control_snap_v1.sql").read_text(
        encoding="utf-8"
    )

    assert "control_snap_v0: control_snap_v0\n" in sql


def test_a_template_that_appends_the_suffix_to_the_name_still_matches(
    generate_control,
):
    """Workspace copies of the YAML templates still read `[[ name ]]_v0`."""
    from engine.services.generation import TemplateOverride, TemplateResolver

    resolver = TemplateResolver(
        use_db_templates=False,
        templates_override={
            "dbt": {
                "snapshot_control_v0": TemplateOverride(
                    yaml="version: 2\nmodels:\n  - name: [[ name ]]_v0\n"
                )
            }
        },
    )
    control = generate_control("control_snap_v0", resolver)

    assert _model_names(control / "control_snap_v0.yml") == ["control_snap_v0"]
