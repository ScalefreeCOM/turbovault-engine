"""
Model builder service for Data Vault export.

Transforms Django ORM models into intermediate Pydantic export models
by deriving all necessary information for generation.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

from engine.services.export.models import (
    HashkeyDefinition,
    HubDefinition,
    HubSourceInfo,
    LinkColumnMapping,
    LinkDefinition,
    LinkSourceInfo,
    MultiActiveConfig,
    PITDefinition,
    PrejoinCondition,
    PrejoinDefinitionExport,
    PrejoinExtractionColumn,
    ProjectExport,
    ReferenceTableDefinition,
    ReferenceTableSatelliteAssignment,
    SatelliteColumnDef,
    SatelliteDefinition,
    SnapshotControlDefinition,
    SnapshotLogicPattern,
    SourceColumnDef,
    SourceSystemDef,
    SourceTableDef,
    StageDefinition,
    StageHashdiffDef,
    StageHashkeyDef,
)

if TYPE_CHECKING:
    from engine.models import Project, SourceTable


class ModelBuilder:
    """
    Builds intermediate export models from Django ORM data.

    This is the core logic layer that:
    - Queries all relevant Django models for a project
    - Derives hashkey definitions for stages from hub/link mappings
    - Aggregates information into target-agnostic representations
    """

    def __init__(self, project: Project) -> None:
        """
        Initialize the builder for a specific project.

        Args:
            project: Django Project model instance
        """
        self.project = project

    def build(
        self,
        export_sources: bool = True,
        generate_tests: bool = True,
        generate_dbml: bool = False,
    ) -> ProjectExport:
        """
        Build complete project export from Django models.

        Args:
            export_sources: Whether to include source system definitions
            generate_tests: Whether tests should be generated (for future dbt generation)
            generate_dbml: Whether DBML file should be generated (for future use)

        Returns:
            ProjectExport with all definitions
        """
        return ProjectExport(
            project_name=self.project.name,
            project_description=self.project.description or None,
            generated_at=datetime.now(),
            stage_schema=(
                self.project.config.get("stage_schema") if self.project.config else None
            ),
            rdv_schema=(
                self.project.config.get("rdv_schema") if self.project.config else None
            ),
            export_sources=export_sources,
            generate_tests=generate_tests,
            generate_dbml=generate_dbml,
            sources=self._build_sources() if export_sources else [],
            hubs=self._build_hubs(),
            links=self._build_links(),
            stages=self._build_stages(),
            satellites=self._build_satellites(),
            snapshot_controls=self._build_snapshot_controls(),
            reference_tables=self._build_reference_tables(),
            pits=self._build_pits(),
        )

    def _build_sources(self) -> list[SourceSystemDef]:
        """
        Build source system definitions from Django models.

        Returns:
            List of source system definitions with their tables/columns
        """
        from engine.models import SourceSystem

        source_systems = SourceSystem.objects.filter(
            project=self.project
        ).prefetch_related("tables__columns")

        result = []
        for source_system in source_systems:
            tables = []
            for table in source_system.tables.all():
                columns = [
                    SourceColumnDef(
                        column_name=col.source_column_physical_name,
                        datatype=col.source_column_datatype,
                    )
                    for col in table.columns.all()
                ]

                tables.append(
                    SourceTableDef(
                        table_name=table.physical_table_name,
                        alias=table.alias,
                        record_source=table.record_source_value,
                        load_date=table.load_date_value,
                        columns=columns,
                    )
                )

            result.append(
                SourceSystemDef(
                    name=source_system.name,
                    schema_name=source_system.schema_name,
                    database_name=source_system.database_name,
                    tables=tables,
                )
            )

        return result

    def _build_hubs(self) -> list[HubDefinition]:
        """
        Build hub definitions from Django models.

        Returns:
            List of hub definitions with hashkey and source info
        """
        from engine.models import Hub, HubColumn

        hubs = Hub.objects.filter(project=self.project).prefetch_related(
            "columns__source_mappings__source_column__source_table__source_system"
        )

        result = []
        for hub in hubs:
            # Get business key columns (ordered)
            bk_columns = hub.columns.filter(
                column_type=HubColumn.ColumnType.BUSINESS_KEY
            ).order_by("sort_order")

            business_key_names = [col.column_name for col in bk_columns]

            # Get additional columns
            additional_columns = hub.columns.filter(
                column_type=HubColumn.ColumnType.ADDITIONAL_COLUMN
            ).order_by("sort_order")

            additional_column_names = [col.column_name for col in additional_columns]

            # Build hashkey definition for standard hubs
            hashkey = None
            if hub.hub_type == Hub.HubType.STANDARD and hub.hub_hashkey_name:
                hashkey = HashkeyDefinition(
                    hashkey_name=hub.hub_hashkey_name, business_keys=business_key_names
                )

            # Get source tables feeding this hub
            source_info = self._get_hub_source_info(hub)

            result.append(
                HubDefinition(
                    hub_name=hub.hub_physical_name,
                    hub_type=hub.hub_type,
                    group=hub.group.group_name if hub.group else None,
                    hashkey=hashkey,
                    business_key_columns=business_key_names,
                    additional_columns=additional_column_names,
                    source_tables=source_info,
                    create_record_tracking_satellite=hub.create_record_tracking_satellite,
                    create_effectivity_satellite=hub.create_effectivity_satellite,
                )
            )

        return result

    def _get_hub_source_info(self, hub) -> list[HubSourceInfo]:
        """
        Get information about source tables feeding a hub.

        Groups source columns by source table to show which columns
        map to business keys for each source.
        """
        from engine.models import HubColumn

        # Group mappings by source table
        source_table_map: dict[str, dict] = defaultdict(
            lambda: {"source_system": "", "stage_name": "", "columns": []}
        )

        for column in hub.columns.filter(column_type=HubColumn.ColumnType.BUSINESS_KEY):
            for mapping in column.source_mappings.all():
                table = mapping.source_column.source_table
                table_key = table.physical_table_name

                source_table_map[table_key]["source_system"] = table.source_system.name
                source_table_map[table_key][
                    "stage_name"
                ] = f"stg__{table.source_system.name.lower().replace(' ', '_')}__{table.physical_table_name.lower()}"
                source_table_map[table_key]["columns"].append(
                    mapping.source_column.source_column_physical_name
                )

        return [
            HubSourceInfo(
                source_table=table_name,
                source_system=info["source_system"],
                stage_name=info["stage_name"],
                business_key_columns=info["columns"],
            )
            for table_name, info in source_table_map.items()
        ]

    def _build_stages(self) -> list[StageDefinition]:
        """
        Build stage definitions for all source tables.

        For each source table, aggregates all hashkeys that need to be
        computed from hubs (and future: links) that use this source,
        plus hashdiffs from satellites.

        Returns:
            List of stage definitions with hashkey and hashdiff calculations
        """
        from engine.models import SourceTable

        source_tables = (
            SourceTable.objects.filter(project=self.project)
            .select_related("source_system")
            .prefetch_related("columns")
        )

        result = []
        for table in source_tables:
            # Get all hashkeys needed for this source table
            hashkeys = self._get_hashkeys_for_source_table(table)

            # Get hashdiffs from satellites that use this source table
            hashdiffs = self._get_hashdiffs_for_source_table(table)

            # Get multi-active config if any multi-active satellite uses this table
            multi_active_config = self._get_multi_active_config_for_source_table(table)

            # Get prejoins that use this source table
            prejoins = self._get_prejoins_for_source_table(table)

            # Get columns
            columns = [
                SourceColumnDef(
                    column_name=col.source_column_physical_name,
                    datatype=col.source_column_datatype,
                )
                for col in table.columns.all()
            ]

            # Generate stage name (stg__<system>__<table>)
            stage_name = f"stg__{table.source_system.name.lower().replace(' ', '_')}__{table.physical_table_name.lower()}"

            result.append(
                StageDefinition(
                    stage_name=stage_name,
                    source_table=table.physical_table_name,
                    source_schema=table.source_system.schema_name,
                    source_system=table.source_system.name,
                    record_source=table.record_source_value,
                    load_date=table.load_date_value,
                    hashkeys=hashkeys,
                    hashdiffs=hashdiffs,
                    prejoins=prejoins,
                    multi_active_config=multi_active_config,
                    columns=columns,
                )
            )

        return result

    def _get_hashdiffs_for_source_table(
        self, source_table: SourceTable
    ) -> list[StageHashdiffDef]:
        """
        Get all hashdiff definitions for satellites using this source table.

        Each satellite creates one hashdiff containing columns where
        include_in_delta_detection is True.
        """
        from engine.models import Satellite

        satellites = Satellite.objects.filter(
            source_table=source_table
        ).prefetch_related("columns__source_column")

        result = []
        for sat in satellites:
            # Get columns that should be included in hashdiff
            hashdiff_columns = [
                col.target_column_name or col.source_column.source_column_physical_name
                for col in sat.columns.all()
                if col.include_in_delta_detection
            ]

            if hashdiff_columns:
                # Generate hashdiff name (hd_<satellite_name_without_sat_prefix>)
                sat_name = sat.satellite_physical_name
                if sat_name.startswith("sat_"):
                    hd_name = f"hd_{sat_name[4:]}"
                else:
                    hd_name = f"hd_{sat_name}"

                result.append(
                    StageHashdiffDef(
                        satellite_name=sat.satellite_physical_name,
                        hashdiff_name=hd_name,
                        columns=hashdiff_columns,
                    )
                )

        return result

    def _get_multi_active_config_for_source_table(
        self, source_table: SourceTable
    ) -> MultiActiveConfig | None:
        """
        Get multi-active configuration if any multi-active satellite uses this source table.

        Takes config from the first multi-active satellite found for this table.
        Returns None if no multi-active satellite exists.
        """
        from engine.models import Satellite

        # Find multi-active satellites for this source table
        multi_active_sat = (
            Satellite.objects.filter(
                source_table=source_table,
                satellite_type=Satellite.SatelliteType.MULTI_ACTIVE,
            )
            .select_related("parent_hub")
            .prefetch_related("columns__source_column")
            .first()
        )

        if not multi_active_sat:
            return None

        # Get multi-active key columns
        ma_key_columns = [
            col.target_column_name or col.source_column.source_column_physical_name
            for col in multi_active_sat.columns.all()
            if col.is_multi_active_key
        ]

        # Get parent hashkey
        main_hashkey = ""
        if multi_active_sat.parent_hub and multi_active_sat.parent_hub.hub_hashkey_name:
            main_hashkey = multi_active_sat.parent_hub.hub_hashkey_name
        # Future: handle parent_link.link_hashkey_name

        if ma_key_columns and main_hashkey:
            return MultiActiveConfig(
                multi_active_key=ma_key_columns, main_hashkey_column=main_hashkey
            )

        return None

    def _get_prejoins_for_source_table(
        self, source_table: SourceTable
    ) -> list[PrejoinDefinitionExport]:
        """
        Get prejoin definitions for a source table.

        Queries prejoins where this source table is the main table being joined from,
        and builds the export representation with join conditions and extraction columns.

        Args:
            source_table: The source table to get prejoins for

        Returns:
            List of prejoin export definitions
        """
        from engine.models import PrejoinDefinition

        # Find all prejoins where this is the source table
        prejoins = PrejoinDefinition.objects.filter(
            source_table=source_table
        ).prefetch_related(
            "prejoin_condition_source_column",
            "prejoin_condition_target_column",
            "prejoin_target_table",
            "extraction_columns__source_column",
        )

        result = []
        for prejoin in prejoins:
            # Build join conditions
            source_columns = [
                col.source_column_physical_name
                for col in prejoin.prejoin_condition_source_column.all()
            ]
            target_columns = [
                col.source_column_physical_name
                for col in prejoin.prejoin_condition_target_column.all()
            ]

            join_conditions = PrejoinCondition(
                source_columns=source_columns,
                target_columns=target_columns,
                operator=prejoin.prejoin_operator,
            )

            # Get extraction column names
            extraction_columns = [
                PrejoinExtractionColumn(
                    source_column_name=ext.source_column.source_column_physical_name,
                    target_column_alias=ext.prejoin_target_column_alias
                    or ext.source_column.source_column_physical_name,
                )
                for ext in prejoin.extraction_columns.all()
            ]

            result.append(
                PrejoinDefinitionExport(
                    target_table=prejoin.prejoin_target_table.physical_table_name,
                    join_conditions=join_conditions,
                    extraction_columns=extraction_columns,
                )
            )

        return result

    def _get_hashkeys_for_source_table(
        self, source_table: SourceTable
    ) -> list[StageHashkeyDef]:
        """
        Get all hashkey definitions needed for a source table's stage.

        Queries hub and link source mappings to find all hashkeys that need
        to be calculated from this source table.

        Args:
            source_table: The source table to get hashkeys for

        Returns:
            List of hashkey definitions for the stage
        """
        from engine.models import (
            Hub,
            HubColumn,
            HubSourceMapping,
            LinkColumn,
            LinkHubSourceMapping,
            LinkSourceMapping,
        )

        result = []

        # ========================================================================
        # 1. Process Hub Hashkeys
        # ========================================================================

        # Find all hub source mappings where source column is from this table
        hub_mappings = HubSourceMapping.objects.filter(
            source_column__source_table=source_table
        ).select_related("hub_column__hub", "source_column")

        # Group by hub to build hashkey definitions
        hub_columns_map: dict[str, dict] = defaultdict(
            lambda: {"hub": None, "source_columns": []}
        )

        for mapping in hub_mappings:
            hub = mapping.hub_column.hub
            hub_key = str(hub.hub_id)

            hub_columns_map[hub_key]["hub"] = hub

            # Only include business key columns for hashkey calculation
            if mapping.hub_column.column_type == HubColumn.ColumnType.BUSINESS_KEY:
                hub_columns_map[hub_key]["source_columns"].append(
                    {
                        "source_column": mapping.source_column.source_column_physical_name,
                        "sort_order": mapping.hub_column.sort_order or 0,
                    }
                )

        for _hub_key, info in hub_columns_map.items():
            hub = info["hub"]

            # Skip if not a standard hub (no hashkey needed)
            if hub.hub_type != Hub.HubType.STANDARD or not hub.hub_hashkey_name:
                continue

            # Sort source columns by hub column sort order
            sorted_columns = sorted(
                info["source_columns"], key=lambda x: x["sort_order"]
            )
            source_column_names = [c["source_column"] for c in sorted_columns]

            if source_column_names:  # Only add if we have business key columns
                result.append(
                    StageHashkeyDef(
                        target_entity=hub.hub_physical_name,
                        entity_type="hub",
                        hashkey_name=hub.hub_hashkey_name,
                        business_key_columns=source_column_names,
                    )
                )

        # ========================================================================
        # 2. Process Link Hashkeys
        # ========================================================================

        # Find all link hub source mappings where source column is from this table
        # This includes both direct source_column and prejoin_extraction_column
        link_hub_mappings = LinkHubSourceMapping.objects.filter(
            source_column__source_table=source_table
        ).select_related(
            "link_hub_reference__link",
            "link_hub_reference__hub",
            "standard_hub_column",
            "source_column",
        ) | LinkHubSourceMapping.objects.filter(
            prejoin_extraction_column__source_column__source_table=source_table
        ).select_related(
            "link_hub_reference__link",
            "link_hub_reference__hub",
            "standard_hub_column",
            "prejoin_extraction_column__source_column",
        )

        # Group by link to build link hashkey definitions
        link_columns_map: dict[str, dict] = defaultdict(
            lambda: {
                "link": None,
                "hub_source_columns": [],  # Columns from hub references
                "dependent_child_keys": [],  # Dependent child key columns
            }
        )

        for mapping in link_hub_mappings:
            link = mapping.link_hub_reference.link
            link_key = str(link.link_id)

            link_columns_map[link_key]["link"] = link

            # Get the source column (either direct or from prejoin)
            if mapping.source_column:
                source_col_name = mapping.source_column.source_column_physical_name
            elif mapping.prejoin_extraction_column:
                source_col_name = (
                    mapping.prejoin_extraction_column.source_column.source_column_physical_name
                )
            else:
                continue  # Skip invalid mappings

            # Add to hub source columns with proper sorting
            link_columns_map[link_key]["hub_source_columns"].append(
                {
                    "source_column": source_col_name,
                    "hub_ref_sort_order": mapping.link_hub_reference.sort_order or 0,
                    "hub_col_sort_order": mapping.standard_hub_column.sort_order or 0,
                }
            )

        # Now find dependent child keys for each link from this source table
        link_source_mappings = LinkSourceMapping.objects.filter(
            source_column__source_table=source_table,
            link_column__column_type=LinkColumn.ColumnType.DEPENDANT_CHILD_KEY,
        ).select_related("link_column__link", "source_column")

        for mapping in link_source_mappings:
            link = mapping.link_column.link
            link_key = str(link.link_id)

            # Initialize link entry if not already present
            if link_key not in link_columns_map:
                link_columns_map[link_key] = {
                    "link": link,
                    "hub_source_columns": [],
                    "dependent_child_keys": [],
                }

            link_columns_map[link_key]["dependent_child_keys"].append(
                {
                    "source_column": mapping.source_column.source_column_physical_name,
                    "sort_order": mapping.link_column.sort_order or 0,
                }
            )

        # Build link hashkey definitions
        for _link_key, info in link_columns_map.items():
            link = info["link"]

            # Skip if no hashkey name is defined
            if not link.link_hashkey_name:
                continue

            # Sort hub source columns first by hub reference sort order, then by hub column sort order
            sorted_hub_columns = sorted(
                info["hub_source_columns"],
                key=lambda x: (x["hub_ref_sort_order"], x["hub_col_sort_order"]),
            )
            hub_column_names = [c["source_column"] for c in sorted_hub_columns]

            # Sort dependent child keys by their sort order
            sorted_child_keys = sorted(
                info["dependent_child_keys"], key=lambda x: x["sort_order"]
            )
            child_key_names = [c["source_column"] for c in sorted_child_keys]

            # Combine hub columns and dependent child keys
            all_business_keys = hub_column_names + child_key_names

            # Only add if we have at least some business key columns
            if all_business_keys:
                result.append(
                    StageHashkeyDef(
                        target_entity=link.link_physical_name,
                        entity_type="link",
                        hashkey_name=link.link_hashkey_name,
                        business_key_columns=all_business_keys,
                    )
                )

        return result

    def _build_satellites(self) -> list[SatelliteDefinition]:
        """
        Build satellite definitions from Django models.

        Returns:
            List of satellite definitions with columns
        """
        from engine.models import Satellite

        satellites = Satellite.objects.filter(project=self.project).prefetch_related(
            "columns__source_column__source_table", "parent_hub", "parent_link"
        )

        result = []
        for sat in satellites:
            # Skip satellites without source_table
            if not sat.source_table:
                continue

            # Determine parent entity, hashkey, and business keys
            parent_business_keys: list[str] = []
            if sat.parent_hub:
                parent_name = sat.parent_hub.hub_physical_name
                parent_type = "hub"
                parent_hashkey = sat.parent_hub.hub_hashkey_name or ""
                # Get business keys from hub columns
                parent_business_keys = list(
                    sat.parent_hub.columns.values_list("column_name", flat=True)
                )
            elif sat.parent_link:
                parent_name = sat.parent_link.link_physical_name
                parent_type = "link"
                parent_hashkey = sat.parent_link.link_hashkey_name or ""
            else:
                # No valid parent
                continue

            # Generate stage name
            stage_name = f"stg__{sat.source_table.source_system.name.lower().replace(' ', '_')}__{sat.source_table.physical_table_name.lower()}"

            # Generate hashdiff name (hd_<satellite_name_without_sat_prefix>)
            sat_name = sat.satellite_physical_name
            if sat_name.startswith("sat_"):
                hashdiff_name = f"hd_{sat_name[4:]}"
            else:
                hashdiff_name = f"hd_{sat_name}"

            # Build column definitions
            columns = []
            for col in sat.columns.all():
                columns.append(
                    SatelliteColumnDef(
                        source_column=col.source_column.source_column_physical_name,
                        target_column_name=col.target_column_name,
                        is_multi_active_key=col.is_multi_active_key,
                        include_in_delta_detection=col.include_in_delta_detection,
                        target_column_transformation=col.target_column_transformation,
                    )
                )

            result.append(
                SatelliteDefinition(
                    satellite_name=sat.satellite_physical_name,
                    satellite_type=sat.satellite_type,
                    group=sat.group.group_name if sat.group else None,
                    parent_entity=parent_name,
                    parent_entity_type=parent_type,
                    parent_hashkey=parent_hashkey,
                    parent_business_keys=parent_business_keys,
                    source_table=sat.source_table.physical_table_name,
                    source_system=sat.source_table.source_system.name,
                    stage_name=stage_name,
                    hashdiff_name=hashdiff_name,
                    columns=columns,
                )
            )

        return result

    def _build_links(self) -> list[LinkDefinition]:
        """
        Build link definitions from Django models.

        Returns:
            List of link definitions with hub references and source info
        """
        from engine.models import Link, LinkColumn

        links = Link.objects.filter(project=self.project).prefetch_related(
            "hub_references",
            "columns__source_mappings__source_column__source_table__source_system",
        )

        result = []
        for link in links:
            # Get hub references with their hashkey names
            hub_refs = link.hub_references.all()
            hub_names = [hub_ref.hub.hub_physical_name for hub_ref in hub_refs]
            foreign_hashkeys = [
                hub_ref.hub.hub_hashkey_name
                for hub_ref in hub_refs
                if hub_ref.hub.hub_hashkey_name
            ]

            # Business key columns are NOT stored in LinkColumn
            # They are derived from hub references via LinkHubSourceMapping
            #  For the link definition export, we don't list them separately
            # as they're implicit in the hub_references
            business_key_column_names = []

            # Get payload and additional columns
            payload_cols = link.columns.filter(
                column_type=LinkColumn.ColumnType.PAYLOAD
            ).values_list("column_name", flat=True)

            additional_cols = link.columns.filter(
                column_type=LinkColumn.ColumnType.ADDITIONAL_COLUMN
            ).values_list("column_name", flat=True)

            # Build source table map with column mappings
            source_table_map: dict[str, dict] = {}

            for column in link.columns.all():
                for mapping in column.source_mappings.all():
                    # Handle both direct source columns and prejoin extraction columns
                    if mapping.source_column:
                        # Direct source column mapping
                        table = mapping.source_column.source_table
                        source_col_name = (
                            mapping.source_column.source_column_physical_name
                        )
                    elif mapping.prejoin_extraction_column:
                        # Prejoin extraction column mapping
                        table = (
                            mapping.prejoin_extraction_column.source_column.source_table
                        )
                        source_col_name = (
                            mapping.prejoin_extraction_column.source_column.source_column_physical_name
                        )
                    else:
                        # Skip invalid mappings (should not happen due to validation)
                        continue

                    table_key = table.physical_table_name

                    if table_key not in source_table_map:
                        source_table_map[table_key] = {
                            "source_system": table.source_system.name,
                            "stage_name": f"stg__{table.source_system.name.lower().replace(' ', '_')}__{table.physical_table_name.lower()}",
                            "columns": [],
                        }

                    # Add column mapping
                    source_table_map[table_key]["columns"].append(
                        LinkColumnMapping(
                            link_column_name=column.column_name,
                            link_column_type=column.column_type,
                            source_column_name=source_col_name,
                        )
                    )

            source_tables = [
                LinkSourceInfo(
                    source_table=table_name,
                    source_system=info["source_system"],
                    stage_name=info["stage_name"],
                    columns=info["columns"],
                )
                for table_name, info in source_table_map.items()
            ]

            # Build hashkey definition for link
            # Business key columns are used for hashkey composition
            hashkey = HashkeyDefinition(
                hashkey_name=link.link_hashkey_name,
                business_keys=business_key_column_names,
            )

            result.append(
                LinkDefinition(
                    link_name=link.link_physical_name,
                    link_type=link.link_type,
                    group=link.group.group_name if link.group else None,
                    hashkey=hashkey,
                    hub_references=hub_names,
                    foreign_hashkeys=foreign_hashkeys,
                    business_key_columns=business_key_column_names,
                    payload_columns=list(payload_cols),
                    additional_columns=list(additional_cols),
                    source_tables=source_tables,
                )
            )

        return result

    def _build_snapshot_controls(self) -> list[SnapshotControlDefinition]:
        """
        Build snapshot control definitions from Django models.

        Returns:
            List of SnapshotControlDefinition objects
        """
        from engine.models import SnapshotControlTable

        result = []

        # Get all snapshot control tables for this project
        snapshot_controls = SnapshotControlTable.objects.filter(
            project=self.project
        ).prefetch_related("logic_rules")

        for control in snapshot_controls:
            # Build logic patterns
            logic_patterns = []
            for logic in control.logic_rules.all():
                logic_patterns.append(
                    SnapshotLogicPattern(
                        column_name=logic.snapshot_control_logic_column_name,
                        component=logic.snapshot_component,
                        duration=logic.snapshot_duration,
                        unit=logic.snapshot_unit,
                        forever=logic.snapshot_forever,
                    )
                )

            result.append(
                SnapshotControlDefinition(
                    name=control.name,
                    start_date=control.snapshot_start_date.isoformat(),
                    end_date=control.snapshot_end_date.isoformat(),
                    daily_time=control.daily_snapshot_time.isoformat(),
                    logic_patterns=logic_patterns,
                )
            )

        return result

    def _build_reference_tables(self) -> list[ReferenceTableDefinition]:
        """
        Build reference table definitions from Django models.

        Returns:
            List of ReferenceTableDefinition objects
        """
        from engine.models import ReferenceTable

        result = []

        # Get all reference tables for this project
        reference_tables = (
            ReferenceTable.objects.filter(project=self.project)
            .select_related(
                "reference_hub", "snapshot_control_table", "snapshot_control_logic"
            )
            .prefetch_related(
                "satellite_assignments__reference_satellite",
                "satellite_assignments__include_columns",
                "satellite_assignments__exclude_columns",
            )
        )

        for ref_table in reference_tables:
            # Build satellite assignments
            satellite_assignments = []
            for assignment in ref_table.satellite_assignments.all():
                # Get column names
                include_cols = [
                    col.satellite_column_physical_name
                    for col in assignment.include_columns.all()
                ]
                exclude_cols = [
                    col.satellite_column_physical_name
                    for col in assignment.exclude_columns.all()
                ]

                satellite_assignments.append(
                    ReferenceTableSatelliteAssignment(
                        satellite_name=assignment.reference_satellite.satellite_physical_name,
                        include_columns=include_cols,
                        exclude_columns=exclude_cols,
                    )
                )

            # Determine snapshot info
            snapshot_table_name = None
            snapshot_logic_column = None
            if (
                ref_table.historization_type
                == ReferenceTable.HistorizationType.SNAPSHOT_BASED
            ):
                if ref_table.snapshot_control_logic:
                    snapshot_logic_column = (
                        ref_table.snapshot_control_logic.snapshot_control_logic_column_name
                    )

            result.append(
                ReferenceTableDefinition(
                    table_name=ref_table.reference_table_physical_name,
                    reference_hub_name=ref_table.reference_hub.hub_physical_name,
                    historization_type=ref_table.historization_type,
                    snapshot_control_table=snapshot_table_name,
                    snapshot_logic_column=snapshot_logic_column,
                    satellites=satellite_assignments,
                )
            )

        return result

    def _build_pits(self) -> list[PITDefinition]:
        """
        Build PIT definitions from Django models.

        Returns:
            List of PITDefinition objects
        """
        from engine.models import PIT

        result = []

        # Get all PITs for this project
        pits = (
            PIT.objects.filter(project=self.project)
            .select_related(
                "tracked_hub",
                "tracked_link",
                "snapshot_control_logic",
                "snapshot_control_logic__snapshot_control_table",
            )
            .prefetch_related("satellites")
        )

        for pit in pits:
            # Get tracked entity name and hashkey
            tracked_entity_name = ""
            tracked_hashkey = ""
            if pit.tracked_hub:
                tracked_entity_name = pit.tracked_hub.hub_physical_name
                tracked_hashkey = pit.tracked_hub.hub_hashkey_name or ""
            elif pit.tracked_link:
                tracked_entity_name = pit.tracked_link.link_physical_name
                tracked_hashkey = pit.tracked_link.link_hashkey_name or ""

            # Get satellite names
            satellite_names = [
                sat.satellite_physical_name for sat in pit.satellites.all()
            ]

            # Get snapshot control name (v1)
            snapshot_control_name = ""
            if (
                pit.snapshot_control_logic
                and pit.snapshot_control_logic.snapshot_control_table
            ):
                base_name = pit.snapshot_control_logic.snapshot_control_table.name
                # Ensure we get the v1 name
                snapshot_control_name = (
                    base_name.removesuffix("_v0").removesuffix("_v1") + "_v1"
                )

            result.append(
                PITDefinition(
                    pit_name=pit.pit_physical_name,
                    tracked_entity_type=pit.tracked_entity_type,
                    tracked_entity_name=tracked_entity_name,
                    tracked_hashkey=tracked_hashkey,
                    satellites=satellite_names,
                    snapshot_control_name=snapshot_control_name,
                    snapshot_logic_column=pit.snapshot_control_logic.snapshot_control_logic_column_name,
                    dimension_key_column=pit.dimension_key_column_name,
                    pit_type=pit.pit_type,
                    use_snapshot_optimization=pit.use_snapshot_optimization,
                    include_business_objects_before_appearance=pit.include_business_objects_before_appearance,
                )
            )

        return result
