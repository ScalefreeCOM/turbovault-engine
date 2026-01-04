"""
Django management command to populate database with template files.

Reads all SQL and YAML templates from the templates directory and creates
ModelTemplate records in the database for each one.
"""

from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from engine.models.templates import ModelTemplate, TemplateCategory
from engine.services.generation.template_resolver import TEMPLATES_DIR


class Command(BaseCommand):
    help = "Populates database with SQL and YAML templates from file system"

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing templates with same entity_type and name",
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

        sql_templates_dir = TEMPLATES_DIR / "sql"
        yaml_templates_dir = TEMPLATES_DIR / "yaml"

        created_count = 0
        updated_count = 0
        skipped_count = 0

        with transaction.atomic():
            # Process SQL templates
            if sql_templates_dir.exists():
                for sql_file in sql_templates_dir.glob("*.sql.j2"):
                    entity_type = sql_file.stem.removesuffix(".sql")
                    result = self._process_template_file(
                        sql_file, entity_type, category, overwrite, "sql"
                    )
                    if result == "created":
                        created_count += 1
                    elif result == "updated":
                        updated_count += 1
                    else:
                        skipped_count += 1

            # Process YAML templates
            if yaml_templates_dir.exists():
                for yaml_file in yaml_templates_dir.glob("*.yml.j2"):
                    entity_type = yaml_file.stem.removesuffix(".yml")

                    # Skip project-level files
                    if entity_type in ["dbt_project", "packages", "sources"]:
                        continue

                    result = self._process_template_file(
                        yaml_file, entity_type, category, overwrite, "yaml"
                    )
                    if result == "created":
                        created_count += 1
                    elif result == "updated":
                        updated_count += 1
                    else:
                        skipped_count += 1

        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\nTemplate population complete:"
                f"\n  Created: {created_count}"
                f"\n  Updated: {updated_count}"
                f"\n  Skipped: {skipped_count}"
            )
        )

    def _process_template_file(
        self,
        file_path: Path,
        entity_type: str,
        category: TemplateCategory,
        overwrite: bool,
        template_type: str,  # 'sql' or 'yaml'
    ) -> str:
        """
        Process a single template file.

        Returns:
            "created", "updated", or "skipped"
        """
        # Validate entity type
        valid_types = [choice[0] for choice in ModelTemplate.EntityType.choices]
        if entity_type not in valid_types:
            self.stdout.write(
                self.style.WARNING(
                    f"Unknown entity type '{entity_type}' for {file_path.name}, skipping"
                )
            )
            return "skipped"

        # Read template content
        content = file_path.read_text(encoding="utf-8")

        # Template name based on entity type and template type
        template_name = f"{entity_type} ({template_type.upper()})"

        # Check if template exists
        existing = ModelTemplate.objects.filter(
            entity_type=entity_type, name=template_name
        ).first()

        if existing:
            if overwrite:
                # Update existing template
                if template_type == "sql":
                    existing.sql_template_content = content
                else:
                    existing.yaml_template_content = content
                existing.category = category
                existing.save()

                self.stdout.write(self.style.WARNING(f"Updated: {template_name}"))
                return "updated"
            else:
                self.stdout.write(
                    self.style.NOTICE(
                        f"Skipped: {template_name} (already exists, use --overwrite to update)"
                    )
                )
                return "skipped"
        else:
            # Create new template
            kwargs = {
                "name": template_name,
                "entity_type": entity_type,
                "category": category,
                "description": f"Default {template_type.upper()} template for {entity_type}",
                "priority": 0,  # Default priority
                "is_active": True,
            }

            if template_type == "sql":
                kwargs["sql_template_content"] = content
            else:
                kwargs["yaml_template_content"] = content

            ModelTemplate.objects.create(**kwargs)

            self.stdout.write(self.style.SUCCESS(f"Created: {template_name}"))
            return "created"
