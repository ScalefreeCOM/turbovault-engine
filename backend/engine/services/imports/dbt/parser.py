"""
Parse stage of the dbt project import.

Finds and reads a dbt project's artifacts and reports what it found:
``manifest.json`` is required; ``catalog.json``, ``dbt_project.yml`` and the
package files are optional, and each one missing is reported with what the
import does without it. Mapping the project's models to TurboVault entities
builds on this (``engine.services.imports.dbt.mapping``).
"""

from __future__ import annotations

from engine.services.imports.dbt.artifacts import (
    DbtArtifactPaths,
    DbtArtifacts,
    load_artifacts,
)
from engine.services.imports.domain import DomainModel
from engine.services.imports.errors import Code, PipelineAbort, make_issue
from engine.services.imports.types import DbtSource, Issue, IssueLocation
from engine.services.runtime_config import EngineRuntimeConfig

# Resource types the import reads; every other type is counted and reported.
_IMPORTED_RESOURCES = frozenset({"model", "source"})

# What the report calls each resource type that isn't imported.
_RESOURCE_LABELS = {
    "seed": "seeds (their data stays in the dbt project)",
    "snapshot": "dbt snapshots",
    "test": "tests (TurboVault generates its own)",
    "unit_test": "unit tests",
    "analysis": "analyses",
    "operation": "operations (hooks)",
    "sql_operation": "SQL operations",
    "exposure": "exposures",
    "metric": "metrics",
    "semantic_model": "semantic models",
    "saved_query": "saved queries",
}


def locate(source: DbtSource) -> DbtArtifactPaths:
    """The artifacts of *source*: found in its folder, or given explicitly."""
    return DbtArtifactPaths.locate(
        source.path,
        catalog=source.catalog,
        dbt_project=source.dbt_project,
        packages=source.packages,
    )


def located_issues(paths: DbtArtifactPaths) -> list[Issue]:
    """What was found, and a warning or note for each optional file missing.

    Raises ``PipelineAbort`` when there is no manifest.
    """
    if not paths.manifest.is_file():
        raise PipelineAbort(
            make_issue(
                severity="error",
                code=Code.DBT_MANIFEST_MISSING,
                stage="parse",
                message=f"No manifest.json found ({paths.manifest})",
                location=IssueLocation(file=str(paths.manifest)),
                suggestion=(
                    "Run `dbt parse` in the dbt project to create "
                    "target/manifest.json (no warehouse connection needed), or "
                    "pass the manifest's path."
                ),
            )
        )

    found = [f"manifest.json ({paths.manifest})"]
    if paths.catalog:
        found.append(f"catalog.json ({paths.catalog})")
    if paths.dbt_project:
        found.append(f"dbt_project.yml ({paths.dbt_project})")
    found.extend(f"{path.name} ({path})" for path in paths.packages)
    issues = [
        make_issue(
            severity="info",
            code=Code.DBT_ARTIFACTS_LOCATED,
            stage="parse",
            message="Found " + ", ".join(found),
        )
    ]
    if not paths.catalog:
        issues.append(
            make_issue(
                severity="warning",
                code=Code.DBT_CATALOG_MISSING,
                stage="parse",
                message=(
                    "No catalog.json: column data types come from the YAML "
                    "properties only, and columns without data_type get none"
                ),
                suggestion=(
                    "Run `dbt docs generate` (it queries the warehouse) and "
                    "import again with target/catalog.json."
                ),
            )
        )
    if not paths.dbt_project:
        issues.append(
            make_issue(
                severity="warning",
                code=Code.DBT_PROJECT_FILE_MISSING,
                stage="parse",
                message=(
                    "No dbt_project.yml: var() calls fall back to their "
                    "defaults, the project's dbt_project.yml settings can't come "
                    "back, and folder-level settings can't be told apart from a "
                    "model's own: models store what differs from TurboVault's "
                    "layer settings (a model without a custom schema gets the "
                    "layer's)"
                ),
                suggestion="Pass the project's dbt_project.yml.",
            )
        )
    if not paths.packages:
        issues.append(
            make_issue(
                severity="info",
                code=Code.DBT_PACKAGES_MISSING,
                stage="parse",
                message=(
                    "No packages.yml, dependencies.yml or package-lock.yml: the "
                    "datavault4dbt version is unknown, so both 1.x and 2.x "
                    "argument formats are read"
                ),
            )
        )
    return issues


def resource_issues(
    artifacts: DbtArtifacts, read: frozenset[str] | set[str] = frozenset()
) -> list[Issue]:
    """One note per resource type the import doesn't read, with its count.

    ``read``: the nodes the mapping read, e.g. seeds and snapshots stages
    read as pre-stages; those are named apart.
    """
    pre_stages: dict[str, int] = {}
    for unique_id in read:
        node = artifacts.nodes.get(unique_id) or {}
        resource_type = str(node.get("resource_type") or "")
        if resource_type and resource_type not in _IMPORTED_RESOURCES:
            pre_stages[resource_type] = pre_stages.get(resource_type, 0) + 1
    issues = []
    for resource_type, count in sorted(artifacts.resource_counts().items()):
        if resource_type in _IMPORTED_RESOURCES or not count:
            continue
        label = _RESOURCE_LABELS.get(resource_type, f"{resource_type} nodes")
        used = pre_stages.get(resource_type, 0)
        if used == count:
            continue  # all read as pre-stages
        message = f"Not imported: {count - used} {label}"
        if used:
            message += f" ({used} more read as pre-stages)"
        issues.append(
            make_issue(
                severity="info",
                code=Code.DBT_RESOURCE_NOT_IMPORTED,
                stage="parse",
                message=message,
            )
        )
    return issues


def parse_dbt(
    source: DbtSource, *, runtime_config: EngineRuntimeConfig | None = None
) -> tuple[DomainModel, list[Issue]]:
    """Read a dbt project's artifacts into a domain model.

    Returns the model and the issues found on the way. Raises
    ``PipelineAbort`` when the artifacts are unusable (no manifest, an
    unsupported manifest version, unreadable files). ``runtime_config`` holds
    the project's naming patterns (D22).
    """
    paths = locate(source)
    issues = located_issues(paths)
    artifacts = load_artifacts(paths)

    from engine.services.imports.dbt.mapping import map_project

    domain, mapping_issues, read = map_project(artifacts, source, runtime_config)
    issues.extend(resource_issues(artifacts, read))
    issues.extend(mapping_issues)
    return domain, issues
