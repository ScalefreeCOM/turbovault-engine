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

    if output_type == "dbt":
        return _write_dbt(artifacts, output_path, options)
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
# dbt
# ---------------------------------------------------------------------------


def _write_dbt(
    artifacts: list[GeneratedArtifact],
    output_path: Path,
    options: GenerationOptions,
) -> tuple[list[GeneratedArtifact], list[Issue]]:
    output_path.mkdir(parents=True, exist_ok=True)
    issues: list[Issue] = []
    written: list[GeneratedArtifact] = []
    seen_paths: set[Path] = set()

    for a in artifacts:
        if not a.path or a.content is None:
            written.append(a)
            continue
        full = output_path / a.path
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

    if options.create_zip:
        zip_artifact, zip_issues = _create_zip(output_path)
        issues.extend(zip_issues)
        if zip_artifact:
            written.append(zip_artifact)

    return written, issues


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
