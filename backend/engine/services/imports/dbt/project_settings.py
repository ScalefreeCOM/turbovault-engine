"""
Model settings, the dbt_project.yml and the project's settings (spec D20,
D22, D25, D28).

Part of the dbt project mapping (``mapping._Mapper`` inherits it). Runs
last, when every model's entity, group and name are known:

- every mapped model's output stores its folder and settings where they
  differ from what TurboVault generates (``settings.stored_settings``);
- the settings the project's models follow are suggested as project
  settings (``types.ProjectSettings``, keyed by runtime config field), with
  one info each: naming patterns, layer schemas and materializations, the
  tables' default record source, load date and static part, stage options,
  the delivery method, default tags, folder patterns, and the dbt project's
  own files (dbt_project.yml, packages). Only what differs from the
  project's settings is suggested; applying it is the caller's choice.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, get_args

from engine.services.config_schema import (
    MODEL_MATERIALIZATION_DEFAULTS,
    DbtMaterialization,
)
from engine.services.export.model_outputs import dbt_source_name, entity_base_name
from engine.services.generation import project_yml
from engine.services.generation.folder_config import (
    KIND_LAYERS,
    FolderConfig,
    fixed_part,
    folder_pattern_error,
    main_source_system,
)
from engine.services.generation.project_yml import Settings
from engine.services.imports.dbt.conventions import DEFAULT_TAGS, GROUP_TAGGED
from engine.services.imports.dbt.naming import (
    FolderSample,
    Inferred,
    infer,
    infer_folder,
    infer_value,
    majority,
)
from engine.services.imports.dbt.settings import (
    folder_settings,
    model_settings,
    stored_settings,
)
from engine.services.imports.domain import DModelOutput
from engine.services.imports.errors import Code
from engine.services.imports.types import ProjectSettings, SettingSuggestion
from engine.services.source_values import DEFAULT_LOAD_DATE, default_record_source

if TYPE_CHECKING:
    from engine.services.imports.dbt.index import DbtModel

# The layer each kind of model belongs to.
_LAYERS = {
    "stage": "staging",
    "hub": "raw_vault",
    "link": "raw_vault",
    "satellite_v0": "raw_vault",
    "satellite_v1": "raw_vault",
    "effectivity_satellite": "raw_vault",
    "record_tracking_satellite": "raw_vault",
    "reference_table": "raw_vault",
    "pit": "business_vault",
    "snapshot_control_v0": "control",
    "snapshot_control_v1": "control",
}
_LAYER_SCHEMAS = {
    "staging": "stage_schema",
    "raw_vault": "rdv_schema",
    "business_vault": "bdv_schema",
    "control": "control_schema",
}
# dbt_project.yml keys that are project settings of their own.
_OWN_KEYS = frozenset({"name", "profile", "vars", "models", "config-version"})
_OUTPUT_FIELDS = (
    "folder",
    "alias",
    "schema_name",
    "database_name",
    "materialized",
    "tags",
    "config",
)
_NAMING_KEYS = (
    "hashkey_naming",
    "hashdiff_naming",
    "satellite_v0_naming",
    "satellite_v1_naming",
    "effectivity_satellite_naming",
    "record_tracking_satellite_naming",
    "stage_naming",
    "prestage_naming",
)
_MATERIALIZATIONS = frozenset(get_args(DbtMaterialization))
# The kinds of model a layer's folder pattern is inferred from (the others
# have patterns of their own, or follow another model)
_LAYER_KINDS = {
    "staging": ("stage",),
    "raw_vault": ("hub", "link", "satellite", "reference_table"),
    "control": ("snapshot_control",),
}
# Kinds placed next to another model unless they have a pattern of their own
_FOLLOWING_KINDS = frozenset(
    {"satellite_v1", "effectivity_satellite", "record_tracking_satellite"}
)
# A setting the source doesn't say (a hand-written manifest's model without
# the resolved config)
_UNKNOWN = object()


def _schema(node: Mapping[str, Any]) -> Any:
    """A model's custom schema as written (None: the target's), or _UNKNOWN."""
    config = node.get("config") or {}
    if "schema" not in config:
        return _UNKNOWN
    raw = node.get("unrendered_config") or {}
    value = raw["schema"] if "schema" in raw else config["schema"]
    return str(value) if value else None


def _materialized(node: Mapping[str, Any]) -> str | None:
    value = (node.get("config") or {}).get("materialized")
    return str(value) if value else None


def _business_vault_folder(pit_pattern: str, samples: list[FolderSample]) -> str:
    """The business vault's layer folder for PITs placed by ``pit_pattern``:
    the folder all of them are in, above a folder of PITs only
    (``models/bdv/pits/<group>`` -> ``models/bdv``)."""
    parts = fixed_part(pit_pattern).split("/")
    for sample in samples:
        folder = sample.folder.split("/")
        shared = 0
        while shared < min(len(parts), len(folder)) and parts[shared] == folder[shared]:
            shared += 1
        parts = parts[:shared]
    if len(parts) > 2 and parts[-1].lower().lstrip("0123456789_") in ("pit", "pits"):
        parts = parts[:-1]
    return "/".join(parts)


def _shown(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (Mapping, list)):
        return f"{len(value)} {'entry' if len(value) == 1 else 'entries'}"
    return f"'{value}'"


@dataclass
class _Output:
    """A mapped model whose output the import fills."""

    outputs: dict[str, DModelOutput]
    kind: str
    model: DbtModel
    # The entity whose group places it: (entity type, name)
    entity: tuple[str, str] | None = None
    # A model it is placed next to by default (a v1 view next to its v0, ...)
    follows: DbtModel | None = None
    # A stage's source system
    system: str | None = None
    # A PIT's snapshot control (its base name)
    control: str | None = None


def _folder(model: DbtModel) -> str:
    return str(PurePosixPath(model.path).parent) if model.path else ""


class ProjectSettingsMapping:
    """Model settings and project settings: a mixin of the mapper."""

    def _track(
        self,
        outputs: dict[str, DModelOutput],
        kind: str,
        model: DbtModel,
        *,
        entity: tuple[str, str] | None = None,
        follows: DbtModel | None = None,
        system: str | None = None,
        control: str | None = None,
    ) -> None:
        self._tracked_outputs.append(
            _Output(outputs, kind, model, entity, follows, system, control)
        )

    # -- model settings -----------------------------------------------------

    def _models_block(self) -> dict[str, Any] | None:
        """The project's entry of dbt_project.yml's models: block (None: no file)."""
        if not self.artifacts.dbt_project:
            return None
        models = self.artifacts.dbt_project.get("models") or {}
        block = (
            models.get(self.artifacts.project_name)
            if isinstance(models, dict)
            else None
        )
        return dict(block) if isinstance(block, dict) else {}

    def _group_of(self, entity: tuple[str, str] | None) -> str | None:
        if entity is None:
            return None
        found = {
            "hub": self.domain.hubs,
            "link": self.domain.links,
            "satellite": self.domain.satellites,
            "pit": self.domain.pits,
            "reference_table": self.domain.reference_tables,
        }.get(entity[0], {}).get(entity[1])
        return getattr(found, "group_name", None) if found is not None else None

    # Folder pattern of each kind of model output (generation's keys)
    _FOLDER_KINDS = {
        "stage": "stage",
        "hub": "hub",
        "link": "link",
        "satellite_v0": "satellite",
        "satellite_v1": "satellite_v1",
        "effectivity_satellite": "effectivity_satellite",
        "record_tracking_satellite": "record_tracking_satellite",
        "reference_table": "reference_table",
        "pit": "pit",
        "snapshot_control_v0": "snapshot_control",
        "snapshot_control_v1": "snapshot_control",
    }

    def _default_folder(self, item: _Output, group: str | None) -> str:
        """The folder TurboVault generates a model in (without a stored one):
        the project's folder pattern for its kind (spec D27)."""
        folders = FolderConfig(dict(self.config.folders or {}))
        return folders.folder(
            self._FOLDER_KINDS[item.kind],
            group=group,
            source_system=self._system_of(item),
        )

    def _system_of(self, item: _Output) -> str | None:
        """The source system [[ source_system ]] stands for in a model's
        folder: a stage's, else its entity's (generation's rule)."""
        return item.system or self._entity_system(item.entity)

    def _entity_system(self, entity: tuple[str, str] | None) -> str | None:
        """An entity's source system, as generation finds it
        (``main_source_system``): a Hub's primary source tables', a Link's
        source tables', a Satellite's table's; a PIT's and a reference
        table's are those of the Hub or Link they belong to."""
        if entity is None:
            return None
        kind, name = entity
        table_systems = {
            identifier: system.name
            for system in self.domain.source_systems.values()
            for identifier in system.tables
        }
        if kind == "hub" and name in self.domain.hubs:
            # One per source table and hash key it loads, as the export lists
            sources = {
                (
                    mapping.source_table_identifier,
                    mapping.stage_hashkey_name
                    if isinstance(mapping.stage_hashkey_name, str)
                    else "",
                ): mapping.is_primary_source
                for column in self.domain.hubs[name].columns
                if column.column_type != "additional_column"
                for mapping in column.source_mappings
            }
            primary = [table for (table, _), first in sources.items() if first]
            return main_source_system(
                table_systems.get(table)
                for table in (primary or [table for table, _ in sources])
            )
        if kind == "link" and name in self.domain.links:
            tables = {
                mapping.source_table_identifier
                for mapping in self.domain.links[name].hub_source_mappings
            }
            return main_source_system(table_systems.get(t) for t in tables)
        if kind == "satellite" and name in self.domain.satellites:
            return table_systems.get(
                self.domain.satellites[name].source_table_identifier
            )
        if kind == "pit" and name in self.domain.pits:
            pit = self.domain.pits[name]
            return self._entity_system(
                (pit.tracked_entity_type, pit.tracked_entity_name)
            )
        if kind == "reference_table" and name in self.domain.reference_tables:
            hub = self.domain.reference_tables[name].reference_hub_name
            return self._entity_system(("hub", hub))
        return None

    def _template_materialization(self, kind: str) -> str | None:
        """What a model's template writes as its materialization, if anything."""
        if (
            kind not in MODEL_MATERIALIZATION_DEFAULTS
            or not self.config.model_specific_materializations
        ):
            return None
        value = self.config.model_materializations.get(
            kind, MODEL_MATERIALIZATION_DEFAULTS[kind]
        )
        layer = getattr(self.config, f"{_LAYERS[kind]}_materialization")
        return None if value == layer else value

    def _layer_settings(self, kind: str) -> Settings:
        layer = _LAYERS[kind]
        return Settings(
            values={
                "materialized": getattr(self.config, f"{layer}_materialization"),
                "schema": getattr(self.config, _LAYER_SCHEMAS[layer]),
            }
        )

    def _template_tags(
        self, item: _Output, group: str | None, *, always: bool = False
    ) -> list[str]:
        """The tags the model's templates give it (none without default tags,
        unless ``always``)."""
        if not self.config.add_default_tags and not always:
            return []
        macro = item.model.macro or ""
        tags = list(DEFAULT_TAGS.get(macro, ()))
        if item.kind == "stage" and item.system:
            tags.append(dbt_source_name(item.system))
        elif macro in GROUP_TAGGED and group:
            tags.append(group)
        return tags

    def _template_defaults(self, item: _Output) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "materialized": self._template_materialization(item.kind)
        }
        if item.kind == "pit" and item.control:
            models = self._models_of.get(("snapshot_control", item.control)) or []
            v1 = models[1].name if len(models) > 1 else f"{item.control}_v1"
            defaults["post-hook"] = "{{ datavault4dbt.clean_up_pit('" + v1 + "') }}"
        return defaults

    def _apply_model_settings(self) -> None:
        """Store each model's folder and settings where they differ (D20)."""
        models_block = self._models_block()
        for item in self._tracked_outputs:
            group = self._group_of(item.entity)
            folder = _folder(item.model)
            folders = FolderConfig(dict(self.config.folders or {}))
            follows = item.follows is not None and not folders.has_own(
                self._FOLDER_KINDS[item.kind]
            )
            if follows:
                stored_folder = None if folder == _folder(item.follows) else folder
            else:
                default = self._default_folder(item, group)
                stored_folder = None if folder == default else folder

            fqn = list(item.model.node.get("fqn") or [])
            folder_level = (
                folder_settings(models_block, fqn)
                if models_block is not None
                else Settings()
            )
            covered = bool(folder_level.values or folder_level.tags)
            fields = stored_settings(
                effective=model_settings(item.model.node),
                folder=folder_level,
                template_defaults=self._template_defaults(item),
                template_tags=self._template_tags(item, group),
                regenerated_folder=(
                    folder_level if covered else self._layer_settings(item.kind)
                ),
            )
            if stored_folder:
                fields["folder"] = stored_folder
            if not fields:
                continue
            output = item.outputs.get(item.kind) or DModelOutput(kind=item.kind)
            for name in _OUTPUT_FIELDS:
                if name in fields:
                    setattr(output, name, fields[name])
            item.outputs[item.kind] = output

    # -- project settings (spec D22, D28) --------------------------------------

    def _project_settings(self) -> ProjectSettings:
        """What the source suggests for the project's settings."""
        self._suggestions: dict[str, SettingSuggestion] = {}
        self._suggest_naming()
        self._suggest_layers()
        self._suggest_source_values()
        self._suggest_tags()
        self._suggest_folders()
        self._suggest_dbt_project()
        return ProjectSettings(suggestions=self._suggestions)

    def _suggest(
        self,
        key: str,
        value: Any,
        current: Any,
        found: Inferred | None = None,
        *,
        of: str = "",
        source: str = "",
        origin: str = "",
    ) -> None:
        """Suggest ``value`` for the runtime config field ``key`` (dotted: an
        entry of a mapping field) where it differs from the ``current`` one.

        ``found``: what follows it (``of`` what); else it is copied from the
        dbt project's ``source`` file. ``origin`` says why, instead.
        """
        if value == current:
            return
        self._suggestions[key] = SettingSuggestion(
            value=value,
            matching=found.matching if found else None,
            total=found.total if found else None,
        )
        if not origin:
            origin = (
                f"{found.matching} of {found.total} {of} follow it"
                if found
                else f"from its {source}"
            )
        self._issue(
            None,
            "info",
            Code.DBT_SETTING_SUGGESTED,
            f"The dbt project suggests {key}: {_shown(value)} ({origin}); the "
            f"project's is {_shown(current)}",
            suggestion=(
                "Apply it (CLI: --apply-settings) so new entities follow the dbt "
                "project and importing again stores less on its models."
            ),
        )

    # Naming patterns

    def _naming_samples(self) -> dict[str, list[tuple[dict[str, str], str]]]:
        samples: dict[str, list[tuple[dict[str, str], str]]] = {
            key: [] for key in _NAMING_KEYS
        }
        for hub in self.domain.hubs.values():
            if hub.hub_type == "standard" and hub.hashkey_name:
                samples["hashkey_naming"].append(
                    ({"entity_name": hub.physical_name}, hub.hashkey_name)
                )
        for link in self.domain.links.values():
            samples["hashkey_naming"].append(
                ({"entity_name": link.physical_name}, link.hashkey_name)
            )
        for (entity_type, name), models in self._models_of.items():
            if entity_type != "satellite":
                continue
            satellite = self.domain.satellites[name]
            if isinstance(satellite.hashdiff_name, str):
                samples["hashdiff_naming"].append(
                    ({"satellite_name": name}, satellite.hashdiff_name)
                )
            samples["satellite_v0_naming"].append(
                ({"satellite_name": name}, models[0].name)
            )
            if len(models) > 1:
                samples["satellite_v1_naming"].append(
                    ({"satellite_name": name}, models[1].name)
                )
        for item in self._tracked_outputs:
            if (
                item.kind in ("effectivity_satellite", "record_tracking_satellite")
                and item.entity
            ):
                samples[f"{item.kind}_naming"].append(
                    (
                        {"satellite_name": entity_base_name(item.entity[1])},
                        item.model.name,
                    )
                )
            elif item.kind == "stage" and item.system:
                table = next(
                    (
                        t
                        for t in self.domain.source_systems[item.system].tables.values()
                        if t.outputs is item.outputs
                    ),
                    None,
                )
                if table is not None:
                    samples["stage_naming"].append(
                        (
                            {
                                "source_system": dbt_source_name(item.system),
                                "source_table": table.physical_name.lower(),
                            },
                            item.model.name,
                        )
                    )
        for system in self.domain.source_systems.values():
            for table in system.tables.values():
                prestage = (table.outputs or {}).get("prestage")
                if table.table_type == "prestage":
                    model_name = prestage.model_name if prestage else None
                    if model_name:
                        samples["prestage_naming"].append(
                            (
                                {
                                    "source_system": dbt_source_name(system.name),
                                    "source_table": table.physical_name.lower(),
                                },
                                model_name,
                            )
                        )
        return samples

    def _suggest_naming(self) -> None:
        for key, pairs in self._naming_samples().items():
            current = getattr(self.config, key)
            found = infer(pairs, prefer=current)
            if found is not None:
                self._suggest(key, found.value, current, found, of="names")

    # Layers: schemas and materializations

    def _suggest_layers(self) -> None:
        by_layer: dict[str, list[_Output]] = {layer: [] for layer in _LAYER_SCHEMAS}
        for item in self._tracked_outputs:
            by_layer[_LAYERS[item.kind]].append(item)
        for layer, key in _LAYER_SCHEMAS.items():
            schemas = [
                schema
                for schema in (_schema(item.model.node) for item in by_layer[layer])
                if schema is not _UNKNOWN
            ]
            current = getattr(self.config, key)
            found = majority(schemas, prefer=current)
            if found is not None:
                self._suggest(key, found.value, current, found, of="models")

        # A layer's materialization: of the models that follow it; the others
        # keep their own (model_specific_materializations)
        own = self.config.model_specific_materializations
        for layer, items in by_layer.items():
            values = [
                value
                for item in items
                if not (own and item.kind in MODEL_MATERIALIZATION_DEFAULTS)
                and (value := _materialized(item.model.node))
            ]
            key = f"{layer}_materialization"
            current = getattr(self.config, key)
            found = majority(values, prefer=current)
            if found is not None and found.value in _MATERIALIZATIONS:
                self._suggest(key, found.value, current, found, of="models")
        if not own:
            return
        for kind, default in MODEL_MATERIALIZATION_DEFAULTS.items():
            values = [
                value
                for item in self._tracked_outputs
                if item.kind == kind and (value := _materialized(item.model.node))
            ]
            current = self.config.model_materializations.get(kind, default)
            found = majority(values, prefer=current)
            if found is not None and found.value in _MATERIALIZATIONS:
                self._suggest(
                    f"model_materializations.{kind}",
                    found.value,
                    current,
                    found,
                    of="models",
                )

    # Source tables: default values, stage options, delivery method

    def _suggest_source_values(self) -> None:
        for attribute, key, current in (
            (
                "record_source_value",
                "default_record_source_value",
                self.config.default_record_source_value
                or default_record_source("[[ source_system ]]"),
            ),
            (
                "load_date_value",
                "default_load_date_value",
                self.config.default_load_date_value or DEFAULT_LOAD_DATE,
            ),
            (
                "static_part_of_record_source",
                "default_static_part_of_record_source",
                self.config.default_static_part_of_record_source,
            ),
        ):
            found = infer_value(self._value_samples.get(attribute, []), prefer=current)
            if found is not None:
                self._suggest(key, found.value, current, found, of="tables")

        for option, values in self._stage_option_values.items():
            current = getattr(self.config, option)
            found = majority(values, prefer=current)
            if found is not None:
                self._suggest(option, found.value, current, found, of="stages")

        methods = [
            "single_batch"
            if table.identifier in self._single_batch_tables
            else "multi_batch"
            for system in self.domain.source_systems.values()
            for table in system.tables.values()
        ]
        single = methods.count("single_batch")
        if single and not self.config.use_delivery_method:
            # Any table loading single-batch data needs the switch
            self._suggest(
                "use_delivery_method",
                True,
                False,
                Inferred(value=True, matching=single, total=len(methods)),
                origin=f"{single} of {len(methods)} tables load single-batch data",
            )
        found = majority(methods, prefer=self.config.delivery_method)
        if found is not None:
            self._suggest(
                "delivery_method",
                found.value,
                self.config.delivery_method,
                found,
                of="tables",
            )

    # Tags

    def _suggest_tags(self) -> None:
        """TurboVault's default tags: on while most models carry them."""
        carried = []
        for item in self._tracked_outputs:
            expected = self._template_tags(
                item, self._group_of(item.entity), always=True
            )
            if not expected:
                continue
            tags = {tag.lower() for tag in model_settings(item.model.node).tags}
            carried.append(all(tag.lower() in tags for tag in expected))
        current = self.config.add_default_tags
        found = majority(carried, prefer=current)
        if found is not None:
            self._suggest("add_default_tags", found.value, current, found, of="models")

    # Folders

    @staticmethod
    def _folder_pattern(
        samples: Iterable[FolderSample],
        current: str,
        context: Iterable[FolderSample] = (),
    ) -> Inferred | None:
        found = infer_folder(samples, prefer=current, context=context)
        if found is None or folder_pattern_error(found.value):
            return None
        return found

    def _suggest_folders(self) -> None:
        """Folder patterns per layer and kind of model (spec D27, D28)."""
        current = FolderConfig(dict(self.config.folders or {}))
        samples: dict[str, list[FolderSample]] = {}
        beside: dict[str, list[bool]] = {}
        for item in self._tracked_outputs:
            key = self._FOLDER_KINDS[item.kind]
            folder = _folder(item.model)
            samples.setdefault(key, []).append(
                FolderSample(folder, self._group_of(item.entity), self._system_of(item))
            )
            if item.follows is not None:
                beside.setdefault(key, []).append(folder == _folder(item.follows))

        layers: dict[str, str] = {}
        for layer, kinds in _LAYER_KINDS.items():
            pool = [sample for kind in kinds for sample in samples.get(kind, [])]
            found = self._folder_pattern(pool, current.pattern(layer))
            if found is not None:
                layers[layer] = found.value
                self._suggest(
                    f"folders.{layer}",
                    found.value,
                    current.pattern(layer),
                    found,
                    of="models",
                )

        for kind, layer in KIND_LAYERS.items():
            if not samples.get(kind):
                continue
            if kind in _FOLLOWING_KINDS and not current.has_own(kind):
                placed = majority(beside.get(kind, []), prefer=True)
                if placed is not None and placed.value:
                    continue  # next to the model they follow, as generated
            effective = (
                current.pattern(kind)
                if current.has_own(kind)
                else layers.get(layer, current.pattern(layer))
            )
            # The layer's other models tell a folder per source from a fixed one
            context = [
                sample
                for other, other_layer in KIND_LAYERS.items()
                if other_layer == layer and other != kind
                for sample in samples.get(other, [])
            ]
            found = self._folder_pattern(samples[kind], effective, context)
            if found is None:
                continue
            self._suggest(f"folders.{kind}", found.value, effective, found, of="models")
            if kind == "pit" and found.value != effective:
                # The business vault's layer folder holds the PITs
                folder = _business_vault_folder(found.value, samples[kind])
                layer_folder = current.layer_folder("business_vault")
                if not folder_pattern_error(folder) and not (
                    folder == layer_folder or folder.startswith(f"{layer_folder}/")
                ):
                    self._suggest(
                        "folders.business_vault",
                        folder,
                        current.pattern("business_vault"),
                        found,
                        of="PITs",
                    )

        found = self._folder_pattern(self._source_folders(), current.pattern("sources"))
        if found is not None:
            self._suggest(
                "folders.sources",
                found.value,
                current.pattern("sources"),
                found,
                of="source systems",
            )

    def _source_folders(self) -> list[FolderSample]:
        """Where the project describes each source system's tables."""
        samples = set()
        for node in self.artifacts.sources.values():
            if node.get("package_name") not in (None, self.artifacts.project_name):
                continue
            schema, database = self._location(node)
            system = self._systems_by_location.get(
                (schema.lower(), database.lower() if database else None)
            )
            path = str(node.get("original_file_path") or "")
            if system is None or not path:
                continue
            if not any(t.table_type != "prestage" for t in system.tables.values()):
                continue
            samples.add(
                FolderSample(str(PurePosixPath(path).parent), source_system=system.name)
            )
        return sorted(samples, key=lambda s: (s.folder, s.source_system or ""))

    # The dbt project's files

    def _suggest_dbt_project(self) -> None:
        """dbt_project.yml (name, profile, vars, models: block, other settings)
        and the packages, copied (D25, D28)."""
        original = self.artifacts.dbt_project or {}
        if original:
            source = "dbt_project.yml"
            if original.get("name"):
                self._suggest(
                    "dbt_project_name",
                    str(original["name"]),
                    self.config.dbt_project_name or self.config.project_name,
                    source=source,
                )
            if original.get("profile"):
                self._suggest(
                    "profile_name",
                    str(original["profile"]),
                    self.config.profile_name,
                    source=source,
                )
            variables = original.get("vars")
            if isinstance(variables, dict) and variables:
                self._suggest(
                    "global_vars",
                    dict(variables),
                    dict(self.config.global_vars),
                    source=source,
                )
            # Without what TurboVault writes anyway with the project's current
            # settings (its layer blocks, its paths): right whichever of the
            # other suggestions are applied
            folders = FolderConfig(dict(self.config.folders or {}))
            models_block = project_yml.without_layers(
                self._models_block() or {},
                project_yml.layers_tree(
                    self.config, folders, prestaging=self._has_prestages()
                ),
            )
            if models_block:
                self._suggest(
                    "dbt_project_models",
                    models_block,
                    dict(self.config.dbt_project_models),
                    source=source,
                )
            other = project_yml.without_defaults(
                self._other_project_settings(original),
                own_model_paths=folders.model_paths(),
            )
            if other:
                self._suggest(
                    "dbt_project_settings",
                    other,
                    dict(self.config.dbt_project_settings),
                    source=source,
                )
        packages = self.artifacts.package_entries
        if packages:
            self._suggest(
                "dbt_packages",
                packages,
                # Without packages of its own, a project has TurboVault's
                [dict(package) for package in self.config.dbt_packages]
                or [dict(project_yml.DATAVAULT4DBT_PACKAGE)],
                source="package files",
            )

    def _has_prestages(self) -> bool:
        return any(
            table.table_type == "prestage"
            for system in self.domain.source_systems.values()
            for table in system.tables.values()
        )

    def _other_project_settings(self, original: Mapping[str, Any]) -> dict:
        """dbt_project.yml's settings without a project setting of their own."""
        other = {key: value for key, value in original.items() if key not in _OWN_KEYS}
        models = original.get("models")
        if isinstance(models, dict):
            other_models = {
                key: value
                for key, value in models.items()
                if key != self.artifacts.project_name
            }
            if other_models:
                other["models"] = other_models
        return other
