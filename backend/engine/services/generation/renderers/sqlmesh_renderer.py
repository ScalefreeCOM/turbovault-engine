"""
SQLMesh project renderer for TurboVault Engine.

Generates a ready-to-use SQLMesh project built on datavault4sqlmesh.
Each Data Vault entity becomes a compact Python file that calls the
appropriate datavault4sqlmesh factory function (hub_model, link_model, etc.).

The model files are rendered from SQLMesh templates resolved per entity type
by a ``TemplateResolver(framework="sqlmesh")``: a per-run override, a DB
template, or the bundled default in ``templates/sqlmesh/models/``. This module
computes the template context; the templates own the generated code.

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
  - Pre-stages, with the stages that read them and the entities loaded from
    those stages (see ``sqlmesh_prestages``).
"""

from __future__ import annotations

import json
import re
import textwrap  # used by _render_readme and _MODELS_INIT
from typing import Any, NamedTuple

from jinja2 import TemplateError

from engine.services.export.models import (
    HubColumnMapping,
    HubDefinition,
    HubSourceInfo,
    LinkDefinition,
    LinkSourceInfo,
    ProjectExport,
    SatelliteDefinition,
    StageDefinition,
)
from engine.services.generation.errors import Code, make_issue
from engine.services.generation.renderers.sqlmesh_prejoins import (
    PrejoinSkips,
    StagePrejoinGaps,
    plan_prejoin_skips,
    prejoin_dependent_warning,
)
from engine.services.generation.renderers.sqlmesh_prestages import (
    plan_prestage_skips,
    prestage_dependent_warning,
)
from engine.services.generation.sqlmesh_dialect import (
    dialect_not_set_warning,
    resolve_driver_requirement,
)
from engine.services.generation.template_resolver import TemplateResolver
from engine.services.generation.types import (
    ArtifactKind,
    EntityRef,
    GeneratedArtifact,
    GenerationOptions,
    Issue,
)
from engine.services.runtime_config import EngineRuntimeConfig


class SQLMeshTemplateError(Exception):
    """A SQLMesh model template is missing or failed to render."""


class _HubKeyMapping(NamedTuple):
    """A hub column mapping together with the hub it belongs to."""

    hub_name: str
    mapping: HubColumnMapping


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

    Without a *template_resolver*, the bundled SQLMesh templates are used
    (no DB templates, no overrides).
    """
    if template_resolver is None:
        template_resolver = TemplateResolver(
            use_db_templates=False, framework="sqlmesh"
        )
    artifacts: list[GeneratedArtifact] = []
    issues: list[Issue] = []

    if not runtime_config.sqlmesh_dialect:
        issues.append(dialect_not_set_warning())

    # --- Scaffold files (always present) ---
    artifacts.extend(_render_scaffold(runtime_config))

    # datavault4sqlmesh has no prejoin support: work out up front which hash
    # keys and entities read prejoined columns, so they can be left out.
    prejoin_skips = plan_prejoin_skips(export)
    issues.extend(prejoin_skips.issues)

    # Nor pre-stages: stages that read one, and the entities loaded from
    # those stages, are left out.
    prestage_skips = plan_prestage_skips(export)
    issues.extend(prestage_skips.issues)

    # --- Hubs, links, satellites first ---
    # Collect the names of entities that were actually rendered so stages can
    # filter their hashed_columns to only include those with a consumer.
    rendered_hub_names: set[str] = set()
    rendered_link_names: set[str] = set()
    rendered_sat_names: set[str] = set()

    for hub in export.hubs:
        prestage_stage = prestage_skips.stage_of("hub", hub.hub_name)
        if prestage_stage:
            issues.append(
                prestage_dependent_warning(
                    "hub", hub.hub_name, hub.group, prestage_stage
                )
            )
            continue
        artifact = _try_render_hub(
            hub, runtime_config, issues, template_resolver, prejoin_skips
        )
        if artifact:
            artifacts.append(artifact)
            rendered_hub_names.add(hub.hub_name)

    for link in export.links:
        prestage_stage = prestage_skips.stage_of("link", link.link_name)
        if prestage_stage:
            issues.append(
                prestage_dependent_warning(
                    "link", link.link_name, link.group, prestage_stage
                )
            )
            continue
        artifact = _try_render_link(
            link,
            runtime_config,
            issues,
            template_resolver,
            rendered_hub_names,
            prejoin_skips,
        )
        if artifact:
            artifacts.append(artifact)
            rendered_link_names.add(link.link_name)

    for sat in export.satellites:
        prestage_stage = prestage_skips.stage_of("satellite", sat.satellite_name)
        if prestage_stage:
            issues.append(
                prestage_dependent_warning(
                    "satellite", sat.satellite_name, sat.group, prestage_stage
                )
            )
            continue
        artifact = _try_render_sat(
            sat,
            runtime_config,
            issues,
            template_resolver,
            rendered_hub_names,
            rendered_link_names,
            prejoin_skips,
        )
        if artifact:
            artifacts.append(artifact)
            rendered_sat_names.add(sat.satellite_name)
            if options.generate_satellite_v1_views and sat.satellite_type == "standard":
                artifacts.append(
                    _render_satellite_v1(sat, runtime_config, template_resolver)
                )

    # --- Stage models (filtered by what was actually rendered above) ---
    hub_key_mappings = _hub_key_mappings_by_stage(export.hubs, rendered_hub_names)
    for stage in export.stages:
        if stage.stage_name in prestage_skips.stages:
            continue
        artifacts.append(
            _render_stage(
                stage,
                runtime_config,
                rendered_hub_names,
                rendered_link_names,
                rendered_sat_names,
                template_resolver,
                issues,
                hub_key_mappings=hub_key_mappings.get(stage.stage_name, []),
                prejoin_gaps=prejoin_skips.for_stage(stage.stage_name),
            )
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
    template_resolver: TemplateResolver,
    prejoin_skips: PrejoinSkips | None = None,
) -> GeneratedArtifact | None:
    """Render a hub artifact, or append a warning and return None if skipped."""
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
    if prejoin_skips and hub.hub_name in prejoin_skips.hubs:
        issues.append(
            prejoin_dependent_warning(
                "hub", hub.hub_name, hub.group, prejoin_skips.hubs[hub.hub_name]
            )
        )
        return None
    return _render_hub(hub, runtime_config, template_resolver)


def _try_render_link(
    link: LinkDefinition,
    runtime_config: EngineRuntimeConfig,
    issues: list[Issue],
    template_resolver: TemplateResolver,
    rendered_hub_names: set[str],
    prejoin_skips: PrejoinSkips | None = None,
) -> GeneratedArtifact | None:
    """Render a link artifact, or append a warning and return None if skipped.

    A link is skipped when its type is unsupported, it has no sources, it
    reads prejoined columns, or one of its hubs was not rendered: the stage
    then drops that hub's hash key, so the link would read a column that
    doesn't exist.
    """
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
    if prejoin_skips and link.link_name in prejoin_skips.links:
        issues.append(
            prejoin_dependent_warning(
                "link", link.link_name, link.group, prejoin_skips.links[link.link_name]
            )
        )
        return None
    skipped_hubs = sorted(
        {ref.hub_name for ref in link.hub_references} - rendered_hub_names
    )
    if skipped_hubs:
        hub_list = ", ".join(f"'{name}'" for name in skipped_hubs)
        issues.append(
            make_issue(
                severity="warning",
                code=Code.SQLMESH_LINK_HUB_SKIPPED,
                stage="render",
                message=(
                    f"Link '{link.link_name}' was skipped because its hub(s) "
                    f"{hub_list} are not rendered in SQLMesh output."
                ),
                entity=EntityRef(type="link", name=link.link_name, group=link.group),
                suggestion=f"See the warning for hub(s) {hub_list} for why they were skipped.",
            )
        )
        return None
    return _render_link(link, runtime_config, template_resolver)


def _try_render_sat(
    sat: SatelliteDefinition,
    runtime_config: EngineRuntimeConfig,
    issues: list[Issue],
    template_resolver: TemplateResolver,
    rendered_hub_names: set[str],
    rendered_link_names: set[str],
    prejoin_skips: PrejoinSkips | None = None,
) -> GeneratedArtifact | None:
    """Render a satellite artifact, or append a warning and return None if skipped.

    A satellite is skipped when its type is unsupported, or when its parent hub
    or link was not rendered (reference hub, non-historized link, no sources):
    the parent's hash key is then filtered out of the stage, so the satellite
    would read a column that doesn't exist. Satellites that read prejoined
    columns are skipped too.
    """
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
        return None
    if prejoin_skips and sat.satellite_name in prejoin_skips.satellites:
        issues.append(
            prejoin_dependent_warning(
                "satellite",
                sat.satellite_name,
                sat.group,
                prejoin_skips.satellites[sat.satellite_name],
            )
        )
        return None
    if not _parent_rendered(sat, rendered_hub_names, rendered_link_names):
        issues.append(
            make_issue(
                severity="warning",
                code=Code.SQLMESH_SATELLITE_PARENT_SKIPPED,
                stage="render",
                message=(
                    f"Satellite '{sat.satellite_name}' was skipped because its parent "
                    f"{sat.parent_entity_type} '{sat.parent_entity}' is not rendered "
                    "in SQLMesh output."
                ),
                entity=EntityRef(
                    type="satellite", name=sat.satellite_name, group=sat.group
                ),
                suggestion=(
                    f"See the warning for {sat.parent_entity_type} "
                    f"'{sat.parent_entity}' for why it was skipped."
                ),
            )
        )
        return None
    return _render_satellite(sat, runtime_config, template_resolver)


def _parent_rendered(
    sat: SatelliteDefinition,
    rendered_hub_names: set[str],
    rendered_link_names: set[str],
) -> bool:
    """Return True when the satellite's parent hub or link produced a model."""
    if sat.parent_entity_type == "hub":
        return sat.parent_entity in rendered_hub_names
    if sat.parent_entity_type == "link":
        return sat.parent_entity in rendered_link_names
    return sat.parent_entity in rendered_hub_names | rendered_link_names


# ---------------------------------------------------------------------------
# Scaffold files
# ---------------------------------------------------------------------------


def _render_scaffold(runtime_config: EngineRuntimeConfig) -> list[GeneratedArtifact]:
    """Return the five project-level scaffold files."""
    return [
        _artifact_once(
            "sqlmesh_config", "config.yaml", _render_config_yaml(runtime_config)
        ),
        # Write-once: users may edit the DV settings by hand.
        _artifact_once(
            "sqlmesh_config", "config.json", _render_config_json(runtime_config)
        ),
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
    """Render the datavault4sqlmesh config.json DV configuration."""
    cfg = _effective_dv_config(runtime_config)
    return json.dumps(cfg, indent=4, ensure_ascii=False) + "\n"


def _effective_dv_config(runtime_config: EngineRuntimeConfig) -> dict[str, Any]:
    """Return the datavault4sqlmesh DV config as written to config.json.

    Single source of truth for config.json and for the ldts/rsrc column
    names stage models emit: hubs, links and satellites read the columns
    named ``ldts_alias`` / ``rsrc_alias`` from the stage, so both must agree.

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

    return cfg


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
    template_resolver: TemplateResolver,
    issues: list[Issue] | None = None,
    hub_key_mappings: list[_HubKeyMapping] | None = None,
    prejoin_gaps: StagePrejoinGaps | None = None,
) -> GeneratedArtifact:
    """Render a stage_model(...) Python file.

    Hashkeys and hashdiffs are filtered to only those whose parent entity was
    actually rendered — derived from the sets passed in, not from hardcoded
    type conditions. If all hashed_columns are filtered out the argument is
    omitted entirely, which is valid for a source-only stage.

    *hub_key_mappings* are the column mappings of the rendered hubs this stage
    loads; renamed business keys become derived columns (see
    ``_add_hub_key_renames``). Conflicting renames are appended to *issues*
    as errors.

    *prejoin_gaps* lists what the stage can't provide because of prejoins
    (unsupported in SQLMesh output): those hash keys, hash diffs and derived
    columns are left out so the stage itself stays valid.
    """
    gaps = prejoin_gaps or StagePrejoinGaps()
    dialect = runtime_config.sqlmesh_dialect
    model_name = f"{runtime_config.stage_schema}.{stage.stage_name}"

    # Normalise source identifiers for case-folding dialects (e.g. postgres).
    # Without this, quoted names like "TPCH_SF1"."Customer" don't match the
    # lowercase table names that PostgreSQL stores by default.
    source_schema = _normalise_source_id(stage.source_schema, dialect)
    source_table = _normalise_source_id(stage.source_table, dialect)

    hashed_columns: dict[str, Any] = {}
    for hk in stage.hashkeys:
        if hk.hashkey_name in gaps.hashkeys:
            continue
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
        if hd.satellite_name in gaps.hashdiff_satellites:
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
        col.column_name: col.datatype for col in stage.columns if col.datatype
    }

    # derived_columns: renames and transformations the stage must apply.
    # Plain column renames have their source name normalised for case-folding
    # dialects; SQL transformation expressions are passed through unchanged.
    derived_columns: dict[str, str] = {}
    for dc in stage.derived_columns:
        if gaps.uses([dc.target_column_name]):
            continue  # computed from a prejoined column
        source_expr = dc.transformation or dc.source_column_name
        if dc.transformation:
            derived_columns[dc.target_column_name] = source_expr
        else:
            derived_columns[dc.target_column_name] = _normalise_source_id(
                source_expr, dialect
            )
    rename_conflicts = _add_hub_key_renames(
        derived_columns, hub_key_mappings or [], dialect, stage.stage_name
    )
    if issues is not None:
        issues.extend(rename_conflicts)

    # Resolve the ldts/rsrc column names exactly as config.json declares them
    # (user-set alias, alias derived from the project default, or the DV
    # default), so downstream models find the columns this stage computes.
    dv_cfg = _effective_dv_config(runtime_config)
    ldts_col = dv_cfg.get("ldts_alias", "ldts")
    rsrc_col = dv_cfg.get("rsrc_alias", "rsrc")

    # load_date handling:
    #   - bare column name  → pass as load_date_col so datavault4sqlmesh reads it,
    #                         and alias it to ldts_col if it has another name
    #   - SQL expression    → inject as a derived column so the stage computes it,
    #                         transpiled to the target dialect (e.g. sysdate() →
    #                         CURRENT_TIMESTAMP on postgres)
    #   - !static literal   → not applicable for load dates; silently ignore
    load_date_col_arg: str | None = None
    if _is_col_ref(stage.load_date):
        load_date_col_arg = stage.load_date
        _alias_source_column(derived_columns, ldts_col, stage.load_date, dialect)
    elif stage.load_date and not _is_static_rsrc(stage.load_date):
        derived_columns[ldts_col] = stage.load_date

    # record_source handling:
    #   - bare column name  → pass as record_source_col (read from source),
    #                         and alias it to rsrc_col if it has another name
    #   - !static literal   → emit as a SQL string constant in derived_columns
    #   - SQL expression    → inject as a derived column expression
    record_source_col_arg: str | None = None
    if _is_col_ref(stage.record_source):
        record_source_col_arg = stage.record_source
        _alias_source_column(derived_columns, rsrc_col, stage.record_source, dialect)
    elif stage.record_source and _is_static_rsrc(stage.record_source):
        # Strip the leading '!' and wrap in SQL single quotes: !Customer → 'Customer'
        literal = stage.record_source[1:]
        derived_columns[rsrc_col] = f"'{literal}'"
    elif stage.record_source:
        derived_columns[rsrc_col] = stage.record_source

    path = f"models/stg/{_slug(stage.source_system)}/{stage.stage_name}.py"
    content = _render_model(
        template_resolver,
        "stage",
        name=model_name,
        stage_name=stage.stage_name,
        source_table=source_table,
        source_schema=source_schema,
        load_date_col=load_date_col_arg,
        record_source_col=record_source_col_arg,
        derived_columns=derived_columns,
        hashed_columns=hashed_columns,
        column_overrides=column_overrides,
        stage_schema=runtime_config.stage_schema,
        stage=stage,
    )
    return _artifact("sqlmesh_model", path, content, "stage", stage.stage_name)


def _alias_source_column(
    derived_columns: dict[str, str], alias: str, column: str, dialect: str | None
) -> None:
    """Expose source *column* under the DV *alias* (ldts/rsrc) when the names differ.

    datavault4sqlmesh declares the ``ldts_alias`` / ``rsrc_alias`` columns on
    the stage and downstream models read them by that name, but the stage
    passes source columns through unchanged. A table whose load date or record
    source column has another name (e.g. ``LOAD_TS`` while config.json says
    ``LOAD_DT``) therefore needs a derived column ``{alias: column}``.

    Names that differ only in case refer to the same column after the
    dialect's normalization, so they need no alias (and aliasing would
    duplicate the column).
    """
    if column.strip().casefold() == alias.casefold():
        return
    derived_columns[alias] = _normalise_source_id(column.strip(), dialect)


def _hub_key_mappings_by_stage(
    hubs: list[HubDefinition], rendered_hub_names: set[str]
) -> dict[str, list[_HubKeyMapping]]:
    """Map each stage name to the column mappings of the rendered hubs it loads."""
    by_stage: dict[str, list[_HubKeyMapping]] = {}
    for hub in hubs:
        if hub.hub_name not in rendered_hub_names:
            continue
        for src in hub.source_tables:
            by_stage.setdefault(src.stage_name, []).extend(
                _HubKeyMapping(hub.hub_name, mapping) for mapping in src.column_mappings
            )
    return by_stage


def _add_hub_key_renames(
    derived_columns: dict[str, str],
    hub_key_mappings: list[_HubKeyMapping],
    dialect: str | None,
    stage_name: str,
) -> list[Issue]:
    """Expose renamed hub business keys in the stage under the hub column name.

    SQLMesh-only. datavault4sqlmesh's ``hub_model(business_keys=[...])`` reads
    the business keys from the stage by the hub's column names — unlike
    datavault4dbt's hub, it has no per-source ``bk_columns`` mapping. So a hub
    column fed from a differently named stage column (``REGION_NAME`` from
    ``R_NAME``) must exist in the stage as a derived column.

    A transformed key reuses the stage's derived expression for the source
    column (the export applies hub key transformations in place); existing
    derived columns are never overwritten.

    The stage can expose only one column per name, so a conflict keeps the
    existing column and returns an error Issue (the hub would otherwise
    silently load other values as its business key than its hash key is
    computed from):

    - two hubs load the same hub column name from different source columns;
      the first mapping is kept and the Issue names both hubs;
    - the stage already has a derived column with the hub column's name (a
      derived column of the table, or a renamed/transformed satellite column)
      whose expression differs from the one the hub needs.
    """
    issues: list[Issue] = []
    # hub column name -> (hub name, source column) of the mapping that claimed it
    claimed: dict[str, tuple[str, str]] = {}
    for hub_name, mapping in hub_key_mappings:
        target = mapping.hub_column
        source = mapping.source_column
        if target in claimed:
            first_hub, first_source = claimed[target]
            if first_source.casefold() != source.casefold():
                issues.append(
                    _hub_key_rename_conflict(
                        stage_name, target, first_hub, first_source, hub_name, source
                    )
                )
            continue
        claimed[target] = (hub_name, source)
        if target == source:
            continue
        if mapping.target_column_transformation and source in derived_columns:
            expression = derived_columns[source]
        else:
            expression = _normalise_source_id(source, dialect)
        existing = derived_columns.get(target)
        if existing is None:
            derived_columns[target] = expression
        elif existing.strip() != expression.strip():
            issues.append(
                _hub_key_derived_column_conflict(
                    stage_name, target, existing, hub_name, source
                )
            )
    return issues


def _hub_key_rename_conflict(
    stage_name: str,
    hub_column: str,
    first_hub: str,
    first_source: str,
    hub_name: str,
    source: str,
) -> Issue:
    """Error Issue for two hubs loading one hub column name from different columns."""
    return make_issue(
        severity="error",
        code=Code.SQLMESH_HUB_KEY_RENAME_CONFLICT,
        stage="render",
        message=(
            f"Hubs '{first_hub}' and '{hub_name}' both load the hub column "
            f"'{hub_column}' from stage '{stage_name}', but from different source "
            f"columns ('{first_source}' and '{source}'). The stage can only expose "
            f"one '{hub_column}' column, so '{hub_name}' would load the values of "
            f"'{first_source}' as its business key."
        ),
        entity=EntityRef(type="hub", name=hub_name),
        suggestion=(
            f"Give the hub column a distinct name in one of the hubs, "
            f"e.g. rename '{hub_column}' in '{hub_name}'."
        ),
    )


def _hub_key_derived_column_conflict(
    stage_name: str,
    hub_column: str,
    existing_expression: str,
    hub_name: str,
    source: str,
) -> Issue:
    """Error Issue for a hub column name already taken by another stage derived column."""
    return make_issue(
        severity="error",
        code=Code.SQLMESH_HUB_KEY_RENAME_CONFLICT,
        stage="render",
        message=(
            f"Hub '{hub_name}' loads the hub column '{hub_column}' from source "
            f"column '{source}' in stage '{stage_name}', but the stage already "
            f"derives a column '{hub_column}' as '{existing_expression}' (a derived "
            f"column of the source table or a renamed satellite column). The stage "
            f"can only expose one '{hub_column}' column, so '{hub_name}' would load "
            f"that value as its business key."
        ),
        entity=EntityRef(type="hub", name=hub_name),
        suggestion=(
            f"Give the hub column '{hub_column}' in '{hub_name}' a distinct name, "
            f"or rename the other derived column."
        ),
    )


# ---------------------------------------------------------------------------
# Hub models
# ---------------------------------------------------------------------------


def _render_hub(
    hub: HubDefinition,
    runtime_config: EngineRuntimeConfig,
    template_resolver: TemplateResolver,
) -> GeneratedArtifact:
    """Render a hub_model(...) Python file."""
    model_name = f"{runtime_config.rdv_schema}.{hub.hub_name}"
    hashkey = hub.hashkey.hashkey_name if hub.hashkey else ""
    business_keys = _hub_business_keys(hub)
    is_multi_source = len(hub.source_tables) > 1
    group_slug = _slug(hub.group) if hub.group else "shared"
    path = f"models/rdv/{group_slug}/{hub.hub_name}.py"

    content = _render_model(
        template_resolver,
        "hub_standard",
        name=model_name,
        hub_name=hub.hub_name,
        hashkey=hashkey,
        business_keys=business_keys,
        is_multi_source=is_multi_source,
        stage_schema=runtime_config.stage_schema,
        rdv_schema=runtime_config.rdv_schema,
        hub=hub,
        **_source_context(hub.source_tables, is_multi_source),
    )
    return _artifact("sqlmesh_model", path, content, "hub", hub.hub_name)


def _source_context(
    sources: list[HubSourceInfo] | list[LinkSourceInfo], is_multi_source: bool
) -> dict[str, Any]:
    """Template context describing a hub's or link's source stage(s).

    Multi-source: ``sources`` plus one static record source part per source
    ('' when unset). Single source: ``source_table`` plus ``rsrc_statics``
    holding the static part only when it is set.
    """
    if is_multi_source:
        return {
            "sources": sources,
            "rsrc_statics": [src.rsrc_static or "" for src in sources],
        }
    src = sources[0]
    return {
        "source_table": src.stage_name,
        "rsrc_statics": [src.rsrc_static] if src.rsrc_static else [],
    }


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
    template_resolver: TemplateResolver,
) -> GeneratedArtifact:
    """Render a link_model(...) Python file."""
    model_name = f"{runtime_config.rdv_schema}.{link.link_name}"
    link_hash_key = link.hashkey.hashkey_name
    foreign_hash_keys = link.foreign_hashkeys
    is_multi_source = len(link.source_tables) > 1
    group_slug = _slug(link.group) if link.group else "shared"
    path = f"models/rdv/{group_slug}/{link.link_name}.py"

    content = _render_model(
        template_resolver,
        "link_standard",
        name=model_name,
        link_name=link.link_name,
        link_hash_key=link_hash_key,
        foreign_hash_keys=foreign_hash_keys,
        is_multi_source=is_multi_source,
        stage_schema=runtime_config.stage_schema,
        rdv_schema=runtime_config.rdv_schema,
        link=link,
        **_source_context(link.source_tables, is_multi_source),
    )
    return _artifact("sqlmesh_model", path, content, "link", link.link_name)


# ---------------------------------------------------------------------------
# Satellite models
# ---------------------------------------------------------------------------


def _render_satellite(
    sat: SatelliteDefinition,
    runtime_config: EngineRuntimeConfig,
    template_resolver: TemplateResolver,
) -> GeneratedArtifact:
    """Render a satellite_model(...) Python file (v0 / standard)."""
    model_name = f"{runtime_config.rdv_schema}.{sat.satellite_name}"
    payload = _sat_payload(sat)
    group_slug = _slug(sat.group) if sat.group else "shared"
    path = f"models/rdv/{group_slug}/{sat.satellite_name}.py"

    content = _render_model(
        template_resolver,
        "satellite_standard",
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


def _render_satellite_v1(
    sat: SatelliteDefinition,
    runtime_config: EngineRuntimeConfig,
    template_resolver: TemplateResolver,
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

    content = _render_model(
        template_resolver,
        # The entity type is "satellite_v1", as for dbt and ModelTemplate.
        "satellite_v1",
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
        base = base[len(v0_prefix) :]
    if v0_suffix and base.endswith(v0_suffix):
        base = base[: -len(v0_suffix)]

    return v1_prefix + base + v1_suffix


# ---------------------------------------------------------------------------
# Code generation helpers
# ---------------------------------------------------------------------------


def _render_model(
    template_resolver: TemplateResolver, entity_type: str, **context: Any
) -> str:
    """Render the SQLMesh model template for *entity_type* with *context*.

    The template comes from the resolver (per-run override, DB template or
    the bundled ``templates/sqlmesh/models/<entity_type>.py.j2``). The result
    always ends with exactly one newline, as Jinja drops a template's final one.

    Raises SQLMeshTemplateError when no template exists or rendering fails.
    """
    try:
        # Compiling an override / DB template happens in the lookup, so a
        # syntax error (e.g. an unknown filter) surfaces here already.
        template = template_resolver.get_sql_template(entity_type)
        if template is None:
            raise SQLMeshTemplateError(
                f"No SQLMesh template found for entity type '{entity_type}'."
            )
        content = template.render(**context)
    except TemplateError as exc:
        raise SQLMeshTemplateError(
            f"SQLMesh template for '{entity_type}' failed to render: {exc}"
        ) from exc
    return content.rstrip("\n") + "\n"


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
