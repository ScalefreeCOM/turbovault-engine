"""Resolving and normalizing datavault4dbt arguments like datavault4dbt does."""

from __future__ import annotations

from engine.services.imports.dbt.datavault4dbt import (
    as_bool,
    interpret,
    normalize_derived_columns,
    normalize_hashdiff,
    normalize_hashed_columns,
    normalize_prejoins,
    normalize_ref_satellites,
    normalize_sat_names,
    normalize_source_models,
    stage_source,
)
from engine.services.imports.dbt.extract import CapturedCall


def _call(macro: str, **kwargs) -> CapturedCall:
    return CapturedCall(package="datavault4dbt", macro=macro, args=[], kwargs=kwargs)


def test_yaml_metadata_wins_over_a_separate_parameter():
    call = interpret(
        _call(
            "hub",
            yaml_metadata="hashkey: hk_from_yaml\nbusiness_keys: [id]",
            hashkey="hk_separate",
        )
    )
    assert call.params["hashkey"] == "hk_from_yaml"
    assert [note.code for note in call.notes] == ["dbt.parameter_given_twice"]


def test_a_separate_parameter_applies_when_the_yaml_lacks_it_and_false_counts():
    call = interpret(
        _call("sat_v1", yaml_metadata="sat_v0: s_v0", add_is_current_flag=False)
    )
    assert call.params == {"sat_v0": "s_v0", "add_is_current_flag": False}


def test_parameters_the_macro_does_not_know_are_dropped():
    yaml_block = (
        "source_model: x\nldts: l\nrsrc: r\n"
        "-- multi_active_config:\n--     multi_active_key: k\n"
    )
    stage = interpret(_call("stage", yaml_metadata=yaml_block))
    assert set(stage.params) == {"source_model", "ldts", "rsrc"}
    assert {note.parameter for note in stage.notes} == {
        "-- multi_active_config",
        "--     multi_active_key",
    }
    assert {note.code for note in stage.notes} == {"dbt.parameter_ignored"}

    hub = interpret(
        _call("hub", hashkey="hk", business_keys=["id"], source_models="s", ldts="x")
    )
    assert "ldts" not in hub.params
    assert hub.notes[0].parameter == "ldts"


def test_invalid_yaml_metadata_is_reported():
    call = interpret(_call("hub", yaml_metadata="hashkey: [unclosed"))
    assert call.notes[0].code == "dbt.value_invalid"


def test_positional_arguments_are_reported():
    call = interpret(CapturedCall("datavault4dbt", "hub", ["hk", ["id"], "stg"], {}))
    assert call.notes[0].code == "dbt.parameter_unsupported"


def test_source_models_in_every_shape():
    defaults = {"hk_column": "hk_customer_h", "bk_columns": ["customer_id"]}
    assert normalize_source_models("stg_a", defaults) == [
        {"name": "stg_a", "hk_column": "hk_customer_h", "bk_columns": ["customer_id"]}
    ]
    assert normalize_source_models(["stg_a", "stg_b"], defaults)[1]["name"] == "stg_b"
    listed = normalize_source_models(
        [
            {
                "name": "stg_a",
                "bk_columns": "author_id",
                "hk_column": "hk_author_h",
                "rsrc_static": "*/A/*",
            }
        ],
        defaults,
    )
    assert listed == [
        {
            "name": "stg_a",
            "bk_columns": ["author_id"],
            "hk_column": "hk_author_h",
            "rsrc_static": ["*/A/*"],
        }
    ]
    mapped = normalize_source_models(
        {"stg_a": {"rsrc_static": ["x", "y"]}, "stg_b": None}, defaults
    )
    assert [source["name"] for source in mapped] == ["stg_a", "stg_b"]
    assert mapped[0]["rsrc_static"] == ["x", "y"]
    assert mapped[1]["bk_columns"] == ["customer_id"]


def test_what_a_stage_reads():
    assert stage_source({"crm": "CUSTOMER"}) == ("source", ("crm", "CUSTOMER"))
    assert stage_source("pstg_customer") == ("model", "pstg_customer")
    assert stage_source({"__ref__": "pstg_customer", "package": None}) == (
        "model",
        "pstg_customer",
    )
    assert stage_source(None) is None


def test_hashed_columns():
    hashkeys, hashdiffs = normalize_hashed_columns(
        {
            "hk_customer_h": ["id"],
            "hk_single": "id",
            "hd_customer_s": {"is_hashdiff": True, "columns": ["name", "email"]},
            "hd_excluding": {
                "is_hashdiff": "true",
                "exclude_columns": True,
                "columns": ["ldts"],
            },
        }
    )
    assert hashkeys == {"hk_customer_h": ["id"], "hk_single": ["id"]}
    assert hashdiffs["hd_customer_s"] == {
        "columns": ["name", "email"],
        "exclude_columns": False,
    }
    assert hashdiffs["hd_excluding"]["exclude_columns"] is True


def test_derived_columns():
    assert normalize_derived_columns(
        {
            "full_name": {
                "value": "a || b",
                "datatype": "VARCHAR",
                "src_cols_required": "a",
            },
            "flag": "!Y",
        }
    ) == {
        "full_name": {
            "value": "a || b",
            "datatype": "VARCHAR",
            "src_cols_required": ["a"],
        },
        "flag": {"value": "!Y", "datatype": None, "src_cols_required": []},
    }


def test_prejoins_in_the_dictionary_notation_are_grouped():
    grouped = normalize_prejoins(
        {
            "contract_number": {
                "ref_model": "pstg_contract",
                "bk": "number",
                "this_column_name": "contract_id",
                "ref_column_name": "id",
            },
            "contract_type": {
                "ref_model": "pstg_contract",
                "bk": "type",
                "this_column_name": "contract_id",
                "ref_column_name": "id",
            },
            "region": {
                "src_name": "crm",
                "src_table": "REGION",
                "bk": "name",
                "this_column_name": "region_id",
                "ref_column_name": "id",
            },
        }
    )
    assert len(grouped) == 2
    assert grouped[0]["extract_columns"] == ["number", "type"]
    assert grouped[0]["aliases"] == ["contract_number", "contract_type"]
    assert grouped[1]["src_table"] == "REGION"


def test_prejoins_in_the_list_notation():
    (entry,) = normalize_prejoins(
        [
            {
                "extract_columns": "name",
                "ref_model": "m",
                "this_column_name": "a",
                "ref_column_name": "b",
            }
        ]
    )
    assert entry["extract_columns"] == ["name"]
    assert entry["aliases"] == ["name"]
    assert entry["operator"] == "AND"


def test_hashdiff_with_an_alias():
    assert normalize_hashdiff("hd_x") == ("hd_x", None)
    assert normalize_hashdiff({"source_column": "hd_x", "alias": "hashdiff"}) == (
        "hd_x",
        "hashdiff",
    )
    assert normalize_hashdiff({"source_column": "hd_x", "alias": "hd_x"}) == (
        "hd_x",
        None,
    )


def test_pit_and_reference_table_lists():
    assert normalize_sat_names(["s1_v1", {"name": "s2_v1", "mandatory": True}]) == [
        "s1_v1",
        "s2_v1",
    ]
    assert normalize_ref_satellites({"r_v1": {"include": "a"}, "q_v1": {}}) == {
        "r_v1": {"include": ["a"], "exclude": []},
        "q_v1": {"include": [], "exclude": []},
    }
    assert normalize_ref_satellites(["r_v1"]) == {
        "r_v1": {"include": [], "exclude": []}
    }


def test_booleans_written_as_strings():
    assert as_bool("True", False) is True
    assert as_bool("false", True) is False
    assert as_bool(None, True) is True
