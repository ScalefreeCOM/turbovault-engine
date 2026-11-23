"""
Output attributes of generated models: the rules for their values.

An entity can store, per model it generates (its *output kind*), the name,
folder and ``config()`` settings the generated model should have, e.g. the
ones of the dbt project it was imported from. The project stores them as
``engine.models.ModelOutput`` rows, one per model. The JSON export carries
them as each entity's ``generation_config``, keyed by framework and then by
output kind (issue #442)::

    {"dbt": {"satellite_v0": {"model_name": "sat_customer",
                              "file_path": "raw/sat_customer.sql"},
             "satellite_v1": {"alias": "customer_details", "tags": ["daily"],
                              "custom_config_json": {"persist_docs": {"relation": true}}}}}

Only ``dbt`` is defined today; another framework (e.g. SQLMesh) gets its own
key next to it rather than sharing the dbt attributes.

This module holds the rules both share: what a model name, a folder, a
``file_path`` and a ``config()`` key may be. Generation writes every value
through escaping literals, so the rules only keep a model inside the dbt
project and its ``config()`` call valid; they accept what real dbt projects
use (e.g. a schema given as a Jinja expression). It must not import services.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible

# Frameworks a generation_config may hold attributes for.
GENERATION_CONFIG_FRAMEWORKS: tuple[str, ...] = ("dbt",)

# Output kinds each entity generates, by the entity's model name.
OUTPUT_KINDS_BY_ENTITY: dict[str, tuple[str, ...]] = {
    # A pre-stage table has its pre-stage model and (usually) a stage.
    "SourceTable": ("stage", "prestage"),
    "Hub": ("hub", "record_tracking_satellite", "effectivity_satellite"),
    "Link": ("link", "record_tracking_satellite", "effectivity_satellite"),
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

# config() keys that have their own attribute; the further config may not set
# them, so each setting has exactly one place.
DEDICATED_CONFIG_KEYS: frozenset[str] = frozenset(
    {"materialized", "alias", "schema", "database", "tags"}
)

# The folder a file_path is relative to.
MODELS_FOLDER = "models"

# A model name is a file name: no path separators, no leading dot, no
# whitespace or control characters.
_MODEL_NAME = re.compile(r"[^/\\\s.][^/\\\s]*")
# config() keys are written as keyword arguments of a dbt config() call.
_CONFIG_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def model_name_error(name: str) -> str | None:
    """Why *name* can't be a model's name, or None when it can."""
    if not _MODEL_NAME.fullmatch(name) or "\x00" in name:
        return (
            f"'{name}' can't name a dbt model: use letters, digits and "
            "underscores, without spaces, dots or slashes"
        )
    return None


def normalize_folder(folder: str) -> str:
    """A folder relative to the dbt project: forward slashes, no outer slashes."""
    return folder.strip().replace("\\", "/").strip("/")


def folder_error(folder: str) -> str | None:
    """Why *folder* can't hold a model, or None when it can.

    The folder is relative to the dbt project. It must stay inside it: no
    absolute paths, drive letters or ``..`` segments.
    """
    if not folder:
        return None
    raw = folder.strip()
    if raw.startswith(("/", "\\", "~")) or re.match(r"[A-Za-z]:", raw):
        return f"Folder '{folder}' must be relative to the dbt project"
    parts = PurePosixPath(normalize_folder(raw)).parts
    if any(part in ("..", ".") for part in parts) or "\x00" in raw:
        return f"Folder '{folder}' must stay inside the dbt project (no '..' or '.')"
    return None


def config_key_errors(config: Any) -> list[str]:
    """What is wrong with further ``config()`` settings (empty if valid).

    Keys are identifiers, as a ``config()`` call takes them (``post_hook``,
    not ``post-hook``), and none has an attribute of its own.
    """
    if not isinstance(config, Mapping):
        return ["the further config must be a mapping of config() key to value"]
    errors = []
    for key in config:
        if not isinstance(key, str) or not _CONFIG_KEY.fullmatch(key):
            errors.append(
                f"config() key {key!r} must be a letter or _ followed by "
                "letters, digits or _"
            )
        elif key in DEDICATED_CONFIG_KEYS:
            errors.append(f"config() key '{key}' has its own attribute")
    return errors


def file_path_folder(file_path: str) -> str:
    """The folder of a model's ``file_path``, relative to the dbt project."""
    parent = PurePosixPath(file_path).parent
    return MODELS_FOLDER if str(parent) == "." else f"{MODELS_FOLDER}/{parent}"


def file_path_of(folder: str, model_name: str) -> str | None:
    """A model's ``file_path`` (relative to ``models/``), or None when its
    folder isn't below ``models/``."""
    folder = normalize_folder(folder)
    if folder == MODELS_FOLDER:
        return f"{model_name}.sql"
    prefix = f"{MODELS_FOLDER}/"
    if not folder.startswith(prefix):
        return None
    return f"{folder[len(prefix):]}/{model_name}.sql"


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
    model_name = attributes.get("model_name")
    if model_name is not None:
        if not isinstance(model_name, str):
            errors.append(f"'model_name' must be a string, got {model_name!r}")
        elif error := model_name_error(model_name):
            errors.append(error)
    for name in ("alias", "schema", "database", "materialized"):
        value = attributes.get(name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            errors.append(f"'{name}' must be a non-empty string, got {value!r}")

    tags = attributes.get("tags")
    if tags is not None and (
        not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)
    ):
        errors.append("'tags' must be a list of strings")

    custom_config = attributes.get("custom_config_json")
    if custom_config is not None:
        errors.extend(
            f"'custom_config_json': {error}"
            for error in config_key_errors(custom_config)
        )

    file_path = attributes.get("file_path")
    if file_path is not None:
        errors.extend(_file_path_errors(file_path, model_name))
    return errors


def _file_path_errors(file_path: Any, model_name: Any) -> list[str]:
    """Containment and naming checks for a model's ``file_path``."""
    if not isinstance(file_path, str) or not file_path:
        return ["'file_path' must be a non-empty string"]
    if "\\" in file_path or file_path.startswith(("/", "~")) or ":" in file_path:
        return [
            f"'file_path' must be a relative path with forward slashes, "
            f"got {file_path!r}"
        ]
    if error := folder_error(file_path):
        return [f"'file_path' {file_path!r} must stay inside models/: {error}"]
    name = PurePosixPath(file_path).name
    if not name.endswith(".sql"):
        return [f"'file_path' {file_path!r} must name a .sql file"]
    stem = name.removesuffix(".sql")
    if model_name_error(stem):
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
    """Validator of a ``generation_config`` value.

    The entity fields it validated (migration 0019) moved to
    ``ModelOutput`` (migration 0026); migration 0019 still names it.
    """

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
