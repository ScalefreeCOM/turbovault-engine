"""Unit tests for the SQLMesh renderer (ticket 423).

render_sqlmesh() is a pure function — no Django or DB is needed.
"""

from __future__ import annotations

import pytest

# All tests in this file import from engine.services.generation, which triggers
# the package __init__.py that loads Django models. The django_setup fixture
# (session-scoped) must run before any import to avoid AppRegistryNotReady.
pytestmark = pytest.mark.usefixtures("django_setup")


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


def _export_with_satellite(sat_type: str = "standard", with_parent_hub: bool = True):
    from engine.services.export.models import (
        ProjectExport,
        SatelliteColumnDef,
        SatelliteDefinition,
    )

    return ProjectExport(
        project_name="test",
        # SQLMesh skips satellites whose parent hub isn't rendered.
        hubs=_export_with_standard_hub().hubs if with_parent_hub else [],
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

    def test_requirements_txt_adds_driver_extra_for_dialect(self):
        from engine.services.generation.renderers.sqlmesh_renderer import _render_requirements

        for dialect in ("postgres", "snowflake", "databricks", "trino", "bigquery"):
            lines = _render_requirements(_runtime_config(sqlmesh_dialect=dialect)).splitlines()
            assert lines == ["datavault4sqlmesh>=0.1.0", f"sqlmesh[{dialect}]"], dialect

    def test_requirements_txt_duckdb_needs_no_driver_extra(self):
        from engine.services.generation.renderers.sqlmesh_renderer import _render_requirements

        lines = _render_requirements(_runtime_config(sqlmesh_dialect="duckdb")).splitlines()
        assert lines == ["datavault4sqlmesh>=0.1.0"]

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

    @staticmethod
    def _assert_satellite_skipped_for_parent(export, parent_label):
        from engine.services.generation.errors import Code
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, issues = render_sqlmesh(export, _runtime_config(), _options())
        assert not any(a.entity_type in ("satellite", "satellite_v1") for a in artifacts)
        (warning,) = [i for i in issues if i.code == Code.SQLMESH_SATELLITE_PARENT_SKIPPED]
        assert warning.severity == "warning"
        assert warning.entity is not None and warning.entity.name == "sat_customer_details"
        assert parent_label in warning.message

    def test_satellite_of_reference_hub_is_skipped(self):
        export = _export_with_satellite("standard")
        export.hubs = [export.hubs[0].model_copy(update={"hub_type": "reference"})]
        self._assert_satellite_skipped_for_parent(export, "hub 'hub_customer'")

    def test_satellite_of_missing_parent_hub_is_skipped(self):
        self._assert_satellite_skipped_for_parent(
            _export_with_satellite("standard", with_parent_hub=False), "hub 'hub_customer'"
        )

    def test_satellite_of_unrendered_link_is_skipped(self):
        """A hub of the same name doesn't count: the parent is a link."""
        export = _export_with_satellite("standard")
        export.satellites = [
            export.satellites[0].model_copy(update={"parent_entity_type": "link"})
        ]
        self._assert_satellite_skipped_for_parent(export, "link 'hub_customer'")

    def test_satellite_hashdiff_dropped_from_stage_when_parent_skipped(self):
        from engine.services.export.models import StageDefinition, StageHashdiffDef
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        export = _export_with_satellite("standard", with_parent_hub=False)
        export.stages = [
            StageDefinition(
                stage_name="stg__crm__customer",
                source_table="customer",
                source_schema="crm_raw",
                source_system="crm",
                hashdiffs=[
                    StageHashdiffDef(
                        satellite_name="sat_customer_details",
                        hashdiff_name="hd_sat_customer_details",
                        columns=["customer_name"],
                    )
                ],
            )
        ]
        artifacts, _ = render_sqlmesh(export, _runtime_config(), _options())
        stage = next(a for a in artifacts if a.entity_type == "stage")
        assert "hd_sat_customer_details" not in stage.content

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


# ---------------------------------------------------------------------------
# TemplateResolver integration
# ---------------------------------------------------------------------------


class TestTemplateResolverIntegration:
    """render_sqlmesh() uses a TemplateResolver when provided.

    These tests use in-memory overrides so no Django DB or file templates
    are required (pure-function behaviour).
    """

    def _hub_export(self):
        from engine.services.export.models import (
            HashkeyDefinition,
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
                    hashkey=HashkeyDefinition(
                        hashkey_name="hk_customer", business_keys=["customer_id"]
                    ),
                    business_key_columns=["customer_id"],
                    source_tables=[
                        HubSourceInfo(
                            source_table="customer",
                            source_system="crm",
                            stage_name="stg_customer",
                            rsrc_static=None,
                        )
                    ],
                )
            ],
        )

    def test_hub_rendered_via_in_memory_override(self):
        """When a sqlmesh/hub_standard override is present the template output
        replaces the hardcoded generator."""
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh
        from engine.services.generation.template_resolver import TemplateResolver
        from engine.services.generation.types import TemplateOverride

        resolver = TemplateResolver(
            use_db_templates=False,
            framework="sqlmesh",
            templates_override={
                "sqlmesh": {
                    "hub_standard": TemplateOverride(sql="# custom hub: [[ hub_name ]]")
                }
            },
        )
        artifacts, issues = render_sqlmesh(
            self._hub_export(), _runtime_config(), _options(), resolver
        )
        hub_artifact = next(
            (a for a in artifacts if a.entity_type == "hub"), None
        )
        assert hub_artifact is not None
        # Rendered model files always end with exactly one newline.
        assert hub_artifact.content == "# custom hub: hub_customer\n"

    def test_dbt_override_does_not_affect_sqlmesh_render(self):
        """An override scoped to 'dbt' must not change SQLMesh output."""
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh
        from engine.services.generation.template_resolver import TemplateResolver
        from engine.services.generation.types import TemplateOverride

        resolver = TemplateResolver(
            use_db_templates=False,
            framework="sqlmesh",
            templates_override={
                "dbt": {
                    "hub_standard": TemplateOverride(sql="# should never appear")
                }
            },
        )
        artifacts, _ = render_sqlmesh(
            self._hub_export(), _runtime_config(), _options(), resolver
        )
        hub_artifact = next(
            (a for a in artifacts if a.entity_type == "hub"), None
        )
        assert hub_artifact is not None
        # Must use the hardcoded generator, not the dbt override.
        assert "hub_model(" in (hub_artifact.content or "")
        assert "should never appear" not in (hub_artifact.content or "")

    def test_no_resolver_uses_hardcoded_generator(self):
        """render_sqlmesh() without a resolver produces the standard output."""
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        artifacts, _ = render_sqlmesh(
            self._hub_export(), _runtime_config(), _options()
        )
        hub_artifact = next(
            (a for a in artifacts if a.entity_type == "hub"), None
        )
        assert hub_artifact is not None
        assert "hub_model(" in (hub_artifact.content or "")
        assert "hub_customer" in (hub_artifact.content or "")


class TestManualRequirement:
    def test_manual_requirement_written_for_unlisted_dialect(self):
        from engine.services.generation.renderers.sqlmesh_renderer import _render_requirements

        rc = _runtime_config(sqlmesh_dialect="mssql", sqlmesh_requirement="sqlmesh[mssql]")
        assert _render_requirements(rc).splitlines() == [
            "datavault4sqlmesh>=0.1.0",
            "sqlmesh[mssql]",
        ]

    def test_empty_requirement_writes_no_driver_line(self):
        from engine.services.generation.renderers.sqlmesh_renderer import _render_requirements

        rc = _runtime_config(sqlmesh_dialect="postgres", sqlmesh_requirement="")
        assert _render_requirements(rc).splitlines() == ["datavault4sqlmesh>=0.1.0"]


class TestNoDialect:
    """A project generated without a dialect: placeholders + a warning."""

    def test_config_yaml_leaves_type_and_dialect_as_placeholders(self):
        import yaml

        from engine.services.generation.renderers.sqlmesh_renderer import _render_config_yaml

        content = _render_config_yaml(_runtime_config(sqlmesh_dialect=None))
        assert "# type: <your connection type" in content
        assert "# dialect: <your SQL dialect" in content
        assert "None" not in content
        parsed = yaml.safe_load(content)
        assert parsed["gateways"]["local"]["connection"] is None
        assert "dialect" not in parsed["model_defaults"]

    def test_config_json_has_no_dialect_key(self):
        import json

        from engine.services.generation.renderers.sqlmesh_renderer import _render_config_json

        parsed = json.loads(_render_config_json(_runtime_config(sqlmesh_dialect=None)))
        assert "dialect" not in parsed

    def test_requirements_have_no_driver_unless_given(self):
        from engine.services.generation.renderers.sqlmesh_renderer import _render_requirements

        assert _render_requirements(_runtime_config(sqlmesh_dialect=None)).splitlines() == [
            "datavault4sqlmesh>=0.1.0"
        ]
        rc = _runtime_config(sqlmesh_dialect=None, sqlmesh_requirement="sqlmesh[mssql]")
        assert _render_requirements(rc).splitlines()[-1] == "sqlmesh[mssql]"

    def test_render_warns_that_dialect_is_not_set(self):
        from engine.services.generation.errors import Code
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        _, issues = render_sqlmesh(
            _minimal_export(), _runtime_config(sqlmesh_dialect=None), _options()
        )
        warnings = [i for i in issues if i.code == Code.SQLMESH_DIALECT_NOT_SET]
        assert len(warnings) == 1
        assert warnings[0].severity == "warning"

    def test_render_does_not_warn_when_dialect_set(self):
        from engine.services.generation.errors import Code
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        _, issues = render_sqlmesh(_minimal_export(), _runtime_config(), _options())
        assert not any(i.code == Code.SQLMESH_DIALECT_NOT_SET for i in issues)


# ---------------------------------------------------------------------------
# Renamed hub business keys (SQLMesh-only derived columns)
# ---------------------------------------------------------------------------


class TestHubKeyRenames:
    """datavault4sqlmesh reads hub business keys from the stage by the hub's
    column names, so renamed keys must be derived in the SQLMesh stage only."""

    @staticmethod
    def _mapping(hub_column, source_column, transformation=None, hub_name="region_h"):
        from engine.services.export.models import HubColumnMapping
        from engine.services.generation.renderers.sqlmesh_renderer import _HubKeyMapping

        return _HubKeyMapping(
            hub_name,
            HubColumnMapping(
                hub_column=hub_column,
                source_column=source_column,
                target_column_transformation=transformation,
            ),
        )

    def test_renamed_key_becomes_derived_column(self):
        from engine.services.generation.renderers.sqlmesh_renderer import _add_hub_key_renames

        derived: dict[str, str] = {}
        _add_hub_key_renames(derived, [self._mapping("REGION_NAME", "R_NAME")], "postgres", "stg")
        assert derived == {"REGION_NAME": "r_name"}

    def test_same_name_key_adds_nothing(self):
        from engine.services.generation.renderers.sqlmesh_renderer import _add_hub_key_renames

        derived: dict[str, str] = {}
        _add_hub_key_renames(derived, [self._mapping("C_CUSTKEY", "C_CUSTKEY")], "postgres", "stg")
        assert derived == {}

    def test_existing_derived_column_is_not_overwritten(self):
        from engine.services.generation.renderers.sqlmesh_renderer import _add_hub_key_renames

        derived = {"REGION_NAME": "UPPER(r_name)"}
        _add_hub_key_renames(derived, [self._mapping("REGION_NAME", "R_NAME")], "postgres", "stg")
        assert derived == {"REGION_NAME": "UPPER(r_name)"}

    def test_transformed_key_reuses_the_in_place_expression(self):
        """The export applies hub key transformations in place (under the
        stage column's name); the renamed hub column takes the same value."""
        from engine.services.generation.renderers.sqlmesh_renderer import _add_hub_key_renames

        derived = {"R_NAME": "TRIM(R_NAME)"}
        mapping = self._mapping("REGION_NAME", "R_NAME", transformation="TRIM(R_NAME)")
        _add_hub_key_renames(derived, [mapping], "postgres", "stg")
        assert derived == {"R_NAME": "TRIM(R_NAME)", "REGION_NAME": "TRIM(R_NAME)"}

    def test_case_preserving_dialect_keeps_source_name(self):
        from engine.services.generation.renderers.sqlmesh_renderer import _add_hub_key_renames

        derived: dict[str, str] = {}
        _add_hub_key_renames(derived, [self._mapping("REGION_NAME", "R_NAME")], "snowflake", "stg")
        assert derived == {"REGION_NAME": "R_NAME"}

    def test_conflicting_renames_report_an_error_naming_both_hubs(self):
        from engine.services.generation.errors import Code
        from engine.services.generation.renderers.sqlmesh_renderer import _add_hub_key_renames

        derived: dict[str, str] = {}
        issues = _add_hub_key_renames(
            derived,
            [
                self._mapping("CODE", "a_code", hub_name="a_h"),
                self._mapping("CODE", "b_code", hub_name="b_h"),
            ],
            "postgres",
            "stg__src__codes",
        )
        assert derived == {"CODE": "a_code"}  # first mapping kept
        (issue,) = issues
        assert issue.severity == "error"
        assert issue.code == Code.SQLMESH_HUB_KEY_RENAME_CONFLICT
        assert "'a_h'" in issue.message and "'b_h'" in issue.message
        assert "'a_code'" in issue.message and "'b_code'" in issue.message
        assert issue.entity is not None and issue.entity.name == "b_h"

    def test_unrenamed_key_also_claims_the_column_name(self):
        """A hub reading CODE as-is conflicts with a hub deriving CODE from another column."""
        from engine.services.generation.renderers.sqlmesh_renderer import _add_hub_key_renames

        derived: dict[str, str] = {}
        issues = _add_hub_key_renames(
            derived,
            [
                self._mapping("CODE", "CODE", hub_name="a_h"),
                self._mapping("CODE", "b_code", hub_name="b_h"),
            ],
            "postgres",
            "stg",
        )
        assert derived == {}
        assert len(issues) == 1

    def test_same_source_for_shared_hub_column_is_no_conflict(self):
        from engine.services.generation.renderers.sqlmesh_renderer import _add_hub_key_renames

        derived: dict[str, str] = {}
        issues = _add_hub_key_renames(
            derived,
            [
                self._mapping("CODE", "a_code", hub_name="a_h"),
                self._mapping("CODE", "A_CODE", hub_name="b_h"),
            ],
            "postgres",
            "stg",
        )
        assert derived == {"CODE": "a_code"}
        assert issues == []

    def test_render_reports_rename_conflict_between_hubs_of_one_stage(self):
        from engine.services.export.models import (
            HashkeyDefinition,
            HubColumnMapping,
            HubDefinition,
            HubSourceInfo,
            ProjectExport,
            StageDefinition,
        )
        from engine.services.generation.errors import Code
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        def hub(name, source_column):
            return HubDefinition(
                hub_name=name,
                hub_type="standard",
                hashkey=HashkeyDefinition(hashkey_name=f"hk_{name}", business_keys=["CODE"]),
                business_key_columns=["CODE"],
                source_tables=[
                    HubSourceInfo(
                        source_table="codes",
                        source_system="src",
                        stage_name="stg__src__codes",
                        business_key_columns=[source_column],
                        is_primary_source=True,
                        column_mappings=[
                            HubColumnMapping(hub_column="CODE", source_column=source_column)
                        ],
                    )
                ],
            )

        export = ProjectExport(
            project_name="test",
            hubs=[hub("a_h", "a_code"), hub("b_h", "b_code")],
            stages=[
                StageDefinition(
                    stage_name="stg__src__codes",
                    source_table="codes",
                    source_schema="src",
                    source_system="src",
                )
            ],
        )
        _, issues = render_sqlmesh(export, _runtime_config(sqlmesh_dialect="postgres"), _options())
        conflicts = [i for i in issues if i.code == Code.SQLMESH_HUB_KEY_RENAME_CONFLICT]
        assert len(conflicts) == 1
        assert conflicts[0].severity == "error"

    def test_stage_render_adds_renames_of_rendered_hubs_only(self):
        from engine.services.export.models import (
            HashkeyDefinition,
            HubColumnMapping,
            HubDefinition,
            HubSourceInfo,
            ProjectExport,
            StageDefinition,
        )
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        def hub(name, hub_type):
            return HubDefinition(
                hub_name=name,
                hub_type=hub_type,
                hashkey=HashkeyDefinition(hashkey_name=f"hk_{name}", business_keys=["REGION_NAME"]),
                business_key_columns=["REGION_NAME"],
                source_tables=[
                    HubSourceInfo(
                        source_table="region",
                        source_system="tpch",
                        stage_name="stg__tpch__region",
                        business_key_columns=["R_NAME"],
                        is_primary_source=True,
                        column_mappings=[
                            HubColumnMapping(hub_column="REGION_NAME", source_column="R_NAME"),
                            HubColumnMapping(hub_column="REF_KEY", source_column="R_COMMENT"),
                        ]
                        if hub_type == "reference"
                        else [HubColumnMapping(hub_column="REGION_NAME", source_column="R_NAME")],
                    )
                ],
            )

        export = ProjectExport(
            project_name="test",
            hubs=[hub("region_h", "standard"), hub("region_rh", "reference")],
            stages=[
                StageDefinition(
                    stage_name="stg__tpch__region",
                    source_table="region",
                    source_schema="tpch_sf1",
                    source_system="tpch",
                )
            ],
        )
        artifacts, _ = render_sqlmesh(export, _runtime_config(sqlmesh_dialect="postgres"), _options())
        stage = next(a for a in artifacts if a.entity_type == "stage")
        assert "'REGION_NAME': 'r_name'," in stage.content
        # The reference hub is not rendered for SQLMesh, so its key isn't added.
        assert "REF_KEY" not in stage.content


class TestLdtsRsrcAliasesMatchConfigJson:
    """Stage ldts/rsrc columns must use the aliases config.json declares.

    Hubs, links and satellites read the ``ldts_alias`` / ``rsrc_alias``
    columns from the stage, so a stage that computes them (``now()``,
    ``!Static``) must name them the same way config.json does.
    """

    @staticmethod
    def _render(stage_load_date, stage_record_source, **runtime_kwargs):
        import json

        from engine.services.export.models import ProjectExport, StageDefinition
        from engine.services.generation.renderers.sqlmesh_renderer import render_sqlmesh

        export = ProjectExport(
            project_name="test",
            stages=[
                StageDefinition(
                    stage_name="stg__crm__customer",
                    source_table="customer",
                    source_schema="crm_raw",
                    source_system="crm",
                    load_date=stage_load_date,
                    record_source=stage_record_source,
                )
            ],
        )
        artifacts, _ = render_sqlmesh(export, _runtime_config(**runtime_kwargs), _options())
        stage = next(a for a in artifacts if a.entity_type == "stage")
        config_json = json.loads(next(a for a in artifacts if a.path == "config.json").content)
        return stage.content, config_json

    def test_derived_aliases_from_project_defaults_are_used_by_stage(self):
        content, config_json = self._render(
            "now()",
            "!Customer",
            default_load_date_value="LOAD_DT",
            default_record_source_value="RSRC_COL",
        )
        assert config_json["ldts_alias"] == "LOAD_DT"
        assert config_json["rsrc_alias"] == "RSRC_COL"
        assert "'LOAD_DT': 'now()'," in content
        assert "'RSRC_COL': \"'Customer'\"," in content
        assert "'ldts':" not in content
        assert "'rsrc':" not in content

    def test_explicit_aliases_win_over_project_defaults(self):
        content, config_json = self._render(
            "now()",
            "!Customer",
            default_load_date_value="LOAD_DT",
            default_record_source_value="RSRC_COL",
            sqlmesh_dv_config=(("ldts_alias", "load_ts"), ("rsrc_alias", "rec_src")),
        )
        assert config_json["ldts_alias"] == "load_ts"
        assert config_json["rsrc_alias"] == "rec_src"
        assert "'load_ts': 'now()'," in content
        assert "'rec_src': \"'Customer'\"," in content

    def test_dv_defaults_without_aliases(self):
        content, config_json = self._render("now()", "!Customer")
        assert "ldts_alias" not in config_json
        assert "rsrc_alias" not in config_json
        assert "'ldts': 'now()'," in content
        assert "'rsrc': \"'Customer'\"," in content

    def test_table_column_differing_from_alias_is_aliased(self):
        """A table's own load date / record source column is exposed under the alias."""
        content, config_json = self._render(
            "LOAD_TS",
            "SRC_SYS",
            default_load_date_value="LOAD_DT",
            default_record_source_value="RSRC_COL",
        )
        assert config_json["ldts_alias"] == "LOAD_DT"
        assert "load_date_col='LOAD_TS'," in content
        # Default dialect duckdb lowercases source references.
        assert "'LOAD_DT': 'load_ts'," in content
        assert "'RSRC_COL': 'src_sys'," in content

    def test_table_column_aliased_against_dv_defaults(self):
        content, _ = self._render("LOAD_TS", "SRC_SYS")
        assert "'ldts': 'load_ts'," in content
        assert "'rsrc': 'src_sys'," in content

    def test_aliased_source_column_keeps_case_on_non_folding_dialects(self):
        content, _ = self._render("LOAD_TS", None, sqlmesh_dialect="snowflake")
        assert "'ldts': 'LOAD_TS'," in content

    @pytest.mark.parametrize("column", ["LOAD_DT", "load_dt"])
    def test_column_matching_alias_needs_no_derived_column(self, column):
        """Same name (ignoring case) is the same column: no alias, no duplicate."""
        content, _ = self._render(column, "RSRC_COL", default_load_date_value="LOAD_DT",
                                  default_record_source_value="RSRC_COL")
        assert "derived_columns" not in content
