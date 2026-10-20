"""
SQLMesh project renderer for TurboVault Engine.

Generates a ready-to-use SQLMesh project built on datavault4sqlmesh.
Each Data Vault entity becomes a compact Python file that calls the
appropriate datavault4sqlmesh factory function (hub_model, link_model, etc.).

datavault4sqlmesh is NOT imported here — only the generated Python source
files call it. This keeps sqlmesh/datavault4sqlmesh out of the engine's
runtime dependencies.

Supported entities (v1 scope):
  - Stage models       → stage_model(...)
  - Hubs (standard)   → hub_model(...)
  - Links (standard)  → link_model(...)
  - Satellites (standard/v0) → satellite_model(...)
  - Satellites (v1)   → satellite_v1_model(...)

Unsupported entities produce warnings and are skipped:
  - Reference hubs, non-historized links, multi-active / non-historized /
    effectivity / record-tracking / reference satellites, reference tables,
    PITs, snapshot controls.
"""

from __future__ import annotations

import json
import textwrap  # used by _render_readme and _MODELS_INIT
from typing import Any

from engine.services.export.models import (
    HubDefinition,
    HubSourceInfo,
    LinkDefinition,
    LinkSourceInfo,
    ProjectExport,
    SatelliteDefinition,
    StageDefinition,
)
from engine.services.generation.errors import Code, make_issue
from engine.services.generation.types import (
    ArtifactKind,
    EntityRef,
    GeneratedArtifact,
    GenerationOptions,
    Issue,
)
from engine.services.runtime_config import EngineRuntimeConfig

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_UNSUPPORTED_SAT_TYPES = frozenset(
    ("non_historized", "multi_active", "effectivity", "record_tracking", "reference")
)

_SAT_TYPE_LABELS: dict[str, str] = {
    "non_historized": "non-historized satellite",
    "multi_active": "multi-active satellite",
    "effectivity": "effectivity satellite",
    "record_tracking": "record-tracking satellite",
    "reference": "reference satellite",
}


def render_sqlmesh(
    export: ProjectExport,
    runtime_config: EngineRuntimeConfig,
    options: GenerationOptions,
) -> tuple[list[GeneratedArtifact], list[Issue]]:
    """Generate a SQLMesh project from the export and return artifacts + issues.

    Unsupported entity types produce warning Issues and are excluded from the
    artifact list (the generation continues in best-effort style regardless of
    the caller's error_strategy — these are structural limitations, not data
    errors). The caller should set status=partial_success when warnings exist.
    """
    artifacts: list[GeneratedArtifact] = []
    issues: list[Issue] = []

    # --- Scaffold files (always present) ---
    artifacts.extend(_render_scaffold(runtime_config))

    # --- Stage models ---
    for stage in export.stages:
        artifacts.append(_render_stage(stage, runtime_config))

    # --- Hub models ---
    for hub in export.hubs:
        if hub.hub_type == "reference":
            issues.append(
                _unsupported_warning(
                    hub.hub_name,
                    "hub",
                    hub.group,
                    Code.SQLMESH_UNSUPPORTED_REFERENCE_HUB,
                    "Reference hubs are not yet supported in SQLMesh output.",
                )
            )
            continue
        if not hub.source_tables:
            issues.append(
                make_issue(
                    severity="warning",
                    code=Code.SQLMESH_HUB_NO_SOURCES,
                    stage="render",
                    message=f"Hub '{hub.hub_name}' has no source tables and was skipped.",
                    entity=EntityRef(type="hub", name=hub.hub_name, group=hub.group),
                )
            )
            continue
        artifacts.append(_render_hub(hub, runtime_config))

    # --- Link models ---
    for link in export.links:
        if link.link_type == "non_historized":
            issues.append(
                _unsupported_warning(
                    link.link_name,
                    "link",
                    link.group,
                    Code.SQLMESH_UNSUPPORTED_NON_HISTORIZED_LINK,
                    "Non-historized links are not yet supported in SQLMesh output.",
                )
            )
            continue
        if not link.source_tables:
            issues.append(
                make_issue(
                    severity="warning",
                    code=Code.SQLMESH_LINK_NO_SOURCES,
                    stage="render",
                    message=f"Link '{link.link_name}' has no source tables and was skipped.",
                    entity=EntityRef(type="link", name=link.link_name, group=link.group),
                )
            )
            continue
        artifacts.append(_render_link(link, runtime_config))

    # --- Satellite models ---
    for sat in export.satellites:
        if sat.satellite_type in _UNSUPPORTED_SAT_TYPES:
            label = _SAT_TYPE_LABELS.get(sat.satellite_type, sat.satellite_type)
            issues.append(
                _unsupported_warning(
                    sat.satellite_name,
                    "satellite",
                    sat.group,
                    Code.SQLMESH_UNSUPPORTED_SATELLITE_TYPE,
                    f"Satellite type '{label}' is not yet supported in SQLMesh output.",
                )
            )
            continue
        artifacts.append(_render_satellite(sat, runtime_config))
        if options.generate_satellite_v1_views and sat.satellite_type == "standard":
            artifacts.append(_render_satellite_v1(sat, runtime_config))

    # --- Unsupported top-level entities ---
    for rt in export.reference_tables:
        issues.append(
            _unsupported_warning(
                rt.table_name,
                "reference_table",
                rt.group,
                Code.SQLMESH_UNSUPPORTED_REFERENCE_TABLE,
                "Reference tables are not yet supported in SQLMesh output.",
            )
        )
    for pit in export.pits:
        issues.append(
            _unsupported_warning(
                pit.pit_name,
                "pit",
                pit.group,
                Code.SQLMESH_UNSUPPORTED_PIT,
                "PIT structures are not yet supported in SQLMesh output.",
            )
        )
    for sc in export.snapshot_controls:
        issues.append(
            make_issue(
                severity="warning",
                code=Code.SQLMESH_UNSUPPORTED_SNAPSHOT_CONTROL,
                stage="render",
                message=f"Snapshot control '{sc.name}' is not yet supported in SQLMesh output.",
                suggestion="Snapshot controls must be defined manually in the SQLMesh project.",
            )
        )

    return artifacts, issues


# ---------------------------------------------------------------------------
# Scaffold files
# ---------------------------------------------------------------------------


def _render_scaffold(runtime_config: EngineRuntimeConfig) -> list[GeneratedArtifact]:
    """Return the five project-level scaffold files."""
    return [
        _artifact("sqlmesh_config", "config.yaml", _render_config_yaml(runtime_config)),
        _artifact("sqlmesh_config", "config.json", _render_config_json(runtime_config)),
        _artifact("sqlmesh_config", "models/__init__.py", _MODELS_INIT),
        _artifact("sqlmesh_config", "requirements.txt", _REQUIREMENTS),
        _artifact("sqlmesh_config", "README.md", _render_readme(runtime_config)),
    ]


_MODELS_INIT = textwrap.dedent("""\
    from datavault4sqlmesh import load_dv_config

    load_dv_config()
""")

_REQUIREMENTS = "datavault4sqlmesh>=0.1.0\n"


def _render_config_yaml(runtime_config: EngineRuntimeConfig) -> str:
    """Render the SQLMesh config.yaml gateway file."""
    gateway = runtime_config.sqlmesh_gateway
    conn_type = runtime_config.sqlmesh_connection_type
    dialect = runtime_config.sqlmesh_dialect
    start = runtime_config.sqlmesh_start

    if conn_type == "duckdb":
        connection_lines = "      type: duckdb\n      database: :memory:"
    else:
        connection_lines = (
            f"      type: {conn_type}\n"
            "      host: ${SQLMESH_HOST}\n"
            "      user: ${SQLMESH_USER}\n"
            "      password: ${SQLMESH_PASSWORD}\n"
            "      database: ${SQLMESH_DATABASE}"
        )

    return (
        f"gateways:\n"
        f"  {gateway}:\n"
        f"    connection:\n"
        f"{connection_lines}\n"
        f"\n"
        f"default_gateway: {gateway}\n"
        f"\n"
        f"model_defaults:\n"
        f"  dialect: {dialect}\n"
        f'  start: "{start}"\n'
    )


def _render_config_json(runtime_config: EngineRuntimeConfig) -> str:
    """Render the datavault4sqlglot config.json DV configuration."""
    cfg: dict[str, Any] = {"dialect": runtime_config.sqlmesh_dialect}
    # Merge any user-supplied DV config keys on top of the dialect default.
    cfg.update(runtime_config.sqlmesh_dv_config_dict)
    return json.dumps(cfg, indent=4, ensure_ascii=False) + "\n"


def _render_readme(runtime_config: EngineRuntimeConfig) -> str:
    project_name = runtime_config.project_name or "TurboVault"
    return textwrap.dedent(f"""\
        # {project_name} — SQLMesh Project

        Generated by TurboVault Engine using [datavault4sqlmesh](https://github.com/ScalefreeCOM/datavault4sqlmesh).

        > **License notice:** datavault4sqlmesh is released under the AGPL-3.0 license.
        > Review the license terms before using this generated project in a commercial context.

        ## Getting started

        ```bash
        pip install -r requirements.txt
        sqlmesh plan
        ```
    """)


# ---------------------------------------------------------------------------
# Stage models
# ---------------------------------------------------------------------------


def _render_stage(
    stage: StageDefinition,
    runtime_config: EngineRuntimeConfig,
) -> GeneratedArtifact:
    """Render a stage_model(...) Python file."""
    model_name = f"{runtime_config.stage_schema}.{stage.stage_name}"

    hashed_columns: dict[str, Any] = {}
    for hk in stage.hashkeys:
        hashed_columns[hk.hashkey_name] = hk.business_key_columns
    for hd in stage.hashdiffs:
        hashed_columns[hd.hashdiff_name] = {
            "is_hashdiff": True,
            "columns": hd.columns,
        }

    column_overrides = {
        col.column_name: col.datatype
        for col in stage.columns
        if col.datatype
    }

    lines = ["from datavault4sqlmesh import stage_model", "", "stage_model("]
    lines.append(f"    name={repr(model_name)},")
    lines.append(f"    source_table={repr(stage.source_table)},")
    lines.append(f"    source_schema={repr(stage.source_schema)},")
    if hashed_columns:
        lines.append(f"    hashed_columns={_fmt_hashed_columns(hashed_columns)},")
    if column_overrides:
        lines.append(f"    column_overrides={_fmt_dict(column_overrides)},")
    lines.append("    cast_ldts_to_timestamp=True,")
    lines.append(")")
    content = "\n".join(lines) + "\n"

    path = f"models/stg/{_slug(stage.source_system)}/{stage.stage_name}.py"
    return _artifact("sqlmesh_model", path, content, "stage", stage.stage_name)


# ---------------------------------------------------------------------------
# Hub models
# ---------------------------------------------------------------------------


def _render_hub(
    hub: HubDefinition,
    runtime_config: EngineRuntimeConfig,
) -> GeneratedArtifact:
    """Render a hub_model(...) Python file."""
    model_name = f"{runtime_config.rdv_schema}.{hub.hub_name}"
    hashkey = hub.hashkey.hashkey_name if hub.hashkey else ""
    business_keys = _hub_business_keys(hub)

    is_multi_source = len(hub.source_tables) > 1

    lines: list[str]
    if is_multi_source:
        lines = ["from datavault4sqlmesh import hub_model, SourceModel", "", "hub_model("]
    else:
        lines = ["from datavault4sqlmesh import hub_model", "", "hub_model("]

    lines.append(f"    name={repr(model_name)},")
    lines.append(f"    hashkey={repr(hashkey)},")
    lines.append(f"    business_keys={repr(business_keys)},")

    if is_multi_source:
        sources_str = _fmt_source_models(hub.source_tables, runtime_config.stage_schema)
        lines.append(f"    sources={sources_str},")
        rsrc_statics = [src.rsrc_static or "" for src in hub.source_tables]
        lines.append(f"    rsrc_statics={repr(rsrc_statics)},")
    else:
        src = hub.source_tables[0]
        lines.append(f"    source_schema={repr(runtime_config.stage_schema)},")
        lines.append(f"    source_table={repr(src.stage_name)},")
        if src.rsrc_static:
            lines.append(f"    rsrc_statics={repr([src.rsrc_static])},")

    lines.append(")")
    content = "\n".join(lines) + "\n"

    group_slug = _slug(hub.group) if hub.group else "shared"
    path = f"models/rdv/{group_slug}/{hub.hub_name}.py"
    return _artifact("sqlmesh_model", path, content, "hub", hub.hub_name)


def _hub_business_keys(hub: HubDefinition) -> list[str]:
    """Return the source column names used as business keys for this hub."""
    if hub.source_tables and hub.source_tables[0].business_key_columns:
        return hub.source_tables[0].business_key_columns
    return hub.business_key_columns


# ---------------------------------------------------------------------------
# Link models
# ---------------------------------------------------------------------------


def _render_link(
    link: LinkDefinition,
    runtime_config: EngineRuntimeConfig,
) -> GeneratedArtifact:
    """Render a link_model(...) Python file."""
    model_name = f"{runtime_config.rdv_schema}.{link.link_name}"
    link_hash_key = link.hashkey.hashkey_name
    foreign_hash_keys = link.foreign_hashkeys

    is_multi_source = len(link.source_tables) > 1

    lines: list[str]
    if is_multi_source:
        lines = ["from datavault4sqlmesh import link_model, SourceModel", "", "link_model("]
    else:
        lines = ["from datavault4sqlmesh import link_model", "", "link_model("]

    lines.append(f"    name={repr(model_name)},")
    lines.append(f"    link_hash_key={repr(link_hash_key)},")
    lines.append(f"    foreign_hash_keys={repr(foreign_hash_keys)},")

    if is_multi_source:
        sources_str = _fmt_source_models(link.source_tables, runtime_config.stage_schema)
        lines.append(f"    sources={sources_str},")
        rsrc_statics = [src.rsrc_static or "" for src in link.source_tables]
        lines.append(f"    rsrc_statics={repr(rsrc_statics)},")
    else:
        src = link.source_tables[0]
        lines.append(f"    source_schema={repr(runtime_config.stage_schema)},")
        lines.append(f"    source_table={repr(src.stage_name)},")
        if src.rsrc_static:
            lines.append(f"    rsrc_statics={repr([src.rsrc_static])},")

    lines.append(")")
    content = "\n".join(lines) + "\n"

    group_slug = _slug(link.group) if link.group else "shared"
    path = f"models/rdv/{group_slug}/{link.link_name}.py"
    return _artifact("sqlmesh_model", path, content, "link", link.link_name)


# ---------------------------------------------------------------------------
# Satellite models
# ---------------------------------------------------------------------------


def _render_satellite(
    sat: SatelliteDefinition,
    runtime_config: EngineRuntimeConfig,
) -> GeneratedArtifact:
    """Render a satellite_model(...) Python file (v0 / standard)."""
    model_name = f"{runtime_config.rdv_schema}.{sat.satellite_name}"
    payload = _sat_payload(sat)

    lines = ["from datavault4sqlmesh import satellite_model", "", "satellite_model("]
    lines.append(f"    name={repr(model_name)},")
    lines.append(f"    parent_hash_key={repr(sat.parent_hashkey)},")
    lines.append(f"    hash_diff={repr(sat.hashdiff_name)},")
    lines.append(f"    payload={repr(payload)},")
    lines.append(f"    source_schema={repr(runtime_config.stage_schema)},")
    lines.append(f"    source_table={repr(sat.stage_name)},")
    lines.append(")")
    content = "\n".join(lines) + "\n"

    group_slug = _slug(sat.group) if sat.group else "shared"
    path = f"models/rdv/{group_slug}/{sat.satellite_name}.py"
    return _artifact("sqlmesh_model", path, content, "satellite", sat.satellite_name)


def _render_satellite_v1(
    sat: SatelliteDefinition,
    runtime_config: EngineRuntimeConfig,
) -> GeneratedArtifact:
    """Render a satellite_v1_model(...) Python file (end-dated view)."""
    v1_name = _derive_v1_name(
        sat.satellite_name,
        runtime_config.satellite_v0_naming,
        runtime_config.satellite_v1_naming,
    )
    model_name = f"{runtime_config.rdv_schema}.{v1_name}"
    payload = _sat_payload(sat)

    lines = ["from datavault4sqlmesh import satellite_v1_model", "", "satellite_v1_model("]
    lines.append(f"    name={repr(model_name)},")
    lines.append(f"    parent_hash_key={repr(sat.parent_hashkey)},")
    lines.append(f"    hash_diff={repr(sat.hashdiff_name)},")
    lines.append(f"    payload={repr(payload)},")
    lines.append(f"    sat_v0_table={repr(sat.satellite_name)},")
    lines.append(f"    sat_v0_schema={repr(runtime_config.rdv_schema)},")
    lines.append(")")
    content = "\n".join(lines) + "\n"

    group_slug = _slug(sat.group) if sat.group else "shared"
    path = f"models/rdv/{group_slug}/{v1_name}.py"
    return _artifact("sqlmesh_model", path, content, "satellite_v1", v1_name)


def _sat_payload(sat: SatelliteDefinition) -> list[str]:
    """Return the ordered list of payload column names for a satellite."""
    return [
        col.target_column_name or col.source_column
        for col in sat.columns
        if not col.is_multi_active_key
    ]


def _derive_v1_name(sat_v0_name: str, v0_naming: str, v1_naming: str) -> str:
    """Derive the v1 satellite model name from the v0 name and naming patterns.

    Both patterns use [[ satellite_name ]] as the placeholder for the base
    satellite name. The base name is recovered by stripping the v0 prefix/suffix
    from `sat_v0_name`, then the v1 pattern is applied.
    """
    placeholder = "[[ satellite_name ]]"
    if placeholder not in v0_naming or placeholder not in v1_naming:
        return f"{sat_v0_name}_v1"

    v0_prefix, v0_suffix = v0_naming.split(placeholder, 1)
    v1_prefix, v1_suffix = v1_naming.split(placeholder, 1)

    base = sat_v0_name
    if v0_prefix and base.startswith(v0_prefix):
        base = base[len(v0_prefix):]
    if v0_suffix and base.endswith(v0_suffix):
        base = base[: -len(v0_suffix)]

    return v1_prefix + base + v1_suffix


# ---------------------------------------------------------------------------
# Code generation helpers
# ---------------------------------------------------------------------------


def _fmt_hashed_columns(hashed_columns: dict[str, Any]) -> str:
    """Format the hashed_columns dict for Python source — multi-line."""
    lines = ["{"]
    for key, value in hashed_columns.items():
        if isinstance(value, list):
            inner = ", ".join(repr(v) for v in value)
            lines.append(f"        {repr(key)}: [{inner}],")
        elif isinstance(value, dict):
            inner_lines = ["{"]
            for ik, iv in value.items():
                if isinstance(iv, list):
                    iv_str = "[" + ", ".join(repr(v) for v in iv) + "]"
                else:
                    iv_str = repr(iv)
                inner_lines.append(f"            {repr(ik)}: {iv_str},")
            inner_lines.append("        }")
            lines.append(f"        {repr(key)}: " + "\n".join(inner_lines) + ",")
        else:
            lines.append(f"        {repr(key)}: {repr(value)},")
    lines.append("    }")
    return "\n".join(lines)


def _fmt_dict(d: dict[str, str]) -> str:
    """Format a flat str→str dict for Python source — multi-line."""
    if not d:
        return "{}"
    lines = ["{"]
    for k, v in d.items():
        lines.append(f"        {repr(k)}: {repr(v)},")
    lines.append("    }")
    return "\n".join(lines)


def _fmt_source_models(
    sources: list[HubSourceInfo] | list[LinkSourceInfo],
    stage_schema: str,
) -> str:
    """Format a list of SourceModel(...) calls for Python source."""
    items = [
        f"SourceModel(schema_name={repr(stage_schema)}, table_name={repr(src.stage_name)})"
        for src in sources
    ]
    if len(items) == 1:
        return f"[{items[0]}]"
    inner = ",\n        ".join(items)
    return f"[\n        {inner},\n    ]"


def _slug(name: str) -> str:
    """Convert a name to a filesystem-safe slug."""
    return name.lower().replace(" ", "_").replace("-", "_")


# ---------------------------------------------------------------------------
# Artifact + issue factories
# ---------------------------------------------------------------------------


def _artifact(
    kind: str,
    path: str,
    content: str,
    entity_type: str | None = None,
    entity_name: str | None = None,
) -> GeneratedArtifact:
    return GeneratedArtifact(
        kind=kind,  # type: ignore[arg-type]
        entity_type=entity_type,
        entity_name=entity_name,
        path=path,
        size_bytes=len(content.encode("utf-8")),
        content=content,
    )


def _unsupported_warning(
    name: str,
    entity_type: str,
    group: str | None,
    code: str,
    message: str,
) -> Issue:
    return make_issue(
        severity="warning",
        code=code,
        stage="render",
        message=message,
        entity=EntityRef(type=entity_type, name=name, group=group),
        suggestion=(
            "This entity type will be supported in a future release. "
            "Track progress at https://github.com/ScalefreeCOM/turbovault4dbt."
        ),
    )
