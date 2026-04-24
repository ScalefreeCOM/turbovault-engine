"""
Service for importing a Data Vault model from the proposal JSON schema.

Writes Hub, HubColumn, Link, LinkHubReference, and Satellite records in FK-safe
order. When a hub or satellite definition includes a source_table name that
already exists in the project, staging column mappings are created automatically
(StagingColumn, HubSourceMapping, SatelliteColumn). If the source table or
individual source columns are not found, the structural entity is still created
and the mapping is recorded in ImportResult.skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.services.model_import_schema import ModelImportSchema


@dataclass
class ImportResult:
    hubs_created: int = 0
    links_created: int = 0
    satellites_created: int = 0
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


def import_model(project_name: str, schema: ModelImportSchema) -> ImportResult:
    """
    Import a ModelImportSchema into the database for the given project.

    Must be called after Django setup (models are imported lazily to keep this
    importable before Django initialises in tests).
    """
    from django.db import transaction

    from engine.models import (
        Hub,
        HubColumn,
        HubSourceMapping,
        Link,
        LinkColumn,
        LinkHubReference,
        LinkSourceMapping,
        Project,
        Satellite,
        SatelliteColumn,
        SourceColumn,
        SourceTable,
        StagingColumn,
    )

    result = ImportResult()

    try:
        project = Project.objects.get(name=project_name)
    except Project.DoesNotExist:
        result.errors.append(f"Project '{project_name}' not found")
        return result

    def _resolve_source_table(name: str) -> SourceTable | None:
        return SourceTable.objects.filter(
            project=project, physical_table_name__iexact=name
        ).first()

    def _get_or_create_staging(src_tbl: SourceTable, col_name: str):
        src_col = SourceColumn.objects.filter(
            source_table=src_tbl, source_column_physical_name__iexact=col_name
        ).first()
        if not src_col:
            return None
        staging, _ = StagingColumn.objects.get_or_create(
            project=project, source_table=src_tbl, source_column=src_col
        )
        return staging

    with transaction.atomic():
        # ── 1. Hubs ──────────────────────────────────────────────────────────
        hub_map: dict[str, Hub] = {}

        for hub_def in schema.hubs:
            try:
                hub, created = Hub.objects.get_or_create(
                    project=project,
                    hub_physical_name=hub_def.name,
                    defaults={
                        "hub_type": hub_def.hub_type,
                        "hub_hashkey_name": hub_def.hashkey or "",
                    },
                )
                if hub_def.hashkey and not hub.hub_hashkey_name:
                    hub.hub_hashkey_name = hub_def.hashkey
                    hub.save()

                hub_map[hub_def.name] = hub

                if created:
                    result.hubs_created += 1
                    hub_columns: list[HubColumn] = []
                    for key_name in hub_def.business_keys:
                        col, _ = HubColumn.objects.get_or_create(
                            hub=hub,
                            column_name=key_name,
                            defaults={"column_type": "business_key"},
                        )
                        hub_columns.append(col)

                    # Source column mappings
                    if hub_def.source_table:
                        src_tbl = _resolve_source_table(hub_def.source_table)
                        if src_tbl:
                            for hub_col in hub_columns:
                                staging = _get_or_create_staging(src_tbl, hub_col.column_name)
                                if staging:
                                    HubSourceMapping.objects.get_or_create(
                                        hub_column=hub_col,
                                        staging_column=staging,
                                        defaults={"is_primary_source": True},
                                    )
                                else:
                                    result.skipped.append(
                                        f"Hub '{hub_def.name}': source column "
                                        f"'{hub_col.column_name}' not found in "
                                        f"'{hub_def.source_table}' — mapping skipped"
                                    )
                        else:
                            result.skipped.append(
                                f"Hub '{hub_def.name}': source table "
                                f"'{hub_def.source_table}' not found — mappings skipped"
                            )
                else:
                    result.skipped.append(
                        f"Hub '{hub_def.name}' already exists — skipped"
                    )
            except Exception as exc:
                result.errors.append(f"Hub '{hub_def.name}': {exc}")

        # ── 2. Links ─────────────────────────────────────────────────────────
        link_map: dict[str, Link] = {}

        for link_def in schema.links:
            try:
                link, created = Link.objects.get_or_create(
                    project=project,
                    link_physical_name=link_def.name,
                    defaults={
                        "link_type": link_def.link_type,
                        "link_hashkey_name": link_def.hashkey or "",
                    },
                )
                if link_def.hashkey and not link.link_hashkey_name:
                    link.link_hashkey_name = link_def.hashkey
                    link.save()

                link_map[link_def.name] = link

                if created:
                    result.links_created += 1
                    for hub_name in link_def.hubs:
                        hub = hub_map.get(hub_name) or Hub.objects.filter(
                            project=project, hub_physical_name=hub_name
                        ).first()
                        if hub:
                            LinkHubReference.objects.get_or_create(
                                link=link, hub=hub
                            )
                        else:
                            result.skipped.append(
                                f"Link '{link_def.name}': hub '{hub_name}' not found — reference skipped"
                            )

                    if link_def.payload_columns:
                        src_tbl = None
                        if link_def.source_table:
                            src_tbl = _resolve_source_table(link_def.source_table)
                            if not src_tbl:
                                result.skipped.append(
                                    f"Link '{link_def.name}': source table "
                                    f"'{link_def.source_table}' not found — payload column mappings skipped"
                                )
                        for col_name in link_def.payload_columns:
                            lc, _ = LinkColumn.objects.get_or_create(
                                link=link,
                                column_name=col_name,
                                defaults={"column_type": LinkColumn.ColumnType.PAYLOAD},
                            )
                            if src_tbl:
                                staging = _get_or_create_staging(src_tbl, col_name)
                                if staging:
                                    LinkSourceMapping.objects.get_or_create(
                                        link_column=lc,
                                        staging_column=staging,
                                    )
                                else:
                                    result.skipped.append(
                                        f"Link '{link_def.name}': payload column "
                                        f"'{col_name}' not found in '{link_def.source_table}' — mapping skipped"
                                    )
                else:
                    result.skipped.append(
                        f"Link '{link_def.name}' already exists — skipped"
                    )
            except Exception as exc:
                result.errors.append(f"Link '{link_def.name}': {exc}")

        # ── 3. Satellites ─────────────────────────────────────────────────────
        for sat_def in schema.satellites:
            try:
                parent_hub = None
                parent_link = None

                if sat_def.parent_hub:
                    parent_hub = hub_map.get(sat_def.parent_hub) or Hub.objects.filter(
                        project=project, hub_physical_name=sat_def.parent_hub
                    ).first()
                    if not parent_hub:
                        result.errors.append(
                            f"Satellite '{sat_def.name}': parent hub '{sat_def.parent_hub}' not found"
                        )
                        continue

                if sat_def.parent_link:
                    parent_link = link_map.get(
                        sat_def.parent_link
                    ) or Link.objects.filter(
                        project=project, link_physical_name=sat_def.parent_link
                    ).first()
                    if not parent_link:
                        result.errors.append(
                            f"Satellite '{sat_def.name}': parent link '{sat_def.parent_link}' not found"
                        )
                        continue

                # Resolve source table for satellite FK + column mappings
                src_tbl = None
                if sat_def.source_table:
                    src_tbl = _resolve_source_table(sat_def.source_table)
                    if not src_tbl:
                        result.skipped.append(
                            f"Satellite '{sat_def.name}': source table "
                            f"'{sat_def.source_table}' not found — source FK and column mappings skipped"
                        )

                sat, created = Satellite.objects.get_or_create(
                    project=project,
                    satellite_physical_name=sat_def.name,
                    defaults={
                        "satellite_type": sat_def.satellite_type,
                        "parent_hub": parent_hub,
                        "parent_link": parent_link,
                        "source_table": src_tbl,
                    },
                )
                if created:
                    result.satellites_created += 1
                    if src_tbl and sat_def.columns:
                        for col_name in sat_def.columns:
                            staging = _get_or_create_staging(src_tbl, col_name)
                            if staging:
                                is_ma_key = (
                                    sat_def.multi_active_key is not None
                                    and col_name.lower() == sat_def.multi_active_key.lower()
                                )
                                SatelliteColumn.objects.get_or_create(
                                    satellite=sat,
                                    staging_column=staging,
                                    defaults={
                                        "include_in_delta_detection": True,
                                        "is_multi_active_key": is_ma_key,
                                    },
                                )
                            else:
                                result.skipped.append(
                                    f"Satellite '{sat_def.name}': source column "
                                    f"'{col_name}' not found in '{sat_def.source_table}' — column mapping skipped"
                                )
                else:
                    result.skipped.append(
                        f"Satellite '{sat_def.name}' already exists — skipped"
                    )

            except Exception as exc:
                result.errors.append(f"Satellite '{sat_def.name}': {exc}")

    return result
