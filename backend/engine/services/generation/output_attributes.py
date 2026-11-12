"""
Per-model output attributes stored in an entity's ``generation_config``.

An entity's ``generation_config`` holds, per framework and output kind, the
attributes of one generated model, e.g. for a hub::

    {"dbt": {"hub": {"model_name": "hub_customer",
                     "file_path": "raw_vault/hubs/hub_customer.sql",
                     "materialized": "incremental",
                     "tags": ["hub"],
                     "schema": "rdv"}}}

Imports from an existing project (dbt manifest, Premium / JSON) store them so
generation can reproduce the original model names, file paths and configs.
Anything not set is derived as before. Only the ``dbt`` framework is read
today; other frameworks can add their own key next to it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# Output kinds of the dbt models an entity can produce.
DBT_OUTPUT_KINDS = frozenset(
    {
        "stage",
        "hub",
        "link",
        "satellite_v0",
        "satellite_v1",
        "record_tracking_satellite",
        "effectivity_satellite",
        "pit",
        "reference_table",
        "snapshot_control_v0",
        "snapshot_control_v1",
    }
)

# Config keys with their own attribute; custom_config_json must not repeat them.
_DEDICATED_CONFIG_KEYS = frozenset(
    {"materialized", "alias", "schema", "database", "tags"}
)

_MODEL_NAME = re.compile(r"[A-Za-z0-9_]+")
# Relation names: also `$` and `-` (e.g. BigQuery project ids).
_RELATION_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_$\-]*")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TAG = re.compile(r"[A-Za-z0-9_.\-]+")
_PATH_SEGMENT = re.compile(r"[A-Za-z0-9_.\-]+")


class OutputAttributesError(ValueError):
    """An entity's generation_config cannot be used."""


def _check(pattern: re.Pattern[str], value: str | None, what: str) -> str | None:
    if value is not None and not pattern.fullmatch(value):
        raise ValueError(f"{value!r} is not a valid {what}")
    return value


class DbtModelAttributes(BaseModel):
    """Attributes of one generated dbt model. Unset ones are derived."""

    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, protected_namespaces=()
    )

    model_name: str | None = None
    alias: str | None = None
    # Path of the .sql file, relative to models/. Its stem is the model name.
    file_path: str | None = None
    materialized: str | None = None
    tags: list[str] | None = None
    schema_name: str | None = Field(default=None, alias="schema")
    database: str | None = None
    # Further config() settings, e.g. {"unique_key": "hk_customer_h"}.
    custom_config_json: dict[str, Any] | None = None

    @field_validator("model_name")
    @classmethod
    def _model_name(cls, value: str | None) -> str | None:
        return _check(_MODEL_NAME, value, "model name")

    @field_validator("alias", "schema_name", "database")
    @classmethod
    def _relation_name(cls, value: str | None) -> str | None:
        return _check(_RELATION_NAME, value, "relation name")

    @field_validator("materialized")
    @classmethod
    def _materialized(cls, value: str | None) -> str | None:
        return _check(_IDENTIFIER, value, "materialization name")

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str] | None) -> list[str] | None:
        for tag in value or []:
            _check(_TAG, tag, "tag")
        return value

    @field_validator("file_path")
    @classmethod
    def _file_path(cls, value: str | None) -> str | None:
        """A relative path inside models/ ending in .sql (see #450)."""
        if value is None:
            return None
        path = PurePosixPath(value)
        if (
            "\\" in value
            or path.is_absolute()
            or path.suffix != ".sql"
            or any(
                part in (".", "..") or not _PATH_SEGMENT.fullmatch(part)
                for part in path.parts
            )
        ):
            raise ValueError(
                f"{value!r} is not a relative path to a .sql file inside models/"
            )
        return value

    @field_validator("custom_config_json")
    @classmethod
    def _custom_config(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        for key in value or {}:
            _check(_IDENTIFIER, key, "config key")
            if key in _DEDICATED_CONFIG_KEYS:
                raise ValueError(f"set {key!r} with its own attribute")
        return value

    @property
    def file_stem(self) -> str | None:
        return PurePosixPath(self.file_path).stem if self.file_path else None

    @property
    def directory(self) -> PurePosixPath | None:
        """Folder of the model file, relative to models/."""
        return PurePosixPath(self.file_path).parent if self.file_path else None

    @property
    def resolved_model_name(self) -> str | None:
        return self.model_name or self.file_stem


def dbt_model_attributes(
    generation_config: Mapping[str, Any] | None, output_kind: str
) -> DbtModelAttributes:
    """Read the dbt attributes of one output kind from a generation_config.

    Returns empty attributes when none are set. Raises OutputAttributesError
    when the config is malformed or names an unknown output kind.
    """
    dbt_section = (generation_config or {}).get("dbt") or {}
    if not isinstance(dbt_section, Mapping):
        raise OutputAttributesError("generation_config.dbt must be an object")
    unknown = sorted(set(dbt_section) - DBT_OUTPUT_KINDS)
    if unknown:
        raise OutputAttributesError(
            f"generation_config.dbt has unknown output kinds: {', '.join(unknown)}"
        )
    try:
        attributes = DbtModelAttributes.model_validate(
            dbt_section.get(output_kind) or {}
        )
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'value'}: {err['msg']}"
            for err in exc.errors()
        )
        raise OutputAttributesError(
            f"generation_config.dbt.{output_kind}: {details}"
        ) from exc
    if (
        attributes.model_name
        and attributes.file_stem
        and attributes.model_name != attributes.file_stem
    ):
        raise OutputAttributesError(
            f"generation_config.dbt.{output_kind}: file_path "
            f"{attributes.file_path!r} does not match model_name "
            f"{attributes.model_name!r}"
        )
    return attributes


def config_literal(value: Any) -> str:
    """A value as a literal for a dbt config() call (Jinja accepts Python's)."""
    return repr(value)
