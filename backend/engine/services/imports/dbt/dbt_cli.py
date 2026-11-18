"""
Running dbt for a local dbt project: ``dbt parse`` only, on request.

The import reads artifacts; it never runs dbt by itself (spec D21). When a
local project folder has no manifest yet, the CLI can offer to create one
with ``dbt parse``: it renders the project's models without connecting to
the warehouse, but needs dbt-core, the project's adapter and its installed
packages (``dbt deps``) in the environment. The catalog needs ``dbt docs
generate``, which queries the warehouse: that stays with the user.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# How much of dbt's output a failure shows.
_OUTPUT_TAIL = 4000


@dataclass(frozen=True)
class DbtRun:
    """Outcome of a dbt command."""

    ok: bool
    output: str


def find_dbt() -> str | None:
    """The dbt executable on the PATH, or None."""
    return shutil.which("dbt")


def run_dbt_parse(project_dir: Path, *, dbt: str | None = None) -> DbtRun:
    """Run ``dbt parse`` in *project_dir* to write ``target/manifest.json``.

    Uses the user's environment: profiles.yml and installed packages as dbt
    finds them. ``ok`` only when dbt succeeded and the manifest exists.
    """
    executable = dbt or find_dbt()
    if executable is None:
        return DbtRun(
            ok=False,
            output=(
                "dbt isn't installed here. Install dbt-core and the project's "
                "adapter (e.g. dbt-snowflake), or run `dbt parse` where dbt is."
            ),
        )
    project_dir = Path(project_dir)
    try:
        completed = subprocess.run(  # noqa: S603 (the user's own project, opt-in)
            [executable, "parse", "--project-dir", str(project_dir)],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DbtRun(ok=False, output=f"dbt parse didn't run: {exc}")
    output = (completed.stdout or "") + (completed.stderr or "")
    manifest = project_dir / "target" / "manifest.json"
    return DbtRun(
        ok=completed.returncode == 0 and manifest.is_file(),
        output=output[-_OUTPUT_TAIL:],
    )
