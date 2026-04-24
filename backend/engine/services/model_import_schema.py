"""
Pydantic schemas for the model import-json command.

This is the bridge schema consumed by `turbovault model import-json` and
produced by the MCP server's propose_model_from_source tool.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class HubImport(BaseModel):
    name: str = Field(description="Physical hub name, e.g. HUB_CUSTOMER")
    business_keys: list[str] = Field(
        default_factory=list, description="Business key column names"
    )
    hashkey: str | None = Field(
        default=None, description="Hashkey column name (auto-derived if omitted)"
    )
    hub_type: str = Field(default="standard", description="'standard' or 'reference'")
    source_table: str | None = Field(
        default=None, description="Physical source table name (optional)"
    )
    group: str | None = Field(default=None, description="Group name (optional)")


class LinkImport(BaseModel):
    name: str = Field(description="Physical link name, e.g. LNK_ORDER_CUSTOMER")
    hubs: list[str] = Field(
        default_factory=list,
        description="Physical hub names referenced by this link",
    )
    hashkey: str | None = Field(
        default=None, description="Hashkey column name (auto-derived if omitted)"
    )
    link_type: str = Field(
        default="standard", description="'standard' or 'non_historized'"
    )
    payload_columns: list[str] = Field(
        default_factory=list,
        description="Payload column names for non-historized links (creates LinkColumn records with type='payload')",
    )
    source_table: str | None = Field(
        default=None,
        description="Physical source table name used to resolve payload column mappings (optional)",
    )
    group: str | None = Field(default=None, description="Group name (optional)")


class SatelliteImport(BaseModel):
    name: str = Field(
        description="Physical satellite name, e.g. SAT_CUSTOMER_DETAILS"
    )
    satellite_type: str = Field(
        default="standard",
        description="'standard', 'non_historized', 'multi_active', or 'reference'",
    )
    parent_hub: str | None = Field(
        default=None, description="Physical hub name (XOR with parent_link)"
    )
    parent_link: str | None = Field(
        default=None, description="Physical link name (XOR with parent_hub)"
    )
    columns: list[str] = Field(
        default_factory=list,
        description="Column names (informational — staging mappings require source metadata)",
    )
    multi_active_key: str | None = Field(
        default=None,
        description="Column name to mark as the multi-active key (sets is_multi_active_key=True on the SatelliteColumn). Only applies to satellite_type='multi_active'.",
    )
    source_table: str | None = Field(
        default=None, description="Physical source table name (optional)"
    )
    group: str | None = Field(default=None, description="Group name (optional)")

    @model_validator(mode="after")
    def check_parent_xor(self) -> SatelliteImport:
        if not self.parent_hub and not self.parent_link:
            raise ValueError("Satellite must have either parent_hub or parent_link")
        if self.parent_hub and self.parent_link:
            raise ValueError(
                "Satellite cannot have both parent_hub and parent_link"
            )
        return self


class ModelImportSchema(BaseModel):
    """
    Root schema for turbovault model import-json.

    Hubs and links must be defined before referencing them in satellites/links.
    The importer resolves references by physical name within the project.
    """

    hubs: list[HubImport] = Field(default_factory=list)
    links: list[LinkImport] = Field(default_factory=list)
    satellites: list[SatelliteImport] = Field(default_factory=list)
    reasoning: str | None = Field(
        default=None, description="Free-text rationale from LLM (informational only)"
    )
    reference_candidates: list[str] = Field(
        default_factory=list,
        description="Column names flagged as possible reference data (informational only)",
    )
