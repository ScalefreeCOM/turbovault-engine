"""What a stage reads besides a dbt source: pre-stages (spec §7.2, D9).

A model, a seed, a dbt snapshot or another package's model a stage reads
becomes a pre-stage under its own name; it stays in the dbt project. A
pre-stage reading sources belongs to their system; one reading none (a seed)
to the system its stage's name gives, which a dbt source of that name shares.
A seed's columns take the types its config gives them.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.imports.dbt.test_dbt_mapping import (
    CUSTOMER,
    PROJECT,
    STG_CUSTOMER,
    dv,
    map_manifest,
    model,
    write_manifest,
)

pytestmark = pytest.mark.django_db


def node(
    resource_type: str,
    name: str,
    *,
    package: str = PROJECT,
    path: str | None = None,
    columns: dict[str, dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    unique_id = f"{resource_type}.{package}.{name}"
    return unique_id, {
        "resource_type": resource_type,
        "package_name": package,
        "name": name,
        "original_file_path": path or f"{resource_type}s/{name}.csv",
        "path": f"{name}.csv",
        "database": "analytics",
        "schema": "raw",
        "description": "",
        "columns": {k: {"name": k, **v} for k, v in (columns or {}).items()},
        "config": config or {},
        "unrendered_config": {},
        "fqn": [package, name],
    }


def stage_reading(name: str, target: str, key: str = "CODE"):
    return model(
        name,
        dv(
            "stage",
            f"""
            source_model: {target}
            ldts: LOAD_TS
            rsrc: '!crm'
            hashed_columns:
                hk_country_h: [{key}]
            """,
        ),
        folder="models/staging",
    )


def codes_and_messages(issues, code: str) -> list[str]:
    return [issue.message for issue in issues if issue.code == code]


def test_a_seed_becomes_a_pre_stage_of_its_stages_system(tmp_path):
    seed = node(
        "seed",
        "countries",
        columns={"CODE": {}, "NAME": {"description": "Country name"}},
        config={"column_types": {"code": "varchar(2)", "NAME": "varchar(80)"}},
    )
    stage = stage_reading("stg__crm__countries", "countries")

    domain, issues = map_manifest(
        write_manifest(tmp_path, [STG_CUSTOMER, stage, seed], [CUSTOMER])
    )

    # One system: the seed's stage is named after crm, the dbt source's system
    assert set(domain.source_systems) == {"crm"}
    crm = domain.source_systems["crm"]
    assert crm.schema_name == "crm_raw"
    table = crm.tables["crm|countries"]
    assert table.table_type == "prestage"
    assert {c.name: c.datatype for c in table.columns.values()} == {
        "CODE": "varchar(2)",
        "NAME": "varchar(80)",
    }
    (warning,) = codes_and_messages(issues, "dbt.prestage_maintained_in_dbt")
    assert "the seed stays in the dbt project" in warning
    # Read as a pre-stage, not reported as not imported
    assert not [
        m
        for m in codes_and_messages(issues, "dbt.resource_not_imported")
        if "seed" in m
    ]


def test_a_dbt_snapshot_belongs_to_the_system_of_its_sources(tmp_path):
    snapshot = node(
        "snapshot", "customer_snapshot", path="snapshots/customer_snapshot.sql"
    )
    stage = stage_reading("stg__history__customer", "customer_snapshot", key="ID")

    domain, issues = map_manifest(
        write_manifest(
            tmp_path,
            [stage, snapshot],
            [CUSTOMER],
            parent_map={snapshot[0]: [CUSTOMER[0]]},
        )
    )

    # Its lineage, not its stage's name, gives the system
    assert "crm|customer_snapshot" in domain.source_systems["crm"].tables
    (warning,) = codes_and_messages(issues, "dbt.prestage_maintained_in_dbt")
    assert "the dbt snapshot stays in the dbt project" in warning


def test_another_packages_model_is_named_in_the_report(tmp_path):
    upstream = node(
        "model",
        "base_countries",
        package="shared",
        path="models/base_countries.sql",
        columns={"CODE": {"data_type": "varchar"}},
    )
    stage = stage_reading("stg__ref__base_countries", "base_countries")

    domain, issues = map_manifest(write_manifest(tmp_path, [stage, upstream], []))

    table = domain.source_systems["ref"].tables["ref|base_countries"]
    assert table.table_type == "prestage"
    (warning,) = codes_and_messages(issues, "dbt.prestage_maintained_in_dbt")
    assert "the model of the package 'shared'" in warning


def _unchanged(report) -> bool:
    return all(e.action in ("unchanged", "skip") for e in report.plan.entities)


def test_seed_systems_stay_apart_in_the_project(tmp_path, django_setup):
    from engine.models import Project, SourceSystem

    from tests.imports.dbt.test_dbt_mapping import import_shop

    project = Project.objects.create(name="shop")
    path = write_manifest(
        tmp_path,
        [
            stage_reading("stg__crm__countries", "countries"),
            stage_reading("stg__erp__currencies", "currencies"),
            node("seed", "countries", columns={"CODE": {}}),
            node("seed", "currencies", columns={"CODE": {}}),
        ],
        [],
    )

    import_shop(project, path)
    again = import_shop(project, path)

    # Both seeds live in one schema, but a system is where it lives: each
    # system of pre-stages gets a schema of its name
    systems = SourceSystem.objects.filter(project=project)
    assert {(s.name, s.schema_name) for s in systems} == {
        ("crm", "crm"),
        ("erp", "erp"),
    }
    assert _unchanged(again)
