"""
Runtime configuration for embeddable TurboVault Engine workflows.

The CLI persists project preferences in ``config.yml``.  Studio stores the same
kind of preferences in its own SaaS models.  This module provides a small,
framework-neutral shape that both callers can pass into Engine services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.models import Project
    from engine.services.config_schema import TurboVaultConfig


@dataclass(frozen=True)
class EngineRuntimeConfig:
    """Project-level settings needed by Engine import/export/generation services."""

    project_name: str | None = None
    project_description: str | None = None

    stage_schema: str = "stage"
    stage_database: str | None = None
    rdv_schema: str = "rdv"
    rdv_database: str | None = None
    bdv_schema: str = "bdv"
    bdv_database: str | None = None

    hashdiff_naming: str = "hd_[[ satellite_name ]]"
    hashkey_naming: str = "hk_[[ entity_name ]]"
    satellite_v0_naming: str = "[[ satellite_name ]]_v0"
    satellite_v1_naming: str = "[[ satellite_name ]]_v1"
    record_tracking_satellite_naming: str = "[[ satellite_name ]]_ts"
    effectivity_satellite_naming: str = "[[ satellite_name ]]_es"

    # Record source / load date of source tables that set none and whose
    # source system sets none either (see engine.services.source_values).
    default_record_source_value: str | None = None
    default_static_part_of_record_source: str | None = None
    default_load_date_value: str | None = None

    dbt_project_name: str | None = None
    create_zip: bool = False
    export_sources: bool = True
    generate_tests: bool = True
    generate_dbml: bool = False
    generate_satellite_v1_views: bool = True

    # Passthrough for datavault4dbt global variables. Rendered verbatim into the
    # `vars:` block of dbt_project.yml. The engine does not curate or validate
    # the key list — that is owned by the caller (e.g. Studio).
    #
    # `hash=False` keeps this frozen dataclass hashable: a dict field would
    # otherwise make every `hash(config)` raise TypeError. It stays part of
    # `__eq__`, so equal configs still hash equal.
    global_vars: dict[str, Any] = field(default_factory=dict, hash=False)

    # SQLMesh project settings (for --type sqlmesh output).
    sqlmesh_dialect: str = "duckdb"
    sqlmesh_gateway: str = "local"
    sqlmesh_connection_type: str = "duckdb"
    sqlmesh_start: str = "2020-01-01"

    # datavault4sqlglot DV config keys rendered into config.json.
    # Stored as a tuple-of-pairs for frozen-dataclass hashability; convert
    # with `sqlmesh_dv_config_dict` property before use.
    sqlmesh_dv_config: tuple[tuple[str, Any], ...] = field(default=(), hash=False)

    @property
    def sqlmesh_dv_config_dict(self) -> dict[str, Any]:
        """Return SQLMesh DV config as a plain dict for rendering."""
        return dict(self.sqlmesh_dv_config)

    @classmethod
    def from_turbovault_config(
        cls, config: TurboVaultConfig
    ) -> EngineRuntimeConfig:
        """Create runtime config from the CLI/project YAML Pydantic config."""
        sm = config.output.sqlmesh
        dv_config_pairs: tuple[tuple[str, Any], ...] = tuple(
            (k, v)
            for k, v in {
                "ldts_alias": sm.ldts_alias,
                "rsrc_alias": sm.rsrc_alias,
                "ledts_alias": sm.ledts_alias,
                "hash": sm.hash,
                "end_of_all_times": sm.end_of_all_times,
                "beginning_of_all_times": sm.beginning_of_all_times,
                "hashkey_input_case_sensitive": sm.hashkey_input_case_sensitive,
                "hashdiff_input_case_sensitive": sm.hashdiff_input_case_sensitive,
                "use_trim": sm.use_trim,
                "quote_identifiers": sm.quote_identifiers,
                "ghost_record_rsrc": sm.ghost_record_rsrc,
                "ghost_record_error_rsrc": sm.ghost_record_error_rsrc,
            }.items()
            if v is not None
        )
        return cls(
            project_name=config.project.name,
            project_description=config.project.description,
            stage_schema=config.configuration.stage_schema,
            stage_database=config.configuration.stage_database,
            rdv_schema=config.configuration.rdv_schema,
            rdv_database=config.configuration.rdv_database,
            bdv_schema=config.configuration.bdv_schema,
            bdv_database=config.configuration.bdv_database,
            hashdiff_naming=config.configuration.hashdiff_naming
            or cls.hashdiff_naming,
            hashkey_naming=config.configuration.hashkey_naming or cls.hashkey_naming,
            satellite_v0_naming=config.configuration.satellite_v0_naming
            or cls.satellite_v0_naming,
            satellite_v1_naming=config.configuration.satellite_v1_naming
            or cls.satellite_v1_naming,
            record_tracking_satellite_naming=(
                config.configuration.record_tracking_satellite_naming
                or cls.record_tracking_satellite_naming
            ),
            effectivity_satellite_naming=(
                config.configuration.effectivity_satellite_naming
                or cls.effectivity_satellite_naming
            ),
            default_record_source_value=(
                config.configuration.default_record_source_value
            ),
            default_static_part_of_record_source=(
                config.configuration.default_static_part_of_record_source
            ),
            default_load_date_value=config.configuration.default_load_date_value,
            dbt_project_name=config.output.dbt_project_name or config.project.name,
            create_zip=config.output.create_zip,
            export_sources=config.output.export_sources,
            generate_tests=config.output.generate_tests,
            generate_dbml=config.output.generate_dbml,
            sqlmesh_dialect=sm.dialect,
            sqlmesh_gateway=sm.gateway,
            sqlmesh_connection_type=sm.connection_type,
            sqlmesh_start=sm.start,
            sqlmesh_dv_config=dv_config_pairs,
        )

    @classmethod
    def from_project(cls, project: Project) -> EngineRuntimeConfig:
        """
        Create runtime config for a project.

        If the standalone CLI project has a ``config.yml`` it is used.  Embedded
        callers such as Studio usually keep ``project_directory`` empty; in that
        case sensible Engine defaults are returned.
        """
        if getattr(project, "project_directory", None):
            try:
                return cls.from_turbovault_config(project.load_config())
            except Exception:
                pass

        return cls(
            project_name=project.name,
            project_description=project.description,
            dbt_project_name=project.name,
        )

    def get_schema(self, schema_type: str) -> str:
        """Return the configured schema for ``stage``, ``rdv``, or ``bdv``."""
        value = getattr(self, f"{schema_type}_schema", None)
        if value:
            return value
        return schema_type

    def get_naming_pattern(self, pattern_key: str) -> str:
        """Return a configured naming pattern by key."""
        defaults = {
            "satellite_v0_naming": self.satellite_v0_naming,
            "satellite_v1_naming": self.satellite_v1_naming,
            "record_tracking_satellite_naming": self.record_tracking_satellite_naming,
            "effectivity_satellite_naming": self.effectivity_satellite_naming,
            "hashkey_naming": self.hashkey_naming,
            "hashdiff_naming": self.hashdiff_naming,
        }
        return defaults.get(pattern_key, f"{{{pattern_key}}}")


def resolve_runtime_config(
    project: Project, runtime_config: EngineRuntimeConfig | None = None
) -> EngineRuntimeConfig:
    """Return the explicit runtime config, or derive one from the project."""
    return runtime_config or EngineRuntimeConfig.from_project(project)
