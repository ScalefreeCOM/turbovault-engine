"""
Configuration schema for TurboVault Engine.

Defines Pydantic models for validating config.yml structure with strong typing.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SourceType(str, Enum):
    """Supported source metadata types."""

    EXCEL = "excel"


class ProjectInfo(BaseModel):
    """Project metadata and identification."""

    name: str = Field(
        ...,
        min_length=1,
        description="Project name (will be used as dbt project name if not specified)",
    )
    description: str | None = Field(None, description="Optional project description")

    @field_validator("name")
    @classmethod
    def validate_project_name(cls, v: str) -> str:
        """Validate project name is not just whitespace."""
        if not v.strip():
            raise ValueError("Project name cannot be empty or whitespace")
        return v.strip()


class ExcelSourceConfig(BaseModel):
    """Configuration for importing metadata from Excel."""

    type: Literal[SourceType.EXCEL] = Field(
        SourceType.EXCEL, description="Source type (must be 'excel')"
    )
    path: Path = Field(..., description="Path to Excel file containing source metadata")

    @field_validator("path")
    @classmethod
    def validate_path_exists(cls, v: Path) -> Path:
        """Warn if file doesn't exist (not error, file might be created later)."""
        if not v.exists():
            import warnings

            warnings.warn(
                f"Excel file not found: {v}. It will need to exist before import.",
                stacklevel=2,
            )
        return v


class ProjectConfiguration(BaseModel):
    """Project-level Data Vault configuration."""

    stage_schema: str = Field("stage", description="Schema name for staging layer")
    stage_database: str | None = Field(
        None, description="Optional database name for staging layer"
    )
    rdv_schema: str = Field("rdv", description="Schema name for Raw Data Vault layer")
    rdv_database: str | None = Field(
        None, description="Optional database name for Raw Data Vault layer"
    )
    hashdiff_naming_pattern: str | None = Field(
        None, description="Optional naming pattern for hashdiff columns (future use)"
    )

    @field_validator("stage_schema", "rdv_schema")
    @classmethod
    def validate_schema_name(cls, v: str) -> str:
        """Validate schema name is a valid SQL identifier."""
        if not v:
            raise ValueError("Schema name cannot be empty")

        # Basic SQL identifier validation
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                f"Schema name '{v}' contains invalid characters. "
                "Use only letters, numbers, underscores, and hyphens."
            )

        return v


class OutputConfiguration(BaseModel):
    """dbt project output configuration."""

    dbt_project_dir: Path = Field(
        ..., description="Directory where dbt project will be generated"
    )
    dbt_project_name: str | None = Field(
        None, description="Name of the dbt project (defaults to project.name)"
    )
    create_zip: bool = Field(
        False, description="Whether to create a ZIP archive of the generated project"
    )

    # Export control options
    export_sources: bool = Field(
        True, description="Whether to include source system definitions in export"
    )

    generate_tests: bool = Field(
        True, description="Whether to generate dbt tests (for future use)"
    )

    generate_dbml: bool = Field(
        False,
        description="Whether to generate DBML file alongside dbt project (for future use)",
    )

    @field_validator("dbt_project_dir")
    @classmethod
    def normalize_path(cls, v: Path) -> Path:
        """Normalize path and ensure it's absolute."""
        return v.expanduser().resolve()


class TurboVaultConfig(BaseModel):
    """
    Root configuration model for TurboVault Engine.

    This is the main config object loaded from config.yml.
    """

    project: ProjectInfo = Field(..., description="Project information")
    source: ExcelSourceConfig | None = Field(
        None, description="Optional source metadata import configuration"
    )
    configuration: ProjectConfiguration = Field(
        default_factory=ProjectConfiguration,
        description="Project-level Data Vault configuration",
    )
    output: OutputConfiguration = Field(
        ..., description="dbt project output configuration"
    )

    @model_validator(mode="after")
    def set_default_dbt_project_name(self) -> TurboVaultConfig:
        """Set dbt_project_name to project.name if not specified."""
        if self.output.dbt_project_name is None:
            self.output.dbt_project_name = self.project.name
        return self

    model_config = {
        "extra": "forbid",  # Don't allow unknown fields
        "str_strip_whitespace": True,
    }
