"""
Excel Import Service for TurboVault Engine.

This service reads legacy Excel metadata formats and transforms them into
the new TurboVault Engine data model.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
from django.db import transaction
from django.utils import timezone

from engine.models.hubs import Hub, HubColumn, HubSourceMapping
from engine.models.links import Link, LinkColumn, LinkSourceMapping
from engine.models.pit import PIT
from engine.models.prejoin import PrejoinDefinition, PrejoinExtractionColumn
from engine.models.project import Project
from engine.models.reference_table import (
    ReferenceTable,
    ReferenceTableSatelliteAssignment,
)
from engine.models.satellites import Satellite, SatelliteColumn
from engine.models.snapshot_control import SnapshotControlLogic, SnapshotControlTable
from engine.models.source_metadata import SourceColumn, SourceSystem, SourceTable

logger = logging.getLogger(__name__)


class ExcelImportService:
    """
    Service to import metadata from the legacy Excel format.

    Processing is done sheet-by-sheet for efficiency.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.excel_file = pd.ExcelFile(file_path)
        self.project: Project | None = None
        self._source_systems: dict[str, SourceSystem] = {}
        self._source_tables: dict[str, SourceTable] = {}
        self._source_columns: dict[str, SourceColumn] = {}
        self._hubs: dict[str, Hub] = {}
        self._links: dict[str, Link] = {}
        self._satellites: dict[str, Satellite] = {}
        self._hub_columns: dict[str, HubColumn] = {}
        self._prejoins: dict[str, PrejoinDefinition] = (
            {}
        )  # key: source_table_id|target_table_id
        self._extractions: dict[str, PrejoinExtractionColumn] = (
            {}
        )  # key: prejoin_id|source_col_name
        self._snapshot_control: SnapshotControlTable | None = None
        self._snapshot_logic: SnapshotControlLogic | None = None

    @transaction.atomic
    def import_metadata(
        self, project_name: str, description: str | None = None
    ) -> Project:
        """
        Main entry point for importing metadata from Excel.
        """
        logger.info(f"Starting import from {self.file_path}")

        # 1. Create Project
        self.project = Project.objects.create(
            name=project_name,
            description=description or f"Imported from {self.file_path}",
            config={},
        )

        # 2. Process Source Data (Systems and Tables)
        if "source_data" in self.excel_file.sheet_names:
            self._process_source_data(self.excel_file.parse("source_data"))

        # 3. Collect all Source Columns first because they are referenced everywhere
        self._collect_all_source_columns()

        # 4. Process Hubs
        if "standard_hub" in self.excel_file.sheet_names:
            self._process_standard_hubs(self.excel_file.parse("standard_hub"))
        if "ref_hub" in self.excel_file.sheet_names:
            self._process_reference_hubs(self.excel_file.parse("ref_hub"))

        # 5. Process Links
        if "standard_link" in self.excel_file.sheet_names:
            self._process_standard_links(self.excel_file.parse("standard_link"))

        # 5.1 Process Prejoins before links
        if "standard_link" in self.excel_file.sheet_names:
            self._process_prejoins(self.excel_file.parse("standard_link"))
        if "non_historized_link" in self.excel_file.sheet_names:
            self._process_prejoins(self.excel_file.parse("non_historized_link"))

        if "non_historized_link" in self.excel_file.sheet_names:
            self._process_non_historized_links(
                self.excel_file.parse("non_historized_link")
            )

        # 6. Process Satellites
        sat_sheets = [
            "standard_satellite",
            "ref_sat",
            "non_historized_satellite",
            "multiactive_satellite",
        ]
        for sheet in sat_sheets:
            if sheet in self.excel_file.sheet_names:
                self._process_satellites(self.excel_file.parse(sheet), sheet)

        # 7. Create default Snapshot Control
        self._create_default_snapshot_control()

        # 8. Process Prejoins (after source columns, before links that might use them)
        # Wait, non_historized_link processing already happens.
        # Actually, let's process prejoins EARLY if they are needed by links.
        # I'll move this up in a second if needed.

        # 9. Process Reference Tables
        if "ref_table" in self.excel_file.sheet_names:
            self._process_reference_tables(self.excel_file.parse("ref_table"))

        # 10. Process PITs
        if "pit" in self.excel_file.sheet_names:
            self._process_pits(self.excel_file.parse("pit"))

        logger.info(f"Import completed. Project ID: {self.project.project_id}")
        return self.project

    def _process_source_data(self, df: pd.DataFrame):
        """Processes the source_data sheet to create SourceSystem and SourceTable objects."""
        # Standardize column names (lowercase)
        df.columns = [c.lower() for c in df.columns]

        for _, row in df.iterrows():
            # Source System
            system_name = self._get_val(row, "source_system") or "Unknown System"
            schema_name = self._get_val(row, "source_schema_physical_name") or "public"

            key = f"{system_name}|{schema_name}"
            if key not in self._source_systems:
                system, _ = SourceSystem.objects.get_or_create(
                    project=self.project,
                    schema_name=schema_name,
                    name=system_name,
                    defaults={"database_name": None},
                )
                self._source_systems[key] = system

            system = self._source_systems[key]

            # Source Table
            table_name = self._get_val(row, "source_table_physical_name")
            table_id = self._get_val(row, "source_table_identifier")

            if table_name and table_id not in self._source_tables:
                table = SourceTable.objects.create(
                    project=self.project,
                    source_system=system,
                    physical_table_name=table_name,
                    alias="",  # Feedback: keep alias empty
                    record_source_value=row.get("record_source_column") or "",
                    static_part_of_record_source=row.get(
                        "static_part_of_record_source_column"
                    )
                    or "",
                    load_date_value=row.get("load_date_column") or "sysdate()",
                )
                self._source_tables[table_id] = table
                # Also store by physical name for backup lookup
                if table_name not in self._source_tables:
                    self._source_tables[table_name] = table

    def _collect_all_source_columns(self):
        """
        Scans all sheets to find all mentioned source columns and creates them.
        This is necessary because almost all DV entities refer to source columns.
        """
        logger.info("Collecting source columns from all sheets...")
        columns_to_create: dict[str, set[str]] = {}  # table_name -> set(col_names)

        # Sheets to scan for source columns
        sheets_to_scan = [
            (
                "standard_hub",
                "source_table_identifier",
                ["source_column_physical_name"],
            ),
            ("ref_hub", "source_table_identifier", ["source_column_physical_name"]),
            (
                "standard_link",
                "source_table_identifier",
                ["source_column_physical_name"],
            ),
            (
                "non_historized_link",
                "source_table_identifier",
                ["source_column_physical_name"],
            ),
            (
                "standard_satellite",
                "source_table_identifier",
                ["source_column_physical_name"],
            ),
            ("ref_sat", "source_table_identifier", ["source_column_physical_name"]),
            (
                "non_historized_satellite",
                "source_table_identifier",
                ["source_column_physical_name"],
            ),
            (
                "multiactive_satellite",
                "source_table_identifier",
                ["source_column_physical_name", "multi_active_attributes"],
            ),
            (
                "non_historized_link",
                "source_table_identifier",
                ["source_column_physical_name"],
            ),
            (
                "non_historized_link",
                "prejoin_table_identifier",
                ["prejoin_table_column_name", "prejoin_extraction_column_name"],
            ),
            (
                "standard_link",
                "source_table_identifier",
                ["source_column_physical_name"],
            ),
            (
                "standard_link",
                "prejoin_table_identifier",
                ["prejoin_table_column_name", "prejoin_extraction_column_name"],
            ),
        ]

        for sheet_name, table_col, data_cols in sheets_to_scan:
            if sheet_name not in self.excel_file.sheet_names:
                continue

            df = self.excel_file.parse(sheet_name)
            df.columns = [c.lower() for c in df.columns]

            for _, row in df.iterrows():
                table_key = row.get(table_col)
                if not table_key or pd.isna(table_key):
                    continue

                table_key = str(table_key)
                if table_key not in columns_to_create:
                    columns_to_create[table_key] = set()

                for dc in data_cols:
                    val = row.get(dc)
                    if val and not pd.isna(val):
                        # Special handling for Multi_Active_Attributes (semicolon separated)
                        if dc == "multi_active_attributes":
                            for sub_val in str(val).split(";"):
                                columns_to_create[table_key].add(sub_val.strip())
                        else:
                            columns_to_create[table_key].add(str(val).strip())

        # Now create the columns in the DB
        for table_key, cols in columns_to_create.items():
            table = self._source_tables.get(table_key)
            if not table:
                logger.warning(
                    f"Source table {table_key} not found in source_data, but referenced columns exist."
                )
                continue

            for col_name in cols:
                column, _ = SourceColumn.objects.get_or_create(
                    source_table=table,
                    source_column_physical_name=col_name,
                    defaults={"source_column_datatype": ""},
                )
                self._source_columns[f"{table_key}|{col_name}"] = column
                # Also store by physical name if different
                phys_name = table.physical_table_name
                self._source_columns[f"{phys_name}|{col_name}"] = column

    def _process_standard_hubs(self, df: pd.DataFrame):
        """Processes standard_hub sheet."""
        df.columns = [c.lower() for c in df.columns]

        for _, row in df.iterrows():
            hub_name = str(row.get("target_hub_table_physical_name"))
            if not hub_name or hub_name == "nan":
                continue

            if hub_name not in self._hubs:
                hub = Hub.objects.create(
                    project=self.project,
                    hub_physical_name=hub_name,
                    hub_type=Hub.HubType.STANDARD,
                    hub_hashkey_name=self._get_val(
                        row, "target_primary_key_physical_name"
                    ),
                    create_record_tracking_satellite=str(
                        row.get("record_tracking_satellite")
                    ).upper()
                    == "TRUE",
                    create_effectivity_satellite=False,
                )
                self._hubs[hub_name] = hub
                # Also store by ID if available
                hub_id = self._get_val(row, "hub_identifier")
                if hub_id:
                    self._hubs[hub_id] = hub

            hub = self._hubs[hub_name]

            # Hub Column
            col_name = row.get("business_key_physical_name") or row.get(
                "source_column_physical_name"
            )
            if not col_name:
                continue

            col_name = str(col_name)
            hub_column, created = HubColumn.objects.get_or_create(
                hub=hub,
                column_name=col_name,
                defaults={
                    "column_type": HubColumn.ColumnType.BUSINESS_KEY,
                },
            )

            # Mapping
            source_table_key = str(row.get("source_table_identifier"))
            source_col_name = str(row.get("source_column_physical_name"))
            source_col = self._source_columns.get(
                f"{source_table_key}|{source_col_name}"
            )

            if source_col:
                HubSourceMapping.objects.get_or_create(
                    hub_column=hub_column,
                    source_column=source_col,
                    defaults={
                        "is_primary_source": str(row.get("is_primary_source")).upper()
                        == "TRUE"
                    },
                )

        # Post-processing: ensure at least one primary source per hub column
        for hub in Hub.objects.filter(project=self.project):
            for col in hub.columns.all():
                if not HubSourceMapping.objects.filter(
                    hub_column=col, is_primary_source=True
                ).exists():
                    first_mapping = HubSourceMapping.objects.filter(
                        hub_column=col
                    ).first()
                    if first_mapping:
                        first_mapping.is_primary_source = True
                        first_mapping.save()

    def _process_reference_hubs(self, df: pd.DataFrame):
        """Processes ref_hub sheet."""
        df.columns = [c.lower() for c in df.columns]

        for _, row in df.iterrows():
            hub_name = str(row.get("target_reference_table_physical_name"))
            if not hub_name or hub_name == "nan":
                continue

            if hub_name not in self._hubs:
                hub = Hub.objects.create(
                    project=self.project,
                    hub_physical_name=hub_name,
                    hub_type=Hub.HubType.REFERENCE,
                    hub_hashkey_name=None,
                    create_record_tracking_satellite=False,
                    create_effectivity_satellite=False,
                )
                self._hubs[hub_name] = hub
                hub_id = str(row.get("reference_hub_identifier"))
                if hub_id and hub_id != "nan":
                    self._hubs[hub_id] = hub

            hub = self._hubs[hub_name]

            source_col_name = str(row.get("source_column_physical_name"))
            if not source_col_name or source_col_name == "nan":
                continue

            hub_column, _ = HubColumn.objects.get_or_create(
                hub=hub,
                column_name=source_col_name,
                defaults={
                    "column_type": HubColumn.ColumnType.REFERENCE_KEY,
                },
            )

            # Mapping
            source_table_key = str(row.get("source_table_identifier"))
            source_col = self._source_columns.get(
                f"{source_table_key}|{source_col_name}"
            )

            if source_col:
                HubSourceMapping.objects.get_or_create(
                    hub_column=hub_column,
                    source_column=source_col,
                    defaults={"is_primary_source": True},
                )

    def _process_standard_links(self, df: pd.DataFrame):
        """Processes standard_link sheet."""
        df.columns = [c.lower() for c in df.columns]

        for _, row in df.iterrows():
            link_name = str(row.get("target_link_table_physical_name"))
            if not link_name or link_name == "nan":
                continue

            if link_name not in self._links:
                link = Link.objects.create(
                    project=self.project,
                    link_physical_name=link_name,
                    link_hashkey_name=f"lk_{link_name}",
                    link_type=Link.LinkType.STANDARD,
                )
                self._links[link_name] = link
                link_id = self._get_val(row, "link_identifier")
                if link_id:
                    self._links[link_id] = link

            link = self._links[link_name]

            # Handle Hub References (Many-to-Many)
            hub_id_str = self._get_val(row, "hub_identifier")
            if hub_id_str:
                hub = self._hubs.get(hub_id_str)
                if not hub:
                    hub = Hub.objects.filter(
                        project=self.project, hub_physical_name=hub_id_str
                    ).first()

                if hub and hub.hub_type == Hub.HubType.STANDARD:
                    link.hub_references.add(hub)

                    # Create LinkColumn and Mapping
                    col_name = self._get_val(
                        row, "target_column_physical_name"
                    ) or self._get_val(row, "source_column_physical_name")
                    if col_name:
                        lc, _ = LinkColumn.objects.get_or_create(
                            link=link,
                            column_name=col_name,
                            defaults={
                                "column_type": LinkColumn.ColumnType.BUSINESS_KEY
                            },
                        )

                        # Mapping (could be prejoin)
                        extraction_key = f"{link.link_physical_name}|{self._get_val(row, 'prejoin_target_column_alias') or col_name}"
                        extraction = self._extractions.get(extraction_key)

                        if extraction:
                            LinkSourceMapping.objects.get_or_create(
                                link_column=lc,
                                prejoin_extraction_column=extraction,
                                defaults={"is_primary_source": True},
                            )
                        else:
                            source_table_id = self._get_val(
                                row, "source_table_identifier"
                            )
                            source_col_name = self._get_val(
                                row, "source_column_physical_name"
                            )
                            source_col = self._source_columns.get(
                                f"{source_table_id}|{source_col_name}"
                            )
                            if source_col:
                                LinkSourceMapping.objects.get_or_create(
                                    link_column=lc,
                                    source_column=source_col,
                                    defaults={"is_primary_source": True},
                                )

    def _process_non_historized_links(self, df: pd.DataFrame):
        """Processes non_historized_link sheet."""
        df.columns = [c.lower() for c in df.columns]

        for _, row in df.iterrows():
            link_name = str(row.get("target_link_table_physical_name"))
            if not link_name or link_name == "nan":
                continue

            if link_name not in self._links:
                link = Link.objects.create(
                    project=self.project,
                    link_physical_name=link_name,
                    link_hashkey_name=f"lk_{link_name}",
                    link_type=Link.LinkType.NON_HISTORIZED,
                )
                self._links[link_name] = link
                nh_link_id = self._get_val(row, "nh_link_identifier")
                if nh_link_id:
                    self._links[nh_link_id] = link

            link = self._links[link_name]

            # Hub References
            hub_id_str = self._get_val(row, "hub_identifier")
            if hub_id_str:
                hub = self._hubs.get(hub_id_str)
                if not hub:
                    hub = Hub.objects.filter(
                        project=self.project, hub_physical_name=hub_id_str
                    ).first()
                if hub and hub.hub_type == Hub.HubType.STANDARD:
                    link.hub_references.add(hub)

                    # BKs for NH links are payload usually, but let's add them as business_key if sort_order present?
                    # Spec says NH Hub Column logic is same.
                    col_name = self._get_val(
                        row, "target_column_physical_name"
                    ) or self._get_val(row, "source_column_physical_name")
                    if col_name:
                        lc, _ = LinkColumn.objects.get_or_create(
                            link=link,
                            column_name=col_name,
                            defaults={
                                "column_type": LinkColumn.ColumnType.BUSINESS_KEY
                            },
                        )
                        # mapping handled below in payload if it matches?
                        # Actually let's separated BK and Payload based on hub_identifier presence.

            # Payload Columns (only if hub_identifier is empty or specifically mapped)
            col_name = (
                self._get_val(row, "prejoin_target_column_alias")
                or self._get_val(row, "prejoin_extraction_column_name")
                or self._get_val(row, "source_column_physical_name")
            )
            if col_name:
                link_column, _ = LinkColumn.objects.get_or_create(
                    link=link,
                    column_name=col_name,
                    defaults={"column_type": LinkColumn.ColumnType.PAYLOAD},
                )

                # Mapping
                source_table_key = self._get_val(row, "source_table_identifier")
                source_col_name = self._get_val(row, "source_column_physical_name")

                # Check for prejoin extraction first
                alias = self._get_val(row, "prejoin_target_column_alias")
                ext_col = self._get_val(row, "prejoin_extraction_column_name")
                extraction_key = (
                    f"{link.link_physical_name}|{alias or ext_col or col_name}"
                )
                extraction = self._extractions.get(extraction_key)

                if extraction:
                    LinkSourceMapping.objects.get_or_create(
                        link_column=link_column,
                        prejoin_extraction_column=extraction,
                        defaults={"is_primary_source": True},
                    )
                else:
                    source_col = self._source_columns.get(
                        f"{source_table_key}|{source_col_name}"
                    )
                    if source_col:
                        LinkSourceMapping.objects.get_or_create(
                            link_column=link_column,
                            source_column=source_col,
                            defaults={"is_primary_source": True},
                        )

    def _process_satellites(self, df: pd.DataFrame, sheet_type: str):
        """Processes all types of satellite sheets."""
        df.columns = [c.lower() for c in df.columns]

        for _, row in df.iterrows():
            sat_name_col = (
                "target_reference_table_physical_name"
                if sheet_type == "ref_sat"
                else "target_satellite_table_physical_name"
            )
            sat_name = str(row.get(sat_name_col))

            if not sat_name or sat_name == "nan":
                continue

            if sat_name not in self._satellites:
                sat_type_map = {
                    "standard_satellite": Satellite.SatelliteType.STANDARD,
                    "ref_sat": Satellite.SatelliteType.REFERENCE,
                    "non_historized_satellite": Satellite.SatelliteType.NON_HISTORIZED,
                    "multiactive_satellite": Satellite.SatelliteType.MULTI_ACTIVE,
                }

                # Find parent (Hub or Link)
                parent_id = (
                    self._get_val(row, "parent_identifier")
                    or self._get_val(row, "parent_table_identifier")
                    or self._get_val(row, "nh_link_identifier")
                    or self._get_val(row, "referenced_hub")
                    or self._get_val(row, "parent_hub")
                )

                parent_hub = self._hubs.get(parent_id)
                parent_link = self._links.get(parent_id)

                # Backup lookup by physical name
                if not parent_hub and not parent_link:
                    parent_hub = Hub.objects.filter(
                        project=self.project, hub_physical_name=parent_id
                    ).first()
                    parent_link = Link.objects.filter(
                        project=self.project, link_physical_name=parent_id
                    ).first()

                source_table_key = self._get_val(row, "source_table_identifier")
                source_table = self._source_tables.get(source_table_key)

                if (parent_hub or parent_link) and source_table:
                    satellite = Satellite.objects.create(
                        project=self.project,
                        satellite_physical_name=sat_name,
                        satellite_type=sat_type_map[sheet_type],
                        parent_hub=parent_hub,
                        parent_link=parent_link,
                        source_table=source_table,
                    )
                    self._satellites[sat_name] = satellite
                    # Also store by Identifier
                    sat_id_col = (
                        "ma_satellite_identifier"
                        if sheet_type == "multiactive_satellite"
                        else (
                            "reference_satellite_identifier"
                            if sheet_type == "ref_sat"
                            else "satellite_identifier"
                        )
                    )  # standard and non-historized often use this
                    sat_id = self._get_val(row, sat_id_col)
                    if sat_id:
                        self._satellites[sat_id] = satellite
                else:
                    logger.warning(
                        f"Could not find parent {parent_id} or source table {source_table_key} for satellite {sat_name}"
                    )
                    continue

            satellite = self._satellites[sat_name]

            # Satellite Columns
            # Collect columns to add: (name, is_ma_key)
            cols_to_add: list[tuple[str, bool]] = []

            # 1. Regular Source Column
            regular_col = self._get_val(row, "source_column_physical_name")
            if regular_col:
                cols_to_add.append((regular_col, False))

            # 2. Multi-Active Attributes (MA Keys)
            if sheet_type == "multiactive_satellite":
                ma_attrs = self._get_val(row, "multi_active_attributes")
                if ma_attrs:
                    for s in str(ma_attrs).split(";"):
                        cols_to_add.append((s.strip(), True))

            for scn, is_ma_key in cols_to_add:
                source_table_key = self._get_val(row, "source_table_identifier")
                source_col = self._source_columns.get(f"{source_table_key}|{scn}")
                if source_col:
                    target_col_name = scn
                    if not is_ma_key:
                        tcn = self._get_val(row, "target_column_physical_name")
                        if tcn:
                            target_col_name = tcn

                    SatelliteColumn.objects.get_or_create(
                        satellite=satellite,
                        source_column=source_col,
                        defaults={
                            "is_multi_active_key": is_ma_key,
                            "include_in_delta_detection": sheet_type
                            != "non_historized_satellite",
                            "target_column_name": target_col_name,
                        },
                    )

    def _process_prejoins(self, df: pd.DataFrame):
        """Processes prejoin definitions and extractions."""
        df.columns = [c.lower() for c in df.columns]

        for _, row in df.iterrows():
            source_table_id = self._get_val(row, "source_table_identifier")
            target_table_id = self._get_val(row, "prejoin_table_identifier")

            if not target_table_id:
                continue

            link_name = self._get_val(row, "target_link_table_physical_name")

            # Prejoin Definition
            prejoin_key = f"{source_table_id}|{target_table_id}"
            if prejoin_key not in self._prejoins:
                source_table = self._source_tables.get(source_table_id)
                target_table = self._source_tables.get(target_table_id)

                if source_table and target_table:
                    prejoin = PrejoinDefinition.objects.create(
                        project=self.project,
                        source_table=source_table,
                        prejoin_target_table=target_table,
                        prejoin_operator=PrejoinDefinition.Operator.AND,
                    )

                    # Conditions
                    source_col_name = self._get_val(row, "source_column_physical_name")
                    target_col_name = self._get_val(row, "prejoin_table_column_name")

                    source_col = self._source_columns.get(
                        f"{source_table_id}|{source_col_name}"
                    )
                    target_col = self._source_columns.get(
                        f"{target_table_id}|{target_col_name}"
                    )

                    if source_col:
                        prejoin.prejoin_condition_source_column.add(source_col)
                    if target_col:
                        prejoin.prejoin_condition_target_column.add(target_col)

                    self._prejoins[prejoin_key] = prejoin

            prejoin = self._prejoins.get(prejoin_key)
            if not prejoin:
                continue

            # Extraction Column
            extraction_col_name = self._get_val(row, "prejoin_extraction_column_name")
            if extraction_col_name:
                source_col = self._source_columns.get(
                    f"{target_table_id}|{extraction_col_name}"
                )
                if source_col:
                    extraction, _ = PrejoinExtractionColumn.objects.get_or_create(
                        prejoin=prejoin, source_column=source_col
                    )
                    # Key by link_name + alias/target_col_name for lookup in links
                    alias = self._get_val(row, "prejoin_target_column_alias")
                    self._extractions[f"{link_name}|{alias or extraction_col_name}"] = (
                        extraction
                    )

    def _process_reference_tables(self, df: pd.DataFrame):
        """Processes ref_table sheet."""
        df.columns = [c.lower() for c in df.columns]

        for _, row in df.iterrows():
            ref_table_name = self._get_val(row, "target_reference_table_physical_name")
            hub_id = self._get_val(row, "referenced_hub")

            if not ref_table_name:
                continue

            hub = self._hubs.get(hub_id)
            if not hub:
                hub = Hub.objects.filter(
                    project=self.project, hub_physical_name=hub_id
                ).first()

            if not hub:
                logger.warning(
                    f"Hub {hub_id} not found for reference table {ref_table_name}"
                )
                continue

            hist_type_map = {
                "TRUE": ReferenceTable.HistorizationType.FULL,
                "FALSE": ReferenceTable.HistorizationType.LATEST,
                "FULL": ReferenceTable.HistorizationType.FULL,
                "LATEST": ReferenceTable.HistorizationType.LATEST,
            }
            hist_val = self._get_val(row, "historized") or "LATEST"

            ref_table, _ = ReferenceTable.objects.get_or_create(
                project=self.project,
                reference_table_physical_name=ref_table_name,
                defaults={
                    "reference_hub": hub,
                    "historization_type": hist_type_map.get(
                        hist_val.upper(), ReferenceTable.HistorizationType.LATEST
                    ),
                },
            )

            # Assignment
            sat_id = self._get_val(row, "referenced_satellite")
            sat = self._satellites.get(sat_id)
            if not sat:
                sat = Satellite.objects.filter(
                    project=self.project, satellite_physical_name=sat_id
                ).first()

            if sat:
                assignment, _ = ReferenceTableSatelliteAssignment.objects.get_or_create(
                    reference_table=ref_table, reference_satellite=sat
                )

                # Include/Exclude columns
                include_str = self._get_val(row, "included_columns")
                exclude_str = self._get_val(row, "excluded_columns")

                if include_str:
                    for col_name in include_str.split(","):
                        col = SatelliteColumn.objects.filter(
                            satellite=sat, target_column_name=col_name.strip()
                        ).first()
                        if col:
                            assignment.include_columns.add(col)

                if exclude_str:
                    for col_name in exclude_str.split(","):
                        col = SatelliteColumn.objects.filter(
                            satellite=sat, target_column_name=col_name.strip()
                        ).first()
                        if col:
                            assignment.exclude_columns.add(col)

    def _process_pits(self, df: pd.DataFrame):
        """Processes pit sheet."""
        df.columns = [c.lower() for c in df.columns]

        for _, row in df.iterrows():
            pit_name = self._get_val(row, "pit_physical_table_name")
            entity_id = self._get_val(row, "tracked_entity")

            if not pit_name:
                continue

            hub = self._hubs.get(entity_id)
            link = self._links.get(entity_id)

            # Backup lookup
            if not hub and not link:
                hub = Hub.objects.filter(
                    project=self.project, hub_physical_name=entity_id
                ).first()
                link = Link.objects.filter(
                    project=self.project, link_physical_name=entity_id
                ).first()

            if not hub and not link:
                logger.warning(
                    f"Tracked entity {entity_id} not found for PIT {pit_name}"
                )
                continue

            pit = PIT.objects.create(
                project=self.project,
                pit_physical_name=pit_name,
                tracked_entity_type=(
                    PIT.TrackedEntityType.HUB if hub else PIT.TrackedEntityType.LINK
                ),
                tracked_hub=hub,
                tracked_link=link,
                snapshot_control_table=self._snapshot_control,
                snapshot_control_logic=self._snapshot_logic,
                dimension_key_column_name=self._get_val(row, "dimension_key_name"),
                pit_type=self._get_val(row, "pit_type"),
                custom_record_source=self._get_val(row, "custom_record_source"),
            )

            # Satellites
            sat_ids = str(row.get("satellite_identifiers"))
            if sat_ids and sat_ids != "nan":
                # Split by comma or semicolon
                for sid in sat_ids.replace(";", ",").split(","):
                    sid = sid.strip()
                    if not sid:
                        continue
                    sat = self._satellites.get(sid)
                    if not sat:
                        sat = Satellite.objects.filter(
                            project=self.project, satellite_physical_name=sid
                        ).first()
                    if not sat:
                        # Try searching for satellite where physical name is sid (identifier in excel sometimes refers to physical name)
                        sat = Satellite.objects.filter(
                            project=self.project, satellite_physical_name__iexact=sid
                        ).first()

                    if sat:
                        pit.satellites.add(sat)

    def _create_default_snapshot_control(self):
        """Creates a default snapshot control table and logic rule as per spec."""
        if self._snapshot_control:
            return  # Already created

        today = timezone.now().date()
        self._snapshot_control = SnapshotControlTable.objects.create(
            project=self.project,
            snapshot_start_date=datetime(today.year - 5, 1, 1).date(),
            snapshot_end_date=datetime(today.year + 5, 12, 31).date(),
            daily_snapshot_time=timezone.make_aware(
                datetime(2000, 1, 1, 8, 0, 0)
            ).time(),
        )

        self._snapshot_logic = SnapshotControlLogic.objects.create(
            snapshot_control_table=self._snapshot_control,
            snapshot_control_logic_column_name="is_active",
            snapshot_component=SnapshotControlLogic.SnapshotComponent.BEGINNING_OF_MONTH,
            snapshot_duration=1,
            snapshot_unit=SnapshotControlLogic.SnapshotUnit.YEAR,
            snapshot_forever=False,
        )

    def _get_val(self, row, col) -> str | None:
        """Helper to get a cleaned string value or None if empty."""
        val = row.get(col)
        if (
            pd.isna(val)
            or val is None
            or str(val).lower() == "nan"
            or str(val).lower() == "none"
        ):
            return None
        return str(val).strip()
