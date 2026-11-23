"""Satellite and stage options.

Satellites: the stage's hash diff column and its alias inside the satellite,
whether they get a v1 view, and the view's load end date, is_current flag and
payload. Stages: include_source_columns, ghost records and a sequence column,
inherited from table over source system to project; columns the source no
longer has (missing_columns). Derived columns may shadow a source column.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from django.core.exceptions import ValidationError

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(django_setup, db):
    """CUSTOMER_H loaded from CUSTOMER, with the satellite CUSTOMER_S."""
    from engine.models import (
        Hub,
        HubColumn,
        HubSourceMapping,
        Project,
        Satellite,
        SatelliteColumn,
        SourceColumn,
        SourceSystem,
        SourceTable,
    )
    from engine.services.staging_service import get_or_create_staging_column

    project = Project.objects.create(name="options")
    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM"
    )
    customer = SourceTable.objects.create(
        project=project,
        source_system=crm,
        physical_table_name="CUSTOMER",
        load_date_value="LOAD_TS",
    )
    staging = {
        name: get_or_create_staging_column(
            SourceColumn.objects.create(
                source_table=customer,
                source_column_physical_name=name,
                source_column_datatype="VARCHAR",
            )
        )
        for name in ("C_ID", "C_NAME", "C_CITY", "LOAD_TS")
    }
    hub = Hub.objects.create(
        project=project,
        hub_physical_name="CUSTOMER_H",
        hub_hashkey_name="hk_customer_h",
        create_effectivity_satellite=False,
    )
    HubSourceMapping.objects.create(
        hub_column=HubColumn.objects.create(hub=hub, column_name="CUSTOMER_ID"),
        staging_column=staging["C_ID"],
        is_primary_source=True,
    )
    satellite = Satellite.objects.create(
        project=project,
        satellite_physical_name="CUSTOMER_S",
        parent_hub=hub,
        source_table=customer,
    )
    SatelliteColumn.objects.create(
        satellite=satellite, staging_column=staging["C_NAME"]
    )
    return project


def _get(model: str, **lookup):
    from engine import models

    return getattr(models, model).objects.get(**lookup)


def _update(model: str, lookup: dict, **values) -> None:
    from engine import models

    getattr(models, model).objects.filter(**lookup).update(**values)


def _generate(project, tmp_path: Path, runtime_config=None, **options):
    from engine.services.generation import generate
    from engine.services.generation.types import GenerationOptions

    return generate(
        project=project,
        output_type="dbt",
        output_path=tmp_path / "dbt",
        runtime_config=runtime_config,
        options=GenerationOptions(**options),
    )


def _issues(report, code: str) -> list:
    return [issue for issue in report.issues if issue.code == code]


def _yaml_metadata(path: Path) -> dict:
    """A model's yaml_metadata block, parsed as datavault4dbt will."""
    sql = path.read_text(encoding="utf-8")
    block = re.search(
        r"\{%- set yaml_metadata -%\}\n(.*?)\{%- endset -%\}", sql, re.DOTALL
    )
    assert block, sql
    return yaml.safe_load(block.group(1))


def _models(tmp_path: Path) -> Path:
    return tmp_path / "dbt" / "models"


# ---------------------------------------------------------------------------
# Hash diff name and alias
# ---------------------------------------------------------------------------


def test_the_hash_diff_name_defaults_to_the_pattern(project, tmp_path):
    _generate(project, tmp_path)

    sat = _yaml_metadata(_models(tmp_path) / "30_raw_vault" / "CUSTOMER_S_v0.sql")
    assert sat["src_hashdiff"] == "hd_CUSTOMER_S"


def test_a_stored_hash_diff_name_and_alias(project, tmp_path):
    _update(
        "Satellite",
        {"satellite_physical_name": "CUSTOMER_S"},
        hashdiff_name="hd_customer_details",
        hashdiff_alias="hashdiff",
    )

    report = _generate(project, tmp_path)
    assert report.status == "success", report.issues

    models = _models(tmp_path)
    stage = _yaml_metadata(models / "20_staging" / "crm" / "stg__crm__customer.sql")
    assert "hd_customer_details" in stage["hashed_columns"]
    sat = _yaml_metadata(models / "30_raw_vault" / "CUSTOMER_S_v0.sql")
    assert sat["src_hashdiff"] == {
        "source_column": "hd_customer_details",
        "alias": "hashdiff",
    }
    v1 = _yaml_metadata(models / "30_raw_vault" / "CUSTOMER_S_v1.sql")
    assert v1["hashdiff"] == "hashdiff"


def test_two_hash_diffs_of_one_name_must_hash_the_same_columns(project, tmp_path):
    from engine.models import Satellite, SatelliteColumn, StagingColumn

    customer = _get("SourceTable", physical_table_name="CUSTOMER")
    other = Satellite.objects.create(
        project=project,
        satellite_physical_name="CUSTOMER_CITY_S",
        parent_hub=_get("Hub", hub_physical_name="CUSTOMER_H"),
        source_table=customer,
        hashdiff_name="hd_customer",
    )
    SatelliteColumn.objects.create(
        satellite=other,
        staging_column=StagingColumn.objects.get(
            source_column__source_column_physical_name="C_CITY"
        ),
    )
    _update(
        "Satellite",
        {"satellite_physical_name": "CUSTOMER_S"},
        hashdiff_name="hd_customer",
    )

    report = _generate(project, tmp_path, dry_run=True)

    (issue,) = _issues(report, "validate.stage.duplicate_hashdiff")
    assert issue.severity == "error"
    assert "hd_customer" in issue.message


def test_a_non_historized_satellite_has_no_hash_diff(project):
    satellite = _get("Satellite", satellite_physical_name="CUSTOMER_S")
    satellite.satellite_type = "non_historized"
    satellite.hashdiff_name = "hd_x"

    with pytest.raises(ValidationError, match="no hash diff"):
        satellite.full_clean()


# ---------------------------------------------------------------------------
# v1 views
# ---------------------------------------------------------------------------


def test_the_v1_view_options(project, tmp_path):
    _update(
        "Satellite",
        {"satellite_physical_name": "CUSTOMER_S"},
        v1_ledts_alias="valid_to",
        v1_add_is_current_flag=False,
        v1_include_payload=False,
    )

    _generate(project, tmp_path)

    v1 = _yaml_metadata(_models(tmp_path) / "30_raw_vault" / "CUSTOMER_S_v1.sql")
    assert v1["ledts_alias"] == "valid_to"
    assert v1["add_is_current_flag"] is False
    assert v1["include_payload"] is False


def test_the_v1_view_defaults_are_unchanged(project, tmp_path):
    _generate(project, tmp_path)

    v1 = _yaml_metadata(_models(tmp_path) / "30_raw_vault" / "CUSTOMER_S_v1.sql")
    assert v1 == {
        "sat_v0": "CUSTOMER_S_v0",
        "hashkey": "hk_customer_h",
        "hashdiff": "hd_CUSTOMER_S",
        "add_is_current_flag": True,
    }


@pytest.mark.parametrize(
    ("project_setting", "own_setting", "expected"),
    [
        (True, None, True),
        (True, False, False),
        (False, True, True),
        (False, None, False),
    ],
)
def test_a_satellite_decides_on_its_v1_view(
    project, tmp_path, project_setting, own_setting, expected
):
    _update(
        "Satellite",
        {"satellite_physical_name": "CUSTOMER_S"},
        create_v1_view=own_setting,
    )

    report = _generate(project, tmp_path, generate_satellite_v1_views=project_setting)

    v1 = _models(tmp_path) / "30_raw_vault" / "CUSTOMER_S_v1.sql"
    assert v1.exists() is expected
    assert report.plan.by_entity_type["satellite"] == (4 if expected else 2)


def test_a_reference_table_needs_its_satellites_v1_views(project, tmp_path):
    from engine.models import (
        Hub,
        HubColumn,
        HubSourceMapping,
        ReferenceTable,
        Satellite,
        SatelliteColumn,
        StagingColumn,
    )

    customer = _get("SourceTable", physical_table_name="CUSTOMER")
    reference_hub = Hub.objects.create(
        project=project,
        hub_physical_name="CITY_RH",
        hub_type=Hub.HubType.REFERENCE,
        create_effectivity_satellite=False,
    )
    city = StagingColumn.objects.get(
        source_column__source_column_physical_name="C_CITY"
    )
    HubSourceMapping.objects.create(
        hub_column=HubColumn.objects.create(
            hub=reference_hub,
            column_name="CITY",
            column_type=HubColumn.ColumnType.REFERENCE_KEY,
        ),
        staging_column=city,
        is_primary_source=True,
    )
    reference_satellite = Satellite.objects.create(
        project=project,
        satellite_physical_name="CITY_RS",
        satellite_type=Satellite.SatelliteType.REFERENCE,
        parent_hub=reference_hub,
        source_table=customer,
        create_v1_view=False,
    )
    SatelliteColumn.objects.create(
        satellite=reference_satellite,
        staging_column=StagingColumn.objects.get(
            source_column__source_column_physical_name="C_NAME"
        ),
    )
    ReferenceTable.objects.create(
        project=project,
        reference_table_physical_name="CITY_R",
        reference_hub=reference_hub,
        historization_type=ReferenceTable.HistorizationType.LATEST,
    )

    report = _generate(project, tmp_path, dry_run=True)

    (issue,) = _issues(report, "validate.reference_table.satellite_without_v1")
    assert issue.severity == "warning"
    assert "CITY_RS" in issue.message


# ---------------------------------------------------------------------------
# Stage options
# ---------------------------------------------------------------------------


def _stage(tmp_path: Path) -> dict:
    return _yaml_metadata(
        _models(tmp_path) / "20_staging" / "crm" / "stg__crm__customer.sql"
    )


def test_stage_options_default_to_datavault4dbts_defaults(project, tmp_path):
    _generate(project, tmp_path)

    stage = _stage(tmp_path)
    for key in (
        "include_source_columns",
        "enable_ghost_records",
        "sequence",
        "missing_columns",
    ):
        assert key not in stage


def test_stage_options_from_the_project(project, tmp_path):
    from engine.services.runtime_config import EngineRuntimeConfig

    config = EngineRuntimeConfig(
        project_name="options",
        include_source_columns=False,
        enable_ghost_records=False,
    )
    _generate(project, tmp_path, runtime_config=config)

    stage = _stage(tmp_path)
    assert stage["include_source_columns"] is False
    assert stage["enable_ghost_records"] is False


def test_a_table_overrides_its_system_which_overrides_the_project(project, tmp_path):
    from engine.services.runtime_config import EngineRuntimeConfig

    _update("SourceSystem", {"name": "CRM"}, include_source_columns=False)
    _update(
        "SourceTable",
        {"physical_table_name": "CUSTOMER"},
        enable_ghost_records=False,
        sequence_column="EXTRACT_SEQ",
    )
    config = EngineRuntimeConfig(project_name="options", enable_ghost_records=True)

    _generate(project, tmp_path, runtime_config=config)

    stage = _stage(tmp_path)
    assert stage["include_source_columns"] is False  # the system's
    assert stage["enable_ghost_records"] is False  # the table's
    assert stage["sequence"] == "EXTRACT_SEQ"


def test_a_missing_column_is_added_by_the_stage(project, tmp_path):
    _update(
        "SourceColumn",
        {"source_column_physical_name": "C_CITY"},
        is_missing=True,
        source_column_datatype="VARCHAR(100)",
    )

    _generate(project, tmp_path)

    assert _stage(tmp_path)["missing_columns"] == {"C_CITY": "VARCHAR(100)"}
    sources = yaml.safe_load(
        (_models(tmp_path) / "10_sources" / "source__crm.yml").read_text(
            encoding="utf-8"
        )
    )
    (table,) = sources["sources"][0]["tables"]
    assert "C_CITY" not in [column["name"] for column in table["columns"]]


# ---------------------------------------------------------------------------
# Derived columns that shadow a source column
# ---------------------------------------------------------------------------


def _shadow_c_name(project):
    from engine.models import DerivedColumn

    derived = DerivedColumn(
        project=project,
        source_table=_get("SourceTable", physical_table_name="CUSTOMER"),
        column_name="C_NAME",
        expression="TRIM(C_NAME)",
        datatype="VARCHAR",
    )
    derived.full_clean()
    derived.save()
    return derived


def test_a_shadowing_derived_column_replaces_the_source_column(project, tmp_path):
    _shadow_c_name(project)

    report = _generate(project, tmp_path)
    assert report.status == "success", report.issues

    stage = _stage(tmp_path)
    assert stage["derived_columns"] == {
        "C_NAME": {
            "value": "TRIM(C_NAME)",
            "datatype": "VARCHAR",
            "src_cols_required": "C_NAME",
        }
    }
    # The satellite maps the source column, which now carries the derived value
    sat = _yaml_metadata(_models(tmp_path) / "30_raw_vault" / "CUSTOMER_S_v0.sql")
    assert sat["src_payload"] == ["C_NAME"]


def test_a_transformation_of_a_shadowed_column_builds_on_the_derived_value(
    project, tmp_path
):
    from engine.models import HubColumn, HubSourceMapping, StagingColumn

    _shadow_c_name(project)
    hub = _get("Hub", hub_physical_name="CUSTOMER_H")
    name_key = HubColumn.objects.create(
        hub=hub,
        column_name="C_NAME",
        target_column_transformation="UPPER([[source_column]])",
        target_column_datatype="VARCHAR",
    )
    HubSourceMapping.objects.create(
        hub_column=name_key,
        staging_column=StagingColumn.objects.get(
            source_column__source_column_physical_name="C_NAME"
        ),
        is_primary_source=True,
    )

    _generate(project, tmp_path)

    derived = _stage(tmp_path)["derived_columns"]
    assert list(derived) == ["C_NAME"]
    assert derived["C_NAME"]["value"] == "UPPER((TRIM(C_NAME)))"


def test_a_json_export_round_trips_a_shadowing_derived_column(project, tmp_path):
    from engine.models import DerivedColumn, Project, SourceColumn
    from engine.services.export.builder import ModelBuilder
    from engine.services.imports import ImportOptions, JsonSource, import_metadata

    _shadow_c_name(project)
    path = tmp_path / "export.json"
    path.write_text(
        json.dumps(ModelBuilder(project).build().model_dump(mode="json"), default=str),
        encoding="utf-8",
    )
    target = Project.objects.create(name="copy")

    report = import_metadata(
        project=target,
        source=JsonSource(path=path),
        options=ImportOptions(skip_snapshots=True),
    )

    assert report.status == "success", report.issues
    assert SourceColumn.objects.filter(
        source_table__project=target, source_column_physical_name="C_NAME"
    ).exists()
    assert DerivedColumn.objects.get(
        project=target, column_name="C_NAME"
    ).expression == ("TRIM(C_NAME)")


def test_a_prejoined_column_cannot_be_shadowed(project):
    from engine.models import (
        DerivedColumn,
        PrejoinDefinition,
        PrejoinExtractionColumn,
        SourceColumn,
        SourceTable,
    )

    customer = _get("SourceTable", physical_table_name="CUSTOMER")
    nation = SourceTable.objects.create(
        project=project,
        source_system=customer.source_system,
        physical_table_name="NATION",
    )
    n_name = SourceColumn.objects.create(
        source_table=nation,
        source_column_physical_name="N_NAME",
        source_column_datatype="VARCHAR",
    )
    prejoin = PrejoinDefinition.objects.create(
        project=project, source_table=customer, prejoin_target_table=nation
    )
    PrejoinExtractionColumn.objects.create(
        prejoin=prejoin, source_column=n_name, prejoin_target_column_alias="NATION_NAME"
    )

    derived = DerivedColumn(
        project=project,
        source_table=customer,
        column_name="nation_name",
        expression="'x'",
    )
    with pytest.raises(ValidationError, match="prejoin"):
        derived.full_clean()
