"""
Stage 3: cross-sheet resolution.

Turns a row-and-sheet IRDocument into a structured DomainModel ready for the
planner. Emits Issues for problems that aren't visible at the row level
(missing parent, link reference to undefined hub, etc.).

Important: row-level diagnostics include both the file/sheet/row coordinates
and a stable `entity` ref where possible. The Studio renders these as deep
links from its job-status UI.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from engine.services.imports.domain import (
    DPIT,
    DHub,
    DHubColumn,
    DHubSourceMapping,
    DLink,
    DLinkColumn,
    DLinkHubReference,
    DLinkHubSourceMapping,
    DLinkSourceMapping,
    DomainModel,
    DReferenceTable,
    DSatellite,
    DSatelliteColumn,
    DSourceColumn,
    DSourceSystem,
    DSourceTable,
)
from engine.services.imports.errors import Code, make_issue
from engine.services.imports.ir import IRDocument, IRRow
from engine.services.imports.parsers.base import truthy
from engine.services.imports.types import (
    EntityRef,
    Issue,
    IssueLocation,
)


def resolve(doc: IRDocument) -> tuple[DomainModel, list[Issue]]:
    """Resolve an IR document into a DomainModel + diagnostics."""
    resolver = _Resolver(doc)
    resolver.run()
    return resolver.model, resolver.issues


class _Resolver:
    def __init__(self, doc: IRDocument):
        self.doc = doc
        self.model = DomainModel()
        self.issues: list[Issue] = []

        # Index from any identifier (system|schema, raw name, etc.) to canonical lookup.
        self._table_by_id: dict[str, DSourceTable] = {}

    # ------------------------------------------------------------------ helpers
    def _loc(self, sheet: str, row: int | None = None, column: str | None = None) -> IssueLocation:
        return IssueLocation(file=self.doc.source_name, sheet=sheet, row=row, column=column)

    def _error(self, code: str, message: str, **kwargs: Any) -> None:
        self.issues.append(
            make_issue(severity="error", code=code, message=message, stage="resolve", **kwargs)
        )

    def _warning(self, code: str, message: str, **kwargs: Any) -> None:
        self.issues.append(
            make_issue(severity="warning", code=code, message=message, stage="resolve", **kwargs)
        )

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        self._resolve_sources()
        self._resolve_standard_hubs()
        self._resolve_ref_hubs()
        self._resolve_links("standard_link", link_type="standard")
        self._resolve_links("non_historized_link", link_type="non_historized")
        self._resolve_satellites("standard_satellite", "standard")
        self._resolve_satellites("non_historized_satellite", "non_historized")
        self._resolve_satellites("multiactive_satellite", "multi_active")
        self._resolve_satellites("ref_sat", "reference")
        self._resolve_reference_tables()
        self._resolve_pits()

        self._collect_source_columns_from_mappings()

    # ------------------------------------------------------------------ sources
    def _resolve_sources(self) -> None:
        sheet = self.doc.get_sheet("source_data")
        if sheet is None:
            return

        # System identity is (name, schema, database). Tables identified by
        # source_table_identifier (or fall back to physical name).
        for row in sheet.rows:
            sys_name = row.get("source_system") or "Unknown System"
            schema = row.get("source_schema_physical_name") or "public"
            database = row.get("source_database_name")
            table_id = row.get("source_table_identifier")
            phys_name = row.get("source_table_physical_name")

            if not table_id and not phys_name:
                continue

            system_key = f"{sys_name}|{schema}|{database or ''}"
            system = self.model.source_systems.get(system_key)
            if system is None:
                system = DSourceSystem(
                    name=sys_name, schema_name=schema, database_name=database
                )
                self.model.source_systems[system_key] = system
                # Also expose by name alone for resolver lookups elsewhere.
                self.model.source_systems.setdefault(sys_name, system)

            identifier = table_id or phys_name
            if identifier in system.tables:
                self._warning(
                    Code.ENTITY_DUPLICATE_NAME,
                    f"Source table identifier '{identifier}' appears more than once in source_data.",
                    location=self._loc("source_data", row.row_number, "source_table_identifier"),
                    entity=EntityRef(type="source_table", name=identifier),
                )
                continue

            table = DSourceTable(
                identifier=identifier,
                physical_name=phys_name or identifier,
                record_source_value=row.get("record_source_column") or "",
                static_part_of_record_source=row.get("static_part_of_record_source_column") or "",
                load_date_value=row.get("load_date_column") or "sysdate()",
                alias=row.get("alias") or "",
            )
            system.tables[identifier] = table
            self._table_by_id[identifier] = table
            if phys_name and phys_name != identifier:
                self._table_by_id.setdefault(phys_name, table)

    def _find_table(self, identifier: str | None) -> DSourceTable | None:
        if not identifier:
            return None
        return self._table_by_id.get(identifier)

    # ----------------------------------------------------------- source columns
    def _ensure_source_column(
        self,
        table_identifier: str | None,
        column_name: str | None,
    ) -> bool:
        """Create a placeholder SourceColumn if missing. Returns True if found/created."""
        if not table_identifier or not column_name:
            return False
        table = self._find_table(table_identifier)
        if table is None:
            return False
        key = column_name.lower()
        if key not in table.columns:
            table.columns[key] = DSourceColumn(name=column_name)
        return True

    def _collect_source_columns_from_mappings(self) -> None:
        """Scan all mappings post-hoc and ensure referenced columns exist.

        We do this in a second pass so missing columns can be reported per
        mapping with full context. Each mapping records its own diagnostics
        inside its own resolve method; this pass only creates the columns
        that ARE resolvable.
        """
        # Hub mappings
        for hub in self.model.hubs.values():
            for col in hub.columns:
                for m in col.source_mappings:
                    self._ensure_source_column(m.source_table_identifier, m.source_column_name)
        # Link mappings
        for link in self.model.links.values():
            for col in link.columns:
                for m in col.source_mappings:
                    self._ensure_source_column(m.source_table_identifier, m.source_column_name)
            for m in link.hub_source_mappings:
                self._ensure_source_column(m.source_table_identifier, m.source_column_name)
        # Satellites — also ensure the satellite source table is referenced
        for sat in self.model.satellites.values():
            for col in sat.columns:
                self._ensure_source_column(sat.source_table_identifier, col.source_column_name)

    # ------------------------------------------------------------------ hubs
    def _resolve_standard_hubs(self) -> None:
        sheet = self.doc.get_sheet("standard_hub")
        if sheet is None:
            return

        for row in sheet.rows:
            hub_name = row.get("target_hub_table_physical_name")
            if not hub_name:
                continue

            hub = self.model.hubs.get(hub_name)
            if hub is None:
                hub = DHub(
                    physical_name=hub_name,
                    hub_type="standard",
                    hashkey_name=row.get("target_primary_key_physical_name"),
                    create_record_tracking_satellite=truthy(row.get("record_tracking_satellite")),
                    create_effectivity_satellite=False,
                    group_name=row.get("group_name"),
                )
                self.model.hubs[hub_name] = hub
                # Also expose by identifier for satellite parent lookup.
                hub_id = row.get("hub_identifier")
                if hub_id:
                    self.model.hubs.setdefault(hub_id, hub)
            elif row.get("group_name") and not hub.group_name:
                hub.group_name = row.get("group_name")

            if hub.group_name:
                self.model.groups.add(hub.group_name)

            col_name = row.get("business_key_physical_name") or row.get("source_column_physical_name")
            if not col_name:
                continue

            existing_col = next((c for c in hub.columns if c.name == col_name), None)
            if existing_col is None:
                existing_col = DHubColumn(
                    name=col_name,
                    column_type="business_key",
                    sort_order=_int_or_none(row.get("target_column_sort_order")),
                )
                hub.columns.append(existing_col)

            src_table = row.get("source_table_identifier")
            src_col = row.get("source_column_physical_name")
            if src_table and src_col:
                if self._find_table(src_table) is None:
                    self._error(
                        Code.ENTITY_MISSING_SOURCE_TABLE,
                        f"Hub '{hub_name}' references unknown source table '{src_table}'.",
                        location=self._loc(
                            "standard_hub", row.row_number, "source_table_identifier"
                        ),
                        entity=EntityRef(type="hub", name=hub_name),
                        suggestion="Add the source table to the source_data sheet.",
                    )
                else:
                    existing_col.source_mappings.append(
                        DHubSourceMapping(
                            source_table_identifier=src_table,
                            source_column_name=src_col,
                            is_primary_source=truthy(row.get("is_primary_source")),
                        )
                    )

    def _resolve_ref_hubs(self) -> None:
        sheet = self.doc.get_sheet("ref_hub")
        if sheet is None:
            return

        for row in sheet.rows:
            hub_name = row.get("target_reference_table_physical_name")
            if not hub_name:
                continue

            hub = self.model.hubs.get(hub_name)
            if hub is None:
                hub = DHub(
                    physical_name=hub_name,
                    hub_type="reference",
                    hashkey_name=None,
                    group_name=row.get("group_name"),
                )
                self.model.hubs[hub_name] = hub
                hub_id = row.get("reference_hub_identifier")
                if hub_id:
                    self.model.hubs.setdefault(hub_id, hub)

            if hub.group_name:
                self.model.groups.add(hub.group_name)

            src_col = row.get("source_column_physical_name")
            if not src_col:
                continue

            existing_col = next((c for c in hub.columns if c.name == src_col), None)
            if existing_col is None:
                existing_col = DHubColumn(name=src_col, column_type="reference_key")
                hub.columns.append(existing_col)

            src_table = row.get("source_table_identifier")
            if src_table and self._find_table(src_table) is not None:
                existing_col.source_mappings.append(
                    DHubSourceMapping(
                        source_table_identifier=src_table,
                        source_column_name=src_col,
                        is_primary_source=True,
                    )
                )
            elif src_table:
                self._error(
                    Code.ENTITY_MISSING_SOURCE_TABLE,
                    f"Reference hub '{hub_name}' references unknown source table '{src_table}'.",
                    location=self._loc("ref_hub", row.row_number, "source_table_identifier"),
                    entity=EntityRef(type="hub", name=hub_name),
                )

    # ------------------------------------------------------------------ links
    def _resolve_links(self, sheet_name: str, *, link_type: str) -> None:
        sheet = self.doc.get_sheet(sheet_name)
        if sheet is None:
            return

        # Forward-fill the link name so later rows continue the previous link.
        link_rows_by_name: dict[str, list[IRRow]] = defaultdict(list)
        last_name: str | None = None
        for row in sheet.rows:
            name = row.get("target_link_table_physical_name") or last_name
            if not name:
                continue
            last_name = name
            link_rows_by_name[name].append(row)

        for link_name, link_rows in link_rows_by_name.items():
            sample = link_rows[0]
            link = self.model.links.get(link_name)
            if link is None:
                link = DLink(
                    physical_name=link_name,
                    link_type=link_type,
                    hashkey_name=sample.get("target_primary_key_physical_name") or f"hk_{link_name}",
                    create_record_tracking_satellite=truthy(
                        sample.get("record_tracking_satellite")
                    ),
                    group_name=sample.get("group_name"),
                )
                self.model.links[link_name] = link
                id_col = "link_identifier" if link_type == "standard" else "nh_link_identifier"
                link_id = sample.get(id_col)
                if link_id:
                    self.model.links.setdefault(link_id, link)

            if link.group_name:
                self.model.groups.add(link.group_name)

            has_hub_id = sheet.has_column("hub_identifier")
            ref_rows = [r for r in link_rows if has_hub_id and not _empty(r.get("hub_identifier"))]
            payload_rows = [r for r in link_rows if not has_hub_id or _empty(r.get("hub_identifier"))]

            self._resolve_link_hub_refs(link, link_name, ref_rows, sheet_name)
            self._resolve_link_payload(link, link_name, payload_rows, sheet_name)

    def _resolve_link_hub_refs(
        self, link: DLink, link_name: str, ref_rows: list[IRRow], sheet_name: str
    ) -> None:
        # Group by hub identifier, then by alias.
        by_hub: dict[str, list[IRRow]] = defaultdict(list)
        for r in ref_rows:
            by_hub[str(r.get("hub_identifier"))].append(r)

        for hub_id, hub_rows in by_hub.items():
            hub = self.model.hubs.get(hub_id)
            if hub is None:
                # Try matching by physical name as a fallback.
                hub = next(
                    (h for h in self.model.hubs.values() if h.physical_name == hub_id),
                    None,
                )
            if hub is None:
                self._error(
                    Code.ENTITY_MISSING_REFERENCE,
                    f"Link '{link_name}' references hub '{hub_id}' which is not defined.",
                    location=self._loc(sheet_name, hub_rows[0].row_number, "hub_identifier"),
                    entity=EntityRef(type="link", name=link_name),
                    suggestion=f"Add a hub with identifier or physical name '{hub_id}' before the link.",
                )
                continue

            alias_groups: dict[str, list[IRRow]] = defaultdict(list)
            for r in hub_rows:
                alias = r.get("target_column_physical_name") or ""
                alias_groups[alias].append(r)

            for alias, alias_rows in alias_groups.items():
                hk_col_name = alias_rows[0].get("target_primary_key_physical_name") or ""
                final_alias = "" if alias == hk_col_name else alias
                sort_order = _int_or_none(alias_rows[0].get("target_column_sort_order")) or 0

                ref_idx = len(link.hub_references)
                link.hub_references.append(
                    DLinkHubReference(
                        hub_physical_name=hub.physical_name,
                        hub_hashkey_alias_in_link=final_alias,
                        sort_order=sort_order,
                    )
                )

                bk_cols = [c for c in hub.columns if c.column_type == "business_key"]
                if not bk_cols:
                    bk_cols = [c for c in hub.columns if c.column_type == "reference_key"]

                for idx, r in enumerate(alias_rows):
                    if idx >= len(bk_cols):
                        continue
                    src_table = r.get("source_table_identifier")
                    src_col = r.get("source_column_physical_name")
                    if not src_table or not src_col:
                        continue
                    if self._find_table(src_table) is None:
                        self._error(
                            Code.ENTITY_MISSING_SOURCE_TABLE,
                            f"Link '{link_name}' references unknown source table '{src_table}'.",
                            location=self._loc(sheet_name, r.row_number, "source_table_identifier"),
                            entity=EntityRef(type="link", name=link_name),
                        )
                        continue
                    link.hub_source_mappings.append(
                        DLinkHubSourceMapping(
                            link_hub_ref_index=ref_idx,
                            hub_column_name=bk_cols[idx].name,
                            source_table_identifier=src_table,
                            source_column_name=src_col,
                        )
                    )

    def _resolve_link_payload(
        self, link: DLink, link_name: str, payload_rows: list[IRRow], sheet_name: str
    ) -> None:
        for r in payload_rows:
            col_name = (
                r.get("target_column_physical_name")
                or r.get("source_column_physical_name")
            )
            if not col_name:
                continue
            hk_def = r.get("target_primary_key_physical_name")
            col_type = "dependent_child_key" if hk_def else "payload"

            existing = next((c for c in link.columns if c.name == col_name), None)
            if existing is None:
                existing = DLinkColumn(
                    name=col_name,
                    column_type=col_type,
                    sort_order=_int_or_none(r.get("target_column_sort_order")) or 0,
                )
                link.columns.append(existing)

            src_table = r.get("source_table_identifier")
            src_col = r.get("source_column_physical_name")
            if src_table and src_col:
                if self._find_table(src_table) is None:
                    self._error(
                        Code.ENTITY_MISSING_SOURCE_TABLE,
                        f"Link '{link_name}' references unknown source table '{src_table}'.",
                        location=self._loc(sheet_name, r.row_number, "source_table_identifier"),
                        entity=EntityRef(type="link", name=link_name),
                    )
                    continue
                existing.source_mappings.append(
                    DLinkSourceMapping(
                        source_table_identifier=src_table,
                        source_column_name=src_col,
                    )
                )

    # ------------------------------------------------------------------ sats
    def _resolve_satellites(self, sheet_name: str, sat_type: str) -> None:
        sheet = self.doc.get_sheet(sheet_name)
        if sheet is None:
            return

        sat_name_col = (
            "target_reference_table_physical_name"
            if sheet_name == "ref_sat"
            else "target_satellite_table_physical_name"
        )

        grouped: dict[str, list[IRRow]] = defaultdict(list)
        for row in sheet.rows:
            sat_name = row.get(sat_name_col)
            if sat_name:
                grouped[sat_name].append(row)

        for sat_name, sat_rows in grouped.items():
            sample = sat_rows[0]
            # Try every column name the existing metadata templates have used
            # for the satellite's parent. ref_sat uses `parent_table_identifier`,
            # standard/multi-active/non-historized sheets use `parent_identifier`,
            # and a few older templates use `nh_link_identifier`, `referenced_hub`,
            # or `parent_hub`.
            parent_id = (
                sample.get("parent_identifier")
                or sample.get("parent_table_identifier")
                or sample.get("nh_link_identifier")
                or sample.get("referenced_hub")
                or sample.get("parent_hub")
            )
            src_table_id = sample.get("source_table_identifier")

            parent_hub = self.model.hubs.get(parent_id) if parent_id else None
            parent_link = self.model.links.get(parent_id) if parent_id and not parent_hub else None

            if not parent_hub and not parent_link:
                self._error(
                    Code.ENTITY_MISSING_PARENT,
                    f"Satellite '{sat_name}' parent '{parent_id}' was not defined.",
                    location=self._loc(sheet_name, sample.row_number, "parent_identifier"),
                    entity=EntityRef(type="satellite", name=sat_name),
                    suggestion=(
                        f"Add a hub or link with identifier or physical name '{parent_id}' "
                        "before the satellite."
                    ),
                )
                continue

            if src_table_id and self._find_table(src_table_id) is None:
                self._error(
                    Code.ENTITY_MISSING_SOURCE_TABLE,
                    f"Satellite '{sat_name}' source table '{src_table_id}' is not defined.",
                    location=self._loc(sheet_name, sample.row_number, "source_table_identifier"),
                    entity=EntityRef(type="satellite", name=sat_name),
                )
                continue

            sat = self.model.satellites.get(sat_name)
            if sat is None:
                sat = DSatellite(
                    physical_name=sat_name,
                    satellite_type=sat_type,
                    parent_entity_name=(parent_hub or parent_link).physical_name,
                    parent_entity_type="hub" if parent_hub else "link",
                    source_table_identifier=src_table_id or "",
                    group_name=sample.get("group_name"),
                )
                self.model.satellites[sat_name] = sat
                if sat.group_name:
                    self.model.groups.add(sat.group_name)

            # Dedup columns by source_column_name within the satellite. The
            # Excel template requires `multi_active_attributes` to be repeated
            # on every row of a MA satellite, and a regular column can also
            # appear in multiple rows; we keep the first occurrence and
            # silently ignore the rest.
            #
            # Sort order:
            #   - If the row has an explicit `target_column_sort_order`, pass it
            #     through unchanged.
            #   - If not (or for multi-active key attributes, which the Excel
            #     format never sort-orders), leave sort_order=None and let
            #     SatelliteColumn.save() auto-assign on the model layer. This
            #     avoids any chance of the resolver colliding with explicit
            #     sort_orders defined on later rows.
            seen_cols: set[str] = {c.source_column_name for c in sat.columns}

            for row in sat_rows:
                src_col = row.get("source_column_physical_name")
                if src_col and src_col not in seen_cols:
                    target = row.get("target_column_physical_name") or src_col
                    explicit_order = _int_or_none(row.get("target_column_sort_order"))
                    sat.columns.append(
                        DSatelliteColumn(
                            source_column_name=src_col,
                            target_column_name=target if target != src_col else None,
                            is_multi_active_key=False,
                            include_in_delta_detection=(sat_type != "non_historized"),
                            sort_order=explicit_order,
                        )
                    )
                    seen_cols.add(src_col)

                if sat_type == "multi_active":
                    ma_attrs = row.get("multi_active_attributes")
                    if ma_attrs:
                        for raw in str(ma_attrs).split(";"):
                            ma_col = raw.strip()
                            if not ma_col or ma_col in seen_cols:
                                continue
                            sat.columns.append(
                                DSatelliteColumn(
                                    source_column_name=ma_col,
                                    is_multi_active_key=True,
                                    include_in_delta_detection=True,
                                    sort_order=None,
                                )
                            )
                            seen_cols.add(ma_col)

    # -------------------------------------------------------------- ref tables
    def _resolve_reference_tables(self) -> None:
        sheet = self.doc.get_sheet("ref_table")
        if sheet is None:
            return

        for row in sheet.rows:
            name = row.get("target_reference_table_physical_name")
            hub_id = row.get("referenced_hub")
            if not name or not hub_id:
                continue
            hub = self.model.hubs.get(hub_id)
            if hub is None:
                self._error(
                    Code.ENTITY_MISSING_REFERENCE,
                    f"Reference table '{name}' references hub '{hub_id}' which is not defined.",
                    location=self._loc("ref_table", row.row_number, "referenced_hub"),
                    entity=EntityRef(type="reference_table", name=name),
                )
                continue
            hist_raw = (row.get("historized") or "").upper()
            hist = "full" if hist_raw in ("TRUE", "FULL") else "latest"

            include = _split_list(row.get("included_columns"))
            exclude = _split_list(row.get("excluded_columns"))

            self.model.reference_tables[name] = DReferenceTable(
                physical_name=name,
                reference_hub_name=hub.physical_name,
                historization_type=hist,
                referenced_satellite_name=row.get("referenced_satellite"),
                group_name=row.get("group_name"),
                include_columns=include,
                exclude_columns=exclude,
            )
            if row.get("group_name"):
                self.model.groups.add(row.get("group_name"))

    # ------------------------------------------------------------------- pits
    def _resolve_pits(self) -> None:
        sheet = self.doc.get_sheet("pit")
        if sheet is None:
            return

        for row in sheet.rows:
            name = row.get("pit_physical_table_name")
            entity_id = row.get("tracked_entity")
            if not name or not entity_id:
                continue

            hub = self.model.hubs.get(entity_id)
            link = self.model.links.get(entity_id) if not hub else None

            if not hub and not link:
                self._error(
                    Code.ENTITY_MISSING_REFERENCE,
                    f"PIT '{name}' tracks unknown entity '{entity_id}'.",
                    location=self._loc("pit", row.row_number, "tracked_entity"),
                    entity=EntityRef(type="pit", name=name),
                )
                continue

            sats = _split_list(row.get("satellite_identifiers"))
            self.model.pits[name] = DPIT(
                physical_name=name,
                tracked_entity_name=(hub or link).physical_name,
                tracked_entity_type="hub" if hub else "link",
                satellite_names=sats,
                dimension_key_column_name=row.get("dimension_key_name"),
                pit_type=row.get("pit_type"),
                custom_record_source=row.get("custom_record_source"),
                group_name=row.get("group_name"),
            )
            if row.get("group_name"):
                self.model.groups.add(row.get("group_name"))


# ----------------------------------------------------------------- utilities

def _empty(val: Any) -> bool:
    return val is None or (isinstance(val, str) and not val.strip())


def _int_or_none(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _split_list(val: Any) -> list[str]:
    if not val:
        return []
    return [p.strip() for p in str(val).replace(";", ",").split(",") if p.strip()]
