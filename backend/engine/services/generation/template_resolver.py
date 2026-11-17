"""
Template resolver for dbt and SQLMesh project generation.

Resolves Jinja2 templates per framework, in this order:
1. Per-generation in-memory overrides (``GenerationOptions.templates_override``)
2. Database (ModelTemplate model) - for customization via Django Admin / Studio
3. File-based defaults bundled with the package under ``templates/<framework>/``
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from jinja2 import Environment, FileSystemLoader, Template, select_autoescape
from markupsafe import Markup

from engine.services.generation.python_literals import (
    py_dict_filter,
    py_hashed_columns_filter,
    py_literal,
    py_source_models_filter,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from jinja2 import BaseLoader

    from engine.models.templates import ModelTemplate
    from engine.services.generation.types import TemplateOverride


# Path to default file-based templates. Each framework has its own subdirectory
# (templates/dbt/, templates/sqlmesh/).
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Where each framework keeps its model templates, as (subdirectory, suffix):
# dbt models are SQL (templates/dbt/sql/<entity>.sql.j2), SQLMesh models are
# Python files (templates/sqlmesh/models/<entity>.py.j2). Only dbt has YAML
# templates (templates/dbt/yaml/<entity>.yml.j2).
_MODEL_TEMPLATE_LAYOUT: dict[str, tuple[str, str]] = {
    "dbt": ("sql", ".sql.j2"),
    "sqlmesh": ("models", ".py.j2"),
}


def framework_templates_dir(framework: str, templates_dir: Path | None = None) -> Path:
    """
    Return the file-based default template directory for *framework*.

    ``templates_dir`` overrides the bundled ``TEMPLATES_DIR`` root.
    """
    return (templates_dir or TEMPLATES_DIR) / framework


def model_template_suffix(framework: str) -> str:
    """Return the file suffix of *framework*'s model templates (e.g. ``.py.j2``)."""
    return _MODEL_TEMPLATE_LAYOUT.get(framework, _MODEL_TEMPLATE_LAYOUT["dbt"])[1]


def model_templates_dir(framework: str, templates_dir: Path | None = None) -> Path:
    """Return the directory holding *framework*'s bundled model templates."""
    subdir = _MODEL_TEMPLATE_LAYOUT.get(framework, _MODEL_TEMPLATE_LAYOUT["dbt"])[0]
    return framework_templates_dir(framework, templates_dir) / subdir


def bundled_model_templates(
    framework: str, templates_dir: Path | None = None
) -> list[tuple[str, Path]]:
    """
    Return ``(entity_type, path)`` for each bundled model template of *framework*.

    Sorted by entity type; empty when the framework has none.
    """
    directory = model_templates_dir(framework, templates_dir)
    suffix = model_template_suffix(framework)
    if not directory.is_dir():
        return []
    return sorted(
        (path.name.removesuffix(suffix), path) for path in directory.glob(f"*{suffix}")
    )


# Project-level YAML templates (not per entity), never seeded as ModelTemplates.
_PROJECT_LEVEL_YAML = frozenset({"dbt_project", "packages", "sources"})

# Label for a framework's model template in seeded ModelTemplate names,
# e.g. "hub_standard (SQL)" for dbt, "hub_standard (Python)" for SQLMesh.
_MODEL_TEMPLATE_LABEL: dict[str, str] = {"dbt": "SQL", "sqlmesh": "Python"}


@dataclass(frozen=True)
class BundledTemplate:
    """One bundled per-entity template file, as seeded into ModelTemplate."""

    framework: str
    entity_type: str
    # "sql" = the model template (stored in sql_template_content), "yaml" = dbt YAML.
    template_type: str
    path: Path

    @property
    def label(self) -> str:
        """Kind shown in the seeded template name: SQL, Python or YAML."""
        if self.template_type == "yaml":
            return "YAML"
        return _MODEL_TEMPLATE_LABEL.get(self.framework, "SQL")


def bundled_templates(
    framework: str, templates_dir: Path | None = None
) -> list[BundledTemplate]:
    """
    Return *framework*'s bundled per-entity templates: model templates first,
    then YAML templates. Project-level files (dbt_project.yml, …) are excluded.
    """
    templates = [
        BundledTemplate(framework, entity_type, "sql", path)
        for entity_type, path in bundled_model_templates(framework, templates_dir)
    ]
    yaml_dir = framework_templates_dir(framework, templates_dir) / "yaml"
    if yaml_dir.is_dir():
        for path in sorted(yaml_dir.glob("*.yml.j2")):
            entity_type = path.name.removesuffix(".yml.j2")
            if entity_type not in _PROJECT_LEVEL_YAML:
                templates.append(BundledTemplate(framework, entity_type, "yaml", path))
    return templates


# Characters YAML treats as line breaks that JSON leaves unescaped.
_YAML_LINE_BREAKS = {"\u0085": "\\x85", "\u2028": "\\u2028", "\u2029": "\\u2029"}


def yaml_quote(value: object) -> Markup:
    """``value`` as a double-quoted YAML scalar.

    User text — descriptions, SQL expressions — can hold anything YAML gives
    meaning to: quotes, ``: ``, `` #``, leading ``-`` or ``!``, several lines.
    A JSON string is a valid YAML double-quoted scalar that escapes all of it,
    so the value parses back exactly. Marked safe: the output is YAML and SQL,
    so HTML autoescaping (on for templates loaded from strings) must not touch
    it.
    """
    text = "" if value is None else str(value)
    quoted = json.dumps(text, ensure_ascii=False)
    for char, escaped in _YAML_LINE_BREAKS.items():
        quoted = quoted.replace(char, escaped)
    return Markup(quoted)


def yaml_scalar(value: object) -> Markup:
    """``value`` as a YAML scalar, quoted only when it has to be.

    A value YAML reads back as the same string (``stage``, ``my_schema``) is
    written as-is, so existing output stays byte-identical. Anything else —
    ``off``/``yes``/``null`` (booleans and null), numbers, ``: `` or ``#`` —
    goes through ``yaml_quote``.
    """
    text = "" if value is None else str(value)
    if text and not any(char in text for char in "\n\r" + "".join(_YAML_LINE_BREAKS)):
        try:
            if yaml.safe_load(text) == text:
                return Markup(text)
        except yaml.YAMLError:
            pass
    return yaml_quote(text)


def yaml_single_quote(value: object) -> Markup:
    """``value`` as a single-quoted YAML scalar, e.g. ``'default'``.

    Doubles embedded single quotes, the YAML escape inside single quotes.
    Line breaks cannot be kept inside single quotes, so such values fall back
    to ``yaml_quote``.
    """
    text = "" if value is None else str(value)
    if any(char in text for char in "\n\r" + "".join(_YAML_LINE_BREAKS)):
        return yaml_quote(text)
    return Markup("'" + text.replace("'", "''") + "'")


def quoted_list(values: Iterable[object] | None) -> Markup:
    """``values`` as a list of single-quoted strings, e.g. ``['a', 'b']``.

    Valid in a dbt ``config()`` call and as a YAML flow sequence. Used for
    stored model tags, which are validated to hold no quotes, backslashes or
    whitespace; escaping is kept anyway so a value can never end the string.
    """
    quoted = (
        "'" + str(item).replace("\\", "\\\\").replace("'", "\\'") + "'"
        for item in values or ()
    )
    return Markup("[" + ", ".join(quoted) + "]")


def yaml_json(value: object) -> Markup:
    """A JSON value as a YAML flow value, e.g. ``{"relation": true}``.

    Used for ``custom_config_json`` values in a model's ``.yml`` config. JSON
    is valid YAML flow syntax; the line breaks YAML knows but JSON leaves
    unescaped are escaped as in ``yaml_quote``.
    """
    dumped = json.dumps(value, ensure_ascii=False)
    for char, escaped in _YAML_LINE_BREAKS.items():
        dumped = dumped.replace(char, escaped)
    return Markup(dumped)


def config_literal(value: object) -> Markup:
    """A JSON value as a literal in a dbt ``config()`` call.

    Used for ``custom_config_json`` values. dbt's Jinja reads Python literal
    syntax: quoted strings with backslash escapes, numbers, ``True`` /
    ``False`` / ``None``, lists and dicts, so ``repr`` of a JSON value is a
    valid literal that parses back to the same value. Marked safe so HTML
    autoescaping (on for templates loaded from strings) leaves it alone.
    """
    return Markup(repr(value))


def build_jinja_environment(loader: BaseLoader | None = None) -> Environment:
    """Build the Jinja2 environment shared by template rendering and validation.

    Uses custom delimiters to avoid conflict with dbt Jinja syntax:
    - [% %] for block statements (instead of {% %})
    - [[ ]] for variable expressions (instead of {{ }})
    - [# #] for comments (instead of {# #})

    Adds the ``yaml_quote``, ``yaml_scalar`` and ``yaml_single_quote`` filters
    for writing user text into YAML, ``quoted_list`` for tag lists,
    ``config_literal`` / ``yaml_json`` for custom config values in SQL / YAML,
    and the ``py``, ``py_dict``,
    ``py_hashed_columns`` and ``py_source_models`` filters for writing Python
    literals into SQLMesh model files.
    """
    environment = Environment(
        loader=loader,
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
        # Custom delimiters to avoid conflict with dbt Jinja
        block_start_string="[%",
        block_end_string="%]",
        variable_start_string="[[",
        variable_end_string="]]",
        comment_start_string="[#",
        comment_end_string="#]",
    )
    environment.filters["yaml_quote"] = yaml_quote
    environment.filters["yaml_scalar"] = yaml_scalar
    environment.filters["yaml_single_quote"] = yaml_single_quote
    environment.filters["quoted_list"] = quoted_list
    environment.filters["config_literal"] = config_literal
    environment.filters["yaml_json"] = yaml_json
    environment.filters["py"] = py_literal
    environment.filters["py_dict"] = py_dict_filter
    environment.filters["py_hashed_columns"] = py_hashed_columns_filter
    environment.filters["py_source_models"] = py_source_models_filter
    return environment


class TemplateResolver:
    """
    Resolves Jinja2 templates for one framework's model generation.

    Templates are resolved with the following priority, each step limited to
    the resolver's framework:
    1. In-memory override for the entity type
    2. Active database template with highest priority
    3. File-based default template

    The "SQL" template of an entity is its model file: SQL for dbt, a Python
    model file for SQLMesh.

    Usage:
        resolver = TemplateResolver()
        sql_template, yaml_template = resolver.get_templates("hub_standard")
        rendered_sql = sql_template.render(hub_name=..., ...)
    """

    def __init__(
        self,
        templates_dir: Path | None = None,
        use_db_templates: bool = True,
        templates_override: dict[str, dict[str, TemplateOverride]] | None = None,
        framework: str = "dbt",
    ) -> None:
        """
        Initialize the template resolver.

        Args:
            templates_dir: Override path to file-based templates directory.
            use_db_templates: Whether to check database for custom templates.
            templates_override: In-memory per-generation template content,
                keyed by ``{framework: {entity_type: TemplateOverride}}``.
                Only the overrides for this resolver's framework are applied;
                overrides for other frameworks are ignored entirely.
            framework: Generation framework ("dbt" or "sqlmesh"). DB-backed
                templates and in-memory overrides are filtered to this
                framework so overrides for one framework never apply to
                another.
        """
        self.templates_dir = templates_dir or TEMPLATES_DIR
        self.use_db_templates = use_db_templates
        self.framework = framework
        # Isolate to this framework's overrides only.
        self._overrides: dict[str, TemplateOverride] = (templates_override or {}).get(
            framework, {}
        )

        # Jinja2 environment for file-based templates and in-memory overrides.
        # File-based defaults live under templates/<framework>/: the model
        # templates' directory (sql/ or models/), yaml/, and project-level files.
        framework_dir = framework_templates_dir(framework, self.templates_dir)
        self._env = build_jinja_environment(
            loader=FileSystemLoader(
                [
                    str(model_templates_dir(framework, self.templates_dir)),
                    str(framework_dir / "yaml"),
                    str(framework_dir),
                ]
            )
        )

        # Template cache for performance
        self._cache: dict[str, tuple[Template | None, Template | None]] = {}

    def get_templates(
        self, entity_type: str
    ) -> tuple[Template | None, Template | None]:
        """
        Get SQL and YAML templates for an entity type.

        Args:
            entity_type: Entity type key (e.g., 'hub_standard', 'satellite_multi_active')

        Returns:
            Tuple of (sql_template, yaml_template). Either may be None if not defined.
        """
        # Check cache first
        if entity_type in self._cache:
            return self._cache[entity_type]

        sql_template: Template | None = None
        yaml_template: Template | None = None

        # Caller-supplied overrides take precedence over DB and file templates
        override = self._overrides.get(entity_type)
        if override is not None:
            if override.sql is not None:
                sql_template = self._env.from_string(override.sql)
            if override.yaml is not None:
                yaml_template = self._env.from_string(override.yaml)

        # Try database templates next
        if self.use_db_templates and (sql_template is None or yaml_template is None):
            db_template = self._get_db_template(entity_type)
            if db_template:
                if sql_template is None and db_template.has_sql_template:
                    sql_template = self._env.from_string(
                        db_template.sql_template_content
                    )
                if yaml_template is None and db_template.has_yaml_template:
                    yaml_template = self._env.from_string(
                        db_template.yaml_template_content
                    )

        # Fall back to file-based templates
        if sql_template is None:
            sql_template = self._get_file_template(entity_type, "sql")
        if yaml_template is None:
            yaml_template = self._get_file_template(entity_type, "yaml")

        # Cache the result
        self._cache[entity_type] = (sql_template, yaml_template)

        return sql_template, yaml_template

    def get_sql_template(self, entity_type: str) -> Template | None:
        """Get only the SQL template for an entity type."""
        sql_template, _ = self.get_templates(entity_type)
        return sql_template

    def get_yaml_template(self, entity_type: str) -> Template | None:
        """Get only the YAML template for an entity type."""
        _, yaml_template = self.get_templates(entity_type)
        return yaml_template

    def get_project_template(self, template_name: str) -> Template | None:
        """
        Get a project-level template (dbt_project.yml, sources.yml, etc.).

        Args:
            template_name: Template filename (e.g., 'dbt_project.yml', 'sources.yml')

        Returns:
            Template or None if not found.
        """
        try:
            return self._env.get_template(f"{template_name}.j2")
        except Exception:
            return None

    def get_available_entity_types(self) -> list[str]:
        """
        Get list of all available entity types.

        Returns:
            List of entity type keys.
        """
        from engine.models.templates import ModelTemplate

        return [choice[0] for choice in ModelTemplate.EntityType.choices]

    def clear_cache(self) -> None:
        """Clear the template cache."""
        self._cache.clear()

    def _get_db_template(self, entity_type: str) -> ModelTemplate | None:
        """
        Get the highest priority active database template for an entity type.

        Args:
            entity_type: Entity type key

        Returns:
            ModelTemplate instance or None if not found.
        """
        from engine.models.templates import ModelTemplate

        return (
            ModelTemplate.objects.filter(
                framework=self.framework,
                entity_type=entity_type,
                is_active=True,
            )
            .order_by("-priority")
            .first()
        )

    def _get_file_template(
        self, entity_type: str, template_type: str
    ) -> Template | None:
        """
        Get a file-based template.

        Args:
            entity_type: Entity type key (e.g., 'hub_standard')
            template_type: 'sql' or 'yaml'

        Returns:
            Template or None if not found.
        """
        # The model template's suffix depends on the framework (.sql.j2 for
        # dbt, .py.j2 for SQLMesh); YAML templates are always .yml.j2.
        if template_type == "yaml":
            filename = f"{entity_type}.yml.j2"
        else:
            filename = f"{entity_type}{model_template_suffix(self.framework)}"

        try:
            return self._env.get_template(filename)
        except Exception:
            # Template file doesn't exist
            return None

    def template_exists(self, entity_type: str) -> bool:
        """
        Check if templates exist for an entity type (either DB or file-based).

        Args:
            entity_type: Entity type key

        Returns:
            True if at least one template (SQL or YAML) exists.
        """
        sql_template, yaml_template = self.get_templates(entity_type)
        return sql_template is not None or yaml_template is not None
