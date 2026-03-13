"""
dbt project generator.

Main module for generating complete dbt projects from TurboVault export data.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .file_writer import write_sql_file, write_yaml_file
from .folder_config import GenerationConfig, get_model_filename
from .report import GenerationReport
from .template_resolver import TemplateResolver

if TYPE_CHECKING:
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

        try:
            # 1. Create folder structure
            self._create_folder_structure()

            # 2. Generate project-level files
            self._generate_project_files()

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

            # 8. Generate PIT models
            self._generate_pits(project_export.pits)

            # 9. Generate reference table models
            self._generate_reference_tables(project_export.reference_tables)

            # 10. Generate snapshot control models
            self._generate_snapshot_controls(project_export.snapshot_controls)

            # 11. Post-generation validation: check for missing YAML files
            self.report.validate_yaml_files()

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

    def _create_folder_structure(self) -> None:
        """Create the dbt project directory structure."""
        self.folder_config.create_project_structure(self.output_path)
        logger.debug("Created folder structure")

    def _generate_project_files(self) -> None:
        """Generate dbt_project.yml and packages.yml."""
        # Generate dbt_project.yml
        template = self.template_resolver.get_project_template("dbt_project.yml")
        if template:
            content = template.render(
                project_name=self.config.project_name,
                profile_name=self.config.profile_name,
                stage_schema=self.config.stage_schema,
                rdv_schema=self.config.rdv_schema,
                bdv_schema=self.config.bdv_schema,
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
                # Get output directory based on source system
                output_dir = self.folder_config.get_staging_path(
                    stage.source_system, self.output_path
                )

                # Generate SQL file
                if sql_template:
                    content = sql_template.render(**stage.model_dump())
                    filename = get_model_filename(stage.stage_name, extension="sql")
                    path = output_dir / filename
                    write_sql_file(path, content)
                    self.report.add_file(path, "stage", stage.stage_name, "sql")

                # Generate YAML file
                if yaml_template:
                    content = yaml_template.render(**stage.model_dump())
                    filename = get_model_filename(stage.stage_name, extension="yml")
                    path = output_dir / filename
                    write_yaml_file(path, content)
                    self.report.add_file(path, "stage", stage.stage_name, "yaml")

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

                # Get output directory based on group
                output_dir = self.folder_config.get_raw_vault_path(
                    hub.group, self.output_path
                )

                # Generate SQL file
                content = sql_template.render(**hub.model_dump())
                filename = get_model_filename(hub.hub_name, extension="sql")
                path = output_dir / filename
                write_sql_file(path, content)
                self.report.add_file(path, entity_type, hub.hub_name, "sql")

                # Generate YAML file
                if yaml_template:
                    content = yaml_template.render(**hub.model_dump())
                    filename = get_model_filename(hub.hub_name, extension="yml")
                    path = output_dir / filename
                    write_yaml_file(path, content)
                    self.report.add_file(path, entity_type, hub.hub_name, "yaml")

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

                # Get output directory based on group
                output_dir = self.folder_config.get_raw_vault_path(
                    link.group, self.output_path
                )

                # Generate SQL file
                content = sql_template.render(**link.model_dump())
                filename = get_model_filename(link.link_name, extension="sql")
                path = output_dir / filename
                write_sql_file(path, content)
                self.report.add_file(path, entity_type, link.link_name, "sql")

                # Generate YAML file
                if yaml_template:
                    content = yaml_template.render(**link.model_dump())
                    filename = get_model_filename(link.link_name, extension="yml")
                    path = output_dir / filename
                    write_yaml_file(path, content)
                    self.report.add_file(path, entity_type, link.link_name, "yaml")

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

        v0_naming = self.config.satellite_v0_naming
        v1_naming = self.config.satellite_v1_naming
        generate_v1 = self.config.generate_satellite_v1_views

        # V1-capable types (standard, effectivity, multi_active, reference)
        v1_types = {"standard", "effectivity", "multi_active", "reference"}

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

                # Get output directory based on group
                output_dir = self.folder_config.get_raw_vault_path(
                    satellite.group, self.output_path
                )

                # Generate v0 model name
                v0_name = self.config.resolve_entity_name(
                    v0_naming, satellite.satellite_name
                )

                # Generate SQL file (v0)
                context = satellite.model_dump()
                context["satellite_name"] = v0_name  # Override with v0 suffix
                content = sql_template.render(**context)
                filename = get_model_filename(v0_name, extension="sql")
                path = output_dir / filename
                write_sql_file(path, content)
                self.report.add_file(path, entity_type, v0_name, "sql")

                # Generate YAML file (v0)
                if yaml_template:
                    content = yaml_template.render(**context)
                    filename = get_model_filename(v0_name, extension="yml")
                    path = output_dir / filename
                    write_yaml_file(path, content)
                    self.report.add_file(path, entity_type, v0_name, "yaml")

                self.report.satellites_generated += 1

                # Generate v1 view if enabled and satellite type supports it
                if generate_v1 and satellite.satellite_type in v1_types:
                    self._generate_satellite_v1(
                        satellite, output_dir, v0_name, v1_naming
                    )

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
        output_dir: Path,
        v0_name: str,
        v1_suffix_or_pattern: str,
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

        # Generate v1 model name
        base_name = satellite.satellite_name
        v1_name = self.config.resolve_entity_name(v1_suffix_or_pattern, base_name)

        # Build context for v1 template
        context = satellite.model_dump()
        context["satellite_name"] = base_name  # Original name for template logic
        context["v0_name"] = v0_name

        try:
            # Generate SQL file (v1)
            content = sql_template.render(**context)
            filename = get_model_filename(v1_name, extension="sql")
            path = output_dir / filename
            write_sql_file(path, content)
            self.report.add_file(path, "satellite_v1", v1_name, "sql")

            # Generate YAML file (v1)
            if yaml_template:
                content = yaml_template.render(**context)
                filename = get_model_filename(v1_name, extension="yml")
                path = output_dir / filename
                write_yaml_file(path, content)
                self.report.add_file(path, "satellite_v1", v1_name, "yaml")

            self.report.satellite_views_generated += 1

        except Exception as e:
            logger.warning(f"Failed to generate satellite v1 {v1_name}: {e}")
            self.report.add_warning(
                entity_type="satellite_v1",
                entity_name=v1_name,
                message=str(e),
                code="SAT_002",
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
                output_dir = self.folder_config.get_business_vault_pits_path(
                    self.output_path
                )

                # Generate SQL file
                content = sql_template.render(**pit.model_dump())
                filename = get_model_filename(pit.pit_name, extension="sql")
                path = output_dir / filename
                write_sql_file(path, content)
                self.report.add_file(path, "pit", pit.pit_name, "sql")

                # Generate YAML file
                if yaml_template:
                    content = yaml_template.render(**pit.model_dump())
                    filename = get_model_filename(pit.pit_name, extension="yml")
                    path = output_dir / filename
                    write_yaml_file(path, content)
                    self.report.add_file(path, "pit", pit.pit_name, "yaml")

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
                output_dir = (
                    self.folder_config.get_business_vault_reference_tables_path(
                        self.output_path
                    )
                )

                # Generate SQL file
                content = sql_template.render(**ref_table.model_dump())
                filename = get_model_filename(ref_table.table_name, extension="sql")
                path = output_dir / filename
                write_sql_file(path, content)
                self.report.add_file(
                    path, "reference_table", ref_table.table_name, "sql"
                )

                # Generate YAML file
                if yaml_template:
                    content = yaml_template.render(**ref_table.model_dump())
                    filename = get_model_filename(ref_table.table_name, extension="yml")
                    path = output_dir / filename
                    write_yaml_file(path, content)
                    self.report.add_file(
                        path, "reference_table", ref_table.table_name, "yaml"
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
                output_dir = self.folder_config.get_control_path(self.output_path)

                # Generate v0 model (control table)
                if v0_sql_template:
                    content = v0_sql_template.render(**snap_ctrl.model_dump())
                    filename = get_model_filename(snap_ctrl.v0_name, extension="sql")
                    path = output_dir / filename
                    write_sql_file(path, content)
                    self.report.add_file(
                        path, "snapshot_control_v0", snap_ctrl.v0_name, "sql"
                    )

                    if v0_yaml_template:
                        content = v0_yaml_template.render(**snap_ctrl.model_dump())
                        filename = get_model_filename(
                            snap_ctrl.v0_name, extension="yml"
                        )
                        path = output_dir / filename
                        write_yaml_file(path, content)
                        self.report.add_file(
                            path, "snapshot_control_v0", snap_ctrl.v0_name, "yaml"
                        )

                # Generate v1 model (control logic)
                if v1_sql_template:
                    content = v1_sql_template.render(**snap_ctrl.model_dump())
                    filename = get_model_filename(snap_ctrl.v1_name, extension="sql")
                    path = output_dir / filename
                    write_sql_file(path, content)
                    self.report.add_file(
                        path, "snapshot_control_v1", snap_ctrl.v1_name, "sql"
                    )

                    if v1_yaml_template:
                        content = v1_yaml_template.render(**snap_ctrl.model_dump())
                        filename = get_model_filename(
                            snap_ctrl.v1_name, extension="yml"
                        )
                        path = output_dir / filename
                        write_yaml_file(path, content)
                        self.report.add_file(
                            path, "snapshot_control_v1", snap_ctrl.v1_name, "yaml"
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
