"""
Names and settings of a project's generated dbt models.

TurboVault derives each model's name from the project's naming patterns. A
stored ``ModelOutput`` replaces the derived name and adds the model's folder
and ``config()`` settings. Everything that names a model asks this module,
so the files and every reference between models (a stage in a hub, a v0
table in its v1 view, satellites in a PIT, ...) agree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from engine.services.export.models import (  # noqa: F401 (re-exported)
    V1_SATELLITE_TYPES,
    ModelOutputDef,
    StoredModelOutputDef,
)

if TYPE_CHECKING:
    from engine.models import (
        PIT,
        Hub,
        Link,
        Project,
        ReferenceTable,
        Satellite,
        SnapshotControlTable,
        SourceTable,
    )
    from engine.services.runtime_config import EngineRuntimeConfig

# DV type suffixes stripped when deriving a satellite base name (longest first).
_DV_TYPE_SUFFIXES = ("_rh", "_nl", "_h", "_l")


def dbt_source_name(source_system_name: str) -> str:
    """The name a source system has in generated dbt code.

    It names the system's source in ``sources.yml`` and is the
    ``[[ source_system ]]`` of the stage and pre-stage naming patterns
    (``stg__crm__customer``).
    """
    return source_system_name.lower().replace(" ", "_")


def entity_base_name(parent_physical_name: str) -> str:
    """Derive a base name: lowercase and strip a trailing DV type suffix.

    e.g. CUSTOMER_H -> customer, ORDERS_CUSTOMERS_L -> orders_customers,
    nation_rh -> nation, LINEITEM_NL -> lineitem.
    """
    lowered = parent_physical_name.lower()
    for suffix in _DV_TYPE_SUFFIXES:
        if lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


def apply_pattern(pattern: str, **values: str) -> str:
    """Fill a naming pattern's ``[[ placeholder ]]``s."""
    result = pattern
    for key, value in values.items():
        result = result.replace(f"[[ {key} ]]", value)
    return result


def satellite_pattern(pattern: str, name: str) -> str:
    """Fill a satellite naming pattern (``[[ satellite_name ]]``/``[[ entity_name ]]``)."""
    return apply_pattern(pattern, satellite_name=name, entity_name=name)


class ModelOutputs:
    """The dbt models of one project: stored settings over derived names."""

    def __init__(self, project: Project, runtime_config: EngineRuntimeConfig) -> None:
        from engine.models import ModelOutput

        self.config = runtime_config
        self._stored: dict[tuple[str, object], ModelOutput] = {}
        self._by_entity: dict[tuple[str, object], list[ModelOutput]] = {}
        for row in ModelOutput.objects.filter(project=project):
            field = row.entity_field
            if field is not None:
                entity_pk = getattr(row, f"{field}_id")
                self._stored[(row.kind, entity_pk)] = row
                self._by_entity.setdefault((field, entity_pk), []).append(row)

    def stored(
        self, entity_field: str, entity_pk: object
    ) -> dict[str, StoredModelOutputDef]:
        """What the project stores for an entity's models, by kind.

        The JSON export carries it so an import restores exactly the stored
        values, not the derived ones.
        """
        rows = sorted(
            self._by_entity.get((entity_field, entity_pk), []), key=lambda r: r.kind
        )
        return {
            row.kind: StoredModelOutputDef(
                model_name=row.model_name or None,
                folder=row.folder or None,
                alias=row.alias or None,
                schema_name=row.schema_name or None,
                database_name=row.database_name or None,
                materialized=row.materialized or None,
                tags=list(row.tags) if row.tags is not None else None,
                config=dict(row.config) if row.config else None,
            )
            for row in rows
        }

    def _output(self, kind: str, entity_pk: object, derived: str) -> ModelOutputDef:
        from engine.models import ModelOutput

        row = self._stored.get((kind, entity_pk))
        if row is None:
            return ModelOutputDef(model_name=derived)
        name = derived
        if row.model_name and kind not in ModelOutput.NAMED_BY_ENTITY:
            name = row.model_name
        return ModelOutputDef(
            model_name=name,
            folder=row.folder or None,
            alias=row.alias or None,
            schema_name=row.schema_name or None,
            database_name=row.database_name or None,
            materialized=row.materialized or None,
            tags=list(row.tags) if row.tags is not None else None,
            config=dict(row.config) if row.config else None,
        )

    # -- source tables -----------------------------------------------------

    def _table_values(self, table: SourceTable) -> dict[str, str]:
        return {
            "source_system": dbt_source_name(table.source_system.name),
            "source_table": table.physical_table_name.lower(),
        }

    def stage(self, table: SourceTable) -> ModelOutputDef:
        """The stage model of a source table."""
        derived = apply_pattern(self.config.stage_naming, **self._table_values(table))
        return self._output("stage", table.pk, derived)

    def prestage_name(self, table: SourceTable) -> str:
        """Name of a pre-stage's model, which its stage reads."""
        derived = apply_pattern(
            self.config.prestage_naming, **self._table_values(table)
        )
        return self._output("prestage", table.pk, derived).model_name

    # -- Raw Vault ---------------------------------------------------------

    def hub(self, hub: Hub) -> ModelOutputDef:
        return self._output("hub", hub.pk, hub.hub_physical_name)

    def link(self, link: Link) -> ModelOutputDef:
        return self._output("link", link.pk, link.link_physical_name)

    def satellite_v0(self, satellite: Satellite) -> ModelOutputDef:
        derived = satellite_pattern(
            self.config.satellite_v0_naming, satellite.satellite_physical_name
        )
        return self._output("satellite_v0", satellite.pk, derived)

    def satellite_v1(self, satellite: Satellite) -> ModelOutputDef:
        derived = satellite_pattern(
            self.config.satellite_v1_naming, satellite.satellite_physical_name
        )
        return self._output("satellite_v1", satellite.pk, derived)

    def effectivity_satellite(
        self, parent: Hub | Link, physical_name: str
    ) -> ModelOutputDef:
        derived = satellite_pattern(
            self.config.effectivity_satellite_naming,
            entity_base_name(physical_name),
        )
        return self._output("effectivity_satellite", parent.pk, derived)

    def record_tracking_satellite(
        self, parent: Hub | Link, physical_name: str
    ) -> ModelOutputDef:
        derived = satellite_pattern(
            self.config.record_tracking_satellite_naming,
            entity_base_name(physical_name),
        )
        return self._output("record_tracking_satellite", parent.pk, derived)

    def reference_table(self, table: ReferenceTable) -> ModelOutputDef:
        return self._output(
            "reference_table", table.pk, table.reference_table_physical_name
        )

    # -- Business Vault and control ----------------------------------------

    def pit(self, pit: PIT) -> ModelOutputDef:
        return self._output("pit", pit.pk, pit.pit_physical_name)

    @staticmethod
    def _control_base(control: SnapshotControlTable) -> str:
        return control.name.removesuffix("_v0").removesuffix("_v1")

    def snapshot_control_v0(self, control: SnapshotControlTable) -> ModelOutputDef:
        derived = f"{self._control_base(control)}_v0"
        return self._output("snapshot_control_v0", control.pk, derived)

    def snapshot_control_v1(self, control: SnapshotControlTable) -> ModelOutputDef:
        derived = f"{self._control_base(control)}_v1"
        return self._output("snapshot_control_v1", control.pk, derived)
