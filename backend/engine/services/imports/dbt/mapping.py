"""
Mapping a datavault4dbt project to TurboVault entities (spec §7).

Works from the interpreted calls of ``index.ProjectIndex``:

- stages become source tables (a dbt source) or pre-stages (a model the
  stage reads), with their record source, load date, stage options, missing,
  derived and prejoined columns (§7.1-7.3);
- Hubs, Links and Satellites map their columns to the stage columns they
  load, which are the table's source, derived or prejoined columns (§7.4,
  7.5). Effectivity and record-tracking Satellites become their Hub's or
  Link's.

Names are kept (D3): a model's name is stored only where it differs from
what the project's naming patterns give (D22). Whatever can't be mapped is
reported on its model and left out; its entity is recorded as skipped, so
``replace_all`` doesn't delete the project's copy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from engine.services.export.model_outputs import (
    apply_pattern,
    dbt_source_name,
    entity_base_name,
    satellite_pattern,
)
from engine.services.imports.dbt.artifacts import DbtArtifacts
from engine.services.imports.dbt.datavault4dbt import (
    as_bool,
    as_list,
    normalize_derived_columns,
    normalize_hashdiff,
    normalize_hashed_columns,
    normalize_payload,
    normalize_prejoins,
    normalize_source_models,
    stage_source,
)
from engine.services.imports.dbt.extract import is_unresolved
from engine.services.imports.dbt.index import DbtModel, ProjectIndex
from engine.services.imports.domain import (
    CLEAR,
    DDerivedColumn,
    DHub,
    DHubColumn,
    DHubSourceMapping,
    DLink,
    DLinkColumn,
    DLinkHubReference,
    DLinkHubSourceMapping,
    DLinkSourceMapping,
    DModelOutput,
    DomainModel,
    DPrejoin,
    DPrejoinExtractionColumn,
    DSatellite,
    DSatelliteColumn,
    DSkipped,
    DSourceColumn,
    DSourceSystem,
    DSourceTable,
)
from engine.services.imports.errors import Code, make_issue
from engine.services.imports.types import DbtSource, EntityRef, Issue
from engine.services.runtime_config import EngineRuntimeConfig
from engine.services.source_values import DEFAULT_LOAD_DATE, fill_placeholders

# Satellite macros and the TurboVault type they map to.
_SATELLITE_TYPES = {
    "sat_v0": "standard",
    "ma_sat_v0": "multi_active",
    "nh_sat": "non_historized",
    "ref_sat_v0": "reference",
}
# v1 macros and the parameter naming their v0 model.
_V1_MACROS = {"sat_v1": "sat_v0", "ma_sat_v1": "sat_v0", "ref_sat_v1": "ref_sat_v0"}

_PLACEHOLDER = re.compile(r"\[\[\s*(\w+)\s*\]\]")


def map_project(
    artifacts: DbtArtifacts,
    source: DbtSource,
    runtime_config: EngineRuntimeConfig | None = None,
) -> tuple[DomainModel, list[Issue]]:
    """Map the project's models; returns the domain model and its issues."""
    mapper = _Mapper(artifacts, source, runtime_config or EngineRuntimeConfig())
    return mapper.run()


def invert_pattern(pattern: str, name: str) -> dict[str, str] | None:
    """The placeholder values for which ``pattern`` gives ``name``, or None.

    ``invert_pattern("[[ satellite_name ]]_v0", "customer_s_v0")`` is
    ``{"satellite_name": "customer_s"}``.
    """
    parts: list[str] = []
    names: list[str] = []
    position = 0
    for match in _PLACEHOLDER.finditer(pattern):
        parts.append(re.escape(pattern[position : match.start()]))
        key = match.group(1)
        if key in names:
            parts.append(f"(?P={key})")
        else:
            names.append(key)
            parts.append(f"(?P<{key}>.+)")
        position = match.end()
    parts.append(re.escape(pattern[position:]))
    found = re.fullmatch("".join(parts), name)
    if found is None:
        return None
    return {key: found.group(key) for key in names}


# ---------------------------------------------------------------------------
# What the mapping keeps about a stage
# ---------------------------------------------------------------------------


@dataclass
class _Stage:
    model: DbtModel
    system: DSourceSystem
    table: DSourceTable
    # The stage's hash keys and hash diffs: name -> stage columns / spec.
    hashkeys: dict[str, list[str]] = field(default_factory=dict)
    hashdiffs: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Columns a prejoin brings in: lowercased name -> the name as written.
    prejoined: dict[str, str] = field(default_factory=dict)

    @property
    def identifier(self) -> str:
        return self.table.identifier

    def hashkey(self, name: str) -> list[str] | None:
        if name in self.hashkeys:
            return self.hashkeys[name]
        lowered = name.lower()
        return next(
            (cols for key, cols in self.hashkeys.items() if key.lower() == lowered),
            None,
        )


@dataclass
class _HubInfo:
    hub: DHub
    model: DbtModel
    # The stages it loads from, with the stage hash key each loads.
    stages: dict[str, str] = field(default_factory=dict)

    @property
    def business_keys(self) -> list[DHubColumn]:
        kinds = ("business_key", "reference_key")
        return [column for column in self.hub.columns if column.column_type in kinds]


@dataclass
class _LinkInfo:
    link: DLink
    model: DbtModel
    stages: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The mapper
# ---------------------------------------------------------------------------


class _Mapper:
    def __init__(
        self,
        artifacts: DbtArtifacts,
        source: DbtSource,
        runtime_config: EngineRuntimeConfig,
    ) -> None:
        self.artifacts = artifacts
        self.source = source
        self.config = runtime_config
        self.index = ProjectIndex(artifacts)
        self.domain = DomainModel()
        self.issues: list[Issue] = []
        self._systems_by_location: dict[tuple[str, str | None], DSourceSystem] = {}
        self._target_database: str | None = None
        self.stages: dict[str, _Stage] = {}
        # Tables the import added columns to without knowing them.
        self._unknown_columns: dict[str, list[str]] = {}
        self.hubs: dict[str, _HubInfo] = {}
        self.links: dict[str, _LinkInfo] = {}
        # Tables a model reads with single-batch logic.
        self._single_batch_tables: set[str] = set()
        # Models the mapping used (for the "not mapped" report).
        self._mapped: set[str] = set()
        # What was left out, for the entities depending on it: stage names,
        # and the hash keys of Hubs and Links (lowercased) with their names.
        self._skipped_stages: set[str] = set()
        self._skipped_keys: dict[str, str] = {}
        self._warned: set[tuple[str, ...]] = set()

    # -- entry --------------------------------------------------------------

    def run(self) -> tuple[DomainModel, list[Issue]]:
        self.index.capture()
        self.issues.extend(self.index.issues)
        self._target_database = self.index.target_database()
        for model in sorted(self.index.models_with("stage"), key=self._stage_order):
            self._map_stage(model)
        for model in self.index.models_with("hub", "ref_hub"):
            self._map_hub(model)
        for model in self.index.models_with("link", "nh_link"):
            self._map_link(model)
        v1_by_v0 = self._v1_models()
        for model in self.index.models_with(*_SATELLITE_TYPES):
            self._map_satellite(model, v1_by_v0)
        for model in self.index.models_with("eff_sat_v0"):
            self._map_effectivity_satellite(model)
        for model in self.index.models_with("rec_track_sat"):
            self._map_record_tracking_satellite(model)
        self._finish_tables()
        self._report_unmapped()
        return self.domain, self.issues

    # -- issues ---------------------------------------------------------------

    def _issue(
        self,
        model: DbtModel | None,
        severity: str,
        code: str,
        message: str,
        *,
        parameter: str | None = None,
        entity: EntityRef | None = None,
        suggestion: str | None = None,
    ) -> None:
        self.issues.append(
            make_issue(
                severity=severity,  # type: ignore[arg-type]
                code=code,
                stage="parse",
                message=message,
                location=model.location(parameter) if model else None,
                entity=entity,
                suggestion=suggestion,
            )
        )

    def _skip(
        self, entity_type: str, name: str, reason: str, *, hashkey: str | None = None
    ) -> None:
        self.domain.skipped[(entity_type, name)] = DSkipped(
            entity_type=entity_type,
            name=name,
            reason=reason,  # type: ignore[arg-type]
        )
        if hashkey:
            self._skipped_keys.setdefault(hashkey.lower(), name)

    def _depends_on_skipped(
        self, model: DbtModel, what: str, *, parameter: str | None = None
    ) -> None:
        """Note an entity left out because one it needs is left out."""
        self._issue(
            model,
            "warning",
            Code.ENTITY_DEPENDS_ON_SKIPPED,
            f"'{model.name}' is left out: it needs {what}, which is left out "
            "(see the error there)",
            parameter=parameter,
        )

    def _description(self, text: Any) -> str | None:
        if not self.source.import_descriptions:
            return None
        return str(text or "").strip() or None

    # -- sources --------------------------------------------------------------

    def _system_for(
        self, node: dict[str, Any], *, name: str | None = None
    ) -> DSourceSystem:
        """The source system of a dbt source (or, with ``name``, of a model).

        Systems are identified by where they live, like TurboVault's: dbt
        sources sharing a schema become one system, named after the first.
        """
        schema = str(node.get("schema") or "")
        if "unrendered_database" in node:
            database = node.get("unrendered_database") or None
        else:
            database = node.get("database") or None
            if database == self._target_database:
                database = None
        system_name = name or str(node.get("source_name") or schema)
        key = (schema.lower(), str(database).lower() if database else None)
        system = self._systems_by_location.get(key)
        if system is None:
            system = DSourceSystem(
                name=system_name,
                schema_name=schema,
                database_name=database,
                description=(
                    self._description(node.get("source_description"))
                    if name is None
                    else None
                ),
                # dbt sets these on stages only: tables inherit nothing else.
                include_source_columns=CLEAR,
                enable_ghost_records=CLEAR,
                delivery_method=CLEAR,
            )
            self._systems_by_location[key] = system
            self.domain.source_systems[system.name] = system
        elif (
            name is None
            and system.name != system_name
            and ("schema", system.name, system_name) not in self._warned
        ):
            self._warned.add(("schema", system.name, system_name))
            self._issue(
                None,
                "warning",
                Code.DBT_PARAMETER_UNSUPPORTED,
                f"The dbt sources '{system.name}' and '{system_name}' read the same "
                f"schema '{schema}': TurboVault keeps one source system, so "
                f"'{system_name}' tables are generated as source('{system.name}', ...)",
            )
        return system

    def _columns(
        self, unique_id: str, yaml_columns: dict[str, Any]
    ) -> dict[str, DSourceColumn]:
        """A node's columns: the YAML's names and types, the catalog's for the rest.

        Ordered like the catalog (the warehouse's order) when there is one.
        """
        catalog = self.artifacts.catalog_columns(unique_id) or {}
        described: dict[str, DSourceColumn] = {}
        for key, column in yaml_columns.items():
            if not isinstance(column, dict):
                continue
            name = str(column.get("name") or key)
            described[name.lower()] = DSourceColumn(
                name=name,
                datatype=str(column.get("data_type") or "") or None,
                description=self._description(column.get("description")),
                is_missing=False,
            )
        result: dict[str, DSourceColumn] = {}
        for catalog_name, catalog_type in catalog.items():
            key = catalog_name.lower()
            column = described.pop(key, None)
            if column is None:
                column = DSourceColumn(
                    name=catalog_name, datatype=catalog_type or None, is_missing=False
                )
            elif column.datatype is None:
                column.datatype = catalog_type or None
            result[key] = column
        result.update(described)
        return result

    def _source_table(self, node: dict[str, Any]) -> tuple[DSourceSystem, DSourceTable]:
        """The source table of a dbt source table, created on first use."""
        system = self._system_for(node)
        physical = str(node.get("name") or "")
        identifier = f"{system.name}|{physical}"
        table = system.tables.get(identifier)
        if table is None:
            table = DSourceTable(
                identifier=identifier,
                physical_name=physical,
                description=self._description(node.get("description")),
                table_type="physical",
                columns=self._columns(node["unique_id"], node.get("columns") or {}),
            )
            system.tables[identifier] = table
            if node.get("identifier") and node["identifier"] != physical:
                self._issue(
                    None,
                    "warning",
                    Code.DBT_PARAMETER_UNSUPPORTED,
                    f"Source table '{node.get('source_name')}.{physical}' reads the "
                    f"table '{node['identifier']}': TurboVault's sources.yml names "
                    "tables by their name only, so add the identifier back by hand",
                    entity=EntityRef(type="source_table", name=physical),
                )
        return system, table

    def _stage_order(self, model: DbtModel) -> tuple[int, str]:
        """Stages in the order they get their tables.

        Several stages may read one pre-stage model; the one named like it
        (``stg__crm__orders`` for ``pstg__crm__orders``) comes first and gets
        its table, the others get pre-stages named after themselves.
        """
        read = stage_source(model.call.params.get("source_model"))
        if read is not None and read[0] == "model":
            prestage = invert_pattern(self.config.prestage_naming, read[1]) or {}
            stage = invert_pattern(self.config.stage_naming, model.name) or {}
            table = prestage.get("source_table") or read[1]
            if (stage.get("source_table") or model.name).lower() != table.lower():
                return 1, model.unique_id
        return 0, model.unique_id

    def _prestage_table(
        self, model: DbtModel, node: dict[str, Any], *, own_table: bool = False
    ) -> tuple[DSourceSystem, DSourceTable]:
        """The pre-stage a stage reads: a model, seed or snapshot of the project.

        It belongs to the source system of the sources it reads, else to one
        named after its folder. Its model stays in the dbt project (D9).
        ``own_table``: another stage reads the model too, and TurboVault has
        one stage per table, so this stage gets a pre-stage of its own, named
        after the stage, reading the same model.
        """
        upstream = self.index.upstream_sources(node["unique_id"])
        if upstream:
            system = self._system_for(upstream[0])
        else:
            folder = self.index.folder_of(node).rstrip("/").split("/")[-1]
            system = self._system_for(node, name=folder or str(node.get("schema")))
        model_name = str(node.get("name") or "")
        # The table's name: what the pre-stage pattern makes of the model's
        # name, if it fits, else the model's name.
        values = invert_pattern(self.config.prestage_naming, model_name) or {}
        physical = model_name
        if values.get("source_system", dbt_source_name(system.name)) == dbt_source_name(
            system.name
        ) and values.get("source_table"):
            physical = values["source_table"]
        if own_table:
            stage_values = invert_pattern(self.config.stage_naming, model.name) or {}
            physical = stage_values.get("source_table") or model.name
            # A name another table has: the stage's own, made unique.
            candidates = [physical, model.name]
            candidates += [f"{model.name}_{n}" for n in range(2, 100)]
            physical = next(
                name
                for name in candidates
                if f"{system.name}|{name}" not in system.tables
            )
        identifier = f"{system.name}|{physical}"
        table = system.tables.get(identifier)
        if table is None:
            table = DSourceTable(
                identifier=identifier,
                physical_name=physical,
                description=self._description(node.get("description")),
                table_type="prestage",
                columns=self._columns(node["unique_id"], node.get("columns") or {}),
                outputs={},
            )
            derived = apply_pattern(
                self.config.prestage_naming,
                source_system=dbt_source_name(system.name),
                source_table=physical.lower(),
            )
            if derived != model_name:
                table.outputs["prestage"] = DModelOutput(
                    kind="prestage", model_name=model_name
                )
            system.tables[identifier] = table
            self._mapped.add(node["unique_id"])
            self._issue(
                model,
                "warning",
                Code.DBT_PRESTAGE_MAINTAINED_IN_DBT,
                f"Stage '{model.name}' reads '{model_name}', which becomes a "
                "pre-stage: its model stays in the dbt project, so generate the "
                "project into this dbt project",
                parameter="source_model",
                entity=EntityRef(type="source_table", name=physical),
            )
        return system, table

    # -- stages -----------------------------------------------------------------

    def _map_stage(self, model: DbtModel) -> None:
        call = model.call
        assert call is not None
        read = stage_source(call.params.get("source_model"))
        if read is None:
            self._issue(
                model,
                "error",
                Code.DBT_VALUE_INVALID,
                f"Stage '{model.name}': source_model names no source or model",
                parameter="source_model",
            )
            self._skipped_stages.add(model.name)
            return
        kind, target = read
        if kind == "source":
            node = self.index.source(*target)
            if node is None:
                self._issue(
                    model,
                    "error",
                    Code.DBT_REFERENCE_UNRESOLVED,
                    f"Stage '{model.name}' reads source('{target[0]}', '{target[1]}'), "
                    "which the manifest doesn't define",
                    parameter="source_model",
                )
                self._skipped_stages.add(model.name)
                return
            system, table = self._source_table(node)
        else:
            node = self.index.referable(target)
            if node is None:
                self._issue(
                    model,
                    "error",
                    Code.DBT_REFERENCE_UNRESOLVED,
                    f"Stage '{model.name}' reads '{target}', which the manifest "
                    "doesn't define",
                    parameter="source_model",
                )
                self._skipped_stages.add(model.name)
                return
            system, table = self._prestage_table(model, node)
            if any(stage.table is table for stage in self.stages.values()):
                system, table = self._prestage_table(model, node, own_table=True)

        if any(stage.table is table for stage in self.stages.values()):
            self._issue(
                model,
                "error",
                Code.DBT_PARAMETER_UNSUPPORTED,
                f"Stage '{model.name}' reads the same source table as another "
                "stage; TurboVault has one stage per source table, so it is left "
                "out",
                parameter="source_model",
                suggestion=(
                    "Read the source through a model of the dbt project (a "
                    "pre-stage): several stages may read one pre-stage."
                ),
            )
            self._skipped_stages.add(model.name)
            return

        stage = _Stage(model=model, system=system, table=table)
        hashkeys, hashdiffs = normalize_hashed_columns(
            call.params.get("hashed_columns")
        )
        stage.hashkeys, stage.hashdiffs = hashkeys, hashdiffs
        for name, spec in hashdiffs.items():
            if spec.get("exclude_columns"):
                self._issue(
                    model,
                    "warning",
                    Code.DBT_PARAMETER_UNSUPPORTED,
                    f"Stage '{model.name}': hash diff '{name}' lists the columns "
                    "to exclude (exclude_columns); TurboVault hashes the "
                    "Satellite's payload instead",
                    parameter="hashed_columns",
                )

        self._stage_values(stage)
        self._stage_options(stage)
        self._derived_columns(stage)
        self._prejoins(stage)
        self.stages[model.name] = stage
        self._mapped.add(model.unique_id)

        if table.outputs is None:
            table.outputs = {}
        derived = apply_pattern(
            self.config.stage_naming,
            source_system=dbt_source_name(system.name),
            source_table=table.physical_name.lower(),
        )
        if derived != model.name:
            table.outputs["stage"] = DModelOutput(kind="stage", model_name=model.name)

    def _plain_value(self, model: DbtModel, parameter: str) -> str | None:
        """A text parameter of the model's call, or None (reported if unresolved)."""
        value = model.call.params.get(parameter) if model.call else None
        if value is None:
            return None
        if is_unresolved(value) or isinstance(value, (dict, list)):
            if not is_unresolved(value):
                self._issue(
                    model,
                    "warning",
                    Code.DBT_VALUE_INVALID,
                    f"{model.name}: '{parameter}' isn't a single value; it is "
                    "not imported",
                    parameter=parameter,
                )
            return None
        return str(value)

    def _stage_values(self, stage: _Stage) -> None:
        """Record source and load date, set on the table (hoisted later)."""
        table = stage.table
        rsrc = self._plain_value(stage.model, "rsrc")
        ldts = self._plain_value(stage.model, "ldts")
        table.record_source_value = rsrc.strip() if rsrc else None
        table.load_date_value = ldts.strip() if ldts else None

    def _stage_options(self, stage: _Stage) -> None:
        params = stage.model.call.params
        table = stage.table
        for option, default in (
            ("include_source_columns", self.config.include_source_columns),
            ("enable_ghost_records", self.config.enable_ghost_records),
        ):
            value = as_bool(params.get(option), True)
            setattr(table, option, CLEAR if value == default else value)
        sequence = self._plain_value(stage.model, "sequence")
        table.sequence_column = sequence or CLEAR
        table.delivery_method = CLEAR

        missing = params.get("missing_columns")
        if isinstance(missing, dict):
            for name, datatype in missing.items():
                key = str(name).lower()
                column = table.columns.get(key)
                if column is None:
                    column = DSourceColumn(name=str(name))
                    table.columns[key] = column
                column.is_missing = True
                column.datatype = str(datatype or "") or column.datatype
        elif missing:
            self._issue(
                stage.model,
                "warning",
                Code.DBT_VALUE_INVALID,
                f"Stage '{stage.model.name}': missing_columns isn't a mapping of "
                "columns to data types; it is not imported",
                parameter="missing_columns",
            )

    def _derived_columns(self, stage: _Stage) -> None:
        table = stage.table
        table.derived_columns = {}
        derived = normalize_derived_columns(
            stage.model.call.params.get("derived_columns")
        )
        for name, spec in derived.items():
            value = spec.get("value")
            if value is None or is_unresolved(value) or isinstance(value, (dict, list)):
                self._issue(
                    stage.model,
                    "warning",
                    Code.DBT_VALUE_INVALID,
                    f"Stage '{stage.model.name}': derived column '{name}' has no "
                    "single value; it is not imported",
                    parameter="derived_columns",
                )
                continue
            table.derived_columns[name.lower()] = DDerivedColumn(
                name=name,
                expression=str(value),
                datatype=str(spec.get("datatype") or "") or None,
            )

    def _prejoins(self, stage: _Stage) -> None:
        entries = normalize_prejoins(stage.model.call.params.get("prejoined_columns"))
        for entry in entries:
            target = self._prejoin_target(stage, entry)
            if target is None:
                continue
            if str(entry.get("join_type") or "left").lower() != "left":
                self._issue(
                    stage.model,
                    "warning",
                    Code.DBT_PARAMETER_UNSUPPORTED,
                    f"Stage '{stage.model.name}': a prejoin uses a "
                    f"{entry['join_type']} join; TurboVault prejoins are left joins",
                    parameter="prejoined_columns",
                )
            columns = []
            for column, alias in zip(
                entry["extract_columns"], entry["aliases"], strict=False
            ):
                columns.append(
                    DPrejoinExtractionColumn(
                        source_column_name=self._column_of(target, column),
                        alias=alias if alias != column else None,
                    )
                )
                stage.prejoined[alias.lower()] = alias
            self.domain.prejoins.append(
                DPrejoin(
                    source_table_identifier=stage.identifier,
                    target_table_identifier=target.identifier,
                    operator=str(entry.get("operator") or "AND").upper(),
                    source_join_columns=[
                        self._column_of(stage.table, c, stage=stage)
                        for c in entry["this_column_name"]
                    ],
                    target_join_columns=[
                        self._column_of(target, c) for c in entry["ref_column_name"]
                    ],
                    extraction_columns=columns,
                )
            )

    def _prejoin_target(
        self, stage: _Stage, entry: dict[str, Any]
    ) -> DSourceTable | None:
        model = stage.model
        if entry.get("ref_model"):
            name = entry["ref_model"]
            name = name.get("__ref__") if isinstance(name, dict) else str(name)
            node = self.index.referable(str(name))
            if node is None:
                self._issue(
                    model,
                    "error",
                    Code.DBT_REFERENCE_UNRESOLVED,
                    f"Stage '{model.name}' prejoins '{name}', which the manifest "
                    "doesn't define; the prejoin is left out",
                    parameter="prejoined_columns",
                )
                return None
            return self._prestage_table(model, node)[1]
        source_name, table_name = entry.get("src_name"), entry.get("src_table")
        node = self.index.source(str(source_name), str(table_name))
        if node is None:
            self._issue(
                model,
                "error",
                Code.DBT_REFERENCE_UNRESOLVED,
                f"Stage '{model.name}' prejoins source('{source_name}', "
                f"'{table_name}'), which the manifest doesn't define; the prejoin "
                "is left out",
                parameter="prejoined_columns",
            )
            return None
        return self._source_table(node)[1]

    # -- columns ----------------------------------------------------------------

    def _column_of(
        self, table: DSourceTable, column: str, *, stage: _Stage | None = None
    ) -> str:
        """A column of a table in the table's spelling; added when unknown.

        With ``stage``, derived and prejoined columns of the stage count too.
        """
        key = str(column).lower()
        if stage is not None:
            if table.derived_columns and key in table.derived_columns:
                return table.derived_columns[key].name
            if key in stage.prejoined:
                return stage.prejoined[key]
        known = table.columns.get(key)
        if known is not None:
            return known.name
        table.columns[key] = DSourceColumn(name=str(column), is_missing=False)
        self._unknown_columns.setdefault(table.identifier, []).append(str(column))
        return str(column)

    def _stage_column(self, stage: _Stage, column: str) -> str:
        return self._column_of(stage.table, column, stage=stage)

    # -- Hubs -------------------------------------------------------------------

    def _skip_reason(self, sources: list[dict[str, Any]]) -> str:
        """Why an entity none of whose stages resolved is left out."""
        if sources and all(s["name"] in self._skipped_stages for s in sources):
            return "depends_on_skipped"
        return "missing_source_table"

    def _resolve_stages(
        self, model: DbtModel, sources: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], _Stage]]:
        """The stages of an entity's source_models; unknown ones are reported."""
        resolved = []
        for source in sources:
            stage = self.stages.get(source["name"])
            if stage is None and source["name"] in self._skipped_stages:
                self._depends_on_skipped(
                    model, f"the stage '{source['name']}'", parameter="source_models"
                )
                continue
            if stage is None:
                self._issue(
                    model,
                    "error",
                    Code.DBT_REFERENCE_UNRESOLVED,
                    f"{model.name} loads from '{source['name']}', which isn't an "
                    "imported stage; that source is left out",
                    parameter="source_models",
                )
                continue
            resolved.append((source, stage))
        return resolved

    def _static_part(
        self, model: DbtModel, stage: _Stage, source: dict[str, Any]
    ) -> None:
        """A source's rsrc_static: the static part of its table's record source."""
        patterns = [str(p) for p in source.get("rsrc_static") or [] if p is not None]
        if not patterns:
            return
        if len(patterns) > 1:
            self._issue(
                model,
                "warning",
                Code.DBT_PARAMETER_UNSUPPORTED,
                f"{model.name}: '{source['name']}' has several rsrc_static patterns; "
                f"TurboVault keeps one ('{patterns[0]}')",
                parameter="source_models",
            )
        current = stage.table.static_part_of_record_source
        if current and current != patterns[0]:
            self._issue(
                model,
                "warning",
                Code.DBT_PARAMETER_UNSUPPORTED,
                f"{model.name}: rsrc_static '{patterns[0]}' of '{source['name']}' "
                f"differs from another model's ('{current}'); TurboVault keeps one "
                "per table",
                parameter="source_models",
            )
            return
        stage.table.static_part_of_record_source = patterns[0]

    def _map_hub(self, model: DbtModel) -> None:
        call = model.call
        assert call is not None
        reference = call.macro == "ref_hub"
        params = call.params
        key_names = [
            str(k)
            for k in as_list(params.get("ref_keys" if reference else "business_keys"))
        ]
        hashkey = None if reference else self._plain_value(model, "hashkey")
        if not key_names or (not reference and not hashkey):
            self._issue(
                model,
                "error",
                Code.DBT_VALUE_INVALID,
                f"Hub '{model.name}' has no "
                + ("ref_keys" if reference else "hashkey or business_keys"),
                parameter="ref_keys" if reference else "business_keys",
            )
            self._skip("hub", model.name, "invalid_configuration", hashkey=hashkey)
            return
        defaults = (
            {"ref_keys": key_names}
            if reference
            else {"hk_column": hashkey, "bk_columns": key_names}
        )
        requested = normalize_source_models(params.get("source_models"), defaults)
        sources = self._resolve_stages(model, requested)
        if not sources:
            self._skip("hub", model.name, self._skip_reason(requested), hashkey=hashkey)
            return

        column_type = "reference_key" if reference else "business_key"
        columns = [
            DHubColumn(name=name, column_type=column_type, sort_order=i + 1)
            for i, name in enumerate(key_names)
        ]
        info = _HubInfo(
            hub=DHub(
                physical_name=model.name,
                hub_type="reference" if reference else "standard",
                hashkey_name=hashkey,
                description=self._description(model.description),
                disable_hwm=as_bool(params.get("disable_hwm"), False),
                columns=columns,
            ),
            model=model,
        )
        for position, (source, stage) in enumerate(sources):
            stage_keys = [
                str(c)
                for c in as_list(source.get("ref_keys" if reference else "bk_columns"))
            ] or key_names
            if len(stage_keys) != len(key_names):
                self._issue(
                    model,
                    "error",
                    Code.DBT_VALUE_INVALID,
                    f"Hub '{model.name}': '{source['name']}' names "
                    f"{len(stage_keys)} key columns for {len(key_names)} keys; "
                    "that source is left out",
                    parameter="source_models",
                )
                continue
            role = None
            if not reference:
                role = str(source.get("hk_column") or hashkey)
                self._check_hash_inputs(model, stage, role, stage_keys)
            for column, stage_key in zip(columns, stage_keys, strict=True):
                column.source_mappings.append(
                    DHubSourceMapping(
                        source_table_identifier=stage.identifier,
                        source_column_name=self._stage_column(stage, stage_key),
                        is_primary_source=position == 0,
                        stage_hashkey_name=(
                            role if role and role != hashkey else CLEAR
                        ),
                    )
                )
            info.stages[stage.model.name] = role or ""
            self._static_part(model, stage, source)

        for i, name in enumerate(as_list(params.get("additional_columns"))):
            column = DHubColumn(
                name=str(name), column_type="additional_column", sort_order=i + 1
            )
            for _source, stage in sources:
                column.source_mappings.append(
                    DHubSourceMapping(
                        source_table_identifier=stage.identifier,
                        source_column_name=self._stage_column(stage, str(name)),
                    )
                )
            columns.append(column)

        if not info.stages:
            self._skip("hub", model.name, "missing_source_table", hashkey=hashkey)
            return
        info.hub.effectivity_is_active_alias = CLEAR
        info.hub.effectivity_disable_hwm = False
        info.hub.effectivity_additional_columns = CLEAR
        info.hub.outputs = {}
        self.hubs[model.name] = info
        self.domain.hubs[model.name] = info.hub
        self._mapped.add(model.unique_id)

    def _check_hash_inputs(
        self, model: DbtModel, stage: _Stage, hashkey: str, columns: list[str]
    ) -> None:
        """Note a stage hash key computed from other columns than the keys mapped."""
        hashed = stage.hashkey(hashkey)
        if hashed is None:
            self._issue(
                model,
                "warning",
                Code.DBT_HASH_INPUTS_DIFFER,
                f"{model.name}: stage '{stage.model.name}' doesn't compute "
                f"'{hashkey}'; TurboVault computes it from {columns}",
                parameter="source_models",
            )
        elif [c.lower() for c in hashed] != [c.lower() for c in columns]:
            self._issue(
                model,
                "warning",
                Code.DBT_HASH_INPUTS_DIFFER,
                f"{model.name}: stage '{stage.model.name}' computes '{hashkey}' "
                f"from {hashed}; TurboVault computes it from the mapped key "
                f"columns {columns}",
                parameter="source_models",
            )

    # -- Links ------------------------------------------------------------------

    def _map_link(self, model: DbtModel) -> None:
        call = model.call
        assert call is not None
        params = call.params
        non_historized = call.macro == "nh_link"
        link_hashkey = self._plain_value(model, "link_hashkey")
        foreign = [str(fk) for fk in as_list(params.get("foreign_hashkeys"))]
        if not link_hashkey or not foreign:
            self._issue(
                model,
                "error",
                Code.DBT_VALUE_INVALID,
                f"Link '{model.name}' has no link_hashkey or foreign_hashkeys",
                parameter="foreign_hashkeys",
            )
            self._skip(
                "link", model.name, "invalid_configuration", hashkey=link_hashkey
            )
            return
        payload = [str(c) for c in as_list(params.get("payload"))]
        defaults = {
            "fk_columns": foreign,
            "link_hk": link_hashkey,
            "payload": payload or None,
        }
        requested = normalize_source_models(params.get("source_models"), defaults)
        sources = self._resolve_stages(model, requested)
        if not sources:
            self._skip(
                "link", model.name, self._skip_reason(requested), hashkey=link_hashkey
            )
            return

        link = DLink(
            physical_name=model.name,
            link_type="non_historized" if non_historized else "standard",
            hashkey_name=link_hashkey,
            description=self._description(model.description),
            create_effectivity_satellite=False,
            disable_hwm=as_bool(params.get("disable_hwm"), False),
            union_strategy=(
                self._plain_value(model, "union_strategy") or CLEAR
                if non_historized
                else CLEAR
            ),
            effectivity_is_active_alias=CLEAR,
            effectivity_disable_hwm=False,
            effectivity_additional_columns=CLEAR,
            outputs={},
        )
        stages = [stage for _source, stage in sources]
        hubs: list[_HubInfo] = []
        # Positions in foreign_hashkeys that reference a Hub. The others are
        # plain columns the link hash key hashes: dependent child keys, which
        # datavault4dbt lists among the foreign hash keys.
        hub_positions: list[int] = []
        key_columns: list[tuple[int, str]] = []
        for position, fk in enumerate(foreign):
            if self._is_key_column(fk, stages, link_hashkey):
                key_columns.append((position, fk))
                continue
            match = self._link_hub(model, fk, stages, hubs)
            if match is None:
                reason = (
                    "depends_on_skipped"
                    if fk.lower() in self._skipped_keys
                    else "missing_reference"
                )
                self._skip("link", model.name, reason, hashkey=link_hashkey)
                return
            hub_info, alias = match
            hubs.append(hub_info)
            hub_positions.append(position)
            link.hub_references.append(
                DLinkHubReference(
                    hub_physical_name=hub_info.hub.physical_name,
                    hub_hashkey_alias_in_link=alias,
                    sort_order=len(hubs),
                )
            )

        # Dependent child keys by lowercased name: (name, stage -> stage column)
        dependent: dict[str, tuple[str, dict[str, str]]] = {
            name.lower(): (name, {}) for _position, name in key_columns
        }
        hashed_only: list[str] = []
        for source, stage in sources:
            all_fk_columns = [
                str(c) for c in as_list(source.get("fk_columns"))
            ] or foreign
            if len(all_fk_columns) != len(foreign):
                self._issue(
                    model,
                    "error",
                    Code.DBT_VALUE_INVALID,
                    f"Link '{model.name}': '{source['name']}' names "
                    f"{len(all_fk_columns)} foreign hash keys for {len(foreign)}; "
                    "that source is left out",
                    parameter="source_models",
                )
                continue
            fk_columns = [all_fk_columns[position] for position in hub_positions]
            hub_columns: list[str] = []
            for index, (hub_info, fk_column) in enumerate(
                zip(hubs, fk_columns, strict=True)
            ):
                keys = hub_info.business_keys
                hashed = stage.hashkey(fk_column)
                if hashed is None or len(hashed) != len(keys):
                    self._issue(
                        model,
                        "error",
                        Code.DBT_HASH_INPUTS_DIFFER,
                        f"Link '{model.name}': stage '{stage.model.name}' "
                        + (
                            f"doesn't compute '{fk_column}'"
                            if hashed is None
                            else f"computes '{fk_column}' from {len(hashed)} columns, "
                            f"but hub '{hub_info.hub.physical_name}' has {len(keys)} "
                            "business keys"
                        )
                        + "; the hub's keys from this stage are left out",
                        parameter="foreign_hashkeys",
                    )
                    continue
                for key, column in zip(keys, hashed, strict=True):
                    stage_column = self._stage_column(stage, column)
                    hub_columns.append(stage_column)
                    link.hub_source_mappings.append(
                        DLinkHubSourceMapping(
                            link_hub_ref_index=index,
                            hub_column_name=key.name,
                            source_table_identifier=stage.identifier,
                            source_column_name=stage_column,
                        )
                    )
            link_hk = str(source.get("link_hk") or link_hashkey)
            if link_hk != link_hashkey:
                self._issue(
                    model,
                    "warning",
                    Code.DBT_PARAMETER_UNSUPPORTED,
                    f"Link '{model.name}': '{source['name']}' loads the link hash key "
                    f"from '{link_hk}'; TurboVault uses '{link_hashkey}' for every "
                    "source",
                    parameter="source_models",
                )
            # The dependent child keys this stage loads: those foreign_hashkeys
            # lists, by its own column names, and any other column the link
            # hash key hashes beyond the hubs' keys.
            used = [c.lower() for c in hub_columns]
            for position, name in key_columns:
                column = self._stage_column(stage, all_fk_columns[position])
                dependent[name.lower()][1][stage.model.name] = column
                used.append(column.lower())
            for column in stage.hashkey(link_hk) or []:
                if column.lower() in used:
                    used.remove(column.lower())
                    continue
                if column.lower() not in dependent:
                    dependent[column.lower()] = (column, {})
                    hashed_only.append(column)
                dependent[column.lower()][1][stage.model.name] = self._stage_column(
                    stage, column
                )
            self._static_part(model, stage, source)

        if hashed_only:
            self._issue(
                model,
                "info",
                Code.DBT_PARAMETER_UNSUPPORTED,
                f"Link '{model.name}': its hash key also hashes "
                + ", ".join(f"'{c}'" for c in hashed_only)
                + ", which foreign_hashkeys doesn't list. TurboVault imports them "
                "as dependent child keys, which its generated link also selects",
                parameter="foreign_hashkeys",
            )
        self._link_columns(model, link, sources, list(dependent.values()), payload)
        self.links[model.name] = _LinkInfo(
            link=link, model=model, stages=[stage.model.name for stage in stages]
        )
        self.domain.links[model.name] = link
        self._mapped.add(model.unique_id)
        if as_bool(params.get("source_is_single_batch"), False):
            self._single_batch_tables.update(stage.identifier for stage in stages)

    def _link_columns(
        self,
        model: DbtModel,
        link: DLink,
        sources: list[tuple[dict[str, Any], _Stage]],
        dependent: list[tuple[str, dict[str, str]]],
        payload: list[str],
    ) -> None:
        """Dependent child keys, payload and additional columns of a link."""
        order = 0
        for name, by_stage in dependent:
            order += 1
            link.columns.append(
                DLinkColumn(
                    name=name,
                    column_type="dependent_child_key",
                    sort_order=order,
                    source_mappings=[
                        DLinkSourceMapping(
                            source_table_identifier=stage.identifier,
                            source_column_name=by_stage[stage.model.name],
                        )
                        for _source, stage in sources
                        if stage.model.name in by_stage
                    ],
                )
            )
        additional = [
            str(c) for c in as_list(model.call.params.get("additional_columns"))
        ]
        for kind, names in (
            ("payload", payload),
            ("additional_column", additional),
        ):
            for name in names:
                order += 1
                column = DLinkColumn(name=name, column_type=kind, sort_order=order)
                for source, stage in sources:
                    stage_name = name
                    if kind == "payload":
                        per_source = [str(c) for c in as_list(source.get("payload"))]
                        if len(per_source) == len(payload):
                            stage_name = per_source[payload.index(name)]
                    column.source_mappings.append(
                        DLinkSourceMapping(
                            source_table_identifier=stage.identifier,
                            source_column_name=self._stage_column(stage, stage_name),
                        )
                    )
                link.columns.append(column)

    def _is_key_column(
        self, foreign_hashkey: str, stages: list[_Stage], link_hashkey: str
    ) -> bool:
        """Whether a foreign hash key is a plain column the link hash key hashes.

        No stage computes it and no Hub has it, but it is an input of the link
        hash key (e.g. a transaction id in a transactional link).
        """
        lowered = foreign_hashkey.lower()
        if any(stage.hashkey(foreign_hashkey) is not None for stage in stages):
            return False
        if any(
            (h.hub.hashkey_name or "").lower() == lowered for h in self.hubs.values()
        ):
            return False
        return any(
            lowered in [c.lower() for c in stage.hashkey(link_hashkey) or []]
            for stage in stages
        )

    def _link_hub(
        self,
        model: DbtModel,
        foreign_hashkey: str,
        stages: list[_Stage],
        referenced: list[_HubInfo],
    ) -> tuple[_HubInfo, str] | None:
        """The Hub a foreign hash key references, and the alias it has.

        Matched by the Hub's hash key. An aliased reference (e.g. the second
        Hub of a self-link) is matched, among the Hubs with as many business
        keys as the stage hashes into it, by a Hub the stages load under that
        hash key, else the Hub the key names (the longest name it contains),
        else the one Hub the link already references.
        """
        stage_names = {stage.model.name for stage in stages}
        lowered = foreign_hashkey.lower()
        standard = [h for h in self.hubs.values() if h.hub.hub_type == "standard"]
        named = [h for h in standard if (h.hub.hashkey_name or "").lower() == lowered]
        if len(named) > 1:
            named = [h for h in named if stage_names & set(h.stages)] or named
        if len(named) == 1:
            return named[0], ""
        if not named:
            width = next(
                (
                    len(hashed)
                    for stage in stages
                    if (hashed := stage.hashkey(foreign_hashkey)) is not None
                ),
                None,
            )
            # An alias is recognized only where a stage computes it.
            fits = [h for h in standard if len(h.business_keys) == width]
            containing = [
                h for h in fits if entity_base_name(h.hub.physical_name) in lowered
            ]
            longest = max(
                (len(entity_base_name(h.hub.physical_name)) for h in containing),
                default=0,
            )
            for candidates in (
                [
                    h
                    for h in fits
                    if any(
                        role.lower() == lowered
                        for stage, role in h.stages.items()
                        if stage in stage_names
                    )
                ],
                [
                    h
                    for h in containing
                    if len(entity_base_name(h.hub.physical_name)) == longest
                ],
                [h for h in fits if any(h is r for r in referenced)],
            ):
                unique = {id(h): h for h in candidates}
                if len(unique) == 1:
                    return next(iter(unique.values())), foreign_hashkey
        if not named and lowered in self._skipped_keys:
            self._depends_on_skipped(
                model,
                f"the hub '{self._skipped_keys[lowered]}'",
                parameter="foreign_hashkeys",
            )
            return None
        self._issue(
            model,
            "error",
            Code.DBT_LINK_HUB_AMBIGUOUS,
            f"Link '{model.name}': the foreign hash key '{foreign_hashkey}' "
            + ("matches several Hubs" if len(named) > 1 else "matches no imported Hub")
            + "; the link is left out",
            parameter="foreign_hashkeys",
            suggestion=(
                "Name the foreign hash key like the Hub's hash key, or import "
                "the Hub it references."
            ),
        )
        return None

    # -- Satellites -------------------------------------------------------------

    def _v1_models(self) -> dict[str, DbtModel]:
        """v1 models by the name of the v0 model each reads."""
        result: dict[str, DbtModel] = {}
        for model in self.index.models_with(*_V1_MACROS):
            v0 = model.call.params.get(_V1_MACROS[model.call.macro])
            if isinstance(v0, dict) and "__ref__" in v0:
                v0 = v0["__ref__"]
            if v0:
                result.setdefault(str(v0), model)
        return result

    def _satellite_parent(
        self, model: DbtModel, stage: _Stage, satellite_type: str
    ) -> tuple[str, str] | None:
        """(parent name, "hub" | "link") of a Satellite, or None (reported)."""
        params = model.call.params
        if satellite_type == "reference":
            keys = [str(k).lower() for k in as_list(params.get("parent_ref_keys"))]
            candidates = [
                h
                for h in self.hubs.values()
                if h.hub.hub_type == "reference"
                and [c.name.lower() for c in h.business_keys] == keys
            ]
            parameter = "parent_ref_keys"
            wanted = ", ".join(keys)
        else:
            parent = str(params.get("parent_hashkey") or "")
            lowered = parent.lower()
            candidates = [
                *[
                    h
                    for h in self.hubs.values()
                    if (h.hub.hashkey_name or "").lower() == lowered
                ],
                *[
                    link_info
                    for link_info in self.links.values()
                    if link_info.link.hashkey_name.lower() == lowered
                ],
            ]
            if not candidates:
                role_hubs = [
                    h
                    for h in self.hubs.values()
                    if h.stages.get(stage.model.name, "").lower() == lowered and lowered
                ]
                if len(role_hubs) == 1:
                    self._issue(
                        model,
                        "warning",
                        Code.DBT_PARAMETER_UNSUPPORTED,
                        f"Satellite '{model.name}' hangs on '{parent}', the hash key "
                        f"hub '{role_hubs[0].hub.physical_name}' is loaded under from "
                        "this stage; TurboVault generates it with the hub's own hash "
                        "key",
                        parameter="parent_hashkey",
                    )
                    candidates = role_hubs
            parameter = "parent_hashkey"
            wanted = parent
        if len(candidates) > 1:
            loading = [
                c
                for c in candidates
                if stage.model.name
                in (c.stages if isinstance(c, _HubInfo) else set(c.stages))
            ]
            candidates = loading or candidates
        if len(candidates) != 1:
            self._issue(
                model,
                "error",
                Code.DBT_REFERENCE_UNRESOLVED,
                f"Satellite '{model.name}': "
                + (
                    f"no imported Hub or Link has '{wanted}'"
                    if not candidates
                    else f"several Hubs or Links have '{wanted}'"
                )
                + "; the satellite is left out",
                parameter=parameter,
            )
            return None
        found = candidates[0]
        if isinstance(found, _HubInfo):
            return found.hub.physical_name, "hub"
        return found.link.physical_name, "link"

    def _map_satellite(self, model: DbtModel, v1_by_v0: dict[str, DbtModel]) -> None:
        call = model.call
        assert call is not None
        params = call.params
        satellite_type = _SATELLITE_TYPES[call.macro]
        v1 = v1_by_v0.get(model.name)
        name = self._satellite_name(model.name, v1.name if v1 else None)

        stage_name = params.get("source_model")
        if isinstance(stage_name, dict) and "__ref__" in stage_name:
            stage_name = stage_name["__ref__"]
        stage = self.stages.get(str(stage_name or ""))
        if stage is None and str(stage_name) in self._skipped_stages:
            self._depends_on_skipped(
                model, f"the stage '{stage_name}'", parameter="source_model"
            )
            self._skip("satellite", name, "depends_on_skipped")
            return
        if stage is None:
            self._issue(
                model,
                "error",
                Code.DBT_REFERENCE_UNRESOLVED,
                f"Satellite '{model.name}' loads from '{stage_name}', which isn't an "
                "imported stage; the satellite is left out",
                parameter="source_model",
            )
            self._skip("satellite", name, "missing_source_table")
            return
        parent_key = str(params.get("parent_hashkey") or "").lower()
        if (
            satellite_type != "reference"
            and parent_key in self._skipped_keys
            and not any(
                (h.hub.hashkey_name or "").lower() == parent_key
                for h in self.hubs.values()
            )
            and not any(
                link.link.hashkey_name.lower() == parent_key
                for link in self.links.values()
            )
        ):
            self._depends_on_skipped(
                model,
                f"'{self._skipped_keys[parent_key]}'",
                parameter="parent_hashkey",
            )
            self._skip("satellite", name, "depends_on_skipped")
            return
        parent = self._satellite_parent(model, stage, satellite_type)
        if parent is None:
            self._skip("satellite", name, "missing_parent")
            return

        hashdiff_column, hashdiff_alias = (None, None)
        if satellite_type != "non_historized":
            hashdiff_column, hashdiff_alias = normalize_hashdiff(
                params.get("src_hashdiff")
            )
        delta_columns = None
        if hashdiff_column:
            spec = stage.hashdiffs.get(hashdiff_column) or next(
                (
                    value
                    for key, value in stage.hashdiffs.items()
                    if key.lower() == hashdiff_column.lower()
                ),
                None,
            )
            if spec is not None:
                delta_columns = {c.lower() for c in spec.get("columns") or []}

        columns: list[DSatelliteColumn] = []
        yaml_columns = model.yaml_columns()
        ma_keys = (
            [str(k) for k in as_list(params.get("src_ma_key"))]
            if satellite_type == "multi_active"
            else []
        )
        entries = [{"column": k, "alias": k, "ma": True} for k in ma_keys] + [
            {**entry, "ma": False}
            for entry in normalize_payload(params.get("src_payload"))
        ]
        for position, entry in enumerate(entries):
            column = self._stage_column(stage, entry["column"])
            alias = entry["alias"]
            docs = yaml_columns.get(alias.lower()) or {}
            columns.append(
                DSatelliteColumn(
                    source_column_name=column,
                    target_column_name=alias if alias != entry["column"] else None,
                    description=self._description(docs.get("description")),
                    is_multi_active_key=entry["ma"],
                    include_in_delta_detection=(
                        delta_columns is None
                        or entry["ma"]
                        or column.lower() in delta_columns
                        or alias.lower() in delta_columns
                    ),
                    sort_order=position + 1,
                )
            )

        satellite = DSatellite(
            physical_name=name,
            satellite_type=satellite_type,  # type: ignore[arg-type]
            parent_entity_name=parent[0],
            parent_entity_type=parent[1],  # type: ignore[arg-type]
            source_table_identifier=stage.identifier,
            description=self._description(model.description),
            hashdiff_name=hashdiff_column or CLEAR,
            hashdiff_alias=hashdiff_alias or CLEAR,
            disable_hwm=as_bool(params.get("disable_hwm"), False),
            columns=columns,
            outputs={},
        )
        self._v1_options(satellite, model, v1)
        derived_v0 = satellite_pattern(self.config.satellite_v0_naming, name)
        if derived_v0 != model.name:
            satellite.outputs["satellite_v0"] = DModelOutput(
                kind="satellite_v0", model_name=model.name
            )
        if v1 is not None:
            self._mapped.add(v1.unique_id)
            derived_v1 = satellite_pattern(self.config.satellite_v1_naming, name)
            if derived_v1 != v1.name:
                satellite.outputs["satellite_v1"] = DModelOutput(
                    kind="satellite_v1", model_name=v1.name
                )
        if name in self.domain.satellites:
            self._issue(
                model,
                "error",
                Code.DBT_VALUE_INVALID,
                f"Satellite '{model.name}' gets the name '{name}', which another "
                "satellite has; it is left out",
            )
            return
        self.domain.satellites[name] = satellite
        self._mapped.add(model.unique_id)
        if as_bool(params.get("source_is_single_batch"), False):
            self._single_batch_tables.add(stage.identifier)

    def _satellite_name(self, v0_name: str, v1_name: str | None) -> str:
        """A Satellite's name: what the v0 (else v1) naming pattern makes of
        its model's name, else the v0 model's name."""
        for pattern, model_name in (
            (self.config.satellite_v0_naming, v0_name),
            (self.config.satellite_v1_naming, v1_name),
        ):
            if not model_name:
                continue
            values = invert_pattern(pattern, model_name)
            if values:
                name = values.get("satellite_name") or values.get("entity_name")
                if name:
                    return name
        return v0_name

    def _v1_options(
        self, satellite: DSatellite, v0: DbtModel, v1: DbtModel | None
    ) -> None:
        project_default = self.config.generate_satellite_v1_views
        has_v1 = v1 is not None
        if satellite.satellite_type == "non_historized":
            satellite.create_v1_view = CLEAR
        else:
            satellite.create_v1_view = CLEAR if has_v1 == project_default else has_v1
        if v1 is None:
            satellite.v1_ledts_alias = CLEAR
            satellite.v1_add_is_current_flag = True
            satellite.v1_include_payload = True
            return
        params = v1.call.params
        ledts = self._plain_value(v1, "ledts_alias")
        satellite.v1_ledts_alias = ledts or CLEAR
        satellite.v1_add_is_current_flag = as_bool(
            params.get("add_is_current_flag"), True
        )
        satellite.v1_include_payload = as_bool(params.get("include_payload"), True)
        hashdiff = self._plain_value(v1, "hashdiff")
        expected = satellite.hashdiff_alias
        expected = satellite.hashdiff_name if expected is CLEAR else expected
        if (
            hashdiff
            and expected not in (CLEAR, None)
            and hashdiff.lower() != str(expected).lower()
        ):
            self._issue(
                v1,
                "warning",
                Code.DBT_PARAMETER_UNSUPPORTED,
                f"v1 view '{v1.name}' reads the hash diff '{hashdiff}', but "
                f"'{v0.name}' writes '{expected}'; TurboVault uses '{expected}'",
                parameter="hashdiff",
            )

    # -- effectivity and record-tracking Satellites ------------------------------

    def _tracked(
        self, model: DbtModel, parameter: str = "tracked_hashkey"
    ) -> _HubInfo | _LinkInfo | None:
        tracked = str(model.call.params.get(parameter) or "").lower()
        candidates = [
            *[
                h
                for h in self.hubs.values()
                if (h.hub.hashkey_name or "").lower() == tracked
            ],
            *[
                link_info
                for link_info in self.links.values()
                if link_info.link.hashkey_name.lower() == tracked
            ],
        ]
        if len(candidates) != 1:
            self._issue(
                model,
                "error",
                Code.DBT_REFERENCE_UNRESOLVED,
                f"'{model.name}' tracks '{model.call.params.get(parameter)}', which "
                + ("no" if not candidates else "more than one")
                + " imported Hub or Link has; it is left out",
                parameter=parameter,
            )
            return None
        return candidates[0]

    def _map_effectivity_satellite(self, model: DbtModel) -> None:
        parent = self._tracked(model)
        if parent is None:
            return
        params = model.call.params
        entity = parent.hub if isinstance(parent, _HubInfo) else parent.link
        entity.create_effectivity_satellite = True
        entity.effectivity_is_active_alias = (
            self._plain_value(model, "is_active_alias") or CLEAR
        )
        entity.effectivity_disable_hwm = as_bool(params.get("disable_hwm"), False)
        entity.effectivity_additional_columns = [
            str(c) for c in as_list(params.get("additional_columns"))
        ] or CLEAR
        derived = satellite_pattern(
            self.config.effectivity_satellite_naming,
            entity_base_name(entity.physical_name),
        )
        if derived != model.name:
            entity.outputs["effectivity_satellite"] = DModelOutput(
                kind="effectivity_satellite", model_name=model.name
            )
        stage_name = params.get("source_model")
        if isinstance(stage_name, dict):
            stage_name = stage_name.get("__ref__")
        stages = list(parent.stages) if isinstance(parent, _HubInfo) else parent.stages
        if stages and str(stage_name) != stages[0]:
            self._issue(
                model,
                "warning",
                Code.DBT_PARAMETER_UNSUPPORTED,
                f"Effectivity satellite '{model.name}' reads '{stage_name}'; "
                f"TurboVault generates it from '{stages[0]}', the first stage of "
                f"'{entity.physical_name}'",
                parameter="source_model",
            )
        stage = self.stages.get(str(stage_name))
        if stage is not None and as_bool(params.get("source_is_single_batch"), False):
            self._single_batch_tables.add(stage.identifier)
        self._mapped.add(model.unique_id)

    def _map_record_tracking_satellite(self, model: DbtModel) -> None:
        parent = self._tracked(model)
        if parent is None:
            return
        entity = parent.hub if isinstance(parent, _HubInfo) else parent.link
        entity.create_record_tracking_satellite = True
        derived = satellite_pattern(
            self.config.record_tracking_satellite_naming,
            entity_base_name(entity.physical_name),
        )
        if derived != model.name:
            entity.outputs["record_tracking_satellite"] = DModelOutput(
                kind="record_tracking_satellite", model_name=model.name
            )
        sources = normalize_source_models(model.call.params.get("source_models"))
        read = {source["name"] for source in sources}
        loaded = set(parent.stages)
        if read != loaded:
            self._issue(
                model,
                "warning",
                Code.DBT_PARAMETER_UNSUPPORTED,
                f"Record-tracking satellite '{model.name}' reads "
                f"{sorted(read)}; TurboVault generates it from the stages "
                f"'{entity.physical_name}' loads from: {sorted(loaded)}",
                parameter="source_models",
            )
        self._mapped.add(model.unique_id)

    # -- tables -----------------------------------------------------------------

    def _finish_tables(self) -> None:
        """Delivery methods, inherited values, and columns nobody described."""
        for system in self.domain.source_systems.values():
            tables = list(system.tables.values())
            for table in tables:
                if table.identifier in self._single_batch_tables:
                    table.delivery_method = "single_batch"
            self._hoist(system, tables, "record_source_value", self._default_rsrc)
            self._hoist(system, tables, "load_date_value", self._default_ldts)
            self._hoist(system, tables, "static_part_of_record_source", None)
        if self._single_batch_tables and not self.config.use_delivery_method:
            self._issue(
                None,
                "info",
                Code.DBT_PROJECT_SETTING,
                "Some models load single-batch data (source_is_single_batch): "
                "their tables get the delivery method single_batch. Turn on the "
                "project setting use_delivery_method to generate them that way",
            )
        for identifier, columns in self._unknown_columns.items():
            system_name, _, table_name = identifier.partition("|")
            self._issue(
                None,
                "warning",
                Code.DBT_COLUMN_UNKNOWN,
                f"Table '{table_name}' of '{system_name}': "
                + ", ".join(sorted(set(columns)))
                + " aren't in the catalog or the YAML; they are created without "
                "a data type",
                entity=EntityRef(type="source_table", name=table_name),
                suggestion="Provide catalog.json, or describe the columns in YAML.",
            )

    def _default_rsrc(self, system: DSourceSystem, table: DSourceTable) -> str:
        value = self.config.default_record_source_value or f"!{system.name}"
        return fill_placeholders(
            value, source_system_name=system.name, source_table_name=table.physical_name
        )

    def _default_ldts(self, system: DSourceSystem, table: DSourceTable) -> str:
        value = self.config.default_load_date_value or DEFAULT_LOAD_DATE
        return fill_placeholders(
            value, source_system_name=system.name, source_table_name=table.physical_name
        )

    @staticmethod
    def _hoist(
        system: DSourceSystem,
        tables: list[DSourceTable],
        attribute: str,
        default: Any,
    ) -> None:
        """Set a value the tables share on their system; drop inherited ones.

        A table's value equal to what it inherits (the project's, else the
        engine's) isn't stored, so the project's setting keeps applying.
        """
        values = [getattr(table, attribute) for table in tables]
        stage_tables = [t for t, v in zip(tables, values, strict=True) if v]
        if not stage_tables:
            setattr(system, attribute, CLEAR)
            for table in tables:
                setattr(table, attribute, CLEAR)
            return
        shared = {getattr(t, attribute) for t in stage_tables}
        if len(shared) == 1 and len(stage_tables) == len(tables):
            value = shared.pop()
            inherited = default is not None and all(
                value == default(system, t) for t in tables
            )
            setattr(system, attribute, CLEAR if inherited else value)
            for table in tables:
                setattr(table, attribute, CLEAR)
            return
        setattr(system, attribute, CLEAR)
        for table in tables:
            value = getattr(table, attribute)
            if not value or (default is not None and value == default(system, table)):
                setattr(table, attribute, CLEAR)

    # -- report -----------------------------------------------------------------

    def _report_unmapped(self) -> None:
        for model in self.index.models.values():
            if model.unique_id in self._mapped or model.call is not None:
                continue
            if model.capture is not None and (
                model.capture.error or model.capture.package_calls
            ):
                continue  # already reported: render failed, macro unsupported
            self._issue(
                model,
                "info",
                Code.DBT_MODEL_NOT_MAPPED,
                f"Model '{model.name}' has no Data Vault call TurboVault maps: it "
                "stays in the dbt project",
            )
        for model in self.index.models.values():
            if model.call is None or model.unique_id in self._mapped:
                continue
            if model.call.macro in (
                "pit",
                "ref_table",
                "control_snap_v0",
                "control_snap_v1",
            ):
                continue  # mapped in a later step
            if model.call.macro in _V1_MACROS:
                self._issue(
                    model,
                    "info",
                    Code.DBT_MODEL_NOT_MAPPED,
                    f"v1 view '{model.name}' reads no imported satellite: it stays "
                    "in the dbt project",
                )
