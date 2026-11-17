"""Safe names in generated output (#450).

Generated files must stay inside the output folder, Data Vault names must be
plain identifiers that differ in more than case, source names with spaces or
hyphens must still give valid YAML and quoted dbt sources, user values must be
escaped wherever they land in YAML or Jinja, and every technical name derived
from a display name must follow one rule.
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
# Naming rules
# ---------------------------------------------------------------------------


class TestTechnicalName:
    @pytest.mark.parametrize(
        ("display_name", "expected"),
        [
            ("crm", "crm"),
            ("SAP ERP", "sap_erp"),
            ("SAP-ERP", "sap_erp"),
            ("Sales & Ops", "sales_ops"),
            ("Müller GmbH", "muller_gmbh"),
            ("already_snake_case", "already_snake_case"),
            ("double__underscore", "double__underscore"),
            ("../../etc", "_etc"),
            ("a/b\\c", "a_b_c"),
            ("", "unnamed"),
            ("&&&", "unnamed"),
        ],
    )
    def test_cases(self, display_name, expected):
        from engine.services.naming import technical_name

        assert technical_name(display_name) == expected

    @pytest.mark.parametrize("display_name", ["..", "../x", "/abs", "a/../b", "C:\\x"])
    def test_never_holds_a_path_separator_or_parent_reference(self, display_name):
        from engine.services.naming import technical_name

        name = technical_name(display_name)
        assert "/" not in name and "\\" not in name and ".." not in name

    def test_folder_source_name_and_stage_prefix_agree(self):
        """One display name gives the same name everywhere it is derived."""
        from engine.services.generation.folder_config import FolderConfig
        from engine.services.prestage_sql import dbt_source_name

        folders = FolderConfig()
        assert dbt_source_name("SAP-ERP") == "sap_erp"
        assert folders.staging_dir("SAP-ERP").name == "sap_erp"
        assert folders.prestaging_dir("SAP-ERP").name == "sap_erp"
        assert folders.source_file("SAP-ERP").name == "source__sap_erp.yml"
        assert folders.raw_vault_dir("Sales & Ops").name == "sales_ops"


class TestDbtProjectName:
    @pytest.mark.parametrize(
        ("display_name", "expected"),
        [
            ("My Project", "my_project"),
            ("Sales-DWH", "sales_dwh"),
            ("2024 DWH", "project_2024_dwh"),
            ("_hidden", "project_hidden"),
            ("", "turbovault_project"),
            (None, "turbovault_project"),
        ],
    )
    def test_starts_with_a_letter(self, display_name, expected):
        from engine.services.naming import dbt_project_name

        assert dbt_project_name(display_name) == expected


class TestDvNames:
    @pytest.mark.parametrize("name", ["hub_customer", "_x", "HK_1", "a"])
    def test_valid(self, name):
        from engine.services.naming import is_dv_name

        assert is_dv_name(name)

    @pytest.mark.parametrize(
        "name",
        ["", "1hub", "hub customer", "hub-customer", "hub/x", "../x", "hub_x\n", None],
    )
    def test_invalid(self, name):
        from engine.services.naming import is_dv_name

        assert not is_dv_name(name)

    def test_case_insensitive_collisions(self):
        from engine.services.naming import case_insensitive_collisions

        assert case_insensitive_collisions(
            ["hub_Customer", "HUB_CUSTOMER", "hub_order", "hub_order"]
        ) == [["hub_Customer", "HUB_CUSTOMER"]]


class TestSourceNames:
    @pytest.mark.parametrize(
        ("name", "needs_quoting"),
        [
            ("customer_id", False),
            ("CUSTOMER_ID", False),
            ("Order Date", True),
            ("order-id", True),
            ("order", True),  # reserved word
            ("CustomerId", True),  # mixed case
        ],
    )
    def test_quoting_reason(self, name, needs_quoting):
        from engine.services.naming import source_name_quoting_reason

        assert (source_name_quoting_reason(name) is not None) is needs_quoting

    def test_only_special_characters_force_identifier_quoting(self):
        """Reserved words and mixed case depend on the warehouse's case folding,
        so dbt's own quoting settings stay in charge of them."""
        from engine.services.naming import needs_identifier_quoting

        assert needs_identifier_quoting("Order Date")
        assert needs_identifier_quoting("order-id")
        assert not needs_identifier_quoting("order")
        assert not needs_identifier_quoting("CustomerId")


# ---------------------------------------------------------------------------
# Escaping filters
# ---------------------------------------------------------------------------


class TestJinjaString:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("control_snap_v1", "'control_snap_v1'"),
            ("it's", "'it\\'s'"),
            ('say "hi"', "'say \\\"hi\\\"'"),
            ("back\\slash", "'back\\\\slash'"),
        ],
    )
    def test_escapes_quotes_and_backslashes(self, value, expected):
        from engine.services.generation.template_resolver import jinja_string

        assert str(jinja_string(value)) == expected

    def test_post_hook_survives_a_quote(self, django_setup):
        """The PIT clean-up hook sits in a double-quoted string inside config()."""
        from engine.services.generation.template_resolver import TemplateResolver

        template = TemplateResolver(use_db_templates=False).get_sql_template("pit")
        sql = template.render(
            snapshot_control_name='it\'s "x"',
            satellite_v0_names=[],
            model_custom_config={},
        )
        hook = next(line for line in sql.splitlines() if "post_hook" in line)
        assert hook == (
            '    post_hook="{{ datavault4dbt.clean_up_pit(\'it\\\'s \\"x\\"\') }}"'
        )


# ---------------------------------------------------------------------------
# Generation with awkward names
# ---------------------------------------------------------------------------


@pytest.fixture
def engine_project(django_setup, db):
    from engine.models import Project

    return Project.objects.create(name="safe_names")


@pytest.fixture
def run(django_setup, engine_project, tmp_path, monkeypatch):
    """Run the dbt pipeline on the given export (bundled templates only)."""
    from engine.services.generation import GenerationOptions, generate
    from engine.services.generation import pipeline as pipeline_module
    from engine.services.generation.stages import build as build_module
    from engine.services.runtime_config import EngineRuntimeConfig

    def _run(export, *, project_name: str = "safe_names", **options):
        monkeypatch.setattr(build_module, "build_export", lambda **_: export)
        monkeypatch.setattr(pipeline_module, "build_export", lambda **_: export)
        out = tmp_path / "out" / "dbt_project"
        report = generate(
            project=engine_project,
            output_type="dbt",
            output_path=out,
            runtime_config=EngineRuntimeConfig(project_name=project_name),
            options=GenerationOptions(use_db_templates=False, **options),
        )
        return report, out

    return _run


@pytest.fixture
def awkward_export(project_export):
    """The conftest export with source system ``SAP-ERP``, subject area
    ``Sales & Ops`` and source columns ``Order Date``, ``order-id`` and
    ``note: x #y`` flowing into the stage and the satellite."""
    from engine.services.export.models import SatelliteColumnDef, SourceColumnDef

    awkward_columns = [
        SourceColumnDef(column_name="Order Date", datatype="DATE"),
        SourceColumnDef(
            column_name="order-id", datatype="STRING", description="Order: id #1"
        ),
        SourceColumnDef(column_name="note: x #y", datatype="STRING"),
    ]
    source = project_export.sources[0]
    source.name = "SAP-ERP"
    source.tables[0].columns.extend(awkward_columns)

    stage = project_export.stages[0]
    stage.source_system = "SAP-ERP"
    stage.columns.extend(awkward_columns)
    stage.hashdiffs[0].columns.extend(["Order Date", "note: x #y"])

    for entity in (
        project_export.hubs[0],
        project_export.links[0],
        project_export.satellites[0],
    ):
        entity.group = "Sales & Ops"
    project_export.satellites[0].columns.extend(
        [
            SatelliteColumnDef(source_column="Order Date"),
            SatelliteColumnDef(source_column="note: x #y"),
            SatelliteColumnDef(source_column="order-id", target_column_name="order_id"),
        ]
    )
    return project_export


def _files(out: Path, pattern: str) -> dict[str, Path]:
    return {path.relative_to(out).as_posix(): path for path in out.rglob(pattern)}


def _metadata(sql: str) -> dict:
    match = YAML_METADATA.search(sql)
    assert match, sql
    return yaml.safe_load(match.group(1))


class TestAwkwardNames:
    def test_generates_valid_yaml_everywhere(self, run, awkward_export):
        report, out = run(awkward_export)
        assert report.status == "success", report.issues
        for path in _files(out, "*.yml").values():
            yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in _files(out, "*.sql").values():
            sql = path.read_text(encoding="utf-8")
            if "yaml_metadata" in sql:
                _metadata(sql)

    def test_source_names_reach_the_metadata_unchanged(self, run, awkward_export):
        _, out = run(awkward_export)
        stage = _metadata(
            (out / "models/02_staging/sap_erp/stg__crm__customer.sql").read_text()
        )
        assert stage["source_model"] == {"sap_erp": "customer"}
        assert stage["hashed_columns"]["hd_sat_customer_details"]["columns"] == [
            "customer_name",
            "Order Date",
            "note: x #y",
        ]
        satellite = _metadata(
            (
                out / "models/03_raw_vault/sales_ops/sat_customer_details_v0.sql"
            ).read_text()
        )
        assert satellite["src_payload"] == [
            "customer_name",
            "Order Date",
            "note: x #y",
            "order_id",
        ]

    def test_sources_yml_quotes_what_only_works_quoted(self, run, awkward_export):
        _, out = run(awkward_export)
        sources = yaml.safe_load(
            (out / "models/01_sources/source__sap_erp.yml").read_text()
        )
        source = sources["sources"][0]
        assert source["name"] == "sap_erp"
        columns = {c["name"]: c for c in source["tables"][0]["columns"]}
        assert columns["Order Date"]["quote"] is True
        assert columns["order-id"]["quote"] is True
        assert columns["note: x #y"]["quote"] is True
        assert "quote" not in columns["customer_id"]
        assert "quoting" not in source["tables"][0]

    def test_quoted_table_identifier(self, run, awkward_export):
        awkward_export.sources[0].tables[0].table_name = "Customer Orders"
        _, out = run(awkward_export)
        sources = yaml.safe_load(
            (out / "models/01_sources/source__sap_erp.yml").read_text()
        )
        table = sources["sources"][0]["tables"][0]
        assert table["name"] == "Customer Orders"
        assert table["quoting"] == {"identifier": True}

    def test_derived_names_are_consistent(self, run, awkward_export):
        _, out = run(awkward_export)
        models = _files(out, "*.sql")
        assert "models/02_staging/sap_erp/stg__crm__customer.sql" in models
        assert "models/03_raw_vault/sales_ops/hub_customer.sql" in models
        hub_sql = models["models/03_raw_vault/sales_ops/hub_customer.sql"].read_text()
        assert "tags=['hub', 'raw_vault', 'sales_ops']" in hub_sql
        stage_sql = models[
            "models/02_staging/sap_erp/stg__crm__customer.sql"
        ].read_text()
        assert "tags=['staging', 'sap_erp']" in stage_sql

    def test_project_name_starts_with_a_letter(self, run, awkward_export):
        _, out = run(awkward_export, project_name="2024 Sales & Ops DWH")
        project = yaml.safe_load((out / "dbt_project.yml").read_text())
        assert project["name"] == "project_2024_sales_ops_dwh"
        assert "project_2024_sales_ops_dwh" in project["models"]

    def test_unusual_source_names_are_a_warning(self, run, awkward_export):
        report, _ = run(awkward_export)
        warnings = [
            i for i in report.issues if i.code == "validate.name.source_needs_quoting"
        ]
        assert len(warnings) == 1
        assert warnings[0].severity == "warning"
        assert "'Order Date'" in warnings[0].message
        assert "'order-id'" in warnings[0].message


# ---------------------------------------------------------------------------
# Validation of Data Vault names
# ---------------------------------------------------------------------------


class TestDvNameValidation:
    def _codes(self, export):
        from engine.services.generation.validators import validate_export

        result = validate_export(export)
        return [(e.code, e.entity_name, e.field) for e in result.errors]

    def test_valid_project_has_no_name_errors(self, project_export):
        assert not [c for c in self._codes(project_export) if c[0].startswith("NAM")]

    @pytest.mark.parametrize(
        ("mutate", "expected"),
        [
            (
                lambda e: setattr(e.hubs[0], "hub_name", "hub customer"),
                ("NAM_001", "hub customer", "hub_name"),
            ),
            (
                lambda e: setattr(e.hubs[0].hashkey, "hashkey_name", "hk-customer"),
                ("NAM_001", "hub_customer", "hashkey"),
            ),
            (
                lambda e: setattr(e.links[0], "link_name", "../lnk"),
                ("NAM_001", "../lnk", "link_name"),
            ),
            (
                lambda e: setattr(e.satellites[0], "hashdiff_name", "hd x"),
                ("NAM_001", "sat_customer_details", "hashdiff_name"),
            ),
            (
                lambda e: e.satellites[0].columns.__setitem__(
                    0,
                    e.satellites[0]
                    .columns[0]
                    .model_copy(update={"target_column_name": "customer name"}),
                ),
                ("NAM_001", "sat_customer_details", "target_column_name"),
            ),
        ],
    )
    def test_invalid_names_are_errors(self, project_export, mutate, expected):
        mutate(project_export)
        assert expected in self._codes(project_export)

    def test_case_collision_between_entities(self, project_export):
        project_export.satellites[0].satellite_name = "HUB_CUSTOMER"
        codes = self._codes(project_export)
        assert ("NAM_002", "hub_customer", "name") in codes
        assert ("NAM_002", "HUB_CUSTOMER", "name") in codes

    def test_case_collision_between_stage_columns(self, project_export):
        project_export.stages[0].hashdiffs[0].hashdiff_name = "HK_CUSTOMER"
        assert ("NAM_002", "stg__crm__customer", "columns") in self._codes(
            project_export
        )

    def test_invalid_name_blocks_generation(self, run, project_export):
        project_export.hubs[0].hub_name = "hub customer"
        report, out = run(project_export)
        assert report.status == "validation_failed"
        assert "validate.name.invalid" in [i.code for i in report.issues]
        assert not out.exists() or not list(out.rglob("*.sql"))


# ---------------------------------------------------------------------------
# Path containment
# ---------------------------------------------------------------------------


class TestPathContainment:
    @pytest.mark.parametrize(
        "hub_name", ["../../escaped", "/abs/escaped", "sub/dir", "..\\escaped"]
    )
    def test_unsafe_model_name_writes_nothing_even_without_validation(
        self, run, project_export, tmp_path, hub_name
    ):
        project_export.hubs[0].hub_name = hub_name
        report, out = run(project_export, skip_validation=True)
        assert "render.unsafe_path" in [i.code for i in report.issues]
        assert report.status != "success"
        assert not list(tmp_path.rglob("escaped*"))
        assert not out.exists() or not list(out.rglob("*.sql"))

    def test_group_cannot_leave_the_models_folder(self, run, project_export, tmp_path):
        for entity in (project_export.hubs[0], project_export.satellites[0]):
            entity.group = "../../../escaped"
        report, out = run(project_export, skip_validation=True)
        assert report.status == "success", report.issues
        assert (out / "models/03_raw_vault/_escaped/hub_customer.sql").exists()
        assert not list(tmp_path.rglob("escaped"))

    def test_unsafe_paths_reports_folders_outside_models(self):
        from pathlib import PurePosixPath

        from engine.services.generation.model_outputs import ModelOutput, ModelOutputs

        outputs = ModelOutputs()
        outputs.add(
            "a",
            ModelOutput(
                kind="hub",
                entity_name="a",
                model_name="a",
                directory=PurePosixPath("models/../../x"),
            ),
        )
        outputs.add(
            "b",
            ModelOutput(
                kind="hub",
                entity_name="b",
                model_name="b",
                directory=PurePosixPath("models/raw"),
            ),
        )
        messages = outputs.unsafe_paths()
        assert len(messages) == 1 and "models/../../x" in messages[0]

    def test_write_stage_refuses_absolute_paths(self, django_setup, tmp_path):
        from engine.services.generation.stages.write import write_artifacts
        from engine.services.generation.types import (
            GeneratedArtifact,
            GenerationOptions,
        )

        outside = tmp_path / "outside.sql"
        written, issues = write_artifacts(
            artifacts=[
                GeneratedArtifact(kind="sql_model", path=str(outside), content="x"),
            ],
            output_type="dbt",
            output_path=tmp_path / "project",
            options=GenerationOptions(),
        )
        assert [i.code for i in issues] == ["write.path_outside_output"]
        assert not outside.exists()

    def test_render_refuses_files_outside_the_temp_tree(self, tmp_path):
        from types import SimpleNamespace

        from engine.services.generation.stages.render import _collect_dbt_artifacts

        root = tmp_path / "render"
        (root / "models").mkdir(parents=True)
        inside = root / "models" / "ok.sql"
        inside.write_text("ok")
        outside = tmp_path / "escaped.sql"
        outside.write_text("x")

        def generated(path: Path) -> SimpleNamespace:
            return SimpleNamespace(
                path=path, entity_type="hub", entity_name="h", file_type="sql"
            )

        report = SimpleNamespace(files=[generated(inside), generated(outside)])
        artifacts, issues = _collect_dbt_artifacts(root, report)
        assert [a.path for a in artifacts] == ["models/ok.sql"]
        assert [i.code for i in issues] == ["write.path_outside_output"]


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class TestImportNameChecks:
    def _domain(self):
        from engine.services.imports.domain import (
            DHub,
            DHubColumn,
            DomainModel,
            DSatellite,
            DSourceColumn,
            DSourceSystem,
            DSourceTable,
        )

        table = DSourceTable(identifier="crm.customer", physical_name="customer")
        table.columns = {
            "customer_id": DSourceColumn(name="customer_id"),
        }
        domain = DomainModel(
            source_systems={
                "crm": DSourceSystem(
                    name="crm", schema_name="raw", tables={"customer": table}
                )
            }
        )
        domain.hubs["hub_customer"] = DHub(
            physical_name="hub_customer",
            hashkey_name="hk_customer",
            columns=[DHubColumn(name="customer_id")],
        )
        domain.satellites["sat_customer"] = DSatellite(physical_name="sat_customer")
        return domain

    def _codes(self, domain):
        from engine.services.imports.validation.names import check_names

        return [(i.code, i.severity) for i in check_names(domain)]

    def test_clean_domain_has_no_issues(self):
        assert self._codes(self._domain()) == []

    def test_invalid_dv_name_is_an_error(self):
        from engine.services.imports.domain import DHubColumn

        domain = self._domain()
        domain.hubs["hub_customer"].columns.append(DHubColumn(name="customer name"))
        assert self._codes(domain) == [("entity.invalid_name", "error")]

    def test_case_collision_is_an_error(self):
        from engine.services.imports.domain import DSatellite

        domain = self._domain()
        domain.satellites["HUB_CUSTOMER"] = DSatellite(physical_name="HUB_CUSTOMER")
        assert self._codes(domain) == [("entity.name_case_collision", "error")]

    def test_unusual_source_name_is_a_warning(self):
        from engine.services.imports.domain import DSourceColumn

        domain = self._domain()
        table = domain.source_systems["crm"].tables["customer"]
        table.columns["Order Date"] = DSourceColumn(name="Order Date")
        table.columns["order-id"] = DSourceColumn(name="order-id")
        assert self._codes(domain) == [("entity.unusual_source_name", "warning")]


# ---------------------------------------------------------------------------
# Template refresh migration
# ---------------------------------------------------------------------------


def _migration():
    import importlib

    return importlib.import_module(
        "engine.migrations.0022_refresh_bundled_templates_safe_names"
    )


class TestRefreshMigration:
    def test_every_entry_is_a_bundled_template_and_now_superseded(self, django_setup):
        from engine.services.generation.template_resolver import bundled_templates

        earlier = __import__("importlib").import_module(
            "engine.migrations.0020_refresh_bundled_templates"
        )
        bundled = {
            ("dbt", t.entity_type, t.template_type): t for t in bundled_templates("dbt")
        }
        for key, hashes in _migration().PRE_450_BUNDLED_HASHES.items():
            assert key in bundled, key
            current = earlier._content_hash(bundled[key].path.read_text("utf-8"))
            assert current not in hashes, f"{key} would be refreshed on every run"

    def test_refreshes_unedited_and_keeps_edited_templates(
        self, django_setup, db, monkeypatch
    ):
        from django.apps import apps
        from engine.models.templates import ModelTemplate
        from engine.services.generation.template_resolver import bundled_templates

        migration = _migration()
        earlier = __import__("importlib").import_module(
            "engine.migrations.0020_refresh_bundled_templates"
        )
        old_content = "[# the pre-#450 stage template #]\n"
        monkeypatch.setitem(
            migration.PRE_450_BUNDLED_HASHES,
            ("dbt", "stage", "sql"),
            frozenset({earlier._content_hash(old_content)}),
        )
        ModelTemplate.objects.filter(entity_type="stage").delete()
        unedited = ModelTemplate.objects.create(
            name="stage unedited",
            entity_type="stage",
            sql_template_content=old_content.replace("\n", "\r\n"),
            priority=0,
        )
        edited = ModelTemplate.objects.create(
            name="stage edited",
            entity_type="stage",
            sql_template_content="[# my own stage #]\n",
            priority=1,
        )

        migration.refresh_bundled_templates(apps, None)

        current = next(
            t
            for t in bundled_templates("dbt")
            if (t.entity_type, t.template_type) == ("stage", "sql")
        ).path.read_text(encoding="utf-8")
        unedited.refresh_from_db()
        edited.refresh_from_db()
        assert unedited.sql_template_content == current
        assert edited.sql_template_content == "[# my own stage #]\n"
