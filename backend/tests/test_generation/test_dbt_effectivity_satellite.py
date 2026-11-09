"""Tests for the bundled dbt effectivity satellite template (issue #223)."""

from __future__ import annotations

import yaml


def _render_effectivity_satellite() -> str:
    from engine.services.generation import TemplateResolver

    resolver = TemplateResolver(use_db_templates=False, framework="dbt")
    sql_template, _ = resolver.get_templates("satellite_effectivity")
    assert sql_template is not None
    return sql_template.render(
        satellite_name="customer_es",
        parent_entity="customer_h",
        parent_hashkey="hk_customer_h",
        stage_name="stg__tpch__customer",
        group="customers",
    )


def _yaml_metadata(rendered: str) -> dict[str, object]:
    """Extract and parse the ``yaml_metadata`` block of a rendered model."""
    start_marker = "{%- set yaml_metadata -%}"
    end_marker = "{%- endset -%}"
    start = rendered.index(start_marker) + len(start_marker)
    end = rendered.index(end_marker, start)
    return yaml.safe_load(rendered[start:end])


def test_effectivity_satellite_sets_source_is_single_batch(django_setup) -> None:
    """datavault4dbt >= 2.0 requires source_is_single_batch; it defaults to
    false (multi-batch), which is correct for single- and multi-load stages."""
    metadata = _yaml_metadata(_render_effectivity_satellite())

    assert metadata == {
        "source_model": "stg__tpch__customer",
        "tracked_hashkey": "hk_customer_h",
        "source_is_single_batch": False,
    }
