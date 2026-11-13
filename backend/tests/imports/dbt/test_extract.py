"""Capturing datavault4dbt calls from a model's Jinja.

Every notation of the metadata must produce the same parameters: a
yaml_metadata block, a YAML or JSON block parsed into separate parameters,
set variables and literals. The sandbox must never reach the environment, the
file system or unsafe attributes.
"""

from __future__ import annotations

import pytest
from engine.services.imports.dbt.datavault4dbt import interpret
from engine.services.imports.dbt.extract import capture_model, ref_name, source_pair

EXPECTED = {
    "hashkey": "hk_customer_h",
    "business_keys": ["customer_id"],
    "source_models": "stg_customer",
}

NOTATIONS = {
    "yaml_metadata block": """
{{ config(materialized='incremental') }}
{%- set yaml_metadata -%}
hashkey: hk_customer_h
business_keys:
    - customer_id
source_models: stg_customer
{%- endset -%}
{{ datavault4dbt.hub(yaml_metadata=yaml_metadata) }}
""",
    "yaml block parsed with fromyaml": """
{%- set yaml_metadata -%}
hashkey: 'hk_customer_h'
business_keys:
    - customer_id
source_models: stg_customer
{%- endset -%}
{%- set metadata_dict = fromyaml(yaml_metadata) -%}
{{ datavault4dbt.hub(hashkey=metadata_dict['hashkey'],
                     business_keys=metadata_dict['business_keys'],
                     source_models=metadata_dict['source_models']) }}
""",
    "json block parsed with fromjson": """
{%- set metadata_json -%}
{"hashkey": "hk_customer_h", "business_keys": ["customer_id"], "source_models": "stg_customer"}
{%- endset -%}
{%- set metadata = fromjson(metadata_json) -%}
{{ datavault4dbt.hub(hashkey=metadata.hashkey, business_keys=metadata.business_keys,
                     source_models=metadata.source_models) }}
""",
    "set variables": """
{%- set hashkey = 'hk_customer_h' -%}
{%- set business_keys = ['customer_id'] -%}
{%- set source_models = 'stg_customer' -%}
{{ datavault4dbt.hub(hashkey=hashkey, business_keys=business_keys, source_models=source_models) }}
""",
    "literals in the call": """
{{ datavault4dbt.hub(hashkey='hk_customer_h', business_keys=['customer_id'], source_models='stg_customer') }}
""",
}


@pytest.mark.parametrize("notation", sorted(NOTATIONS))
def test_every_notation_gives_the_same_parameters(notation):
    capture = capture_model(NOTATIONS[notation])

    assert capture.error is None
    (call,) = capture.package_calls
    assert call.macro == "hub"
    resolved = interpret(call)
    assert resolved.params == EXPECTED
    assert resolved.notes == []


def test_a_key_the_block_lacks_is_not_set():
    """`metadata_dict['missing_columns']` for a key the YAML doesn't have."""
    capture = capture_model("""
{%- set yaml_metadata -%}
source_model: {crm: customer}
ldts: load_ts
rsrc: '!CRM'
{%- endset -%}
{%- set metadata_dict = fromyaml(yaml_metadata) -%}
{{ datavault4dbt.stage(source_model=metadata_dict['source_model'], ldts=metadata_dict['ldts'],
                       rsrc=metadata_dict['rsrc'], missing_columns=metadata_dict['missing_columns'],
                       derived_columns=metadata_dict.get('derived_columns')) }}
""")
    resolved = interpret(capture.package_calls[0])
    assert set(resolved.params) == {"source_model", "ldts", "rsrc"}
    assert resolved.params["source_model"] == {"crm": "customer"}


def test_config_ref_and_source_are_recorded():
    capture = capture_model("""
{{ config(materialized='view', tags=['staging'], schema='stage') }}
select * from {{ ref('pstg_customer') }} join {{ source('crm', 'CUSTOMER') }}
{{ datavault4dbt.stage(source_model=ref('pstg_customer'), ldts='x', rsrc='!y') }}
""")
    assert capture.config == {
        "materialized": "view",
        "tags": ["staging"],
        "schema": "stage",
    }
    call = capture.package_calls[0]
    assert ref_name(call.kwargs["source_model"]) == "pstg_customer"
    assert source_pair({"__source__": ["crm", "CUSTOMER"]}) == ("crm", "CUSTOMER")


def test_var_reads_the_project_vars_then_the_default():
    raw = "{{ datavault4dbt.hub(hashkey=var('hk'), business_keys=var('bk', ['id']), source_models=var('src')) }}"
    capture = capture_model(raw, project_vars={"hk": "hk_customer_h"})

    call = interpret(capture.package_calls[0])
    assert call.params["hashkey"] == "hk_customer_h"
    assert call.params["business_keys"] == ["id"]
    assert call.params["source_models"] == {"__unresolved__": "var('src')"}
    assert capture.unresolved == ["var('src')"]
    assert [note.code for note in call.notes] == ["dbt.value_unresolved"]


def test_env_var_never_reads_the_environment(monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "do-not-read")
    capture = capture_model(
        "{{ datavault4dbt.hub(hashkey=env_var('SECRET_TOKEN'), business_keys=['id'], source_models=env_var('X', 'stg')) }}"
    )
    params = interpret(capture.package_calls[0]).params
    assert params["hashkey"] == {"__unresolved__": "env_var('SECRET_TOKEN')"}
    assert params["source_models"] == "stg"
    assert "do-not-read" not in str(params)


def test_unknown_functions_give_unresolved_values():
    capture = capture_model("""
{%- set ts = parse_iso8601('x') -%}
select {{ dbt_utils.star(ref('a')) }}
{{ datavault4dbt.stage(source_model='a', ldts=ts, rsrc='!x') }}
""")
    assert capture.error is None
    params = interpret(capture.package_calls[0]).params
    assert params["ldts"] == {"__unresolved__": "parse_iso8601()"}


def test_a_compiler_error_fails_the_model():
    capture = capture_model("{{ exceptions.raise_compiler_error('nope') }}")
    assert capture.error and "nope" in capture.error


def test_the_sandbox_blocks_unsafe_attributes():
    """Unsafe attributes are undefined in the sandbox: nothing leaks into a call."""
    capture = capture_model(
        "{% set classes = ''.__class__.__mro__ %}"
        "{{ datavault4dbt.hub(hashkey=classes, business_keys=cycler.__init__.__globals__) }}"
    )
    call = capture.package_calls[0]
    for value in call.kwargs.values():
        assert value is None or "__unresolved__" in value
    assert "class" not in str(call.kwargs).replace("__class__", "")


def test_a_wrapper_macro_is_followed_into_the_call():
    wrapper = """
{% macro my_hub(name) %}
{{ datavault4dbt.hub(hashkey='hk_' ~ name ~ '_h', business_keys=[name ~ '_id'], source_models='stg_' ~ name) }}
{% endmacro %}
"""
    capture = capture_model(
        "{{ my_hub('customer') }}", project_macros={"my_hub": wrapper}
    )

    params = interpret(capture.package_calls[0]).params
    assert params == EXPECTED


def test_the_metadata_may_use_jinja_itself():
    capture = capture_model(
        """
{%- set yaml_metadata -%}
hashkey: hk_{{ var('entity') }}_h
business_keys: [{{ var('entity') }}_id]
source_models: stg_{{ var('entity') }}
{%- endset -%}
{{ datavault4dbt.hub(yaml_metadata=yaml_metadata) }}
""",
        project_vars={"entity": "customer"},
    )
    assert interpret(capture.package_calls[0]).params == EXPECTED
