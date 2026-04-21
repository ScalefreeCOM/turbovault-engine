"""
Service for importing a Data Vault model from the proposal JSON schema.

Writes Hub, HubColumn, Link, LinkHubReference, and Satellite records in FK-safe
order. Source-level details (StagingColumn, HubSourceMapping, SatelliteColumn)
are skipped when no matching SourceTable exists in the project — the user can
add those later via `turbovault project init` or Django Admin.
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
        Link,
        LinkHubReference,
        Project,
        Satellite,
    )

    result = ImportResult()

    try:
        project = Project.objects.get(name=project_name)
    except Project.DoesNotExist:
        result.errors.append(f"Project '{project_name}' not found")
        return result

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
                    for key_name in hub_def.business_keys:
                        HubColumn.objects.get_or_create(
                            hub=hub,
                            column_name=key_name,
                            defaults={"column_type": "business_key"},
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

                _, created = Satellite.objects.get_or_create(
                    project=project,
                    satellite_physical_name=sat_def.name,
                    defaults={
                        "satellite_type": sat_def.satellite_type,
                        "parent_hub": parent_hub,
                        "parent_link": parent_link,
                    },
                )
                if created:
                    result.satellites_created += 1
                else:
                    result.skipped.append(
                        f"Satellite '{sat_def.name}' already exists — skipped"
                    )

            except Exception as exc:
                result.errors.append(f"Satellite '{sat_def.name}': {exc}")

    return result
