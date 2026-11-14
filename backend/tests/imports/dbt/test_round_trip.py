"""Round trip: a generated dbt project, parsed by dbt and imported, generates
the same files again (spec §12).

The TPC-H sample is generated, dbt parses the result (``dbt parse`` writes
``target/manifest.json`` without connecting to a database), the manifest is
imported into a new project with the settings it suggests, and that project
is generated again. Both dbt projects must match file by file.

Opt-in, as it needs dbt:

- ``TURBOVAULT_DBT``: a dbt executable with an adapter (e.g. a virtualenv with
  dbt-core and dbt-postgres; it can be another one than the Engine's);
- ``TURBOVAULT_DATAVAULT4DBT`` (optional): a local datavault4dbt package
  folder; without it ``dbt deps`` downloads the package;
- ``TURBOVAULT_DBT_PROFILES_DIR`` (optional): a profiles folder with a
  ``default`` profile; without it a placeholder Postgres profile is used.
"""

from __future__ import annotations

import difflib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

DBT = os.environ.get("TURBOVAULT_DBT")
DATAVAULT4DBT = os.environ.get("TURBOVAULT_DATAVAULT4DBT")
TPCH = Path(__file__).resolve().parents[4] / "TurboVault_TPCH_Data.db"

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        not DBT, reason="set TURBOVAULT_DBT to a dbt executable to run the round trip"
    ),
]

# dbt parse reads the profile but doesn't connect.
PLACEHOLDER_PROFILE = """{name}:
  target: parse
  outputs:
    parse:
      type: postgres
      host: localhost
      port: 5432
      user: parse_only
      password: "{{{{ env_var('TURBOVAULT_UNUSED_PASSWORD', 'unused') }}}}"
      dbname: parse_only
      schema: public
      threads: 1
"""

# The sample has two Hubs with the hash key HK_NATION_REGION_H: a Link on it
# can't tell them apart in dbt, so the import leaves it out, and with it its
# hash key in the nation stage (where the sample's two test links also share
# one).
KNOWN_DIFFERENCES = {
    "models/30_raw_vault/region/nation_test_bkcc_link.sql",
    "models/30_raw_vault/region/nation_test_bkcc_link.yml",
    "models/20_staging/tpch/stg__tpch__nation.sql",
    "models/20_staging/tpch/stg__tpch__nation.yml",
}


def profiles_dir(tmp_path: Path, profile: str = "default") -> Path:
    """TURBOVAULT_DBT_PROFILES_DIR, else a folder with a placeholder profile."""
    if os.environ.get("TURBOVAULT_DBT_PROFILES_DIR"):
        return Path(os.environ["TURBOVAULT_DBT_PROFILES_DIR"])
    folder = tmp_path / "profiles"
    folder.mkdir(exist_ok=True)
    (folder / "profiles.yml").write_text(
        PLACEHOLDER_PROFILE.format(name=profile), encoding="utf-8"
    )
    return folder


def dbt_parse(project: Path, profiles: Path) -> None:
    """Install the project's packages and parse it (in place)."""
    if DATAVAULT4DBT:
        # Install the local package, then put the project's packages.yml back
        original = (project / "packages.yml").read_text(encoding="utf-8")
        (project / "packages.yml").write_text(
            f"packages:\n  - local: {DATAVAULT4DBT}\n", encoding="utf-8"
        )
        _dbt("deps", cwd=project, profiles=profiles)
        (project / "packages.yml").write_text(original, encoding="utf-8")
        (project / "package-lock.yml").unlink(missing_ok=True)
    else:
        _dbt("deps", cwd=project, profiles=profiles)
    _dbt("parse", cwd=project, profiles=profiles)


def _dbt(*args: str, cwd: Path, profiles: Path) -> None:
    result = subprocess.run(
        [str(DBT), *args, "--profiles-dir", str(profiles)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"dbt {' '.join(args)} failed:\n{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
    )


def _parse(generated: Path, work: Path, profiles: Path) -> Path:
    """A copy of the generated project, parsed by dbt."""
    shutil.copytree(generated, work)
    dbt_parse(work, profiles)
    return work


def _files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.is_file()
    }


def test_a_generated_project_comes_back_as_it_was(django_setup, tmp_path):
    from engine.models import Project
    from engine.services.generation import generate
    from engine.services.imports import (
        DbtSource,
        ImportOptions,
        SqliteSource,
        import_metadata,
    )
    from engine.services.runtime_config import EngineRuntimeConfig

    profiles = profiles_dir(tmp_path)

    original = Project.objects.create(name="tpch")
    report = import_metadata(
        project=original, source=SqliteSource(path=TPCH), options=ImportOptions()
    )
    assert report.status in ("success", "partial_success"), report.issues
    first = tmp_path / "first"
    result = generate(project=original, output_type="dbt", output_path=first)
    assert result.status == "success", result.issues
    parsed = _parse(first, tmp_path / "parsed", profiles)

    # Imported like the CLI does: a dry run, its suggestions, the import
    copy = Project.objects.create(name="tpch_copy")
    config = EngineRuntimeConfig(project_name="tpch_copy", dbt_project_name="tpch_copy")
    preview = import_metadata(
        project=copy,
        source=DbtSource(path=parsed),
        options=ImportOptions(dry_run=True),
        runtime_config=config,
    )
    config = config.with_settings(
        {key: s.value for key, s in preview.project_settings.suggestions.items()}
    )
    report = import_metadata(
        project=copy,
        source=DbtSource(path=parsed),
        options=ImportOptions(),
        runtime_config=config,
    )
    errors = {(i.code, i.message.split(":")[0]) for i in report.issues}
    assert {e for e in errors if e[0].startswith("dbt.link")} == {
        ("dbt.link_hub_ambiguous", "Link 'nation_test_bkcc_link'")
    }
    assert not [i for i in report.issues if i.severity == "error"][1:]
    second = tmp_path / "second"
    result = generate(
        project=copy, output_type="dbt", output_path=second, runtime_config=config
    )
    assert result.status == "success", result.issues

    before, after = _files(first), _files(second)
    differing = {
        name
        for name in before.keys() | after.keys()
        if before.get(name) != after.get(name)
    }
    unexpected = sorted(differing - KNOWN_DIFFERENCES)
    assert not unexpected, "\n".join(
        line
        for name in unexpected[:5]
        for line in difflib.unified_diff(
            (before.get(name) or "").splitlines(),
            (after.get(name) or "").splitlines(),
            f"first/{name}",
            f"second/{name}",
            lineterm="",
        )
    )
