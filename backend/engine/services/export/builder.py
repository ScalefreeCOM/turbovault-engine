"""
Model builder service for Data Vault export.

Transforms Django ORM models into intermediate Pydantic export models
by deriving all necessary information for generation.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

from engine.services.export.model_outputs import (  # noqa: F401 (re-exported)
    V1_SATELLITE_TYPES,
    ModelOutputs,
    dbt_source_name,
)
from engine.services.export.models import (
    ColumnDescriptionDef,
    DerivedColumnDef,
    EffectivitySatelliteOptions,
    HashkeyDefinition,
    HubColumnMapping,
    HubDefinition,
    HubSourceInfo,
    LinkColumnMapping,
    LinkDefinition,
    LinkHubReferenceDefinition,
    LinkSourceHashkeyMapping,
    LinkSourceInfo,
    MultiActiveConfig,
    PITDefinition,
    PrejoinCondition,
    PrejoinDefinitionExport,
    PrejoinExtractionColumn,
    PrestageDefinition,
    ProjectExport,
    ReferenceTableDefinition,
    ReferenceTableSatelliteAssignment,
    SatelliteColumnDef,
    SatelliteDefinition,
    SnapshotControlDefinition,
    SnapshotLogicPattern,
    SourceColumnDef,
    SourceDerivedColumnDef,
    SourceSystemDef,
    SourceTableDef,
    StageDefinition,
    StageHashdiffDef,
    StageHashkeyDef,
)
from engine.services.runtime_config import (
    EngineRuntimeConfig,
    resolve_runtime_config,
)
from engine.services.source_values import ResolvedSourceValues, resolve_table_values
from engine.services.sql_columns import referenced_columns

if TYPE_CHECKING:
    from collections.abc import Iterable

    from engine.models import Project, SourceTable, StagingColumn

# Enough of a staging column to know its name, type and description, whatever
# kind of column it wraps.
_STAGING_COLUMN_RELATED = (
    "source_column",
    "prejoin_column__source_column",
    "derived_column",
)


def _staging_prefetch(prefix: str) -> list[str]:
    return [f"{prefix}__{related}" for related in _STAGING_COLUMN_RELATED]


def _column_description(
    own: str | None, staging_columns: Iterable[StagingColumn]
) -> ColumnDescriptionDef | None:
    """A Raw Vault column's own description and the one it inherits.

    It inherits from the first of its source columns that has a description,
    so callers pass the primary source first.
    """
    inherited = next((sc.description for sc in staging_columns if sc.description), None)
    if not own and not inherited:
        return None
    return ColumnDescriptionDef(description=own or None, source_description=inherited)


def _prejoin_origin(staging_column: StagingColumn) -> tuple[str | None, str | None]:
    """Where a staging column's value comes from, when it is not a direct column.

    A ``StagingColumn`` wraps either a ``SourceColumn`` (direct) or a
    ``PrejoinExtractionColumn`` (pulled across a prejoin). For the latter,
    return the prejoin's target table and its source system so the importer can
    bind back to the extraction column instead of inventing a source column on
    the owning table. Returns ``(None, None)`` for direct columns.
    """
    prejoin_column = staging_column.prejoin_column
    if prejoin_column is None:
        return None, None
    target = prejoin_column.prejoin.prejoin_target_table
    return target.physical_table_name, target.source_system.name


class ModelBuilder:
    """
    Builds intermediate export models from Django ORM data.

    This is the core logic layer that:
    - Queries all relevant Django models for a project
    - Derives hashkey definitions for stages from hub/link mappings
    - Aggregates information into target-agnostic representations
    """

    # Transformation placeholder mappings
    # Each entry maps a placeholder pattern to a lambda that generates its replacement value
    # Add new placeholders here as needed
    TRANSFORMATION_PLACEHOLDERS = {
        "[[source_column]]": lambda source_col_name: source_col_name,
        # Future placeholders can be added here, e.g.:
        # "[[target_column]]": lambda source_col_name, target_col_name: target_col_name,
        # "[[datatype]]": lambda source_col_name, datatype: datatype,
    }

    def __init__(
        self, project: Project, runtime_config: EngineRuntimeConfig | None = None
    ) -> None:
        """
        Initialize the builder for a specific project.

        Args:
            project: Django Project model instance
            runtime_config: Optional project settings supplied by an embedder.
        """
        self.project = project
        self.runtime_config = resolve_runtime_config(project, runtime_config)
        self._outputs: ModelOutputs | None = None

    @property
    def outputs(self) -> ModelOutputs:
        """Names and settings of the project's dbt models."""
        if self._outputs is None:
            self._outputs = ModelOutputs(self.project, self.runtime_config)
        return self._outputs

    def _source_values(self, table: SourceTable) -> ResolvedSourceValues:
        """The record source, static part and load date the table's stage uses."""
        return resolve_table_values(table, runtime_config=self.runtime_config)

    def build(
        self,
        export_sources: bool = True,
        generate_tests: bool = True,
        generate_dbml: bool = False,
        runtime_config: EngineRuntimeConfig | None = None,
    ) -> ProjectExport:
        """
        Build complete project export from Django models.

        Args:
            export_sources: Whether to include source system definitions
            generate_tests: Whether tests should be generated (for future dbt generation)
            generate_dbml: Whether DBML file should be generated (for future use)

        Returns:
            ProjectExport with all definitions
        """
        config = runtime_config or self.runtime_config
        if runtime_config is not None:
            self.runtime_config = runtime_config
            self._outputs = None  # names follow the new config's patterns
        stage_schema = config.stage_schema
        rdv_schema = config.rdv_schema
        bdv_schema = config.bdv_schema

        return ProjectExport(
            project_name=self.project.name,
            project_description=self.project.description or None,
            generated_at=datetime.now(),
            stage_schema=stage_schema,
            rdv_schema=rdv_schema,
            bdv_schema=bdv_schema,
            export_sources=export_sources,
            generate_tests=generate_tests,
            generate_dbml=generate_dbml,
            sources=self._build_sources() if export_sources else [],
            hubs=self._build_hubs(),
            links=self._build_links(),
            prestages=self._build_prestages(),
            stages=self._build_stages(),
            satellites=self._build_satellites(),
            snapshot_controls=self._build_snapshot_controls(),
            reference_tables=self._build_reference_tables(),
            pits=self._build_pits(),
        )

    def _build_sources(self) -> list[SourceSystemDef]:
        """
        Build source system definitions from Django models.

        Returns:
            List of source system definitions with their tables/columns
        """
        from engine.models import SourceSystem

        source_systems = SourceSystem.objects.filter(
            project=self.project
        ).prefetch_related("tables__columns", "tables__derived_columns")

        result = []
        for source_system in source_systems:
            tables = []
            for table in source_system.tables.all():
                columns = [
                    SourceColumnDef(
                        column_name=col.source_column_physical_name,
                        datatype=col.source_column_datatype,
                        description=col.description or None,
                        is_missing=col.is_missing,
                    )
                    for col in table.columns.all()
                ]
                derived_columns = [
                    SourceDerivedColumnDef(
                        column_name=derived.column_name,
                        expression=derived.expression,
                        datatype=derived.datatype or None,
                        description=derived.description or None,
                    )
                    for derived in table.derived_columns.all()
                ]

                tables.append(
                    SourceTableDef(
                        table_name=table.physical_table_name,
                        table_type=table.table_type,
                        alias=table.alias,
                        record_source=table.record_source_value,
                        static_part_of_record_source=(
                            table.static_part_of_record_source
                        ),
                        load_date=table.load_date_value,
                        include_source_columns=table.include_source_columns,
                        enable_ghost_records=table.enable_ghost_records,
                        sequence_column=table.sequence_column or None,
                        delivery_method=table.delivery_method or None,
                        description=table.description or None,
                        columns=columns,
                        derived_columns=derived_columns,
                    )
                )

            result.append(
                SourceSystemDef(
                    name=source_system.name,
                    schema_name=source_system.schema_name,
                    database_name=source_system.database_name,
                    description=source_system.description or None,
                    record_source=source_system.record_source_value,
                    static_part_of_record_source=(
                        source_system.static_part_of_record_source
                    ),
                    load_date=source_system.load_date_value,
                    include_source_columns=source_system.include_source_columns,
                    enable_ghost_records=source_system.enable_ghost_records,
                    delivery_method=source_system.delivery_method or None,
                    tables=tables,
                )
            )

        return result

    def _build_hubs(self) -> list[HubDefinition]:
        """
        Build hub definitions from Django models.

        Returns:
            List of hub definitions with hashkey and source info
        """
        from engine.models import Hub, HubColumn

        hubs = Hub.objects.filter(project=self.project).prefetch_related(
            "columns__source_mappings__staging_column",
            *_staging_prefetch("columns__source_mappings__staging_column"),
            *_staging_prefetch("columns__link_hub_mappings__staging_column"),
        )

        result = []
        for hub in hubs:
            # Get business key columns (ordered)
            bk_columns = hub.columns.filter(
                column_type=HubColumn.ColumnType.BUSINESS_KEY
            ).order_by("sort_order")

            business_key_names = [col.column_name for col in bk_columns]

            # Get reference key columns (ordered)
            rk_columns = hub.columns.filter(
                column_type=HubColumn.ColumnType.REFERENCE_KEY
            ).order_by("sort_order")

            reference_key_names = [col.column_name for col in rk_columns]

            # Get additional columns
            additional_columns = hub.columns.filter(
                column_type=HubColumn.ColumnType.ADDITIONAL_COLUMN
            ).order_by("sort_order")

            additional_column_names = [col.column_name for col in additional_columns]

            # Build hashkey definition for standard hubs
            hashkey = None
            if hub.hub_type == Hub.HubType.STANDARD and hub.hub_hashkey_name:
                hashkey = HashkeyDefinition(
                    hashkey_name=hub.hub_hashkey_name, business_keys=business_key_names
                )

            # Get source tables feeding this hub
            source_info = self._get_hub_source_info(hub)

            column_descriptions: dict[str, ColumnDescriptionDef] = {}
            for column in hub.columns.all():
                # The primary source first; then sources that only load the
                # hub through a link.
                direct = sorted(
                    column.source_mappings.all(),
                    key=lambda mapping: not mapping.is_primary_source,
                )
                docs = _column_description(
                    column.description,
                    [
                        *(mapping.staging_column for mapping in direct),
                        *(
                            mapping.staging_column
                            for mapping in column.link_hub_mappings.all()
                        ),
                    ],
                )
                if docs is not None:
                    column_descriptions[column.column_name] = docs

            result.append(
                HubDefinition(
                    hub_name=hub.hub_physical_name,
                    hub_type=hub.hub_type,
                    group=hub.group.group_name if hub.group else None,
                    hashkey=hashkey,
                    business_key_columns=business_key_names,
                    reference_key_columns=reference_key_names,
                    additional_columns=additional_column_names,
                    source_tables=source_info,
                    create_record_tracking_satellite=hub.create_record_tracking_satellite,
                    create_effectivity_satellite=hub.create_effectivity_satellite,
                    disable_hwm=hub.disable_hwm,
                    effectivity_options=EffectivitySatelliteOptions(
                        is_active_alias=hub.effectivity_is_active_alias or None,
                        disable_hwm=hub.effectivity_disable_hwm,
                        additional_columns=list(
                            hub.effectivity_additional_columns or []
                        ),
                        # It reads the stage of the hub's first source that
                        # loads the hub's own hash key
                        source_is_single_batch=next(
                            (
                                source.source_is_single_batch
                                for source in source_info
                                if not source.hk_column
                            ),
                            False,
                        ),
                    ),
                    description=hub.description or None,
                    column_descriptions=column_descriptions,
                    output=self.outputs.hub(hub),
                    effectivity_satellite_output=(
                        self.outputs.effectivity_satellite(hub, hub.hub_physical_name)
                        if hub.create_effectivity_satellite
                        else None
                    ),
                    record_tracking_satellite_output=(
                        self.outputs.record_tracking_satellite(
                            hub, hub.hub_physical_name
                        )
                        if hub.create_record_tracking_satellite
                        else None
                    ),
                )
            )

        return result

    def _get_hub_source_info(self, hub) -> list[HubSourceInfo]:
        """
        Get information about source tables feeding a hub.

        Groups source columns by source table to show which columns
        map to business keys for each source.
        """
        from engine.models import HubColumn

        # Group mappings by source table and the stage hash key they load: a
        # table loading the hub under another hash key (role-playing) is a
        # source of its own.
        source_table_map: dict[tuple[str, str], dict] = defaultdict(
            lambda: {
                "source_system": "",
                "stage_name": "",
                "rsrc_static": None,
                "columns": [],
                "mappings": [],
                "is_primary_source": False,
                "single_batch": False,
            }
        )

        def source_key(mapping) -> tuple[str, str]:
            table = mapping.staging_column.source_table
            role = mapping.stage_hashkey_name or ""
            if role == (hub.hub_hashkey_name or ""):
                role = ""
            return (table.physical_table_name, role)

        for column in hub.columns.filter(column_type=HubColumn.ColumnType.BUSINESS_KEY):
            for mapping in column.source_mappings.all():
                table = mapping.staging_column.source_table
                table_key = source_key(mapping)

                source_table_map[table_key]["single_batch"] = self._single_batch(table)
                source_table_map[table_key]["source_system"] = table.source_system.name
                source_table_map[table_key]["stage_name"] = self.outputs.stage(
                    table
                ).model_name
                source_table_map[table_key]["rsrc_static"] = self._source_values(
                    table
                ).static_part.value
                src_col_name = mapping.staging_column.physical_name
                source_table_map[table_key]["columns"].append(src_col_name)
                source_table_map[table_key]["mappings"].append(
                    {
                        "hub_column": column.column_name,
                        "source_column": src_col_name,
                        "transformation": column.target_column_transformation,
                        "datatype": column.target_column_datatype,
                    }
                )
                if mapping.is_primary_source:
                    source_table_map[table_key]["is_primary_source"] = True

        # Also process REFERENCE_KEY columns for reference hubs
        for column in hub.columns.filter(
            column_type=HubColumn.ColumnType.REFERENCE_KEY
        ):
            for mapping in column.source_mappings.all():
                table = mapping.staging_column.source_table
                table_key = source_key(mapping)

                source_table_map[table_key]["single_batch"] = self._single_batch(table)
                source_table_map[table_key]["source_system"] = table.source_system.name
                source_table_map[table_key]["stage_name"] = self.outputs.stage(
                    table
                ).model_name
                source_table_map[table_key]["rsrc_static"] = self._source_values(
                    table
                ).static_part.value

                # Append if not already present
                col_name = mapping.staging_column.physical_name
                if col_name not in source_table_map[table_key]["columns"]:
                    source_table_map[table_key]["columns"].append(col_name)
                    source_table_map[table_key]["mappings"].append(
                        {
                            "hub_column": column.column_name,
                            "source_column": col_name,
                            "transformation": column.target_column_transformation,
                            "datatype": column.target_column_datatype,
                        }
                    )
                if mapping.is_primary_source:
                    source_table_map[table_key]["is_primary_source"] = True

        return [
            HubSourceInfo(
                source_table=table_name,
                source_system=info["source_system"],
                stage_name=info["stage_name"],
                rsrc_static=info["rsrc_static"],
                business_key_columns=info["columns"],
                is_primary_source=info["is_primary_source"],
                column_mappings=[
                    HubColumnMapping(
                        hub_column=m["hub_column"],
                        source_column=m["source_column"],
                        target_column_transformation=m["transformation"],
                        target_column_datatype=m["datatype"],
                    )
                    for m in info["mappings"]
                ],
                hk_column=role or None,
                source_is_single_batch=info["single_batch"],
            )
            for (table_name, role), info in source_table_map.items()
        ]

    def _build_stages(self) -> list[StageDefinition]:
        """
        Build stage definitions for all source tables.

        For each source table, aggregates all hashkeys that need to be
        computed from hubs (and future: links) that use this source,
        plus hashdiffs from satellites.

        A pre-stage's stage reads the pre-stage model with ``ref()``.

        Returns:
            List of stage definitions with hashkey and hashdiff calculations
        """
        from engine.models import SourceTable

        source_tables = list(
            SourceTable.objects.filter(project=self.project)
            .select_related("source_system")
            .prefetch_related("columns", "derived_columns")
        )

        result = []
        for table in source_tables:
            # Get all hashkeys needed for this source table
            hashkeys = self._get_hashkeys_for_source_table(table)

            # Get hashdiffs from satellites that use this source table
            hashdiffs = self._get_hashdiffs_for_source_table(table)

            # Get multi-active config if any multi-active satellite uses this table
            multi_active_config = self._get_multi_active_config_for_source_table(table)

            # Get prejoins that use this source table
            prejoins = self._get_prejoins_for_source_table(table)

            # Derived columns: defined on the table, or from transformations
            derived_columns = self._get_derived_columns_for_source_table(table)

            # Get columns; the missing ones the stage adds with NULL values
            columns = [
                SourceColumnDef(
                    column_name=col.source_column_physical_name,
                    datatype=col.source_column_datatype,
                    description=col.description or None,
                    is_missing=col.is_missing,
                )
                for col in table.columns.all()
            ]

            values = self._source_values(table)
            output = self.outputs.stage(table)

            result.append(
                StageDefinition(
                    stage_name=output.model_name,
                    source_table=table.physical_table_name,
                    source_schema=table.source_system.schema_name,
                    source_system=table.source_system.name,
                    prestage_model=(
                        self.outputs.prestage_name(table) if table.is_prestage else None
                    ),
                    record_source=values.record_source.value,
                    load_date=values.load_date.value,
                    output=output,
                    description=table.description or None,
                    include_source_columns=self._stage_option(
                        table, "include_source_columns"
                    ),
                    enable_ghost_records=self._stage_option(
                        table, "enable_ghost_records"
                    ),
                    sequence_column=table.sequence_column or None,
                    missing_columns=[col for col in columns if col.is_missing],
                    hashkeys=hashkeys,
                    hashdiffs=hashdiffs,
                    prejoins=prejoins,
                    multi_active_config=multi_active_config,
                    derived_columns=derived_columns,
                    columns=columns,
                )
            )

        return result

    def _build_prestages(self) -> list[PrestageDefinition]:
        """Build the pre-stages: one per source table of type prestage.

        The dbt project maintains each pre-stage's model; TurboVault generates
        no file for it. The list names the models the project must contain.
        """
        from engine.models import SourceTable

        tables = (
            SourceTable.objects.filter(
                project=self.project, table_type=SourceTable.TableType.PRESTAGE
            )
            .select_related("source_system")
            .prefetch_related("columns")
        )
        return [
            PrestageDefinition(
                model_name=self.outputs.prestage_name(table),
                table_name=table.physical_table_name,
                source_system=table.source_system.name,
                description=table.description or None,
                columns=[
                    SourceColumnDef(
                        column_name=column.source_column_physical_name,
                        datatype=column.source_column_datatype,
                        description=column.description or None,
                    )
                    for column in table.columns.all()
                ],
            )
            for table in tables
        ]

    def _get_hashdiffs_for_source_table(
        self, source_table: SourceTable
    ) -> list[StageHashdiffDef]:
        """
        Get all hashdiff definitions for satellites using this source table.

        Each satellite creates one hashdiff containing columns where
        include_in_delta_detection is True.
        """
        from engine.models import Satellite

        satellites = Satellite.objects.filter(
            source_table=source_table
        ).prefetch_related("columns__staging_column")

        result = []
        for sat in satellites:
            # Get columns that should be included in hashdiff
            hashdiff_columns = [
                col.target_column_name or col.staging_column.physical_name
                for col in sat.columns.order_by("column_sort_order")
                if col.include_in_delta_detection
            ]

            if hashdiff_columns:
                result.append(
                    StageHashdiffDef(
                        satellite_name=sat.satellite_physical_name,
                        hashdiff_name=self._hashdiff_name(sat),
                        columns=hashdiff_columns,
                    )
                )

        return result

    def _hashdiff_name(self, satellite) -> str:
        """The stage's hash diff column of a satellite: stored, else the pattern."""
        return satellite.hashdiff_name or self.project.resolve_naming_pattern(
            "hashdiff_naming",
            satellite.satellite_physical_name,
            runtime_config=self.runtime_config,
        )

    def _stage_option(self, table: SourceTable, field: str) -> bool:
        """A stage option: the table's, else its source system's, else the project's."""
        for value in (
            getattr(table, field),
            getattr(table.source_system, field),
        ):
            if value is not None:
                return value
        return getattr(self.runtime_config, field)

    def _single_batch(self, table: SourceTable | None) -> bool:
        """Whether models may load *table* with datavault4dbt's single-batch logic.

        Only with the project's delivery method switch on, for a table whose
        delivery method (its own, else its system's, else the project's) is
        single_batch.
        """
        if table is None or not self.runtime_config.use_delivery_method:
            return False
        method = (
            table.delivery_method
            or table.source_system.delivery_method
            or self.runtime_config.delivery_method
        )
        return method == "single_batch"

    def _get_multi_active_config_for_source_table(
        self, source_table: SourceTable
    ) -> MultiActiveConfig | None:
        """
        Get multi-active configuration if any multi-active satellite uses this source table.

        Takes config from the first multi-active satellite found for this table.
        Returns None if no multi-active satellite exists.
        """
        from engine.models import Satellite

        # Find multi-active satellites for this source table
        multi_active_sat = (
            Satellite.objects.filter(
                source_table=source_table,
                satellite_type=Satellite.SatelliteType.MULTI_ACTIVE,
            )
            .select_related("parent_hub")
            .prefetch_related("columns__staging_column")
            .first()
        )

        if not multi_active_sat:
            return None

        # Get multi-active key columns
        ma_key_columns = [
            col.target_column_name or col.staging_column.physical_name
            for col in multi_active_sat.columns.all()
            if col.is_multi_active_key
        ]

        # Get parent hashkey
        main_hashkey = ""
        if multi_active_sat.parent_hub and multi_active_sat.parent_hub.hub_hashkey_name:
            main_hashkey = multi_active_sat.parent_hub.hub_hashkey_name
        # Future: handle parent_link.link_hashkey_name

        if ma_key_columns and main_hashkey:
            return MultiActiveConfig(
                multi_active_key=ma_key_columns, main_hashkey_column=main_hashkey
            )

        return None

    def _replace_transformation_placeholders(
        self, transformation: str | None, source_col_name: str
    ) -> str | None:
        """
        Replace placeholders in transformation string with actual values.

        Iterates through all defined TRANSFORMATION_PLACEHOLDERS and replaces
        each placeholder with its corresponding value.

        Args:
            transformation: The transformation string (may contain placeholders)
            source_col_name: The source column name for placeholder replacement

        Returns:
            Transformation string with all placeholders replaced, or None if input was None
        """
        if not transformation:
            return transformation

        result = transformation
        # Iterate through all defined placeholders and replace them
        for placeholder, replacement_fn in self.TRANSFORMATION_PLACEHOLDERS.items():
            if placeholder in result:
                # Call the replacement function with source_col_name
                replacement_value = replacement_fn(source_col_name)
                result = result.replace(placeholder, replacement_value)

        return result

    def _get_derived_columns_for_source_table(
        self, source_table: SourceTable
    ) -> list[DerivedColumnDef]:
        """
        Get derived column definitions for this source table's stage.

        Covers four producers:
          - derived columns defined on the table,
          - satellite columns that are renamed and/or transformed,
          - hub columns with a transformation (business key hard rules),
          - link columns with a transformation (dependent child keys, payload).

        Hub and link transformations are emitted *in place*: the derived column
        keeps the source column's name, so it replaces the raw value everywhere
        downstream in the stage. datavault4dbt builds `hashed_columns` on top of
        `derived_columns`, which is what makes the hashkey hash the transformed
        business key instead of the raw one.

        datavault4dbt computes every derived column in one SELECT, so one can't
        read another. A transformation of a derived column therefore inlines
        that column's expression in place of ``[[source_column]]``.

        An expression needs a data type: datavault4dbt looks one up only for a
        value that is a plain column name, and fails for anything else. A
        transformation without its own type takes the source column's.

        Args:
            source_table: The source table to get derived columns for

        Returns:
            List of derived column definitions with placeholders replaced
        """
        from engine.models import (
            DerivedColumn,
            HubColumn,
            HubSourceMapping,
            LinkColumn,
            LinkHubSourceMapping,
            LinkSourceMapping,
            Satellite,
        )

        # What src_cols_required may list: the table's own columns.
        table_columns = [
            column.source_column_physical_name for column in source_table.columns.all()
        ]

        result: list[DerivedColumnDef] = []
        # A source column can reach the stage through several routes at once
        # (e.g. a table feeding both a hub and a link that references it).
        # Derived columns become YAML mapping keys, so identical definitions
        # must be emitted only once.
        seen: set[tuple[str, str, str | None]] = set()
        # Where each derived column defined on the table sits in `result`, so
        # an in-place transformation of it replaces its definition.
        defined_at: dict[str, int] = {}
        # Derived columns by name. One named like a source column shadows it:
        # the stage replaces the source column with the derived value, so a
        # mapping of that source column reads the derived column.
        derived_by_name: dict[str, DerivedColumn] = {}

        for derived in DerivedColumn.objects.filter(source_table=source_table):
            required = referenced_columns(derived.expression, table_columns)
            defined_at[derived.column_name.lower()] = len(result)
            derived_by_name[derived.column_name.lower()] = derived
            result.append(
                DerivedColumnDef(
                    target_column_name=derived.column_name,
                    source_column_name=required[0] if required else derived.column_name,
                    datatype=derived.datatype or "",
                    transformation=derived.expression,
                    src_cols_required=required,
                    description=derived.description or None,
                )
            )

        def add(
            target_col_name: str,
            staging_column: StagingColumn,
            transformation: str | None,
            datatype: str | None,
        ) -> None:
            source_col_name = staging_column.physical_name
            derived = staging_column.derived_column
            if derived is None and staging_column.source_column_id is not None:
                # A source column a derived column shadows reads the derived value
                derived = derived_by_name.get(source_col_name.lower())
            if derived is not None:
                if target_col_name == source_col_name and not transformation:
                    return  # the derived column itself, already defined
                inlined = f"({derived.expression})"
                value = (
                    self._replace_transformation_placeholders(transformation, inlined)
                    or inlined
                )
                required = referenced_columns(derived.expression, table_columns)
                resolved_type = datatype or derived.datatype or ""
                position = defined_at.get(target_col_name.lower())
                if position is not None:
                    result[position] = result[position].model_copy(
                        update={"transformation": value, "datatype": resolved_type}
                    )
                    return
                definition = DerivedColumnDef(
                    target_column_name=target_col_name,
                    source_column_name=required[0] if required else source_col_name,
                    datatype=resolved_type,
                    transformation=value,
                    src_cols_required=required,
                )
            else:
                transformation_replaced = self._replace_transformation_placeholders(
                    transformation, source_col_name
                )
                # Nothing to derive if neither renamed nor transformed
                if target_col_name == source_col_name and not transformation_replaced:
                    return
                definition = DerivedColumnDef(
                    target_column_name=target_col_name,
                    source_column_name=source_col_name,
                    # A plain rename lets datavault4dbt look the type up.
                    datatype=(
                        (datatype or staging_column.datatype or "")
                        if transformation_replaced
                        else ""
                    ),
                    transformation=transformation_replaced,
                    src_cols_required=[source_col_name],
                )
            key = (
                definition.target_column_name,
                definition.source_column_name,
                definition.transformation,
            )
            if key in seen:
                return
            seen.add(key)
            result.append(definition)

        satellites = Satellite.objects.filter(
            source_table=source_table
        ).prefetch_related(*_staging_prefetch("columns__staging_column"))

        for sat in satellites:
            for col in sat.columns.all():
                add(
                    col.target_column_name or col.staging_column.physical_name,
                    col.staging_column,
                    col.target_column_transformation,
                    col.target_column_datatype,
                )

        # Hub business/reference keys loaded directly from this source table.
        hub_mappings = HubSourceMapping.objects.filter(
            staging_column__source_table=source_table
        ).select_related("hub_column", *_staging_prefetch("staging_column"))

        for mapping in hub_mappings:
            transformation = mapping.hub_column.target_column_transformation
            if mapping.hub_column.column_type == HubColumn.ColumnType.ADDITIONAL_COLUMN:
                # datavault4dbt takes additional columns from the stage as they
                # are: the stage provides them under the hub column's name.
                add(
                    mapping.hub_column.column_name,
                    mapping.staging_column,
                    transformation,
                    mapping.hub_column.target_column_datatype,
                )
                continue
            if not transformation:
                continue
            add(
                mapping.staging_column.physical_name,
                mapping.staging_column,
                transformation,
                mapping.hub_column.target_column_datatype,
            )

        # Hub business keys reached via a link. The same hub column may be fed
        # from a table that only loads the link, and its hub hashkey is computed
        # there too — so the transformation has to be applied in that stage as
        # well, otherwise the two stages produce different hashkeys.
        link_hub_mappings = LinkHubSourceMapping.objects.filter(
            staging_column__source_table=source_table
        ).select_related("standard_hub_column", *_staging_prefetch("staging_column"))

        for link_hub_mapping in link_hub_mappings:
            hub_column = link_hub_mapping.standard_hub_column
            if not hub_column.target_column_transformation:
                continue
            add(
                link_hub_mapping.staging_column.physical_name,
                link_hub_mapping.staging_column,
                hub_column.target_column_transformation,
                hub_column.target_column_datatype,
            )

        # Link's own columns (dependent child keys, payload, additional).
        link_source_mappings = LinkSourceMapping.objects.filter(
            staging_column__source_table=source_table
        ).select_related("link_column", *_staging_prefetch("staging_column"))

        for link_mapping in link_source_mappings:
            link_column = link_mapping.link_column
            if link_column.column_type == LinkColumn.ColumnType.ADDITIONAL_COLUMN:
                # Taken from the stage as they are, like a hub's
                add(
                    link_column.column_name,
                    link_mapping.staging_column,
                    link_column.target_column_transformation,
                    link_column.target_column_datatype,
                )
                continue
            if not link_column.target_column_transformation:
                continue
            add(
                link_mapping.staging_column.physical_name,
                link_mapping.staging_column,
                link_column.target_column_transformation,
                link_column.target_column_datatype,
            )

        return result

    def _get_prejoins_for_source_table(
        self, source_table: SourceTable
    ) -> list[PrejoinDefinitionExport]:
        """
        Get prejoin definitions for a source table.

        Queries prejoins where this source table is the main table being joined from,
        and builds the export representation with join conditions and extraction columns.

        Args:
            source_table: The source table to get prejoins for

        Returns:
            List of prejoin export definitions
        """
        from engine.models import PrejoinDefinition

        # Find all prejoins where this is the source table
        prejoins = PrejoinDefinition.objects.filter(
            source_table=source_table
        ).prefetch_related(
            "prejoin_condition_source_column",
            "prejoin_condition_target_column",
            "prejoin_target_table__source_system",
            "extraction_columns__source_column",
        )

        result = []
        for prejoin in prejoins:
            # Build join conditions
            source_columns = [
                col.source_column_physical_name
                for col in prejoin.prejoin_condition_source_column.all()
            ]
            target_columns = [
                col.source_column_physical_name
                for col in prejoin.prejoin_condition_target_column.all()
            ]

            join_conditions = PrejoinCondition(
                source_columns=source_columns,
                target_columns=target_columns,
                operator=prejoin.prejoin_operator,
            )

            # Get extraction column names
            extraction_columns = [
                PrejoinExtractionColumn(
                    source_column_name=ext.source_column.source_column_physical_name,
                    target_column_alias=ext.prejoin_target_column_alias
                    or ext.source_column.source_column_physical_name,
                )
                for ext in prejoin.extraction_columns.all()
            ]

            target = prejoin.prejoin_target_table
            result.append(
                PrejoinDefinitionExport(
                    target_table=target.physical_table_name,
                    target_source_system=target.source_system.name,
                    target_model=(
                        self.outputs.prestage_name(target)
                        if target.is_prestage
                        else None
                    ),
                    join_conditions=join_conditions,
                    extraction_columns=extraction_columns,
                )
            )

        return result

    def _get_hashkeys_for_source_table(
        self, source_table: SourceTable
    ) -> list[StageHashkeyDef]:
        """
        Get all hashkey definitions needed for a source table's stage.

        Queries hub and link source mappings to find all hashkeys that need
        to be calculated from this source table.

        Args:
            source_table: The source table to get hashkeys for

        Returns:
            List of hashkey definitions for the stage
        """
        from engine.models import (
            Hub,
            HubColumn,
            HubSourceMapping,
            LinkColumn,
            LinkHubSourceMapping,
            LinkSourceMapping,
        )

        result = []
        generated_hashkeys = set()

        # ========================================================================
        # 1. Process Hub Hashkeys
        # ========================================================================

        # Find all hub source mappings where source column is from this table
        hub_mappings = HubSourceMapping.objects.filter(
            staging_column__source_table=source_table
        ).select_related("hub_column__hub", "staging_column")

        # Group by hub and the stage hash key the mappings load: the hub's own,
        # or another one when this table loads the hub in another role.
        hub_columns_map: dict[tuple[str, str], dict] = defaultdict(
            lambda: {"hub": None, "source_columns": []}
        )

        for mapping in hub_mappings:
            hub = mapping.hub_column.hub
            hub_key = (str(hub.hub_id), mapping.stage_hashkey_name or "")

            hub_columns_map[hub_key]["hub"] = hub

            # Only include business key columns for hashkey calculation
            if mapping.hub_column.column_type == HubColumn.ColumnType.BUSINESS_KEY:
                hub_columns_map[hub_key]["source_columns"].append(
                    {
                        "source_column": mapping.staging_column.physical_name,
                        "sort_order": mapping.hub_column.sort_order or 0,
                    }
                )

        for (_hub_id, role), info in hub_columns_map.items():
            hub = info["hub"]

            # Skip if not a standard hub (no hashkey needed)
            if hub.hub_type != Hub.HubType.STANDARD or not hub.hub_hashkey_name:
                continue

            # Sort source columns by hub column sort order
            sorted_columns = sorted(
                info["source_columns"], key=lambda x: x["sort_order"]
            )
            source_column_names = [c["source_column"] for c in sorted_columns]

            if source_column_names:  # Only add if we have business key columns
                hashkey_name = role or hub.hub_hashkey_name
                # A role's hash key once per stage, even if two roles name it alike
                if role and hashkey_name in generated_hashkeys:
                    continue
                result.append(
                    StageHashkeyDef(
                        target_entity=hub.hub_physical_name,
                        entity_type="hub",
                        hashkey_name=hashkey_name,
                        business_key_columns=source_column_names,
                    )
                )
                generated_hashkeys.add(hashkey_name)

        # ========================================================================
        # 2. Process Link Hashkeys
        # ========================================================================

        # Find all link hub source mappings where source column is from this table
        link_hub_mappings = LinkHubSourceMapping.objects.filter(
            staging_column__source_table=source_table
        ).select_related(
            "link_hub_reference__link",
            "link_hub_reference__hub",
            "standard_hub_column",
            "staging_column",
        )

        # Group by link to build link hashkey definitions
        link_columns_map: dict[str, dict] = defaultdict(
            lambda: {
                "link": None,
                "hub_source_columns": [],  # Columns from hub references
                "dependent_child_keys": [],  # Dependent child key columns
                "hub_refs": defaultdict(list),  # Track columns per hub reference
            }
        )

        for mapping in link_hub_mappings:
            link = mapping.link_hub_reference.link
            link_key = str(link.link_id)
            hub_ref = mapping.link_hub_reference

            link_columns_map[link_key]["link"] = link

            # Get the source column name from the unified staging column
            source_col_name = mapping.staging_column.physical_name

            # Add to hub source columns with proper sorting (for Link Hashkey)
            link_columns_map[link_key]["hub_source_columns"].append(
                {
                    "source_column": source_col_name,
                    "hub_ref_sort_order": hub_ref.sort_order or 0,
                    "hub_col_sort_order": mapping.standard_hub_column.sort_order or 0,
                }
            )

            # Store for Hub Hashkey (grouped by Hub Ref)
            link_columns_map[link_key]["hub_refs"][hub_ref].append(
                {
                    "source_column": source_col_name,
                    "sort_order": mapping.standard_hub_column.sort_order or 0,
                }
            )

        # Now find dependent child keys for each link from this source table
        link_source_mappings = LinkSourceMapping.objects.filter(
            staging_column__source_table=source_table,
            link_column__column_type=LinkColumn.ColumnType.DEPENDENT_CHILD_KEY,
        ).select_related("link_column__link", "staging_column")

        for mapping in link_source_mappings:
            link = mapping.link_column.link
            link_key = str(link.link_id)

            # Initialize link entry if not already present
            if link_key not in link_columns_map:
                link_columns_map[link_key] = {
                    "link": link,
                    "hub_source_columns": [],
                    "dependent_child_keys": [],
                    "hub_refs": defaultdict(list),
                }

            link_columns_map[link_key]["dependent_child_keys"].append(
                {
                    "source_column": mapping.staging_column.physical_name,
                    "sort_order": mapping.link_column.sort_order or 0,
                }
            )

        # Build link hashkey definitions
        for _link_key, info in link_columns_map.items():
            link = info["link"]

            # ----------------------------------------------------------------
            # Handle referenced Hub Hashkeys
            # ----------------------------------------------------------------
            for hub_ref, col_info in info["hub_refs"].items():
                # Determine hashkey name
                hashkey_name = (
                    hub_ref.hub_hashkey_alias_in_link or hub_ref.hub.hub_hashkey_name
                )

                if not hashkey_name:
                    continue

                # Avoid duplicates if we already generated this hashkey
                if hashkey_name in generated_hashkeys:
                    continue

                # Sort by hub column sort order
                sorted_hub_bk_cols = sorted(col_info, key=lambda x: x["sort_order"])
                bk_col_names = [c["source_column"] for c in sorted_hub_bk_cols]

                if bk_col_names:
                    result.append(
                        StageHashkeyDef(
                            target_entity=hub_ref.hub.hub_physical_name,
                            entity_type="hub",
                            hashkey_name=hashkey_name,
                            business_key_columns=bk_col_names,
                        )
                    )
                    generated_hashkeys.add(hashkey_name)

            # ----------------------------------------------------------------
            # Link Hashkey
            # ----------------------------------------------------------------
            # Skip if no hashkey name is defined
            if not link.link_hashkey_name:
                continue

            # Sort hub source columns first by hub reference sort order, then by hub column sort order
            sorted_hub_columns = sorted(
                info["hub_source_columns"],
                key=lambda x: (x["hub_ref_sort_order"], x["hub_col_sort_order"]),
            )
            hub_column_names = [c["source_column"] for c in sorted_hub_columns]

            # Sort dependent child keys by their sort order
            sorted_child_keys = sorted(
                info["dependent_child_keys"], key=lambda x: x["sort_order"]
            )
            child_key_names = [c["source_column"] for c in sorted_child_keys]

            # Combine hub columns and dependent child keys
            all_business_keys = hub_column_names + child_key_names

            # Only add if we have at least some business key columns
            if all_business_keys:
                result.append(
                    StageHashkeyDef(
                        target_entity=link.link_physical_name,
                        entity_type="link",
                        hashkey_name=link.link_hashkey_name,
                        business_key_columns=all_business_keys,
                    )
                )

        return result

    def _build_satellites(self) -> list[SatelliteDefinition]:
        """
        Build satellite definitions from Django models.

        Returns:
            List of satellite definitions with columns
        """
        from engine.models import Satellite

        satellites = Satellite.objects.filter(project=self.project).prefetch_related(
            "columns__staging_column__source_table",
            *_staging_prefetch("columns__staging_column"),
            "parent_hub",
            "parent_link",
        )

        result = []
        for sat in satellites:
            # Skip satellites without source_table
            if not sat.source_table:
                continue

            # Determine parent entity, hashkey, and business keys
            parent_business_keys: list[str] = []
            if sat.parent_hub:
                parent_name = sat.parent_hub.hub_physical_name
                parent_type = "hub"
                parent_hashkey = sat.parent_hub.hub_hashkey_name or ""
                # Get business keys from hub columns
                parent_business_keys = list(
                    sat.parent_hub.columns.values_list("column_name", flat=True)
                )
            elif sat.parent_link:
                parent_name = sat.parent_link.link_physical_name
                parent_type = "link"
                parent_hashkey = sat.parent_link.link_hashkey_name or ""
            else:
                # No valid parent
                continue

            stage_name = self.outputs.stage(sat.source_table).model_name

            # The stage's hash diff column: stored, else the project pattern
            hashdiff_name = self._hashdiff_name(sat)

            # Build column definitions
            columns = []
            for col in sat.columns.order_by("column_sort_order"):
                columns.append(
                    SatelliteColumnDef(
                        source_column=col.staging_column.physical_name,
                        target_column_name=col.target_column_name,
                        is_multi_active_key=col.is_multi_active_key,
                        include_in_delta_detection=col.include_in_delta_detection,
                        target_column_transformation=col.target_column_transformation,
                        target_column_datatype=col.target_column_datatype or None,
                        description=col.description or None,
                        source_description=col.staging_column.description or None,
                    )
                )

            result.append(
                SatelliteDefinition(
                    satellite_name=sat.satellite_physical_name,
                    satellite_type=sat.satellite_type,
                    group=sat.group.group_name if sat.group else None,
                    parent_entity=parent_name,
                    parent_entity_type=parent_type,
                    parent_hashkey=parent_hashkey,
                    parent_business_keys=parent_business_keys,
                    source_table=sat.source_table.physical_table_name,
                    source_system=sat.source_table.source_system.name,
                    stage_name=stage_name,
                    hashdiff_name=hashdiff_name,
                    hashdiff_alias=sat.hashdiff_alias or None,
                    columns=columns,
                    description=sat.description or None,
                    v0_output=self.outputs.satellite_v0(sat),
                    v1_output=(
                        self.outputs.satellite_v1(sat)
                        if sat.satellite_type in V1_SATELLITE_TYPES
                        else None
                    ),
                    create_v1_view=sat.create_v1_view,
                    v1_ledts_alias=sat.v1_ledts_alias or None,
                    v1_add_is_current_flag=sat.v1_add_is_current_flag,
                    v1_include_payload=sat.v1_include_payload,
                    disable_hwm=sat.disable_hwm,
                    source_is_single_batch=self._single_batch(sat.source_table),
                )
            )

        return result

    def _build_links(self) -> list[LinkDefinition]:
        """
        Build link definitions from Django models.

        Returns:
            List of link definitions with hub references and source info
        """
        from engine.models import Link, LinkColumn

        links = Link.objects.filter(project=self.project).prefetch_related(
            "hub_references__source_mappings__staging_column__source_table__source_system",
            "hub_references__source_mappings__staging_column__prejoin_column__prejoin__prejoin_target_table__source_system",
            "hub_references__source_mappings__standard_hub_column",
            "columns__source_mappings__staging_column__source_table__source_system",
            "columns__source_mappings__staging_column__prejoin_column__prejoin__prejoin_target_table__source_system",
            *_staging_prefetch("columns__source_mappings__staging_column"),
        )

        result = []
        for link in links:
            # Get hub references with their hashkey names
            hub_refs = link.hub_references.all()

            # Transform to LinkHubReferenceDefinition
            hub_ref_defs = [
                LinkHubReferenceDefinition(
                    hub_name=hub_ref.hub.hub_physical_name,
                    hub_hashkey_alias_in_link=hub_ref.hub_hashkey_alias_in_link or None,
                )
                for hub_ref in hub_refs
            ]

            foreign_hashkeys = [
                hub_ref.hub_hashkey_alias_in_link or hub_ref.hub.hub_hashkey_name
                for hub_ref in hub_refs
                if (hub_ref.hub_hashkey_alias_in_link or hub_ref.hub.hub_hashkey_name)
            ]

            # Business key columns are NOT stored in LinkColumn
            # They are derived from hub references via LinkHubSourceMapping
            #  For the link definition export, we don't list them separately
            # as they're implicit in the hub_references
            business_key_column_names = []

            # Get payload and additional columns
            payload_cols = link.columns.filter(
                column_type=LinkColumn.ColumnType.PAYLOAD
            ).values_list("column_name", flat=True)

            additional_cols = link.columns.filter(
                column_type=LinkColumn.ColumnType.ADDITIONAL_COLUMN
            ).values_list("column_name", flat=True)

            # Build source table map with column mappings
            source_table_map: dict[str, dict] = {}

            for column in link.columns.all():
                for mapping in column.source_mappings.all():
                    # Handle unified staging column
                    table = mapping.staging_column.source_table
                    source_col_name = mapping.staging_column.physical_name

                    table_key = table.physical_table_name

                    if table_key not in source_table_map:
                        source_table_map[table_key] = {
                            "source_system": table.source_system.name,
                            "stage_name": self.outputs.stage(table).model_name,
                            "rsrc_static": self._source_values(table).static_part.value,
                            "single_batch": self._single_batch(table),
                            "columns": [],
                            "hashkey_mappings": [],
                        }

                    prejoin_target, prejoin_system = _prejoin_origin(
                        mapping.staging_column
                    )

                    # Add column mapping
                    source_table_map[table_key]["columns"].append(
                        LinkColumnMapping(
                            link_column_name=column.column_name,
                            link_column_type=column.column_type,
                            source_column_name=source_col_name,
                            source_prejoin_target_table=prejoin_target,
                            source_prejoin_target_source_system=prejoin_system,
                            target_column_transformation=column.target_column_transformation,
                            target_column_datatype=column.target_column_datatype,
                        )
                    )

            # Process hub references to add source tables for business keys
            for hub_ref in hub_refs:
                for mapping in hub_ref.source_mappings.all():
                    # Handle unified staging column
                    table = mapping.staging_column.source_table
                    source_col_name = mapping.staging_column.physical_name

                    table_key = table.physical_table_name

                    if table_key not in source_table_map:
                        source_table_map[table_key] = {
                            "source_system": table.source_system.name,
                            "stage_name": self.outputs.stage(table).model_name,
                            "rsrc_static": self._source_values(table).static_part.value,
                            "single_batch": self._single_batch(table),
                            "columns": [],
                        }

                    # Target Foreign Hashkey: alias if exists, else hub hashkey name.
                    # Identifies WHICH hub reference this mapping feeds, so links
                    # that reference the same hub more than once round-trip.
                    target_hk = (
                        hub_ref.hub_hashkey_alias_in_link
                        or hub_ref.hub.hub_hashkey_name
                    )

                    # Add column mapping for Business Key
                    # Only add if not already present (to avoid duplicates if used same column multiple times)
                    # For a given source table, we want to list this column usage.
                    # A link's hub business key is frequently fed by a prejoin:
                    # the FK on the source table points at something that is not
                    # the target's business key, so the real key is pulled across.
                    # Record where it came from, otherwise the importer cannot
                    # tell this apart from a plain column of `source_table`.
                    prejoin_target, prejoin_system = _prejoin_origin(
                        mapping.staging_column
                    )

                    source_table_map[table_key]["columns"].append(
                        LinkColumnMapping(
                            link_column_name=mapping.standard_hub_column.column_name,
                            link_column_type="business_key",
                            source_column_name=source_col_name,
                            source_prejoin_target_table=prejoin_target,
                            source_prejoin_target_source_system=prejoin_system,
                            target_foreign_hashkey=target_hk or None,
                            target_column_transformation=mapping.standard_hub_column.target_column_transformation,
                            target_column_datatype=mapping.standard_hub_column.target_column_datatype,
                        )
                    )

                    # Add hashkey mapping

                    # Source Stage Hashkey:
                    # In _get_hashkeys_for_source_table, we use alias if available for the hashkey name
                    # So source stage hashkey matches the target foreign hashkey name
                    stage_hk = target_hk

                    if target_hk:
                        hk_mapping = LinkSourceHashkeyMapping(
                            target_foreign_hashkey=target_hk,
                            source_stage_hashkey=stage_hk,
                        )
                        # Avoid duplicates: check if we initialized it properly above
                        if "hashkey_mappings" not in source_table_map[table_key]:
                            source_table_map[table_key]["hashkey_mappings"] = []

                        existing_mappings = source_table_map[table_key][
                            "hashkey_mappings"
                        ]

                        if hk_mapping not in existing_mappings:
                            existing_mappings.append(hk_mapping)
                            source_table_map[table_key][
                                "hashkey_mappings"
                            ] = existing_mappings

            source_tables = [
                LinkSourceInfo(
                    source_table=table_name,
                    source_system=info["source_system"],
                    stage_name=info["stage_name"],
                    rsrc_static=info.get("rsrc_static"),
                    columns=info["columns"],
                    hashkey_mappings=info.get("hashkey_mappings", []),
                    source_is_single_batch=info.get("single_batch", False),
                )
                for table_name, info in source_table_map.items()
            ]

            column_descriptions: dict[str, ColumnDescriptionDef] = {}
            for column in link.columns.all():
                docs = _column_description(
                    column.description,
                    (
                        mapping.staging_column
                        for mapping in column.source_mappings.all()
                    ),
                )
                if docs is not None:
                    column_descriptions[column.column_name] = docs

            # Build hashkey definition for link
            # Business key columns are used for hashkey composition
            hashkey = HashkeyDefinition(
                hashkey_name=link.link_hashkey_name,
                business_keys=business_key_column_names,
            )

            result.append(
                LinkDefinition(
                    link_name=link.link_physical_name,
                    link_type=link.link_type,
                    group=link.group.group_name if link.group else None,
                    hashkey=hashkey,
                    hub_references=hub_ref_defs,
                    foreign_hashkeys=foreign_hashkeys,
                    business_key_columns=business_key_column_names,
                    payload_columns=list(payload_cols),
                    additional_columns=list(additional_cols),
                    source_tables=source_tables,
                    create_record_tracking_satellite=link.create_record_tracking_satellite,
                    description=link.description or None,
                    column_descriptions=column_descriptions,
                    disable_hwm=link.disable_hwm,
                    union_strategy=link.union_strategy or None,
                    # Single-batch logic only when every source delivers so
                    source_is_single_batch=bool(source_tables)
                    and all(source.source_is_single_batch for source in source_tables),
                    create_effectivity_satellite=link.create_effectivity_satellite,
                    effectivity_options=EffectivitySatelliteOptions(
                        is_active_alias=link.effectivity_is_active_alias or None,
                        disable_hwm=link.effectivity_disable_hwm,
                        additional_columns=list(
                            link.effectivity_additional_columns or []
                        ),
                        # It reads the link's first source's stage
                        source_is_single_batch=bool(
                            source_tables and source_tables[0].source_is_single_batch
                        ),
                    ),
                    output=self.outputs.link(link),
                    effectivity_satellite_output=(
                        self.outputs.effectivity_satellite(
                            link, link.link_physical_name
                        )
                        if link.create_effectivity_satellite
                        else None
                    ),
                    record_tracking_satellite_output=(
                        self.outputs.record_tracking_satellite(
                            link, link.link_physical_name
                        )
                        if link.create_record_tracking_satellite
                        else None
                    ),
                )
            )

        return result

    def _build_snapshot_controls(self) -> list[SnapshotControlDefinition]:
        """
        Build snapshot control definitions from Django models.

        Returns:
            List of SnapshotControlDefinition objects
        """
        from engine.models import SnapshotControlTable

        result = []

        # Get all snapshot control tables for this project
        snapshot_controls = SnapshotControlTable.objects.filter(
            project=self.project
        ).prefetch_related("logic_rules")

        for control in snapshot_controls:
            # Build logic patterns
            logic_patterns = []
            for logic in control.logic_rules.all():
                logic_patterns.append(
                    SnapshotLogicPattern(
                        column_name=logic.snapshot_control_logic_column_name,
                        component=logic.snapshot_component,
                        duration=logic.snapshot_duration,
                        unit=logic.snapshot_unit,
                        forever=logic.snapshot_forever,
                    )
                )

            result.append(
                SnapshotControlDefinition(
                    name=control.name,
                    start_date=control.snapshot_start_date.isoformat(),
                    end_date=(
                        control.snapshot_end_date.isoformat()
                        if control.snapshot_end_date
                        else None
                    ),
                    daily_time=control.daily_snapshot_time.isoformat(),
                    sdts_alias=control.sdts_alias or None,
                    logic_patterns=logic_patterns,
                    v0_output=self.outputs.snapshot_control_v0(control),
                    v1_output=self.outputs.snapshot_control_v1(control),
                )
            )

        return result

    def _build_reference_tables(self) -> list[ReferenceTableDefinition]:
        """
        Build reference table definitions from Django models.

        Returns:
            List of ReferenceTableDefinition objects
        """
        from engine.models import ReferenceTable, Satellite

        result = []

        # Get all reference tables for this project
        reference_tables = (
            ReferenceTable.objects.filter(project=self.project)
            .select_related(
                "reference_hub", "snapshot_control_table", "snapshot_control_logic"
            )
            .prefetch_related(
                "satellite_assignments__reference_satellite",
                "satellite_assignments__include_columns__staging_column__source_column",
                "satellite_assignments__include_columns__staging_column__prejoin_column__source_column",
                "satellite_assignments__exclude_columns__staging_column__source_column",
                "satellite_assignments__exclude_columns__staging_column__prejoin_column__source_column",
                "reference_hub__satellites",
            )
        )

        for ref_table in reference_tables:
            # Build satellite assignments
            satellite_assignments = []
            for assignment in ref_table.satellite_assignments.all():
                # Effective name is the target override or the staging column name.
                include_cols = [
                    col.target_column_name or col.staging_column.physical_name
                    for col in assignment.include_columns.all()
                ]
                exclude_cols = [
                    col.target_column_name or col.staging_column.physical_name
                    for col in assignment.exclude_columns.all()
                ]

                satellite_assignments.append(
                    ReferenceTableSatelliteAssignment(
                        satellite_name=assignment.reference_satellite.satellite_physical_name,
                        model_name=self.outputs.satellite_v1(
                            assignment.reference_satellite
                        ).model_name,
                        include_columns=include_cols,
                        exclude_columns=exclude_cols,
                    )
                )

            # No explicit assignments means all reference satellites of the hub
            if not satellite_assignments:
                ref_sats = sorted(
                    (
                        s
                        for s in ref_table.reference_hub.satellites.all()
                        if s.satellite_type == Satellite.SatelliteType.REFERENCE
                    ),
                    key=lambda s: s.satellite_physical_name,
                )
                satellite_assignments = [
                    ReferenceTableSatelliteAssignment(
                        satellite_name=s.satellite_physical_name,
                        model_name=self.outputs.satellite_v1(s).model_name,
                        include_columns=[],
                        exclude_columns=[],
                    )
                    for s in ref_sats
                ]

            # Snapshot-based: the snapshot control's logic model (v1) and the
            # column that triggers a snapshot, as for PITs
            snapshot_table_name = None
            snapshot_logic_column = None
            if (
                ref_table.historization_type
                == ReferenceTable.HistorizationType.SNAPSHOT_BASED
            ):
                logic = ref_table.snapshot_control_logic
                control = ref_table.snapshot_control_table or (
                    logic.snapshot_control_table if logic else None
                )
                if control is not None:
                    snapshot_table_name = self.outputs.snapshot_control_v1(
                        control
                    ).model_name
                if logic:
                    snapshot_logic_column = logic.snapshot_control_logic_column_name

            result.append(
                ReferenceTableDefinition(
                    table_name=ref_table.reference_table_physical_name,
                    group=ref_table.group.group_name if ref_table.group else None,
                    reference_hub_name=ref_table.reference_hub.hub_physical_name,
                    historization_type=ref_table.historization_type,
                    snapshot_control_table=snapshot_table_name,
                    snapshot_logic_column=snapshot_logic_column,
                    satellites=satellite_assignments,
                    description=ref_table.description or None,
                    output=self.outputs.reference_table(ref_table),
                )
            )

        return result

    def _build_pits(self) -> list[PITDefinition]:
        """
        Build PIT definitions from Django models.

        Returns:
            List of PITDefinition objects
        """
        from engine.models import PIT

        result = []

        # Get all PITs for this project
        pits = (
            PIT.objects.filter(project=self.project)
            .select_related(
                "tracked_hub",
                "tracked_link",
                "snapshot_control_logic",
                "snapshot_control_logic__snapshot_control_table",
            )
            .prefetch_related("satellites")
        )

        for pit in pits:
            # Get tracked entity name and hashkey
            tracked_entity_name = ""
            tracked_hashkey = ""
            if pit.tracked_hub:
                tracked_entity_name = pit.tracked_hub.hub_physical_name
                tracked_hashkey = pit.tracked_hub.hub_hashkey_name or ""
            elif pit.tracked_link:
                tracked_entity_name = pit.tracked_link.link_physical_name
                tracked_hashkey = pit.tracked_link.link_hashkey_name or ""

            # The satellites, and the v0 models the PIT reads
            satellites = list(pit.satellites.all())
            satellite_names = [sat.satellite_physical_name for sat in satellites]
            satellite_models = [
                self.outputs.satellite_v0(sat).model_name for sat in satellites
            ]

            # The snapshot control's logic model (v1), which the PIT reads
            snapshot_control_name = ""
            if (
                pit.snapshot_control_logic
                and pit.snapshot_control_logic.snapshot_control_table
            ):
                snapshot_control_name = self.outputs.snapshot_control_v1(
                    pit.snapshot_control_logic.snapshot_control_table
                ).model_name

            result.append(
                PITDefinition(
                    pit_name=pit.pit_physical_name,
                    group=pit.group.group_name if pit.group else None,
                    tracked_entity_type=pit.tracked_entity_type,
                    tracked_entity_name=tracked_entity_name,
                    tracked_hashkey=tracked_hashkey,
                    satellites=satellite_names,
                    satellite_models=satellite_models,
                    snapshot_control_name=snapshot_control_name,
                    snapshot_logic_column=pit.snapshot_control_logic.snapshot_control_logic_column_name,
                    dimension_key_column=pit.dimension_key_column_name,
                    pit_type=pit.pit_type,
                    use_snapshot_optimization=pit.use_snapshot_optimization,
                    custom_record_source=pit.custom_record_source or None,
                    include_business_objects_before_appearance=pit.include_business_objects_before_appearance,
                    output=self.outputs.pit(pit),
                )
            )

        return result
