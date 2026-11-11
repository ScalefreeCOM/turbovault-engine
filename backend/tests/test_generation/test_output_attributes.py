"""Output attributes of generated dbt models (#442).

Models can carry the file path, name and config of the project they were
imported from. Generation must write them there, under that name and with
that config, and every reference to a model must use its actual name —
for stored attributes as much as for configured naming patterns.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.django_db

YAML_METADATA = re.compile(
    r"\{%- set yaml_metadata -%\}\n(.*?)\{%- endset -%\}", re.DOTALL
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def full_export(project_export):
    """The conftest export plus every other kind of model generation emits:
    record-tracking and effectivity satellites, a reference hub with a
    reference satellite and table, a snapshot control and a PIT."""
    from engine.services.export.models import (
        HubDefinition,
        HubSourceInfo,
        PITDefinition,
        ReferenceTableDefinition,
        ReferenceTableSatelliteAssignment,
        SatelliteColumnDef,
        SatelliteDefinition,
        SnapshotControlDefinition,
        SnapshotLogicPattern,
    )

    hub = project_export.hubs[0]
    hub.create_record_tracking_satellite = True
    hub.create_effectivity_satellite = True

    nation_source = HubSourceInfo(
        source_table="customer",
        source_system="crm",
        stage_name="stg__crm__customer",
        business_key_columns=["customer_id"],
    )
    return project_export.model_copy(
        update={
            "hubs": [
                hub,
                HubDefinition(
                    hub_name="nation_rh",
                    hub_type="reference",
                    reference_key_columns=["customer_id"],
                    source_tables=[nation_source],
                ),
            ],
            "satellites": [
                *project_export.satellites,
                SatelliteDefinition(
                    satellite_name="nation_rs",
                    satellite_type="reference",
                    parent_entity="nation_rh",
                    parent_entity_type="hub",
                    parent_hashkey="",
                    parent_business_keys=["customer_id"],
                    source_table="customer",
                    source_system="crm",
                    stage_name="stg__crm__customer",
                    hashdiff_name="hd_nation_rs",
                    columns=[SatelliteColumnDef(source_column="customer_name")],
                ),
            ],
            "reference_tables": [
                ReferenceTableDefinition(
                    table_name="nation_r",
                    reference_hub_name="nation_rh",
                    historization_type="latest",
                    satellites=[
                        ReferenceTableSatelliteAssignment(satellite_name="nation_rs")
                    ],
                )
            ],
            "snapshot_controls": [
                SnapshotControlDefinition(
                    name="control_snap",
                    start_date="2020-01-01",
                    end_date="2030-12-31",
                    daily_time="08:00:00",
                    logic_patterns=[
                        SnapshotLogicPattern(
                            column_name="is_active", component="daily", forever=True
                        )
                    ],
                )
            ],
            "pits": [
                PITDefinition(
                    pit_name="customer_bp",
                    tracked_entity_type="hub",
                    tracked_entity_name="hub_customer",
                    tracked_hashkey="hk_customer",
                    satellites=["sat_customer_details"],
                    snapshot_control_name="control_snap_v1",
                    snapshot_logic_column="is_active",
                )
            ],
        }
    )


@pytest.fixture
def engine_project(django_setup, db):
    from engine.models import Project

    return Project.objects.create(name="attrs_e2e")


@pytest.fixture
def run(django_setup, engine_project, tmp_path, monkeypatch):
    """Run the dbt pipeline on the given export (bundled templates only)."""
    from engine.services.generation import GenerationOptions, generate
    from engine.services.generation import pipeline as pipeline_module
    from engine.services.generation.stages import build as build_module
    from engine.services.runtime_config import EngineRuntimeConfig

    def _run(export, *, runtime: dict | None = None, **options):
        monkeypatch.setattr(build_module, "build_export", lambda **_: export)
        monkeypatch.setattr(pipeline_module, "build_export", lambda **_: export)
        out = tmp_path / "dbt_out"
        report = generate(
            project=engine_project,
            output_type="dbt",
            output_path=out,
            runtime_config=EngineRuntimeConfig(
                project_name="attrs_e2e", **(runtime or {})
            ),
            options=GenerationOptions(use_db_templates=False, **options),
        )
        return report, out

    return _run


def _attributes(**by_kind: dict) -> dict:
    from engine.services.export.models import ModelOutputAttributes

    return {
        kind: ModelOutputAttributes.model_validate(values)
        for kind, values in by_kind.items()
    }


def _models(out: Path) -> dict[str, Path]:
    """Every generated model's name and .sql path."""
    return {path.stem: path for path in (out / "models").rglob("*.sql")}


def _sql(out: Path, model: str) -> str:
    return _models(out)[model].read_text(encoding="utf-8")


def _metadata(sql: str) -> dict:
    match = YAML_METADATA.search(sql)
    assert match, sql
    return yaml.safe_load(match.group(1))


def _references(sql: str) -> set[str]:
    """Names of the models a generated model's yaml_metadata refers to."""
    metadata = _metadata(sql)
    refs: set[str] = set()
    source_models = metadata.get("source_models")
    if isinstance(source_models, list):
        refs |= {entry["name"] for entry in source_models}
    if isinstance(metadata.get("source_model"), str):
        refs.add(metadata["source_model"])
    for key in (
        "sat_v0",
        "ref_sat_v0",
        "control_snap_v0",
        "snapshot_relation",
        "tracked_entity",
        "ref_hub",
    ):
        if key in metadata:
            refs.add(metadata[key])
    refs |= set(metadata.get("sat_names") or [])
    refs |= set(metadata.get("ref_satellites") or {})
    return refs


def assert_consistent_project(out: Path) -> None:
    """Every .yml names the model of its .sql, and every reference resolves."""
    models = _models(out)
    assert len(models) == len(list((out / "models").rglob("*.sql"))), "dup names"
    for name, path in models.items():
        yml = path.with_suffix(".yml")
        assert yml.exists(), f"{name} has no .yml"
        documented = [m["name"] for m in yaml.safe_load(yml.read_text())["models"]]
        assert documented == [name], f"{yml} documents {documented}"
        missing = _references(path.read_text(encoding="utf-8")) - models.keys()
        assert not missing, f"{name} refers to missing models {missing}"


def _config_call(sql: str) -> str:
    return sql[sql.index("{{ config(") : sql.index(") }}") + 4]


# ---------------------------------------------------------------------------
# Without attributes
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_standard_structure_and_consistent_references(self, run, full_export):
        report, out = run(full_export)
        assert report.status == "success", report.issues
        models = _models(out)
        rel = {name: path.relative_to(out).as_posix() for name, path in models.items()}
        assert rel["stg__crm__customer"] == (
            "models/02_staging/crm/stg__crm__customer.sql"
        )
        assert rel["hub_customer"] == "models/03_raw_vault/sales/hub_customer.sql"
        assert rel["sat_customer_details_v0"].startswith("models/03_raw_vault/sales/")
        assert rel["customer_bp"] == "models/04_business_vault/pits/customer_bp.sql"
        assert rel["control_snap_v1"] == "models/00_control/control_snap_v1.sql"
        assert_consistent_project(out)

    def test_no_per_model_config_beyond_todays(self, run, full_export):
        _, out = run(full_export)
        hub_config = _config_call(_sql(out, "hub_customer"))
        assert "alias=" not in hub_config
        assert "schema=" not in hub_config
        assert "materialized=" not in hub_config
        assert "tags=['hub', 'raw_vault', 'sales']" in hub_config


# ---------------------------------------------------------------------------
# Naming patterns (the hard-coded _v0 / _v1 suffix bug)
# ---------------------------------------------------------------------------


class TestNamingPatterns:
    RUNTIME = {
        "satellite_v0_naming": "[[ satellite_name ]]_hist",
        "satellite_v1_naming": "[[ satellite_name ]]_cur",
    }

    def test_references_follow_non_default_patterns(self, run, full_export):
        report, out = run(full_export, runtime=self.RUNTIME)
        assert report.status == "success", report.issues
        models = _models(out)
        assert {"sat_customer_details_hist", "sat_customer_details_cur"} <= set(models)
        assert not any(
            name.endswith(("_v0", "_v1")) for name in models if "sat" in name
        )

        v1 = _metadata(_sql(out, "sat_customer_details_cur"))
        assert v1["sat_v0"] == "sat_customer_details_hist"
        ref_v1 = _metadata(_sql(out, "nation_rs_cur"))
        assert ref_v1["ref_sat_v0"] == "nation_rs_hist"
        assert _metadata(_sql(out, "customer_bp"))["sat_names"] == [
            "sat_customer_details_hist"
        ]
        assert list(_metadata(_sql(out, "nation_r"))["ref_satellites"]) == [
            "nation_rs_cur"
        ]
        assert_consistent_project(out)

    def test_v1_yml_names_the_v1_model(self, run, full_export):
        _, out = run(full_export, runtime=self.RUNTIME)
        yml = _models(out)["sat_customer_details_cur"].with_suffix(".yml")
        assert yaml.safe_load(yml.read_text())["models"][0]["name"] == (
            "sat_customer_details_cur"
        )

    def test_snapshot_control_yml_matches_a_suffixed_stored_name(
        self, run, full_export
    ):
        """A control stored as `control_snap_v0` used to document
        `control_snap_v0_v0` while writing `control_snap_v0.sql`."""
        full_export.snapshot_controls[0].name = "control_snap_v0"
        _, out = run(full_export)
        assert {"control_snap_v0", "control_snap_v1"} <= set(_models(out))
        assert _metadata(_sql(out, "control_snap_v1"))["control_snap_v0"] == (
            "control_snap_v0"
        )
        assert_consistent_project(out)


# ---------------------------------------------------------------------------
# Stored attributes
# ---------------------------------------------------------------------------


def _with_original_layout(export):
    """Give the export an imported project's layout and names."""
    export.stages[0].output_attributes = _attributes(
        stage={"file_path": "staging/crm/stg_customers.sql", "materialized": "view"}
    )
    export.hubs[0].output_attributes = _attributes(
        hub={
            "file_path": "raw_vault/hubs/customer_h.sql",
            "alias": "customer_hub",
            "tags": ["raw", "pii"],
        },
        effectivity_satellite={"model_name": "customer_eff"},
    )
    satellite = next(
        s for s in export.satellites if s.satellite_name == "sat_customer_details"
    )
    satellite.output_attributes = _attributes(
        satellite_v0={"file_path": "raw_vault/sats/customer_details.sql"},
        satellite_v1={
            "model_name": "customer_details_current",
            "materialized": "view",
            "schema": "presentation",
            "database": "analytics",
        },
    )
    export.snapshot_controls[0].output_attributes = _attributes(
        snapshot_control_v1={"model_name": "snapshots_daily"}
    )
    export.pits[0].output_attributes = _attributes(
        pit={"file_path": "marts/pit_customer.sql"}
    )
    return export


class TestStoredAttributes:
    def test_paths_and_names(self, run, full_export):
        report, out = run(_with_original_layout(full_export))
        assert report.status == "success", report.issues
        rel = {n: p.relative_to(out).as_posix() for n, p in _models(out).items()}
        assert rel["stg_customers"] == "models/staging/crm/stg_customers.sql"
        assert rel["customer_h"] == "models/raw_vault/hubs/customer_h.sql"
        assert rel["customer_details"] == "models/raw_vault/sats/customer_details.sql"
        assert rel["pit_customer"] == "models/marts/pit_customer.sql"
        # Only the name is stored: Turbovault's folder.
        assert rel["customer_eff"] == "models/03_raw_vault/sales/customer_eff.sql"
        assert rel["customer_details_current"].startswith("models/03_raw_vault/")
        # Nothing stored: as before.
        assert rel["lnk_customer_order"] == (
            "models/03_raw_vault/sales/lnk_customer_order.sql"
        )
        assert "hub_customer" not in rel and "stg__crm__customer" not in rel

    def test_every_reference_uses_the_stored_names(self, run, full_export):
        _, out = run(_with_original_layout(full_export))
        hub = _metadata(_sql(out, "customer_h"))
        assert [s["name"] for s in hub["source_models"]] == ["stg_customers"]
        assert _metadata(_sql(out, "customer_details"))["source_model"] == (
            "stg_customers"
        )
        assert _metadata(_sql(out, "customer_details_current"))["sat_v0"] == (
            "customer_details"
        )
        assert _metadata(_sql(out, "customer_eff"))["source_model"] == "stg_customers"
        pit_sql = _sql(out, "pit_customer")
        pit = _metadata(pit_sql)
        assert pit["tracked_entity"] == "customer_h"
        assert pit["sat_names"] == ["customer_details"]
        assert pit["snapshot_relation"] == "snapshots_daily"
        assert "clean_up_pit('snapshots_daily')" in pit_sql
        assert_consistent_project(out)

    def test_config_carries_alias_schema_database_materialization_tags(
        self, run, full_export
    ):
        _, out = run(_with_original_layout(full_export))
        hub_config = _config_call(_sql(out, "customer_h"))
        assert "alias='customer_hub'" in hub_config
        assert "tags=['raw', 'pii']" in hub_config
        hub_yml = yaml.safe_load(
            _models(out)["customer_h"].with_suffix(".yml").read_text()
        )
        assert hub_yml["models"][0]["config"]["tags"] == ["raw", "pii"]

        v1_config = _config_call(_sql(out, "customer_details_current"))
        assert "materialized='view'" in v1_config
        assert "schema='presentation'" in v1_config
        assert "database='analytics'" in v1_config

    def test_models_outside_layer_folders_get_layer_schema_and_materialization(
        self, run, full_export
    ):
        _, out = run(_with_original_layout(full_export))
        # dbt_project.yml configures 03_raw_vault/, not raw_vault/.
        hub_config = _config_call(_sql(out, "customer_h"))
        assert "schema='rdv'" in hub_config
        assert "materialized='incremental'" in hub_config
        # A stored value wins over the layer's.
        stage_config = _config_call(_sql(out, "stg_customers"))
        assert "materialized='view'" in stage_config
        assert "schema='stage'" in stage_config
        pit_config = _config_call(_sql(out, "pit_customer"))
        assert "schema='bdv'" in pit_config
        # A PIT keeps its own materialization rather than its layer's.
        assert "materialized='incremental'" in pit_config
        # Inside its layer folder a model still inherits from dbt_project.yml.
        eff_config = _config_call(_sql(out, "customer_eff"))
        assert "schema=" not in eff_config and "materialized=" not in eff_config

    def test_selection_keeps_stored_names_of_unselected_models(self, run, full_export):
        """A PIT generated on its own still refers to the stored names of the
        hub and satellites the selection left out."""
        from engine.services.generation.types import EntitySelection

        report, out = run(
            _with_original_layout(full_export),
            entity_selection=EntitySelection(include_entity_types={"pit"}),
        )
        assert report.status == "success", report.issues
        assert "customer_h" not in _models(out)
        pit = _metadata(_sql(out, "pit_customer"))
        assert pit["tracked_entity"] == "customer_h"
        assert pit["sat_names"] == ["customer_details"]
        assert pit["snapshot_relation"] == "snapshots_daily"

    def test_standard_paths_option_ignores_attributes(self, run, full_export):
        report, out = run(_with_original_layout(full_export), use_original_paths=False)
        assert report.status == "success", report.issues
        models = _models(out)
        assert {"stg__crm__customer", "hub_customer", "sat_customer_details_v0"} <= set(
            models
        )
        assert not {"stg_customers", "customer_h", "customer_details"} & set(models)
        assert "alias=" not in _config_call(_sql(out, "hub_customer"))
        assert not (out / "models" / "raw_vault").exists()
        assert_consistent_project(out)


# ---------------------------------------------------------------------------
# Collisions
# ---------------------------------------------------------------------------


class TestCollisions:
    @pytest.mark.parametrize(
        "attributes",
        [
            # Same model name as the link.
            {"hub": {"model_name": "lnk_customer_order"}},
            # Same name, different case.
            {"hub": {"model_name": "LNK_Customer_Order"}},
            # Same file as the link, by path.
            {"hub": {"file_path": "03_raw_vault/sales/lnk_customer_order.sql"}},
        ],
    )
    def test_collision_writes_nothing(self, run, full_export, attributes):
        full_export.hubs[0].output_attributes = _attributes(**attributes)
        report, out = run(full_export)
        errors = [i for i in report.issues if i.severity == "error"]
        assert [i.code for i in errors] == ["write.path_collision"]
        assert "hub of 'hub_customer'" in errors[0].message
        assert "link of 'lnk_customer_order'" in errors[0].message
        assert report.files_generated == 0
        assert not (out / "models").exists()

    def test_collision_with_a_naming_pattern(self, run, full_export):
        """Stored names are checked against derived ones too."""
        full_export.hubs[0].output_attributes = _attributes(
            hub={"model_name": "sat_customer_details_v1"}
        )
        report, _ = run(full_export)
        assert [i.code for i in report.issues if i.severity == "error"] == [
            "write.path_collision"
        ]

    def test_same_name_in_another_folder_still_collides(self, run, full_export):
        full_export.hubs[0].output_attributes = _attributes(
            hub={"file_path": "elsewhere/lnk_customer_order.sql"}
        )
        report, _ = run(full_export)
        assert any(i.code == "write.path_collision" for i in report.issues)

    def test_two_stages_with_the_same_name_collide(self, run, full_export):
        """Source tables whose names differ only in case give one stage name;
        the second must not silently replace the first."""
        stage = full_export.stages[0]
        full_export.stages.append(stage.model_copy(update={"source_table": "CUSTOMER"}))
        report, out = run(full_export)
        errors = [i for i in report.issues if i.severity == "error"]
        assert [i.code for i in errors] == ["write.path_collision"]
        assert f"Model name '{stage.stage_name}'" in errors[0].message
        assert report.files_generated == 0
        assert not (out / "models").exists()

    def test_same_stage_name_with_different_stored_names_collides(
        self, run, full_export
    ):
        """Distinct stored names don't help: both stages are looked up by
        their shared stage name, so both would be written from one."""
        stage = full_export.stages[0]
        full_export.stages.append(
            stage.model_copy(
                update={
                    "source_table": "CUSTOMER",
                    "output_attributes": _attributes(stage={"model_name": "stg_other"}),
                }
            )
        )
        report, _ = run(full_export)
        errors = [i for i in report.issues if i.severity == "error"]
        assert [i.code for i in errors] == ["write.path_collision"]
        assert "is generated by more than one entity" in errors[0].message

    def test_no_collision_check_with_standard_paths(self, run, full_export):
        full_export.hubs[0].output_attributes = _attributes(
            hub={"model_name": "lnk_customer_order"}
        )
        report, _ = run(full_export, use_original_paths=False)
        assert report.status == "success", report.issues


def test_write_stage_refuses_paths_outside_the_output(django_setup, tmp_path):
    """Safeguard behind the input validation: a path that escapes the output
    folder is skipped with an error; the other files are still written."""
    from engine.services.generation.stages.write import write_artifacts
    from engine.services.generation.types import GeneratedArtifact, GenerationOptions

    out = tmp_path / "project"
    artifacts = [
        GeneratedArtifact(kind="sql_model", path="../escaped.sql", content="x"),
        GeneratedArtifact(kind="sql_model", path="models/ok.sql", content="y"),
    ]
    written, issues = write_artifacts(
        artifacts=artifacts,
        output_type="dbt",
        output_path=out,
        options=GenerationOptions(),
    )
    assert [i.code for i in issues] == ["write.path_outside_output"]
    assert not (tmp_path / "escaped.sql").exists()
    assert (out / "models" / "ok.sql").read_text() == "y"


# ---------------------------------------------------------------------------
# Validation of the attributes themselves
# ---------------------------------------------------------------------------


class TestAttributeValidation:
    @pytest.mark.parametrize(
        ("values", "fragment"),
        [
            ({"file_path": "../outside.sql"}, "must stay inside models/"),
            ({"file_path": "a/../../b.sql"}, "must stay inside models/"),
            ({"file_path": "/abs/hub.sql"}, "relative path"),
            ({"file_path": "C:/abs/hub.sql"}, "relative path"),
            ({"file_path": "raw\\hub.sql"}, "relative path"),
            ({"file_path": "raw/hub.yml"}, ".sql file"),
            ({"file_path": "raw//hub.sql"}, "must stay inside models/"),
            ({"file_path": "raw/my hub.sql"}, "must stay inside models/"),
            ({"model_name": "a", "file_path": "raw/b.sql"}, "named after"),
            ({"model_name": "1hub"}, "'model_name'"),
            ({"model_name": "hub-x"}, "'model_name'"),
            ({"alias": "x'; drop"}, "'alias'"),
            ({"schema": "my schema"}, "'schema'"),
            ({"materialized": "table\n"}, "'materialized'"),
            ({"tags": ["ok", "it's"]}, "'tags'"),
            ({"tags": "daily"}, "valid list"),
        ],
    )
    def test_invalid_values_rejected(self, django_setup, values, fragment):
        from engine.services.export.models import ModelOutputAttributes
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match=re.escape(fragment)):
            ModelOutputAttributes.model_validate(values)

    def test_valid_values_accepted(self, django_setup):
        from engine.services.export.models import ModelOutputAttributes

        attributes = ModelOutputAttributes.model_validate(
            {
                "model_name": "hub_customer",
                "file_path": "raw-vault/v2.1/hub_customer.sql",
                "alias": "customer$hub",
                "schema": "rdv",
                "database": "my-gcp-project-1",
                "materialized": "incremental",
                "tags": ["layer:raw", "team/dv", "v1.2"],
            }
        )
        assert attributes.as_stored()["schema"] == "rdv"

    def test_unknown_output_kind_rejected(self, django_setup):
        from engine.services.export.models import HubDefinition
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="unknown output kind"):
            HubDefinition(
                hub_name="h",
                hub_type="standard",
                output_attributes={"satellite_v0": {"model_name": "x"}},
            )

    def test_export_leaves_out_unset_attributes(self, django_setup):
        attributes = _attributes(hub={"model_name": "customer_h", "schema": "rdv"})
        assert attributes["hub"].model_dump(mode="json") == {
            "model_name": "customer_h",
            "schema": "rdv",
        }

    def test_django_field_validates(self, engine_project):
        from django.core.exceptions import ValidationError
        from engine.models import Hub

        hub = Hub(
            project=engine_project,
            hub_physical_name="hub_customer",
            hub_hashkey_name="hk_customer",
            output_attributes={"hub": {"file_path": "../../etc/passwd.sql"}},
        )
        with pytest.raises(ValidationError, match="output_attributes"):
            hub.full_clean()
        hub.output_attributes = {"hub": {"file_path": "raw/hub_customer.sql"}}
        hub.full_clean()
