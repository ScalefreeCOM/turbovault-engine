"""What a pre-stage's SQL reads, and how it is materialized.

The scan only recognizes calls with string literal arguments. Jinja comments
are skipped; SQL comments are not, because dbt renders Jinja inside them too.
"""

from __future__ import annotations

from engine.services.prestage_sql import (
    configured_materialization,
    dbt_source_name,
    referenced_models,
    referenced_sources,
)

SQL = """
{{ config(materialized='table') }}
{# {{ source('crm', 'COMMENTED_OUT') }} #}
select r.id, a.value:street::varchar as street
from {{ source('crm', 'CUSTOMER_RAW') }} r,
     lateral flatten(input => r.payload:addresses) a
join {{source("crm","COUNTRY")}} c on c.code = a.value:country
-- also read when commented out in SQL: {{ source('crm', 'LEGACY') }}
union all
select * from {{ ref('pstg__crm__other') }}
union all
select * from {{ ref('shared_package', 'base_customer') }}
union all
select * from {{ source('crm', 'CUSTOMER_RAW') }}
"""


def test_referenced_sources_in_order_without_duplicates():
    assert referenced_sources(SQL) == [
        ("crm", "CUSTOMER_RAW"),
        ("crm", "COUNTRY"),
        ("crm", "LEGACY"),
    ]


def test_referenced_models_include_package_refs():
    assert referenced_models(SQL) == ["pstg__crm__other", "base_customer"]


def test_nothing_is_read_from_empty_sql():
    assert referenced_sources(None) == []
    assert referenced_models("") == []


def test_configured_materialization():
    assert configured_materialization(SQL) == "table"
    assert configured_materialization("select 1") is None


def test_the_last_materialization_wins():
    sql = (
        "{{ config(materialized='table') }}\n"
        '{{ config(tags=["x"], materialized = "ephemeral") }}\nselect 1'
    )
    assert configured_materialization(sql) == "ephemeral"


def test_a_materialization_in_a_jinja_comment_is_ignored():
    sql = "{# {{ config(materialized='ephemeral') }} #}\nselect 1"
    assert configured_materialization(sql) is None


def test_dbt_source_name_matches_sources_yml():
    assert dbt_source_name("Sales CRM") == "sales_crm"
