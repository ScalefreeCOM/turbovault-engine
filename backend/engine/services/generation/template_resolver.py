"""
Template resolver for dbt project generation.

Resolves Jinja2 templates from:
1. Database (ModelTemplate model) - for customization via Django Admin
2. File-based defaults - bundled with the package

Database templates take precedence over file-based templates.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape

if TYPE_CHECKING:
    from engine.models.templates import ModelTemplate


# Path to default file-based templates
TEMPLATES_DIR = Path(__file__).parent / "templates"


class TemplateResolver:
    """
    Resolves Jinja2 templates for dbt model generation.
    
    Templates are resolved with the following priority:
    1. Active database template with highest priority
    2. File-based default template
    
    Usage:
        resolver = TemplateResolver()
        sql_template, yaml_template = resolver.get_templates("hub_standard")
        rendered_sql = sql_template.render(hub_name=..., ...)
    """
    
    def __init__(
        self,
        templates_dir: Path | None = None,
        use_db_templates: bool = True
    ) -> None:
        """
        Initialize the template resolver.
        
        Args:
            templates_dir: Override path to file-based templates directory.
            use_db_templates: Whether to check database for custom templates.
        """
        self.templates_dir = templates_dir or TEMPLATES_DIR
        self.use_db_templates = use_db_templates
        
        # Initialize Jinja2 environment for file-based templates
        # Uses custom delimiters to avoid conflict with dbt Jinja syntax:
        # - [% %] for block statements (instead of {% %})
        # - [[ ]] for variable expressions (instead of {{ }})
        # - [# #] for comments (instead of {# #})
        self._env = Environment(
            loader=FileSystemLoader([
                str(self.templates_dir / "sql"),
                str(self.templates_dir / "yaml"),
                str(self.templates_dir),
            ]),
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
        
        # Template cache for performance
        self._cache: dict[str, tuple[Template | None, Template | None]] = {}
    
    def get_templates(
        self,
        entity_type: str
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
        
        # Try database templates first
        if self.use_db_templates:
            db_template = self._get_db_template(entity_type)
            if db_template:
                if db_template.has_sql_template:
                    sql_template = self._env.from_string(db_template.sql_template_content)
                if db_template.has_yaml_template:
                    yaml_template = self._env.from_string(db_template.yaml_template_content)
        
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
            ModelTemplate.objects
            .filter(entity_type=entity_type, is_active=True)
            .order_by("-priority")
            .first()
        )
    
    def _get_file_template(
        self,
        entity_type: str,
        template_type: str
    ) -> Template | None:
        """
        Get a file-based template.
        
        Args:
            entity_type: Entity type key (e.g., 'hub_standard')
            template_type: 'sql' or 'yaml'
        
        Returns:
            Template or None if not found.
        """
        # Map template_type to file extension
        # Use .yml for YAML files (shorter, more common in dbt)
        ext = "yml" if template_type == "yaml" else template_type
        filename = f"{entity_type}.{ext}.j2"
        
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
