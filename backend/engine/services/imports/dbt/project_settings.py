"""
Model settings, the dbt_project.yml and naming patterns (spec D20, D22, D25).

Part of the dbt project mapping (``mapping._Mapper`` inherits it). Runs
last, when every model's entity, group and name are known:

- every mapped model's output stores its folder and settings where they
  differ from what TurboVault generates (``settings.stored_settings``);
- the project's ``dbt_project.yml`` (name, profile, vars, models: block,
  other settings) and the naming patterns its models follow are suggested as
  project settings (``types.ProjectSettings``), with one info per pattern.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from engine.services.config_schema import MODEL_MATERIALIZATION_DEFAULTS
from engine.services.export.model_outputs import dbt_source_name, entity_base_name
from engine.services.generation.folder_config import FolderConfig
from engine.services.generation.project_yml import Settings
from engine.services.imports.dbt.conventions import DEFAULT_TAGS, GROUP_TAGGED
from engine.services.imports.dbt.naming import infer
from engine.services.imports.dbt.settings import (
    folder_settings,
    model_settings,
    stored_settings,
)
from engine.services.imports.domain import DModelOutput
from engine.services.imports.errors import Code
from engine.services.imports.types import NamingSuggestion, ProjectSettings

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

    def _default_folder(self, item: _Output, group: str | None) -> str:
        """The folder TurboVault generates a model in (without a stored one)."""
        folders = FolderConfig()
        named = folders._sanitize_name
        if item.kind == "stage":
            return f"{folders.staging_path}/{named(item.system or '')}"
        if item.kind == "pit":
            base = f"{folders.business_vault_path}/{folders.pits_subdir}"
            return f"{base}/{named(group)}" if group else base
        if item.kind.startswith("snapshot_control"):
            return folders.control_path
        if item.kind == "reference_table" or not group:
            return folders.raw_vault_path
        return f"{folders.raw_vault_path}/{named(group)}"

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

    def _template_tags(self, item: _Output, group: str | None) -> list[str]:
        """The tags the model's templates give it (none without default tags)."""
        if not self.config.add_default_tags:
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
            if item.follows is not None:
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

    # -- project settings ----------------------------------------------------

    def _naming(self) -> dict[str, NamingSuggestion]:
        samples: dict[str, list[tuple[dict[str, str], str]]] = {
            key: []
            for key in (
                "hashkey_naming",
                "hashdiff_naming",
                "satellite_v0_naming",
                "satellite_v1_naming",
                "effectivity_satellite_naming",
                "record_tracking_satellite_naming",
                "stage_naming",
                "prestage_naming",
            )
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

        suggestions: dict[str, NamingSuggestion] = {}
        for key, pairs in samples.items():
            found = infer(pairs)
            if found is None or found.pattern == getattr(self.config, key):
                continue
            suggestions[key] = NamingSuggestion(
                pattern=found.pattern, matching=found.matching, total=found.total
            )
            self._issue(
                None,
                "info",
                Code.DBT_NAMING_INFERRED,
                f"The project names {key.removesuffix('_naming').replace('_', ' ')}s "
                f"'{found.pattern}' ({found.matching} of {found.total}); the "
                f"project setting {key} is '{getattr(self.config, key)}'",
                suggestion=(
                    f"Set {key} to '{found.pattern}' so new entities follow the "
                    "project's style; importing again then stores fewer names."
                ),
            )
        return suggestions

    def _project_settings(self) -> ProjectSettings:
        """What the source suggests for the project's settings (D22, D25)."""
        project_yml = self.artifacts.dbt_project or {}
        models = project_yml.get("models")
        models = models if isinstance(models, dict) else {}
        root = self.artifacts.project_name
        other = {
            key: value for key, value in project_yml.items() if key not in _OWN_KEYS
        }
        other_models = {key: value for key, value in models.items() if key != root}
        if other_models:
            other["models"] = other_models
        variables = project_yml.get("vars")
        return ProjectSettings(
            naming=self._naming(),
            dbt_project_name=str(project_yml["name"])
            if project_yml.get("name")
            else None,
            profile_name=str(project_yml["profile"])
            if project_yml.get("profile")
            else None,
            global_vars=dict(variables) if isinstance(variables, dict) else {},
            dbt_project_models=dict(self._models_block() or {}),
            dbt_project_settings=other,
            use_delivery_method=(
                True
                if self._single_batch_tables and not self.config.use_delivery_method
                else None
            ),
        )
