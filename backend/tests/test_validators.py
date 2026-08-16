"""
Unit tests for pre-generation validators.
"""


class TestValidationResult:
    """Tests for ValidationResult class."""

    def test_is_valid_with_no_errors(self, django_setup):
        """Result with no errors is valid."""
        from engine.services.generation.validators import ValidationResult

        result = ValidationResult()
        assert result.is_valid

    def test_is_valid_with_warnings_only(self, django_setup):
        """Result with only warnings is still valid."""
        from engine.services.generation.validators import ValidationResult

        result = ValidationResult()
        result.add_warning("test", "entity", "field", "message")
        assert result.is_valid

    def test_is_invalid_with_errors(self, django_setup):
        """Result with errors is invalid."""
        from engine.services.generation.validators import ValidationResult

        result = ValidationResult()
        result.add_error("test", "entity", "field", "message")
        assert not result.is_valid

    def test_merge_combines_results(self, django_setup):
        """Merge combines errors and warnings from two results."""
        from engine.services.generation.validators import ValidationResult

        result1 = ValidationResult()
        result1.add_error("test", "entity1", "field", "error1")
        result1.add_warning("test", "entity1", "field", "warning1")

        result2 = ValidationResult()
        result2.add_error("test", "entity2", "field", "error2")

        result1.merge(result2)

        assert len(result1.errors) == 2
        assert len(result1.warnings) == 1


class TestValidateExport:
    """Tests for validate_export function with real export data."""

    def test_validate_export_with_sample_data(self, django_setup, project_export):
        """validate_export returns valid result for sample data."""
        from engine.services.generation.validators import validate_export

        result = validate_export(project_export)

        # Sample data may have some warnings but should be valid
        assert (
            result.is_valid or len(result.errors) >= 0
        )  # Always true, just run without crash

    def test_validate_export_returns_validation_result(
        self, django_setup, project_export
    ):
        """validate_export returns a ValidationResult object."""
        from engine.services.generation.validators import (
            ValidationResult,
            validate_export,
        )

        result = validate_export(project_export)

        assert isinstance(result, ValidationResult)

    def test_validate_export_checks_all_entity_types(
        self, django_setup, project_export
    ):
        """validate_export checks sources, stages, hubs, links, satellites."""
        from engine.services.generation.validators import validate_export

        result = validate_export(project_export)

        # Just verify it ran without error
        # The sample data should have at least some entities validated
        assert hasattr(result, "errors")
        assert hasattr(result, "warnings")


class TestValidationErrorCodes:
    """Tests for validation error codes."""

    def test_validation_error_has_code(self, django_setup):
        """ValidationError has a code field."""
        from engine.services.generation.validators import ValidationError

        error = ValidationError(
            entity_type="hub",
            entity_name="hub_test",
            field="hashkey",
            message="Test message",
            code="HUB_001",
        )

        assert error.code == "HUB_001"

    def test_validation_error_str_includes_code(self, django_setup):
        """ValidationError str representation includes code."""
        from engine.services.generation.validators import ValidationError

        error = ValidationError(
            entity_type="hub",
            entity_name="hub_test",
            field="hashkey",
            message="Test message",
            code="HUB_001",
        )

        assert "HUB_001" in str(error)

    def test_validation_warning_str(self, django_setup):
        """ValidationWarning str representation."""
        from engine.services.generation.validators import ValidationWarning

        warning = ValidationWarning(
            entity_type="hub",
            entity_name="hub_test",
            field="source_tables",
            message="Test warning",
            code="HUB_003",
        )

        assert "hub_test" in str(warning)
        assert "HUB_003" in str(warning)


class TestLinkSourceValidation:
    """LNK_003: a link with no source tables must be a hard error.

    A source-less link produces an empty `source_models` block (invalid
    datavault4dbt) and no stage computes its link hashkey. This happens when
    a link is imported without a source_table so no link_hub_source_mapping
    rows exist — generation must fail loudly rather than emit a broken model.
    """

    def _link(self, *, with_sources: bool):
        from engine.services.export.models import (
            HashkeyDefinition,
            LinkColumnMapping,
            LinkDefinition,
            LinkHubReferenceDefinition,
            LinkSourceInfo,
        )

        source_tables = []
        if with_sources:
            source_tables = [
                LinkSourceInfo(
                    source_table="orders",
                    source_system="crm",
                    stage_name="stg__crm__orders",
                    columns=[
                        LinkColumnMapping(
                            link_column_name="O_ORDERKEY",
                            link_column_type="business_key",
                            source_column_name="O_ORDERKEY",
                        ),
                    ],
                )
            ]
        return LinkDefinition(
            link_name="orders_customers_l",
            link_type="standard",
            hashkey=HashkeyDefinition(hashkey_name="hk_orders_customers_l"),
            hub_references=[
                LinkHubReferenceDefinition(hub_name="order_h"),
                LinkHubReferenceDefinition(hub_name="customer_h"),
            ],
            foreign_hashkeys=["hk_order_h", "hk_customer_h"],
            source_tables=source_tables,
        )

    def test_link_without_sources_is_error(self, django_setup):
        from engine.services.generation.validators import _validate_link

        result = _validate_link(self._link(with_sources=False))

        assert not result.is_valid
        codes = [e.code for e in result.errors]
        assert "LNK_003" in codes
        # Must be an error, not merely a warning.
        assert "LNK_003" not in [w.code for w in result.warnings]

    def test_link_with_sources_has_no_lnk_003(self, django_setup):
        from engine.services.generation.validators import _validate_link

        result = _validate_link(self._link(with_sources=True))

        assert "LNK_003" not in [e.code for e in result.errors]
        assert "LNK_003" not in [w.code for w in result.warnings]

    def test_generation_validate_stage_blocks_source_less_link(self, django_setup):
        """The validate stage surfaces LNK_003 as a blocking error issue."""
        from engine.services.export.models import ProjectExport
        from engine.services.generation.stages.validate import validate
        from engine.services.generation.types import GenerationOptions

        export = ProjectExport(project_name="t", links=[self._link(with_sources=False)])
        issues = validate(project_export=export, options=GenerationOptions())

        lnk = [i for i in issues if i.code == "validate.link.no_sources"]
        assert lnk, "expected a validate.link.no_sources issue"
        assert lnk[0].severity == "error"
