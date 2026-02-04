"""
DBML exporter for Data Vault export.

Exports the Data Vault model to DBML (Database Markup Language) format
for ER diagram visualization. Excludes staging tables as per requirements.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from engine.services.export.exporters.base import BaseExporter

if TYPE_CHECKING:
    from engine.services.export.models import (
        HubDefinition,
        LinkDefinition,
        PITDefinition,
        ProjectExport,
        ReferenceTableDefinition,
        SatelliteDefinition,
    )


class DBMLExporter(BaseExporter):
    """
    Exports Data Vault project to DBML format.

    Produces a DBML document containing all Data Vault entities
    (hubs, links, satellites, PITs, reference tables) with their
    columns and relationships for ER diagram visualization.
    """

    def __init__(self) -> None:
        """Initialize DBML exporter."""
        self.output_lines: list[str] = []

    def export(self, project_export: ProjectExport) -> str:
        """
        Export project to DBML string.

        Args:
            project_export: The intermediate project representation

        Returns:
            Formatted DBML string
        """
        self.output_lines = []

        # Build lookup for hubs to ensure references use correct column names and keys
        self.hub_lookup = {
            hub.hub_name: {
                "hashkey": hub.hashkey.hashkey_name if hub.hashkey else None,
                "type": hub.hub_type,
                "reference_keys": hub.reference_key_columns,
                "business_keys": hub.business_key_columns
            }
            for hub in project_export.hubs
        }

        # Add project header
        self._add_header(project_export)

        # Export hubs
        for hub in project_export.hubs:
            self._export_hub(hub)

        # Export links
        for link in project_export.links:
            self._export_link(link)

        # Export satellites
        for satellite in project_export.satellites:
            self._export_satellite(satellite)

        # Export PITs
        for pit in project_export.pits:
            self._export_pit(pit)

        # Export reference tables
        for ref_table in project_export.reference_tables:
            self._export_reference_table(ref_table)

        return "\n".join(self.output_lines)

    def _add_header(self, project_export: ProjectExport) -> None:
        """Add DBML file header with project information."""
        self.output_lines.append(f"// Data Vault ER Diagram: {project_export.project_name}")
        if project_export.project_description:
            self.output_lines.append(f"// {project_export.project_description}")
        self.output_lines.append(f"// Generated at: {project_export.generated_at}")
        self.output_lines.append("")

    def _export_hub(self, hub: HubDefinition) -> None:
        """Export a hub table to DBML."""
        self.output_lines.append(f"Table {hub.hub_name} {{")

        # Hashkey column (primary key)
        if hub.hashkey:
            self.output_lines.append(f"  {hub.hashkey.hashkey_name.upper()} varchar [primary key]")

        # Business key columns
        for bk in hub.business_key_columns:
            self.output_lines.append(f"  {bk.upper()} varchar")

        # Reference key columns (for reference hubs)
        for rk in hub.reference_key_columns:
            self.output_lines.append(f"  {rk.upper()} varchar")

        # Additional columns
        for col in hub.additional_columns:
            self.output_lines.append(f"  {col.upper()} varchar")

        # Standard Data Vault columns
        self.output_lines.append("  LDTS timestamp")
        self.output_lines.append("  RSRC varchar")

        self.output_lines.append("}")
        self.output_lines.append("")

    def _export_link(self, link: LinkDefinition) -> None:
        """Export a link table to DBML."""
        self.output_lines.append(f"Table {link.link_name} {{")

        # Link hashkey (primary key)
        hk_name = link.hashkey.hashkey_name or f"hk_{link.link_name.lower()}_l"
        self.output_lines.append(f"  {hk_name.upper()} varchar [primary key]")

        # Foreign hashkeys (references to hubs)
        for fk in link.foreign_hashkeys:
            # Find the corresponding hub reference to get the hub name
            hub_ref = None
            for ref in link.hub_references:
                # Direct match by alias
                if ref.hub_hashkey_alias_in_link == fk:
                    hub_ref = ref
                    break
                # Match by convention: hk_hub_name
                hub_hk_name = f"hk_{ref.hub_name.lower().removeprefix('hub_')}"
                if fk.lower() == hub_hk_name.lower():
                    hub_ref = ref
                    break
            
            if hub_ref:
                # Use actual hub hashkey name from lookup if available, fallback to guessing
                hub_info = self.hub_lookup.get(hub_ref.hub_name, {})
                target_hk = hub_info.get("hashkey")
                if not target_hk:
                    target_hk = f"hk_{hub_ref.hub_name.lower().removeprefix('hub_')}"
                
                self.output_lines.append(
                    f"  {fk.upper()} varchar [ref: > {hub_ref.hub_name}.{target_hk.upper()}]"
                )
            else:
                # Fallback if we can't find the reference
                self.output_lines.append(f"  {fk.upper()} varchar")

        # Business key columns
        for bk in link.business_key_columns:
            self.output_lines.append(f"  {bk.upper()} varchar")

        # Payload columns
        for payload in link.payload_columns:
            self.output_lines.append(f"  {payload.upper()} varchar")

        # Additional columns
        for col in link.additional_columns:
            self.output_lines.append(f"  {col.upper()} varchar")

        # Standard Data Vault columns
        self.output_lines.append("  LDTS timestamp")
        self.output_lines.append("  RSRC varchar")

        self.output_lines.append("}")
        self.output_lines.append("")

    def _export_satellite(self, satellite: SatelliteDefinition) -> None:
        """Export a satellite table to DBML."""
        self.output_lines.append(f"Table {satellite.satellite_name} {{")

        if satellite.satellite_type == "reference":
            # For reference satellites, link via business/reference keys
            parent_hub = satellite.parent_entity
            hub_info = self.hub_lookup.get(parent_hub)
            
            # If no business keys provided, fallback to standard hashkey logic (should not happen for reference sats)
            if not satellite.parent_business_keys and not hub_info:
                hk_name = satellite.parent_hashkey or "PARENT_HK"
                self.output_lines.append(f"  {hk_name.upper()} varchar")
            else:
                for i, bk in enumerate(satellite.parent_business_keys):
                    ref_str = ""
                    if hub_info and i < len(hub_info["reference_keys"]):
                        target_col = hub_info["reference_keys"][i]
                        ref_str = f" [ref: > {parent_hub}.{target_col.upper()}]"
                    self.output_lines.append(f"  {bk.upper()} varchar{ref_str}")
        else:
            # Parent hashkey (foreign key reference)
            parent_table = satellite.parent_entity
            hk_name = satellite.parent_hashkey or "parent_hk"
            if parent_table:
                # Potentially refinement: check if hk_name is actually the hub's hashkey name
                # though usually satellites carry the correct parent_hashkey metadata.
                self.output_lines.append(
                    f"  {hk_name.upper()} varchar [ref: > {parent_table}.{hk_name.upper()}]"
                )
            else:
                self.output_lines.append(f"  {hk_name.upper()} varchar")

        # Load date timestamp (part of composite key for satellites)
        self.output_lines.append("  LDTS timestamp")

        # Hashdiff column
        self.output_lines.append(f"  {satellite.hashdiff_name.upper()} varchar")

        # Satellite columns
        for col in satellite.columns:
            target_name = col.target_column_name or col.source_column
            # Add note for multi-active key columns
            if col.is_multi_active_key:
                self.output_lines.append(f"  {target_name.upper()} varchar [note: 'Multi-active key']")
            else:
                self.output_lines.append(f"  {target_name.upper()} varchar")

        # Record source
        self.output_lines.append("  RSRC varchar")

        # Add notes
        notes = []
        if satellite.satellite_type != "standard":
            notes.append(f"Satellite type: {satellite.satellite_type}")
        
        if notes:
            combined_note = ". ".join(notes)
            self.output_lines.append(f"  Note: '{combined_note}'")

        self.output_lines.append("}")
        self.output_lines.append("")

    def _export_pit(self, pit: PITDefinition) -> None:
        """Export a PIT (Point-in-Time) table to DBML."""
        self.output_lines.append(f"Table {pit.pit_name} {{")

        # Tracked entity hashkey (foreign key)
        tracked_entity = pit.tracked_entity_name
        self.output_lines.append(
            f"  {pit.tracked_hashkey.upper()} varchar [ref: > {tracked_entity}.{pit.tracked_hashkey.upper()}]"
        )

        # Snapshot date
        self.output_lines.append("  SNAPSHOT_DATE date")

        # Dimension key (if present)
        if pit.dimension_key_column:
            self.output_lines.append(f"  {pit.dimension_key_column.upper()} varchar")

        # For each satellite, add ldts columns
        for sat_name in pit.satellites:
            self.output_lines.append(f"  {sat_name.upper()}_LDTS timestamp")

        self.output_lines.append("}")
        self.output_lines.append("")

    def _export_reference_table(self, ref_table: ReferenceTableDefinition) -> None:
        """Export a reference table to DBML."""
        self.output_lines.append(f"Table {ref_table.table_name} {{")

        # Reference to the hub
        hub_info = self.hub_lookup.get(ref_table.reference_hub_name)
        
        if hub_info and hub_info["type"] == "reference" and hub_info["reference_keys"]:
            # Link via reference keys
            for rk in hub_info["reference_keys"]:
                self.output_lines.append(
                    f"  {rk.upper()} varchar [ref: > {ref_table.reference_hub_name}.{rk.upper()}]"
                )
        else:
            # Fallback to hashkey
            hub_hashkey = hub_info.get("hashkey") if hub_info else None
            if not hub_hashkey:
                hub_hashkey = f"hk_{ref_table.reference_hub_name.removeprefix('hub_')}"

            self.output_lines.append(
                f"  {hub_hashkey.upper()} varchar [ref: > {ref_table.reference_hub_name}.{hub_hashkey.upper()}]"
            )

        # Snapshot date (for snapshot-based historization)
        if ref_table.historization_type == "snapshot_based":
            self.output_lines.append("  SNAPSHOT_DATE date")

        # Load date timestamp
        self.output_lines.append("  LDTS timestamp")

        # Combine notes
        notes = []
        notes.append(f"Historization type: {ref_table.historization_type}")
        
        if ref_table.satellites:
            sat_names = ", ".join(s.satellite_name for s in ref_table.satellites)
            notes.append(f"Includes columns from: {sat_names}")

        combined_note = ". ".join(notes)
        self.output_lines.append(f"  Note: '{combined_note}'")

        self.output_lines.append("}")
        self.output_lines.append("")

    def get_format_name(self) -> str:
        """Return format identifier."""
        return "dbml"

    def get_file_extension(self) -> str:
        """Return file extension."""
        return "dbml"
