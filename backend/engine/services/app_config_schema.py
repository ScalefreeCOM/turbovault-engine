"""
Application-level configuration schema for TurboVault Engine.

Defines the structure of turbovault.yml which contains global settings
like database configuration, project root, admin credentials, and defaults.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from engine.services.config_schema import DatabaseConfig, DatabaseEngine


class AdminCredentials(BaseModel):
    """Django admin superuser credentials for auto-creation."""

    username: str = Field(
        ...,
        min_length=1,
        description="Admin username",
    )
    password: str = Field(
        ...,
        min_length=1,
        description="Admin password",
    )
    email: str = Field(
        ...,
        description="Admin email address",
    )

    @field_validator("username", "password")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Validate that username and password are not empty."""
        if not v.strip():
            raise ValueError("Field cannot be empty or whitespace")
        return v.strip()


class GlobalDefaults(BaseModel):
    """Global default values for new projects."""

    stage_schema: str = Field("stage", description="Default staging schema name")
    rdv_schema: str = Field("rdv", description="Default RDV schema name")
    bdv_schema: str = Field("bdv", description="Default BDV schema name")
    hashdiff_naming: str | None = Field(
        None, description="Default hashdiff naming pattern"
    )
    hashkey_naming: str | None = Field(
        None, description="Default hashkey naming pattern"
    )
    satellite_v0_naming: str | None = Field(
        None, description="Default satellite v0 naming pattern"
    )
    satellite_v1_naming: str | None = Field(
        None, description="Default satellite v1 naming pattern"
    )


class ApplicationConfig(BaseModel):
    """
    Application-level configuration for TurboVault Engine.

    This is loaded from turbovault.yml and contains Django-level settings
    and global defaults, not project-specific configuration.
    """

    database: DatabaseConfig | None = Field(
        None,
        description="Database configuration (defaults to SQLite if not specified)",
    )

    project_root: str | None = Field(
        None,
        description=(
            "Root directory where all project folders are located. "
            "If not specified, defaults to directory containing turbovault.yml"
        ),
    )

    admin: AdminCredentials | None = Field(
        None,
        description="Optional admin credentials for auto-creation on first startup",
    )

    defaults: GlobalDefaults = Field(
        default_factory=GlobalDefaults,
        description="Global default values for new projects",
    )

    @model_validator(mode="after")
    def set_default_database(self) -> ApplicationConfig:
        """Ensure database config exists with SQLite defaults."""
        if self.database is None:
            self.database = DatabaseConfig(
                engine=DatabaseEngine.SQLITE,
                name="db.sqlite3",
            )
        return self

    model_config = {
        "extra": "forbid",  # Don't allow unknown fields
        "str_strip_whitespace": True,
    }
