"""
Output attributes of generated models.

An entity can store, per model it generates (its *output kind*), the file
path, model name and config the generated model should have — e.g. the ones
of the dbt project it was imported from. Generation derives everything it
does not find here, as it always has.

The attributes live in an ``output_attributes`` JSON field on each entity,
keyed by output kind::

    {"satellite_v0": {"model_name": "sat_customer", "file_path": "raw/sat_customer.sql"},
     "satellite_v1": {"alias": "customer_details", "tags": ["daily"]}}

This module only holds the format rules, shared by the Django field
validator, the export/import schema and generation. It must not import
services.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.deconstruct import deconstructible

# Output kinds each entity generates, by the entity's model name.
OUTPUT_KINDS_BY_ENTITY: dict[str, tuple[str, ...]] = {
    "SourceTable": ("stage",),
    "Hub": ("hub", "record_tracking_satellite", "effectivity_satellite"),
    "Link": ("link", "record_tracking_satellite"),
    "Satellite": ("satellite_v0", "satellite_v1"),
    "PIT": ("pit",),
    "ReferenceTable": ("reference_table",),
    "SnapshotControlTable": ("snapshot_control_v0", "snapshot_control_v1"),
}

OUTPUT_ATTRIBUTE_FIELDS: tuple[str, ...] = (
    "model_name",
    "alias",
    "file_path",
    "materialized",
    "tags",
    "schema",
    "database",
)

# dbt names a model after its file, so a model name is also a file stem.
_MODEL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Relation names dbt writes into SQL; `$` is valid in Snowflake/Postgres.
_RELATION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
# Databases may also be e.g. BigQuery project ids (`my-project-123`).
_DATABASE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_$-]*")
_MATERIALIZATION = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Tags are written into single-quoted SQL and YAML strings, so no quotes,
# backslashes or whitespace.
_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:/-]*")
# One folder or file name of a model path.
_PATH_SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")


def output_attribute_errors(attributes: Mapping[str, Any]) -> list[str]:
    """Return what is wrong with one output kind's attributes (empty if valid).

    ``file_path`` is relative to the dbt project's ``models/`` folder, uses
    forward slashes, ends in ``.sql`` and cannot leave ``models/``. When both
    ``file_path`` and ``model_name`` are set, the file must be named after the
    model, as dbt requires.
    """
    if not isinstance(attributes, Mapping):
        return ["must be a mapping of attribute name to value"]

    errors = [
        f"unknown attribute '{name}'"
        for name in attributes
        if name not in OUTPUT_ATTRIBUTE_FIELDS
    ]
    checks = (
        ("model_name", _MODEL_NAME, "a letter or _ followed by letters, digits or _"),
        ("alias", _RELATION_NAME, "a SQL identifier"),
        ("schema", _RELATION_NAME, "a SQL identifier"),
        ("database", _DATABASE_NAME, "a database name"),
        ("materialized", _MATERIALIZATION, "a dbt materialization name"),
    )
    for name, pattern, expected in checks:
        value = attributes.get(name)
        if value is None:
            continue
        if not isinstance(value, str) or not pattern.fullmatch(value):
            errors.append(f"'{name}' must be {expected}, got {value!r}")

    tags = attributes.get("tags")
    if tags is not None:
        if not isinstance(tags, list) or not all(
            isinstance(tag, str) and _TAG.fullmatch(tag) for tag in tags
        ):
            errors.append(
                "'tags' must be a list of tags made of letters, digits and _ . : / -"
            )

    file_path = attributes.get("file_path")
    if file_path is not None:
        errors.extend(_file_path_errors(file_path, attributes.get("model_name")))
    return errors


def _file_path_errors(file_path: Any, model_name: Any) -> list[str]:
    """Containment and naming checks for a model's ``file_path``."""
    if not isinstance(file_path, str) or not file_path:
        return ["'file_path' must be a non-empty string"]
    if "\\" in file_path or file_path.startswith("/") or ":" in file_path:
        return [
            f"'file_path' must be a relative path with forward slashes, "
            f"got {file_path!r}"
        ]
    segments = file_path.split("/")
    if any(
        segment in ("", ".", "..") or not _PATH_SEGMENT.fullmatch(segment)
        for segment in segments
    ):
        return [
            f"'file_path' {file_path!r} must stay inside models/ and use only "
            "letters, digits, _ . - in folder and file names"
        ]
    if not segments[-1].endswith(".sql"):
        return [f"'file_path' {file_path!r} must name a .sql file"]
    stem = segments[-1].removesuffix(".sql")
    if not _MODEL_NAME.fullmatch(stem):
        return [f"the file name of 'file_path' {file_path!r} is not a valid model name"]
    if isinstance(model_name, str) and model_name != stem:
        return [
            f"'file_path' {file_path!r} must be named after 'model_name' "
            f"({model_name}.sql): dbt names a model after its file"
        ]
    return []


def output_attributes_errors(value: Any, allowed_kinds: tuple[str, ...]) -> list[str]:
    """Return what is wrong with a whole ``output_attributes`` value."""
    if value in (None, {}):
        return []
    if not isinstance(value, Mapping):
        return ["output attributes must be a mapping of output kind to attributes"]
    errors: list[str] = []
    for kind, attributes in value.items():
        if kind not in allowed_kinds:
            errors.append(
                f"unknown output kind '{kind}' (expected one of: "
                f"{', '.join(allowed_kinds)})"
            )
            continue
        errors.extend(
            f"{kind}: {error}" for error in output_attribute_errors(attributes)
        )
    return errors


@deconstructible
class OutputAttributesValidator:
    """Django field validator for an entity's ``output_attributes``."""

    def __init__(self, allowed_kinds: tuple[str, ...]) -> None:
        self.allowed_kinds = tuple(allowed_kinds)

    def __call__(self, value: Any) -> None:
        errors = output_attributes_errors(value, self.allowed_kinds)
        if errors:
            raise ValidationError(errors)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, OutputAttributesValidator)
            and self.allowed_kinds == other.allowed_kinds
        )


def output_attributes_field(entity: str) -> models.JSONField:
    """The ``output_attributes`` JSON field for the given entity model."""
    kinds = OUTPUT_KINDS_BY_ENTITY[entity]
    return models.JSONField(
        default=dict,
        blank=True,
        validators=[OutputAttributesValidator(kinds)],
        help_text=(
            "Output attributes of the generated model(s), keyed by output kind "
            f"({', '.join(kinds)}): model_name, alias, file_path (relative to "
            "models/), materialized, tags, schema, database. Generation derives "
            "whatever is not set."
        ),
    )
