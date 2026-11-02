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
import re
import textwrap  # used by _render_readme and _MODELS_INIT
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.services.generation.template_resolver import TemplateResolver

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
from engine.services.generation.sqlmesh_dialect import (
    dialect_not_set_warning,
    resolve_driver_requirement,
)
from engine.services.generation.types import (
    ArtifactKind,
    EntityRef,
    GeneratedArtifact,
    GenerationOptions,
    Issue,
)
from engine.services.runtime_config import EngineRuntimeConfig

# ---------------------------------------------------------------------------
# Identifier & value helpers
# ---------------------------------------------------------------------------

# Dialects that fold unquoted identifiers to lowercase (like PostgreSQL).
# Used to normalise source_schema / source_table so quoted names match the DB.
_LOWERCASE_DIALECTS: frozenset[str] = frozenset(
    {"postgres", "duckdb", "trino", "bigquery", "mysql", "spark", "databricks"}
)

# A plain SQL identifier — no parens, spaces, dots or operator characters.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_col_ref(value: str | None) -> bool:
    """Return True when *value* looks like a bare column name, not a SQL expression."""
    return bool(value and _IDENTIFIER_RE.match(value.strip()))


def _is_static_rsrc(value: str | None) -> bool:
    """Return True when *value* is a TurboVault static literal (``!text`` prefix)."""
    return bool(value and value.startswith("!"))


def _normalise_source_id(value: str, dialect: str | None) -> str:
    """Lowercase *value* for case-folding dialects so quoted references match the DB."""
    return value.lower() if dialect in _LOWERCASE_DIALECTS else value



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
    template_resolver: TemplateResolver | None = None,
) -> tuple[list[GeneratedArtifact], list[Issue]]:
    """Generate a SQLMesh project from the export and return artifacts + issues.

    Hubs, links, and satellites are rendered first. The set of entity names that
    actually produced an artifact is then used to filter stage hashkeys/hashdiffs,
    so stages only include hashed columns for entities that will be consumed.
    This filtering is fully dynamic — no hardcoded type lists here.

    Unsupported entity types produce warning Issues and are excluded from the
    artifact list (the generation continues in best-effort style regardless of
    the caller's error_strategy — these are structural limitations, not data
    errors).
    """
    artifacts: list[GeneratedArtifact] = []
    issues: list[Issue] = []

    if not runtime_config.sqlmesh_dialect:
        issues.append(dialect_not_set_warning())

    # --- Scaffold files (always present) ---
    artifacts.extend(_render_scaffold(runtime_config))

    # --- Hubs, links, satellites first ---
    # Collect the names of entities that were actually rendered so stages can
    # filter their hashed_columns to only include those with a consumer.
    rendered_hub_names: set[str] = set()
    rendered_link_names: set[str] = set()
    rendered_sat_names: set[str] = set()

    for hub in export.hubs:
        artifact = _try_render_hub(hub, runtime_config, issues, template_resolver)
        if artifact:
            artifacts.append(artifact)
            rendered_hub_names.add(hub.hub_name)

    for link in export.links:
        artifact = _try_render_link(link, runtime_config, issues, template_resolver)
        if artifact:
            artifacts.append(artifact)
            rendered_link_names.add(link.link_name)

    for sat in export.satellites:
        artifact = _try_render_sat(sat, runtime_config, issues, template_resolver)
        if artifact:
            artifacts.append(artifact)
            rendered_sat_names.add(sat.satellite_name)
            if options.generate_satellite_v1_views and sat.satellite_type == "standard":
                artifacts.append(_render_satellite_v1(sat, runtime_config, template_resolver))

    # --- Stage models (filtered by what was actually rendered above) ---
    for stage in export.stages:
        artifacts.append(
            _render_stage(stage, runtime_config,
                          rendered_hub_names, rendered_link_names, rendered_sat_names,
                          template_resolver, issues)
        )

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


def _try_render_hub(
    hub: HubDefinition,
    runtime_config: EngineRuntimeConfig,
    issues: list[Issue],
    template_resolver: TemplateResolver | None = None,
) -> GeneratedArtifact | None:
    """Render a hub artifact, or append a warning and return None if skipped."""
    if hub.hub_type == "reference":
        issues.append(
            _unsupported_warning(
                hub.hub_name, "hub", hub.group,
                Code.SQLMESH_UNSUPPORTED_REFERENCE_HUB,
                "Reference hubs are not yet supported in SQLMesh output.",
            )
        )
        return None
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
        return None
    return _render_hub(hub, runtime_config, template_resolver)


def _try_render_link(
    link: LinkDefinition,
    runtime_config: EngineRuntimeConfig,
    issues: list[Issue],
    template_resolver: TemplateResolver | None = None,
) -> GeneratedArtifact | None:
    """Render a link artifact, or append a warning and return None if skipped."""
    if link.link_type == "non_historized":
        issues.append(
            _unsupported_warning(
                link.link_name, "link", link.group,
                Code.SQLMESH_UNSUPPORTED_NON_HISTORIZED_LINK,
                "Non-historized links are not yet supported in SQLMesh output.",
            )
        )
        return None
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
        return None
    return _render_link(link, runtime_config, template_resolver)


def _try_render_sat(
    sat: SatelliteDefinition,
    runtime_config: EngineRuntimeConfig,
    issues: list[Issue],
    template_resolver: TemplateResolver | None = None,
) -> GeneratedArtifact | None:
    """Render a satellite artifact, or append a warning and return None if skipped."""
    if sat.satellite_type in _UNSUPPORTED_SAT_TYPES:
        label = _SAT_TYPE_LABELS.get(sat.satellite_type, sat.satellite_type)
        issues.append(
            _unsupported_warning(
                sat.satellite_name, "satellite", sat.group,
                Code.SQLMESH_UNSUPPORTED_SATELLITE_TYPE,
                f"Satellite type '{label}' is not yet supported in SQLMesh output.",
            )
        )
        return None
    return _render_satellite(sat, runtime_config, template_resolver)


# ---------------------------------------------------------------------------
# Scaffold files
# ---------------------------------------------------------------------------


def _render_scaffold(runtime_config: EngineRuntimeConfig) -> list[GeneratedArtifact]:
    """Return the five project-level scaffold files."""
    return [
        _artifact_once("sqlmesh_config", "config.yaml", _render_config_yaml(runtime_config)),
        # Write-once: users may edit the DV settings by hand.
        _artifact_once("sqlmesh_config", "config.json", _render_config_json(runtime_config)),
        _artifact("sqlmesh_config", "models/__init__.py", _MODELS_INIT),
        # Write-once like config.yaml: users may pin versions or add packages.
        _artifact_once(
            "sqlmesh_config", "requirements.txt", _render_requirements(runtime_config)
        ),
        _artifact("sqlmesh_config", "README.md", _render_readme(runtime_config)),
    ]


_MODELS_INIT = textwrap.dedent("""\
    from datavault4sqlmesh import load_dv_config

    load_dv_config()
""")

def _render_requirements(runtime_config: EngineRuntimeConfig) -> str:
    """Render requirements.txt: datavault4sqlmesh plus the dialect's DB driver.

    datavault4sqlmesh only depends on plain ``sqlmesh``; the connection driver
    comes from the matching SQLMesh extra (e.g. ``sqlmesh[postgres]``), or from
    the requirement the user entered for a manually chosen dialect.
    """
    lines = ["datavault4sqlmesh>=0.1.0"]
    driver = resolve_driver_requirement(
        runtime_config.sqlmesh_dialect, runtime_config.sqlmesh_requirement
    )
    if driver:
        lines.append(driver)
    return "\n".join(lines) + "\n"


def _render_config_yaml(runtime_config: EngineRuntimeConfig) -> str:
    """Render a type-agnostic SQLMesh config.yaml hull.

    Only written on first generation — never overwritten. The user fills in
    the connection block for their target platform (postgres, snowflake, etc.).
    Without a dialect, the connection type and model dialect are left as
    commented placeholders for the user to fill in.
    """
    gateway = runtime_config.sqlmesh_gateway
    dialect = runtime_config.sqlmesh_dialect
    start = runtime_config.sqlmesh_start
    if dialect:
        type_line = f"      type: {dialect}\n"
        dialect_line = f"  dialect: {dialect}\n"
    else:
        type_line = "      # type: <your connection type, e.g. postgres>\n"
        dialect_line = "  # dialect: <your SQL dialect, e.g. postgres>  (required)\n"

    return (
        "# SQLMesh project configuration\n"
        "# Fill in the connection details for your target platform and run sqlmesh plan.\n"
        "# Full reference: https://sqlmesh.readthedocs.io/en/stable/reference/configuration/\n"
        "#\n"
        "# Connection examples by type:\n"
        "#   postgres:    type, host, port, user, password, database\n"
        "#   snowflake:   type, account, user, password, database, warehouse, role\n"
        "#   databricks:  type, server_hostname, http_path, access_token, catalog\n"
        "#   trino:       type, host, port, user, catalog\n"
        "#   bigquery:    type, project, dataset\n"
        "#   duckdb:      type: duckdb / database: ':memory:'\n"
        "\n"
        f"gateways:\n"
        f"  {gateway}:\n"
        f"    connection:\n"
        f"{type_line}"
        f"      # add connection parameters here\n"
        f"\n"
        f"default_gateway: {gateway}\n"
        f"\n"
        f"model_defaults:\n"
        f"{dialect_line}"
        f'  start: "{start}"\n'
    )


def _render_config_json(runtime_config: EngineRuntimeConfig) -> str:
    """Render the datavault4sqlmesh config.json DV configuration.

    If the project's default load-date or record-source value is a plain
    column reference (not a SQL expression or a ``!static`` literal),
    ``ldts_alias`` / ``rsrc_alias`` are set automatically so that downstream
    DV models address the column by its real name rather than the DV default
    ``ldts`` / ``rsrc``.  Explicit values in ``output.sqlmesh`` always win.
    Without a dialect the ``dialect`` key is left out for the user to add.
    """
    cfg: dict[str, Any] = {}
    if runtime_config.sqlmesh_dialect:
        cfg["dialect"] = runtime_config.sqlmesh_dialect
    # Merge any user-supplied DV config keys on top of the dialect default.
    cfg.update(runtime_config.sqlmesh_dv_config_dict)

    # Auto-derive ldts_alias when the project load-date is a bare column name.
    if "ldts_alias" not in cfg and _is_col_ref(runtime_config.default_load_date_value):
        cfg["ldts_alias"] = runtime_config.default_load_date_value

    # Auto-derive rsrc_alias when the project record-source is a bare column name
    # (but NOT a !static literal, which is a fixed string, not a column).
    if (
        "rsrc_alias" not in cfg
        and _is_col_ref(runtime_config.default_record_source_value)
        and not _is_static_rsrc(runtime_config.default_record_source_value)
    ):
        cfg["rsrc_alias"] = runtime_config.default_record_source_value

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
    rendered_hub_names: set[str],
    rendered_link_names: set[str],
    rendered_sat_names: set[str],
    template_resolver: TemplateResolver | None = None,
    issues: list[Issue] | None = None,
) -> GeneratedArtifact:
    """Render a stage_model(...) Python file.

    Hashkeys and hashdiffs are filtered to only those whose parent entity was
    actually rendered — derived from the sets passed in, not from hardcoded
    type conditions. If all hashed_columns are filtered out the argument is
    omitted entirely, which is valid for a source-only stage.
    """
    dialect = runtime_config.sqlmesh_dialect
    model_name = f"{runtime_config.stage_schema}.{stage.stage_name}"

    # Normalise source identifiers for case-folding dialects (e.g. postgres).
    # Without this, quoted names like "TPCH_SF1"."Customer" don't match the
    # lowercase table names that PostgreSQL stores by default.
    source_schema = _normalise_source_id(stage.source_schema, dialect)
    source_table = _normalise_source_id(stage.source_table, dialect)

    hashed_columns: dict[str, Any] = {}
    for hk in stage.hashkeys:
        if hk.entity_type == "hub" and hk.target_entity not in rendered_hub_names:
            continue
        if hk.entity_type == "link" and hk.target_entity not in rendered_link_names:
            continue
        # Normalise source column names for case-folding dialects.
        hashed_columns[hk.hashkey_name] = [
            _normalise_source_id(col, dialect) for col in hk.business_key_columns
        ]
    for hd in stage.hashdiffs:
        if hd.satellite_name not in rendered_sat_names:
            continue
        hashed_columns[hd.hashdiff_name] = {
            "is_hashdiff": True,
            "columns": [_normalise_source_id(col, dialect) for col in hd.columns],
        }

    # column_overrides: only needed when the caller wants to declare a precise
    # type for a specific column (e.g. "amount": "DECIMAL(18,2)"). Business key
    # and hashdiff/payload source columns are now auto-inferred from hashed_columns
    # by datavault4sqlmesh's infer_stage_columns(), so they no longer need to be
    # declared here.
    column_overrides = {
        col.column_name: col.datatype
        for col in stage.columns
        if col.datatype
    }

    # derived_columns: renames and transformations the stage must apply.
    # Plain column renames have their source name normalised for case-folding
    # dialects; SQL transformation expressions are passed through unchanged.
    derived_columns: dict[str, str] = {}
    for dc in stage.derived_columns:
        source_expr = dc.transformation or dc.source_column_name
        if dc.transformation:
            derived_columns[dc.target_column_name] = source_expr
        else:
            derived_columns[dc.target_column_name] = _normalise_source_id(source_expr, dialect)

    # Resolve the output column names that datavault4sqlmesh uses for ldts/rsrc
    # (either the DV defaults or whatever ldts_alias/rsrc_alias is configured).
    dv_cfg = runtime_config.sqlmesh_dv_config_dict
    ldts_col = dv_cfg.get("ldts_alias", "ldts")
    rsrc_col = dv_cfg.get("rsrc_alias", "rsrc")

    # load_date handling:
    #   - bare column name  → pass as load_date_col so datavault4sqlmesh reads it
    #   - SQL expression    → inject as a derived column so the stage computes it,
    #                         transpiled to the target dialect (e.g. sysdate() →
    #                         CURRENT_TIMESTAMP on postgres)
    #   - !static literal   → not applicable for load dates; silently ignore
    load_date_col_arg: str | None = None
    if _is_col_ref(stage.load_date):
        load_date_col_arg = stage.load_date
    elif stage.load_date and not _is_static_rsrc(stage.load_date):
        derived_columns[ldts_col] = stage.load_date

    # record_source handling:
    #   - bare column name  → pass as record_source_col (read from source)
    #   - !static literal   → emit as a SQL string constant in derived_columns
    #   - SQL expression    → inject as a derived column expression
    record_source_col_arg: str | None = None
    if _is_col_ref(stage.record_source):
        record_source_col_arg = stage.record_source
    elif stage.record_source and _is_static_rsrc(stage.record_source):
        # Strip the leading '!' and wrap in SQL single quotes: !Customer → 'Customer'
        literal = stage.record_source[1:]
        derived_columns[rsrc_col] = f"'{literal}'"
    elif stage.record_source:
        derived_columns[rsrc_col] = stage.record_source

    path = f"models/stg/{_slug(stage.source_system)}/{stage.stage_name}.py"

    if template_resolver is not None:
        sql_template = template_resolver.get_sql_template("stage")
        if sql_template is not None:
            content = sql_template.render(
                name=model_name,
                stage_name=stage.stage_name,
                source_table=stage.source_table,
                source_schema=stage.source_schema,
                derived_columns=derived_columns,
                hashed_columns=hashed_columns,
                column_overrides=column_overrides,
                stage_schema=runtime_config.stage_schema,
                stage=stage,
            )
            return _artifact("sqlmesh_model", path, content, "stage", stage.stage_name)

    lines = ["from datavault4sqlmesh import stage_model", "", "stage_model("]
    lines.append(f"    name={repr(model_name)},")
    lines.append(f"    source_table={repr(source_table)},")
    lines.append(f"    source_schema={repr(source_schema)},")
    if load_date_col_arg:
        lines.append(f"    load_date_col={repr(load_date_col_arg)},")
    if record_source_col_arg:
        lines.append(f"    record_source_col={repr(record_source_col_arg)},")
    if derived_columns:
        lines.append(f"    derived_columns={_fmt_dict(derived_columns)},")
    if hashed_columns:
        lines.append(f"    hashed_columns={_fmt_hashed_columns(hashed_columns)},")
    if column_overrides:
        lines.append(f"    column_overrides={_fmt_dict(column_overrides)},")
    lines.append(")")
    content = "\n".join(lines) + "\n"
    return _artifact("sqlmesh_model", path, content, "stage", stage.stage_name)


# ---------------------------------------------------------------------------
# Hub models
# ---------------------------------------------------------------------------


def _render_hub(
    hub: HubDefinition,
    runtime_config: EngineRuntimeConfig,
    template_resolver: TemplateResolver | None = None,
) -> GeneratedArtifact:
    """Render a hub_model(...) Python file."""
    model_name = f"{runtime_config.rdv_schema}.{hub.hub_name}"
    hashkey = hub.hashkey.hashkey_name if hub.hashkey else ""
    business_keys = _hub_business_keys(hub)
    is_multi_source = len(hub.source_tables) > 1
    group_slug = _slug(hub.group) if hub.group else "shared"
    path = f"models/rdv/{group_slug}/{hub.hub_name}.py"

    if template_resolver is not None:
        sql_template = template_resolver.get_sql_template("hub_standard")
        if sql_template is not None:
            ctx: dict[str, Any] = {
                "name": model_name,
                "hub_name": hub.hub_name,
                "hashkey": hashkey,
                "business_keys": business_keys,
                "is_multi_source": is_multi_source,
                "stage_schema": runtime_config.stage_schema,
                "rdv_schema": runtime_config.rdv_schema,
                "hub": hub,
            }
            if is_multi_source:
                ctx["sources"] = hub.source_tables
                ctx["rsrc_statics"] = [src.rsrc_static or "" for src in hub.source_tables]
            else:
                src = hub.source_tables[0]
                ctx["source_table"] = src.stage_name
                ctx["rsrc_statics"] = [src.rsrc_static] if src.rsrc_static else []
            content = sql_template.render(**ctx)
            return _artifact("sqlmesh_model", path, content, "hub", hub.hub_name)

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
    return _artifact("sqlmesh_model", path, content, "hub", hub.hub_name)


def _hub_business_keys(hub: HubDefinition) -> list[str]:
    """Return the hub column names for the business key — these are the column
    names that all source stages must expose after any derived-column renames."""
    return hub.business_key_columns


# ---------------------------------------------------------------------------
# Link models
# ---------------------------------------------------------------------------


def _render_link(
    link: LinkDefinition,
    runtime_config: EngineRuntimeConfig,
    template_resolver: TemplateResolver | None = None,
) -> GeneratedArtifact:
    """Render a link_model(...) Python file."""
    model_name = f"{runtime_config.rdv_schema}.{link.link_name}"
    link_hash_key = link.hashkey.hashkey_name
    foreign_hash_keys = link.foreign_hashkeys
    is_multi_source = len(link.source_tables) > 1
    group_slug = _slug(link.group) if link.group else "shared"
    path = f"models/rdv/{group_slug}/{link.link_name}.py"

    if template_resolver is not None:
        sql_template = template_resolver.get_sql_template("link_standard")
        if sql_template is not None:
            ctx: dict[str, Any] = {
                "name": model_name,
                "link_name": link.link_name,
                "link_hash_key": link_hash_key,
                "foreign_hash_keys": foreign_hash_keys,
                "is_multi_source": is_multi_source,
                "stage_schema": runtime_config.stage_schema,
                "rdv_schema": runtime_config.rdv_schema,
                "link": link,
            }
            if is_multi_source:
                ctx["sources"] = link.source_tables
                ctx["rsrc_statics"] = [src.rsrc_static or "" for src in link.source_tables]
            else:
                src = link.source_tables[0]
                ctx["source_table"] = src.stage_name
                ctx["rsrc_statics"] = [src.rsrc_static] if src.rsrc_static else []
            content = sql_template.render(**ctx)
            return _artifact("sqlmesh_model", path, content, "link", link.link_name)

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
    return _artifact("sqlmesh_model", path, content, "link", link.link_name)


# ---------------------------------------------------------------------------
# Satellite models
# ---------------------------------------------------------------------------


def _render_satellite(
    sat: SatelliteDefinition,
    runtime_config: EngineRuntimeConfig,
    template_resolver: TemplateResolver | None = None,
) -> GeneratedArtifact:
    """Render a satellite_model(...) Python file (v0 / standard)."""
    model_name = f"{runtime_config.rdv_schema}.{sat.satellite_name}"
    payload = _sat_payload(sat)
    group_slug = _slug(sat.group) if sat.group else "shared"
    path = f"models/rdv/{group_slug}/{sat.satellite_name}.py"

    if template_resolver is not None:
        sql_template = template_resolver.get_sql_template("satellite_standard")
        if sql_template is not None:
            content = sql_template.render(
                name=model_name,
                satellite_name=sat.satellite_name,
                parent_hash_key=sat.parent_hashkey,
                hash_diff=sat.hashdiff_name,
                payload=payload,
                source_schema=runtime_config.stage_schema,
                source_table=sat.stage_name,
                stage_schema=runtime_config.stage_schema,
                rdv_schema=runtime_config.rdv_schema,
                sat=sat,
            )
            return _artifact("sqlmesh_model", path, content, "satellite", sat.satellite_name)

    lines = ["from datavault4sqlmesh import satellite_model", "", "satellite_model("]
    lines.append(f"    name={repr(model_name)},")
    lines.append(f"    parent_hash_key={repr(sat.parent_hashkey)},")
    lines.append(f"    hash_diff={repr(sat.hashdiff_name)},")
    lines.append(f"    payload={repr(payload)},")
    lines.append(f"    source_schema={repr(runtime_config.stage_schema)},")
    lines.append(f"    source_table={repr(sat.stage_name)},")
    lines.append(")")
    content = "\n".join(lines) + "\n"
    return _artifact("sqlmesh_model", path, content, "satellite", sat.satellite_name)


def _render_satellite_v1(
    sat: SatelliteDefinition,
    runtime_config: EngineRuntimeConfig,
    template_resolver: TemplateResolver | None = None,
) -> GeneratedArtifact:
    """Render a satellite_v1_model(...) Python file (end-dated view)."""
    dialect = runtime_config.sqlmesh_dialect
    v1_name = _derive_v1_name(
        sat.satellite_name,
        runtime_config.satellite_v0_naming,
        runtime_config.satellite_v1_naming,
    )
    model_name = f"{runtime_config.rdv_schema}.{v1_name}"
    payload = _sat_payload(sat)
    group_slug = _slug(sat.group) if sat.group else "shared"
    path = f"models/rdv/{group_slug}/{v1_name}.py"
    # The v0 table is created by SQLMesh using the satellite name; for
    # case-folding dialects (e.g. postgres) it is stored lowercase.
    sat_v0_table = _normalise_source_id(sat.satellite_name, dialect)

    if template_resolver is not None:
        sql_template = template_resolver.get_sql_template("satellite_standard_v1")
        if sql_template is not None:
            content = sql_template.render(
                name=model_name,
                v1_name=v1_name,
                parent_hash_key=sat.parent_hashkey,
                hash_diff=sat.hashdiff_name,
                payload=payload,
                sat_v0_table=sat_v0_table,
                sat_v0_schema=runtime_config.rdv_schema,
                rdv_schema=runtime_config.rdv_schema,
                sat=sat,
            )
            return _artifact("sqlmesh_model", path, content, "satellite_v1", v1_name)

    lines = ["from datavault4sqlmesh import satellite_v1_model", "", "satellite_v1_model("]
    lines.append(f"    name={repr(model_name)},")
    lines.append(f"    parent_hash_key={repr(sat.parent_hashkey)},")
    lines.append(f"    hash_diff={repr(sat.hashdiff_name)},")
    lines.append(f"    payload={repr(payload)},")
    lines.append(f"    sat_v0_table={repr(sat_v0_table)},")
    lines.append(f"    sat_v0_schema={repr(runtime_config.rdv_schema)},")
    lines.append(")")
    content = "\n".join(lines) + "\n"
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


def _artifact_once(kind: str, path: str, content: str) -> GeneratedArtifact:
    """Like _artifact but with overwrite=False — written only if the file does not exist."""
    return GeneratedArtifact(
        kind=kind,  # type: ignore[arg-type]
        path=path,
        size_bytes=len(content.encode("utf-8")),
        content=content,
        overwrite=False,
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
