"""Reading dbt artifacts: locating them, the version check, vars and catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine.services.imports.dbt import artifacts as artifacts_module
from engine.services.imports.dbt.artifacts import (
    DbtArtifactPaths,
    is_dbt_manifest,
    load_artifacts,
)
from engine.services.imports.errors import PipelineAbort

V12 = "https://schemas.getdbt.com/dbt/manifest/v12.json"


def _manifest(version: str = V12, **extra) -> dict:
    return {
        "metadata": {
            "dbt_schema_version": version,
            "project_name": "shop",
            "adapter_type": "snowflake",
        },
        "nodes": {},
        "sources": {},
        **extra,
    }


def _write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_project_directory_is_located(tmp_path):
    _write(tmp_path / "target" / "manifest.json", _manifest())
    _write(tmp_path / "target" / "catalog.json", {"nodes": {}, "sources": {}})
    (tmp_path / "dbt_project.yml").write_text("name: shop\n", encoding="utf-8")
    (tmp_path / "packages.yml").write_text(
        'packages:\n  - package: ScalefreeCOM/datavault4dbt\n    version: [">=1.9.0", "<3.0.0"]\n',
        encoding="utf-8",
    )

    paths = DbtArtifactPaths.locate(tmp_path)
    assert paths.manifest == tmp_path / "target" / "manifest.json"
    assert paths.catalog == tmp_path / "target" / "catalog.json"
    assert paths.dbt_project == tmp_path / "dbt_project.yml"
    artifacts = load_artifacts(paths)
    assert artifacts.project_name == "shop"
    assert artifacts.datavault4dbt_version == ">=1.9.0 <3.0.0"


def test_only_manifest_v12_is_read(tmp_path):
    path = _write(
        tmp_path / "manifest.json",
        _manifest("https://schemas.getdbt.com/dbt/manifest/v11.json"),
    )
    with pytest.raises(PipelineAbort) as caught:
        load_artifacts(DbtArtifactPaths.locate(path))
    assert caught.value.issue.code == "dbt.unsupported_manifest_version"


def test_a_missing_or_broken_manifest_is_reported(tmp_path):
    with pytest.raises(PipelineAbort) as caught:
        load_artifacts(DbtArtifactPaths(manifest=tmp_path / "nope.json"))
    assert caught.value.issue.code == "source.unreadable"

    broken = tmp_path / "manifest.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(PipelineAbort) as caught:
        load_artifacts(DbtArtifactPaths(manifest=broken))
    assert caught.value.issue.code == "source.invalid_json"


def test_too_large_artifacts_are_refused(tmp_path, monkeypatch):
    path = _write(tmp_path / "manifest.json", _manifest())
    monkeypatch.setattr(artifacts_module, "MAX_ARTIFACT_SIZE", 10)
    with pytest.raises(PipelineAbort) as caught:
        load_artifacts(DbtArtifactPaths(manifest=path))
    assert caught.value.issue.code == "dbt.artifact_too_large"


def test_a_manifest_is_told_from_a_turbovault_export(tmp_path):
    manifest = _write(tmp_path / "manifest.json", _manifest())
    export = _write(tmp_path / "export.json", {"project_name": "x", "sources": []})
    assert is_dbt_manifest(manifest)
    assert not is_dbt_manifest(export)


def test_project_vars_include_scoped_and_package_settings(tmp_path):
    path = _write(tmp_path / "manifest.json", _manifest())
    project = tmp_path / "dbt_project.yml"
    project.write_text(
        "name: shop\nvars:\n  entity: customer\n  datavault4dbt.ldts_alias: load_date\n"
        "  shop:\n    scoped: yes\n  other_package:\n    hidden: 1\n",
        encoding="utf-8",
    )
    artifacts = load_artifacts(DbtArtifactPaths(manifest=path, dbt_project=project))
    assert artifacts.project_vars == {
        "entity": "customer",
        "datavault4dbt.ldts_alias": "load_date",
        "scoped": True,
    }


def test_catalog_columns_in_column_order(tmp_path):
    path = _write(tmp_path / "manifest.json", _manifest())
    catalog = _write(
        tmp_path / "catalog.json",
        {
            "nodes": {},
            "sources": {
                "source.shop.crm.customer": {
                    "columns": {
                        "NAME": {"name": "NAME", "type": "TEXT", "index": 2},
                        "ID": {"name": "ID", "type": "NUMBER", "index": 1},
                    }
                }
            },
        },
    )
    artifacts = load_artifacts(DbtArtifactPaths(manifest=path, catalog=catalog))
    assert artifacts.catalog_columns("source.shop.crm.customer") == {
        "ID": "NUMBER",
        "NAME": "TEXT",
    }
    assert artifacts.catalog_columns("model.shop.unknown") is None
