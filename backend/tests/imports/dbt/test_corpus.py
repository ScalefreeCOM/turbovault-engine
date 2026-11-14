"""Real dbt projects import and generate (opt-in, spec §12).

``TURBOVAULT_DBT_EXAMPLES`` names a folder with a folder per dbt project, each
holding its ``manifest.json`` (and, if there are, ``catalog.json``,
``dbt_project.yml`` and package files). Such projects aren't part of the
repository: they are other people's. For each of them:

- every error the mapping reports is reported on a model;
- the settings it suggests, applied, leave nothing more to suggest;
- with them it imports into a project; importing it again changes nothing;
  the project generates a dbt project;
- with ``TURBOVAULT_DBT`` (see test_round_trip.py), dbt parses that project,
  its pre-stages stubbed: their models stay in the original dbt project.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tests.imports.dbt.test_round_trip import DBT, dbt_parse, profiles_dir

EXAMPLES = os.environ.get("TURBOVAULT_DBT_EXAMPLES")

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        not EXAMPLES,
        reason="set TURBOVAULT_DBT_EXAMPLES to a folder of dbt projects' artifacts",
    ),
]


def _stub_prestages(project: Path) -> None:
    """A model for each pre-stage the generated stages read."""
    models = {path.stem for path in (project / "models").rglob("*.sql")}
    read = {
        match.group(1)
        for path in (project / "models").rglob("*.sql")
        for match in re.finditer(
            r"^source_model: '?(\w+)'?$", path.read_text(encoding="utf-8"), re.M
        )
    }
    stubs = project / "models" / "prestage_stubs"
    stubs.mkdir(exist_ok=True)
    for name in sorted(read - models):
        (stubs / f"{name}.sql").write_text("select 1 as stub\n", encoding="utf-8")


def _projects() -> list[Path]:
    if not EXAMPLES:
        return []
    return sorted(
        folder
        for folder in Path(EXAMPLES).iterdir()
        if (folder / "manifest.json").is_file()
    )


@pytest.mark.parametrize("folder", _projects(), ids=lambda folder: folder.name)
def test_a_dbt_project_imports_and_generates(django_setup, folder, tmp_path):
    from engine.models import Project
    from engine.services.generation import generate
    from engine.services.imports import DbtSource, ImportOptions, import_metadata
    from engine.services.imports.dbt.parser import parse_dbt
    from engine.services.runtime_config import EngineRuntimeConfig

    source = DbtSource(path=folder)
    config = EngineRuntimeConfig(project_name="corpus", dbt_project_name="corpus")

    domain, issues = parse_dbt(source, runtime_config=config)

    assert domain.hubs or domain.links or domain.satellites
    unlocated = [
        issue
        for issue in issues
        if issue.severity == "error" and not (issue.location and issue.location.node_id)
    ]
    assert not unlocated, unlocated[:3]

    config = config.with_settings(
        {key: s.value for key, s in domain.project_settings.suggestions.items()}
    )
    again, _ = parse_dbt(source, runtime_config=config)
    assert again.project_settings.is_empty(), list(again.project_settings.suggestions)

    project = Project.objects.create(name="corpus")
    report = import_metadata(
        project=project, source=source, options=ImportOptions(), runtime_config=config
    )
    assert report.status in ("success", "partial_success"), [
        issue for issue in report.issues if issue.severity == "error"
    ][:3]
    again = import_metadata(
        project=project, source=source, options=ImportOptions(), runtime_config=config
    )
    changed = [e for e in again.plan.entities if e.action not in ("unchanged", "skip")]
    assert not changed, [(e.ref.type, e.ref.name, e.changes[:2]) for e in changed[:3]]
    result = generate(
        project=project,
        output_type="dbt",
        output_path=tmp_path / "dbt",
        runtime_config=config,
    )
    assert result.status in ("success", "partial_success"), [
        (issue.code, issue.message)
        for issue in result.issues
        if issue.severity == "error"
    ][:3]
    if DBT:
        _stub_prestages(tmp_path / "dbt")
        dbt_parse(tmp_path / "dbt", profiles_dir(tmp_path, config.profile_name))
