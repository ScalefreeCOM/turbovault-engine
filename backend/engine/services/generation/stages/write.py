"""
Stage 5 — Write.

Takes the artifacts the render stage produced (with `content` populated
and `path` holding a *relative* path for dbt, or `None` for json/dbml)
and either:

  - **Writes them to disk** when `options.dry_run` is False. For dbt,
    each artifact's relative path is rebased under `output_path`. For
    json/dbml, the single artifact is written to `output_path` as a
    file. Optionally creates a sibling ZIP for dbt when
    `options.create_zip=True`.
  - **Skips writing entirely** when `options.dry_run` is True. The
    artifact list is preserved (so the report still shows the plan);
    `path` is set to None on each artifact, and `content` is stripped
    unless `options.return_content=True`.

Issues raised here use the `write.*` taxonomy.
"""

from __future__ import annotations

import hashlib
import logging
import zipfile
from pathlib import Path

import yaml

from engine.services.generation.dbt_target import (
    PROJECT_FILES,
    defined_twice,
    kept_sources,
    read_record,
    write_record,
)
from engine.services.generation.dbt_target import checksum as file_checksum
from engine.services.generation.errors import Code, make_issue
from engine.services.generation.types import (
    GeneratedArtifact,
    GenerationOptions,
    Issue,
    OutputType,
)

logger = logging.getLogger(__name__)


def write_artifacts(
    *,
    artifacts: list[GeneratedArtifact],
    output_type: OutputType,
    output_path: Path | None,
    options: GenerationOptions,
) -> tuple[list[GeneratedArtifact], list[Issue]]:
    """Persist (or simulate persisting) each rendered artifact.

    Returns the artifact list with `path`, `size_bytes`, `checksum`, and
    `content` finalized, plus any write-stage issues.
    """
    if options.dry_run:
        return _finalize_dry_run(artifacts, options), []

    if output_path is None:
        return (
            artifacts,
            [
                make_issue(
                    severity="error",
                    code=Code.WRITE_IO_ERROR,
                    stage="write",
                    message=(
                        "An output_path is required for a real generation run. "
                        "Use dry_run=True to preview without writing."
                    ),
                )
            ],
        )

    if output_type in ("dbt", "sqlmesh"):
        written, issues = _write_project(artifacts, output_path, options)
        if output_type == "dbt":
            issues.extend(_defined_twice(written, output_path))
        return written, issues
    return _write_single_file(artifacts, output_path, output_type, options)


# ---------------------------------------------------------------------------
# Dry-run path
# ---------------------------------------------------------------------------


def _finalize_dry_run(
    artifacts: list[GeneratedArtifact], options: GenerationOptions
) -> list[GeneratedArtifact]:
    finalized: list[GeneratedArtifact] = []
    for a in artifacts:
        finalized.append(
            a.model_copy(
                update={
                    "path": None,
                    "checksum": None,
                    # Keep content only if the caller asked for it explicitly
                    # (e.g. the Studio metadata editor's preview pane).
                    "content": a.content if options.return_content else None,
                }
            )
        )
    return finalized


# ---------------------------------------------------------------------------
# Multi-file project outputs (dbt and sqlmesh share this writer)
# ---------------------------------------------------------------------------


def _write_project(
    artifacts: list[GeneratedArtifact],
    output_path: Path,
    options: GenerationOptions,
) -> tuple[list[GeneratedArtifact], list[Issue]]:
    # Two files of one path (however cased: dbt, Windows and macOS ignore
    # case) would overwrite each other: nothing is written
    collisions = _colliding_paths(artifacts)
    if collisions:
        return [], [
            make_issue(
                severity="error",
                code=Code.WRITE_PATH_COLLISION,
                stage="write",
                message=(
                    f"{len(paths)} generated files would have the path "
                    + " / ".join(dict.fromkeys(paths))
                    + ", e.g. a model named and placed like a sources file. "
                    "Nothing was written."
                ),
            )
            for paths in collisions
        ]
    output_path.mkdir(parents=True, exist_ok=True)
    output_root = output_path.resolve()
    issues: list[Issue] = []
    written: list[GeneratedArtifact] = []
    seen_paths: set[Path] = set()
    # TurboVault's record of the files it wrote here before (spec D17)
    previous = read_record(output_path)
    record: dict[str, str] = {}
    replaced: list[str] = []

    for a in artifacts:
        if not a.path or a.content is None:
            written.append(a)
            continue
        full = output_path / a.path
        # Names and stored folders are validated before rendering; this
        # catches anything that still points outside the output folder.
        if not full.resolve().is_relative_to(output_root):
            issues.append(
                make_issue(
                    severity="error",
                    code=Code.WRITE_PATH_OUTSIDE_OUTPUT,
                    stage="write",
                    message=f"Refused to write outside the output folder: {a.path}",
                )
            )
            continue
        relative = Path(a.path).as_posix()
        record[relative] = file_checksum(a.content)

        # Write-once artifacts are skipped silently when the file already exists
        # so the user's edits (e.g. filled-in credentials) are never overwritten.
        if not a.overwrite and full.exists():
            record[relative] = file_checksum(full.read_bytes())
            written.append(a.model_copy(update={"path": str(full), "content": None}))
            continue
        if (
            relative not in previous
            and full.is_file()
            and file_checksum(full.read_bytes()) != record[relative]
        ):
            replaced.append(relative)
            issues.extend(_keep_project_sources(full, a.content, output_path))

        if full in seen_paths:
            issues.append(
                make_issue(
                    severity="error",
                    code=Code.WRITE_PATH_COLLISION,
                    stage="write",
                    message=f"Two artifacts targeted the same path: {a.path}",
                )
            )
            continue
        seen_paths.add(full)
        try:
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(a.content, encoding="utf-8")
        except OSError as exc:
            issues.append(
                make_issue(
                    severity="error",
                    code=Code.WRITE_IO_ERROR,
                    stage="write",
                    message=f"Could not write {a.path}: {exc}",
                )
            )
            continue
        size = full.stat().st_size
        checksum = hashlib.sha256(a.content.encode("utf-8")).hexdigest()
        written.append(
            a.model_copy(
                update={
                    "path": str(full),
                    "size_bytes": size,
                    "checksum": checksum,
                    # Strip content from the report unless the caller asked
                    # for it; large dbt projects make the JSON payload heavy.
                    "content": a.content if options.return_content else None,
                }
            )
        )
        # Only config.yaml carries placeholder connection values; other
        # write-once files (e.g. requirements.txt) are complete as generated.
        if not a.overwrite and a.path == "config.yaml":
            issues.append(
                make_issue(
                    severity="warning",
                    code="write.sqlmesh.config_yaml_created",
                    stage="write",
                    message=(
                        f"{a.path} was created with placeholder values — "
                        "fill in your connection details before running sqlmesh plan."
                    ),
                )
            )

    issues.extend(_stale_files(output_path, previous, record, options))
    if replaced:
        issues.append(
            make_issue(
                severity="info",
                code=Code.WRITE_FILES_REPLACED,
                stage="write",
                message=(
                    f"{len(replaced)} file(s) of the folder TurboVault hadn't "
                    "written were replaced by its own: "
                    + ", ".join(replaced[:5])
                    + (", ..." if len(replaced) > 5 else "")
                ),
            )
        )
    # A dbt project whose own dbt_project.yml was kept: noted, so the CLI
    # doesn't ask again next time
    kept = (output_path / PROJECT_FILES[0]).is_file() and PROJECT_FILES[0] not in record
    try:
        write_record(output_path, record, project_files_kept=kept)
    except OSError as exc:
        issues.append(
            make_issue(
                severity="warning",
                code=Code.WRITE_IO_ERROR,
                stage="write",
                message=f"Could not record the generated files: {exc}",
            )
        )

    if options.create_zip:
        zip_artifact, zip_issues = _create_zip(output_path)
        issues.extend(zip_issues)
        if zip_artifact:
            written.append(zip_artifact)

    return written, issues


def _colliding_paths(artifacts: list[GeneratedArtifact]) -> list[list[str]]:
    """The paths more than one artifact would be written to, compared
    case-insensitively, each with the spellings of its artifacts."""
    by_path: dict[str, list[str]] = {}
    for a in artifacts:
        if a.path and a.content is not None:
            path = Path(a.path).as_posix()
            by_path.setdefault(path.casefold(), []).append(path)
    return [paths for paths in by_path.values() if len(paths) > 1]


def _keep_project_sources(full: Path, content: str, output_path: Path) -> list[Issue]:
    """Before TurboVault replaces a dbt project's own sources file, keep the
    source tables it doesn't generate in a file next to it."""
    if full.suffix not in (".yml", ".yaml"):
        return []
    kept = kept_sources(full.read_text(encoding="utf-8", errors="replace"), content)
    if kept is None:
        return []
    candidates = [full.with_name(f"{full.stem}__kept{full.suffix}")] + [
        full.with_name(f"{full.stem}__kept_{n}{full.suffix}") for n in range(2, 100)
    ]
    target = next(path for path in candidates if not path.exists())
    target.write_text(
        f"# Source tables of the dbt project that TurboVault doesn't generate,\n"
        f"# kept when it replaced {full.name}. The project's own file.\n"
        + yaml.safe_dump(
            kept, sort_keys=False, default_flow_style=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
    tables = [
        f"{source['name']}.{table.get('name')}"
        for source in kept["sources"]
        for table in source["tables"]
    ]
    return [
        make_issue(
            severity="info",
            code=Code.WRITE_SOURCES_KEPT,
            stage="write",
            message=(
                f"{full.relative_to(output_path).as_posix()} was the dbt project's: "
                "the source tables TurboVault doesn't generate ("
                + ", ".join(tables[:5])
                + (", ..." if len(tables) > 5 else "")
                + f") are kept in {target.relative_to(output_path).as_posix()}"
            ),
        )
    ]


def _stale_files(
    output_path: Path,
    previous: dict[str, str],
    record: dict[str, str],
    options: GenerationOptions,
) -> list[Issue]:
    """The files TurboVault wrote before and no longer generates.

    Reported; deleted with ``remove_stale_files`` while unchanged since
    TurboVault wrote them. A file changed since stays and leaves the record:
    it is the project's now. Unchanged ones stay in the record until deleted.
    """
    issues: list[Issue] = []
    for relative, written_checksum in sorted(previous.items()):
        if relative in record:
            continue
        full = output_path / relative
        if not full.is_file():
            continue
        if file_checksum(full.read_bytes()) != written_checksum:
            issues.append(
                make_issue(
                    severity="warning",
                    code=Code.WRITE_STALE_FILE_CHANGED,
                    stage="write",
                    message=(
                        f"{relative}: TurboVault no longer generates it, and it "
                        "was changed since TurboVault wrote it, so it stays"
                    ),
                )
            )
            continue
        if options.remove_stale_files:
            full.unlink()
            issues.append(
                make_issue(
                    severity="info",
                    code=Code.WRITE_STALE_FILE_REMOVED,
                    stage="write",
                    message=f"{relative}: TurboVault no longer generates it; deleted",
                )
            )
            continue
        record[relative] = written_checksum
        issues.append(
            make_issue(
                severity="warning",
                code=Code.WRITE_STALE_FILE,
                stage="write",
                message=(
                    f"{relative}: TurboVault generated it before and no longer "
                    "does. Delete it, or generate with --remove-stale-files"
                ),
            )
        )
    return issues


def _defined_twice(written: list[GeneratedArtifact], output_path: Path) -> list[Issue]:
    """Models and sources TurboVault wrote that the dbt project defines again.

    dbt fails on a model, its YAML or a source table defined twice: the user
    removes one of them.
    """
    paths = {
        Path(a.path).relative_to(output_path).as_posix()
        for a in written
        if a.path and Path(a.path).is_absolute() and a.kind != "zip"
    }
    issues = []
    for kind, name, other in defined_twice(output_path, paths):
        what = {
            "model": f"Model '{name}' is defined twice: by TurboVault and in {other}",
            "model_yaml": (
                f"Model '{name}' is described twice: in TurboVault's YAML and "
                f"in {other}"
            ),
            "source": f"Source table '{name}' is defined twice: by TurboVault and in {other}",
        }[kind]
        issues.append(
            make_issue(
                severity="warning",
                code=(
                    Code.WRITE_SOURCE_DEFINED_TWICE
                    if kind == "source"
                    else Code.WRITE_MODEL_DEFINED_TWICE
                ),
                stage="write",
                message=f"{what}. dbt needs one: remove one of them.",
            )
        )
    return issues


def _create_zip(output_path: Path) -> tuple[GeneratedArtifact | None, list[Issue]]:
    zip_path = output_path.with_suffix(".zip")
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file in output_path.rglob("*"):
                if file.is_file():
                    zipf.write(file, file.relative_to(output_path.parent))
    except OSError as exc:
        return None, [
            make_issue(
                severity="error",
                code=Code.WRITE_ZIP_FAILED,
                stage="write",
                message=f"Could not create zip archive: {exc}",
            )
        ]
    size = zip_path.stat().st_size
    return (
        GeneratedArtifact(
            kind="zip",
            path=str(zip_path),
            size_bytes=size,
            checksum=_sha256_file(zip_path),
        ),
        [],
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Single-file outputs (JSON / DBML)
# ---------------------------------------------------------------------------


def _write_single_file(
    artifacts: list[GeneratedArtifact],
    output_path: Path,
    output_type: OutputType,
    options: GenerationOptions,
) -> tuple[list[GeneratedArtifact], list[Issue]]:
    if not artifacts:
        return [], []
    # There should be exactly one artifact for json/dbml.
    artifact = artifacts[0]
    if artifact.content is None:
        return artifacts, []

    # Default extension if the caller passed a directory.
    target = output_path
    if target.suffix == "":
        extension = "json" if output_type == "json" else "dbml"
        target = target / f"export.{extension}"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(artifact.content, encoding="utf-8")
    except OSError as exc:
        return artifacts, [
            make_issue(
                severity="error",
                code=Code.WRITE_IO_ERROR,
                stage="write",
                message=f"Could not write {target}: {exc}",
            )
        ]
    size = target.stat().st_size
    checksum = hashlib.sha256(artifact.content.encode("utf-8")).hexdigest()
    written = [
        artifact.model_copy(
            update={
                "path": str(target),
                "size_bytes": size,
                "checksum": checksum,
                "content": artifact.content if options.return_content else None,
            }
        )
    ]
    return written, []
