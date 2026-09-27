"""Descriptions, from the metadata to the generated dbt docs.

Source systems, tables and columns carry descriptions, and so do hubs, links,
satellites, reference tables and their columns. A Raw Vault column without its
own description takes the one of the source column it is loaded from.

Descriptions are free text, so the generated YAML is parsed back here: a quote,
a colon or a line break must come out exactly as it went in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.django_db

# Everything YAML gives a meaning to, in one description.
TRICKY = 'The customer\'s "number": #1 key\n- from CRM, see {{ doc("x") }}'


@pytest.fixture
def documented_project(django_setup, db):
    from engine.models import (
        Hub,
        HubColumn,
        Link,
        LinkColumn,
        Project,
        Satellite,
        SatelliteColumn,
        SourceColumn,
        SourceSystem,
        SourceTable,
    )
    from engine.services.model_import_schema import ModelImportSchema
    from engine.services.model_import_service import import_model

    project = Project.objects.create(name="documented")
    crm = SourceSystem.objects.create(
        project=project,
        schema_name="crm_raw",
        name="CRM",
        database_name="ops",
        description="The CRM system",
    )

    def table(name: str, columns: dict[str, str | None], description=None):
        source_table = SourceTable.objects.create(
            project=project,
            source_system=crm,
            physical_table_name=name,
            record_source_value=f"CRM.{name}",
            load_date_value="LOAD_DATE",
            description=description,
        )
        for column, column_description in columns.items():
            SourceColumn.objects.create(
                source_table=source_table,
                source_column_physical_name=column,
                source_column_datatype="VARCHAR",
                description=column_description,
            )

    table(
        "customer",
        {"C_CUSTKEY": TRICKY, "C_NAME": "Full name", "C_PHONE": None},
        description="One row per customer",
    )
    table(
        "orders",
        {"O_ORDERKEY": None, "O_CUSTKEY": None, "O_COMMENT": "Free text"},
    )

    result = import_model(
        project.name,
        ModelImportSchema.model_validate(
            {
                "hubs": [
                    {
                        "name": "CUSTOMER_H",
                        "business_keys": ["C_CUSTKEY"],
                        "source_table": "customer",
                    },
                    {
                        "name": "ORDER_H",
                        "business_keys": ["O_ORDERKEY"],
                        "source_table": "orders",
                    },
                ],
                "links": [
                    {
                        "name": "ORDER_CUSTOMER_L",
                        "hubs": ["ORDER_H", "CUSTOMER_H"],
                        "source_table": "orders",
                        "hub_source_columns": {"CUSTOMER_H": "O_CUSTKEY"},
                    }
                ],
                "satellites": [
                    {
                        "name": "CUSTOMER_S",
                        "parent_hub": "CUSTOMER_H",
                        "columns": ["C_NAME", "C_PHONE"],
                        "source_table": "customer",
                    }
                ],
            }
        ),
    )
    assert result.errors == [], result.errors

    Hub.objects.filter(project=project, hub_physical_name="CUSTOMER_H").update(
        description="Everyone who ever ordered"
    )
    Link.objects.filter(project=project).update(description="Who placed an order")
    Satellite.objects.filter(project=project).update(description="Customer details")
    # C_PHONE has no source description; give the satellite column its own.
    SatelliteColumn.objects.filter(
        satellite__project=project,
        staging_column__source_column__source_column_physical_name="C_PHONE",
    ).update(description="Phone, as dialled")
    link = Link.objects.get(project=project)
    LinkColumn.objects.create(link=link, column_name="O_COMMENT", column_type="payload")
    assert HubColumn.objects.filter(hub__project=project).exists()
    return project


def _generate(project, tmp_path: Path) -> dict[str, str]:
    from engine.services.generation import generate

    report = generate(
        project=project, output_type="dbt", output_path=tmp_path / "dbt_out"
    )
    assert report.status in ("success", "partial_success"), report.issues
    return {
        Path(artifact.path).name: Path(artifact.path).read_text(encoding="utf-8")
        for artifact in report.artifacts
    }


def _satellite_yml(files: dict[str, str], name: str) -> str:
    """The satellite's own model (named by the project's v0 pattern), not its v1 view."""
    return next(
        content
        for file_name, content in files.items()
        if file_name.startswith(name)
        and file_name.endswith(".yml")
        and "_v1" not in file_name
    )


def _columns(model_yaml: str) -> dict[str, str]:
    model = yaml.safe_load(model_yaml)["models"][0]
    return {column["name"]: column.get("description") for column in model["columns"]}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_carries_source_descriptions(documented_project):
    from engine.services.export.builder import ModelBuilder

    export = ModelBuilder(documented_project).build()
    crm = export.sources[0]
    assert crm.description == "The CRM system"
    customer = next(t for t in crm.tables if t.table_name == "customer")
    assert customer.description == "One row per customer"
    columns = {c.column_name: c.description for c in customer.columns}
    assert columns == {"C_CUSTKEY": TRICKY, "C_NAME": "Full name", "C_PHONE": None}


def test_raw_vault_columns_inherit_the_source_description(documented_project):
    from engine.services.export.builder import ModelBuilder

    export = ModelBuilder(documented_project).build()
    hub = next(h for h in export.hubs if h.hub_name == "CUSTOMER_H")
    assert hub.description == "Everyone who ever ordered"
    docs = hub.column_descriptions["C_CUSTKEY"]
    # Inherited, not copied: the column has none of its own.
    assert docs.description is None
    assert docs.source_description == TRICKY

    satellite = export.satellites[0]
    columns = {c.source_column: c for c in satellite.columns}
    assert columns["C_NAME"].description is None
    assert columns["C_NAME"].source_description == "Full name"
    assert columns["C_PHONE"].description == "Phone, as dialled"


def test_a_columns_own_description_wins(documented_project):
    from engine.models import HubColumn
    from engine.services.export.builder import ModelBuilder

    HubColumn.objects.filter(
        hub__project=documented_project, column_name="C_CUSTKEY"
    ).update(description="Customer number")
    hub = next(
        h
        for h in ModelBuilder(documented_project).build().hubs
        if h.hub_name == "CUSTOMER_H"
    )
    assert hub.column_descriptions["C_CUSTKEY"].effective == "Customer number"


# ---------------------------------------------------------------------------
# Generated dbt YAML
# ---------------------------------------------------------------------------


def test_sources_yml_carries_every_description(documented_project, tmp_path):
    files = _generate(documented_project, tmp_path)
    source = yaml.safe_load(files["source__crm.yml"])["sources"][0]

    assert source["description"] == "The CRM system"
    tables = {t["name"]: t for t in source["tables"]}
    assert tables["customer"]["description"] == "One row per customer"
    # A table without one keeps the generated default, now naming its system.
    assert tables["orders"]["description"] == "Source table from CRM"
    columns = {c["name"]: c for c in tables["customer"]["columns"]}
    assert columns["C_CUSTKEY"]["description"] == TRICKY
    assert "description" not in columns["C_PHONE"]


def test_model_yml_uses_own_then_inherited_then_default(documented_project, tmp_path):
    files = _generate(documented_project, tmp_path)

    hub = yaml.safe_load(files["CUSTOMER_H.yml"])["models"][0]
    assert hub["description"] == "Everyone who ever ordered"
    assert _columns(files["CUSTOMER_H.yml"])["C_CUSTKEY"] == TRICKY
    # A hub without descriptions keeps the generated ones.
    assert _columns(files["ORDER_H.yml"])["O_ORDERKEY"] == "Business key column"

    satellite_yml = _satellite_yml(files, "CUSTOMER_S")
    satellite = yaml.safe_load(satellite_yml)["models"][0]
    assert satellite["description"] == "Customer details"
    columns = _columns(satellite_yml)
    assert columns["C_NAME"] == "Full name"
    assert columns["C_PHONE"] == "Phone, as dialled"

    link = yaml.safe_load(files["ORDER_CUSTOMER_L.yml"])["models"][0]
    assert link["description"] == "Who placed an order"


def test_stage_yml_documents_described_columns(documented_project, tmp_path):
    files = _generate(documented_project, tmp_path)
    stage = yaml.safe_load(files["stg__crm__customer.yml"])["models"][0]

    assert stage["description"] == "One row per customer"
    columns = _columns(files["stg__crm__customer.yml"])
    assert columns["C_CUSTKEY"] == TRICKY
    # Undocumented source columns aren't listed.
    assert "C_PHONE" not in columns


def test_generation_without_descriptions_is_unchanged(documented_project, tmp_path):
    """A project that sets none keeps exactly the generated defaults."""
    from engine.models import (
        Hub,
        Link,
        Satellite,
        SatelliteColumn,
        SourceColumn,
        SourceSystem,
        SourceTable,
    )

    for model in (SourceSystem, SourceTable, Hub, Link, Satellite):
        model.objects.filter(project=documented_project).update(description=None)
    SourceColumn.objects.filter(source_table__project=documented_project).update(
        description=None
    )
    SatelliteColumn.objects.filter(satellite__project=documented_project).update(
        description=None
    )

    files = _generate(documented_project, tmp_path)
    assert '    description: "Standard hub for CUSTOMER_H"\n' in files["CUSTOMER_H.yml"]
    assert '        description: "Business key column"\n' in files["CUSTOMER_H.yml"]
    assert '        description: "Payload column"\n' in _satellite_yml(
        files, "CUSTOMER_S"
    )
    assert (
        '    description: "Staging model for customer from CRM"\n'
        in files["stg__crm__customer.yml"]
    )
    assert "description" not in yaml.safe_load(files["source__crm.yml"])["sources"][0]


# ---------------------------------------------------------------------------
# DBML
# ---------------------------------------------------------------------------


def test_dbml_notes_carry_descriptions(documented_project):
    from engine.services.export.builder import ModelBuilder
    from engine.services.export.exporters.dbml_exporter import DBMLExporter

    dbml = DBMLExporter().export(ModelBuilder(documented_project).build())

    assert "C_NAME varchar [note: 'Full name']" in dbml
    assert "  Note: 'Everyone who ever ordered'" in dbml
    # A line break makes it a triple-quoted string.
    assert "C_CUSTKEY varchar [note: '''The customer's" in dbml
