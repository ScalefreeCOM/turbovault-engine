"""
Where each generated dbt model goes, what it is called and how it is configured.

Before anything is rendered, `resolve_model_outputs` decides for every model
the generator will emit:

- its model name and folder: the stored output attributes (see
  `engine.models.output_attributes`) when `use_original_paths` is on, else the
  configured naming patterns and Turbovault's layer folders;
- its per-model config: alias, schema, database, materialization and tags.

Every reference between models (stages in `source_models`, `sat_v0` in v1
views and PITs, `sat_v1` in reference tables, the snapshot control in PITs)
is looked up here, so references always match the names the models are
written under.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from engine.services.export.models import ModelOutputAttributes, ProjectExport
    from engine.services.generation.folder_config import GenerationConfig

# Model kinds the dbt generator emits, with the layer each belongs to.
LAYER_BY_KIND: dict[str, str] = {
    "stage": "staging",
    "hub": "raw_vault",
    "link": "raw_vault",
    "satellite_v0": "raw_vault",
    "satellite_v1": "raw_vault",
    "record_tracking_satellite": "raw_vault",
    "effectivity_satellite": "raw_vault",
    "reference_table": "raw_vault",
    "pit": "business_vault",
    "snapshot_control_v0": "control",
    "snapshot_control_v1": "control",
}

# Satellite types that get a v1 (load end date) view.
V1_SATELLITE_TYPES = frozenset({"standard", "effectivity", "multi_active", "reference"})

# DV type suffixes stripped when deriving a satellite base name (longest first).
_DV_TYPE_SUFFIXES = ("_rh", "_nl", "_h", "_l")


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


@dataclass(frozen=True)
class ModelOutput:
    """Name, location and config of one generated model."""

    kind: str
    # The Turbovault entity the model is generated from, for messages.
    entity_name: str
    model_name: str
    # Folder of the model's .sql and .yml, relative to the project root.
    directory: PurePosixPath
    alias: str | None = None
    schema: str | None = None
    database: str | None = None
    materialized: str | None = None
    tags: tuple[str, ...] | None = None

    @property
    def sql_path(self) -> PurePosixPath:
        """Path of the model's .sql file relative to the project root."""
        return self.directory / f"{self.model_name}.sql"


@dataclass
class ModelOutputs:
    """The resolved `ModelOutput` of every model, by (kind, entity key)."""

    _outputs: dict[tuple[str, str], ModelOutput] = field(default_factory=dict)

    def add(self, key: str, output: ModelOutput) -> None:
        self._outputs[(output.kind, key)] = output

    def get(self, kind: str, key: str) -> ModelOutput | None:
        return self._outputs.get((kind, key))

    def name(self, kind: str, key: str, default: str) -> str:
        """The model name of (kind, key), or ``default`` if it isn't generated.

        References to a model generation skips (e.g. a v1 view while v1 views
        are off) keep the name it would have.
        """
        output = self.get(kind, key)
        return output.model_name if output else default

    def __iter__(self) -> Iterator[ModelOutput]:
        return iter(self._outputs.values())

    def collisions(self) -> list[str]:
        """Describe every model name or file path used by more than one model.

        Compared case-insensitively: dbt names must be unique however they
        are cased, and Windows and macOS file systems ignore case.
        """
        by_name: dict[str, list[ModelOutput]] = defaultdict(list)
        by_path: dict[str, list[ModelOutput]] = defaultdict(list)
        for output in self:
            by_name[output.model_name.casefold()].append(output)
            by_path[str(output.sql_path).casefold()].append(output)

        messages = []
        for outputs in by_name.values():
            if len(outputs) > 1:
                messages.append(
                    f"Model name '{outputs[0].model_name}' is used by "
                    f"{_describe(outputs)}"
                )
        for outputs in by_path.values():
            # Same name in the same folder is already reported above.
            if len(outputs) > 1 and len({o.model_name.casefold() for o in outputs}) > 1:
                messages.append(
                    f"File path '{outputs[0].sql_path}' is used by {_describe(outputs)}"
                )
        return messages


def _describe(outputs: list[ModelOutput]) -> str:
    return ", ".join(f"{o.kind} of '{o.entity_name}'" for o in outputs)


def resolve_model_outputs(
    project_export: ProjectExport, config: GenerationConfig
) -> ModelOutputs:
    """Resolve the `ModelOutput` of every model the dbt generator will emit.

    Mirrors the generator's rules for which models exist (v1 views only when
    enabled and for v1-capable types, record-tracking satellites only for
    flagged parents with a hashkey, ...), so collisions are checked across
    exactly the files that would be written.
    """
    resolver = _Resolver(config)
    folders = config.folder_config

    for stage in project_export.stages:
        resolver.add(
            "stage",
            stage.stage_name,
            entity_name=stage.stage_name,
            default_name=stage.stage_name,
            default_directory=PurePosixPath(folders.staging_path)
            / folders._sanitize_name(stage.source_system),
            attributes=stage.output_attributes.get("stage"),
        )

    for hub in project_export.hubs:
        directory = _raw_vault_directory(config, hub.group)
        resolver.add(
            "hub",
            hub.hub_name,
            entity_name=hub.hub_name,
            default_name=hub.hub_name,
            default_directory=directory,
            attributes=hub.output_attributes.get("hub"),
        )
        if hub.create_record_tracking_satellite and hub.hashkey:
            resolver.add(
                "record_tracking_satellite",
                record_tracking_key("hub", hub.hub_name),
                entity_name=hub.hub_name,
                default_name=config.resolve_entity_name(
                    config.record_tracking_satellite_naming,
                    entity_base_name(hub.hub_name),
                ),
                default_directory=directory,
                attributes=hub.output_attributes.get("record_tracking_satellite"),
            )
        if hub.create_effectivity_satellite and hub.hashkey and hub.source_tables:
            resolver.add(
                "effectivity_satellite",
                hub.hub_name,
                entity_name=hub.hub_name,
                default_name=config.resolve_entity_name(
                    config.effectivity_satellite_naming,
                    entity_base_name(hub.hub_name),
                ),
                default_directory=directory,
                attributes=hub.output_attributes.get("effectivity_satellite"),
            )

    for link in project_export.links:
        directory = _raw_vault_directory(config, link.group)
        resolver.add(
            "link",
            link.link_name,
            entity_name=link.link_name,
            default_name=link.link_name,
            default_directory=directory,
            attributes=link.output_attributes.get("link"),
        )
        if link.create_record_tracking_satellite and link.hashkey:
            resolver.add(
                "record_tracking_satellite",
                record_tracking_key("link", link.link_name),
                entity_name=link.link_name,
                default_name=config.resolve_entity_name(
                    config.record_tracking_satellite_naming,
                    entity_base_name(link.link_name),
                ),
                default_directory=directory,
                attributes=link.output_attributes.get("record_tracking_satellite"),
            )

    for satellite in project_export.satellites:
        directory = _raw_vault_directory(config, satellite.group)
        resolver.add(
            "satellite_v0",
            satellite.satellite_name,
            entity_name=satellite.satellite_name,
            default_name=config.resolve_entity_name(
                config.satellite_v0_naming, satellite.satellite_name
            ),
            default_directory=directory,
            attributes=satellite.output_attributes.get("satellite_v0"),
        )
        if (
            config.generate_satellite_v1_views
            and satellite.satellite_type in V1_SATELLITE_TYPES
        ):
            resolver.add(
                "satellite_v1",
                satellite.satellite_name,
                entity_name=satellite.satellite_name,
                default_name=config.resolve_entity_name(
                    config.satellite_v1_naming, satellite.satellite_name
                ),
                default_directory=directory,
                attributes=satellite.output_attributes.get("satellite_v1"),
            )

    for pit in project_export.pits:
        directory = PurePosixPath(folders.business_vault_path) / folders.pits_subdir
        if pit.group:
            directory /= folders._sanitize_name(pit.group)
        resolver.add(
            "pit",
            pit.pit_name,
            entity_name=pit.pit_name,
            default_name=pit.pit_name,
            default_directory=directory,
            attributes=pit.output_attributes.get("pit"),
        )

    for ref_table in project_export.reference_tables:
        resolver.add(
            "reference_table",
            ref_table.table_name,
            entity_name=ref_table.table_name,
            default_name=ref_table.table_name,
            default_directory=_raw_vault_directory(config, ref_table.group),
            attributes=ref_table.output_attributes.get("reference_table"),
        )

    for control in project_export.snapshot_controls:
        for kind, default_name in (
            ("snapshot_control_v0", control.v0_name),
            ("snapshot_control_v1", control.v1_name),
        ):
            resolver.add(
                kind,
                control.name,
                entity_name=control.name,
                default_name=default_name,
                default_directory=PurePosixPath(folders.control_path),
                attributes=control.output_attributes.get(kind),
            )

    return resolver.outputs


def record_tracking_key(parent_type: str, parent_name: str) -> str:
    """Key of a record-tracking satellite: hubs and links may share a name."""
    return f"{parent_type}:{parent_name}"


def _raw_vault_directory(config: GenerationConfig, group: str | None) -> PurePosixPath:
    folders = config.folder_config
    directory = PurePosixPath(folders.raw_vault_path)
    return directory / folders._sanitize_name(group) if group else directory


class _Resolver:
    """Builds `ModelOutputs`, applying stored attributes when enabled."""

    def __init__(self, config: GenerationConfig) -> None:
        self.config = config
        self.outputs = ModelOutputs()

    def add(
        self,
        kind: str,
        key: str,
        *,
        entity_name: str,
        default_name: str,
        default_directory: PurePosixPath,
        attributes: ModelOutputAttributes | None,
    ) -> None:
        if attributes is None or not self.config.use_original_paths:
            output = ModelOutput(
                kind=kind,
                entity_name=entity_name,
                model_name=default_name,
                directory=default_directory,
            )
        else:
            output = self._from_attributes(
                kind, entity_name, default_name, default_directory, attributes
            )
        self.outputs.add(key, output)

    def _from_attributes(
        self,
        kind: str,
        entity_name: str,
        default_name: str,
        default_directory: PurePosixPath,
        attributes: ModelOutputAttributes,
    ) -> ModelOutput:
        directory = default_directory
        model_name = attributes.model_name or default_name
        if attributes.file_path:
            # Validated on input: relative, inside models/, named after the model.
            file_path = PurePosixPath(attributes.file_path)
            directory = PurePosixPath("models") / file_path.parent
            model_name = attributes.model_name or file_path.stem
        return ModelOutput(
            kind=kind,
            entity_name=entity_name,
            model_name=model_name,
            directory=directory,
            alias=attributes.alias,
            schema=attributes.schema_name,
            database=attributes.database,
            materialized=attributes.materialized,
            tags=tuple(attributes.tags) if attributes.tags is not None else None,
        )
