"""
Output attributes of generated models.

An entity can store, per model it generates (its *output kind*), the file
path, model name and config the generated model should have — e.g. the ones
of the dbt project it was imported from. Generation derives everything it
does not find here, as it always has.

The attributes live in a ``generation_config`` JSON field on each entity,
keyed by framework and then by output kind::

    {"dbt": {"satellite_v0": {"model_name": "sat_customer",
                              "file_path": "raw/sat_customer.sql"},
             "satellite_v1": {"alias": "customer_details", "tags": ["daily"],
                              "custom_config_json": {"persist_docs": {"relation": true}}}}}

Only ``dbt`` is defined today; another framework (e.g. SQLMesh) gets its own
key next to it rather than sharing the dbt attributes.

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

# Frameworks a generation_config may hold attributes for.
GENERATION_CONFIG_FRAMEWORKS: tuple[str, ...] = ("dbt",)

# Output kinds each entity generates, by the entity's model name.
OUTPUT_KINDS_BY_ENTITY: dict[str, tuple[str, ...]] = {
    # A pre-stage table generates its pre-stage model and (usually) a stage.
    "SourceTable": ("stage", "prestage"),
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
    "custom_config_json",
)

# config() keys that have their own attribute; custom_config_json may not set
# them, so each setting has exactly one place.
DEDICATED_CONFIG_KEYS: frozenset[str] = frozenset(
    {"materialized", "alias", "schema", "database", "tags"}
)

# dbt names a model after its file, so a model name is also a file stem.
_MODEL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Relation names dbt writes into SQL; `$` is valid in Snowflake/Postgres.
_RELATION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
# Databases may also be e.g. BigQuery project ids (`my-project-123`).
_DATABASE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_$-]*")
_MATERIALIZATION = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# config() keys are written as keyword arguments of a dbt config() call.
_CONFIG_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
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
    model, as dbt requires. ``custom_config_json`` holds further ``config()``
    settings, but none that has its own attribute.
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

    custom_config = attributes.get("custom_config_json")
    if custom_config is not None:
        errors.extend(_custom_config_errors(custom_config))

    file_path = attributes.get("file_path")
    if file_path is not None:
        errors.extend(_file_path_errors(file_path, attributes.get("model_name")))
    return errors


def _custom_config_errors(custom_config: Any) -> list[str]:
    """Checks for ``custom_config_json``: further ``config()`` settings."""
    if not isinstance(custom_config, Mapping):
        return ["'custom_config_json' must be a mapping of config key to value"]
    errors = []
    for key in custom_config:
        if not isinstance(key, str) or not _CONFIG_KEY.fullmatch(key):
            errors.append(
                f"'custom_config_json' key {key!r} must be a letter or _ "
                "followed by letters, digits or _"
            )
        elif key in DEDICATED_CONFIG_KEYS:
            errors.append(
                f"'custom_config_json' cannot set '{key}': use the '{key}' attribute"
            )
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


def output_kind_errors(
    value: Any, allowed_kinds: tuple[str, ...], framework: str = "dbt"
) -> list[str]:
    """Return what is wrong with one framework's attributes, keyed by output kind.

    Messages name the attribute's place, e.g. ``dbt.hub: 'alias' must be ...``.
    """
    if not isinstance(value, Mapping):
        return [f"'{framework}' must be a mapping of output kind to attributes"]
    errors: list[str] = []
    for kind, attributes in value.items():
        if kind not in allowed_kinds:
            errors.append(
                f"{framework}: unknown output kind '{kind}' (expected one of: "
                f"{', '.join(allowed_kinds)})"
            )
            continue
        errors.extend(
            f"{framework}.{kind}: {error}"
            for error in output_attribute_errors(attributes)
        )
    return errors


def generation_config_errors(value: Any, allowed_kinds: tuple[str, ...]) -> list[str]:
    """Return what is wrong with a whole ``generation_config`` value."""
    if value in (None, {}):
        return []
    if not isinstance(value, Mapping):
        return ["generation_config must be a mapping of framework to attributes"]
    errors: list[str] = []
    for framework, by_kind in value.items():
        if framework not in GENERATION_CONFIG_FRAMEWORKS:
            errors.append(
                f"unknown framework '{framework}' (expected one of: "
                f"{', '.join(GENERATION_CONFIG_FRAMEWORKS)})"
            )
            continue
        errors.extend(output_kind_errors(by_kind, allowed_kinds, framework))
    return errors


@deconstructible
class GenerationConfigValidator:
    """Django field validator for an entity's ``generation_config``."""

    def __init__(self, allowed_kinds: tuple[str, ...]) -> None:
        self.allowed_kinds = tuple(allowed_kinds)

    def __call__(self, value: Any) -> None:
        errors = generation_config_errors(value, self.allowed_kinds)
        if errors:
            raise ValidationError(errors)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, GenerationConfigValidator)
            and self.allowed_kinds == other.allowed_kinds
        )


def generation_config_field(entity: str) -> models.JSONField:
    """The ``generation_config`` JSON field for the given entity model."""
    kinds = OUTPUT_KINDS_BY_ENTITY[entity]
    return models.JSONField(
        default=dict,
        blank=True,
        validators=[GenerationConfigValidator(kinds)],
        help_text=(
            "Output attributes of the generated model(s), keyed by framework "
            f"(dbt) and output kind ({', '.join(kinds)}): model_name, alias, "
            "file_path (relative to models/), materialized, tags, schema, "
            "database, custom_config_json. Generation derives whatever is not "
            "set."
        ),
    )
