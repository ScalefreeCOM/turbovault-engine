"""The dbt source of the import pipeline: finding a project's artifacts.

A dbt project folder is searched for its manifest, catalog, dbt_project.yml
and package files; the report says what was found and what each missing file
means. Without a manifest, or when nothing maps, nothing is imported. The CLI
tells dbt projects from IRiS folders and TurboVault exports, takes a
project's configured dbt project as the default source, and can run
`dbt parse` on request.
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.django_db

V12 = "https://schemas.getdbt.com/dbt/manifest/v12.json"


def _manifest(version: str = V12, nodes: dict | None = None) -> dict:
    return {
        "metadata": {
            "dbt_schema_version": version,
            "project_name": "shop",
            "adapter_type": "postgres",
            "dbt_version": "1.10.0",
        },
        "nodes": nodes or {},
        "sources": {},
        "macros": {},
        "parent_map": {},
        "child_map": {},
    }


def _write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _dbt_project(root: Path, *, catalog: bool = False, packages: bool = False) -> Path:
    _write(root / "target" / "manifest.json", _manifest())
    (root / "dbt_project.yml").write_text("name: shop\n", encoding="utf-8")
    if catalog:
        _write(root / "target" / "catalog.json", {"nodes": {}, "sources": {}})
    if packages:
        (root / "packages.yml").write_text(
            "packages:\n  - package: ScalefreeCOM/datavault4dbt\n    version: 2.3.0\n",
            encoding="utf-8",
        )
    return root


def _import(project, source, **options):
    from engine.services.imports import ImportOptions, import_metadata

    return import_metadata(
        project=project,
        source=source,
        options=ImportOptions(skip_snapshots=True, **options),
    )


def _codes(report) -> dict[str, str]:
    return {issue.code: issue.severity for issue in report.issues}


@pytest.fixture
def project(django_setup, db):
    from engine.models import Project

    return Project.objects.create(name="shop")


# ---------------------------------------------------------------------------
# Locating the artifacts
# ---------------------------------------------------------------------------


def test_a_project_folder_reports_what_it_found_and_misses(tmp_path):
    from engine.services.imports import DbtSource
    from engine.services.imports.dbt.parser import locate, located_issues

    issues = located_issues(locate(DbtSource(path=_dbt_project(tmp_path))))

    by_code = {issue.code: issue for issue in issues}
    assert by_code["dbt.artifacts_located"].severity == "info"
    assert "manifest.json" in by_code["dbt.artifacts_located"].message
    assert "dbt_project.yml" in by_code["dbt.artifacts_located"].message
    assert by_code["dbt.catalog_missing"].severity == "warning"
    assert "dbt docs generate" in by_code["dbt.catalog_missing"].suggestion
    assert by_code["dbt.packages_missing"].severity == "info"
    assert "dbt.project_file_missing" not in by_code


def test_a_complete_project_folder_misses_nothing(tmp_path):
    from engine.services.imports import DbtSource
    from engine.services.imports.dbt.parser import locate, located_issues

    root = _dbt_project(tmp_path, catalog=True, packages=True)
    issues = located_issues(locate(DbtSource(path=root)))

    assert [issue.code for issue in issues] == ["dbt.artifacts_located"]


def test_a_manifest_in_target_finds_its_project_files(tmp_path):
    from engine.services.imports.dbt.artifacts import DbtArtifactPaths

    root = _dbt_project(tmp_path, catalog=True, packages=True)

    paths = DbtArtifactPaths.locate(root / "target" / "manifest.json")

    assert paths.catalog == root / "target" / "catalog.json"
    assert paths.dbt_project == root / "dbt_project.yml"
    assert paths.packages == (root / "packages.yml",)


def test_explicit_files_win(tmp_path):
    from engine.services.imports import DbtSource
    from engine.services.imports.dbt.parser import locate

    root = _dbt_project(tmp_path, catalog=True)
    other = _write(tmp_path / "elsewhere" / "catalog.json", {"nodes": {}})

    assert locate(DbtSource(path=root, catalog=other)).catalog == other


# ---------------------------------------------------------------------------
# Through the pipeline
# ---------------------------------------------------------------------------


def test_without_a_manifest_nothing_is_imported(project, tmp_path):
    from engine.services.imports import DbtSource

    (tmp_path / "dbt_project.yml").write_text("name: shop\n", encoding="utf-8")

    report = _import(project, DbtSource(path=tmp_path))

    (issue,) = [i for i in report.issues if i.code == "dbt.manifest_missing"]
    assert issue.severity == "error"
    assert "dbt parse" in issue.suggestion
    assert report.status != "success"


def test_an_old_manifest_is_rejected(project, tmp_path):
    from engine.services.imports import DbtSource

    _write(
        tmp_path / "manifest.json",
        _manifest("https://schemas.getdbt.com/dbt/manifest/v11.json"),
    )

    report = _import(project, DbtSource(path=tmp_path / "manifest.json"))

    assert _codes(report)["dbt.unsupported_manifest_version"] == "error"


def test_resources_the_import_skips_are_counted(project, tmp_path):
    from engine.services.imports import DbtSource

    nodes = {
        f"test.shop.t{i}": {"resource_type": "test", "package_name": "shop"}
        for i in range(3)
    }
    nodes["seed.shop.countries"] = {"resource_type": "seed", "package_name": "shop"}
    _write(tmp_path / "target" / "manifest.json", _manifest(nodes=nodes))

    report = _import(project, DbtSource(path=tmp_path), dry_run=True)

    messages = [
        i.message for i in report.issues if i.code == "dbt.resource_not_imported"
    ]
    assert "Not imported: 1 seeds (their data stays in the dbt project)" in messages
    assert "Not imported: 3 tests (TurboVault generates its own)" in messages


def test_a_project_without_models_to_map_changes_nothing(project, tmp_path):
    """replace_all must never read an empty project as "delete everything"."""
    from engine.models import SourceSystem
    from engine.services.imports import DbtSource

    SourceSystem.objects.create(project=project, schema_name="crm", name="CRM")

    report = _import(
        project, DbtSource(path=_dbt_project(tmp_path)), conflict_strategy="replace_all"
    )

    assert _codes(report)["dbt.nothing_to_import"] == "error"
    assert "dbt.artifacts_located" in _codes(report)
    assert SourceSystem.objects.filter(project=project).exists()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_the_cli_tells_the_formats_apart(django_setup, tmp_path):
    from engine.cli.commands.import_cmd import _detect_format

    dbt_root = _dbt_project(tmp_path / "dbt")
    iris_root = tmp_path / "iris"
    iris_root.mkdir()
    export = _write(tmp_path / "export.json", {"project_name": "shop"})

    assert _detect_format(dbt_root) == "dbt"
    assert _detect_format(dbt_root / "target" / "manifest.json") == "dbt"
    assert _detect_format(iris_root) == "iris"
    assert _detect_format(export) == "json"
    assert _detect_format(tmp_path / "metadata.xlsx") == "excel"


def test_the_dbt_project_folder_is_a_project_setting(tmp_path):
    from engine.services.config_schema import TurboVaultConfig
    from engine.services.project_config import write_project_config

    config = TurboVaultConfig(
        project={"name": "shop"}, dbt_project={"path": " '../analytics_dbt' "}
    )
    assert config.dbt_project.path == Path("../analytics_dbt")

    path = tmp_path / "config.yml"
    write_project_config(path, config)
    assert "dbt_project:\n  path: ../analytics_dbt" in path.read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="uses a shell script")
def test_dbt_parse_creates_the_manifest(tmp_path):
    from engine.services.imports.dbt.dbt_cli import run_dbt_parse

    fake_dbt = tmp_path / "bin" / "dbt"
    fake_dbt.parent.mkdir()
    fake_dbt.write_text(
        "#!/bin/sh\nmkdir -p target && echo '{}' > target/manifest.json && echo parsed\n",
        encoding="utf-8",
    )
    fake_dbt.chmod(fake_dbt.stat().st_mode | stat.S_IEXEC)
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    result = run_dbt_parse(project_dir, dbt=str(fake_dbt))

    assert result.ok
    assert "parsed" in result.output
    assert (project_dir / "target" / "manifest.json").is_file()


def test_dbt_parse_without_dbt_explains(tmp_path, monkeypatch):
    from engine.services.imports.dbt import dbt_cli

    monkeypatch.setattr(dbt_cli, "find_dbt", lambda: None)

    result = dbt_cli.run_dbt_parse(tmp_path)

    assert not result.ok
    assert "isn't installed" in result.output


def test_the_wizard_shows_a_dbt_projects_files_once(project, tmp_path, monkeypatch):
    import typer
    from engine.cli.commands import import_cmd

    root = _dbt_project(tmp_path / "dbt")
    # Project, path, descriptions, tags, mode, errors, dry run, snapshots
    answers = iter(
        [project.name, str(root), True, True, "merge", "best-effort", True, False]
    )

    class Prompt:
        def __init__(self, *args, **kwargs):
            pass

        def ask(self):
            return next(answers)

    for prompt in ("select", "path", "confirm"):
        monkeypatch.setattr(import_cmd.questionary, prompt, Prompt)
    shown = []
    show = import_cmd._prepare_dbt_source

    def prepare(source, *, run_parse):
        shown.append(source.path)
        return show(source, run_parse=run_parse)

    monkeypatch.setattr(import_cmd, "_prepare_dbt_source", prepare)

    with pytest.raises(typer.Exit):
        import_cmd.import_metadata_cmd(
            source=None,
            source_format=None,
            catalog=None,
            dbt_project_file=None,
            dbt_parse=False,
            no_descriptions=False,
            no_tags=False,
            apply_settings=None,
            project_name=None,
            mode="merge",
            on_error="best-effort",
            dry_run=False,
            skip_snapshots=False,
            interactive=True,
        )

    assert shown == [root]
