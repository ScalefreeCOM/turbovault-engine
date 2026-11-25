"""
Stage 3: cross-sheet resolution.

Turns a row-and-sheet IRDocument into a structured DomainModel ready for the
planner. Emits Issues for problems that aren't visible at the row level
(missing parent, link reference to undefined hub, etc.).

Important: row-level diagnostics include both the file/sheet/row coordinates
and a stable `entity` ref where possible. The Studio renders these as deep
links from its job-status UI.

An entity that can't be imported correctly is left out of the model rather
than resolved into a broken version of itself: a link missing one of its hubs
(its grain would change), a satellite without its parent or source table, a
reference table or PIT pointing at something undefined. Anything depending on
a left-out entity is left out too, with an `entity.depends_on_skipped`
warning. Each one is recorded in `DomainModel.skipped` so the planner reports
it as a skip. A mapping to an unknown source table is different: only the
mapping is dropped, the entity it belongs to stays valid.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

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
    DPrejoin,
    DPrejoinExtractionColumn,
    DReferenceTable,
    DRefSatAssignment,
    DSatellite,
    DSatelliteColumn,
    DSkipped,
    DSourceColumn,
    DSourceSystem,
    DSourceTable,
    SkipReason,
    link_hub_problem,
)
from engine.services.imports.errors import Code, make_issue
from engine.services.imports.ir import IRDocument, IRRow
from engine.services.imports.parsers.base import truthy
from engine.services.imports.types import (
    EntityRef,
    Issue,
    IssueLocation,
)
from engine.services.source_values import written_value

_ENTITY_LABELS = {
    "link": "Link",
    "satellite": "Satellite",
    "reference_table": "Reference table",
    "pit": "PIT",
}


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
        # The source system name of each table, by the table's identifier.
        self._system_by_table: dict[str, str] = {}

        # Prejoins the link sheets declare, one per pair of tables and join (two
        # tables can be prejoined more than one way): (source id, target id,
        # source join column, target join column), lowercased -> (prejoin,
        # where its join was first declared).
        self._prejoins: dict[
            tuple[str, str, str, str], tuple[DPrejoin, IssueLocation]
        ] = {}

        # Where each resolved link starts in the file: name -> (sheet, row).
        self._link_origin: dict[str, tuple[str, int]] = {}

        # Effectivity satellites, by name and identifier -> name. They become
        # their parent's flag, so a PIT can't track them.
        self._effectivity_keys: dict[str, str] = {}

        # Map a satellite identifier (e.g. S0001) to its physical name, so PITs
        # can reference satellites by identifier.
        self._sat_id_to_name: dict[str, str] = {}

        # Left-out entities by type, reachable by physical name or identifier:
        # entity_type -> key -> physical name.
        self._skipped_keys: dict[str, dict[str, str]] = defaultdict(dict)

    # ------------------------------------------------------------------ helpers
    def _loc(
        self, sheet: str, row: int | None = None, column: str | None = None
    ) -> IssueLocation:
        return IssueLocation(
            file=self.doc.source_name, sheet=sheet, row=row, column=column
        )

    def _error(self, code: str, message: str, **kwargs: Any) -> None:
        self.issues.append(
            make_issue(
                severity="error", code=code, message=message, stage="resolve", **kwargs
            )
        )

    def _warning(self, code: str, message: str, **kwargs: Any) -> None:
        self.issues.append(
            make_issue(
                severity="warning",
                code=code,
                message=message,
                stage="resolve",
                **kwargs,
            )
        )

    def _skip(
        self, entity_type: str, name: str, reason: SkipReason, *aliases: Any
    ) -> None:
        """Leave an entity out of the model and remember why."""
        self.model.skipped.setdefault(
            (entity_type, name),
            DSkipped(entity_type=entity_type, name=name, reason=reason),
        )
        keys = self._skipped_keys[entity_type]
        keys[name] = name
        for alias in aliases:
            if alias:
                keys.setdefault(str(alias), name)

    def _skipped_name(self, entity_type: str, key: Any) -> str | None:
        """The physical name of a left-out entity, looked up by name or identifier."""
        if not key:
            return None
        return self._skipped_keys[entity_type].get(str(key))

    def _depends_on_skipped(
        self,
        entity_type: str,
        name: str,
        dependency: str,
        *,
        location: IssueLocation,
    ) -> None:
        label = _ENTITY_LABELS.get(entity_type, entity_type)
        self._warning(
            Code.ENTITY_DEPENDS_ON_SKIPPED,
            f"{label} '{name}' is left out because {dependency} can't be imported.",
            location=location,
            entity=EntityRef(type=entity_type, name=name),
            suggestion="Fix the problem reported for it and import again.",
        )

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        self._resolve_sources()
        self._resolve_standard_hubs()
        self._resolve_ref_hubs()
        self._resolve_links("standard_link", link_type="standard")
        self._resolve_links("non_historized_link", link_type="non_historized")
        self._check_link_hubs()
        self._resolve_satellites("standard_satellite", "standard")
        self._resolve_satellites("non_historized_satellite", "non_historized")
        self._resolve_satellites("multiactive_satellite", "multi_active")
        self._resolve_satellites("ref_sat", "reference")
        self._resolve_effectivity_satellites()
        self._resolve_reference_tables()
        self._resolve_pits()

        self.model.prejoins = [prejoin for prejoin, _ in self._prejoins.values()]
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
                    location=self._loc(
                        "source_data", row.row_number, "source_table_identifier"
                    ),
                    entity=EntityRef(type="source_table", name=identifier),
                )
                continue

            table = DSourceTable(
                identifier=identifier,
                physical_name=phys_name or identifier,
                record_source_value=written_value(row.get("record_source_column")),
                static_part_of_record_source=written_value(
                    row.get("static_part_of_record_source_column")
                ),
                load_date_value=written_value(row.get("load_date_column")),
                alias=written_value(row.get("alias")),
            )
            system.tables[identifier] = table
            self._table_by_id[identifier] = table
            self._system_by_table[identifier] = sys_name
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
                    self._ensure_source_column(
                        m.source_table_identifier, m.source_column_name
                    )
        # Link mappings. One fed by a prejoin names a column the prejoin brings
        # into the stage, not a column of its source table: none is created.
        for link in self.model.links.values():
            for link_col in link.columns:
                for col_mapping in link_col.source_mappings:
                    if col_mapping.prejoin_target_table_identifier is None:
                        self._ensure_source_column(
                            col_mapping.source_table_identifier,
                            col_mapping.source_column_name,
                        )
            for key_mapping in link.hub_source_mappings:
                if key_mapping.prejoin_target_table_identifier is None:
                    self._ensure_source_column(
                        key_mapping.source_table_identifier,
                        key_mapping.source_column_name,
                    )
        # Prejoins: the join columns on both tables, and what the target gives.
        for (source_id, target_id, _, _), (prejoin, _) in self._prejoins.items():
            for name in prejoin.source_join_columns:
                self._ensure_source_column(source_id, name)
            for name in prejoin.target_join_columns:
                self._ensure_source_column(target_id, name)
            for extraction in prejoin.extraction_columns:
                self._ensure_source_column(target_id, extraction.source_column_name)
        # Satellites — also ensure the satellite source table is referenced
        for sat in self.model.satellites.values():
            for col in sat.columns:
                self._ensure_source_column(
                    sat.source_table_identifier, col.source_column_name
                )

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
                    create_record_tracking_satellite=truthy(
                        row.get("record_tracking_satellite")
                    ),
                    create_effectivity_satellite=truthy(
                        row.get("effectivity_satellite")
                    ),
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

            col_name = row.get("business_key_physical_name") or row.get(
                "source_column_physical_name"
            )
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
                    location=self._loc(
                        "ref_hub", row.row_number, "source_table_identifier"
                    ),
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

        id_col = "link_identifier" if link_type == "standard" else "nh_link_identifier"
        for link_name, link_rows in link_rows_by_name.items():
            if ("link", link_name) in self.model.skipped:
                continue
            sample = link_rows[0]
            link_id = sample.get(id_col)
            link = self.model.links.get(link_name)
            is_new = link is None
            if link is None:
                link = DLink(
                    physical_name=link_name,
                    link_type=link_type,
                    hashkey_name=sample.get("target_primary_key_physical_name")
                    or f"hk_{link_name}",
                    create_record_tracking_satellite=truthy(
                        sample.get("record_tracking_satellite")
                    ),
                    group_name=sample.get("group_name"),
                )

            has_hub_id = sheet.has_column("hub_identifier")
            ref_rows = [
                r
                for r in link_rows
                if has_hub_id and not _empty(r.get("hub_identifier"))
            ]
            payload_rows = [
                r
                for r in link_rows
                if not has_hub_id or _empty(r.get("hub_identifier"))
            ]

            checkpoint = self._prejoin_checkpoint()
            if not self._resolve_link_hub_refs(link, link_name, ref_rows, sheet_name):
                # Without one of its hubs the link has a different grain: left
                # out, not imported half-connected, and so are the prejoins only
                # it declared.
                self._prejoin_rollback(checkpoint)
                self._forget_link(link_name)
                self._skip("link", link_name, "missing_reference", link_id)
                continue
            self._resolve_link_payload(link, link_name, payload_rows, sheet_name)
            self._link_origin.setdefault(link_name, (sheet_name, sample.row_number))

            if is_new:
                self.model.links[link_name] = link
                if link_id:
                    self.model.links.setdefault(link_id, link)
            if link.group_name:
                self.model.groups.add(link.group_name)

    def _forget_link(self, link_name: str) -> None:
        """Drop a link (and its identifier aliases) already in the model."""
        link = self.model.links.get(link_name)
        if link is None:
            return
        for key in [key for key, value in self.model.links.items() if value is link]:
            del self.model.links[key]

    def _resolve_link_hub_refs(
        self, link: DLink, link_name: str, ref_rows: list[IRRow], sheet_name: str
    ) -> bool:
        """Resolve the link's hub references; False when a hub is undefined."""
        resolved = True
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
                    location=self._loc(
                        sheet_name, hub_rows[0].row_number, "hub_identifier"
                    ),
                    entity=EntityRef(type="link", name=link_name),
                    suggestion=f"Add a hub with identifier or physical name '{hub_id}' before the link.",
                )
                resolved = False
                continue

            alias_groups: dict[str, list[IRRow]] = defaultdict(list)
            for r in hub_rows:
                alias = r.get("target_column_physical_name") or ""
                alias_groups[alias].append(r)

            for alias, alias_rows in alias_groups.items():
                hk_col_name = (
                    alias_rows[0].get("target_primary_key_physical_name") or ""
                )
                final_alias = "" if alias == hk_col_name else alias
                sort_order = (
                    _int_or_none(alias_rows[0].get("target_column_sort_order")) or 0
                )

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
                    bk_cols = [
                        c for c in hub.columns if c.column_type == "reference_key"
                    ]

                # Rows map the hub's keys in order: the first row its first key.
                for idx, r in enumerate(alias_rows[: len(bk_cols)]):
                    src_table = r.get("source_table_identifier")
                    src_col = r.get("source_column_physical_name")
                    if not src_table or not src_col:
                        continue
                    table = self._find_table(src_table)
                    if table is None:
                        self._error(
                            Code.ENTITY_MISSING_SOURCE_TABLE,
                            f"Link '{link_name}' references unknown source table '{src_table}'.",
                            location=self._loc(
                                sheet_name, r.row_number, "source_table_identifier"
                            ),
                            entity=EntityRef(type="link", name=link_name),
                        )
                        continue
                    usable, prejoin_target, column = self._row_prejoin(
                        sheet_name, r, link_name, table
                    )
                    if not usable or column is None:
                        continue
                    link.hub_source_mappings.append(
                        DLinkHubSourceMapping(
                            link_hub_ref_index=ref_idx,
                            hub_column_name=bk_cols[idx].name,
                            source_table_identifier=src_table,
                            source_column_name=column,
                            prejoin_target_table_identifier=prejoin_target,
                        )
                    )
                surplus = alias_rows[len(bk_cols) :]
                if surplus:
                    keys = len(bk_cols)
                    self._warning(
                        Code.ENTITY_INVALID_CONFIGURATION,
                        (
                            f"Link '{link_name}' maps {len(alias_rows)} columns to "
                            f"Hub '{hub.physical_name}', which has {keys} "
                            f"{'key' if keys == 1 else 'keys'}: "
                            f"{_rows_phrase(surplus)} "
                            f"{'is' if len(surplus) == 1 else 'are'} not imported."
                        ),
                        location=self._loc(
                            sheet_name, surplus[0].row_number, "hub_identifier"
                        ),
                        entity=EntityRef(type="link", name=link_name),
                        suggestion=(
                            "Give the connection one row per key of the Hub, in "
                            "the order of its keys."
                        ),
                    )
        return resolved

    def _resolve_link_payload(
        self, link: DLink, link_name: str, payload_rows: list[IRRow], sheet_name: str
    ) -> None:
        for r in payload_rows:
            col_name = r.get("target_column_physical_name") or r.get(
                "source_column_physical_name"
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
                table = self._find_table(src_table)
                if table is None:
                    self._error(
                        Code.ENTITY_MISSING_SOURCE_TABLE,
                        f"Link '{link_name}' references unknown source table '{src_table}'.",
                        location=self._loc(
                            sheet_name, r.row_number, "source_table_identifier"
                        ),
                        entity=EntityRef(type="link", name=link_name),
                    )
                    continue
                usable, prejoin_target, column = self._row_prejoin(
                    sheet_name, r, link_name, table
                )
                if not usable or column is None:
                    continue
                existing.source_mappings.append(
                    DLinkSourceMapping(
                        source_table_identifier=src_table,
                        source_column_name=column,
                        prejoin_target_table_identifier=prejoin_target,
                    )
                )

    def _check_link_hubs(self) -> None:
        """Say which links lack the hubs, or the key, they need.

        A standard link usually relates two or more business objects; one hub
        connected twice (hierarchical, same-as) counts as two. One hub is
        allowed, with a warning; none is reported too. A non-historized link
        may connect any number, none too: one that records transactions on
        their own has no hub. Its hash key is then hashed from its dependent
        child keys alone, so it needs one. Each is imported as the file has it,
        to complete in the project.
        """
        seen: set[int] = set()
        for link in self.model.links.values():
            if id(link) in seen:
                continue
            seen.add(id(link))
            message = link_hub_problem(link)
            if message is None:
                continue
            sheet_name, row_number = self._link_origin.get(
                link.physical_name, (None, None)
            )
            self._warning(
                Code.ENTITY_INVALID_CONFIGURATION,
                message,
                location=(
                    self._loc(sheet_name, row_number, "hub_identifier")
                    if sheet_name
                    else None
                ),
                entity=EntityRef(type="link", name=link.physical_name),
                suggestion=(
                    "Make the column that identifies each row a dependent child key "
                    "(target_primary_key_physical_name on its row)."
                    if link.link_type == "non_historized"
                    else "Name each hub the link connects in hub_identifier, one row "
                    "per key of the hub."
                ),
            )

    # --------------------------------------------------------------- prejoins
    def _qualified(self, table: DSourceTable) -> str:
        """``{system}|{table}``: how a prejoin names its tables, as JSON exports do."""
        return f"{self._system_by_table[table.identifier]}|{table.physical_name}"

    def _prejoin_checkpoint(self) -> dict[tuple[str, str, str, str], int]:
        """The prejoins declared so far, with how many columns each extracts."""
        return {
            key: len(prejoin.extraction_columns)
            for key, (prejoin, _) in self._prejoins.items()
        }

    def _prejoin_rollback(
        self, checkpoint: dict[tuple[str, str, str, str], int]
    ) -> None:
        """Forget what was declared since ``checkpoint``."""
        for key in [key for key in self._prejoins if key not in checkpoint]:
            del self._prejoins[key]
        for key, extracted in checkpoint.items():
            del self._prejoins[key][0].extraction_columns[extracted:]

    def _row_prejoin(
        self, sheet_name: str, row: IRRow, link_name: str, table: DSourceTable
    ) -> tuple[bool, str | None, str | None]:
        """Where a link row's column comes from: ``(usable, prejoin target, column)``.

        Without ``prejoin_table_identifier``, from the row's source column.
        With it, as datavault4dbt's ``prejoined_columns``: the row's source
        column joins ``prejoin_table_column_name`` of the prejoined table, which
        gives ``prejoin_extraction_column_name``, named in the stage
        ``prejoin_target_column_alias`` when there is one. The mapping then
        names that staged column, and the target table's identifier says it
        comes from the prejoin.

        Rows that join the same tables on the same columns are one prejoin;
        on other columns, another one. Not usable when the prejoin is
        incomplete or names an unknown table. A column the same prejoin
        already takes under another name keeps that name: it has one in the
        stage.
        """
        source_column = row.get("source_column_physical_name")
        target_ref = row.get("prejoin_table_identifier")
        if not target_ref:
            return True, None, source_column
        entity = EntityRef(type="link", name=link_name)
        join_column = row.get("prejoin_table_column_name")
        taken = row.get("prejoin_extraction_column_name")
        missing = [
            column
            for column, value in (
                ("prejoin_table_column_name", join_column),
                ("prejoin_extraction_column_name", taken),
            )
            if not value
        ]
        if missing or not source_column or not join_column or not taken:
            self._error(
                Code.ENTITY_INVALID_CONFIGURATION,
                (
                    f"Link '{link_name}' prejoins '{target_ref}' without "
                    f"{' or '.join(missing) or 'source_column_physical_name'}, "
                    "so the column it maps can't be brought in."
                ),
                location=self._loc(
                    sheet_name,
                    row.row_number,
                    missing[0] if missing else "source_column_physical_name",
                ),
                entity=entity,
                suggestion=(
                    "Fill in the join column of each table and the column to take "
                    "from the prejoined one, or clear prejoin_table_identifier."
                ),
            )
            return False, None, None
        target = self._find_table(target_ref)
        if target is None:
            self._error(
                Code.ENTITY_MISSING_SOURCE_TABLE,
                f"Link '{link_name}' prejoins unknown source table '{target_ref}'.",
                location=self._loc(
                    sheet_name, row.row_number, "prejoin_table_identifier"
                ),
                entity=entity,
                suggestion="Add the source table to the source_data sheet.",
            )
            return False, None, None

        location = self._loc(sheet_name, row.row_number, "prejoin_table_column_name")
        key = (
            table.identifier,
            target.identifier,
            source_column.lower(),
            join_column.lower(),
        )
        known = self._prejoins.get(key)
        # Another prejoin of this table may not give a stage column the same
        # name: a link's mapping names the column, not the join it comes by.
        staged = (row.get("prejoin_target_column_alias") or taken).lower()
        clash = next(
            (
                (other_key, other)
                for other_key, (other, _) in self._prejoins.items()
                if other_key[0] == table.identifier
                and other_key != key
                and any(
                    (e.alias or e.source_column_name).lower() == staged
                    for e in other.extraction_columns
                )
            ),
            None,
        )
        if clash is not None:
            other_key, other = clash
            self._error(
                Code.ENTITY_INVALID_CONFIGURATION,
                (
                    f"Link '{link_name}' takes {target.physical_name}.{taken} as "
                    f"'{row.get('prejoin_target_column_alias') or taken}', a name "
                    f"another prejoin of '{table.physical_name}' already gives "
                    f"(joined on {table.physical_name}.{other.source_join_columns[0]}"
                    f" = {_bare_table(other.target_table_identifier)}."
                    f"{other.target_join_columns[0]}): the stage can select only "
                    "one column by that name."
                ),
                location=self._loc(
                    sheet_name, row.row_number, "prejoin_target_column_alias"
                ),
                entity=entity,
                suggestion="Give the column an alias of its own.",
            )
            return False, None, None
        if known is None:
            prejoin = DPrejoin(
                source_table_identifier=self._qualified(table),
                target_table_identifier=self._qualified(target),
                source_join_columns=[source_column],
                target_join_columns=[join_column],
            )
            self._prejoins[key] = (prejoin, location)
        else:
            prejoin = known[0]

        alias = row.get("prejoin_target_column_alias") or None
        extraction = next(
            (
                e
                for e in prejoin.extraction_columns
                if e.source_column_name.lower() == taken.lower()
            ),
            None,
        )
        if extraction is None:
            prejoin.extraction_columns.append(
                DPrejoinExtractionColumn(source_column_name=taken, alias=alias)
            )
        elif (extraction.alias or "").lower() != (alias or "").lower():
            # The same join takes the same column: the same values, under the
            # name the stage already gives them. Mapped to that column, named
            # as the earlier row has it (the Engine stages a column once).
            staged = extraction.alias or extraction.source_column_name
            self._warning(
                Code.ENTITY_INVALID_CONFIGURATION,
                (
                    f"Link '{link_name}' takes {target.physical_name}.{taken} as "
                    f"'{alias or taken}', but an earlier row takes it as "
                    f"'{staged}'; the link uses '{staged}', the same column."
                ),
                location=self._loc(
                    sheet_name, row.row_number, "prejoin_target_column_alias"
                ),
                entity=entity,
                suggestion="Give the column the same alias in every row.",
            )
            return True, target.identifier, staged
        return True, target.identifier, alias or taken

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
            # Register the satellite's identifier (if any) so PITs can reference
            # it by identifier rather than physical name.
            sat_identifier = (
                sample.get("satellite_identifier")
                or sample.get("ma_satellite_identifier")
                or sample.get("nh_satellite_identifier")
                or sample.get("reference_satellite_identifier")
            )
            if sat_identifier:
                self._sat_id_to_name[str(sat_identifier)] = sat_name
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
            parent_link = (
                self.model.links.get(parent_id)
                if parent_id and not parent_hub
                else None
            )

            if not parent_hub and not parent_link:
                location = self._loc(sheet_name, sample.row_number, "parent_identifier")
                skipped_parent = self._skipped_name("link", parent_id)
                if skipped_parent is not None:
                    self._depends_on_skipped(
                        "satellite",
                        sat_name,
                        f"its parent link '{skipped_parent}'",
                        location=location,
                    )
                    self._skip(
                        "satellite", sat_name, "depends_on_skipped", sat_identifier
                    )
                    continue
                self._error(
                    Code.ENTITY_MISSING_PARENT,
                    f"Satellite '{sat_name}' parent '{parent_id}' was not defined.",
                    location=location,
                    entity=EntityRef(type="satellite", name=sat_name),
                    suggestion=(
                        f"Add a hub or link with identifier or physical name '{parent_id}' "
                        "before the satellite."
                    ),
                )
                self._skip("satellite", sat_name, "missing_parent", sat_identifier)
                continue

            if src_table_id and self._find_table(src_table_id) is None:
                self._error(
                    Code.ENTITY_MISSING_SOURCE_TABLE,
                    f"Satellite '{sat_name}' source table '{src_table_id}' is not defined.",
                    location=self._loc(
                        sheet_name, sample.row_number, "source_table_identifier"
                    ),
                    entity=EntityRef(type="satellite", name=sat_name),
                )
                self._skip(
                    "satellite", sat_name, "missing_source_table", sat_identifier
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

    # ---------------------------------------------------- effectivity satellites
    def _resolve_effectivity_satellites(self) -> None:
        """Each effectivity satellite sets its parent's effectivity flag.

        The Engine generates a hub's or link's effectivity satellite from that
        flag, named by the project's naming pattern, so the sheet's own name
        and columns don't carry over: said once per parent. A file with the
        sheet describes its links' effectivity in full: a link it doesn't list
        gets none (a hub's flag comes from the standard_hub sheet as before).
        """
        sheet = self.doc.get_sheet("effectivity_satellite")
        if sheet is None:
            return

        grouped: dict[str, list[IRRow]] = defaultdict(list)
        for row in sheet.rows:
            name = row.get("target_satellite_table_physical_name")
            if name:
                grouped[name].append(row)

        # Parent (by identity) -> (parent, its effectivity satellites, first row)
        by_parent: dict[int, tuple[DHub | DLink, list[str], IRRow]] = {}
        for sat_name, rows in grouped.items():
            first = rows[0]
            sat_id = first.get("effectivity_satellite_identifier")
            for key in (sat_name, sat_id):
                if key:
                    self._effectivity_keys[str(key)] = sat_name
            entity = EntityRef(type="satellite", name=sat_name)
            parent_id = first.get("parent_identifier")
            differing = next(
                (row for row in rows if row.get("parent_identifier") != parent_id),
                None,
            )
            if differing is not None:
                self._error(
                    Code.ENTITY_INVALID_CONFIGURATION,
                    (
                        f"Effectivity satellite '{sat_name}' names parent "
                        f"'{parent_id}' in row {first.row_number} but "
                        f"'{differing.get('parent_identifier')}' in row "
                        f"{differing.row_number}; it belongs to one hub or link."
                    ),
                    location=self._loc(
                        "effectivity_satellite",
                        differing.row_number,
                        "parent_identifier",
                    ),
                    entity=entity,
                    suggestion="Name the same parent in every row of the satellite.",
                )
                self._skip("satellite", sat_name, "invalid_configuration", sat_id)
                continue

            parent: DHub | DLink | None = self.model.hubs.get(
                parent_id
            ) or self.model.links.get(parent_id)
            if parent is None:
                location = self._loc(
                    "effectivity_satellite", first.row_number, "parent_identifier"
                )
                skipped_parent = self._skipped_name("link", parent_id)
                if skipped_parent is not None:
                    self._depends_on_skipped(
                        "satellite",
                        sat_name,
                        f"its parent link '{skipped_parent}'",
                        location=location,
                    )
                    self._skip("satellite", sat_name, "depends_on_skipped", sat_id)
                    continue
                self._error(
                    Code.ENTITY_MISSING_PARENT,
                    (
                        f"Effectivity satellite '{sat_name}' parent '{parent_id}' "
                        "was not defined."
                    ),
                    location=location,
                    entity=entity,
                    suggestion=(
                        f"Add a hub or link with identifier or physical name "
                        f"'{parent_id}', or name an existing one."
                    ),
                )
                self._skip("satellite", sat_name, "missing_parent", sat_id)
                continue
            by_parent.setdefault(id(parent), (parent, [], first))[1].append(sat_name)

        for link in self.model.links.values():
            link.create_effectivity_satellite = False
        for parent, names, first in by_parent.values():
            parent.create_effectivity_satellite = True
            kind: Literal["hub", "link"] = "hub" if isinstance(parent, DHub) else "link"
            listed = " and ".join(
                [", ".join(f"'{n}'" for n in names[:-1]), f"'{names[-1]}'"]
                if len(names) > 1
                else [f"'{names[0]}'"]
            )
            self._warning(
                Code.ENTITY_IMPORTED_DIFFERENTLY,
                (
                    f"Effectivity satellite{'s' if len(names) > 1 else ''} {listed} "
                    f"{'are' if len(names) > 1 else 'is'} imported as {kind} "
                    f"'{parent.physical_name}''s effectivity satellite. The Engine "
                    "names it by the project's naming pattern; the sheet's name "
                    "and columns are not imported."
                ),
                location=self._loc(
                    "effectivity_satellite",
                    first.row_number,
                    "target_satellite_table_physical_name",
                ),
                entity=EntityRef(type=kind, name=parent.physical_name),
                suggestion=(
                    "Set the effectivity satellite's options on the "
                    f"{kind} in the project."
                ),
            )

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
            if ("reference_table", name) in self.model.skipped:
                continue
            hub = self.model.hubs.get(hub_id)
            if hub is None:
                self._error(
                    Code.ENTITY_MISSING_REFERENCE,
                    f"Reference table '{name}' references hub '{hub_id}' which is not defined.",
                    location=self._loc("ref_table", row.row_number, "referenced_hub"),
                    entity=EntityRef(type="reference_table", name=name),
                )
                self.model.reference_tables.pop(name, None)
                self._skip("reference_table", name, "missing_reference")
                continue
            # A table spans one row per satellite: one left-out satellite
            # leaves the whole table out.
            skipped_sat = self._skipped_name(
                "satellite", row.get("referenced_satellite")
            )
            if skipped_sat is not None:
                self._depends_on_skipped(
                    "reference_table",
                    name,
                    f"its satellite '{skipped_sat}'",
                    location=self._loc(
                        "ref_table", row.row_number, "referenced_satellite"
                    ),
                )
                self.model.reference_tables.pop(name, None)
                self._skip("reference_table", name, "depends_on_skipped")
                continue
            hist_raw = (row.get("historized") or "").upper()
            hist = "full" if hist_raw in ("TRUE", "FULL") else "latest"

            # A ref table can span multiple rows, one per referenced satellite.
            rt = self.model.reference_tables.get(name)
            if rt is None:
                rt = DReferenceTable(
                    physical_name=name,
                    reference_hub_name=hub.physical_name,
                    historization_type=hist,
                    group_name=row.get("group_name"),
                )
                self.model.reference_tables[name] = rt
            if row.get("group_name"):
                self.model.groups.add(row.get("group_name"))

            sat_ref = row.get("referenced_satellite")
            if sat_ref:
                rt.satellite_assignments.append(
                    DRefSatAssignment(
                        satellite_name=self._sat_id_to_name.get(sat_ref, sat_ref),
                        include_columns=_split_list(row.get("included_columns")),
                        exclude_columns=_split_list(row.get("excluded_columns")),
                    )
                )

    # ------------------------------------------------------------------- pits
    def _resolve_pits(self) -> None:
        sheet = self.doc.get_sheet("pit")
        if sheet is None:
            return

        # A PIT can span several rows of the sheet: read them as one.
        rows_by_pit: dict[str, list[IRRow]] = defaultdict(list)
        for row in sheet.rows:
            name = row.get("pit_physical_table_name")
            if name and row.get("tracked_entity"):
                rows_by_pit[name].append(row)

        for name, rows in rows_by_pit.items():
            self._resolve_pit(name, rows)

    def _resolve_pit(self, name: str, rows: list[IRRow]) -> None:
        """One PIT from its rows: one entity tracked, the satellites of all rows."""
        entity = EntityRef(type="pit", name=name)
        entity_id = rows[0].get("tracked_entity")
        differing = next(
            (row for row in rows if row.get("tracked_entity") != entity_id), None
        )
        if differing is not None:
            self._error(
                Code.ENTITY_INVALID_CONFIGURATION,
                (
                    f"PIT '{name}' tracks '{entity_id}' in row "
                    f"{rows[0].row_number} but '{differing.get('tracked_entity')}' "
                    f"in row {differing.row_number}; a PIT tracks one hub or link."
                ),
                location=self._loc("pit", differing.row_number, "tracked_entity"),
                entity=entity,
                suggestion=(
                    "Track the same hub or link in every row of the PIT, or give "
                    "each PIT a name of its own."
                ),
            )
            self._skip("pit", name, "invalid_configuration")
            return

        hub = self.model.hubs.get(entity_id)
        tracked: DHub | DLink | None = hub or self.model.links.get(entity_id)
        if tracked is None:
            location = self._loc("pit", rows[0].row_number, "tracked_entity")
            skipped_link = self._skipped_name("link", entity_id)
            if skipped_link is not None:
                self._depends_on_skipped(
                    "pit",
                    name,
                    f"the link '{skipped_link}' it tracks",
                    location=location,
                )
                self._skip("pit", name, "depends_on_skipped")
                return
            spread = f" (in {len(rows)} rows)" if len(rows) > 1 else ""
            self._error(
                Code.ENTITY_MISSING_REFERENCE,
                f"PIT '{name}' tracks unknown entity '{entity_id}'{spread}.",
                location=location,
                entity=entity,
                suggestion=(
                    "Name the hub or link by its identifier or physical name, as "
                    "the standard_hub or standard_link sheet defines it."
                ),
            )
            self._skip("pit", name, "missing_reference")
            return

        # The satellites of every row, each once, in the order they first appear.
        sat_keys: list[str] = []
        for row in rows:
            for key in _split_list(row.get("satellite_identifiers")):
                if key not in sat_keys:
                    sat_keys.append(key)
        effectivity = [
            key
            for key in sat_keys
            if key in self._effectivity_keys and key not in self._sat_id_to_name
        ]
        if effectivity:
            sat_keys = [key for key in sat_keys if key not in effectivity]
            names = sorted({self._effectivity_keys[key] for key in effectivity})
            self._warning(
                Code.ENTITY_IMPORTED_DIFFERENTLY,
                (
                    f"PIT '{name}' lists effectivity satellite"
                    f"{'s' if len(names) > 1 else ''} "
                    f"{', '.join(repr(n) for n in names)}, which "
                    f"{'are' if len(names) > 1 else 'is'} imported as "
                    "their parent's effectivity satellite: the PIT tracks "
                    f"{'them' if len(names) > 1 else 'it'} no more."
                ),
                location=self._loc("pit", rows[0].row_number, "satellite_identifiers"),
                entity=entity,
                suggestion="Track the PIT's other satellites, or none of these.",
            )
        skipped_sat = next(
            (
                skipped
                for key in sat_keys
                if (skipped := self._skipped_name("satellite", key)) is not None
            ),
            None,
        )
        if skipped_sat is not None:
            self._depends_on_skipped(
                "pit",
                name,
                f"its satellite '{skipped_sat}'",
                location=self._loc("pit", rows[0].row_number, "satellite_identifiers"),
            )
            self._skip("pit", name, "depends_on_skipped")
            return

        settings = {
            column: self._pit_setting(name, rows, column)
            for column in (
                "snapshot_model_name",
                "snapshot_trigger_column",
                "dimension_key_name",
                "pit_type",
                "custom_record_source",
                "group_name",
            )
        }
        self.model.pits[name] = DPIT(
            physical_name=name,
            tracked_entity_name=tracked.physical_name,
            tracked_entity_type="hub" if hub else "link",
            satellite_names=[self._sat_id_to_name.get(s, s) for s in sat_keys],
            snapshot_control_name=settings["snapshot_model_name"],
            snapshot_logic_column=settings["snapshot_trigger_column"],
            dimension_key_column_name=settings["dimension_key_name"],
            pit_type=settings["pit_type"],
            custom_record_source=settings["custom_record_source"],
            group_name=settings["group_name"],
        )
        if settings["group_name"]:
            self.model.groups.add(settings["group_name"])

    def _pit_setting(self, name: str, rows: list[IRRow], column: str) -> str | None:
        """A PIT setting from its rows: the first value given, said when rows differ."""
        values = [(row, str(row.get(column))) for row in rows if row.get(column)]
        if not values:
            return None
        first = values[0][1]
        other = next(((row, v) for row, v in values if v != first), None)
        if other is not None:
            self._warning(
                Code.ENTITY_INVALID_CONFIGURATION,
                (
                    f"PIT '{name}' has {column} '{first}' in row "
                    f"{values[0][0].row_number} but '{other[1]}' in row "
                    f"{other[0].row_number}; '{first}' is used."
                ),
                location=self._loc("pit", other[0].row_number, column),
                entity=EntityRef(type="pit", name=name),
                suggestion=f"Give {column} the same value in every row of the PIT.",
            )
        return first


# ----------------------------------------------------------------- utilities


def _bare_table(identifier: str) -> str:
    """ "crm|orders" -> "orders": the table of a prejoin's qualified identifier."""
    return identifier.split("|", 1)[1] if "|" in identifier else identifier


def _rows_phrase(rows: list[IRRow]) -> str:
    """Row numbers, runs as ranges: "row 7", "rows 4-13", "rows 4-6, 9 and 11"."""
    numbers = sorted({row.row_number for row in rows})
    spans: list[str] = []
    start = previous = numbers[0]
    for number in [*numbers[1:], None]:
        if number is not None and number == previous + 1:
            previous = number
            continue
        spans.append(str(start) if start == previous else f"{start}\u2013{previous}")
        if number is not None:
            start = previous = number
    if len(spans) == 1:
        return f"{'row' if len(numbers) == 1 else 'rows'} {spans[0]}"
    return f"rows {', '.join(spans[:-1])} and {spans[-1]}"


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
