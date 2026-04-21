"""
JSON Import Service for TurboVault Engine.

Imports metadata from a JSON file exported by the TurboVault Engine JSON exporter,
restoring the full Data Vault model into the Django backend.
"""

from __future__ import annotations

import logging
from datetime import date, time
from pathlib import Path

from django.db import transaction

from engine.models.group import Group
from engine.models.hubs import Hub, HubColumn, HubSourceMapping
from engine.models.links import (
    Link,
    LinkColumn,
    LinkHubReference,
    LinkHubSourceMapping,
    LinkSourceMapping,
)
from engine.models.pit import PIT
from engine.models.prejoin import PrejoinDefinition
from engine.models.prejoin import PrejoinExtractionColumn as PrejoinExtractionColumnORM
from engine.models.project import Project
from engine.models.reference_table import (
    ReferenceTable,
    ReferenceTableSatelliteAssignment,
)
from engine.models.satellites import Satellite, SatelliteColumn
from engine.models.snapshot_control import SnapshotControlLogic, SnapshotControlTable
from engine.models.source_metadata import SourceColumn, SourceSystem, SourceTable
from engine.models.staging import StagingColumn
from engine.services.export.models import ProjectExport
from engine.services.staging_service import get_or_create_staging_column

logger = logging.getLogger(__name__)


def _stage_name(source_system: str, source_table: str) -> str:
    """Derive the canonical stage name from system and table names."""
    return f"stg__{source_system.lower().replace(' ', '_')}__{source_table.lower()}"


class JsonImportService:
    """
    Imports metadata from a TurboVault JSON export file.

    Parses the exported JSON into a ProjectExport Pydantic model and
    creates the corresponding Django ORM objects in dependency order.
    """

    def __init__(self, json_path: str | Path) -> None:
        self._json_path = Path(json_path)
        # Internal caches
        self.project: Project | None = None
        self._groups: dict[str, Group] = {}
        self._source_systems: dict[str, SourceSystem] = {}
        # keyed by "system_name|table_name"
        self._source_tables: dict[str, SourceTable] = {}
        # keyed by "system_name|table_name|col_name"
        self._source_columns: dict[str, SourceColumn] = {}
        # keyed by "system_name|table_name|col_name"
        self._staging_cols: dict[str, StagingColumn] = {}
        # keyed by "stage_name|alias" → PrejoinExtractionColumnORM
        self._prejoin_extractions: dict[str, PrejoinExtractionColumnORM] = {}
        self._hubs: dict[str, Hub] = {}
        self._hub_columns: dict[str, HubColumn] = {}  # "hub_name|col_name"
        self._links: dict[str, Link] = {}
        self._satellites: dict[str, Satellite] = {}
        self._snapshot_controls: dict[str, SnapshotControlTable] = {}
        # keyed by "control_name|logic_column_name"
        self._snapshot_logics: dict[str, SnapshotControlLogic] = {}

    @transaction.atomic
    def import_metadata(
        self,
        project_name: str | None = None,
        description: str | None = None,
        project: Project | None = None,
    ) -> Project:
        """Main entry point: parse JSON and import all metadata."""
        json_text = self._json_path.read_text(encoding="utf-8")
        export = ProjectExport.model_validate_json(json_text)

        if project:
            self.project = project
        else:
            if not project_name:
                project_name = export.project_name
            self.project = Project.objects.create(
                name=project_name,
                description=description or export.project_description or "",
            )

        logger.info("Starting JSON import for project: %s", self.project.name)

        self._import_groups(export)
        self._import_snapshot_controls(export)
        self._import_sources(export)
        self._import_hubs(export)
        self._import_links(export)
        self._import_prejoins(export)
        self._import_hub_source_mappings(export)
        self._import_satellites(export)
        self._import_reference_tables(export)
        self._import_pits(export)

        logger.info("JSON import completed successfully.")
        return self.project

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------

    def _import_groups(self, export: ProjectExport) -> None:
        group_names: set[str] = set()
        for hub in export.hubs:
            if hub.group:
                group_names.add(hub.group)
        for link in export.links:
            if link.group:
                group_names.add(link.group)
        for sat in export.satellites:
            if sat.group:
                group_names.add(sat.group)

        for name in group_names:
            group, _ = Group.objects.get_or_create(
                project=self.project,
                group_name=name,
            )
            self._groups[name] = group

    # ------------------------------------------------------------------
    # Snapshot Controls
    # ------------------------------------------------------------------

    def _import_snapshot_controls(self, export: ProjectExport) -> None:
        for ctrl in export.snapshot_controls:
            snap_table = SnapshotControlTable.objects.create(
                project=self.project,
                name=ctrl.name,
                snapshot_start_date=date.fromisoformat(ctrl.start_date),
                snapshot_end_date=date.fromisoformat(ctrl.end_date),
                daily_snapshot_time=time.fromisoformat(ctrl.daily_time),
            )
            self._snapshot_controls[ctrl.name] = snap_table

            for pattern in ctrl.logic_patterns:
                logic = SnapshotControlLogic.objects.create(
                    snapshot_control_table=snap_table,
                    snapshot_control_logic_column_name=pattern.column_name,
                    snapshot_component=pattern.component,
                    snapshot_duration=pattern.duration,
                    snapshot_unit=pattern.unit,
                    snapshot_forever=pattern.forever,
                )
                self._snapshot_logics[f"{ctrl.name}|{pattern.column_name}"] = logic

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def _import_sources(self, export: ProjectExport) -> None:
        for sys_def in export.sources:
            system, _ = SourceSystem.objects.get_or_create(
                project=self.project,
                name=sys_def.name,
                schema_name=sys_def.schema_name,
                defaults={"database_name": sys_def.database_name},
            )
            self._source_systems[sys_def.name] = system

            for table_def in sys_def.tables:
                table, _ = SourceTable.objects.get_or_create(
                    project=self.project,
                    source_system=system,
                    physical_table_name=table_def.table_name,
                    defaults={
                        "alias": table_def.alias or "",
                        "record_source_value": table_def.record_source or "",
                        "load_date_value": table_def.load_date or "sysdate()",
                        "static_part_of_record_source": "",
                    },
                )
                table_key = f"{sys_def.name}|{table_def.table_name}"
                self._source_tables[table_key] = table

                for col_def in table_def.columns:
                    col, _ = SourceColumn.objects.get_or_create(
                        source_table=table,
                        source_column_physical_name=col_def.column_name,
                        defaults={"source_column_datatype": col_def.datatype},
                    )
                    col_key = (
                        f"{sys_def.name}|{table_def.table_name}|{col_def.column_name}"
                    )
                    self._source_columns[col_key] = col

    def _get_source_column(
        self, source_system: str, source_table: str, col_name: str
    ) -> SourceColumn | None:
        return self._source_columns.get(f"{source_system}|{source_table}|{col_name}")

    def _get_or_create_staging_col(
        self, source_system: str, source_table: str, col_name: str
    ) -> StagingColumn | None:
        key = f"{source_system}|{source_table}|{col_name}"
        if key in self._staging_cols:
            return self._staging_cols[key]
        source_col = self._get_source_column(source_system, source_table, col_name)
        if not source_col:
            logger.warning("Source column not found: %s", key)
            return None
        staging = get_or_create_staging_column(source_col)
        self._staging_cols[key] = staging
        return staging

    def _resolve_staging(
        self,
        source_system: str,
        source_table: str,
        col_name: str,
        stage_name: str,
    ) -> StagingColumn | None:
        """
        Resolve a column name to a StagingColumn.

        Checks the prejoin extraction cache first (for prejoin-derived columns),
        then falls back to the direct source column.
        """
        prejoin_key = f"{stage_name}|{col_name}"
        extraction = self._prejoin_extractions.get(prejoin_key)
        if extraction:
            return get_or_create_staging_column(extraction)
        return self._get_or_create_staging_col(source_system, source_table, col_name)

    # ------------------------------------------------------------------
    # Hubs
    # ------------------------------------------------------------------

    def _import_hubs(self, export: ProjectExport) -> None:
        for hub_def in export.hubs:
            hub = Hub.objects.create(
                project=self.project,
                hub_physical_name=hub_def.hub_name,
                hub_type=hub_def.hub_type,
                hub_hashkey_name=(
                    hub_def.hashkey.hashkey_name if hub_def.hashkey else None
                ),
                group=self._groups.get(hub_def.group) if hub_def.group else None,
                create_record_tracking_satellite=hub_def.create_record_tracking_satellite,
                create_effectivity_satellite=hub_def.create_effectivity_satellite,
            )
            self._hubs[hub_def.hub_name] = hub

            for i, col_name in enumerate(hub_def.business_key_columns):
                hc = HubColumn.objects.create(
                    hub=hub,
                    column_name=col_name,
                    column_type=HubColumn.ColumnType.BUSINESS_KEY,
                    sort_order=i,
                )
                self._hub_columns[f"{hub_def.hub_name}|{col_name}"] = hc

            for i, col_name in enumerate(hub_def.reference_key_columns):
                hc = HubColumn.objects.create(
                    hub=hub,
                    column_name=col_name,
                    column_type=HubColumn.ColumnType.REFERENCE_KEY,
                    sort_order=i,
                )
                self._hub_columns[f"{hub_def.hub_name}|{col_name}"] = hc

            for i, col_name in enumerate(hub_def.additional_columns):
                HubColumn.objects.create(
                    hub=hub,
                    column_name=col_name,
                    column_type=HubColumn.ColumnType.ADDITIONAL_COLUMN,
                    sort_order=i,
                )

    def _import_hub_source_mappings(self, export: ProjectExport) -> None:
        """Create HubSourceMappings after prejoins are available in cache."""
        for hub_def in export.hubs:
            hub = self._hubs.get(hub_def.hub_name)
            if not hub:
                continue
            for src_info in hub_def.source_tables:
                for col_mapping in src_info.column_mappings:
                    hub_col = self._hub_columns.get(
                        f"{hub_def.hub_name}|{col_mapping.hub_column}"
                    )
                    if not hub_col:
                        logger.warning(
                            "Hub column not found for mapping: %s|%s",
                            hub_def.hub_name,
                            col_mapping.hub_column,
                        )
                        continue
                    staging = self._resolve_staging(
                        src_info.source_system,
                        src_info.source_table,
                        col_mapping.source_column,
                        src_info.stage_name,
                    )
                    if staging:
                        HubSourceMapping.objects.get_or_create(
                            hub_column=hub_col,
                            staging_column=staging,
                            defaults={"is_primary_source": src_info.is_primary_source},
                        )

    # ------------------------------------------------------------------
    # Links
    # ------------------------------------------------------------------

    def _import_links(self, export: ProjectExport) -> None:
        for link_def in export.links:
            link = Link.objects.create(
                project=self.project,
                link_physical_name=link_def.link_name,
                link_hashkey_name=link_def.hashkey.hashkey_name,
                link_type=link_def.link_type,
                group=self._groups.get(link_def.group) if link_def.group else None,
            )
            self._links[link_def.link_name] = link

            for i, hub_ref_def in enumerate(link_def.hub_references):
                hub = self._hubs.get(hub_ref_def.hub_name)
                if not hub:
                    hub = Hub.objects.filter(
                        project=self.project, hub_physical_name=hub_ref_def.hub_name
                    ).first()
                if not hub:
                    logger.warning(
                        "Hub %s not found for link %s",
                        hub_ref_def.hub_name,
                        link_def.link_name,
                    )
                    continue
                LinkHubReference.objects.create(
                    link=link,
                    hub=hub,
                    hub_hashkey_alias_in_link=hub_ref_def.hub_hashkey_alias_in_link
                    or "",
                    sort_order=i,
                )

            for i, col_name in enumerate(link_def.payload_columns):
                LinkColumn.objects.create(
                    link=link,
                    column_name=col_name,
                    column_type=LinkColumn.ColumnType.PAYLOAD,
                    sort_order=i,
                )

            for i, col_name in enumerate(link_def.additional_columns):
                LinkColumn.objects.create(
                    link=link,
                    column_name=col_name,
                    column_type=LinkColumn.ColumnType.ADDITIONAL_COLUMN,
                    sort_order=i,
                )

            for src_info in link_def.source_tables:
                src_stage = _stage_name(src_info.source_system, src_info.source_table)
                lhrs = list(
                    LinkHubReference.objects.filter(link=link).order_by("sort_order")
                )

                for col_mapping in src_info.columns:
                    source_staging = self._resolve_staging(
                        src_info.source_system,
                        src_info.source_table,
                        col_mapping.source_column_name,
                        src_stage,
                    )
                    if not source_staging:
                        continue

                    if col_mapping.link_column_type == "business_key":
                        for lhr in lhrs:
                            hub_col = HubColumn.objects.filter(
                                hub=lhr.hub,
                                column_name=col_mapping.link_column_name,
                            ).first()
                            if hub_col:
                                LinkHubSourceMapping.objects.get_or_create(
                                    link_hub_reference=lhr,
                                    standard_hub_column=hub_col,
                                    staging_column=source_staging,
                                )
                                break
                    else:
                        link_col = LinkColumn.objects.filter(
                            link=link, column_name=col_mapping.link_column_name
                        ).first()
                        if link_col:
                            LinkSourceMapping.objects.get_or_create(
                                link_column=link_col,
                                staging_column=source_staging,
                            )

    # ------------------------------------------------------------------
    # Prejoins (reconstructed from stage definitions)
    # ------------------------------------------------------------------

    def _import_prejoins(self, export: ProjectExport) -> None:
        for stage in export.stages:
            if not stage.prejoins:
                continue

            source_table_key = f"{stage.source_system}|{stage.source_table}"
            source_table = self._source_tables.get(source_table_key)
            if not source_table:
                logger.warning(
                    "Source table not found for stage prejoins: %s", source_table_key
                )
                continue

            for pj_def in stage.prejoins:
                target_table_key = f"{stage.source_system}|{pj_def.target_table}"
                target_table = self._source_tables.get(target_table_key)
                if not target_table:
                    logger.warning(
                        "Prejoin target table not found: %s", pj_def.target_table
                    )
                    continue

                operator = pj_def.join_conditions.operator.upper()
                if operator not in PrejoinDefinition.JoinOperator.values:
                    operator = PrejoinDefinition.JoinOperator.AND

                prejoin_obj = PrejoinDefinition.objects.create(
                    project=self.project,
                    source_table=source_table,
                    prejoin_target_table=target_table,
                    prejoin_operator=operator,
                )

                for src_col_name in pj_def.join_conditions.source_columns:
                    src_col = self._get_source_column(
                        stage.source_system, stage.source_table, src_col_name
                    )
                    if src_col:
                        prejoin_obj.prejoin_condition_source_column.add(src_col)

                for tgt_col_name in pj_def.join_conditions.target_columns:
                    tgt_col = self._get_source_column(
                        stage.source_system, pj_def.target_table, tgt_col_name
                    )
                    if tgt_col:
                        prejoin_obj.prejoin_condition_target_column.add(tgt_col)

                for ext in pj_def.extraction_columns:
                    tgt_col = self._get_source_column(
                        stage.source_system, pj_def.target_table, ext.source_column_name
                    )
                    if not tgt_col:
                        logger.warning(
                            "Prejoin extraction source column not found: %s.%s",
                            pj_def.target_table,
                            ext.source_column_name,
                        )
                        continue

                    alias = ext.target_column_alias or ext.source_column_name
                    extraction, _ = PrejoinExtractionColumnORM.objects.get_or_create(
                        prejoin=prejoin_obj,
                        source_column=tgt_col,
                        defaults={
                            "prejoin_target_column_alias": ext.target_column_alias
                        },
                    )
                    self._prejoin_extractions[f"{stage.stage_name}|{alias}"] = (
                        extraction
                    )

    # ------------------------------------------------------------------
    # Satellites
    # ------------------------------------------------------------------

    def _import_satellites(self, export: ProjectExport) -> None:
        sat_type_map = {
            "standard": Satellite.SatelliteType.STANDARD,
            "reference": Satellite.SatelliteType.REFERENCE,
            "non_historized": Satellite.SatelliteType.NON_HISTORIZED,
            "multi_active": Satellite.SatelliteType.MULTI_ACTIVE,
        }

        for sat_def in export.satellites:
            if sat_def.parent_entity_type == "hub":
                parent_hub = self._hubs.get(sat_def.parent_entity)
                parent_link = None
            else:
                parent_hub = None
                parent_link = self._links.get(sat_def.parent_entity)

            if not parent_hub and not parent_link:
                logger.warning(
                    "Parent entity not found for satellite %s", sat_def.satellite_name
                )
                continue

            source_table_key = f"{sat_def.source_system}|{sat_def.source_table}"
            source_table = self._source_tables.get(source_table_key)
            if not source_table:
                logger.warning(
                    "Source table not found for satellite %s: %s",
                    sat_def.satellite_name,
                    source_table_key,
                )
                continue

            sat = Satellite.objects.create(
                project=self.project,
                satellite_physical_name=sat_def.satellite_name,
                satellite_type=sat_type_map.get(
                    sat_def.satellite_type, Satellite.SatelliteType.STANDARD
                ),
                group=self._groups.get(sat_def.group) if sat_def.group else None,
                parent_hub=parent_hub,
                parent_link=parent_link,
                source_table=source_table,
            )
            self._satellites[sat_def.satellite_name] = sat

            for i, col_def in enumerate(sat_def.columns):
                staging = self._resolve_staging(
                    sat_def.source_system,
                    sat_def.source_table,
                    col_def.source_column,
                    sat_def.stage_name,
                )
                if not staging:
                    logger.warning(
                        "Staging column not found for %s.%s",
                        sat_def.satellite_name,
                        col_def.source_column,
                    )
                    continue

                SatelliteColumn.objects.create(
                    satellite=sat,
                    staging_column=staging,
                    target_column_name=col_def.target_column_name,
                    is_multi_active_key=col_def.is_multi_active_key,
                    include_in_delta_detection=col_def.include_in_delta_detection,
                    target_column_transformation=col_def.target_column_transformation,
                    column_sort_order=i,
                )

    # ------------------------------------------------------------------
    # Reference Tables
    # ------------------------------------------------------------------

    def _import_reference_tables(self, export: ProjectExport) -> None:
        hist_type_map = {
            "latest": ReferenceTable.HistorizationType.LATEST,
            "full": ReferenceTable.HistorizationType.FULL,
            "snapshot_based": ReferenceTable.HistorizationType.SNAPSHOT_BASED,
        }

        for rt_def in export.reference_tables:
            hub = self._hubs.get(rt_def.reference_hub_name)
            if not hub:
                logger.warning(
                    "Reference hub not found for reference table %s", rt_def.table_name
                )
                continue

            snap_control = None
            snap_logic = None
            if (
                rt_def.historization_type == "snapshot_based"
                and rt_def.snapshot_control_table
                and rt_def.snapshot_logic_column
            ):
                snap_control = self._snapshot_controls.get(
                    rt_def.snapshot_control_table
                )
                snap_logic = self._snapshot_logics.get(
                    f"{rt_def.snapshot_control_table}|{rt_def.snapshot_logic_column}"
                )

            ref_table = ReferenceTable.objects.create(
                project=self.project,
                reference_table_physical_name=rt_def.table_name,
                reference_hub=hub,
                historization_type=hist_type_map.get(
                    rt_def.historization_type, ReferenceTable.HistorizationType.LATEST
                ),
                snapshot_control_table=snap_control,
                snapshot_control_logic=snap_logic,
            )

            for sat_assign in rt_def.satellites:
                sat = self._satellites.get(sat_assign.satellite_name)
                if not sat:
                    logger.warning(
                        "Satellite %s not found for ref table assignment",
                        sat_assign.satellite_name,
                    )
                    continue

                assignment, _ = ReferenceTableSatelliteAssignment.objects.get_or_create(
                    reference_table=ref_table, reference_satellite=sat
                )

                for col_name in sat_assign.include_columns:
                    col = SatelliteColumn.objects.filter(
                        satellite=sat, target_column_name=col_name
                    ).first()
                    if col:
                        assignment.include_columns.add(col)

                for col_name in sat_assign.exclude_columns:
                    col = SatelliteColumn.objects.filter(
                        satellite=sat, target_column_name=col_name
                    ).first()
                    if col:
                        assignment.exclude_columns.add(col)

    # ------------------------------------------------------------------
    # PITs
    # ------------------------------------------------------------------

    def _import_pits(self, export: ProjectExport) -> None:
        for pit_def in export.pits:
            tracked_hub = None
            tracked_link = None
            if pit_def.tracked_entity_type == "hub":
                tracked_hub = self._hubs.get(pit_def.tracked_entity_name)
            else:
                tracked_link = self._links.get(pit_def.tracked_entity_name)

            if not tracked_hub and not tracked_link:
                logger.warning("Tracked entity not found for PIT %s", pit_def.pit_name)
                continue

            # PITs export the v1 name; the cache stores v0 names (as in the ORM)
            snap_ctrl_key = (
                pit_def.snapshot_control_name.removesuffix("_v1").removesuffix("_v0")
                + "_v0"
            )
            snap_control = self._snapshot_controls.get(snap_ctrl_key)
            snap_logic = self._snapshot_logics.get(
                f"{snap_ctrl_key}|{pit_def.snapshot_logic_column}"
            )
            if not snap_logic:
                logger.warning(
                    "Snapshot logic not found for PIT %s: %s|%s",
                    pit_def.pit_name,
                    snap_ctrl_key,
                    pit_def.snapshot_logic_column,
                )
                continue

            pit = PIT.objects.create(
                project=self.project,
                pit_physical_name=pit_def.pit_name,
                tracked_entity_type=(
                    PIT.TrackedEntityType.HUB
                    if tracked_hub
                    else PIT.TrackedEntityType.LINK
                ),
                tracked_hub=tracked_hub,
                tracked_link=tracked_link,
                snapshot_control_table=snap_control,
                snapshot_control_logic=snap_logic,
                dimension_key_column_name=pit_def.dimension_key_column,
                pit_type=pit_def.pit_type,
                use_snapshot_optimization=pit_def.use_snapshot_optimization,
                include_business_objects_before_appearance=pit_def.include_business_objects_before_appearance,
            )

            for sat_name in pit_def.satellites:
                sat = self._satellites.get(sat_name)
                if not sat:
                    sat = Satellite.objects.filter(
                        project=self.project, satellite_physical_name=sat_name
                    ).first()
                if sat:
                    pit.satellites.add(sat)
