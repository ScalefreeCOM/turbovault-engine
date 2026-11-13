"""
Mapping snapshot controls, PITs and reference tables (spec §7.4, 7.5).

Part of the dbt project mapping (``mapping._Mapper`` inherits it): it runs
after the Raw Vault is mapped, since PITs and reference tables read Hubs,
Links and Satellites, and both read a snapshot control.

datavault4dbt's snapshot logic (``control_snap_v1``'s ``log_logic``) names
intervals: ``daily``, ``weekly``, ``monthly``, ``yearly``. A mapping of them
is one logic column, named by the ``datavault4dbt.snapshot_trigger_column``
variable (default ``is_active``); a list of ``{column: {...}}`` entries
names a column each. TurboVault stores one logic rule per column and
component; the intervals become the components datavault4dbt computes them
from (``weekly`` is the beginning of the week, ...).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from engine.services.imports.dbt.datavault4dbt import (
    as_bool,
    normalize_ref_satellites,
    normalize_sat_names,
)
from engine.services.imports.domain import (
    CLEAR,
    DPIT,
    DModelOutput,
    DReferenceTable,
    DRefSatAssignment,
    DSnapshotControl,
    DSnapshotControlLogic,
)
from engine.services.imports.errors import Code

if TYPE_CHECKING:
    from engine.services.imports.dbt.index import DbtModel

# log_logic intervals and the component datavault4dbt computes each from.
INTERVAL_COMPONENTS = {
    "daily": "daily",
    "weekly": "beginning_of_week",
    "monthly": "beginning_of_month",
    "yearly": "beginning_of_year",
}

# TurboVault's components (engine.models.SnapshotControlLogic.SnapshotComponent).
COMPONENTS = frozenset(
    {
        "daily",
        "beginning_of_week",
        "end_of_week",
        "beginning_of_month",
        "end_of_month",
        "beginning_of_quarter",
        "end_of_quarter",
        "beginning_of_year",
        "end_of_year",
    }
)
_UNITS = frozenset({"DAY", "WEEK", "MONTH", "QUARTER", "YEAR"})

# PIT parameters TurboVault doesn't store: the model's columns come from
# the project's datavault4dbt variables.
_PIT_UNSUPPORTED = (
    "ldts",
    "ledts",
    "sdts",
    "refer_to_ghost_records",
    "mandatory_strategy",
)


def _ref(value: Any) -> str | None:
    """A model a parameter names, written as a name or a ref()."""
    if isinstance(value, dict) and "__ref__" in value:
        value = value["__ref__"]
    return str(value) if value else None


class BusinessVaultMapping:
    """Snapshot controls, PITs and reference tables: a mixin of the mapper."""

    # -- snapshot controls ------------------------------------------------

    def _map_snapshot_controls(self) -> None:
        for model in self.index.models_with("control_snap_v0"):
            self._map_control_table(model)
        for model in self.index.models_with("control_snap_v1"):
            self._map_control_logic(model)

    def _map_control_table(self, model: DbtModel) -> None:
        name = model.name
        base = name[:-3] if name.lower().endswith("_v0") else name
        if base in self.domain.snapshot_controls:
            self._issue(
                model,
                "error",
                Code.DBT_VALUE_INVALID,
                f"Snapshot control '{name}' has the same base name as another; it "
                "is left out",
            )
            return
        control = DSnapshotControl(
            name=base,
            start_date=self._date_param(model, "start_date"),
            end_date=self._date_param(model, "end_date") or CLEAR,
            daily_time=self._time_param(model, "daily_snapshot_time"),
            sdts_alias=self._plain_value(model, "sdts_alias") or CLEAR,
            outputs={},
        )
        if f"{base}_v0" != name:
            control.outputs["snapshot_control_v0"] = DModelOutput(
                kind="snapshot_control_v0", model_name=name
            )
        self.domain.snapshot_controls[base] = control
        self._controls_by_model[name] = base
        self._models_of[("snapshot_control", base)] = [model]
        self._track(control.outputs, "snapshot_control_v0", model)
        self._mapped.add(model.unique_id)

    def _map_control_logic(self, model: DbtModel) -> None:
        v0 = _ref(model.call.params.get("control_snap_v0"))
        base = self._controls_by_model.get(v0 or "")
        if base is None:
            self._issue(
                model,
                "error",
                Code.DBT_REFERENCE_UNRESOLVED,
                f"Snapshot control logic '{model.name}' reads '{v0}', which isn't "
                "an imported snapshot control table; it is left out",
                parameter="control_snap_v0",
            )
            return
        control = self.domain.snapshot_controls[base]
        if control.logic_rules:
            self._issue(
                model,
                "warning",
                Code.DBT_PARAMETER_UNSUPPORTED,
                f"'{model.name}' is a second logic model of snapshot control "
                f"'{v0}'; TurboVault has one per control, so it is left out",
                parameter="control_snap_v0",
            )
            return
        control.logic_rules = self._logic_rules(model)
        if f"{base}_v1" != model.name:
            control.outputs["snapshot_control_v1"] = DModelOutput(
                kind="snapshot_control_v1", model_name=model.name
            )
        sdts = self._plain_value(model, "sdts_alias")
        if sdts and control.sdts_alias not in (CLEAR, sdts):
            self._issue(
                model,
                "warning",
                Code.DBT_PARAMETER_UNSUPPORTED,
                f"'{model.name}' names the snapshot date column '{sdts}', its "
                f"table '{control.sdts_alias}'; TurboVault uses the table's",
                parameter="sdts_alias",
            )
        elif sdts and control.sdts_alias is CLEAR:
            control.sdts_alias = sdts
        self._controls_by_model[model.name] = base
        self._models_of[("snapshot_control", base)].append(model)
        self._track(
            control.outputs,
            "snapshot_control_v1",
            model,
            follows=self._models_of[("snapshot_control", base)][0],
        )
        self._mapped.add(model.unique_id)

    def _trigger_column(self) -> str:
        """The logic column a log_logic mapping computes."""
        value = self.artifacts.project_vars.get("datavault4dbt.snapshot_trigger_column")
        return str(value) if value else "is_active"

    def _logic_rules(self, model: DbtModel) -> list[DSnapshotControlLogic]:
        log_logic = model.call.params.get("log_logic")
        if isinstance(log_logic, dict):
            columns = [(self._trigger_column(), log_logic)]
        elif isinstance(log_logic, list):
            columns = []
            for entry in log_logic:
                if isinstance(entry, dict) and len(entry) == 1:
                    ((column, intervals),) = entry.items()
                    columns.append((str(column), intervals))
        else:
            columns = []
        rules: list[DSnapshotControlLogic] = []
        for column, intervals in columns:
            if not isinstance(intervals, dict):
                continue
            for interval, spec in intervals.items():
                component = INTERVAL_COMPONENTS.get(str(interval).lower())
                component = component or str(interval).lower()
                if component not in COMPONENTS:
                    self._issue(
                        model,
                        "warning",
                        Code.DBT_VALUE_INVALID,
                        f"'{model.name}': '{interval}' in log_logic is no interval "
                        "datavault4dbt knows (daily, weekly, monthly, yearly); it "
                        "is not imported",
                        parameter="log_logic",
                    )
                    continue
                spec = spec if isinstance(spec, dict) else {}
                forever = as_bool(spec.get("forever"), False)
                unit = str(spec.get("unit") or "").upper() or None
                duration = spec.get("duration")
                try:
                    duration = int(duration) if duration is not None else None
                except (TypeError, ValueError):
                    duration = None
                if unit is not None and unit not in _UNITS:
                    unit = None
                rules.append(
                    DSnapshotControlLogic(
                        column_name=column,
                        component=component,
                        duration=None if forever else duration,
                        unit=None if forever else unit,
                        forever=forever,
                    )
                )
        return rules

    def _date_param(self, model: DbtModel, parameter: str) -> str | None:
        value = model.call.params.get(parameter)
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        text = str(value).strip().strip("'\"")
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            self._issue(
                model,
                "warning",
                Code.DBT_VALUE_INVALID,
                f"'{model.name}': {parameter} '{value}' isn't a date (YYYY-MM-DD); "
                "it is not imported",
                parameter=parameter,
            )
            return None

    def _time_param(self, model: DbtModel, parameter: str) -> str | None:
        value = model.call.params.get(parameter)
        if value is None:
            return None
        if isinstance(value, int) and not isinstance(value, bool):
            # YAML reads an unquoted 23:59:59 as sexagesimal seconds
            hours, rest = divmod(value, 3600)
            return f"{hours:02d}:{rest // 60:02d}:{rest % 60:02d}"
        text = str(value).strip()
        parts = text.split(":")
        if len(parts) in (2, 3) and all(p.isdigit() for p in parts):
            hours, minutes = int(parts[0]), int(parts[1])
            seconds = int(parts[2]) if len(parts) == 3 else 0
            if hours < 24 and minutes < 60 and seconds < 60:
                return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        self._issue(
            model,
            "warning",
            Code.DBT_VALUE_INVALID,
            f"'{model.name}': {parameter} '{value}' isn't a time (HH:MM:SS); it "
            "is not imported",
            parameter=parameter,
        )
        return None

    def _control_for(self, model: DbtModel, parameter: str) -> str | None:
        """The snapshot control a PIT or reference table reads (reported if none)."""
        relation = _ref(model.call.params.get(parameter))
        base = self._controls_by_model.get(relation or "")
        if base is None:
            self._issue(
                model,
                "error",
                Code.DBT_REFERENCE_UNRESOLVED,
                f"'{model.name}' reads the snapshot control '{relation}', which "
                "isn't imported; it is left out",
                parameter=parameter,
            )
        return base

    def _check_trigger(self, model: DbtModel, base: str, trigger: str | None) -> None:
        """Note a trigger column that isn't one of the control's logic columns."""
        if not trigger:
            return
        rules = self.domain.snapshot_controls[base].logic_rules
        if rules and trigger.lower() not in {r.column_name.lower() for r in rules}:
            self._issue(
                model,
                "warning",
                Code.DBT_PARAMETER_UNSUPPORTED,
                f"'{model.name}' selects snapshots with '{trigger}', which isn't a "
                f"logic column of snapshot control '{base}' in TurboVault: the "
                "import adds it to the control with the default logic",
                parameter="snapshot_trigger_column",
            )

    # -- satellites by model ------------------------------------------------

    def _satellite_of(self, model_name: str) -> str | None:
        found = self._sats_by_model.get(model_name)
        if found is None:
            lowered = model_name.lower()
            found = next(
                (
                    sat
                    for name, sat in self._sats_by_model.items()
                    if name.lower() == lowered
                ),
                None,
            )
        return found

    def _skipped_satellite(self, model_name: str) -> bool:
        return model_name in self._skipped_sat_models

    # -- PITs -----------------------------------------------------------------

    def _map_pit(self, model: DbtModel) -> None:
        params = model.call.params
        tracked = _ref(params.get("tracked_entity")) or ""
        hub = self.hubs.get(tracked)
        link = self.links.get(tracked)
        if hub is None and link is None:
            if ("hub", tracked) in self.domain.skipped or (
                "link",
                tracked,
            ) in self.domain.skipped:
                self._depends_on_skipped(
                    model, f"'{tracked}'", parameter="tracked_entity"
                )
                self._skip("pit", model.name, "depends_on_skipped")
            else:
                self._issue(
                    model,
                    "error",
                    Code.DBT_REFERENCE_UNRESOLVED,
                    f"PIT '{model.name}' tracks '{tracked}', which isn't an imported "
                    "Hub or Link; it is left out",
                    parameter="tracked_entity",
                )
                self._skip("pit", model.name, "missing_reference")
            return
        entity_hashkey = hub.hub.hashkey_name if hub else link.link.hashkey_name
        hashkey = self._plain_value(model, "hashkey")
        if hashkey and entity_hashkey and hashkey.lower() != entity_hashkey.lower():
            self._issue(
                model,
                "warning",
                Code.DBT_PARAMETER_UNSUPPORTED,
                f"PIT '{model.name}' joins on '{hashkey}'; TurboVault uses the hash "
                f"key of '{tracked}', '{entity_hashkey}'",
                parameter="hashkey",
            )

        satellites: list[str] = []
        for name in normalize_sat_names(params.get("sat_names")):
            satellite = self._satellite_of(name)
            if satellite is None:
                if self._skipped_satellite(name):
                    self._depends_on_skipped(
                        model, f"the satellite '{name}'", parameter="sat_names"
                    )
                    self._skip("pit", model.name, "depends_on_skipped")
                else:
                    self._issue(
                        model,
                        "error",
                        Code.DBT_REFERENCE_UNRESOLVED,
                        f"PIT '{model.name}' reads '{name}', which isn't an imported "
                        "satellite; it is left out",
                        parameter="sat_names",
                    )
                    self._skip("pit", model.name, "missing_reference")
                return
            satellites.append(satellite)

        base = self._control_for(model, "snapshot_relation")
        if base is None:
            self._skip("pit", model.name, "missing_reference")
            return
        trigger = self._plain_value(model, "snapshot_trigger_column")
        self._check_trigger(model, base, trigger)
        for parameter in _PIT_UNSUPPORTED:
            if params.get(parameter) is not None:
                self._issue(
                    model,
                    "warning",
                    Code.DBT_PARAMETER_UNSUPPORTED,
                    f"PIT '{model.name}' sets '{parameter}'; TurboVault doesn't "
                    "store it, so the generated PIT uses the default",
                    parameter=parameter,
                )
        optimization = params.get("snapshot_optimization")
        pit = DPIT(
            physical_name=model.name,
            tracked_entity_name=tracked,
            tracked_entity_type="hub" if hub is not None else "link",
            satellite_names=satellites,
            snapshot_control_name=base,
            snapshot_logic_column=trigger,
            dimension_key_column_name=self._plain_value(model, "dimension_key"),
            pit_type=self._plain_value(model, "pit_type"),
            custom_record_source=self._plain_value(model, "custom_rsrc"),
            use_snapshot_optimization=(
                CLEAR if optimization is None else as_bool(optimization, False)
            ),
            outputs={},
        )
        self.domain.pits[model.name] = pit
        self._models_of[("pit", model.name)] = [model]
        self._track(pit.outputs, "pit", model, entity=("pit", model.name), control=base)
        self._mapped.add(model.unique_id)

    # -- reference tables ----------------------------------------------------

    def _map_reference_table(self, model: DbtModel) -> None:
        params = model.call.params
        hub_name = _ref(params.get("ref_hub")) or ""
        hub = self.hubs.get(hub_name)
        if hub is None or hub.hub.hub_type != "reference":
            if ("hub", hub_name) in self.domain.skipped:
                self._depends_on_skipped(model, f"'{hub_name}'", parameter="ref_hub")
                self._skip("reference_table", model.name, "depends_on_skipped")
            else:
                self._issue(
                    model,
                    "error",
                    Code.DBT_REFERENCE_UNRESOLVED,
                    f"Reference table '{model.name}' reads '{hub_name}', which isn't "
                    "an imported reference hub; it is left out",
                    parameter="ref_hub",
                )
                self._skip("reference_table", model.name, "missing_reference")
            return
        assignments: list[DRefSatAssignment] = []
        for name, columns in normalize_ref_satellites(
            params.get("ref_satellites")
        ).items():
            satellite = self._satellite_of(name)
            if satellite is None:
                reason = (
                    "depends_on_skipped"
                    if self._skipped_satellite(name)
                    else "missing_reference"
                )
                if reason == "depends_on_skipped":
                    self._depends_on_skipped(
                        model, f"the satellite '{name}'", parameter="ref_satellites"
                    )
                else:
                    self._issue(
                        model,
                        "error",
                        Code.DBT_REFERENCE_UNRESOLVED,
                        f"Reference table '{model.name}' reads '{name}', which isn't "
                        "an imported satellite; it is left out",
                        parameter="ref_satellites",
                    )
                self._skip("reference_table", model.name, reason)
                return
            assignments.append(
                DRefSatAssignment(
                    satellite_name=satellite,
                    include_columns=list(columns["include"]),
                    exclude_columns=list(columns["exclude"]),
                )
            )
        historized = str(params.get("historized") or "latest").strip().lower()
        historization = {"full": "full", "snapshot": "snapshot_based"}.get(
            historized, "latest"
        )
        base = trigger = None
        if historization == "snapshot_based":
            base = self._control_for(model, "snapshot_relation")
            if base is None:
                self._skip("reference_table", model.name, "missing_reference")
                return
            trigger = self._plain_value(model, "snapshot_trigger_column")
            self._check_trigger(model, base, trigger)
        self.domain.reference_tables[model.name] = DReferenceTable(
            physical_name=model.name,
            reference_hub_name=hub_name,
            historization_type=historization,
            snapshot_control_name=base,
            snapshot_logic_column=trigger,
            description=self._description(model.description),
            satellite_assignments=assignments,
            outputs={},
        )
        self._models_of[("reference_table", model.name)] = [model]
        self._track(
            self.domain.reference_tables[model.name].outputs,
            "reference_table",
            model,
            entity=("reference_table", model.name),
        )
        self._mapped.add(model.unique_id)
