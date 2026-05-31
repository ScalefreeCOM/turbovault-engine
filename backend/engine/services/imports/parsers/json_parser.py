"""JSON parser: TurboVault project export → DomainModel.

JSON exports are already structured, so we skip the IR layer and produce
a DomainModel directly. The export schema is owned by
`engine.services.export.models.ProjectExport`.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from engine.services.export.models import ProjectExport
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
    DSatellite,
    DSatelliteColumn,
    DSnapshotControl,
    DSnapshotControlLogic,
    DSourceColumn,
    DSourceSystem,
    DSourceTable,
)
from engine.services.imports.errors import Code, PipelineAbort, make_issue
from engine.services.imports.types import IssueLocation


def parse_json(path: Path) -> DomainModel:
    """Read a TurboVault JSON export and produce a DomainModel."""
    if not path.exists():
        raise PipelineAbort(
            make_issue(
                severity="error",
                code=Code.SOURCE_UNREADABLE,
                stage="parse",
                message=f"File not found: {path}",
                location=IssueLocation(file=str(path)),
            )
        )

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PipelineAbort(
            make_issue(
                severity="error",
                code=Code.SOURCE_UNREADABLE,
                stage="parse",
                message=f"Could not read JSON file: {exc}",
                location=IssueLocation(file=str(path)),
            )
        ) from exc

    try:
        # Validate JSON parses first to distinguish "malformed" from "wrong shape".
        json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise PipelineAbort(
            make_issue(
                severity="error",
                code=Code.SOURCE_INVALID_JSON,
                stage="parse",
                message=f"The file is not valid JSON: {exc.msg} (line {exc.lineno}).",
                location=IssueLocation(file=str(path), row=exc.lineno),
                suggestion="Re-export the project as JSON from a working environment.",
            )
        ) from exc

    try:
        export = ProjectExport.model_validate_json(raw_text)
    except ValidationError as exc:
        # First validation issue is usually the most informative.
        first = exc.errors()[0] if exc.errors() else None
        msg = (
            f"JSON does not match TurboVault export schema: {first.get('msg')}"
            if first
            else "JSON does not match TurboVault export schema."
        )
        raise PipelineAbort(
            make_issue(
                severity="error",
                code=Code.SOURCE_INVALID_JSON,
                stage="parse",
                message=msg,
                location=IssueLocation(file=str(path)),
                suggestion="Re-export the project using a recent Engine version.",
            )
        ) from exc

    return _project_export_to_domain(export)


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def _project_export_to_domain(export: ProjectExport) -> DomainModel:
    model = DomainModel()

    # Groups
    for hub in export.hubs:
        if hub.group:
            model.groups.add(hub.group)
    for link in export.links:
        if link.group:
            model.groups.add(link.group)
    for sat in export.satellites:
        if sat.group:
            model.groups.add(sat.group)
    for rt in export.reference_tables:
        if rt.group:
            model.groups.add(rt.group)
    for pit in export.pits:
        if pit.group:
            model.groups.add(pit.group)

    # Sources
    # In JSON we identify tables by their physical name (since there is no
    # external identifier). We synthesize identifiers as "{system}|{table}".
    for sys_def in export.sources:
        system = DSourceSystem(
            name=sys_def.name,
            schema_name=sys_def.schema_name,
            database_name=sys_def.database_name,
        )
        for table_def in sys_def.tables:
            identifier = f"{sys_def.name}|{table_def.table_name}"
            table = DSourceTable(
                identifier=identifier,
                physical_name=table_def.table_name,
                alias=table_def.alias or "",
                record_source_value=table_def.record_source or "",
                load_date_value=table_def.load_date or "sysdate()",
            )
            for col in table_def.columns:
                table.columns[col.column_name.lower()] = DSourceColumn(
                    name=col.column_name,
                    datatype=col.datatype or "",
                )
            system.tables[identifier] = table
            # Also expose by raw physical name for lookups from hubs/links/sats.
            system.tables.setdefault(table_def.table_name, table)
        model.source_systems[sys_def.name] = system

    # Hubs
    for hub_def in export.hubs:
        hub = DHub(
            physical_name=hub_def.hub_name,
            hub_type="reference" if hub_def.hub_type == "reference" else "standard",
            hashkey_name=hub_def.hashkey.hashkey_name if hub_def.hashkey else None,
            create_record_tracking_satellite=hub_def.create_record_tracking_satellite,
            create_effectivity_satellite=hub_def.create_effectivity_satellite,
            group_name=hub_def.group,
        )
        for i, col_name in enumerate(hub_def.business_key_columns):
            hub.columns.append(
                DHubColumn(name=col_name, column_type="business_key", sort_order=i + 1)
            )
        for i, col_name in enumerate(hub_def.reference_key_columns):
            hub.columns.append(
                DHubColumn(name=col_name, column_type="reference_key", sort_order=i + 1)
            )
        for i, col_name in enumerate(hub_def.additional_columns):
            hub.columns.append(
                DHubColumn(
                    name=col_name, column_type="additional_column", sort_order=i + 1
                )
            )

        # Source mappings — JSON exports include explicit hub_column → source_column maps.
        col_by_name = {c.name: c for c in hub.columns}
        for src_info in hub_def.source_tables:
            table_id = f"{src_info.source_system}|{src_info.source_table}"
            for col_mapping in src_info.column_mappings:
                col = col_by_name.get(col_mapping.hub_column)
                if col is None:
                    continue
                col.source_mappings.append(
                    DHubSourceMapping(
                        source_table_identifier=table_id,
                        source_column_name=col_mapping.source_column,
                        is_primary_source=src_info.is_primary_source,
                    )
                )
        model.hubs[hub_def.hub_name] = hub

    # Links
    for link_def in export.links:
        link = DLink(
            physical_name=link_def.link_name,
            link_type=(
                "non_historized" if link_def.link_type == "non_historized" else "standard"
            ),
            hashkey_name=link_def.hashkey.hashkey_name,
            group_name=link_def.group,
        )
        for i, ref in enumerate(link_def.hub_references):
            link.hub_references.append(
                DLinkHubReference(
                    hub_physical_name=ref.hub_name,
                    hub_hashkey_alias_in_link=ref.hub_hashkey_alias_in_link or "",
                    sort_order=i + 1,
                )
            )
        for i, col_name in enumerate(link_def.payload_columns):
            link.columns.append(
                DLinkColumn(name=col_name, column_type="payload", sort_order=i + 1)
            )
        for i, col_name in enumerate(link_def.additional_columns):
            link.columns.append(
                DLinkColumn(
                    name=col_name, column_type="additional_column", sort_order=i + 1
                )
            )

        col_by_name = {c.name: c for c in link.columns}
        for src_info in link_def.source_tables:
            table_id = f"{src_info.source_system}|{src_info.source_table}"
            for col_mapping in src_info.columns:
                if col_mapping.link_column_type == "business_key":
                    # Match to a hub column by name across hub references.
                    for ref_idx, ref in enumerate(link.hub_references):
                        hub = model.hubs.get(ref.hub_physical_name)
                        if hub is None:
                            continue
                        if any(c.name == col_mapping.link_column_name for c in hub.columns):
                            link.hub_source_mappings.append(
                                DLinkHubSourceMapping(
                                    link_hub_ref_index=ref_idx,
                                    hub_column_name=col_mapping.link_column_name,
                                    source_table_identifier=table_id,
                                    source_column_name=col_mapping.source_column_name,
                                )
                            )
                            break
                else:
                    col = col_by_name.get(col_mapping.link_column_name)
                    if col is not None:
                        col.source_mappings.append(
                            DLinkSourceMapping(
                                source_table_identifier=table_id,
                                source_column_name=col_mapping.source_column_name,
                            )
                        )
        model.links[link_def.link_name] = link

    # Satellites
    for sat_def in export.satellites:
        sat = DSatellite(
            physical_name=sat_def.satellite_name,
            satellite_type=sat_def.satellite_type or "standard",
            parent_entity_name=sat_def.parent_entity,
            parent_entity_type="hub" if sat_def.parent_entity_type == "hub" else "link",
            source_table_identifier=f"{sat_def.source_system}|{sat_def.source_table}",
            group_name=sat_def.group,
        )
        for i, col_def in enumerate(sat_def.columns):
            sat.columns.append(
                DSatelliteColumn(
                    source_column_name=col_def.source_column,
                    target_column_name=col_def.target_column_name,
                    is_multi_active_key=col_def.is_multi_active_key,
                    include_in_delta_detection=col_def.include_in_delta_detection,
                    sort_order=i + 1,
                )
            )
        model.satellites[sat_def.satellite_name] = sat

    # Snapshot controls
    for ctrl in export.snapshot_controls:
        sc = DSnapshotControl(
            name=ctrl.name,
            start_date=ctrl.start_date,
            end_date=ctrl.end_date,
            daily_time=ctrl.daily_time,
        )
        for pattern in ctrl.logic_patterns:
            sc.logic_rules.append(
                DSnapshotControlLogic(
                    column_name=pattern.column_name,
                    component=pattern.component,
                    duration=pattern.duration,
                    unit=pattern.unit,
                    forever=pattern.forever,
                )
            )
        model.snapshot_controls[ctrl.name] = sc

    # Reference tables
    for rt_def in export.reference_tables:
        # JSON only carries one satellite reference per ref-table assignment.
        satellite_name = (
            rt_def.satellites[0].satellite_name if rt_def.satellites else None
        )
        include = list(rt_def.satellites[0].include_columns) if rt_def.satellites else []
        exclude = list(rt_def.satellites[0].exclude_columns) if rt_def.satellites else []
        model.reference_tables[rt_def.table_name] = DReferenceTable(
            physical_name=rt_def.table_name,
            reference_hub_name=rt_def.reference_hub_name,
            historization_type=rt_def.historization_type or "latest",
            snapshot_control_name=rt_def.snapshot_control_table,
            snapshot_logic_column=rt_def.snapshot_logic_column,
            referenced_satellite_name=satellite_name,
            group_name=rt_def.group,
            include_columns=include,
            exclude_columns=exclude,
        )

    # PITs
    for pit_def in export.pits:
        # The export uses v1 control names; the engine stores v0.
        snapshot_v0 = (
            pit_def.snapshot_control_name.removesuffix("_v1").removesuffix("_v0")
            + "_v0"
        )
        model.pits[pit_def.pit_name] = DPIT(
            physical_name=pit_def.pit_name,
            tracked_entity_name=pit_def.tracked_entity_name,
            tracked_entity_type=(
                "hub" if pit_def.tracked_entity_type == "hub" else "link"
            ),
            satellite_names=list(pit_def.satellites),
            snapshot_control_name=snapshot_v0,
            snapshot_logic_column=pit_def.snapshot_logic_column,
            dimension_key_column_name=pit_def.dimension_key_column,
            pit_type=pit_def.pit_type,
            group_name=pit_def.group,
        )

    # Prejoins are embedded in stage definitions in JSON exports.
    for stage in export.stages:
        if not stage.prejoins:
            continue
        source_table_id = f"{stage.source_system}|{stage.source_table}"
        for pj in stage.prejoins:
            target_id = f"{stage.source_system}|{pj.target_table}"
            prejoin = DPrejoin(
                source_table_identifier=source_table_id,
                target_table_identifier=target_id,
                operator=pj.join_conditions.operator.upper() if pj.join_conditions else "AND",
                source_join_columns=list(pj.join_conditions.source_columns or []),
                target_join_columns=list(pj.join_conditions.target_columns or []),
            )
            for ext in pj.extraction_columns:
                prejoin.extraction_columns.append(
                    DPrejoinExtractionColumn(
                        source_column_name=ext.source_column_name,
                        alias=ext.target_column_alias,
                    )
                )
            model.prejoins.append(prejoin)

    return model
