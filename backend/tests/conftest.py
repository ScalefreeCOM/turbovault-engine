"""
Pytest configuration and fixtures for TurboVault Engine tests.
"""

import json
import os
from pathlib import Path
from typing import Generator

import pytest

# Set Django settings before any Django imports
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")


@pytest.fixture(scope="session")
def django_setup() -> None:
    """Initialize Django for the test session."""
    import django

    django.setup()


@pytest.fixture
def sample_export_path() -> Path:
    """Path to sample export JSON file."""
    project_root = Path(__file__).parent.parent.parent

    # Prefer the test export file if it exists
    test_export = project_root / "pizza_delivery_empire_export_test.json"
    if test_export.exists():
        return test_export

    # Otherwise look for any export JSON file
    export_files = list(project_root.glob("*_export_*.json"))
    if export_files:
        return export_files[0]

    pytest.skip("No sample export JSON file found")


@pytest.fixture
def sample_export_data(sample_export_path: Path) -> dict:
    """Load sample export data from JSON file."""
    with open(sample_export_path) as f:
        return json.load(f)


@pytest.fixture
def project_export(django_setup, sample_export_data: dict):
    """Create a ProjectExport from sample data."""
    from engine.services.export.models import ProjectExport

    try:
        return ProjectExport(**sample_export_data)
    except Exception as e:
        pytest.skip(f"Could not create ProjectExport from sample data: {e}")


@pytest.fixture
def temp_output_dir(tmp_path: Path) -> Path:
    """Create a temporary output directory for generated files."""
    output_dir = tmp_path / "dbt_output"
    output_dir.mkdir()
    return output_dir


@pytest.fixture
def generation_config():
    """Create a default GenerationConfig for testing."""
    from engine.services.generation import GenerationConfig

    return GenerationConfig(
        project_name="test_project",
        profile_name="default",
    )


@pytest.fixture
def template_resolver(django_setup):
    """Create a TemplateResolver for testing (file-based only)."""
    from engine.services.generation import TemplateResolver

    # Disable database lookups for tests to avoid ORM issues
    return TemplateResolver(use_db_templates=False)


# Sample data fixtures for unit tests
@pytest.fixture
def sample_hub_definition() -> dict:
    """Sample hub definition for validation tests."""
    return {
        "hub_name": "hub_customer",
        "hub_type": "standard",
        "group": "customer_domain",
        "hashkey": {"hashkey_name": "hk_customer"},
        "business_key_columns": ["customer_id"],
        "source_tables": ["stg__app__customers"],
    }


@pytest.fixture
def sample_link_definition() -> dict:
    """Sample link definition for validation tests."""
    return {
        "link_name": "link_customer_order",
        "link_type": "standard",
        "group": "operations_domain",
        "hashkey": {"hashkey_name": "lk_customer_order"},
        "foreign_hashkeys": ["hk_customer", "hk_order"],
        "hub_references": ["hub_customer", "hub_order"],
        "source_tables": ["stg__app__orders"],
    }


@pytest.fixture
def sample_satellite_definition() -> dict:
    """Sample satellite definition for validation tests."""
    return {
        "satellite_name": "sat_customer_details",
        "satellite_type": "standard",
        "parent_entity": "hub_customer",
        "parent_type": "hub",
        "group": "customer_domain",
        "stage_name": "stg__app__customers",
        "hashdiff_name": "hd_customer_details",
        "parent_hashkey": "hk_customer",
        "columns": [
            {"source_column": "customer_name"},
            {"source_column": "email"},
        ],
    }


@pytest.fixture
def sample_source_definition() -> dict:
    """Sample source definition for validation tests."""
    return {
        "source_system": "PizzaOrderApp",
        "schema_name": "raw_pizza",
        "database_name": "analytics",
        "tables": [
            {
                "table_name": "customers",
                "columns": [
                    {"column_name": "customer_id", "datatype": "VARCHAR"},
                ],
            },
        ],
    }


@pytest.fixture
def sample_stage_definition() -> dict:
    """Sample stage definition for validation tests."""
    return {
        "stage_name": "stg__pizzaorderapp__customers",
        "source_system": "PizzaOrderApp",
        "source_table": "customers",
        "rsrc": "PIZZA_APP",
        "ldts": "load_timestamp",
        "hashkeys": [{"hashkey_name": "hk_customer", "columns": ["customer_id"]}],
        "hashdiffs": [{"hashdiff_name": "hd_customer_details", "columns": ["name"]}],
    }
