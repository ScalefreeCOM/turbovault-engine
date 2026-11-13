"""
The ``config()`` block of a generated dbt model.

SQL templates write it with ``[[ model_config(materialized=..., tags=[...]) ]]``
and YAML templates write the model's tags with ``[[ model_tags([...]) ]]``.
The arguments are the template's defaults; a model's stored settings (see
``engine.models.ModelOutput``) override them: materialization, alias, schema,
database and tags, plus further ``config()`` keys added as they are.

``dbt_project.yml`` sets each layer's schema and materialization for the
layer's folder only. A model stored in a folder outside its layer's folder
therefore gets them in its own ``config()``, unless its settings say
otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from markupsafe import Markup

from engine.services.export.models import ModelOutputDef

# Keys the block writes first, in this order; the rest follow as given.
_LEADING_KEYS = ("materialized", "alias", "schema", "database", "tags")


@dataclass(frozen=True)
class LayerDefaults:
    """Schema and materialization of the layer a model belongs to."""

    materialized: str | None
    schema: str | None


def jinja_literal(value: Any) -> str:
    """*value* as a literal of dbt's Jinja, for a ``config()`` argument.

    Strings take single quotes, or double quotes when they contain single
    quotes but no double quotes (``"{{ macro('x') }}"`` reads best that way).
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "none"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        if "'" in value and '"' not in value and "\\" not in value:
            return f'"{value}"'
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    if isinstance(value, Mapping):
        items = ", ".join(
            f"{jinja_literal(str(k))}: {jinja_literal(v)}" for k, v in value.items()
        )
        return "{" + items + "}"
    if isinstance(value, Sequence):
        return "[" + ", ".join(jinja_literal(item) for item in value) + "]"
    return jinja_literal(str(value))


def yaml_tags_literal(tags: Sequence[str]) -> str:
    """Tags as a YAML flow sequence of single-quoted strings."""
    return "[" + ", ".join("'" + tag.replace("'", "''") + "'" for tag in tags) + "]"


def config_block(settings: Mapping[str, Any]) -> str:
    """A ``{{ config(...) }}`` call with one argument per line."""
    if not settings:
        return "{{ config() }}"
    lines = [f"    {key}={jinja_literal(value)}" for key, value in settings.items()]
    return "{{ config(\n" + ",\n".join(lines) + "\n) }}"


def _clean_tags(tags: Sequence[Any] | None) -> list[str]:
    """Template default tags without the empty ones (e.g. a model without group)."""
    return [str(tag) for tag in tags or [] if tag]


class ModelConfig:
    """The ``config()`` settings of one model, for its templates.

    Called from a SQL template, it renders the ``config()`` block; ``tags``
    renders the tags of the YAML file. ``config_used`` and ``tags_used``
    record whether the templates did: a workspace's copy of a template from
    before stored settings existed doesn't, and generation warns.
    """

    def __init__(
        self,
        output: ModelOutputDef | None = None,
        layer: LayerDefaults | None = None,
    ) -> None:
        self.output = output
        self.layer = layer
        self.config_used = False
        self.tags_used = False

    @property
    def needs_config(self) -> bool:
        """Whether the SQL needs more than an old template's ``config()``."""
        return bool(self.layer) or bool(self.output and self.output.settings())

    @property
    def needs_tags(self) -> bool:
        """Whether the YAML needs other tags than an old template's defaults."""
        return bool(self.output and self.output.tags is not None)

    def settings(self, **defaults: Any) -> dict[str, Any]:
        """The model's ``config()`` settings: stored over template defaults."""
        stored = self.output.settings() if self.output else {}
        layer = self.layer or LayerDefaults(None, None)

        leading: dict[str, Any] = {
            "materialized": stored.get("materialized")
            or defaults.get("materialized")
            or layer.materialized,
            "alias": stored.get("alias") or defaults.get("alias"),
            "schema": stored.get("schema") or defaults.get("schema") or layer.schema,
            "database": stored.get("database") or defaults.get("database"),
        }
        result = {key: value for key, value in leading.items() if value}
        if "tags" in stored:
            result["tags"] = list(stored["tags"])
        elif "tags" in defaults:
            result["tags"] = _clean_tags(defaults["tags"])

        for key, value in defaults.items():
            if key not in _LEADING_KEYS and value is not None:
                result[key] = value
        for key, value in stored.items():
            if key not in _LEADING_KEYS:
                result[key] = value
        return result

    def __call__(self, **defaults: Any) -> Markup:
        self.config_used = True
        return Markup(config_block(self.settings(**defaults)))

    def tags(self, defaults: Sequence[Any] | None = None) -> Markup:
        """The model's tags as a YAML flow sequence: stored, else *defaults*."""
        self.tags_used = True
        stored = self.output.tags if self.output else None
        tags = list(stored) if stored is not None else _clean_tags(defaults)
        return Markup(yaml_tags_literal(tags))

    def context(self) -> dict[str, Any]:
        """Template variables: ``model_config`` and ``model_tags``."""
        return {"model_config": self, "model_tags": self.tags}
