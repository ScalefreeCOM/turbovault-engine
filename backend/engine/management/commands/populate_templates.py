"""
Django management command to populate database with template files.

Reads the bundled per-entity templates of every framework — dbt SQL and YAML
from templates/dbt/, SQLMesh Python models from templates/sqlmesh/models/ —
and creates a ModelTemplate record for each one, tagged with its framework.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from engine.models.templates import ModelTemplate, TemplateCategory
from engine.services.generation.template_resolver import (
    BundledTemplate,
    bundled_templates,
)


class Command(BaseCommand):
    help = "Populates database with the bundled dbt and SQLMesh templates"

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing templates with same framework, entity_type and name",
        )
        parser.add_argument(
            "--category",
            type=str,
            default="File-based Defaults",
            help="Category name for the templates (default: 'File-based Defaults')",
        )

    def handle(self, *args, **options):
        overwrite = options["overwrite"]
        category_name = options["category"]

        self.stdout.write(self.style.NOTICE("Populating templates from file system..."))

        # Get or create category
        category, created = TemplateCategory.objects.get_or_create(
            name=category_name,
            defaults={"description": "Default templates from file system"},
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created category: {category_name}"))

        counts = {"created": 0, "updated": 0, "skipped": 0}

        with transaction.atomic():
            for framework in ModelTemplate.Framework.values:
                for template in bundled_templates(framework):
                    result = self._process_template_file(template, category, overwrite)
                    counts[result] += 1

        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\nTemplate population complete:"
                f"\n  Created: {counts['created']}"
                f"\n  Updated: {counts['updated']}"
                f"\n  Skipped: {counts['skipped']}"
            )
        )

    def _process_template_file(
        self,
        template: BundledTemplate,
        category: TemplateCategory,
        overwrite: bool,
    ) -> str:
        """
        Create or update the ModelTemplate for one bundled template file.

        Returns:
            "created", "updated", or "skipped"
        """
        entity_type = template.entity_type
        valid_types = [choice[0] for choice in ModelTemplate.EntityType.choices]
        if entity_type not in valid_types:
            self.stdout.write(
                self.style.WARNING(
                    f"Unknown entity type '{entity_type}' for {template.path.name}, skipping"
                )
            )
            return "skipped"

        content = template.path.read_text(encoding="utf-8")
        template_name = f"{entity_type} ({template.label})"
        content_field = (
            "yaml_template_content" if template.template_type == "yaml" else "sql_template_content"
        )

        # Scoped to the framework so a same-named template of another
        # framework is never overwritten.
        existing = ModelTemplate.objects.filter(
            framework=template.framework, entity_type=entity_type, name=template_name
        ).first()

        if existing:
            if not overwrite:
                self.stdout.write(
                    self.style.NOTICE(
                        f"Skipped: {template.framework} {template_name} "
                        "(already exists, use --overwrite to update)"
                    )
                )
                return "skipped"
            setattr(existing, content_field, content)
            existing.category = category
            existing.save()
            self.stdout.write(
                self.style.WARNING(f"Updated: {template.framework} {template_name}")
            )
            return "updated"

        ModelTemplate.objects.create(
            name=template_name,
            entity_type=entity_type,
            framework=template.framework,
            category=category,
            description=(
                f"Default {template.framework} {template.label} template for {entity_type}"
            ),
            priority=0,
            is_active=True,
            **{content_field: content},
        )
        self.stdout.write(self.style.SUCCESS(f"Created: {template.framework} {template_name}"))
        return "created"
