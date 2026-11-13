"""
dbt project generator.

Main module for generating complete dbt projects from TurboVault export data.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from markupsafe import Markup

from engine.services.config_schema import MODEL_MATERIALIZATION_DEFAULTS

from .file_writer import write_sql_file, write_yaml_file
from .folder_config import GenerationConfig
from .model_outputs import (
    LAYER_BY_KIND,
    V1_SATELLITE_TYPES,
    ModelOutput,
    ModelOutputs,
    record_tracking_key,
    resolve_model_outputs,
)
from .profiles_yml import LiteralSecretError, render_profiles_yml
from .report import GenerationReport
from .template_resolver import TemplateResolver
from .vars_block import render_vars_block

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jinja2 import Template

    from engine.services.export.models import (
        HubDefinition,
        LinkDefinition,
        PITDefinition,
        PrestageDefinition,
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

# Each layer's schema setting in GenerationConfig (its materialization is
# `<layer>_materialization`).
_LAYER_SCHEMA_FIELDS = {
    "prestaging": "stage_schema",
    "staging": "stage_schema",
    "raw_vault": "rdv_schema",
    "business_vault": "bdv_schema",
    "control": "control_schema",
}


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
        # Name, folder and config of every model; resolved in generate().
        self.outputs = ModelOutputs()

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
            project_export: The project export containing the entities to
                generate (possibly narrowed by an entity selection).
            reference_export: The full, unfiltered export. References to
                models (a PIT's satellites, a reference table's hub, ...) are
                resolved against it, so they keep the stored names of models
                the selection left out. Defaults to ``project_export``.

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

        # Resolve every model's name and file before writing anything: a
        # collision found mid-run would leave one model overwriting another.
        # Collisions are checked across the models this run writes; names are
        # resolved across the whole project, as a selected model may reference
        # one the selection left out.
        collisions = resolve_model_outputs(project_export, self.config).collisions()
        self.outputs = resolve_model_outputs(
            reference_export or project_export, self.config
        )
        if collisions:
            for message in collisions:
                self.report.add_error(
                    entity_type="project",
                    entity_name=self.config.project_name,
                    message=message,
                    code="PTH_001",
                )
            return self.report
        project_export = self._with_resolved_references(project_export)

        try:
            # 1. Create folder structure
            self._create_folder_structure()

            # 2. Generate project-level files
            self._generate_project_files(
                vars_block,
                profiles_content,
                has_prestage_models=self._has_prestages_in_layer_folder(
                    project_export.prestages
                ),
            )

            # 3. Generate sources.yml
            self._generate_sources(project_export.sources)

            # 4. Generate pre-stage models, then the stage models reading them
            self._generate_prestages(project_export.prestages)
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
            self.config, f"{LAYER_BY_KIND[model_kind]}_materialization"
        )
        return None if value == layer_value else value

    def _model_config(self, output: ModelOutput) -> dict[str, Any]:
        """Template variables for the model's name and its config() block.

        A stored attribute wins. A model outside its layer's folder misses
        that folder's `+schema` / `+materialized` from dbt_project.yml, so it
        gets the layer's values in its own config() instead.
        """
        layer = LAYER_BY_KIND[output.kind]
        materialization = output.materialized or self._specific_materialization(
            output.kind
        )
        schema = output.schema
        if not output.directory.is_relative_to(self.folder_config.layer_dir(layer)):
            materialization = materialization or self._layer_materialization(layer)
            schema = schema or getattr(self.config, _LAYER_SCHEMA_FIELDS[layer])
        return {
            "model_name": output.model_name,
            "materialization": materialization,
            "model_alias": output.alias,
            "model_schema": schema,
            "model_database": output.database,
            "model_tags": list(output.tags) if output.tags is not None else None,
            # Further config() settings from custom_config_json, in stored order.
            "model_custom_config": dict(output.custom_config),
        }

    def _layer_materialization(self, layer: str) -> str:
        """A layer's materialization, as dbt_project.yml configures it."""
        if layer == "prestaging":
            return self._prestaging_materialization()
        return getattr(self.config, f"{layer}_materialization")

    def _has_prestages_in_layer_folder(
        self, prestages: list[PrestageDefinition]
    ) -> bool:
        """Whether a pre-stage model is written into the pre-staging folder.

        dbt_project.yml only configures that folder then, so dbt finds no
        unused path when every pre-stage was moved elsewhere.
        """
        layer_dir = self.folder_config.layer_dir("prestaging")
        return any(
            self._output("prestage", prestage.model_name).directory.is_relative_to(
                layer_dir
            )
            for prestage in prestages
            if prestage.sql
        )

    def _output(self, kind: str, key: str) -> ModelOutput:
        """The resolved output of a model generate() is about to write."""
        output = self.outputs.get(kind, key)
        if output is None:  # pragma: no cover - resolve_model_outputs mirrors us
            raise LookupError(f"No resolved output for {kind} '{key}'")
        return output

    def _write_model(
        self,
        output: ModelOutput,
        sql_template: Template | None,
        yaml_template: Template | None,
        context: Mapping[str, Any],
        entity_type: str,
    ) -> str | None:
        """Render a model's .sql and .yml and write them into its folder.

        Returns the rendered SQL, or None without an SQL template.
        """
        context = {**context, **self._model_config(output)}
        directory = self.output_path.joinpath(*output.directory.parts)
        sql_content = None
        if sql_template:
            sql_content = sql_template.render(**context)
            path = directory / f"{output.model_name}.sql"
            write_sql_file(path, sql_content)
            self.report.add_file(path, entity_type, output.model_name, "sql")
        if yaml_template:
            path = directory / f"{output.model_name}.yml"
            write_yaml_file(path, yaml_template.render(**context))
            self.report.add_file(path, entity_type, output.model_name, "yaml")
        return sql_content

    def _with_resolved_references(self, project_export: ProjectExport) -> ProjectExport:
        """A copy of the export whose references to other models use the
        resolved model names: pre-stages (read by stages and prejoins),
        stages, the hub or link a PIT tracks, the hub of a reference table and
        the snapshot control of a PIT.

        References to satellite v0/v1 models are passed to the templates as
        their own variables (`v0_name`, `v1_name`, `satellite_v0_names`), as
        the templates also need the satellite's base name.

        Only the definitions holding such references are copied, shallowly,
        with the resolved names: the caller's export stays untouched without
        deep-copying every column, mapping and description.
        """
        outputs = self.outputs

        def stage(name: str) -> str:
            return outputs.name("stage", name, name)

        def prestage(name: str | None) -> str | None:
            return outputs.name("prestage", name, name) if name else None

        def with_prestages(stage_def: StageDefinition) -> StageDefinition:
            return stage_def.model_copy(
                update={
                    "prestage_model": prestage(stage_def.prestage_model),
                    "prejoins": [
                        prejoin.model_copy(
                            update={"target_model": prestage(prejoin.target_model)}
                        )
                        for prejoin in stage_def.prejoins
                    ],
                }
            )

        def with_stages(entity: Any) -> Any:
            return entity.model_copy(
                update={
                    "source_tables": [
                        source.model_copy(
                            update={"stage_name": stage(source.stage_name)}
                        )
                        for source in entity.source_tables
                    ]
                }
            )

        control_v1_names = {
            control.v1_name: outputs.name(
                "snapshot_control_v1", control.name, control.v1_name
            )
            for control in project_export.snapshot_controls
        }
        return project_export.model_copy(
            update={
                "stages": [with_prestages(stage) for stage in project_export.stages],
                "hubs": [with_stages(hub) for hub in project_export.hubs],
                "links": [with_stages(link) for link in project_export.links],
                "satellites": [
                    satellite.model_copy(
                        update={"stage_name": stage(satellite.stage_name)}
                    )
                    for satellite in project_export.satellites
                ],
                "pits": [
                    pit.model_copy(
                        update={
                            "tracked_entity_name": outputs.name(
                                pit.tracked_entity_type,
                                pit.tracked_entity_name,
                                pit.tracked_entity_name,
                            ),
                            "snapshot_control_name": control_v1_names.get(
                                pit.snapshot_control_name, pit.snapshot_control_name
                            ),
                        }
                    )
                    for pit in project_export.pits
                ],
                "reference_tables": [
                    ref_table.model_copy(
                        update={
                            "reference_hub_name": outputs.name(
                                "hub",
                                ref_table.reference_hub_name,
                                ref_table.reference_hub_name,
                            )
                        }
                    )
                    for ref_table in project_export.reference_tables
                ],
            }
        )

    def _satellite_v0_name(self, satellite_name: str) -> str:
        """Model name of a satellite's v0 model, as referenced by others."""
        return self.outputs.name(
            "satellite_v0",
            satellite_name,
            self.config.resolve_entity_name(
                self.config.satellite_v0_naming, satellite_name
            ),
        )

    def _satellite_v1_name(self, satellite_name: str) -> str:
        """Model name of a satellite's v1 view, as referenced by others."""
        return self.outputs.name(
            "satellite_v1",
            satellite_name,
            self.config.resolve_entity_name(
                self.config.satellite_v1_naming, satellite_name
            ),
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

    def _prestaging_materialization(self) -> str:
        """Materialization of the pre-stage layer: the staging layer's.

        The stage reads a pre-stage's columns from the database, where an
        ephemeral model doesn't exist, so an ephemeral staging layer gives views.
        """
        materialization = self.config.staging_materialization
        return "view" if materialization == "ephemeral" else materialization

    def _generate_project_files(
        self,
        vars_block: str = "",
        profiles_content: str | None = None,
        has_prestage_models: bool = False,
    ) -> None:
        """Generate dbt_project.yml, packages.yml and the optional profiles.yml.

        `vars_block` is the already-rendered `vars:` section and
        `profiles_content` the already-rendered profiles.yml, or None when not
        requested (see `generate()`, which resolves both up front so an invalid
        value fails before any file is written). The pre-stage layer is only
        configured when `has_prestage_models`, so dbt finds no unused path.
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
                    self._prestaging_materialization() if has_prestage_models else None
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
            # Pre-stages are dbt models, not sources: their stages ref() them.
            physical_tables = [t for t in source.tables if t.table_type != "prestage"]
            if source.tables and not physical_tables:
                continue
            source = source.model_copy(update={"tables": physical_tables})
            source_name = self.folder_config.sanitize_name(source.name)
            if template:
                content = template.render(source=source)
                path = self.output_path.joinpath(
                    *self.folder_config.source_file(source.name).parts
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

    def _generate_prestages(self, prestages: list[PrestageDefinition]) -> None:
        """Generate the pre-stage models: their SQL as it is, and a YAML file.

        A pre-stage without SQL is maintained outside TurboVault: nothing is
        written for it, and its stage reads the model all the same.
        """
        prestages = [prestage for prestage in prestages if prestage.sql]
        if not prestages:
            logger.debug("No pre-stage models to generate")
            return

        sql_template, yaml_template = self.template_resolver.get_templates("prestage")

        for prestage in prestages:
            try:
                output = self._output("prestage", prestage.model_name)
                context = prestage.model_dump()
                # The SQL goes in as it is: templates loaded from strings (the
                # workspace's copies) autoescape, which would mangle its quotes.
                # It may set its own config(), so the stored config goes into
                # the .yml, which dbt ranks below the model's config().
                context["prestage_sql"] = Markup(prestage.sql)
                self._write_model(
                    output, sql_template, yaml_template, context, "prestage"
                )
                self.report.prestages_generated += 1

            except Exception as e:
                logger.warning(
                    f"Failed to generate pre-stage {prestage.model_name}: {e}"
                )
                self.report.add_error(
                    entity_type="prestage",
                    entity_name=prestage.model_name,
                    message=str(e),
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
                output = self._output("stage", stage.stage_name)
                context = stage.model_dump()
                context["stage_name"] = output.model_name
                sql_content = self._write_model(
                    output, sql_template, yaml_template, context, "stage"
                )
                if sql_content is not None:
                    self._check_prestage_support(stage, sql_content)
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
                context = hub.model_dump()
                context["hub_name"] = output.model_name
                self._write_model(
                    output, sql_template, yaml_template, context, entity_type
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
                context = link.model_dump()
                context["link_name"] = output.model_name
                self._write_model(
                    output, sql_template, yaml_template, context, entity_type
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
                # Templates name the model after `satellite_name`.
                context["satellite_name"] = output.model_name
                self._write_model(
                    output, sql_template, yaml_template, context, entity_type
                )
                self.report.satellites_generated += 1

                # Generate v1 view if enabled and satellite type supports it
                if generate_v1 and satellite.satellite_type in V1_SATELLITE_TYPES:
                    self._generate_satellite_v1(satellite, output.model_name)

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
        """Generate satellite v1 view (load_end_date view) on top of `v0_name`."""
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
        v1_name = output.model_name

        # Build context for v1 template
        context = satellite.model_dump()
        context["satellite_name"] = satellite.satellite_name  # For template logic
        context["v0_name"] = v0_name
        context["v1_name"] = v1_name

        try:
            self._write_model(
                output, sql_template, yaml_template, context, "satellite_v1"
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
        """Generate a record-tracking satellite for each flagged hub and link."""
        # Collect flagged parents as (key, name, group, hashkey_name, source_tables).
        parents: list[tuple[str, str, str | None, str | None, list]] = []
        for hub in hubs:
            if getattr(hub, "create_record_tracking_satellite", False):
                hashkey_name = hub.hashkey.hashkey_name if hub.hashkey else None
                parents.append(
                    (
                        record_tracking_key("hub", hub.hub_name),
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
                        record_tracking_key("link", link.link_name),
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
                    "satellite_name": output.model_name,
                    "parent_entity": parent_name,
                    "parent_hashkey": hashkey_name,
                    "group": group,
                    "source_tables": [st.model_dump() for st in source_tables],
                }
                self._write_model(
                    output,
                    sql_template,
                    yaml_template,
                    context,
                    "satellite_record_tracking",
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
                    "satellite_name": output.model_name,
                    "parent_entity": hub.hub_name,
                    "parent_hashkey": hashkey_name,
                    "stage_name": stage_name,
                    "group": hub.group,
                }
                self._write_model(
                    output,
                    sql_template,
                    yaml_template,
                    context,
                    "satellite_effectivity",
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
                context = pit.model_dump()
                context["pit_name"] = output.model_name
                # `satellites` holds the base names; the PIT reads the v0 models.
                context["satellite_v0_names"] = [
                    self._satellite_v0_name(name) for name in pit.satellites
                ]
                self._write_model(output, sql_template, yaml_template, context, "pit")
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
                context = ref_table.model_dump()
                context["table_name"] = output.model_name
                # The reference table reads each satellite's v1 view.
                for assignment in context["satellites"]:
                    assignment["v1_name"] = self._satellite_v1_name(
                        assignment["satellite_name"]
                    )
                self._write_model(
                    output, sql_template, yaml_template, context, "reference_table"
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
                # Templates append _v0/_v1 to `name`, so they get the base name:
                # a control stored as 'control_snap_v0' must not name its models
                # 'control_snap_v0_v0'. The v1 model reads the v0 model; both
                # name themselves with their resolved model names.
                context = {
                    **snap_ctrl.model_dump(),
                    "name": snap_ctrl.base_name,
                    "v0_name": v0_output.model_name,
                    "v1_name": v1_output.model_name,
                }

                # The YAML is only written with its model, as before.
                if v0_sql_template:
                    self._write_model(
                        v0_output,
                        v0_sql_template,
                        v0_yaml_template,
                        context,
                        "snapshot_control_v0",
                    )
                if v1_sql_template:
                    self._write_model(
                        v1_output,
                        v1_sql_template,
                        v1_yaml_template,
                        context,
                        "snapshot_control_v1",
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
