"""Regression tests for two JSON export/import round-trip gaps.

1. Cross-source-system prejoins. `PrejoinDefinitionExport` only carried
   `target_table`, and the JSON parser resolved the target as
   `"{stage.source_system}|{target_table}"` — i.e. it assumed the prejoin
   target always lives in the stage's own source system. The Django model
   (`prejoin_definition`) has no such restriction: it references two arbitrary
   `source_table` rows. A legitimate cross-system prejoin therefore re-imported
   pointing at the wrong table.

2. Satellite column transformations. `SatelliteColumnDef` carries
   `target_column_transformation` and the builder writes it, but the import
   domain object had no such field, so a hard business rule expressed as a
   column transformation was silently dropped on re-import.

Note on prejoins: the import executor does not yet materialise prejoins into
the database ("full prejoin support is a follow-up", see
`engine/services/imports/domain.py`). These tests therefore assert on the
parsed `DomainModel`, which is where the target resolution actually happens.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine.models import (
    PrejoinDefinition,
    PrejoinExtractionColumn,
    Project,
    Satellite,
    SatelliteColumn,
    SourceColumn,
    SourceSystem,
    SourceTable,
)
from engine.services.export.builder import ModelBuilder
from engine.services.imports import ImportOptions, JsonSource, import_metadata
from engine.services.imports.parsers.json_parser import parse_json
from engine.services.model_import_schema import ModelImportSchema
from engine.services.model_import_service import import_model

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _write_export(project: Project, out: Path) -> dict:
    export = ModelBuilder(project).build()
    data = export.model_dump(mode="json")
    out.write_text(json.dumps(data, default=str), encoding="utf-8")
    return data


def _stage_prejoins(data: dict, source_table: str) -> list[dict]:
    for stage in data["stages"]:
        if stage["source_table"] == source_table:
            return stage["prejoins"]
    raise AssertionError(f"no stage exported for source table {source_table!r}")


def _prejoin_targets(model) -> dict[str, str]:
    """Map prejoin target physical name -> resolved target table identifier."""
    return {
        pj.target_table_identifier.split("|", 1)[1]: pj.target_table_identifier
        for pj in model.prejoins
    }


def _build_prejoin_project() -> Project:
    """A project with a cross-system prejoin AND a same-system prejoin.

    orders (CRM) -> currency (REF)      : crosses source systems
    orders (CRM) -> order_status (CRM)  : stays inside one source system
    """
    project = Project.objects.create(name="prejoin-src")

    crm = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM", database_name="ops"
    )
    ref = SourceSystem.objects.create(
        project=project, schema_name="ref_raw", name="REF", database_name="reference"
    )

    orders = _table(
        project,
        crm,
        "orders",
        ("O_ORDERKEY", "O_CUSTKEY", "O_CURRENCY_CODE", "O_STATUS_CODE"),
    )
    currency = _table(project, ref, "currency", ("C_CODE", "C_NAME"))
    order_status = _table(project, crm, "order_status", ("S_CODE", "S_LABEL"))

    cross = PrejoinDefinition.objects.create(
        project=project,
        source_table=orders,
        prejoin_target_table=currency,
        prejoin_operator=PrejoinDefinition.JoinOperator.AND,
    )
    cross.prejoin_condition_source_column.add(
        SourceColumn.objects.get(
            source_table=orders, source_column_physical_name="O_CURRENCY_CODE"
        )
    )
    cross.prejoin_condition_target_column.add(
        SourceColumn.objects.get(
            source_table=currency, source_column_physical_name="C_CODE"
        )
    )
    PrejoinExtractionColumn.objects.create(
        prejoin=cross,
        source_column=SourceColumn.objects.get(
            source_table=currency, source_column_physical_name="C_NAME"
        ),
        prejoin_target_column_alias="CURRENCY_NAME",
    )

    same = PrejoinDefinition.objects.create(
        project=project,
        source_table=orders,
        prejoin_target_table=order_status,
        prejoin_operator=PrejoinDefinition.JoinOperator.AND,
    )
    same.prejoin_condition_source_column.add(
        SourceColumn.objects.get(
            source_table=orders, source_column_physical_name="O_STATUS_CODE"
        )
    )
    same.prejoin_condition_target_column.add(
        SourceColumn.objects.get(
            source_table=order_status, source_column_physical_name="S_CODE"
        )
    )
    PrejoinExtractionColumn.objects.create(
        prejoin=same,
        source_column=SourceColumn.objects.get(
            source_table=order_status, source_column_physical_name="S_LABEL"
        ),
        prejoin_target_column_alias="STATUS_LABEL",
    )

    return project


# ---------------------------------------------------------------------------
# Gap 1 — cross-source-system prejoins
# ---------------------------------------------------------------------------


def test_cross_system_prejoin_survives_json_roundtrip(tmp_path):
    """A prejoin whose target lives in another source system must re-import
    against that system, not against the stage's own system."""
    project = _build_prejoin_project()
    data = _write_export(project, tmp_path / "export.json")

    prejoins = {pj["target_table"]: pj for pj in _stage_prejoins(data, "orders")}
    assert prejoins["currency"]["target_source_system"] == "REF"
    assert prejoins["order_status"]["target_source_system"] == "CRM"

    model = parse_json(tmp_path / "export.json")
    targets = _prejoin_targets(model)

    assert targets["currency"] == "REF|currency"
    assert targets["order_status"] == "CRM|order_status"

    # Both identifiers must actually resolve against the imported sources.
    for identifier in targets.values():
        assert model.get_source_table(identifier) is not None, identifier


def test_cross_system_prejoin_keeps_join_and_extraction_details(tmp_path):
    """The rest of the prejoin payload must be unaffected by the new field."""
    project = _build_prejoin_project()
    _write_export(project, tmp_path / "export.json")

    model = parse_json(tmp_path / "export.json")
    cross = next(
        pj for pj in model.prejoins if pj.target_table_identifier == "REF|currency"
    )

    assert cross.source_table_identifier == "CRM|orders"
    assert cross.operator == "AND"
    assert cross.source_join_columns == ["O_CURRENCY_CODE"]
    assert cross.target_join_columns == ["C_CODE"]
    assert [(c.source_column_name, c.alias) for c in cross.extraction_columns] == [
        ("C_NAME", "CURRENCY_NAME")
    ]


def test_prejoin_without_target_source_system_falls_back_to_stage_system(tmp_path):
    """Backwards compatibility: exports written before `target_source_system`
    existed omit the field entirely and must still resolve against the stage's
    own source system."""
    project = _build_prejoin_project()
    data = _write_export(project, tmp_path / "export.json")

    # Simulate a legacy export: strip the new field everywhere.
    for stage in data["stages"]:
        for pj in stage["prejoins"]:
            pj.pop("target_source_system", None)
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps(data, default=str), encoding="utf-8")

    model = parse_json(legacy)
    targets = _prejoin_targets(model)

    # The same-system prejoin still resolves exactly as it did before.
    assert targets["order_status"] == "CRM|order_status"
    assert model.get_source_table(targets["order_status"]) is not None

    # The cross-system one degrades to the old (lossy) behaviour rather than
    # crashing — the field is the only way to express it.
    assert targets["currency"] == "CRM|currency"


# ---------------------------------------------------------------------------
# Gap 2 — satellite column transformations
# ---------------------------------------------------------------------------

TRANSFORMATION = "UPPER(TRIM(O_COMMENT))"


def _build_satellite_project() -> Project:
    project = Project.objects.create(name="transformation-src")
    system = SourceSystem.objects.create(
        project=project, schema_name="crm_raw", name="CRM", database_name="ops"
    )
    _table(project, system, "orders", ("O_ORDERKEY", "O_COMMENT", "O_TOTALPRICE"))

    result = import_model(
        project.name,
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
                        "columns": ["O_COMMENT", "O_TOTALPRICE"],
                        "source_table": "orders",
                    }
                ],
            }
        ),
    )
    assert result.errors == [], result.errors

    # Hard business rule on one column, plus a rename on the same column so we
    # can prove the two fields are carried independently.
    col = SatelliteColumn.objects.get(
        satellite__satellite_physical_name="ORDER_S",
        staging_column__source_column__source_column_physical_name="O_COMMENT",
    )
    col.target_column_name = "ORDER_COMMENT"
    col.target_column_transformation = TRANSFORMATION
    col.save(update_fields=["target_column_name", "target_column_transformation"])

    return project


def test_satellite_column_transformation_survives_json_roundtrip(tmp_path):
    src = _build_satellite_project()
    out = tmp_path / "export.json"
    data = _write_export(src, out)

    exported = next(
        c
        for sat in data["satellites"]
        for c in sat["columns"]
        if c["source_column"] == "O_COMMENT"
    )
    assert exported["target_column_transformation"] == TRANSFORMATION

    dst = Project.objects.create(name="transformation-dst")
    report = import_metadata(
        project=dst,
        source=JsonSource(path=out),
        options=ImportOptions(skip_snapshots=True),
    )
    assert report.status == "success", report.issues

    col = SatelliteColumn.objects.get(
        satellite__project=dst,
        satellite__satellite_physical_name="ORDER_S",
        staging_column__source_column__source_column_physical_name="O_COMMENT",
    )
    assert col.target_column_transformation == TRANSFORMATION
    assert col.target_column_name == "ORDER_COMMENT"

    # Columns without a transformation must not gain a spurious one.
    plain = SatelliteColumn.objects.get(
        satellite__project=dst,
        satellite__satellite_physical_name="ORDER_S",
        staging_column__source_column__source_column_physical_name="O_TOTALPRICE",
    )
    assert plain.target_column_transformation in (None, "")


def test_stage_derived_columns_regenerate_after_roundtrip(tmp_path):
    """Stage `derived_columns` are derived state: the builder recomputes them
    from satellite columns. Once the transformation round-trips on the satellite
    column, the re-exported stage carries the derived column again without the
    importer ever reading `stage.derived_columns`."""
    src = _build_satellite_project()
    out = tmp_path / "export.json"
    _write_export(src, out)

    dst = Project.objects.create(name="derived-dst")
    report = import_metadata(
        project=dst,
        source=JsonSource(path=out),
        options=ImportOptions(skip_snapshots=True),
    )
    assert report.status == "success", report.issues

    reexport = ModelBuilder(dst).build().model_dump(mode="json")
    derived = {
        d["target_column_name"]: d
        for stage in reexport["stages"]
        for d in stage["derived_columns"]
    }
    assert derived["ORDER_COMMENT"]["source_column_name"] == "O_COMMENT"
    assert derived["ORDER_COMMENT"]["transformation"] == TRANSFORMATION


def test_satellite_column_transformation_not_required(tmp_path):
    """A satellite with no transformations at all still imports cleanly."""
    src = Project.objects.create(name="no-transformation-src")
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
    _write_export(src, out)

    dst = Project.objects.create(name="no-transformation-dst")
    report = import_metadata(
        project=dst,
        source=JsonSource(path=out),
        options=ImportOptions(skip_snapshots=True),
    )
    assert report.status == "success", report.issues
    assert Satellite.objects.filter(
        project=dst, satellite_physical_name="ORDER_S"
    ).exists()
    assert (
        SatelliteColumn.objects.filter(
            satellite__project=dst,
            satellite__satellite_physical_name="ORDER_S",
        )
        .exclude(target_column_transformation=None)
        .exclude(target_column_transformation="")
        .count()
        == 0
    )


def test_reimport_without_transformations_preserves_existing_ones(tmp_path):
    """A format that has no transformation concept must not clear one.

    Excel, SQLite and IRiS have no column-transformation field, so their parsers
    always leave ``DSatelliteColumn.target_column_transformation`` at ``None``.
    Writing that into ``update_or_create`` defaults unconditionally would wipe a
    transformation the user set in Django Admin the next time they re-imported
    their spreadsheet. This pins the conditional write in ``_upsert_satellite``.
    """
    project = _build_satellite_project()

    col = SatelliteColumn.objects.get(
        satellite__project=project,
        satellite__satellite_physical_name="ORDER_S",
        staging_column__source_column__source_column_physical_name="O_COMMENT",
    )
    assert col.target_column_transformation == TRANSFORMATION

    # Re-run the same import path the non-JSON parsers produce: identical
    # satellite columns, but with no transformation supplied.
    out = tmp_path / "export.json"
    data = _write_export(project, out)
    for sat in data["satellites"]:
        for column in sat["columns"]:
            column["target_column_transformation"] = None
    out.write_text(json.dumps(data), encoding="utf-8")

    report = import_metadata(
        project=project,
        source=JsonSource(path=out),
        options=ImportOptions(skip_snapshots=True),
    )
    assert report.status == "success", report.issues

    col.refresh_from_db()
    assert col.target_column_transformation == TRANSFORMATION
