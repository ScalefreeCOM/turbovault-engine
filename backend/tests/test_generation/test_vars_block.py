"""
Tests for the datavault4dbt global-vars passthrough:
  - render_vars_block() serialization behavior
  - the dbt_project.yml template splicing the block correctly and staying
    byte-identical when no vars are supplied.
"""

import pytest
import yaml

from engine.services.generation.vars_block import render_vars_block


class TestRenderVarsBlock:
    def test_empty_mapping_returns_empty_string(self):
        assert render_vars_block({}) == ""

    def test_none_returns_empty_string(self):
        assert render_vars_block(None) == ""

    def test_mixed_types_round_trip(self):
        global_vars = {
            "hash": "MD5",
            "flag": True,
            "n": 3,
            "ts": "1970-01-01T00:00:01",
        }
        block = render_vars_block(global_vars)

        # Parses as valid YAML and round-trips the mapping.
        parsed = yaml.safe_load(block)
        assert parsed == {"vars": global_vars}

        # Correct YAML typing/quoting.
        assert "flag: true" in block  # bool, not "True"
        assert "n: 3" in block  # int, unquoted
        assert "ts: '1970-01-01T00:00:01'" in block  # timestamp-like str quoted

    def test_preserves_insertion_order(self):
        global_vars = {"zeta": 1, "alpha": 2, "mid": 3}
        block = render_vars_block(global_vars)

        lines = [
            line.strip().split(":")[0]
            for line in block.splitlines()
            if line.startswith("  ")
        ]
        assert lines == ["zeta", "alpha", "mid"]

    def test_trailing_blank_line_for_splicing(self):
        block = render_vars_block({"a": 1})
        assert block.endswith("\n\n")

    def test_non_mapping_raises(self):
        with pytest.raises(ValueError, match="must be a mapping"):
            render_vars_block(["not", "a", "mapping"])  # type: ignore[arg-type]

    def test_non_string_key_raises(self):
        with pytest.raises(ValueError, match="keys must be strings"):
            render_vars_block({1: "one"})  # type: ignore[dict-item]

    def test_non_serializable_value_raises(self):
        with pytest.raises(ValueError, match="non-serializable"):
            render_vars_block({"x": object()})


class TestDbtProjectTemplateVars:
    def _render(self, django_setup, **extra):
        from engine.services.generation import TemplateResolver

        resolver = TemplateResolver(use_db_templates=False)
        template = resolver.get_project_template("dbt_project.yml")
        assert template is not None
        return template.render(
            project_name="test_project",
            profile_name="default",
            stage_schema="stage",
            rdv_schema="rdv",
            bdv_schema="bdv",
            **extra,
        )

    def test_no_vars_omits_block(self, django_setup):
        content = self._render(django_setup, vars_block=render_vars_block({}))
        assert "vars:" not in content

    def test_no_vars_kwarg_is_backwards_compatible(self, django_setup):
        """Even without passing vars_block, the template must not emit vars:."""
        with_block = self._render(django_setup, vars_block=render_vars_block({}))
        without_kwarg = self._render(django_setup)
        assert with_block == without_kwarg
        assert "vars:" not in without_kwarg

    def test_vars_block_renders_and_parses(self, django_setup):
        global_vars = {"datavault4dbt.hash": "MD5", "beginning_of_all_times": True}
        content = self._render(
            django_setup, vars_block=render_vars_block(global_vars)
        )

        parsed = yaml.safe_load(content)
        assert parsed["vars"] == global_vars
        # models section must still be present after the vars block.
        assert "models" in parsed
        assert "test_project" in parsed["models"]
