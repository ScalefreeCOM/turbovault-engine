"""
Django Admin configuration for TurboVault Engine.

Register domain models here for data inspection and debugging via the admin UI.
"""

from django.contrib import admin

from engine.models import (
    PIT,
    Group,
    PrejoinDefinition,
    PrejoinExtractionColumn,
    Project,
    ReferenceTable,
    ReferenceTableSatelliteAssignment,
    ReferenceTable,
    ReferenceTableSatelliteAssignment,
    SourceColumn,
    SourceSystem,
    SourceTable,
    StagingColumn,
)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    """Admin configuration for Project model."""

    list_display = ["name", "created_at", "updated_at"]
    search_fields = ["name", "description"]
    readonly_fields = ["project_id", "created_at", "updated_at"]
    fieldsets = [
        (None, {"fields": ["project_id", "name", "description"]}),
        ("Configuration", {"fields": ["config"], "classes": ["collapse"]}),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    """Admin configuration for Group model."""

    list_display = ["group_name", "project", "created_at"]
    list_filter = ["project"]
    search_fields = ["group_name", "description"]
    readonly_fields = ["group_id", "created_at", "updated_at"]
    autocomplete_fields = ["project"]
    fieldsets = [
        (None, {"fields": ["group_id", "project", "group_name", "description"]}),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]


@admin.register(SourceSystem)
class SourceSystemAdmin(admin.ModelAdmin):
    """Admin configuration for SourceSystem model."""

    list_display = ["name", "schema_name", "database_name", "project"]
    list_filter = ["project"]
    search_fields = ["name", "schema_name", "database_name"]
    readonly_fields = ["source_system_id"]
    autocomplete_fields = ["project"]


@admin.register(SourceTable)
class SourceTableAdmin(admin.ModelAdmin):
    """Admin configuration for SourceTable model."""

    list_display = ["physical_table_name", "alias", "source_system", "project"]
    list_filter = ["source_system", "project"]
    search_fields = ["physical_table_name", "alias"]
    readonly_fields = ["source_table_id"]
    autocomplete_fields = ["project", "source_system"]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "source_table_id",
                    "project",
                    "source_system",
                    "physical_table_name",
                    "alias",
                ]
            },
        ),
        (
            "Data Vault Configuration",
            {
                "fields": [
                    "record_source_value",
                    "static_part_of_record_source",
                    "load_date_value",
                ],
                "classes": ["collapse"],
            },
        ),
    ]


@admin.register(SourceColumn)
class SourceColumnAdmin(admin.ModelAdmin):
    """Admin configuration for SourceColumn model."""

    list_display = [
        "source_column_physical_name",
        "source_column_datatype",
        "source_table",
        "get_source_system",
    ]
    list_filter = ["source_table__source_system", "source_table"]
    search_fields = ["source_column_physical_name", "source_column_datatype"]
    readonly_fields = ["source_column_id"]
    autocomplete_fields = ["source_table"]

    @admin.display(description="Source System")
    def get_source_system(self, obj: SourceColumn) -> str:
        """Return the source system name for this column."""
        return obj.source_table.source_system.name


@admin.register(StagingColumn)
class StagingColumnAdmin(admin.ModelAdmin):
    """Admin configuration for StagingColumn model."""

    list_display = ["physical_name", "datatype", "source_table", "project"]
    list_filter = ["source_table", "project"]
    search_fields = [
        "source_column__source_column_physical_name",
        "prejoin_column__prejoin_target_column_alias",
    ]
    autocomplete_fields = ["project", "source_table", "source_column", "prejoin_column"]

    def has_add_permission(self, request) -> bool:
        """Prevent manual creation of staging columns."""
        return False

    def has_change_permission(self, request, obj: StagingColumn | None = None) -> bool:
        """Prevent manual modification of staging columns."""
        return False

    def has_delete_permission(self, request, obj: StagingColumn | None = None) -> bool:
        """Prevent manual deletion of staging columns."""
        return False


# Import hub models
from engine.models import Hub, HubColumn, HubSourceMapping


class HubColumnInline(admin.TabularInline):
    """Inline admin for hub columns."""

    model = HubColumn
    extra = 1
    fields = ["column_name", "column_type", "sort_order"]
    ordering = ["sort_order"]
    show_change_link = True  # Allow clicking to edit column details including mappings


class HubSourceMappingInline(admin.TabularInline):
    """Inline admin for hub source mappings."""

    model = HubSourceMapping
    extra = 1
    fields = ["staging_column", "is_primary_source"]
    autocomplete_fields = ["staging_column"]
    verbose_name = "Input Mapping"
    verbose_name_plural = "Input Mappings"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Rename staging_column to Input Column in the admin form."""
        if db_field.name == "staging_column":
            db_field.verbose_name = "Input Column"
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Hub)
class HubAdmin(admin.ModelAdmin):
    """Admin configuration for Hub model."""

    list_display = [
        "hub_physical_name",
        "hub_type",
        "hub_hashkey_name",
        "group",
        "project",
        "created_at",
    ]
    list_filter = [
        "hub_type",
        "project",
        "group",
        "create_record_tracking_satellite",
        "create_effectivity_satellite",
    ]
    search_fields = ["hub_physical_name", "hub_hashkey_name"]
    readonly_fields = ["hub_id", "created_at", "updated_at"]
    autocomplete_fields = ["project", "group"]
    inlines = [HubColumnInline]

    fieldsets = [
        (
            None,
            {
                "fields": [
                    "hub_id",
                    "project",
                    "hub_physical_name",
                    "hub_type",
                    "hub_hashkey_name",
                ]
            },
        ),
        (
            "Satellite Options",
            {
                "fields": [
                    "create_record_tracking_satellite",
                    "create_effectivity_satellite",
                ],
                "classes": ["collapse"],
            },
        ),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]


@admin.register(HubColumn)
class HubColumnAdmin(admin.ModelAdmin):
    """Admin configuration for HubColumn model."""

    list_display = [
        "column_name",
        "column_type",
        "hub",
        "sort_order",
        "get_mapping_count",
        "created_at",
    ]
    list_filter = ["column_type", "hub__hub_type"]
    search_fields = ["column_name", "hub__hub_physical_name"]
    readonly_fields = ["hub_column_id", "created_at", "updated_at"]
    autocomplete_fields = ["hub"]
    ordering = ["hub", "sort_order"]
    inlines = [HubSourceMappingInline]

    @admin.display(description="Source Mappings")
    def get_mapping_count(self, obj: HubColumn) -> int:
        """Return the number of source mappings for this column."""
        return obj.source_mappings.count()


@admin.register(HubSourceMapping)
class HubSourceMappingAdmin(admin.ModelAdmin):
    """Admin configuration for HubSourceMapping model."""

    list_display = [
        "hub_column",
        "staging_column",
        "is_primary_source",
        "get_hub",
        "created_at",
    ]
    list_filter = ["is_primary_source", "hub_column__hub__project"]
    search_fields = [
        "hub_column__column_name",
        "hub_column__hub__hub_physical_name",
        "staging_column__source_column__source_column_physical_name",
    ]
    readonly_fields = ["hub_source_mapping_id", "created_at", "updated_at"]
    autocomplete_fields = ["hub_column", "staging_column"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Rename staging_column to Input Column in the admin form."""
        if db_field.name == "staging_column":
            db_field.verbose_name = "Input Column"
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description="Hub", ordering="hub_column__hub__hub_physical_name")
    def get_hub(self, obj: HubSourceMapping) -> str:
        """Return the hub name for this mapping."""
        return obj.hub_column.hub.hub_physical_name


# Import snapshot control models
from engine.models import SnapshotControlLogic, SnapshotControlTable


class SnapshotControlLogicInline(admin.TabularInline):
    """Inline admin for snapshot control logic rules."""

    model = SnapshotControlLogic
    extra = 1
    fields = [
        "snapshot_control_logic_column_name",
        "snapshot_component",
        "snapshot_duration",
        "snapshot_unit",
        "snapshot_forever",
    ]
    verbose_name = "Logic Rule"
    verbose_name_plural = "Logic Rules"


@admin.register(SnapshotControlTable)
class SnapshotControlTableAdmin(admin.ModelAdmin):
    """Admin for snapshot control tables."""

    list_display = [
        "name",
        "project",
        "snapshot_start_date",
        "snapshot_end_date",
        "daily_snapshot_time",
    ]
    list_filter = ["project"]
    search_fields = ["name", "project__name"]
    readonly_fields = ["snapshot_control_table_id", "created_at", "updated_at"]
    autocomplete_fields = ["project"]
    inlines = [SnapshotControlLogicInline]

    fieldsets = [
        (None, {"fields": ["snapshot_control_table_id", "project", "name"]}),
        (
            "Snapshot Configuration",
            {
                "fields": [
                    "snapshot_start_date",
                    "snapshot_end_date",
                    "daily_snapshot_time",
                ]
            },
        ),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]

    @admin.display(description="Logic Rules")
    def get_logic_count(self, obj: SnapshotControlTable) -> int:
        """Return the number of logic rules for this snapshot control table."""
        return obj.logic_rules.count()


@admin.register(SnapshotControlLogic)
class SnapshotControlLogicAdmin(admin.ModelAdmin):
    """Admin configuration for SnapshotControlLogic model."""

    list_display = [
        "snapshot_control_logic_column_name",
        "snapshot_component",
        "snapshot_duration",
        "snapshot_unit",
        "snapshot_forever",
        "snapshot_control_table",
    ]
    list_filter = [
        "snapshot_component",
        "snapshot_unit",
        "snapshot_forever",
        "snapshot_control_table__project",
    ]
    search_fields = [
        "snapshot_control_logic_column_name",
        "snapshot_control_table__project__name",
    ]
    readonly_fields = ["snapshot_control_logic_id", "created_at", "updated_at"]
    autocomplete_fields = ["snapshot_control_table"]


# Import satellite models
from engine.models import Satellite, SatelliteColumn


class SatelliteColumnInline(admin.TabularInline):
    """Inline admin for satellite columns."""

    model = SatelliteColumn
    extra = 1
    fields = [
        "staging_column",
        "target_column_name",
        "is_multi_active_key",
        "include_in_delta_detection",
        "target_column_transformation",
    ]
    autocomplete_fields = ["staging_column"]
    verbose_name = "Satellite Column"
    verbose_name_plural = "Satellite Columns"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Rename staging_column and filter choices if possible."""
        if db_field.name == "staging_column":
            db_field.verbose_name = "Input Column"
            # Get the satellite being edited
            if request.resolver_match and request.resolver_match.kwargs.get(
                "object_id"
            ):
                try:
                    satellite = Satellite.objects.get(
                        pk=request.resolver_match.kwargs["object_id"]
                    )
                    if satellite.source_table:
                        # Filter to only staging columns from this satellite's source table
                        kwargs["queryset"] = StagingColumn.objects.filter(source_table=satellite.source_table)
                except Satellite.DoesNotExist:
                    pass
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Satellite)
class SatelliteAdmin(admin.ModelAdmin):
    """Admin configuration for Satellite model."""

    list_display = [
        "satellite_physical_name",
        "satellite_type",
        "get_parent",
        "source_table",
        "get_column_count",
        "project",
        "created_at",
    ]
    list_filter = [
        "satellite_type",
        "project",
        "group",
        "parent_hub",
        "parent_link",
        "source_table__source_system",
    ]
    search_fields = [
        "satellite_physical_name",
        "parent_hub__hub_physical_name",
        "parent_link__link_physical_name",
        "source_table__physical_table_name",
    ]
    readonly_fields = ["satellite_id", "created_at", "updated_at"]
    autocomplete_fields = [
        "project",
        "group",
        "parent_hub",
        "parent_link",
        "source_table",
    ]
    inlines = [SatelliteColumnInline]

    fieldsets = [
        (
            None,
            {
                "fields": [
                    "satellite_id",
                    "project",
                    "satellite_physical_name",
                    "satellite_type",
                ]
            },
        ),
        (
            "Parent Entity",
            {
                "fields": ["parent_hub", "parent_link"],
                "description": "Satellite must belong to exactly one parent: either a hub OR a link",
            },
        ),
        (
            "Source Table",
            {
                "fields": ["source_table"],
                "description": "All satellite columns must come from this source table",
            },
        ),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]

    @admin.display(description="Parent Entity")
    def get_parent(self, obj: Satellite) -> str:
        """Return the parent entity name."""
        if obj.parent_hub:
            return f"Hub: {obj.parent_hub.hub_physical_name}"
        elif obj.parent_link:
            return f"Link: {obj.parent_link.link_physical_name}"
        return "No parent"

    @admin.display(description="Columns")
    def get_column_count(self, obj: Satellite) -> int:
        """Return the number of columns in this satellite."""
        return obj.columns.count()


@admin.register(SatelliteColumn)
class SatelliteColumnAdmin(admin.ModelAdmin):
    """Admin configuration for SatelliteColumn model."""

    list_display = [
        "get_satellite",
        "staging_column",
        "target_column_name",
        "is_multi_active_key",
        "include_in_delta_detection",
    ]
    list_filter = [
        "satellite__satellite_type",
        "is_multi_active_key",
        "include_in_delta_detection",
        "satellite__project",
    ]
    search_fields = [
        "satellite__satellite_physical_name",
        "staging_column__source_column__source_column_physical_name",
        "target_column_name",
    ]
    readonly_fields = ["satellite_column_id", "created_at", "updated_at"]
    autocomplete_fields = ["satellite", "staging_column"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "staging_column":
            db_field.verbose_name = "Input Column"
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(
        description="Satellite", ordering="satellite__satellite_physical_name"
    )
    def get_satellite(self, obj: SatelliteColumn) -> str:
        """Return the satellite name."""
        return obj.satellite.satellite_physical_name


# Import link models
from engine.models import (
    Link,
    LinkColumn,
    LinkHubReference,
    LinkHubSourceMapping,
    LinkSourceMapping,
)


class LinkColumnInline(admin.TabularInline):
    """Inline admin for link columns."""

    model = LinkColumn
    extra = 1
    fields = ["column_name", "column_type", "sort_order"]
    ordering = ["sort_order"]
    show_change_link = True
    verbose_name = "Link Column"
    verbose_name_plural = "Link Columns"


class LinkHubSourceMappingInline(admin.TabularInline):
    """Inline admin for link hub source mappings."""

    model = LinkHubSourceMapping
    extra = 1
    fields = ["standard_hub_column", "staging_column"]
    autocomplete_fields = ["staging_column"]
    verbose_name = "Hub Key Mapping"
    verbose_name_plural = "Hub Key Mappings"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Filter standard_hub_column to only allow columns from the referenced hub."""
        if db_field.name == "standard_hub_column":
            # Get the ID of the LinkHubReference being edited
            if request.resolver_match and request.resolver_match.kwargs.get(
                "object_id"
            ):
                try:
                    link_hub_ref = LinkHubReference.objects.get(
                        pk=request.resolver_match.kwargs["object_id"]
                    )
                    # Filter columns to those belonging to the referenced hub
                    kwargs["queryset"] = HubColumn.objects.filter(hub=link_hub_ref.hub)
                except LinkHubReference.DoesNotExist:
                    pass
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class LinkHubReferenceInline(admin.TabularInline):
    """Inline admin for link hub references."""

    model = LinkHubReference
    extra = 1
    fields = ["hub", "hub_hashkey_alias_in_link", "sort_order"]
    ordering = ["sort_order"]
    autocomplete_fields = ["hub"]
    show_change_link = True  # Allow clicking to edit mappings in LinkHubReferenceAdmin
    verbose_name = "Hub Reference"
    verbose_name_plural = "Hub References"


class LinkSourceMappingInline(admin.TabularInline):
    """Inline admin for link source mappings."""

    model = LinkSourceMapping
    extra = 1
    fields = ["staging_column"]
    autocomplete_fields = ["staging_column"]
    verbose_name = "Input Mapping"
    verbose_name_plural = "Input Mappings"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "staging_column":
            db_field.verbose_name = "Input Column"
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    """Admin configuration for Link model."""

    list_display = [
        "link_physical_name",
        "link_type",
        "link_hashkey_name",
        "get_hub_count",
        "group",
        "project",
        "created_at",
    ]
    list_filter = ["link_type", "project", "group"]
    search_fields = ["link_physical_name", "link_hashkey_name"]
    readonly_fields = ["link_id", "created_at", "updated_at"]
    autocomplete_fields = ["project", "group"]
    inlines = [LinkHubReferenceInline, LinkColumnInline]

    fieldsets = [
        (
            None,
            {
                "fields": [
                    "link_id",
                    "project",
                    "group",
                    "link_physical_name",
                    "link_type",
                    "link_hashkey_name",
                ]
            },
        ),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]

    @admin.display(description="Hubs")
    def get_hub_count(self, obj: Link) -> int:
        """Return the number of hubs connected by this link."""
        return obj.hub_references.count()


@admin.register(LinkColumn)
class LinkColumnAdmin(admin.ModelAdmin):
    """Admin configuration for LinkColumn model."""

    list_display = [
        "column_name",
        "column_type",
        "link",
        "sort_order",
        "get_mapping_count",
        "created_at",
    ]
    list_filter = ["column_type", "link__project"]
    search_fields = ["column_name", "link__link_physical_name"]
    readonly_fields = ["link_column_id", "created_at", "updated_at"]
    autocomplete_fields = ["link"]
    ordering = ["link", "sort_order"]
    inlines = [LinkSourceMappingInline]

    @admin.display(description="Source Mappings")
    def get_mapping_count(self, obj: LinkColumn) -> int:
        """Return the number of source mappings for this column."""
        return obj.source_mappings.count()


@admin.register(LinkSourceMapping)
class LinkSourceMappingAdmin(admin.ModelAdmin):
    """Admin configuration for LinkSourceMapping model."""

    list_display = [
        "link_column",
        "staging_column",
        "get_link",
        "created_at",
    ]
    list_filter = ["link_column__link__project"]
    search_fields = [
        "link_column__column_name",
        "staging_column__source_column__source_column_physical_name",
    ]
    readonly_fields = ["link_source_mapping_id", "created_at", "updated_at"]
    autocomplete_fields = ["link_column", "staging_column"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "staging_column":
            db_field.verbose_name = "Input Column"
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description="Link", ordering="link_column__link__link_physical_name")
    def get_link(self, obj: LinkSourceMapping) -> str:
        """Return the link name for this mapping."""
        return obj.link_column.link.link_physical_name


@admin.register(LinkHubReference)
class LinkHubReferenceAdmin(admin.ModelAdmin):
    """Admin configuration for LinkHubReference model."""

    list_display = [
        "link",
        "hub",
        "hub_hashkey_alias_in_link",
        "sort_order",
        "created_at",
    ]
    list_filter = ["link__project", "hub"]
    search_fields = ["link__link_physical_name", "hub__hub_physical_name"]
    autocomplete_fields = ["link", "hub"]
    inlines = [LinkHubSourceMappingInline]


@admin.register(LinkHubSourceMapping)
class LinkHubSourceMappingAdmin(admin.ModelAdmin):
    """Admin configuration for LinkHubSourceMapping model."""

    list_display = [
        "link_hub_reference",
        "standard_hub_column",
        "staging_column",
        "created_at",
    ]
    list_filter = ["link_hub_reference__link__project"]
    search_fields = ["link_hub_reference__link__link_physical_name"]
    autocomplete_fields = [
        "link_hub_reference",
        "standard_hub_column",
        "staging_column",
    ]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Rename staging_column to Input Column in the admin form."""
        if db_field.name == "staging_column":
            db_field.verbose_name = "Input Column"
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# ==============================================================================
# Reference Table Admin
# ==============================================================================


class ReferenceTableSatelliteAssignmentInline(admin.TabularInline):
    """Inline for managing satellite assignments to reference tables."""

    model = ReferenceTableSatelliteAssignment
    extra = 1
    fields = ["reference_satellite", "include_columns", "exclude_columns"]
    autocomplete_fields = ["reference_satellite"]
    filter_horizontal = ["include_columns", "exclude_columns"]


@admin.register(ReferenceTable)
class ReferenceTableAdmin(admin.ModelAdmin):
    """Admin configuration for ReferenceTable model."""

    list_display = [
        "reference_table_physical_name",
        "reference_hub",
        "historization_type",
        "project",
        "created_at",
    ]
    list_filter = ["historization_type", "project"]
    search_fields = [
        "reference_table_physical_name",
        "reference_hub__hub_physical_name",
    ]
    readonly_fields = ["reference_table_id", "created_at", "updated_at"]
    autocomplete_fields = [
        "project",
        "reference_hub",
        "snapshot_control_table",
        "snapshot_control_logic",
    ]
    inlines = [ReferenceTableSatelliteAssignmentInline]

    fieldsets = [
        (
            None,
            {
                "fields": [
                    "reference_table_id",
                    "project",
                    "reference_table_physical_name",
                    "reference_hub",
                    "historization_type",
                ]
            },
        ),
        (
            "Snapshot Configuration",
            {
                "fields": ["snapshot_control_table", "snapshot_control_logic"],
                "description": "Required only for snapshot-based historization",
                "classes": ["collapse"],
            },
        ),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]


@admin.register(ReferenceTableSatelliteAssignment)
class ReferenceTableSatelliteAssignmentAdmin(admin.ModelAdmin):
    """Admin configuration for ReferenceTableSatelliteAssignment model."""

    list_display = ["reference_table", "reference_satellite", "created_at"]
    list_filter = ["reference_table", "reference_satellite"]
    search_fields = [
        "reference_table__reference_table_physical_name",
        "reference_satellite__satellite_physical_name",
    ]
    readonly_fields = ["assignment_id", "created_at", "updated_at"]
    autocomplete_fields = ["reference_table", "reference_satellite"]
    filter_horizontal = ["include_columns", "exclude_columns"]

    fieldsets = [
        (None, {"fields": ["assignment_id", "reference_table", "reference_satellite"]}),
        (
            "Column Control",
            {
                "fields": ["include_columns", "exclude_columns"],
                "description": "Specify EITHER include OR exclude columns, not both. Leave both empty to include all columns.",
            },
        ),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]


# ==============================================================================
# PIT Admin
# ==============================================================================


@admin.register(PIT)
class PITAdmin(admin.ModelAdmin):
    """Admin configuration for PIT model."""

    list_display = [
        "pit_physical_name",
        "tracked_entity_type",
        "get_tracked_entity",
        "get_satellite_count",
        "project",
        "created_at",
    ]
    list_filter = ["tracked_entity_type", "project", "use_snapshot_optimization"]
    search_fields = [
        "pit_physical_name",
        "tracked_hub__hub_physical_name",
        "tracked_link__link_physical_name",
    ]
    readonly_fields = ["pit_id", "created_at", "updated_at"]
    autocomplete_fields = [
        "project",
        "tracked_hub",
        "tracked_link",
        "snapshot_control_table",
        "snapshot_control_logic",
    ]
    filter_horizontal = ["satellites"]

    fieldsets = [
        (None, {"fields": ["pit_id", "project", "pit_physical_name"]}),
        (
            "Tracked Entity",
            {
                "fields": ["tracked_entity_type", "tracked_hub", "tracked_link"],
                "description": "Select EITHER a hub OR a link, not both",
            },
        ),
        (
            "Snapshot Configuration",
            {"fields": ["snapshot_control_table", "snapshot_control_logic"]},
        ),
        (
            "Satellites",
            {
                "fields": ["satellites"],
                "description": "Satellites to include in this PIT structure",
            },
        ),
        (
            "Options",
            {
                "fields": [
                    "dimension_key_column_name",
                    "pit_type",
                    "custom_record_source",
                    "use_snapshot_optimization",
                    "include_business_objects_before_appearance",
                ],
                "classes": ["collapse"],
            },
        ),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]

    @admin.display(description="Tracked Entity")
    def get_tracked_entity(self, obj: PIT) -> str:
        """Return the tracked entity name."""
        if obj.tracked_hub:
            return f"Hub: {obj.tracked_hub.hub_physical_name}"
        elif obj.tracked_link:
            return f"Link: {obj.tracked_link.link_physical_name}"
        return "None"

    @admin.display(description="Satellites")
    def get_satellite_count(self, obj: PIT) -> int:
        """Return the number of satellites in this PIT."""
        return obj.satellites.count()


# ==============================================================================
# Prejoin Admin
# ==============================================================================


class PrejoinExtractionColumnInline(admin.TabularInline):
    """Inline for prejoin extraction columns."""

    model = PrejoinExtractionColumn
    extra = 1
    autocomplete_fields = ["source_column"]
    fields = ["source_column", "prejoin_target_column_alias"]
    readonly_fields = ["extraction_id", "created_at", "updated_at"]


@admin.register(PrejoinDefinition)
class PrejoinDefinitionAdmin(admin.ModelAdmin):
    """Admin configuration for PrejoinDefinition model."""

    list_display = [
        "get_prejoin_name",
        "source_table",
        "prejoin_target_table",
        "prejoin_operator",
        "get_extraction_count",
        "project",
        "created_at",
    ]
    list_filter = ["project", "prejoin_operator", "source_table__source_system"]
    search_fields = [
        "source_table__physical_table_name",
        "prejoin_target_table__physical_table_name",
    ]
    readonly_fields = ["prejoin_id", "created_at", "updated_at"]
    autocomplete_fields = ["project", "source_table", "prejoin_target_table"]
    filter_horizontal = [
        "prejoin_condition_source_column",
        "prejoin_condition_target_column",
    ]
    inlines = [PrejoinExtractionColumnInline]

    fieldsets = [
        (None, {"fields": ["prejoin_id", "project"]}),
        (
            "Join Configuration",
            {
                "fields": [
                    "source_table",
                    "prejoin_condition_source_column",
                    "prejoin_target_table",
                    "prejoin_condition_target_column",
                    "prejoin_operator",
                ],
                "description": "Define the join between source and target tables",
            },
        ),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]

    @admin.display(description="Prejoin")
    def get_prejoin_name(self, obj: PrejoinDefinition) -> str:
        """Return a descriptive name for the prejoin."""
        return f"{obj.source_table.physical_table_name} → {obj.prejoin_target_table.physical_table_name}"

    @admin.display(description="Extraction Columns")
    def get_extraction_count(self, obj: PrejoinDefinition) -> int:
        """Return the number of extraction columns."""
        return obj.extraction_columns.count()


@admin.register(PrejoinExtractionColumn)
class PrejoinExtractionColumnAdmin(admin.ModelAdmin):
    """Admin configuration for PrejoinExtractionColumn model."""

    list_display = [
        "get_column_name",
        "prejoin_target_column_alias",
        "prejoin",
        "source_column",
        "created_at",
    ]
    list_filter = ["prejoin__project", "prejoin__source_table"]
    search_fields = [
        "source_column__source_column_physical_name",
        "prejoin__source_table__physical_table_name",
        "prejoin_target_column_alias",
    ]
    readonly_fields = ["extraction_id", "created_at", "updated_at"]
    autocomplete_fields = ["prejoin", "source_column"]

    @admin.display(description="Physical Column")
    def get_column_name(self, obj: PrejoinExtractionColumn) -> str:
        return obj.source_column.source_column_physical_name

    fieldsets = [
        (
            None,
            {
                "fields": [
                    "extraction_id",
                    "prejoin",
                    "source_column",
                    "prejoin_target_column_alias",
                ]
            },
        ),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]

    @admin.display(description="Extraction Column")
    def get_column_name(self, obj: PrejoinExtractionColumn) -> str:
        """Return the extraction column name."""
        return obj.source_column.source_column_physical_name


# ==============================================================================
# Template Admin
# ==============================================================================

from engine.models import ModelTemplate, TemplateCategory


@admin.register(TemplateCategory)
class TemplateCategoryAdmin(admin.ModelAdmin):
    """Admin configuration for TemplateCategory model."""

    list_display = ["name", "description", "created_at"]
    search_fields = ["name", "description"]
    readonly_fields = ["category_id", "created_at", "updated_at"]

    fieldsets = [
        (None, {"fields": ["category_id", "name", "description"]}),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]


@admin.register(ModelTemplate)
class ModelTemplateAdmin(admin.ModelAdmin):
    """Admin configuration for ModelTemplate model."""

    list_display = [
        "name",
        "entity_type",
        "category",
        "priority",
        "is_active",
        "has_sql_template",
        "has_yaml_template",
        "updated_at",
    ]
    list_filter = ["entity_type", "category", "is_active"]
    search_fields = ["name", "description"]
    readonly_fields = ["template_id", "created_at", "updated_at"]
    autocomplete_fields = ["category"]

    fieldsets = [
        (
            None,
            {
                "fields": [
                    "template_id",
                    "name",
                    "entity_type",
                    "category",
                    "description",
                ]
            },
        ),
        (
            "SQL Template",
            {
                "fields": ["sql_template_content"],
                "description": "Jinja2 template for the dbt SQL model",
            },
        ),
        (
            "YAML Template",
            {
                "fields": ["yaml_template_content"],
                "description": "Jinja2 template for the dbt YAML schema",
            },
        ),
        (
            "Configuration",
            {"fields": ["priority", "is_active"], "classes": ["collapse"]},
        ),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]

    @admin.display(boolean=True, description="SQL")
    def has_sql_template(self, obj: ModelTemplate) -> bool:
        """Check if template has SQL content."""
        return obj.has_sql_template

    @admin.display(boolean=True, description="YAML")
    def has_yaml_template(self, obj: ModelTemplate) -> bool:
        """Check if template has YAML content."""
        return obj.has_yaml_template
