"""
Mapping a dbt project's models to TurboVault entities.

Turns the datavault4dbt calls of a project's models (see ``extract`` and
``datavault4dbt``) into the import's ``DomainModel``: source systems and
tables, stages, hubs, links, satellites, PITs, reference tables and snapshot
controls, with each model's name, folder and settings. Built in Phase 4b of
the dbt project import (spec §7).
"""

from __future__ import annotations

from engine.services.imports.dbt.artifacts import DbtArtifacts
from engine.services.imports.domain import DomainModel
from engine.services.imports.types import DbtSource, Issue


def map_project(
    artifacts: DbtArtifacts, source: DbtSource
) -> tuple[DomainModel, list[Issue]]:
    """Map the project's models; returns the domain model and its issues."""
    return DomainModel(), []
