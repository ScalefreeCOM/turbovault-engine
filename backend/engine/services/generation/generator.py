"""
dbt project generator.

Main module for generating complete dbt projects from TurboVault export data.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from engine.services.config_schema import MODEL_MATERIALIZATION_DEFAULTS

from .file_writer import write_sql_file, write_yaml_file
from .folder_config import GenerationConfig, get_model_filename
from .output_attributes import (
    DbtModelAttributes,
    OutputAttributesError,
    config_literal,
    dbt_model_attributes,
)
from .profiles_yml import LiteralSecretError, render_profiles_yml
from .report import GenerationReport
from .template_resolver import TemplateResolver
from .vars_block import render_vars_block

if TYPE_CHECKING:
    from jinja2 import Template

    from engine.services.export.models import (
        HubDefinition,
        LinkDefinition,
        PITDefinition,
        ProjectExport,
        ReferenceTableDefinition,
        SatelliteDefinition,
        SnapshotControlDefinition,
        StageDefinition,
    )


logger = logging.getLogger(__name__)

# Layer materialization settings, checked before generation starts.
_MATERIALIZATION_FIELDS = (
    "control_materialization",
    "staging_materialization",
    "raw_vault_materialization",
    "business_vault_materialization",
)
# A dbt materialization name: built-in (table, view, ...) or a custom one.
_MATERIALIZATION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _is_materialization_name(value: object) -> bool:
    """Whether `value` is a usable dbt materialization name.

    Only real strings count — `str(None)` would pass as "None" — and the whole
    string must match: `$` in `re.match` also accepts a trailing newline, which
    would break the `materialized='...'` line in the generated SQL.
    """
    return isinstance(value, str) and bool(_MATERIALIZATION_NAME.fullmatch(value))


# Models whose materialization differs from their layer's by nature, with
# their default. Written into the model's config() while
# `model_specific_materializations` is on.
_SPECIFIC_MATERIALIZATIONS = MODEL_MATERIALIZATION_DEFAULTS
# The layer each of those models lives in.
_MODEL_LAYERS = {
    "satellite_v1": "raw_vault",
    "reference_table": "raw_vault",
    "pit": "business_vault",
    "snapshot_control_v0": "control",
    "snapshot_control_v1": "control",
}

# Per layer: its folder (FolderConfig attribute), schema and materialization
# (GenerationConfig attributes), as set by the dbt_project.yml models: block.
_LAYERS = {
    "control": ("control_path", "control_schema", "control_materialization"),
    "staging": ("staging_path", "stage_schema", "staging_materialization"),
    "raw_vault": ("raw_vault_path", "rdv_schema", "raw_vault_materialization"),
    "business_vault": (
        "business_vault_path",
        "bdv_schema",
        "business_vault_materialization",
    ),
}

# Satellite types that get a v1 (load end date) view.
_V1_SATELLITE_TYPES = frozenset(
    {"standard", "effectivity", "multi_active", "reference"}
)

# DV type suffixes stripped when deriving a satellite base name (longest first).
_DV_TYPE_SUFFIXES = ("_rh", "_nl", "_h", "_l")


@dataclass(frozen=True)
class _ModelSpec:
    """One model an export can generate, with what its output defaults to."""

    kind: str  # output kind, a key under generation_config.dbt
    key: str  # identifies the model within its kind
    # The entity the model is generated from (owns the generation_config).
    entity_type: str  # a key of DBT_OUTPUT_KINDS_BY_ENTITY
    entity_name: str
    generation_config: Mapping[str, Any]
    default_name: str
    default_dir: Path
    layer: str  # a key of _LAYERS
    # Template entity types needed to write the model; empty when it is only
    # referenced by other models (e.g. a v1 satellite no v1 view is made for).
    templates: tuple[str, ...]


@dataclass(frozen=True)
class _ModelOutput:
    """The resolved name, folder and config() settings of one model."""

    name: str
    directory: Path
    materialization: str | None = None
    # config() settings besides materialized and tags, as Jinja literals.
    config: dict[str, str] = field(default_factory=dict)
    # The tags as a list literal, replacing the template's; None keeps those.
    tags: str | None = None

    @property
    def sql_path(self) -> Path:
        return self.directory / get_model_filename(self.name, extension="sql")

    def template_context(self) -> dict[str, Any]:
        return {
            "model_name": self.name,
            "materialization": self.materialization,
            "model_config": self.config,
            "model_tags": self.tags,
        }


def _entity_base_name(parent_physical_name: str) -> str:
    """Derive a base name: lowercase and strip a trailing DV type suffix.

    e.g. CUSTOMER_H -> customer, ORDERS_CUSTOMERS_L -> orders_customers,
    nation_rh -> nation, LINEITEM_NL -> lineitem.
    """
    lowered = parent_physical_name.lower()
    for suffix in _DV_TYPE_SUFFIXES:
        if lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


class DbtProjectGenerator:
    """
    Generate a complete dbt project from TurboVault export data.

    Usage:
        from engine.services.generation import DbtProjectGenerator, GenerationConfig

        config = GenerationConfig(project_name="my_project")
        generator = DbtProjectGenerator(
            output_path=Path("./output/my_project"),
            config=config
        )
        report = generator.generate(project_export)
    """

    def __init__(
        self,
        output_path: Path,
        config: GenerationConfig | None = None,
        template_resolver: TemplateResolver | None = None,
    ) -> None:
        """
        Initialize the generator.

        Args:
            output_path: Root directory for the generated dbt project.
            config: Generation configuration options.
            template_resolver: Custom template resolver (uses default if None).
        """
        self.output_path = Path(output_path)
        self.config = config or GenerationConfig()
        self.template_resolver = template_resolver or TemplateResolver()
        self.folder_config = self.config.folder_config
        # Resolved model outputs, keyed by (output kind, entity key).
        self._outputs: dict[tuple[str, str], _ModelOutput] = {}

        # Initialize report
        self.report = GenerationReport(project_path=self.output_path)

    def generate(
        self,
        project_export: ProjectExport,
        reference_export: ProjectExport | None = None,
    ) -> GenerationReport:
        """
        Generate complete dbt project from export data.

        Args:
            project_export: The project export containing all entity definitions.
            reference_export: The whole project when `project_export` holds
                only selected entities. Model names (and their collisions) are
                resolved from it, so references to models left out still use
                their stored names.

        Returns:
            GenerationReport with results, counts, and any errors/warnings.
        """
        logger.info(f"Starting dbt project generation at: {self.output_path}")

        # 0. Resolve the caller-supplied vars block before creating anything.
        # Doing it here rather than mid-run means a bad value cannot leave a
        # half-written tree behind: the write stage only replaces files it is
        # given, so skipping dbt_project.yml later would mix fresh models with
        # a previous run's project config. Failing now writes nothing at all.
        try:
            vars_block = render_vars_block(self.config.global_vars)
        except ValueError as e:
            self.report.add_error(
                entity_type="project",
                entity_name="dbt_project.yml",
                message=f"Invalid global_vars: {e}",
                code="VAR_001",
            )
            return self.report

        # Same reasoning for the optional profiles.yml.
        profiles_content: str | None = None
        if self.config.generate_profiles_yml:
            try:
                profiles_content = render_profiles_yml(self.config.profiles)
            except LiteralSecretError as e:
                self.report.add_error(
                    entity_type="project",
                    entity_name="profiles.yml",
                    message=str(e),
                    code="PRF_002",
                )
                return self.report
            except ValueError as e:
                self.report.add_error(
                    entity_type="project",
                    entity_name="profiles.yml",
                    message=f"Invalid profiles: {e}",
                    code="PRF_001",
                )
                return self.report

        # Materializations end up in SQL (`materialized='...'`) and YAML, so
        # only dbt identifiers are accepted — built-in or custom ones.
        invalid = [
            field_name
            for field_name in _MATERIALIZATION_FIELDS
            if not _is_materialization_name(getattr(self.config, field_name))
        ]
        model_materializations = self.config.model_materializations
        if not isinstance(model_materializations, dict):
            invalid.append("model_materializations")
        else:
            invalid.extend(
                f"model_materializations.{kind}"
                for kind, value in model_materializations.items()
                if kind not in _SPECIFIC_MATERIALIZATIONS
                or not _is_materialization_name(value)
            )
        if invalid:
            self.report.add_error(
                entity_type="project",
                entity_name="dbt_project.yml",
                message=(
                    f"Invalid materialization in {', '.join(invalid)}: use a dbt "
                    "materialization name such as table, view, incremental or "
                    "ephemeral"
                ),
                code="MAT_001",
            )
            return self.report

        # Resolve every model's name, folder and config() up front: models
        # reference each other by their final names, and an invalid or
        # colliding attribute must stop the run before any file is written.
        if not self._resolve_outputs(reference_export or project_export):
            return self.report
        project_export = self._with_resolved_references(project_export)

        try:
            # 1. Create folder structure
            self._create_folder_structure()

            # 2. Generate project-level files
            self._generate_project_files(vars_block, profiles_content)

            # 3. Generate sources.yml
            self._generate_sources(project_export.sources)

            # 4. Generate stage models
            self._generate_stages(project_export.stages)

            # 5. Generate hub models
            self._generate_hubs(project_export.hubs)

            # 6. Generate link models
            self._generate_links(project_export.links)

            # 7. Generate satellite models (v0 and optionally v1)
            self._generate_satellites(project_export.satellites)

            # 7b. Generate record-tracking satellites for flagged hubs/links
            self._generate_record_tracking_satellites(
                project_export.hubs, project_export.links
            )

            # 7c. Generate effectivity satellites for flagged hubs
            self._generate_effectivity_satellites(project_export.hubs)

            # 8. Generate PIT models
            self._generate_pits(project_export.pits)

            # 9. Generate reference table models
            self._generate_reference_tables(project_export.reference_tables)

            # 10. Generate snapshot control models
            self._generate_snapshot_controls(project_export.snapshot_controls)

            # 11. Post-generation validation: check for missing YAML files
            self.report.validate_yaml_files()

            # 12. Prune empty folders
            self._prune_empty_folders()

            logger.info(
                f"Generation complete. {self.report.total_files} files created."
            )

        except Exception as e:
            logger.exception("Generation failed with exception")
            self.report.success = False
            self.report.add_error(
                entity_type="project",
                entity_name=self.config.project_name,
                message=str(e),
                code="GEN_001",
            )

        return self.report

    def _specific_materialization(self, model_kind: str) -> str | None:
        """Materialization to write into a model-specific config() block.

        Models whose nature differs from their layer (see
        `_SPECIFIC_MATERIALIZATIONS`) keep their own materialization while
        `model_specific_materializations` is set: the caller's value from
        `model_materializations`, else the default — unless it equals the
        layer's. Otherwise — and for every other model — None is returned, so
        the model inherits its layer's `+materialized` from dbt_project.yml.
        """
        if (
            not self.config.model_specific_materializations
            or model_kind not in _SPECIFIC_MATERIALIZATIONS
        ):
            return None
        value = self.config.model_materializations.get(
            model_kind, _SPECIFIC_MATERIALIZATIONS[model_kind]
        )
        # A value equal to the layer's adds nothing: leave it to dbt_project.yml.
        layer_value = getattr(
            self.config, f"{_MODEL_LAYERS[model_kind]}_materialization"
        )
        return None if value == layer_value else value

    # ------------------------------------------------------------------
    # Model outputs (names, folders, config) and references between them
    # ------------------------------------------------------------------

    def _resolve_output(self, spec: _ModelSpec) -> _ModelOutput:
        """Resolve one model from its stored attributes, else the defaults.

        A model placed outside its layer's folder no longer gets the layer's
        schema and materialization from dbt_project.yml, so they go into its
        config() unless its attributes set them.
        Raises OutputAttributesError for unusable attributes.
        """
        attributes = (
            dbt_model_attributes(spec.generation_config, spec.kind, spec.entity_type)
            if self.config.use_original_paths
            else DbtModelAttributes()
        )
        directory = (
            self.output_path / "models" / attributes.directory
            if attributes.directory is not None
            else spec.default_dir
        )
        folder_attr, schema_attr, materialization_attr = _LAYERS[spec.layer]
        layer_root = self.output_path / getattr(self.folder_config, folder_attr)
        outside_layer = not directory.is_relative_to(layer_root)

        materialization = (
            attributes.materialized
            or self._specific_materialization(spec.kind)
            or (getattr(self.config, materialization_attr) if outside_layer else None)
        )
        schema = attributes.schema_name or (
            getattr(self.config, schema_attr) if outside_layer else None
        )
        config = {
            key: config_literal(value)
            for key, value in (
                ("alias", attributes.alias),
                ("schema", schema),
                ("database", attributes.database),
                *(attributes.custom_config_json or {}).items(),
            )
            if value is not None
        }
        return _ModelOutput(
            name=attributes.resolved_model_name or spec.default_name,
            directory=directory,
            materialization=materialization,
            config=config,
            tags=None if attributes.tags is None else config_literal(attributes.tags),
        )

    def _output(self, kind: str, key: str) -> _ModelOutput:
        return self._outputs[(kind, key)]

    def _output_name(self, kind: str, key: str, default: str) -> str:
        output = self._outputs.get((kind, key))
        return output.name if output else default

    def _model_specs(self, project_export: ProjectExport) -> list[_ModelSpec]:
        """Every model this export can generate, with its defaults."""
        raw_vault = self.folder_config.get_raw_vault_path
        specs: list[_ModelSpec] = []

        for stage in project_export.stages:
            specs.append(
                _ModelSpec(
                    kind="stage",
                    key=stage.stage_name,
                    entity_type="source_table",
                    entity_name=f"{stage.source_system}.{stage.source_table}",
                    generation_config=stage.generation_config,
                    default_name=stage.stage_name,
                    default_dir=self.folder_config.get_staging_path(
                        stage.source_system, self.output_path
                    ),
                    layer="staging",
                    templates=("stage",),
                )
            )
        for hub in project_export.hubs:
            hub_spec = _ModelSpec(
                kind="hub",
                key=hub.hub_name,
                entity_type="hub",
                entity_name=hub.hub_name,
                generation_config=hub.generation_config,
                default_name=hub.hub_name,
                default_dir=raw_vault(hub.group, self.output_path),
                layer="raw_vault",
                templates=(f"hub_{hub.hub_type}",),
            )
            specs.append(hub_spec)
            has_hashkey = bool(hub.hashkey and hub.hashkey.hashkey_name)
            base_name = _entity_base_name(hub.hub_name)
            if hub.create_record_tracking_satellite and has_hashkey:
                specs.append(
                    replace(
                        hub_spec,
                        kind="record_tracking_satellite",
                        key=f"hub:{hub.hub_name}",
                        default_name=self.config.resolve_entity_name(
                            self.config.record_tracking_satellite_naming, base_name
                        ),
                        templates=("satellite_record_tracking",),
                    )
                )
            if hub.create_effectivity_satellite and has_hashkey and hub.source_tables:
                specs.append(
                    replace(
                        hub_spec,
                        kind="effectivity_satellite",
                        default_name=self.config.resolve_entity_name(
                            self.config.effectivity_satellite_naming, base_name
                        ),
                        templates=("satellite_effectivity",),
                    )
                )
        for link in project_export.links:
            link_spec = _ModelSpec(
                kind="link",
                key=link.link_name,
                entity_type="link",
                entity_name=link.link_name,
                generation_config=link.generation_config,
                default_name=link.link_name,
                default_dir=raw_vault(link.group, self.output_path),
                layer="raw_vault",
                templates=(f"link_{link.link_type}",),
            )
            specs.append(link_spec)
            if (
                link.create_record_tracking_satellite
                and link.hashkey
                and link.hashkey.hashkey_name
            ):
                specs.append(
                    replace(
                        link_spec,
                        kind="record_tracking_satellite",
                        key=f"link:{link.link_name}",
                        default_name=self.config.resolve_entity_name(
                            self.config.record_tracking_satellite_naming,
                            _entity_base_name(link.link_name),
                        ),
                        templates=("satellite_record_tracking",),
                    )
                )
        for satellite in project_export.satellites:
            name = satellite.satellite_name
            v0_template = f"satellite_{satellite.satellite_type}"
            v0_spec = _ModelSpec(
                kind="satellite_v0",
                key=name,
                entity_type="satellite",
                entity_name=name,
                generation_config=satellite.generation_config,
                default_name=self.config.resolve_entity_name(
                    self.config.satellite_v0_naming, name
                ),
                default_dir=raw_vault(satellite.group, self.output_path),
                layer="raw_vault",
                templates=(v0_template,),
            )
            specs.append(v0_spec)
            generates_v1 = (
                self.config.generate_satellite_v1_views
                and satellite.satellite_type in _V1_SATELLITE_TYPES
            )
            # Reference tables refer to the v1 name even when none is generated.
            specs.append(
                replace(
                    v0_spec,
                    kind="satellite_v1",
                    default_name=self.config.resolve_entity_name(
                        self.config.satellite_v1_naming, name
                    ),
                    templates=(v0_template, "satellite_v1") if generates_v1 else (),
                )
            )
        for pit in project_export.pits:
            specs.append(
                _ModelSpec(
                    kind="pit",
                    key=pit.pit_name,
                    entity_type="pit",
                    entity_name=pit.pit_name,
                    generation_config=pit.generation_config,
                    default_name=pit.pit_name,
                    default_dir=self.folder_config.get_business_vault_pits_path(
                        pit.group, self.output_path
                    ),
                    layer="business_vault",
                    templates=("pit",),
                )
            )
        for ref_table in project_export.reference_tables:
            specs.append(
                _ModelSpec(
                    kind="reference_table",
                    key=ref_table.table_name,
                    entity_type="reference_table",
                    entity_name=ref_table.table_name,
                    generation_config=ref_table.generation_config,
                    default_name=ref_table.table_name,
                    default_dir=raw_vault(ref_table.group, self.output_path),
                    layer="raw_vault",
                    templates=("reference_table",),
                )
            )
        for snap_ctrl in project_export.snapshot_controls:
            for kind, default_name in (
                ("snapshot_control_v0", snap_ctrl.v0_name),
                ("snapshot_control_v1", snap_ctrl.v1_name),
            ):
                specs.append(
                    _ModelSpec(
                        kind=kind,
                        key=snap_ctrl.name,
                        entity_type="snapshot_control",
                        entity_name=snap_ctrl.name,
                        generation_config=snap_ctrl.generation_config,
                        default_name=default_name,
                        default_dir=self.folder_config.get_control_path(
                            self.output_path
                        ),
                        layer="control",
                        templates=(kind,),
                    )
                )
        return specs

    def _is_written(self, spec: _ModelSpec) -> bool:
        """Whether generation writes this model's SQL file."""
        return bool(spec.templates) and all(
            self.template_resolver.get_sql_template(template)
            for template in spec.templates
        )

    def _resolve_outputs(self, project_export: ProjectExport) -> bool:
        """Resolve the output of every model this export generates.

        Reports invalid attributes, and models sharing a file path or a model
        name. Returns False when any was found: nothing may be written then.
        """
        valid = True
        seen_paths: dict[str, str] = {}
        seen_names: dict[str, str] = {}
        reported: set[tuple[str, str, str]] = set()
        for spec in self._model_specs(project_export):
            try:
                output = self._resolve_output(spec)
            except OutputAttributesError as e:
                valid = False
                # An entity's config is read for each of its output kinds:
                # report a malformed one once.
                error = (spec.entity_type, spec.entity_name, str(e))
                if error not in reported:
                    reported.add(error)
                    self.report.add_error(
                        entity_type=spec.entity_type,
                        entity_name=spec.entity_name,
                        message=str(e),
                        code="ATTR_001",
                    )
                continue
            self._outputs[(spec.kind, spec.key)] = output
            if not self._is_written(spec):
                continue
            label = f"{spec.entity_type.replace('_', ' ')} '{spec.entity_name}'"
            if spec.kind != spec.entity_type:
                label = f"{spec.kind.replace('_', ' ')} of the {label}"
            relative_path = output.sql_path.relative_to(self.output_path).as_posix()
            for seen, value, what in (
                (seen_paths, relative_path, f"file path {relative_path}"),
                (seen_names, output.name, f"model name {output.name}"),
            ):
                # Case-insensitive: file systems and warehouses often are.
                other = seen.setdefault(value.casefold(), label)
                if other != label:
                    valid = False
                    self.report.add_error(
                        entity_type=spec.entity_type,
                        entity_name=spec.entity_name,
                        message=f"The {label} has the same {what} as the {other}",
                        code="COL_001",
                    )
                    break  # A shared path usually means a shared name too.
        return valid

    def _with_resolved_references(self, project_export: ProjectExport) -> ProjectExport:
        """A copy of the export whose references to other models use their
        resolved names (see `_resolve_outputs`)."""
        export = project_export.model_copy(deep=True)
        for owner in (*export.hubs, *export.links):
            for source in owner.source_tables:
                source.stage_name = self._output_name(
                    "stage", source.stage_name, source.stage_name
                )
        for satellite in export.satellites:
            satellite.stage_name = self._output_name(
                "stage", satellite.stage_name, satellite.stage_name
            )
        snapshot_v1_names = {
            snap_ctrl.v1_name: self._output_name(
                "snapshot_control_v1", snap_ctrl.name, snap_ctrl.v1_name
            )
            for snap_ctrl in export.snapshot_controls
        }
        for pit in export.pits:
            pit.tracked_entity_name = self._output_name(
                pit.tracked_entity_type,
                pit.tracked_entity_name,
                pit.tracked_entity_name,
            )
            pit.snapshot_control_name = snapshot_v1_names.get(
                pit.snapshot_control_name, pit.snapshot_control_name
            )
        for ref_table in export.reference_tables:
            ref_table.reference_hub_name = self._output_name(
                "hub", ref_table.reference_hub_name, ref_table.reference_hub_name
            )
        return export

    def _satellite_model_name(self, kind: str, satellite_name: str) -> str:
        """The resolved v0 or v1 model name of a satellite.

        Falls back to the naming pattern for a satellite not in this run
        (e.g. left out by an entity selection).
        """
        naming = (
            self.config.satellite_v0_naming
            if kind == "satellite_v0"
            else self.config.satellite_v1_naming
        )
        return self._output_name(
            kind,
            satellite_name,
            self.config.resolve_entity_name(naming, satellite_name),
        )

    def _write_model(
        self,
        output: _ModelOutput,
        entity_type: str,
        sql_template: Template | None,
        yaml_template: Template | None,
        context: Mapping[str, Any],
        references: Iterable[str] = (),
    ) -> None:
        """Render and write a model's SQL and YAML files.

        `references` are the resolved names of models the SQL must refer to.
        A template that drops one of them, or a stored config() setting, gets
        a warning: it predates (or was customized past) the hooks for stored
        output attributes, so the generated model would not match them.
        """
        context = {**context, **output.template_context()}
        ignored: list[str] = []
        if sql_template:
            sql = sql_template.render(**context)
            write_sql_file(output.sql_path, sql)
            self.report.add_file(output.sql_path, entity_type, output.name, "sql")
            ignored += [
                f"config {key}"
                for key, value in output.config.items()
                if f"{key}={value}" not in sql
            ]
            if output.tags is not None and f"tags={output.tags}" not in sql:
                ignored.append("tags")
            ignored += [
                f"reference to {name}" for name in references if name not in sql
            ]
        if yaml_template:
            path = output.directory / get_model_filename(output.name, extension="yml")
            yaml = yaml_template.render(**context)
            write_yaml_file(path, yaml)
            self.report.add_file(path, entity_type, output.name, "yaml")
            if f"name: {output.name}" not in yaml:
                ignored.append("model name in the YAML")
            if output.tags is not None and output.tags not in yaml:
                ignored.append("tags in the YAML")
        if ignored:
            self.report.add_warning(
                entity_type=entity_type,
                entity_name=output.name,
                message=(
                    f"The {entity_type} template ignores: {', '.join(ignored)}. "
                    "It lacks the hooks for stored output attributes and naming "
                    "patterns; compare it with the bundled template."
                ),
                code="TPL_003",
            )

    def _create_folder_structure(self) -> None:
        """Create the dbt project directory structure."""
        self.folder_config.create_project_structure(self.output_path)
        logger.debug("Created folder structure")

    def _prune_empty_folders(self) -> None:
        """Remove empty directories from the generated project."""
        # Walk the output path from the bottom up
        for dirpath, dirnames, filenames in os.walk(self.output_path, topdown=False):
            # An empty directory has no subdirectories and no files
            if not dirnames and not filenames:
                try:
                    os.rmdir(dirpath)
                    logger.debug(f"Removed empty directory: {dirpath}")
                except OSError as e:
                    # Log an error if the directory could not be removed
                    logger.error(f"Error removing directory {dirpath}: {e}")

    def _generate_project_files(
        self, vars_block: str = "", profiles_content: str | None = None
    ) -> None:
        """Generate dbt_project.yml, packages.yml and the optional profiles.yml.

        `vars_block` is the already-rendered `vars:` section and
        `profiles_content` the already-rendered profiles.yml, or None when not
        requested (see `generate()`, which resolves both up front so an invalid
        value fails before any file is written).
        """
        # Generate dbt_project.yml
        template = self.template_resolver.get_project_template("dbt_project.yml")
        if template:
            content = template.render(
                project_name=self.config.project_name,
                profile_name=self.config.profile_name,
                stage_schema=self.config.stage_schema,
                rdv_schema=self.config.rdv_schema,
                bdv_schema=self.config.bdv_schema,
                control_schema=self.config.control_schema,
                control_materialization=self.config.control_materialization,
                staging_materialization=self.config.staging_materialization,
                raw_vault_materialization=self.config.raw_vault_materialization,
                business_vault_materialization=(
                    self.config.business_vault_materialization
                ),
                vars_block=vars_block,
            )
            path = self.output_path / "dbt_project.yml"
            write_yaml_file(path, content)
            self.report.add_file(path, "project", "dbt_project", "yaml")
            logger.debug("Generated dbt_project.yml")
        else:
            self.report.add_warning(
                entity_type="project",
                entity_name="dbt_project.yml",
                message="Template not found, skipping",
                code="TPL_001",
            )

        # Generate packages.yml
        template = self.template_resolver.get_project_template("packages.yml")
        if template:
            content = template.render()
            path = self.output_path / "packages.yml"
            write_yaml_file(path, content)
            self.report.add_file(path, "project", "packages", "yaml")
            logger.debug("Generated packages.yml")
        else:
            self.report.add_warning(
                entity_type="project",
                entity_name="packages.yml",
                message="Template not found, skipping",
                code="TPL_001",
            )

        # Generate profiles.yml (opt-in)
        if profiles_content is not None:
            path = self.output_path / "profiles.yml"
            write_yaml_file(path, profiles_content)
            self.report.add_file(path, "project", "profiles", "yaml")
            logger.debug("Generated profiles.yml")

    def _generate_sources(self, sources: list) -> None:
        """Generate sources.yml with all source systems."""
        if not sources:
            logger.debug("No sources to generate")
            return

        template = self.template_resolver.get_project_template("sources.yml")

        for source in sources:
            source_name = self.folder_config._sanitize_name(source.name)
            if template:
                content = template.render(source=source)
                path = (
                    self.folder_config.get_source_path(self.output_path)
                    / f"source__{source_name}.yml"
                )
                write_yaml_file(path, content)
                self.report.add_file(path, "source", f"source__{source_name}", "yaml")
                logger.debug(
                    f"Generated 'source__{source_name}' with {len(source.tables)} tables"
                )
            else:
                self.report.add_warning(
                    entity_type="source",
                    entity_name=f"source__{source_name}",
                    message="Template not found, skipping",
                    code="TPL_001",
                )

    def _generate_stages(self, stages: list[StageDefinition]) -> None:
        """Generate stage SQL and YAML models."""
        if not stages:
            logger.debug("No stages to generate")
            return

        sql_template, yaml_template = self.template_resolver.get_templates("stage")

        for stage in stages:
            try:
                output = self._output("stage", stage.stage_name)
                context = {**stage.model_dump(), "stage_name": output.name}
                self._write_model(output, "stage", sql_template, yaml_template, context)
                self.report.stages_generated += 1

            except Exception as e:
                logger.warning(f"Failed to generate stage {stage.stage_name}: {e}")
                self.report.add_error(
                    entity_type="stage",
                    entity_name=stage.stage_name,
                    message=str(e),
                    code="STG_001",
                )

    def _generate_hubs(self, hubs: list[HubDefinition]) -> None:
        """Generate hub SQL and YAML models."""
        if not hubs:
            logger.debug("No hubs to generate")
            return

        for hub in hubs:
            try:
                # Determine entity type based on hub type
                entity_type = f"hub_{hub.hub_type}"
                sql_template, yaml_template = self.template_resolver.get_templates(
                    entity_type
                )

                if not sql_template:
                    self.report.add_skipped(
                        entity_type=entity_type,
                        entity_name=hub.hub_name,
                        reason=f"No template found for {entity_type}",
                    )
                    continue

                output = self._output("hub", hub.hub_name)
                context = {**hub.model_dump(), "hub_name": output.name}
                self._write_model(
                    output, entity_type, sql_template, yaml_template, context
                )
                self.report.hubs_generated += 1

            except Exception as e:
                logger.warning(f"Failed to generate hub {hub.hub_name}: {e}")
                self.report.add_error(
                    entity_type="hub",
                    entity_name=hub.hub_name,
                    message=str(e),
                    code="HUB_001",
                )

    def _generate_links(self, links: list[LinkDefinition]) -> None:
        """Generate link SQL and YAML models."""
        if not links:
            logger.debug("No links to generate")
            return

        for link in links:
            try:
                # Determine entity type based on link type
                entity_type = f"link_{link.link_type}"
                sql_template, yaml_template = self.template_resolver.get_templates(
                    entity_type
                )

                if not sql_template:
                    self.report.add_skipped(
                        entity_type=entity_type,
                        entity_name=link.link_name,
                        reason=f"No template found for {entity_type}",
                    )
                    continue

                output = self._output("link", link.link_name)
                context = {**link.model_dump(), "link_name": output.name}
                self._write_model(
                    output, entity_type, sql_template, yaml_template, context
                )
                self.report.links_generated += 1

            except Exception as e:
                logger.warning(f"Failed to generate link {link.link_name}: {e}")
                self.report.add_error(
                    entity_type="link",
                    entity_name=link.link_name,
                    message=str(e),
                    code="LNK_001",
                )

    def _generate_satellites(self, satellites: list[SatelliteDefinition]) -> None:
        """Generate satellite SQL and YAML models (v0 and optionally v1)."""
        if not satellites:
            logger.debug("No satellites to generate")
            return

        generate_v1 = self.config.generate_satellite_v1_views

        for satellite in satellites:
            try:
                # Get template for satellite type
                entity_type = f"satellite_{satellite.satellite_type}"
                sql_template, yaml_template = self.template_resolver.get_templates(
                    entity_type
                )

                if not sql_template:
                    self.report.add_skipped(
                        entity_type=entity_type,
                        entity_name=satellite.satellite_name,
                        reason=f"No template found for {entity_type}",
                    )
                    continue

                output = self._output("satellite_v0", satellite.satellite_name)
                context = satellite.model_dump()
                context["satellite_name"] = output.name  # Override with v0 name
                self._write_model(
                    output, entity_type, sql_template, yaml_template, context
                )
                self.report.satellites_generated += 1

                # Generate v1 view if enabled and satellite type supports it
                if generate_v1 and satellite.satellite_type in _V1_SATELLITE_TYPES:
                    self._generate_satellite_v1(satellite, output.name)

            except Exception as e:
                logger.warning(
                    f"Failed to generate satellite {satellite.satellite_name}: {e}"
                )
                self.report.add_error(
                    entity_type="satellite",
                    entity_name=satellite.satellite_name,
                    message=str(e),
                    code="SAT_001",
                )

    def _generate_satellite_v1(
        self, satellite: SatelliteDefinition, v0_name: str
    ) -> None:
        """Generate satellite v1 view (load_end_date view)."""
        sql_template, yaml_template = self.template_resolver.get_templates(
            "satellite_v1"
        )

        if not sql_template:
            self.report.add_warning(
                entity_type="satellite_v1",
                entity_name=satellite.satellite_name,
                message="Template not found for satellite_v1, skipping v1 view",
                code="TPL_002",
            )
            return

        output = self._output("satellite_v1", satellite.satellite_name)

        # Build context for v1 template
        context = satellite.model_dump()
        context["satellite_name"] = satellite.satellite_name  # For template logic
        context["v0_name"] = v0_name

        try:
            self._write_model(
                output,
                "satellite_v1",
                sql_template,
                yaml_template,
                context,
                references=[v0_name],
            )
            self.report.satellite_views_generated += 1

        except Exception as e:
            logger.warning(f"Failed to generate satellite v1 {output.name}: {e}")
            self.report.add_warning(
                entity_type="satellite_v1",
                entity_name=output.name,
                message=str(e),
                code="SAT_002",
            )

    def _generate_record_tracking_satellites(
        self,
        hubs: list[HubDefinition],
        links: list[LinkDefinition],
    ) -> None:
        """Generate a record-tracking satellite for each flagged hub and link."""
        # Collect flagged parents as (key, name, group, hashkey_name, source_tables).
        parents: list[tuple[str, str, str | None, str | None, list]] = []
        for hub in hubs:
            if getattr(hub, "create_record_tracking_satellite", False):
                hashkey_name = hub.hashkey.hashkey_name if hub.hashkey else None
                parents.append(
                    (
                        f"hub:{hub.hub_name}",
                        hub.hub_name,
                        hub.group,
                        hashkey_name,
                        hub.source_tables,
                    )
                )
        for link in links:
            if getattr(link, "create_record_tracking_satellite", False):
                hashkey_name = link.hashkey.hashkey_name if link.hashkey else None
                parents.append(
                    (
                        f"link:{link.link_name}",
                        link.link_name,
                        link.group,
                        hashkey_name,
                        link.source_tables,
                    )
                )

        if not parents:
            return

        sql_template, yaml_template = self.template_resolver.get_templates(
            "satellite_record_tracking"
        )
        if not sql_template:
            for _, parent_name, *_ in parents:
                self.report.add_skipped(
                    entity_type="satellite_record_tracking",
                    entity_name=parent_name,
                    reason="No template found for satellite_record_tracking",
                )
            return

        for key, parent_name, group, hashkey_name, source_tables in parents:
            if not hashkey_name:
                self.report.add_skipped(
                    entity_type="satellite_record_tracking",
                    entity_name=parent_name,
                    reason="Parent has no hashkey; cannot track records",
                )
                continue

            try:
                output = self._output("record_tracking_satellite", key)
                context = {
                    "satellite_name": output.name,
                    "parent_entity": parent_name,
                    "parent_hashkey": hashkey_name,
                    "group": group,
                    "source_tables": [st.model_dump() for st in source_tables],
                }
                self._write_model(
                    output,
                    "satellite_record_tracking",
                    sql_template,
                    yaml_template,
                    context,
                )
                self.report.record_tracking_satellites_generated += 1

            except Exception as e:
                logger.warning(
                    f"Failed to generate record-tracking satellite for "
                    f"{parent_name}: {e}"
                )
                self.report.add_error(
                    entity_type="satellite_record_tracking",
                    entity_name=parent_name,
                    message=str(e),
                    code="RTS_001",
                )

    def _generate_effectivity_satellites(self, hubs: list[HubDefinition]) -> None:
        """Generate an effectivity satellite for each flagged hub."""
        flagged = [
            hub for hub in hubs if getattr(hub, "create_effectivity_satellite", False)
        ]
        if not flagged:
            return

        sql_template, yaml_template = self.template_resolver.get_templates(
            "satellite_effectivity"
        )
        if not sql_template:
            for hub in flagged:
                self.report.add_skipped(
                    entity_type="satellite_effectivity",
                    entity_name=hub.hub_name,
                    reason="No template found for satellite_effectivity",
                )
            return

        for hub in flagged:
            hashkey_name = hub.hashkey.hashkey_name if hub.hashkey else None
            stage_name = hub.source_tables[0].stage_name if hub.source_tables else None
            if not hashkey_name or not stage_name:
                self.report.add_skipped(
                    entity_type="satellite_effectivity",
                    entity_name=hub.hub_name,
                    reason="Hub has no hashkey or source stage; cannot track effectivity",
                )
                continue

            try:
                output = self._output("effectivity_satellite", hub.hub_name)
                context = {
                    "satellite_name": output.name,
                    "parent_entity": hub.hub_name,
                    "parent_hashkey": hashkey_name,
                    "stage_name": stage_name,
                    "group": hub.group,
                }
                self._write_model(
                    output,
                    "satellite_effectivity",
                    sql_template,
                    yaml_template,
                    context,
                )
                self.report.effectivity_satellites_generated += 1

            except Exception as e:
                logger.warning(
                    f"Failed to generate effectivity satellite for {hub.hub_name}: {e}"
                )
                self.report.add_error(
                    entity_type="satellite_effectivity",
                    entity_name=hub.hub_name,
                    message=str(e),
                    code="EFS_001",
                )

    def _generate_pits(self, pits: list[PITDefinition]) -> None:
        """Generate PIT SQL and YAML models."""
        if not pits:
            logger.debug("No PITs to generate")
            return

        sql_template, yaml_template = self.template_resolver.get_templates("pit")

        if not sql_template:
            self.report.add_warning(
                entity_type="pit",
                entity_name="*",
                message="PIT template not found, skipping all PITs",
                code="TPL_001",
            )
            return

        for pit in pits:
            try:
                output = self._output("pit", pit.pit_name)
                context = {
                    **pit.model_dump(),
                    "pit_name": output.name,
                    # The v0 model of each satellite, in `satellites` order.
                    "satellite_models": [
                        self._satellite_model_name("satellite_v0", satellite)
                        for satellite in pit.satellites
                    ],
                }
                self._write_model(
                    output,
                    "pit",
                    sql_template,
                    yaml_template,
                    context,
                    references=context["satellite_models"],
                )
                self.report.pits_generated += 1

            except Exception as e:
                logger.warning(f"Failed to generate PIT {pit.pit_name}: {e}")
                self.report.add_error(
                    entity_type="pit",
                    entity_name=pit.pit_name,
                    message=str(e),
                    code="PIT_001",
                )

    def _generate_reference_tables(
        self, ref_tables: list[ReferenceTableDefinition]
    ) -> None:
        """Generate reference table SQL and YAML models."""
        if not ref_tables:
            logger.debug("No reference tables to generate")
            return

        sql_template, yaml_template = self.template_resolver.get_templates(
            "reference_table"
        )

        if not sql_template:
            self.report.add_warning(
                entity_type="reference_table",
                entity_name="*",
                message="Reference table template not found, skipping all",
                code="TPL_001",
            )
            return

        for ref_table in ref_tables:
            try:
                output = self._output("reference_table", ref_table.table_name)
                context = {
                    **ref_table.model_dump(),
                    "table_name": output.name,
                    # The v1 model of each satellite, by satellite name.
                    "satellite_models": {
                        assignment.satellite_name: self._satellite_model_name(
                            "satellite_v1", assignment.satellite_name
                        )
                        for assignment in ref_table.satellites
                    },
                }
                self._write_model(
                    output,
                    "reference_table",
                    sql_template,
                    yaml_template,
                    context,
                    references=context["satellite_models"].values(),
                )
                self.report.reference_tables_generated += 1

            except Exception as e:
                logger.warning(
                    f"Failed to generate reference table {ref_table.table_name}: {e}"
                )
                self.report.add_error(
                    entity_type="reference_table",
                    entity_name=ref_table.table_name,
                    message=str(e),
                    code="REF_001",
                )

    def _generate_snapshot_controls(
        self, snapshot_controls: list[SnapshotControlDefinition]
    ) -> None:
        """Generate snapshot control v0 and v1 models."""
        if not snapshot_controls:
            logger.debug("No snapshot controls to generate")
            return

        # Get templates for v0 (control table) and v1 (control logic)
        v0_sql_template, v0_yaml_template = self.template_resolver.get_templates(
            "snapshot_control_v0"
        )
        v1_sql_template, v1_yaml_template = self.template_resolver.get_templates(
            "snapshot_control_v1"
        )

        for snap_ctrl in snapshot_controls:
            try:
                v0_output = self._output("snapshot_control_v0", snap_ctrl.name)
                v1_output = self._output("snapshot_control_v1", snap_ctrl.name)
                context = {
                    **snap_ctrl.model_dump(),
                    "control_v0_name": v0_output.name,
                }

                # Generate v0 model (control table)
                if v0_sql_template:
                    self._write_model(
                        v0_output,
                        "snapshot_control_v0",
                        v0_sql_template,
                        v0_yaml_template,
                        context,
                    )

                # Generate v1 model (control logic)
                if v1_sql_template:
                    self._write_model(
                        v1_output,
                        "snapshot_control_v1",
                        v1_sql_template,
                        v1_yaml_template,
                        context,
                        references=[v0_output.name],
                    )

                self.report.snapshot_controls_generated += 1

            except Exception as e:
                logger.warning(
                    f"Failed to generate snapshot control {snap_ctrl.name}: {e}"
                )
                self.report.add_error(
                    entity_type="snapshot_control",
                    entity_name=snap_ctrl.name,
                    message=str(e),
                    code="SNAP_001",
                )
