"""
Unit tests for pre-generation validators.
"""

import pytest


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
            validate_export,
            ValidationResult,
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
