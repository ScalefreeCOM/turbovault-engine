"""
Names and settings of a project's generated dbt models.

TurboVault derives each model's name from the project's naming patterns. A
stored ``ModelOutput`` replaces the derived name and adds the model's folder
and ``config()`` settings. Everything that names a model asks this module,
so the files and every reference between models (a stage in a hub, a v0
table in its v1 view, satellites in a PIT, ...) agree.

The JSON export carries what is stored as each entity's ``generation_config``
(issue #442): a folder as the ``file_path`` of the model's ``.sql`` file
relative to ``models/``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from engine.models.output_attributes import file_path_of
from engine.services.export.models import (  # noqa: F401 (re-exported)
    V1_SATELLITE_TYPES,
    GenerationConfigDef,
    ModelOutputAttributes,
    ModelOutputDef,
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

logger = logging.getLogger(__name__)

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


# The physical name field of entities whose models are named after them.
_OWN_NAME_FIELDS = {
    "hub": "hub_physical_name",
    "link": "link_physical_name",
    "pit": "pit_physical_name",
    "reference_table": "reference_table_physical_name",
}


def derived_model_name(kind: str, entity: Any, config: EngineRuntimeConfig) -> str:
    """The name TurboVault gives an entity's model of ``kind``, from the
    project's naming patterns: what a stored model name replaces.

    ``entity`` is the model's entity: a source table (stage, pre-stage), the
    hub or link of an effectivity or record-tracking satellite, ...
    """
    if kind in ("stage", "prestage"):
        pattern = config.stage_naming if kind == "stage" else config.prestage_naming
        return apply_pattern(
            pattern,
            source_system=dbt_source_name(entity.source_system.name),
            source_table=entity.physical_table_name.lower(),
        )
    if kind in ("satellite_v0", "satellite_v1"):
        pattern = (
            config.satellite_v0_naming
            if kind == "satellite_v0"
            else config.satellite_v1_naming
        )
        return satellite_pattern(pattern, entity.satellite_physical_name)
    if kind in ("effectivity_satellite", "record_tracking_satellite"):
        parent = getattr(entity, "hub_physical_name", None) or entity.link_physical_name
        pattern = (
            config.effectivity_satellite_naming
            if kind == "effectivity_satellite"
            else config.record_tracking_satellite_naming
        )
        return satellite_pattern(pattern, entity_base_name(parent))
    if kind in ("snapshot_control_v0", "snapshot_control_v1"):
        base = entity.name.removesuffix("_v0").removesuffix("_v1")
        return f"{base}_{kind.rsplit('_', 1)[1]}"
    return getattr(entity, _OWN_NAME_FIELDS[kind])


class ModelOutputs:
    """The dbt models of one project: stored settings over derived names."""

    def __init__(self, project: Project, runtime_config: EngineRuntimeConfig) -> None:
        from engine.models import ModelOutput

        self.config = runtime_config
        self._stored: dict[tuple[str, object], ModelOutput] = {}
        self._by_entity: dict[tuple[str, object], list[ModelOutput]] = {}
        for row in ModelOutput.objects.filter(
            project=project, framework=ModelOutput.Framework.DBT
        ):
            field = row.entity_field
            if field is not None:
                entity_pk = getattr(row, f"{field}_id")
                self._stored[(row.kind, entity_pk)] = row
                self._by_entity.setdefault((field, entity_pk), []).append(row)

    def generation_config(
        self, entity_field: str, entity: Any, entity_label: str
    ) -> GenerationConfigDef:
        """What the project stores for an entity's dbt models, as the JSON
        export carries it (``generation_config``): the stored values, not the
        derived ones, so an import restores exactly them.

        A folder becomes the ``file_path`` of the model's ``.sql`` file
        relative to ``models/``; one outside ``models/`` can't be written that
        way and is left out (logged). ``entity_label`` names the entity in
        messages.
        """
        rows = sorted(
            self._by_entity.get((entity_field, entity.pk), []), key=lambda r: r.kind
        )
        by_kind: dict[str, ModelOutputAttributes] = {}
        for row in rows:
            file_path = None
            if row.folder:
                name = row.model_name or derived_model_name(
                    row.kind, entity, self.config
                )
                file_path = file_path_of(row.folder, name)
                if file_path is None:
                    logger.warning(
                        "The %s model of %s is in '%s', outside models/: the "
                        "JSON export can't carry its folder",
                        row.kind.replace("_", " "),
                        entity_label,
                        row.folder,
                    )
            try:
                attributes = ModelOutputAttributes(
                    model_name=row.model_name or None,
                    file_path=file_path,
                    alias=row.alias or None,
                    schema_name=row.schema_name or None,
                    database=row.database_name or None,
                    materialized=row.materialized or None,
                    tags=list(row.tags) if row.tags is not None else None,
                    custom_config_json=dict(row.config) if row.config else None,
                )
            except ValueError as exc:
                raise ValueError(
                    f"The stored {row.kind.replace('_', ' ')} model of "
                    f"{entity_label} is invalid: {exc}"
                ) from exc
            if attributes.as_stored():
                by_kind[row.kind] = attributes
        return GenerationConfigDef(dbt=by_kind)

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

    def _derived(self, kind: str, entity: Any) -> ModelOutputDef:
        """The model of ``kind``: stored settings over the derived name."""
        derived = derived_model_name(kind, entity, self.config)
        return self._output(kind, entity.pk, derived)

    # -- source tables -----------------------------------------------------

    def stage(self, table: SourceTable) -> ModelOutputDef:
        """The stage model of a source table."""
        return self._derived("stage", table)

    def prestage_name(self, table: SourceTable) -> str:
        """Name of a pre-stage's model, which its stage reads."""
        return self._derived("prestage", table).model_name

    # -- Raw Vault ---------------------------------------------------------

    def hub(self, hub: Hub) -> ModelOutputDef:
        return self._derived("hub", hub)

    def link(self, link: Link) -> ModelOutputDef:
        return self._derived("link", link)

    def satellite_v0(self, satellite: Satellite) -> ModelOutputDef:
        return self._derived("satellite_v0", satellite)

    def satellite_v1(self, satellite: Satellite) -> ModelOutputDef:
        return self._derived("satellite_v1", satellite)

    def effectivity_satellite(self, parent: Hub | Link) -> ModelOutputDef:
        return self._derived("effectivity_satellite", parent)

    def record_tracking_satellite(self, parent: Hub | Link) -> ModelOutputDef:
        return self._derived("record_tracking_satellite", parent)

    def reference_table(self, table: ReferenceTable) -> ModelOutputDef:
        return self._derived("reference_table", table)

    # -- Business Vault and control ----------------------------------------

    def pit(self, pit: PIT) -> ModelOutputDef:
        return self._derived("pit", pit)

    def snapshot_control_v0(self, control: SnapshotControlTable) -> ModelOutputDef:
        return self._derived("snapshot_control_v0", control)

    def snapshot_control_v1(self, control: SnapshotControlTable) -> ModelOutputDef:
        return self._derived("snapshot_control_v1", control)
