
from __future__ import annotations
import logging
import pandas as pd
from datetime import datetime
from django.db import transaction
from django.utils import timezone

from engine.models.hubs import Hub, HubColumn, HubSourceMapping
from engine.models.links import (
    Link,
    LinkColumn,
    LinkHubReference,
    LinkHubSourceMapping,
    LinkSourceMapping,
)
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
from engine.services.metadata_source import MetadataSource

logger = logging.getLogger(__name__)

class BaseImportService:
    def __init__(self, source: MetadataSource):
        self.source = source
        self.project: Project | None = None
        self._source_systems: dict[str, SourceSystem] = {}
        self._source_tables: dict[str, SourceTable] = {}
        self._source_columns: dict[str, SourceColumn] = {}
        self._hubs: dict[str, Hub] = {}
        self._links: dict[str, Link] = {}
        self._satellites: dict[str, Satellite] = {}
        self._hub_columns: dict[str, HubColumn] = {}
        self._prejoins: dict[str, PrejoinDefinition] = {}
        self._extractions: dict[str, PrejoinExtractionColumn] = {}
        self._snapshot_control: SnapshotControlTable | None = None
        self._snapshot_logic: SnapshotControlLogic | None = None

    @transaction.atomic
    def import_metadata(
        self,
        project_name: str | None = None,
        description: str | None = None,
        project: Project | None = None,
        skip_snapshots: bool = False,
    ) -> Project:
        logger.info("Starting metadata import")

        if project:
            self.project = project
        else:
            if not project_name:
                raise ValueError("project_name is required if no project instance is provided")
            self.project = Project.objects.create(
                name=project_name,
                description=description or "Imported metadata",
                config={},
            )

        sheet_names = self.source.get_sheet_names()

        if "source_data" in sheet_names:
            self._process_source_data(self.source.get_data("source_data"))

        self._collect_all_source_columns(sheet_names)

        if "standard_hub" in sheet_names:
            self._process_standard_hubs(self.source.get_data("standard_hub"))
        if "ref_hub" in sheet_names:
            self._process_reference_hubs(self.source.get_data("ref_hub"))

        if "standard_link" in sheet_names:
            self._process_prejoins(self.source.get_data("standard_link"), "standard_link")
        if "non_historized_link" in sheet_names:
            self._process_prejoins(self.source.get_data("non_historized_link"), "non_historized_link")

        if "standard_link" in sheet_names:
            self._process_standard_links(self.source.get_data("standard_link"))
        if "non_historized_link" in sheet_names:
            self._process_non_historized_links(self.source.get_data("non_historized_link"))

        sat_sheets = [
            "standard_satellite",
            "ref_sat",
            "non_historized_satellite",
            "multiactive_satellite",
        ]
        for sheet in sat_sheets:
            if sheet in sheet_names:
                self._process_satellites(self.source.get_data(sheet), sheet)

        self._create_default_snapshot_control(skip_creation=skip_snapshots)

        if "ref_table" in sheet_names:
            self._process_reference_tables(self.source.get_data("ref_table"))

        if "pit" in sheet_names:
            self._process_pits(self.source.get_data("pit"))

        return self.project

    def _process_source_data(self, df: pd.DataFrame):
        for _, row in df.iterrows():
            system_name = self._get_val(row, "source_system") or "Unknown System"
            schema_name = self._get_val(row, "source_schema_physical_name") or "public"

            key = f"{system_name}|{schema_name}"
            if key not in self._source_systems:
                system, _ = SourceSystem.objects.get_or_create(
                    project=self.project,
                    schema_name=schema_name,
                    name=system_name,
                )
                self._source_systems[key] = system

            system = self._source_systems[key]
            table_name = self._get_val(row, "source_table_physical_name")
            table_id = self._get_val(row, "source_table_identifier")

            if table_name and table_id not in self._source_tables:
                table = SourceTable.objects.create(
                    project=self.project,
                    source_system=system,
                    physical_table_name=table_name,
                    record_source_value=row.get("record_source_column") or "",
                    static_part_of_record_source=row.get("static_part_of_record_source_column") or "",
                    load_date_value=row.get("load_date_column") or "sysdate()",
                )
                self._source_tables[table_id] = table
                if table_name not in self._source_tables:
                    self._source_tables[table_name] = table

    def _collect_all_source_columns(self, sheet_names: list[str]):
        columns_to_create: dict[str, set[str]] = {}
        sheets_to_scan = [
            ("standard_hub", "source_table_identifier", ["source_column_physical_name"]),
            ("ref_hub", "source_table_identifier", ["source_column_physical_name"]),
            ("standard_link", "source_table_identifier", ["source_column_physical_name"]),
            ("non_historized_link", "source_table_identifier", ["source_column_physical_name"]),
            ("standard_satellite", "source_table_identifier", ["source_column_physical_name"]),
            ("ref_sat", "source_table_identifier", ["source_column_physical_name"]),
            ("non_historized_satellite", "source_table_identifier", ["source_column_physical_name"]),
            ("multiactive_satellite", "source_table_identifier", ["source_column_physical_name", "multi_active_attributes"]),
            ("standard_link", "prejoin_table_identifier", ["prejoin_table_column_name", "prejoin_extraction_column_name"]),
            ("non_historized_link", "prejoin_table_identifier", ["prejoin_table_column_name", "prejoin_extraction_column_name"]),
        ]

        for sheet_name, table_col, data_cols in sheets_to_scan:
            if sheet_name not in sheet_names:
                continue
            df = self.source.get_data(sheet_name)
            for _, row in df.iterrows():
                table_key = self._get_val(row, table_col)
                if not table_key: continue
                if table_key not in columns_to_create: columns_to_create[table_key] = set()
                for dc in data_cols:
                    val = row.get(dc)
                    if val and not pd.isna(val):
                        if dc == "multi_active_attributes":
                            for sub_val in str(val).split(";"): columns_to_create[table_key].add(sub_val.strip())
                        else: columns_to_create[table_key].add(str(val).strip())

        for table_key, cols in columns_to_create.items():
            table = self._source_tables.get(table_key)
            if not table: continue
            for col_name in cols:
                column, _ = SourceColumn.objects.get_or_create(
                    source_table=table,
                    source_column_physical_name=col_name,
                )
                self._source_columns[f"{table_key}|{col_name}"] = column
                self._source_columns[f"{table.physical_table_name}|{col_name}"] = column

    def _process_standard_hubs(self, df: pd.DataFrame):
        for _, row in df.iterrows():
            hub_name = self._get_val(row, "target_hub_table_physical_name")
            if not hub_name: continue
            if hub_name not in self._hubs:
                hub = Hub.objects.create(
                    project=self.project,
                    hub_physical_name=hub_name,
                    hub_type=Hub.HubType.STANDARD,
                    hub_hashkey_name=self._get_val(row, "target_primary_key_physical_name"),
                    create_record_tracking_satellite=str(row.get("record_tracking_satellite")).upper() == "TRUE",
                )
                self._hubs[hub_name] = hub
                hub_id = self._get_val(row, "hub_identifier")
                if hub_id: self._hubs[hub_id] = hub
            hub = self._hubs[hub_name]
            col_name = self._get_val(row, "business_key_physical_name") or self._get_val(row, "source_column_physical_name")
            if not col_name: continue
            hub_column, _ = HubColumn.objects.get_or_create(
                hub=hub, column_name=col_name,
                defaults={"column_type": HubColumn.ColumnType.BUSINESS_KEY}
            )
            source_table_key = self._get_val(row, "source_table_identifier")
            source_col_name = self._get_val(row, "source_column_physical_name")
            source_col = self._source_columns.get(f"{source_table_key}|{source_col_name}")
            if source_col:
                HubSourceMapping.objects.get_or_create(
                    hub_column=hub_column, source_column=source_col,
                    defaults={"is_primary_source": str(row.get("is_primary_source")).upper() == "TRUE"}
                )

    def _process_reference_hubs(self, df: pd.DataFrame):
        for _, row in df.iterrows():
            hub_name = self._get_val(row, "target_reference_table_physical_name")
            if not hub_name: continue
            if hub_name not in self._hubs:
                hub = Hub.objects.create(
                    project=self.project, hub_physical_name=hub_name, hub_type=Hub.HubType.REFERENCE,
                )
                self._hubs[hub_name] = hub
                hub_id = self._get_val(row, "reference_hub_identifier")
                if hub_id: self._hubs[hub_id] = hub
            hub = self._hubs[hub_name]
            source_col_name = self._get_val(row, "source_column_physical_name")
            if not source_col_name: continue
            hub_column, _ = HubColumn.objects.get_or_create(
                hub=hub, column_name=source_col_name,
                defaults={"column_type": HubColumn.ColumnType.REFERENCE_KEY}
            )
            source_table_key = self._get_val(row, "source_table_identifier")
            source_col = self._source_columns.get(f"{source_table_key}|{source_col_name}")
            if source_col:
                HubSourceMapping.objects.get_or_create(hub_column=hub_column, source_column=source_col, defaults={"is_primary_source": True})

    def _process_standard_links(self, df: pd.DataFrame):
        if "target_link_table_physical_name" in df.columns:
            df["target_link_table_physical_name"] = df["target_link_table_physical_name"].ffill()
        for link_name, link_rows in df.groupby("target_link_table_physical_name"):
            link_name = str(link_name)
            row_sample = link_rows.iloc[0]
            if link_name not in self._links:
                link = Link.objects.create(
                    project=self.project, link_physical_name=link_name,
                    link_hashkey_name=self._get_val(row_sample, "target_primary_key_physical_name") or f"lk_{link_name}",
                    link_type=Link.LinkType.STANDARD,
                )
                self._links[link_name] = link
                link_id = self._get_val(row_sample, "link_identifier")
                if link_id: self._links[link_id] = link
            self._process_link_contents(self._links[link_name], link_rows)

    def _process_non_historized_links(self, df: pd.DataFrame):
        if "target_link_table_physical_name" in df.columns:
            df["target_link_table_physical_name"] = df["target_link_table_physical_name"].ffill()
        for link_name, link_rows in df.groupby("target_link_table_physical_name"):
            link_name = str(link_name)
            row_sample = link_rows.iloc[0]
            if link_name not in self._links:
                link = Link.objects.create(
                    project=self.project, link_physical_name=link_name,
                    link_hashkey_name=self._get_val(row_sample, "target_primary_key_physical_name") or f"lk_{link_name}",
                    link_type=Link.LinkType.NON_HISTORIZED,
                )
                self._links[link_name] = link
                link_id = self._get_val(row_sample, "nh_link_identifier")
                if link_id: self._links[link_id] = link
            self._process_link_contents(self._links[link_name], link_rows)

    def _process_link_contents(self, link: Link, link_rows: pd.DataFrame):
        if "hub_identifier" in link_rows.columns:
            ref_rows = link_rows[link_rows["hub_identifier"].notna()]
            payload_rows = link_rows[link_rows["hub_identifier"].isna()]
            for hub_id, hub_rows in ref_rows.groupby("hub_identifier"):
                hub = self._hubs.get(str(hub_id))
                if not hub: continue
                alias = self._get_val(hub_rows.iloc[0], "target_column_physical_name") or ""
                hk_col = self._get_val(hub_rows.iloc[0], "target_primary_key_physical_name")
                final_alias = alias if alias != hk_col else ""
                lhr = LinkHubReference.objects.create(link=link, hub=hub, hub_hashkey_alias_in_link=final_alias)
                hub_cols = list(hub.columns.filter(column_type__in=[HubColumn.ColumnType.BUSINESS_KEY, HubColumn.ColumnType.REFERENCE_KEY]).order_by("sort_order"))
                for idx, (_, row) in enumerate(hub_rows.sort_values("target_column_sort_order").iterrows()):
                    if idx >= len(hub_cols): continue
                    source_table_id = self._get_val(row, "source_table_identifier")
                    source_col_name = self._get_val(row, "source_column_physical_name")
                    prejoin_alias = self._get_val(row, "prejoin_target_column_alias")
                    ext_col_name = self._get_val(row, "prejoin_extraction_column_name")
                    prejoin_ext = self._extractions.get(f"{link.link_physical_name}|{prejoin_alias or ext_col_name or source_col_name}")
                    source_col = self._source_columns.get(f"{source_table_id}|{source_col_name}") if not prejoin_ext else None
                    if source_col or prejoin_ext:
                        LinkHubSourceMapping.objects.create(link_hub_reference=lhr, standard_hub_column=hub_cols[idx], source_column=source_col, prejoin_extraction_column=prejoin_ext)
        else: payload_rows = link_rows

        for _, row in payload_rows.iterrows():
            col_name = self._get_val(row, "target_column_physical_name") or self._get_val(row, "source_column_physical_name")
            if not col_name: continue
            lc, _ = LinkColumn.objects.get_or_create(link=link, column_name=col_name, defaults={"column_type": LinkColumn.ColumnType.PAYLOAD})
            source_table_id = self._get_val(row, "source_table_identifier")
            source_col_name = self._get_val(row, "source_column_physical_name")
            source_col = self._source_columns.get(f"{source_table_id}|{source_col_name}")
            if source_col: LinkSourceMapping.objects.get_or_create(link_column=lc, source_column=source_col)

    def _process_satellites(self, df: pd.DataFrame, sheet_type: str):
        name_col = "target_reference_table_physical_name" if sheet_type == "ref_sat" else "target_satellite_table_physical_name"
        if name_col in df.columns: df[name_col] = df[name_col].ffill()
        else: return

        sat_type_map = {
            "standard_satellite": Satellite.SatelliteType.STANDARD,
            "ref_sat": Satellite.SatelliteType.REFERENCE,
            "non_historized_satellite": Satellite.SatelliteType.NON_HISTORIZED,
            "multiactive_satellite": Satellite.SatelliteType.MULTI_ACTIVE,
        }

        for sat_name, sat_rows in df.groupby(name_col):
            sat_name = str(sat_name)
            row_sample = sat_rows.iloc[0]
            if sat_name not in self._satellites:
                parent_id = self._get_val(row_sample, "parent_identifier") or self._get_val(row_sample, "parent_table_identifier") or self._get_val(row_sample, "referenced_hub")
                parent_hub = self._hubs.get(parent_id)
                parent_link = self._links.get(parent_id)
                source_table = self._source_tables.get(self._get_val(row_sample, "source_table_identifier"))
                if (parent_hub or parent_link) and source_table:
                    sat = Satellite.objects.create(
                        project=self.project, satellite_physical_name=sat_name,
                        satellite_type=sat_type_map[sheet_type], parent_hub=parent_hub, parent_link=parent_link, source_table=source_table
                    )
                    self._satellites[sat_name] = sat
                    sat_id_col = "ma_satellite_identifier" if sheet_type == "multiactive_satellite" else ("reference_satellite_identifier" if sheet_type == "ref_sat" else "satellite_identifier")
                    sat_id = self._get_val(row_sample, sat_id_col)
                    if sat_id: self._satellites[sat_id] = sat
            
            sat = self._satellites.get(sat_name)
            if not sat: continue
            for _, row in sat_rows.iterrows():
                col_name = self._get_val(row, "target_column_physical_name") or self._get_val(row, "source_column_physical_name")
                if not col_name: continue
                source_table_id = self._get_val(row, "source_table_identifier")
                source_col = self._source_columns.get(f"{source_table_id}|{self._get_val(row, 'source_column_physical_name')}")
                if source_col:
                    SatelliteColumn.objects.get_or_create(
                        satellite=sat, source_column=source_col,
                        defaults={"target_column_name": col_name if col_name != source_col.source_column_physical_name else None}
                    )

    def _process_prejoins(self, df: pd.DataFrame, sheet_name: str):
        df["target_link_table_physical_name"] = df["target_link_table_physical_name"].ffill()
        for _, row in df.iterrows():
            target_table_id = self._get_val(row, "prejoin_table_identifier")
            if not target_table_id: continue
            source_table_id = self._get_val(row, "source_table_identifier")
            source_table = self._source_tables.get(source_table_id)
            target_table = self._source_tables.get(target_table_id)
            if not source_table or not target_table: continue
            prejoin_key = f"{source_table_id}|{target_table_id}"
            prejoin, _ = PrejoinDefinition.objects.get_or_create(project=self.project, source_table=source_table, prejoin_target_table=target_table)
            ext_name = self._get_val(row, "prejoin_extraction_column_name")
            if ext_name:
                source_col = self._source_columns.get(f"{target_table_id}|{ext_name}")
                if source_col:
                    ext, _ = PrejoinExtractionColumn.objects.get_or_create(prejoin=prejoin, source_column=source_col, defaults={"prejoin_target_column_alias": self._get_val(row, "prejoin_target_column_alias")})
                    self._extractions[f"{self._get_val(row, 'target_link_table_physical_name')}|{self._get_val(row, 'prejoin_target_column_alias') or ext_name}"] = ext

    def _process_reference_tables(self, df: pd.DataFrame):
        for _, row in df.iterrows():
            name = self._get_val(row, "target_reference_table_physical_name")
            hub_id = self._get_val(row, "referenced_hub")
            hub = self._hubs.get(hub_id)
            if name and hub:
                ref_table, _ = ReferenceTable.objects.get_or_create(project=self.project, reference_table_physical_name=name, defaults={"reference_hub": hub})
                sat_id = self._get_val(row, "referenced_satellite")
                sat = self._satellites.get(sat_id)
                if sat: ReferenceTableSatelliteAssignment.objects.get_or_create(reference_table=ref_table, reference_satellite=sat)

    def _process_pits(self, df: pd.DataFrame):
        for _, row in df.iterrows():
            name = self._get_val(row, "pit_physical_table_name")
            if name:
                ent_id = self._get_val(row, "tracked_entity")
                hub, link = self._hubs.get(ent_id), self._links.get(ent_id)
                if hub or link:
                    pit = PIT.objects.create(
                        project=self.project,
                        pit_physical_name=name,
                        tracked_entity_type=PIT.TrackedEntityType.HUB if hub else PIT.TrackedEntityType.LINK,
                        tracked_hub=hub,
                        tracked_link=link,
                        snapshot_control_table=self._snapshot_control,
                        snapshot_control_logic=self._snapshot_logic,
                    )
                    sats = str(row.get("satellite_identifiers")).split(",")
                    for sid in sats:
                        sat = self._satellites.get(sid.strip())
                        if sat: pit.satellites.add(sat)

    def _create_default_snapshot_control(self, skip_creation: bool = False):
        if skip_creation: return
        sct, _ = SnapshotControlTable.objects.get_or_create(project=self.project, name="control_snap")
        self._snapshot_control = sct
        scl, _ = SnapshotControlLogic.objects.get_or_create(snapshot_control_table=sct, snapshot_control_logic_column_name="daily", defaults={"snapshot_component": SnapshotControlLogic.SnapshotComponent.DAILY, "snapshot_duration": 30, "snapshot_unit": SnapshotControlLogic.SnapshotUnit.DAY})
        self._snapshot_logic = scl

    def _get_val(self, row, col) -> str | None:
        val = row.get(col)
        if pd.isna(val) or val is None or str(val).lower() in ["nan", "none"]: return None
        return str(val).strip()
