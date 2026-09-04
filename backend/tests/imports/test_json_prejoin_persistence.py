"""Regression tests for prejoins on the JSON import path.

Two defects, both pre-existing and both visible in the engine's own
export -> import round trip:

1. Prejoins were parsed and then discarded. `json_parser` populated
   `DomainModel.prejoins`, but neither the planner nor the executor ever looked
   at it ("full prejoin support is a follow-up",
   `engine/services/imports/domain.py`). Importing an export whose
   `stages[].prejoins[]` was non-empty left `PrejoinDefinition.objects.count()`
   at 0.

2. A link business key could not be marked as prejoin-fed.
   `LinkColumnMapping` carried only `source_column_name`, so when a link's hub
   business key was actually fed by a prejoin extraction the export named a
   column that does not exist on the owning table — and on import
   `_ensure_source_column` created it, polluting the source table with phantom
   columns. The generated stage then hashed columns that do not exist.

The scenario below is the canonical one: `order` (WEBSHOP) links to a customer
hub whose business key is `SYSID` + `KUNDENNUMMER`, but `order` only carries an
opaque `KUNDEN_REF`. The real business keys have to be prejoined across from
`kunden` (CRM) to compute the hub hashkey.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine.models import (
    HubColumn,
    Link,
    LinkHubSourceMapping,
    PrejoinDefinition,
    PrejoinExtractionColumn,
    Project,
    SourceColumn,
    SourceSystem,
    SourceTable,
)
from engine.services.export.builder import ModelBuilder
from engine.services.imports import (
    ImportOptions,
    ImportReport,
    JsonSource,
    import_metadata,
)
from engine.services.model_import_schema import ModelImportSchema
from engine.services.model_import_service import import_model
from engine.services.staging_service import get_or_create_staging_column

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixture model
# ---------------------------------------------------------------------------

ORDER_COLUMNS = ("ORDER_ID", "KUNDEN_REF", "AMOUNT")
KUNDEN_COLUMNS = ("KUNDEN_REF", "SYSID", "KUNDENNUMMER", "NAME")


def _table(
    project: Project, system: SourceSystem, name: str, columns: tuple[str, ...]
) -> SourceTable:
    table = SourceTable.objects.create(
        project=project,
        source_system=system,
        physical_table_name=name,
        record_source_value=f"{system.name}.{name}",
        load_date_value="LOAD_DATE",
    )
    for col in columns:
        SourceColumn.objects.create(
            source_table=table,
            source_column_physical_name=col,
            source_column_datatype="VARCHAR",
        )
    return table


def _column(table: SourceTable, name: str) -> SourceColumn:
    return SourceColumn.objects.get(
        source_table=table, source_column_physical_name=name
    )


def _build_source_project(name: str = "prejoin-src") -> Project:
    """A model whose link business key is fed by a prejoin.

    WEBSHOP.order --(KUNDEN_REF)--> CRM.kunden, extracting SYSID and
    KUNDENNUMMER, which together are KUNDE_H's business key.
    """
    project = Project.objects.create(name=name)

    webshop = SourceSystem.objects.create(
        project=project, schema_name="webshop_raw", name="WEBSHOP", database_name="shop"
    )
    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM", database_name="ops"
    )

    order = _table(project, webshop, "order", ORDER_COLUMNS)
    kunden = _table(project, crm, "kunden", KUNDEN_COLUMNS)

    prejoin = PrejoinDefinition.objects.create(
        project=project,
        source_table=order,
        prejoin_target_table=kunden,
        prejoin_operator=PrejoinDefinition.JoinOperator.AND,
    )
    prejoin.prejoin_condition_source_column.add(_column(order, "KUNDEN_REF"))
    prejoin.prejoin_condition_target_column.add(_column(kunden, "KUNDEN_REF"))

    sysid_ext = PrejoinExtractionColumn.objects.create(
        prejoin=prejoin, source_column=_column(kunden, "SYSID")
    )
    kdnr_ext = PrejoinExtractionColumn.objects.create(
        prejoin=prejoin,
        source_column=_column(kunden, "KUNDENNUMMER"),
        # An alias on one of the two, so the alias path is covered as well.
        prejoin_target_column_alias="KUNDEN_NR",
    )

    result = import_model(
        project.name,
        ModelImportSchema.model_validate(
            {
                "hubs": [
                    {
                        "name": "ORDER_H",
                        "business_keys": ["ORDER_ID"],
                        "source_table": "order",
                    },
                    {
                        "name": "KUNDE_H",
                        "business_keys": ["SYSID", "KUNDENNUMMER"],
                        "source_table": "kunden",
                    },
                ],
                "links": [
                    {
                        "name": "ORDER_KUNDE_L",
                        "link_type": "standard",
                        "hubs": ["ORDER_H", "KUNDE_H"],
                        "source_table": "order",
                    }
                ],
            }
        ),
    )
    assert result.errors == [], result.errors

    # `import_model` wired KUNDE_H's business keys off `order` directly, which is
    # exactly the phantom-column situation this change exists to prevent. Rewire
    # them to the prejoin extractions, as a user would in Django Admin.
    link = Link.objects.get(project=project, link_physical_name="ORDER_KUNDE_L")
    kunde_ref = link.hub_references.get(hub__hub_physical_name="KUNDE_H")
    for column_name, extraction in (
        ("SYSID", sysid_ext),
        ("KUNDENNUMMER", kdnr_ext),
    ):
        hub_column = HubColumn.objects.get(
            hub__project=project,
            hub__hub_physical_name="KUNDE_H",
            column_name=column_name,
        )
        LinkHubSourceMapping.objects.filter(
            link_hub_reference=kunde_ref, standard_hub_column=hub_column
        ).delete()
        LinkHubSourceMapping.objects.create(
            link_hub_reference=kunde_ref,
            standard_hub_column=hub_column,
            staging_column=get_or_create_staging_column(extraction),
        )

    # Drop the phantom columns import_model created on `order` so the fixture
    # starts clean and any that reappear are unambiguously the importer's doing.
    SourceColumn.objects.filter(source_table=order).exclude(
        source_column_physical_name__in=ORDER_COLUMNS
    ).delete()

    return project


def _export(project: Project, out: Path) -> dict:
    data = ModelBuilder(project).build().model_dump(mode="json")
    out.write_text(json.dumps(data, default=str), encoding="utf-8")
    return data


def _import(
    project: Project, path: Path, conflict_strategy: str = "merge"
) -> ImportReport:
    return import_metadata(
        project=project,
        source=JsonSource(path=path),
        options=ImportOptions(
            skip_snapshots=True,
            conflict_strategy=conflict_strategy,  # type: ignore[arg-type]
        ),
    )


def _roundtrip(tmp_path: Path, dst_name: str = "prejoin-dst") -> Project:
    src = _build_source_project()
    out = tmp_path / "export.json"
    _export(src, out)

    dst = Project.objects.create(name=dst_name)
    report = _import(dst, out)
    assert report.status == "success", report.issues
    return dst


# ---------------------------------------------------------------------------
# Defect 1 — prejoins must actually reach the database
# ---------------------------------------------------------------------------


def test_prejoin_is_persisted_on_import(tmp_path: Path) -> None:
    """The parsed prejoin must become a real PrejoinDefinition row."""
    dst = _roundtrip(tmp_path)

    prejoin = PrejoinDefinition.objects.get(project=dst)
    assert prejoin.source_table.physical_table_name == "order"
    assert prejoin.source_table.source_system.name == "WEBSHOP"
    assert prejoin.prejoin_target_table.physical_table_name == "kunden"
    assert prejoin.prejoin_target_table.source_system.name == "CRM"
    assert prejoin.prejoin_operator == "AND"

    assert [
        c.source_column_physical_name
        for c in prejoin.prejoin_condition_source_column.all()
    ] == ["KUNDEN_REF"]
    assert [
        c.source_column_physical_name
        for c in prejoin.prejoin_condition_target_column.all()
    ] == ["KUNDEN_REF"]


def test_prejoin_extraction_columns_are_persisted(tmp_path: Path) -> None:
    dst = _roundtrip(tmp_path)

    extractions = {
        e.source_column.source_column_physical_name: e
        for e in PrejoinExtractionColumn.objects.filter(prejoin__project=dst)
    }
    assert set(extractions) == {"SYSID", "KUNDENNUMMER"}

    # Extractions must hang off the target table's columns, not the source's.
    for extraction in extractions.values():
        assert extraction.source_column.source_table.physical_table_name == "kunden"

    assert extractions["KUNDENNUMMER"].prejoin_target_column_alias == "KUNDEN_NR"
    # The exporter defaults the alias to the physical column name. That must be
    # normalised back to None rather than re-imported as a redundant alias.
    assert extractions["SYSID"].prejoin_target_column_alias is None


def test_prejoin_survives_a_second_export_import_generation(tmp_path: Path) -> None:
    """Export -> import -> export must be stable, not merely non-crashing."""
    first = _roundtrip(tmp_path)
    second_out = tmp_path / "second.json"
    data = _export(first, second_out)

    prejoins = [
        pj
        for stage in data["stages"]
        if stage["source_table"] == "order"
        for pj in stage["prejoins"]
    ]
    assert len(prejoins) == 1
    assert prejoins[0]["target_table"] == "kunden"
    assert prejoins[0]["target_source_system"] == "CRM"
    assert prejoins[0]["join_conditions"]["source_columns"] == ["KUNDEN_REF"]
    assert prejoins[0]["join_conditions"]["target_columns"] == ["KUNDEN_REF"]
    assert {
        (e["source_column_name"], e["target_column_alias"])
        for e in prejoins[0]["extraction_columns"]
    } == {("SYSID", "SYSID"), ("KUNDENNUMMER", "KUNDEN_NR")}


def test_reimporting_the_same_export_is_idempotent(tmp_path: Path) -> None:
    """A re-import must update the prejoin in place, not duplicate it."""
    src = _build_source_project()
    out = tmp_path / "export.json"
    _export(src, out)

    dst = Project.objects.create(name="prejoin-idempotent")
    for _ in range(2):
        report = _import(dst, out)
        assert report.status == "success", report.issues

    assert PrejoinDefinition.objects.filter(project=dst).count() == 1
    assert PrejoinExtractionColumn.objects.filter(prejoin__project=dst).count() == 2

    prejoin = PrejoinDefinition.objects.get(project=dst)
    # The M2M join condition is replaced, not accumulated.
    assert prejoin.prejoin_condition_source_column.count() == 1
    assert prejoin.prejoin_condition_target_column.count() == 1

    # And the link stays bound to a single staging column per hub key.
    link = Link.objects.get(project=dst, link_physical_name="ORDER_KUNDE_L")
    assert (
        LinkHubSourceMapping.objects.filter(
            link_hub_reference__link=link,
            link_hub_reference__hub__hub_physical_name="KUNDE_H",
        ).count()
        == 2
    )


def test_replace_all_drops_a_prejoin_that_is_gone_from_the_file(
    tmp_path: Path,
) -> None:
    """Under replace_all a prejoin absent from the file must be deleted — and
    the link mappings it fed must not resurrect it or bind to a dead row."""
    src = _build_source_project()
    out = tmp_path / "export.json"
    data = _export(src, out)

    dst = Project.objects.create(name="prejoin-replace-all")
    assert _import(dst, out, conflict_strategy="replace_all").status == "success"
    assert PrejoinDefinition.objects.filter(project=dst).count() == 1

    # Remove the prejoin and every mapping that depended on it.
    for stage in data["stages"]:
        stage["prejoins"] = []
    for link in data["links"]:
        for source in link["source_tables"]:
            source["columns"] = [
                c for c in source["columns"] if not c.get("source_prejoin_target_table")
            ]
    stripped = tmp_path / "stripped.json"
    stripped.write_text(json.dumps(data, default=str), encoding="utf-8")

    report = _import(dst, stripped, conflict_strategy="replace_all")
    assert report.status == "success", report.issues

    assert PrejoinDefinition.objects.filter(project=dst).count() == 0
    assert PrejoinExtractionColumn.objects.filter(prejoin__project=dst).count() == 0

    # The cascade cleared the prejoin-fed hub keys rather than leaving dangling
    # mappings, and no phantom column was invented to replace them.
    link_obj = Link.objects.get(project=dst, link_physical_name="ORDER_KUNDE_L")
    assert not LinkHubSourceMapping.objects.filter(
        link_hub_reference__link=link_obj,
        link_hub_reference__hub__hub_physical_name="KUNDE_H",
    ).exists()
    assert not SourceColumn.objects.filter(
        source_table__project=dst,
        source_table__physical_table_name="order",
        source_column_physical_name__in=("SYSID", "KUNDENNUMMER", "KUNDEN_NR"),
    ).exists()


def test_changed_join_condition_replaces_the_previous_one(tmp_path: Path) -> None:
    """An updated prejoin must overwrite the old join condition."""
    src = _build_source_project()
    out = tmp_path / "export.json"
    data = _export(src, out)

    dst = Project.objects.create(name="prejoin-updated")
    assert _import(dst, out).status == "success"

    # Re-point the join at a different pair of columns.
    for stage in data["stages"]:
        for prejoin in stage["prejoins"]:
            if prejoin["target_table"] == "kunden":
                prejoin["join_conditions"]["source_columns"] = ["ORDER_ID"]
                prejoin["join_conditions"]["target_columns"] = ["SYSID"]
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(data, default=str), encoding="utf-8")

    assert _import(dst, changed).status == "success"

    prejoin = PrejoinDefinition.objects.get(project=dst)
    assert [
        c.source_column_physical_name
        for c in prejoin.prejoin_condition_source_column.all()
    ] == ["ORDER_ID"]
    assert [
        c.source_column_physical_name
        for c in prejoin.prejoin_condition_target_column.all()
    ] == ["SYSID"]


def test_prejoin_referencing_an_unknown_column_reports_an_issue(tmp_path: Path) -> None:
    """An unresolvable join column is an Issue, not a silently invented column."""
    src = _build_source_project()
    out = tmp_path / "export.json"
    data = _export(src, out)

    for stage in data["stages"]:
        for prejoin in stage["prejoins"]:
            if prejoin["target_table"] == "kunden":
                prejoin["join_conditions"]["source_columns"] = ["DOES_NOT_EXIST"]
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(data, default=str), encoding="utf-8")

    dst = Project.objects.create(name="prejoin-broken")
    report = _import(dst, broken)

    codes = {issue.code for issue in report.issues}
    assert "entity.missing_source_column" in codes
    assert PrejoinDefinition.objects.filter(project=dst).count() == 0

    # The bogus column must not have been created on the source table.
    assert not SourceColumn.objects.filter(
        source_table__project=dst,
        source_table__physical_table_name="order",
        source_column_physical_name="DOES_NOT_EXIST",
    ).exists()


# ---------------------------------------------------------------------------
# Defect 2 — a prejoin-fed link business key must bind to the extraction
# ---------------------------------------------------------------------------


def test_link_business_key_binds_to_the_prejoin_extraction_column(
    tmp_path: Path,
) -> None:
    dst = _roundtrip(tmp_path)

    link = Link.objects.get(project=dst, link_physical_name="ORDER_KUNDE_L")
    mappings = {
        m.standard_hub_column.column_name: m
        for m in LinkHubSourceMapping.objects.filter(
            link_hub_reference__link=link,
            link_hub_reference__hub__hub_physical_name="KUNDE_H",
        ).select_related("staging_column__prejoin_column__source_column")
    }
    assert set(mappings) == {"SYSID", "KUNDENNUMMER"}

    for column_name, mapping in mappings.items():
        staging = mapping.staging_column
        assert staging.prejoin_column is not None, column_name
        assert staging.source_column is None, column_name
        assert (
            staging.prejoin_column.source_column.source_column_physical_name
            == column_name
        )
        # The staging column still belongs to the table being staged.
        assert staging.source_table.physical_table_name == "order"

    # The link's other hub key is a plain source column and must stay one.
    order_key = LinkHubSourceMapping.objects.get(
        link_hub_reference__link=link,
        link_hub_reference__hub__hub_physical_name="ORDER_H",
    )
    assert order_key.staging_column.prejoin_column is None
    order_source_column = order_key.staging_column.source_column
    assert order_source_column is not None
    assert order_source_column.source_column_physical_name == "ORDER_ID"


def test_import_does_not_invent_phantom_columns_on_the_source_table(
    tmp_path: Path,
) -> None:
    """The regression itself: `order` must not gain SYSID / KUNDENNUMMER."""
    dst = _roundtrip(tmp_path)

    order_columns = set(
        SourceColumn.objects.filter(
            source_table__project=dst, source_table__physical_table_name="order"
        ).values_list("source_column_physical_name", flat=True)
    )
    assert order_columns == set(ORDER_COLUMNS)
    assert "SYSID" not in order_columns
    assert "KUNDENNUMMER" not in order_columns
    assert "KUNDEN_NR" not in order_columns


def test_export_marks_the_business_key_as_prejoin_fed(tmp_path: Path) -> None:
    """The exporter must say where the column comes from, or the importer
    cannot tell it apart from a plain column of `order`."""
    src = _build_source_project()
    data = _export(src, tmp_path / "export.json")

    link = next(x for x in data["links"] if x["link_name"] == "ORDER_KUNDE_L")
    order_source = next(
        s for s in link["source_tables"] if s["source_table"] == "order"
    )
    by_column = {c["link_column_name"]: c for c in order_source["columns"]}

    for column_name, staged_name in (
        ("SYSID", "SYSID"),
        ("KUNDENNUMMER", "KUNDEN_NR"),
    ):
        mapping = by_column[column_name]
        assert mapping["source_column_name"] == staged_name
        assert mapping["source_prejoin_target_table"] == "kunden"
        assert mapping["source_prejoin_target_source_system"] == "CRM"

    # A direct column must not be tagged.
    assert by_column["ORDER_ID"]["source_prejoin_target_table"] is None
    assert by_column["ORDER_ID"]["source_prejoin_target_source_system"] is None


def test_unresolvable_prejoin_reference_reports_an_issue(tmp_path: Path) -> None:
    """If a mapping claims a prejoin that isn't in the file, say so — do not
    quietly fall back to creating the phantom column again."""
    src = _build_source_project()
    out = tmp_path / "export.json"
    data = _export(src, out)

    # Keep the link mappings, drop the prejoin that backs them.
    for stage in data["stages"]:
        stage["prejoins"] = []
    orphaned = tmp_path / "orphaned.json"
    orphaned.write_text(json.dumps(data, default=str), encoding="utf-8")

    dst = Project.objects.create(name="prejoin-orphaned")
    report = _import(dst, orphaned)

    codes = {issue.code for issue in report.issues}
    assert "entity.missing_reference" in codes

    assert not SourceColumn.objects.filter(
        source_table__project=dst,
        source_table__physical_table_name="order",
        source_column_physical_name__in=("SYSID", "KUNDENNUMMER", "KUNDEN_NR"),
    ).exists()


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------


def test_export_without_the_new_fields_imports_exactly_as_before(
    tmp_path: Path,
) -> None:
    """An export written before `source_prejoin_target_table` existed omits the
    field entirely. Every mapping must then be treated as a direct source
    column, exactly as it was before this change.
    """
    src = Project.objects.create(name="legacy-src")
    system = SourceSystem.objects.create(
        project=src, schema_name="crm_raw", name="CRM", database_name="ops"
    )
    _table(src, system, "orders", ("O_ORDERKEY", "O_CUSTKEY", "O_TOTALPRICE"))
    result = import_model(
        src.name,
        ModelImportSchema.model_validate(
            {
                "hubs": [
                    {
                        "name": "ORDER_H",
                        "business_keys": ["O_ORDERKEY"],
                        "source_table": "orders",
                    },
                    {
                        "name": "CUSTOMER_H",
                        "business_keys": ["O_CUSTKEY"],
                        "source_table": "orders",
                    },
                ],
                "links": [
                    {
                        "name": "ORDER_CUSTOMER_L",
                        "link_type": "standard",
                        "hubs": ["ORDER_H", "CUSTOMER_H"],
                        "payload_columns": ["O_TOTALPRICE"],
                        "source_table": "orders",
                    }
                ],
            }
        ),
    )
    assert result.errors == [], result.errors

    out = tmp_path / "export.json"
    data = _export(src, out)

    # Simulate a legacy export: strip the new fields everywhere.
    for link in data["links"]:
        for source in link["source_tables"]:
            for column in source["columns"]:
                column.pop("source_prejoin_target_table", None)
                column.pop("source_prejoin_target_source_system", None)
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps(data, default=str), encoding="utf-8")

    dst = Project.objects.create(name="legacy-dst")
    report = _import(dst, legacy)
    assert report.status == "success", report.issues

    link = Link.objects.get(project=dst, link_physical_name="ORDER_CUSTOMER_L")
    mappings = LinkHubSourceMapping.objects.filter(
        link_hub_reference__link=link
    ).select_related("staging_column__source_column")
    assert mappings.count() == 2
    for mapping in mappings:
        assert mapping.staging_column.prejoin_column is None
        assert mapping.staging_column.source_column is not None

    # No prejoins in the file, none in the database.
    assert PrejoinDefinition.objects.filter(project=dst).count() == 0


def test_model_without_prejoins_is_unaffected(tmp_path: Path) -> None:
    """A project that never had a prejoin must import with none created and no
    prejoin-related issues raised."""
    src = Project.objects.create(name="no-prejoin-src")
    system = SourceSystem.objects.create(
        project=src, schema_name="crm_raw", name="CRM", database_name="ops"
    )
    _table(src, system, "orders", ("O_ORDERKEY", "O_COMMENT"))
    import_model(
        src.name,
        ModelImportSchema.model_validate(
            {
                "hubs": [
                    {
                        "name": "ORDER_H",
                        "business_keys": ["O_ORDERKEY"],
                        "source_table": "orders",
                    }
                ],
                "satellites": [
                    {
                        "name": "ORDER_S",
                        "parent_hub": "ORDER_H",
                        "columns": ["O_COMMENT"],
                        "source_table": "orders",
                    }
                ],
            }
        ),
    )

    out = tmp_path / "export.json"
    _export(src, out)

    dst = Project.objects.create(name="no-prejoin-dst")
    report = _import(dst, out)
    assert report.status == "success", report.issues
    assert [i for i in report.issues if "prejoin" in i.code] == []
    assert PrejoinDefinition.objects.filter(project=dst).count() == 0
