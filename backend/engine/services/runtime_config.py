"""
Runtime configuration for embeddable TurboVault Engine workflows.

The CLI persists project preferences in ``config.yml``.  Studio stores the same
kind of preferences in its own SaaS models.  This module provides a small,
framework-neutral shape that both callers can pass into Engine services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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
    pit_naming: str = "[[ pit_name ]]_bp"

    dbt_project_name: str | None = None
    create_zip: bool = False
    export_sources: bool = True
    generate_tests: bool = True
    generate_dbml: bool = False
    generate_satellite_v1_views: bool = True

    @classmethod
    def from_turbovault_config(
        cls, config: TurboVaultConfig
    ) -> EngineRuntimeConfig:
        """Create runtime config from the CLI/project YAML Pydantic config."""
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
            pit_naming=config.configuration.pit_naming or cls.pit_naming,
            dbt_project_name=config.output.dbt_project_name or config.project.name,
            create_zip=config.output.create_zip,
            export_sources=config.output.export_sources,
            generate_tests=config.output.generate_tests,
            generate_dbml=config.output.generate_dbml,
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
            "pit_naming": self.pit_naming,
            "hashkey_naming": self.hashkey_naming,
            "hashdiff_naming": self.hashdiff_naming,
        }
        return defaults.get(pattern_key, f"{{{pattern_key}}}")


def resolve_runtime_config(
    project: Project, runtime_config: EngineRuntimeConfig | None = None
) -> EngineRuntimeConfig:
    """Return the explicit runtime config, or derive one from the project."""
    return runtime_config or EngineRuntimeConfig.from_project(project)
