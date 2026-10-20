"""Unit tests for the SQLMesh renderer (ticket 423).

render_sqlmesh() is a pure function — no Django or DB is needed.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _options(**kwargs):
    from engine.services.generation.types import GenerationOptions

    return GenerationOptions(**kwargs)


def _runtime_config(**kwargs):
    from engine.services.runtime_config import EngineRuntimeConfig

    return EngineRuntimeConfig(**kwargs)


def _minimal_export(project_name: str = "test"):
    from engine.services.export.models import ProjectExport

    return ProjectExport(project_name=project_name)


def _export_with_stage():
    from engine.services.export.models import (
        ProjectExport,
        SourceColumnDef,
        StageDefinition,
        StageHashkeyDef,
    )

    return ProjectExport(
        project_name="test",
        stages=[
            StageDefinition(
                stage_name="stg__crm__customer",
                source_table="customer",
                source_schema="crm_raw",
                source_system="crm",
                hashkeys=[
                    StageHashkeyDef(
                        target_entity="hub_customer",
                        entity_type="hub",
                        hashkey_name="hk_customer",
                        business_key_columns=["customer_id"],
                    )
                ],
                hashdiffs=[],
                columns=[SourceColumnDef(column_name="customer_id", datatype="STRING")],
            )
        ],
    )


def _export_with_standard_hub(group: str | None = "sales"):
    from engine.services.export.models import (
        HashkeyDefinition,
        HubColumnMapping,
        HubDefinition,
        HubSourceInfo,
        ProjectExport,
    )

    return ProjectExport(
        project_name="test",
        hubs=[
            HubDefinition(
                hub_name="hub_customer",
                hub_type="standard",
                group=group,
                hashkey=HashkeyDefinition(
                    hashkey_name="hk_customer",
                    business_keys=["customer_id"],
                ),
                business_key_columns=["customer_id"],
                source_tables=[
                    HubSourceInfo(
                        source_table="customer",
                        source_system="crm",
                        stage_name="stg__crm__customer",
                        business_key_columns=["customer_id"],
                        is_primary_source=True,
                        column_mappings=[
                            HubColumnMapping(
                                hub_column="customer_id",
                                source_column="customer_id",
                            )
                        ],
                    )
                ],
            )
        ],
    )


def _export_with_satellite(sat_type: str = "standard"):
    from engine.services.export.models import (
        ProjectExport,
        SatelliteColumnDef,
        SatelliteDefinition,
    )

    return ProjectExport(
        project_name="test",
        satellites=[
            SatelliteDefinition(
                satellite_name="sat_customer_details",
                satellite_type=sat_type,
                group="sales",
                parent_entity="hub_customer",
                parent_entity_type="hub",
                parent_hashkey="hk_customer",
                source_table="customer",
                source_system="crm",
                stage_name="stg__crm__customer",
                hashdiff_name="hd_sat_customer_details",
                columns=[SatelliteColumnDef(source_column="customer_name")],
            )
        ],
    )


# ---------------------------------------------------------------------------
# Scaffold files
# ---------------------------------------------------------------------------


class TestScaffoldFiles:
    _EXPECTED_PATHS = {
        "config.yaml",
        "config.json",
        "models/__init__.py",
        "requirements.txt",
        "README.md",
    }

    def test_all_five_scaffold_files_are_present(self):
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(_minimal_export(), _runtime_config(), _options())
        scaffold_paths = {a.path for a in artifacts if a.kind == "sqlmesh_config"}
        assert scaffold_paths == self._EXPECTED_PATHS

    def test_scaffold_artifacts_have_non_empty_content(self):
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(_minimal_export(), _runtime_config(), _options())
        for a in artifacts:
            assert a.content, f"{a.path} has empty content"

    def test_models_init_calls_load_dv_config(self):
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(_minimal_export(), _runtime_config(), _options())
        init = next(a for a in artifacts if a.path == "models/__init__.py")
        assert "load_dv_config" in init.content

    def test_requirements_txt_pins_datavault4sqlmesh(self):
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(_minimal_export(), _runtime_config(), _options())
        req = next(a for a in artifacts if a.path == "requirements.txt")
        assert "datavault4sqlmesh" in req.content

    def test_readme_includes_agpl_license_notice(self):
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(_minimal_export(), _runtime_config(), _options())
        readme = next(a for a in artifacts if a.path == "README.md")
        assert "AGPL" in readme.content


# ---------------------------------------------------------------------------
# Entity model files — paths and imports
# ---------------------------------------------------------------------------


class TestEntityModelFiles:
    def test_stage_model_path(self):
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(_export_with_stage(), _runtime_config(), _options())
        stage = next(a for a in artifacts if a.entity_type == "stage")
        assert stage.path == "models/stg/crm/stg__crm__customer.py"

    def test_stage_model_imports_stage_model(self):
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(_export_with_stage(), _runtime_config(), _options())
        stage = next(a for a in artifacts if a.entity_type == "stage")
        assert "from datavault4sqlmesh import stage_model" in stage.content
        assert "stage_model(" in stage.content

    def test_hub_model_path_with_group(self):
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(_export_with_standard_hub(group="sales"), _runtime_config(), _options())
        hub = next(a for a in artifacts if a.entity_type == "hub")
        assert hub.path == "models/rdv/sales/hub_customer.py"

    def test_hub_model_imports_hub_model(self):
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(_export_with_standard_hub(), _runtime_config(), _options())
        hub = next(a for a in artifacts if a.entity_type == "hub")
        assert "from datavault4sqlmesh import hub_model" in hub.content
        assert "hub_model(" in hub.content

    def test_satellite_v0_model_path_and_import(self):
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(
            _export_with_satellite("standard"),
            _runtime_config(),
            _options(generate_satellite_v1_views=False),
        )
        sat = next(a for a in artifacts if a.entity_type == "satellite")
        assert sat.path == "models/rdv/sales/sat_customer_details.py"
        assert "from datavault4sqlmesh import satellite_model" in sat.content

    def test_satellite_v1_produced_when_enabled(self):
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(
            _export_with_satellite("standard"),
            _runtime_config(),
            _options(generate_satellite_v1_views=True),
        )
        v1 = next((a for a in artifacts if a.entity_type == "satellite_v1"), None)
        assert v1 is not None
        assert "from datavault4sqlmesh import satellite_v1_model" in v1.content

    def test_satellite_v1_not_produced_when_disabled(self):
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(
            _export_with_satellite("standard"),
            _runtime_config(),
            _options(generate_satellite_v1_views=False),
        )
        assert not any(a.entity_type == "satellite_v1" for a in artifacts)

    def test_ungrouped_entity_placed_in_shared_subfolder(self):
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(
            _export_with_standard_hub(group=None),
            _runtime_config(),
            _options(),
        )
        hub = next(a for a in artifacts if a.entity_type == "hub")
        assert hub.path == "models/rdv/shared/hub_customer.py"


# ---------------------------------------------------------------------------
# Unsupported entity warnings
# ---------------------------------------------------------------------------


class TestUnsupportedEntityWarnings:
    def test_reference_hub_emits_warning_and_no_artifact(self):
        from engine.services.export.models import (
            HashkeyDefinition,
            HubDefinition,
            ProjectExport,
        )
        from engine.services.generation.errors import Code
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        export = ProjectExport(
            project_name="test",
            hubs=[
                HubDefinition(
                    hub_name="hub_ref",
                    hub_type="reference",
                    hashkey=HashkeyDefinition(hashkey_name="hk_ref", business_keys=[]),
                    business_key_columns=[],
                    source_tables=[],
                )
            ],
        )
        artifacts, issues = render_sqlmesh(export, _runtime_config(), _options())
        assert any(i.code == Code.SQLMESH_UNSUPPORTED_REFERENCE_HUB for i in issues)
        assert not any(a.entity_type == "hub" for a in artifacts)

    def test_non_historized_link_emits_warning_and_no_artifact(self):
        from engine.services.export.models import (
            HashkeyDefinition,
            LinkDefinition,
            ProjectExport,
        )
        from engine.services.generation.errors import Code
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        export = ProjectExport(
            project_name="test",
            links=[
                LinkDefinition(
                    link_name="lnk_nh",
                    link_type="non_historized",
                    hashkey=HashkeyDefinition(hashkey_name="hk_nh", business_keys=[]),
                    hub_references=[],
                    foreign_hashkeys=[],
                    payload_columns=[],
                    source_tables=[],
                )
            ],
        )
        artifacts, issues = render_sqlmesh(export, _runtime_config(), _options())
        assert any(i.code == Code.SQLMESH_UNSUPPORTED_NON_HISTORIZED_LINK for i in issues)
        assert not any(a.entity_type == "link" for a in artifacts)

    @pytest.mark.parametrize(
        "sat_type",
        ["non_historized", "multi_active", "effectivity", "record_tracking", "reference"],
    )
    def test_unsupported_satellite_type_emits_warning(self, sat_type):
        from engine.services.generation.errors import Code
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, issues = render_sqlmesh(
            _export_with_satellite(sat_type), _runtime_config(), _options()
        )
        assert any(i.code == Code.SQLMESH_UNSUPPORTED_SATELLITE_TYPE for i in issues)
        assert not any(a.entity_type == "satellite" for a in artifacts)

    def test_reference_table_emits_warning(self):
        from engine.services.export.models import ProjectExport, ReferenceTableDefinition
        from engine.services.generation.errors import Code
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        export = ProjectExport(
            project_name="test",
            reference_tables=[
                ReferenceTableDefinition(
                    table_name="ref_country",
                    reference_hub_name="hub_country",
                    historization_type="latest",
                )
            ],
        )
        _, issues = render_sqlmesh(export, _runtime_config(), _options())
        assert any(i.code == Code.SQLMESH_UNSUPPORTED_REFERENCE_TABLE for i in issues)

    def test_pit_emits_warning(self):
        from engine.services.export.models import PITDefinition, ProjectExport
        from engine.services.generation.errors import Code
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        export = ProjectExport(
            project_name="test",
            pits=[
                PITDefinition(
                    pit_name="pit_customer",
                    tracked_entity_type="hub",
                    tracked_entity_name="hub_customer",
                    tracked_hashkey="hk_customer",
                    snapshot_control_name="snap_ctrl",
                    snapshot_logic_column="snap_col",
                )
            ],
        )
        _, issues = render_sqlmesh(export, _runtime_config(), _options())
        assert any(i.code == Code.SQLMESH_UNSUPPORTED_PIT for i in issues)

    def test_snapshot_control_emits_warning(self):
        from engine.services.export.models import ProjectExport, SnapshotControlDefinition
        from engine.services.generation.errors import Code
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        export = ProjectExport(
            project_name="test",
            snapshot_controls=[
                SnapshotControlDefinition(
                    name="snap_ctrl",
                    start_date="2020-01-01",
                    end_date="2030-12-31",
                    daily_time="00:00:00",
                )
            ],
        )
        _, issues = render_sqlmesh(export, _runtime_config(), _options())
        assert any(i.code == Code.SQLMESH_UNSUPPORTED_SNAPSHOT_CONTROL for i in issues)

    def test_unsupported_entities_produce_only_warnings_never_errors(self):
        from engine.services.export.models import (
            HashkeyDefinition,
            HubDefinition,
            ProjectExport,
        )
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        export = ProjectExport(
            project_name="test",
            hubs=[
                HubDefinition(
                    hub_name="hub_ref",
                    hub_type="reference",
                    hashkey=HashkeyDefinition(hashkey_name="hk_ref", business_keys=[]),
                    business_key_columns=[],
                    source_tables=[],
                )
            ],
        )
        _, issues = render_sqlmesh(export, _runtime_config(), _options())
        assert issues, "Expected at least one issue for an unsupported reference hub"
        assert all(i.severity == "warning" for i in issues)
