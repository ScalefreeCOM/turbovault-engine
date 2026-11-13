"""Snapshot control logic, written as datavault4dbt's control_snap_v1 reads it.

datavault4dbt's log_logic names intervals: daily, weekly, monthly, yearly
(computed from the snapshot's day and the beginning of its week, month and
year). TurboVault's components become those intervals. One logic column
named like the trigger column variable (default is_active) is written as a
mapping; several columns as a list. Components datavault4dbt can't compute
are left out with a warning, and a template copy that still writes component
names gets TPL_003.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


def _logic(column: str, component: str, duration=1, unit="YEAR", forever=False):
    from engine.services.export.models import SnapshotLogicPattern

    return SnapshotLogicPattern(
        column_name=column,
        component=component,
        duration=None if forever else duration,
        unit=None if forever else unit,
        forever=forever,
    )


@pytest.fixture
def generate(django_setup, project_export, tmp_path):
    """Generate one snapshot control with the given logic; return the report."""

    def run(patterns, *, global_vars=None, resolver=None, sdts_alias=None):
        from engine.services.export.models import SnapshotControlDefinition
        from engine.services.generation import DbtProjectGenerator, TemplateResolver
        from engine.services.generation.folder_config import GenerationConfig

        export = project_export.model_copy(
            update={
                "snapshot_controls": [
                    SnapshotControlDefinition(
                        name="control_snap",
                        start_date="2020-01-01",
                        daily_time="08:00:00",
                        sdts_alias=sdts_alias,
                        logic_patterns=patterns,
                    )
                ]
            }
        )
        config = GenerationConfig(global_vars=global_vars or {})
        return DbtProjectGenerator(
            output_path=tmp_path / "dbt",
            template_resolver=resolver or TemplateResolver(use_db_templates=False),
            config=config,
        ).generate(export)

    return run


def _metadata(tmp_path: Path) -> dict:
    sql = (
        tmp_path / "dbt" / "models" / "00_control" / "control_snap_v1.sql"
    ).read_text(encoding="utf-8")
    block = re.search(
        r"\{%- set yaml_metadata -%\}\n(.*?)\{%- endset -%\}", sql, re.DOTALL
    )
    return yaml.safe_load(block.group(1))


def _columns(tmp_path: Path) -> list[str]:
    path = tmp_path / "dbt" / "models" / "00_control" / "control_snap_v1.yml"
    schema = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [column["name"] for column in schema["models"][0]["columns"]]


def test_one_is_active_column_is_a_mapping_of_intervals(generate, tmp_path):
    generate(
        [
            _logic("is_active", "daily", 3, "MONTH"),
            _logic("is_active", "beginning_of_week", 1, "YEAR"),
            _logic("is_active", "beginning_of_month", 5, "YEAR"),
            _logic("is_active", "beginning_of_year", forever=True),
        ]
    )

    assert _metadata(tmp_path)["log_logic"] == {
        "daily": {"duration": 3, "unit": "MONTH"},
        "weekly": {"duration": 1, "unit": "YEAR"},
        "monthly": {"duration": 5, "unit": "YEAR"},
        "yearly": {"forever": True},
    }
    # Each logic column once
    assert _columns(tmp_path) == ["sdts", "is_active"]


def test_several_logic_columns_are_a_list(generate, tmp_path):
    generate(
        [
            _logic("is_recent", "daily", 1, "MONTH"),
            _logic("is_monthly", "beginning_of_month", forever=True),
        ],
        sdts_alias="snapshot_date",
    )

    assert _metadata(tmp_path)["log_logic"] == [
        {"is_recent": {"daily": {"duration": 1, "unit": "MONTH"}}},
        {"is_monthly": {"monthly": {"forever": True}}},
    ]
    assert _metadata(tmp_path)["sdts_alias"] == "snapshot_date"
    assert _columns(tmp_path) == ["snapshot_date", "is_recent", "is_monthly"]


def test_the_trigger_column_variable_names_the_mapping(generate, tmp_path):
    generate(
        [_logic("is_snapshot", "daily", 3, "MONTH")],
        global_vars={"datavault4dbt.snapshot_trigger_column": "is_snapshot"},
    )

    assert _metadata(tmp_path)["log_logic"] == {
        "daily": {"duration": 3, "unit": "MONTH"}
    }


def test_components_without_an_interval_are_left_out(generate, tmp_path):
    report = generate(
        [
            _logic("is_active", "daily", 3, "MONTH"),
            _logic("is_active", "end_of_month", 1, "YEAR"),
            _logic("is_active", "beginning_of_quarter", 1, "YEAR"),
        ]
    )

    assert _metadata(tmp_path)["log_logic"] == {
        "daily": {"duration": 3, "unit": "MONTH"}
    }
    warnings = [w for w in report.warnings if w.code == "SNAP_002"]
    assert len(warnings) == 2
    assert "end_of_month" in warnings[0].message


def test_a_template_writing_components_is_outdated(generate, tmp_path):
    from engine.services.generation import TemplateOverride, TemplateResolver

    old_template = (
        "{%- set yaml_metadata -%}\n"
        "control_snap_v0: [[ v0_name ]]\n"
        "log_logic:\n"
        "[% for pattern in logic_patterns %]\n"
        "    [[ pattern.component ]]:\n"
        "        forever: true\n"
        "[% endfor %]\n"
        "{%- endset -%}\n"
        "{{ datavault4dbt.control_snap_v1(yaml_metadata=yaml_metadata) }}\n"
    )
    resolver = TemplateResolver(
        use_db_templates=False,
        templates_override={
            "dbt": {"snapshot_control_v1": TemplateOverride(sql=old_template)}
        },
    )

    report = generate([_logic("is_active", "beginning_of_month")], resolver=resolver)

    (warning,) = [
        w
        for w in report.warnings
        if w.code == "TPL_003" and w.entity_type == "snapshot_control_v1"
    ]
    assert "beginning_of_month" in warning.message


def test_a_new_projects_default_control_uses_datavault4dbts_intervals(django_setup, db):
    from engine.cli.utils.db_utils import create_default_snapshot_controls
    from engine.models import Project, SnapshotControlLogic

    project = Project.objects.create(name="defaults")

    create_default_snapshot_controls(project)

    rules = SnapshotControlLogic.objects.filter(
        snapshot_control_table__project=project
    ).order_by("snapshot_component")
    assert {r.snapshot_control_logic_column_name for r in rules} == {"is_active"}
    assert {r.snapshot_component for r in rules} == {
        "daily",
        "beginning_of_week",
        "beginning_of_month",
        "beginning_of_year",
    }
