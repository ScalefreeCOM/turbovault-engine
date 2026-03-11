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
    SQLITE = "sqlite"


class DatabaseEngine(str, Enum):
    """Supported database backends."""

    SQLITE = "sqlite3"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    ORACLE = "oracle"
    MSSQL = "mssql"
    SNOWFLAKE = "snowflake"


class DatabaseConfig(BaseModel):
    """
    Database connection configuration.

    Allows configuring external databases (PostgreSQL, MySQL, etc.)
    instead of the default SQLite.
    """

    engine: DatabaseEngine = Field(
        DatabaseEngine.SQLITE,
        description="Database backend engine",
    )
    name: str = Field(
        ...,
        description="Database name (or file path for SQLite)",
    )
    user: str | None = Field(
        None,
        description="Database username (not required for SQLite)",
    )
    password: str | None = Field(
        None,
        description="Database password (not required for SQLite)",
    )
    host: str | None = Field(
        None,
        description="Database host (not required for SQLite)",
    )
    port: int | None = Field(
        None,
        description="Database port (not required for SQLite)",
    )
    options: dict[str, str] | None = Field(
        None,
        description="Additional database options (e.g., sslmode, charset)",
    )

    @model_validator(mode="after")
    def validate_required_fields(self) -> DatabaseConfig:
        """Validate that required fields are present based on engine type."""
        # SQLite only needs name (file path)
        if self.engine == DatabaseEngine.SQLITE:
            return self

        # All other databases require user, password, and host
        missing_fields = []

        if not self.user:
            missing_fields.append("user")
        if not self.password:
            missing_fields.append("password")
        if not self.host:
            missing_fields.append("host")

        if missing_fields:
            raise ValueError(
                f"Database engine '{self.engine}' requires the following fields: "
                f"{', '.join(missing_fields)}"
            )

        return self

    def to_django_config(
        self, base_dir: Path | None = None
    ) -> dict[str, str | int | dict]:
        """
        Convert to Django DATABASES configuration format.

        Args:
            base_dir: Base directory for resolving relative SQLite paths

        Returns:
            Dictionary compatible with Django DATABASES setting
        """
        config: dict[str, str | int | dict] = {
            "ENGINE": f"django.db.backends.{self.engine.value}",
            "NAME": self.name,
        }

        # For SQLite, resolve path relative to base_dir if provided
        if self.engine == DatabaseEngine.SQLITE and base_dir:
            db_path = Path(self.name)
            if not db_path.is_absolute():
                config["NAME"] = str(base_dir / db_path)

        # Add connection parameters for non-SQLite databases
        if self.engine != DatabaseEngine.SQLITE:
            if self.user:
                config["USER"] = self.user
            if self.password:
                config["PASSWORD"] = self.password
            if self.host:
                config["HOST"] = self.host
            if self.port:
                config["PORT"] = self.port

        # Add additional options if provided
        if self.options:
            config["OPTIONS"] = self.options

        return config


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


class SqliteSourceConfig(BaseModel):
    """Configuration for importing metadata from SQLite."""

    type: Literal[SourceType.SQLITE] = Field(
        SourceType.SQLITE, description="Source type (must be 'sqlite')"
    )
    path: Path = Field(
        ..., description="Path to SQLite database containing source metadata"
    )

    @field_validator("path")
    @classmethod
    def validate_path_exists(cls, v: Path) -> Path:
        """Warn if file doesn't exist."""
        if not v.exists():
            import warnings

            warnings.warn(
                f"SQLite database not found: {v}. It will need to exist before import.",
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
    bdv_schema: str = Field("bdv", description="Schema name for Business Data Vault layer")
    bdv_database: str | None = Field(
        None, description="Optional database name for Business Data Vault layer"
    )
    hashdiff_naming: str | None = Field(
        None, description="Naming pattern for hashdiff columns"
    )
    hashkey_naming: str | None = Field(
        None, description="Naming pattern for hub/link hashkey columns"
    )
    satellite_v0_naming: str | None = Field(
        None, description="Naming pattern for v0 satellite models"
    )
    satellite_v1_naming: str | None = Field(
        None, description="Naming pattern for v1 satellite models"
    )

    @field_validator("stage_schema", "rdv_schema", "bdv_schema")
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

    # Output path overrides — all are optional.
    # When absent the generate command falls back to the convention:
    #   exports/dbt_project/  exports/json/  exports/dbml/
    dbt_project_dir: Path | None = Field(
        None,
        description="Custom directory for generated dbt project (default: exports/dbt_project/)",
    )
    json_output_dir: Path | None = Field(
        None,
        description="Custom directory for JSON exports (default: exports/json/)",
    )
    dbml_output_dir: Path | None = Field(
        None,
        description="Custom directory for DBML exports (default: exports/dbml/)",
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


class TurboVaultConfig(BaseModel):
    """
    Root configuration model for TurboVault Engine.

    This is the main config object loaded from config.yml.
    """

    project: ProjectInfo = Field(..., description="Project information")
    source: ExcelSourceConfig | SqliteSourceConfig | None = Field(
        None, description="Optional source metadata import configuration"
    )
    database: DatabaseConfig | None = Field(
        None,
        description="Optional database configuration (defaults to SQLite if not specified)",
    )
    configuration: ProjectConfiguration = Field(
        default_factory=ProjectConfiguration,
        description="Project-level Data Vault configuration",
    )
    output: OutputConfiguration = Field(
        default_factory=OutputConfiguration,
        description="dbt project output configuration",
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
