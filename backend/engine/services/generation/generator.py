"""
dbt project generator.

Main module for generating complete dbt projects from TurboVault export data.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from engine.models.model_output import folder_error, normalize_folder
from engine.services.config_schema import MODEL_MATERIALIZATION_DEFAULTS
from engine.services.export.model_outputs import entity_base_name, satellite_pattern

from .file_writer import write_sql_file, write_yaml_file
from .folder_config import GenerationConfig, get_model_filename
from .model_config import LayerDefaults, ModelConfig
from .profiles_yml import LiteralSecretError, render_profiles_yml
from .report import GenerationReport
from .template_resolver import TemplateResolver
from .vars_block import render_vars_block

if TYPE_CHECKING:
    from jinja2 import Template

    from engine.services.export.models import (
        HubDefinition,
        LinkDefinition,
        ModelOutputDef,
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

_OUTDATED_TEMPLATE_HINT = (
    "`python manage.py populate_templates --overwrite` refreshes the workspace's "
    "copies (and replaces their customizations)."
)


def _file_name_error(model_name: str) -> str | None:
    """Why *model_name* can't name a file inside the project, or None."""
    if (
        not model_name
        or model_name in (".", "..")
        or any(char in model_name for char in "/\\\x00")
    ):
        return f"'{model_name}' can't name a model file: no slashes or '..'"
    return None


def _in_folder_of(
    output: ModelOutputDef | None, other: ModelOutputDef | None
) -> ModelOutputDef | None:
    """*output*, placed in *other*'s folder when it has no folder of its own.

    A satellite v1 view follows its v0 table, an effectivity or
    record-tracking satellite its parent, a snapshot control's logic its table.
    """
    if output is None or output.folder or other is None or not other.folder:
        return output
    return output.model_copy(update={"folder": other.folder})


def _model_outputs(project_export: ProjectExport) -> Iterable[ModelOutputDef]:
    """Every resolved model output the export carries."""
    for stage in project_export.stages:
        yield from filter(None, (stage.output,))
    for hub in project_export.hubs:
        yield from filter(
            None,
            (
                hub.output,
                hub.effectivity_satellite_output,
                hub.record_tracking_satellite_output,
            ),
        )
    for link in project_export.links:
        yield from filter(
            None,
            (
                link.output,
                link.effectivity_satellite_output,
                link.record_tracking_satellite_output,
            ),
        )
    for satellite in project_export.satellites:
        yield from filter(None, (satellite.v0_output, satellite.v1_output))
    for pit in project_export.pits:
        yield from filter(None, (pit.output,))
    for table in project_export.reference_tables:
        yield from filter(None, (table.output,))
    for control in project_export.snapshot_controls:
        yield from filter(None, (control.v0_output, control.v1_output))


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

        # Initialize report
        self.report = GenerationReport(project_path=self.output_path)

    def generate(self, project_export: ProjectExport) -> GenerationReport:
        """
        Generate complete dbt project from export data.

        Args:
            project_export: The project export containing all entity definitions.

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

        try:
            # 1. Create folder structure
            self._create_folder_structure()

            # 2. Generate project-level files
            self._generate_project_files(
                vars_block,
                profiles_content,
                has_prestages=bool(project_export.prestages),
                model_paths=self._model_paths(project_export),
            )

            # 3. Generate sources.yml
            self._generate_sources(project_export.sources)

            # 4. Generate stage models. Pre-stages are the dbt project's own:
            # their stages read them, and the report says where they must be.
            self._generate_stages(project_export.stages)
            self._report_prestages(project_export)

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

            # 7c. Generate effectivity satellites for flagged hubs and links
            self._generate_effectivity_satellites(
                project_export.hubs, project_export.links
            )

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
        if not self.config.model_specific_materializations:
            return None
        value = self.config.model_materializations.get(
            model_kind, _SPECIFIC_MATERIALIZATIONS[model_kind]
        )
        # A value equal to the layer's adds nothing: leave it to dbt_project.yml.
        layer_value = getattr(
            self.config, f"{_MODEL_LAYERS[model_kind]}_materialization"
        )
        return None if value == layer_value else value

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

    def _prestaging_materialization(self) -> str:
        """Materialization of the pre-stage layer: the staging layer's.

        The stage reads a pre-stage's columns from the database, where an
        ephemeral model doesn't exist, so an ephemeral staging layer gives views.
        """
        materialization = self.config.staging_materialization
        return "view" if materialization == "ephemeral" else materialization

    # -- model outputs -----------------------------------------------------

    def _layer_folder(self, layer: str) -> str:
        """A layer's folder, relative to the project (e.g. models/30_raw_vault)."""
        folders = self.folder_config
        return {
            "staging": folders.staging_path,
            "raw_vault": folders.raw_vault_path,
            "business_vault": folders.business_vault_path,
            "control": folders.control_path,
        }[layer]

    def _layer_defaults(self, layer: str) -> LayerDefaults:
        """The schema and materialization dbt_project.yml gives a layer's folder."""
        schemas = {
            "staging": self.config.stage_schema,
            "raw_vault": self.config.rdv_schema,
            "business_vault": self.config.bdv_schema,
            "control": self.config.control_schema,
        }
        return LayerDefaults(
            materialized=getattr(self.config, f"{layer}_materialization"),
            schema=schemas[layer],
        )

    def _stored_folder(self, output: ModelOutputDef | None) -> str | None:
        """The folder stored for a model, or None for its layer's folder."""
        if not self.config.use_model_folders or output is None or not output.folder:
            return None
        if error := folder_error(output.folder):
            raise ValueError(error)
        return normalize_folder(output.folder) or None

    def _placement(
        self, output: ModelOutputDef | None, default_dir: Path, layer: str
    ) -> tuple[Path, ModelConfig]:
        """Where a model's files go, and the settings of its config() block.

        A model stored in a folder outside its layer's folder misses the
        layer's settings in dbt_project.yml, so its config() gets them.
        """
        folder = self._stored_folder(output)
        if folder is None:
            return default_dir, ModelConfig(output)
        layer_folder = self._layer_folder(layer)
        inside = folder == layer_folder or folder.startswith(f"{layer_folder}/")
        layer_defaults = None if inside else self._layer_defaults(layer)
        return self.output_path / folder, ModelConfig(output, layer_defaults)

    def _model_paths(self, project_export: ProjectExport) -> list[str]:
        """dbt_project.yml's model-paths: models, plus stored folders' tops."""
        paths = ["models"]
        if not self.config.use_model_folders:
            return paths
        for output in _model_outputs(project_export):
            if output.folder and not folder_error(output.folder):
                parts = PurePosixPath(normalize_folder(output.folder)).parts
                if parts and parts[0] not in paths:
                    paths.append(parts[0])
        return paths

    def _write_model(
        self,
        *,
        entity_type: str,
        model_name: str,
        directory: Path,
        sql_template: Template | None,
        yaml_template: Template | None,
        context: dict[str, Any],
        model_config: ModelConfig,
        sql_context: dict[str, Any] | None = None,
        references: Iterable[str] = (),
    ) -> str | None:
        """Render and write a model's SQL and YAML files; return the SQL.

        *references* are the models the SQL must name (a v1 view's v0 table,
        a PIT's satellites, ...): a template that doesn't is outdated.
        """
        if error := _file_name_error(model_name):
            raise ValueError(error)
        context = {**context, **model_config.context()}
        sql_content = yaml_content = None
        if sql_template is not None:
            sql_content = sql_template.render(**{**context, **(sql_context or {})})
            path = directory / get_model_filename(model_name, extension="sql")
            write_sql_file(path, sql_content)
            self.report.add_file(path, entity_type, model_name, "sql")
        if yaml_template is not None:
            yaml_content = yaml_template.render(**context)
            path = directory / get_model_filename(model_name, extension="yml")
            write_yaml_file(path, yaml_content)
            self.report.add_file(path, entity_type, model_name, "yaml")
        self._check_model_templates(
            entity_type, model_name, model_config, sql_content, yaml_content, references
        )
        return sql_content

    def _check_model_templates(
        self,
        entity_type: str,
        model_name: str,
        model_config: ModelConfig,
        sql_content: str | None,
        yaml_content: str | None,
        references: Iterable[str],
    ) -> None:
        """Warn when a template ignores the model's stored names or settings.

        A workspace's copies of the templates take precedence over the bundled
        ones. Copies made before model outputs existed write fixed config()
        blocks and append _v0/_v1 to satellite names.
        """
        problems = []
        if (
            sql_content is not None
            and model_config.needs_config
            and not model_config.config_used
        ):
            problems.append(
                "write the model's stored dbt settings (alias, schema, tags, ... "
                "or its folder's layer settings)"
            )
        if (
            yaml_content is not None
            and model_config.needs_tags
            and not model_config.tags_used
        ):
            problems.append("write the model's stored tags into its YAML")
        if sql_content is not None:
            missing = [name for name in references if name and name not in sql_content]
            if missing:
                problems.append(
                    "reference " + ", ".join(f"'{name}'" for name in missing)
                )
        if yaml_content is not None and model_name not in yaml_content:
            problems.append(f"name the model '{model_name}' in its YAML")
        if problems:
            self.report.add_warning(
                entity_type=entity_type,
                entity_name=model_name,
                message=(
                    f"The {entity_type} template doesn't {' or '.join(problems)}: "
                    "it predates stored model names and settings. Update the "
                    f"template: {_OUTDATED_TEMPLATE_HINT}"
                ),
                code="TPL_003",
            )

    def _generate_project_files(
        self,
        vars_block: str = "",
        profiles_content: str | None = None,
        has_prestages: bool = False,
        model_paths: list[str] | None = None,
    ) -> None:
        """Generate dbt_project.yml, packages.yml and the optional profiles.yml.

        `vars_block` is the already-rendered `vars:` section and
        `profiles_content` the already-rendered profiles.yml, or None when not
        requested (see `generate()`, which resolves both up front so an invalid
        value fails before any file is written). The pre-stage layer is only
        configured when the project `has_prestages`: the dbt project's
        pre-stage models placed there get the staging layer's settings.
        `model_paths` are the project's `model-paths` (default: models).
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
                prestaging_materialization=(
                    self._prestaging_materialization() if has_prestages else None
                ),
                model_paths=model_paths or ["models"],
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
            # Pre-stages are dbt models, not sources: their stages ref() them.
            physical_tables = [t for t in source.tables if t.table_type != "prestage"]
            if source.tables and not physical_tables:
                continue
            source = source.model_copy(update={"tables": physical_tables})
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

    def _report_prestages(self, project_export: ProjectExport) -> None:
        """Warn once per pre-stage that the dbt project must contain its model.

        TurboVault generates no file for a pre-stage: the model belongs to the
        dbt project and its developers. The generated stage reads it with
        ``ref()``, which only resolves inside the dbt project that has it.
        """
        stage_of = {
            stage.prestage_model: stage.stage_name
            for stage in project_export.stages
            if stage.prestage_model
        }
        for prestage in project_export.prestages:
            stage = stage_of.get(prestage.model_name)
            reader = f"stage '{stage}' reads" if stage else "its stage reads"
            self.report.add_warning(
                entity_type="prestage",
                entity_name=prestage.model_name,
                message=(
                    f"Pre-stage '{prestage.model_name}' isn't generated: it is a "
                    f"model of your dbt project, and {reader} it with ref(). "
                    "Generate into the dbt project that contains this model; "
                    "anywhere else dbt won't find it."
                ),
                code="PST_001",
            )

    def _check_prestage_support(self, stage: StageDefinition, content: str) -> None:
        """Warn when the stage template doesn't know pre-stages.

        A workspace's copies of the templates take precedence over the bundled
        ones. A copy made before pre-stages existed reads every table as a dbt
        source, which a pre-stage isn't: dbt would fail to find the source.
        """
        unsupported = []
        if stage.prestage_model and stage.prestage_model not in content:
            unsupported.append(f"read the pre-stage model '{stage.prestage_model}'")
        if any(
            prejoin.target_model and prejoin.target_model not in content
            for prejoin in stage.prejoins
        ):
            unsupported.append("prejoin a pre-stage model")
        if unsupported:
            self.report.add_warning(
                entity_type="stage",
                entity_name=stage.stage_name,
                message=(
                    f"The stage template doesn't {' or '.join(unsupported)}: it "
                    "predates pre-stages. Update the stage template: "
                    "`python manage.py populate_templates --overwrite` refreshes the "
                    "workspace's copies (and replaces their customizations)."
                ),
                code="TPL_003",
            )

    def _generate_stages(self, stages: list[StageDefinition]) -> None:
        """Generate stage SQL and YAML models."""
        if not stages:
            logger.debug("No stages to generate")
            return

        sql_template, yaml_template = self.template_resolver.get_templates("stage")

        for stage in stages:
            try:
                # Standard folder: one per source system
                directory, model_config = self._placement(
                    stage.output,
                    self.folder_config.get_staging_path(
                        stage.source_system, self.output_path
                    ),
                    "staging",
                )
                content = self._write_model(
                    entity_type="stage",
                    model_name=stage.stage_name,
                    directory=directory,
                    sql_template=sql_template,
                    yaml_template=yaml_template,
                    context=stage.model_dump(),
                    model_config=model_config,
                )
                if content is not None:
                    self._check_prestage_support(stage, content)

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

                # Standard folder: the raw vault layer's, per group
                directory, model_config = self._placement(
                    hub.output,
                    self.folder_config.get_raw_vault_path(hub.group, self.output_path),
                    "raw_vault",
                )
                self._write_model(
                    entity_type=entity_type,
                    model_name=hub.hub_name,
                    directory=directory,
                    sql_template=sql_template,
                    yaml_template=yaml_template,
                    context=hub.model_dump(),
                    model_config=model_config,
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

                # Standard folder: the raw vault layer's, per group
                directory, model_config = self._placement(
                    link.output,
                    self.folder_config.get_raw_vault_path(link.group, self.output_path),
                    "raw_vault",
                )
                self._write_model(
                    entity_type=entity_type,
                    model_name=link.link_name,
                    directory=directory,
                    sql_template=sql_template,
                    yaml_template=yaml_template,
                    context=link.model_dump(),
                    model_config=model_config,
                    # A template copy from before they were selected misses them
                    references=link.dependent_child_keys,
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

                # The v0 model: its stored name, else the v0 naming pattern
                v0_name = (
                    satellite.v0_output.model_name
                    if satellite.v0_output
                    else satellite_pattern(
                        self.config.satellite_v0_naming, satellite.satellite_name
                    )
                )
                # Standard folder: the raw vault layer's, per group
                default_dir = self.folder_config.get_raw_vault_path(
                    satellite.group, self.output_path
                )
                directory, model_config = self._placement(
                    satellite.v0_output, default_dir, "raw_vault"
                )

                # Templates name the v0 model satellite_name
                context = satellite.model_dump()
                context["satellite_name"] = v0_name
                self._write_model(
                    entity_type=entity_type,
                    model_name=v0_name,
                    directory=directory,
                    sql_template=sql_template,
                    yaml_template=yaml_template,
                    context=context,
                    model_config=model_config,
                )

                self.report.satellites_generated += 1

                # The v1 view: the satellite's own setting, else the project's
                if satellite.gets_v1_view(generate_v1):
                    self._generate_satellite_v1(satellite, default_dir, v0_name)

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
        self,
        satellite: SatelliteDefinition,
        default_dir: Path,
        v0_name: str,
    ) -> None:
        """Generate satellite v1 view (load_end_date view).

        Without a folder of its own, the view goes where its v0 table goes.
        """
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

        # The view's model: its stored name, else the v1 naming pattern
        base_name = satellite.satellite_name
        output = satellite.v1_output
        v1_name = (
            output.model_name
            if output
            else satellite_pattern(self.config.satellite_v1_naming, base_name)
        )
        output = _in_folder_of(output, satellite.v0_output)

        # Build context for v1 template
        context = satellite.model_dump()
        context["satellite_name"] = base_name  # Original name for template logic
        context["v0_name"] = v0_name
        context["v1_name"] = v1_name

        try:
            directory, model_config = self._placement(output, default_dir, "raw_vault")
            self._write_model(
                entity_type="satellite_v1",
                model_name=v1_name,
                directory=directory,
                sql_template=sql_template,
                yaml_template=yaml_template,
                context=context,
                model_config=model_config,
                sql_context={
                    "materialization": self._specific_materialization("satellite_v1")
                },
                references=[v0_name],
            )

            self.report.satellite_views_generated += 1

        except Exception as e:
            logger.warning(f"Failed to generate satellite v1 {v1_name}: {e}")
            self.report.add_warning(
                entity_type="satellite_v1",
                entity_name=v1_name,
                message=str(e),
                code="SAT_002",
            )

    def _generate_record_tracking_satellites(
        self,
        hubs: list[HubDefinition],
        links: list[LinkDefinition],
    ) -> None:
        """Generate a record-tracking satellite for each flagged hub and link.

        Without a folder of its own, the satellite goes where its parent goes.
        """
        # Collect flagged parents as (name, group, hashkey_name, source_tables,
        # the satellite's output, in its parent's folder unless it has one).
        parents: list[
            tuple[str, str | None, str | None, list, ModelOutputDef | None]
        ] = []
        for hub in hubs:
            if getattr(hub, "create_record_tracking_satellite", False):
                hashkey_name = hub.hashkey.hashkey_name if hub.hashkey else None
                parents.append(
                    (
                        hub.hub_name,
                        hub.group,
                        hashkey_name,
                        hub.source_tables,
                        _in_folder_of(hub.record_tracking_satellite_output, hub.output),
                    )
                )
        for link in links:
            if getattr(link, "create_record_tracking_satellite", False):
                hashkey_name = link.hashkey.hashkey_name if link.hashkey else None
                parents.append(
                    (
                        link.link_name,
                        link.group,
                        hashkey_name,
                        link.source_tables,
                        _in_folder_of(
                            link.record_tracking_satellite_output, link.output
                        ),
                    )
                )

        if not parents:
            return

        sql_template, yaml_template = self.template_resolver.get_templates(
            "satellite_record_tracking"
        )
        if not sql_template:
            for parent_name, *_ in parents:
                self.report.add_skipped(
                    entity_type="satellite_record_tracking",
                    entity_name=parent_name,
                    reason="No template found for satellite_record_tracking",
                )
            return

        naming = self.config.record_tracking_satellite_naming

        for parent_name, group, hashkey_name, source_tables, output in parents:
            if not hashkey_name:
                self.report.add_skipped(
                    entity_type="satellite_record_tracking",
                    entity_name=parent_name,
                    reason="Parent has no hashkey; cannot track records",
                )
                continue

            try:
                rts_name = (
                    output.model_name
                    if output
                    else satellite_pattern(naming, entity_base_name(parent_name))
                )
                context = {
                    "satellite_name": rts_name,
                    "parent_entity": parent_name,
                    "parent_hashkey": hashkey_name,
                    "group": group,
                    "source_tables": [st.model_dump() for st in source_tables],
                }

                directory, model_config = self._placement(
                    output,
                    self.folder_config.get_raw_vault_path(group, self.output_path),
                    "raw_vault",
                )
                self._write_model(
                    entity_type="satellite_record_tracking",
                    model_name=rts_name,
                    directory=directory,
                    sql_template=sql_template,
                    yaml_template=yaml_template,
                    context=context,
                    model_config=model_config,
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

    def _generate_effectivity_satellites(
        self,
        hubs: list[HubDefinition],
        links: list[LinkDefinition] | None = None,
    ) -> None:
        """Generate an effectivity satellite for each flagged hub and link.

        It tracks its parent's hash key in the stage of the parent's first
        source (for a hub, the first that loads the hub's own hash key).
        Without a folder of its own, the satellite goes where its parent goes.
        """
        parents: list[
            tuple[str, str, str | None, str | None, str | None, Any, Any, Any]
        ] = []
        for hub in hubs:
            if not getattr(hub, "create_effectivity_satellite", False):
                continue
            stage = next(
                (s.stage_name for s in hub.source_tables if not s.hk_column), None
            )
            parents.append(
                (
                    "hub",
                    hub.hub_name,
                    hub.group,
                    hub.hashkey.hashkey_name if hub.hashkey else None,
                    stage,
                    hub.effectivity_satellite_output,
                    hub.output,
                    hub.effectivity_options,
                )
            )
        for link in links or []:
            if not getattr(link, "create_effectivity_satellite", False):
                continue
            parents.append(
                (
                    "link",
                    link.link_name,
                    link.group,
                    link.hashkey.hashkey_name if link.hashkey else None,
                    link.source_tables[0].stage_name if link.source_tables else None,
                    link.effectivity_satellite_output,
                    link.output,
                    link.effectivity_options,
                )
            )
        if not parents:
            return

        sql_template, yaml_template = self.template_resolver.get_templates(
            "satellite_effectivity"
        )
        if not sql_template:
            for _kind, parent_name, *_ in parents:
                self.report.add_skipped(
                    entity_type="satellite_effectivity",
                    entity_name=parent_name,
                    reason="No template found for satellite_effectivity",
                )
            return

        naming = self.config.effectivity_satellite_naming

        for (
            kind,
            parent_name,
            group,
            hashkey_name,
            stage_name,
            own_output,
            parent_output,
            options,
        ) in parents:
            if not hashkey_name or not stage_name:
                self.report.add_skipped(
                    entity_type="satellite_effectivity",
                    entity_name=parent_name,
                    reason=(
                        f"{kind.capitalize()} has no hashkey or source stage; "
                        "cannot track effectivity"
                    ),
                )
                continue

            try:
                output = _in_folder_of(own_output, parent_output)
                es_name = (
                    output.model_name
                    if output
                    else satellite_pattern(naming, entity_base_name(parent_name))
                )
                context = {
                    "satellite_name": es_name,
                    "parent_entity": parent_name,
                    "parent_entity_type": kind,
                    "parent_hashkey": hashkey_name,
                    "stage_name": stage_name,
                    "group": group,
                    "is_active_alias": options.is_active_alias,
                    "disable_hwm": options.disable_hwm,
                    "additional_columns": options.additional_columns,
                    "source_is_single_batch": options.source_is_single_batch,
                }

                directory, model_config = self._placement(
                    output,
                    self.folder_config.get_raw_vault_path(group, self.output_path),
                    "raw_vault",
                )
                self._write_model(
                    entity_type="satellite_effectivity",
                    model_name=es_name,
                    directory=directory,
                    sql_template=sql_template,
                    yaml_template=yaml_template,
                    context=context,
                    model_config=model_config,
                )

                self.report.effectivity_satellites_generated += 1

            except Exception as e:
                logger.warning(
                    f"Failed to generate effectivity satellite for {parent_name}: {e}"
                )
                self.report.add_error(
                    entity_type="satellite_effectivity",
                    entity_name=parent_name,
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
                # Standard folder: the business vault's pits folder, per group
                directory, model_config = self._placement(
                    pit.output,
                    self.folder_config.get_business_vault_pits_path(
                        pit.group, self.output_path
                    ),
                    "business_vault",
                )
                self._write_model(
                    entity_type="pit",
                    model_name=pit.pit_name,
                    directory=directory,
                    sql_template=sql_template,
                    yaml_template=yaml_template,
                    context=pit.model_dump(),
                    model_config=model_config,
                    sql_context={
                        "materialization": self._specific_materialization("pit")
                    },
                    references=[*pit.satellite_models, pit.snapshot_control_name],
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
                # Standard folder: the raw vault layer's, per group
                directory, model_config = self._placement(
                    ref_table.output,
                    self.folder_config.get_raw_vault_path(
                        ref_table.group, self.output_path
                    ),
                    "raw_vault",
                )
                self._write_model(
                    entity_type="reference_table",
                    model_name=ref_table.table_name,
                    directory=directory,
                    sql_template=sql_template,
                    yaml_template=yaml_template,
                    context=ref_table.model_dump(),
                    model_config=model_config,
                    sql_context={
                        "materialization": self._specific_materialization(
                            "reference_table"
                        )
                    },
                    references=[
                        *(
                            sat.model_name
                            for sat in ref_table.satellites
                            if sat.model_name
                        ),
                        *filter(None, (ref_table.snapshot_control_table,)),
                    ],
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
                control_dir = self.folder_config.get_control_path(self.output_path)
                # Templates append _v0/_v1 to `name`, so they get the base name:
                # a control stored as 'control_snap_v0' must not name its models
                # 'control_snap_v0_v0'. The model names are passed as they are.
                context = {
                    **snap_ctrl.model_dump(),
                    "name": snap_ctrl.base_name,
                    "v0_name": snap_ctrl.v0_name,
                    "v1_name": snap_ctrl.v1_name,
                }

                # Generate v0 model (control table)
                if v0_sql_template:
                    directory, model_config = self._placement(
                        snap_ctrl.v0_output, control_dir, "control"
                    )
                    self._write_model(
                        entity_type="snapshot_control_v0",
                        model_name=snap_ctrl.v0_name,
                        directory=directory,
                        sql_template=v0_sql_template,
                        yaml_template=v0_yaml_template,
                        context=context,
                        model_config=model_config,
                        sql_context={
                            "materialization": self._specific_materialization(
                                "snapshot_control_v0"
                            )
                        },
                    )

                # Generate v1 model (control logic), next to the table by default
                if v1_sql_template:
                    directory, model_config = self._placement(
                        _in_folder_of(snap_ctrl.v1_output, snap_ctrl.v0_output),
                        control_dir,
                        "control",
                    )
                    self._write_model(
                        entity_type="snapshot_control_v1",
                        model_name=snap_ctrl.v1_name,
                        directory=directory,
                        sql_template=v1_sql_template,
                        yaml_template=v1_yaml_template,
                        context=context,
                        model_config=model_config,
                        sql_context={
                            "materialization": self._specific_materialization(
                                "snapshot_control_v1"
                            )
                        },
                        references=[snap_ctrl.v0_name],
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
