"""
Django management command to import metadata from an Excel file.
"""
import os
from django.core.management.base import BaseCommand, CommandError
from engine.services.excel_import import ExcelImportService

class Command(BaseCommand):
    help = "Imports metadata from a legacy TurboVault Excel file into the domain model."

    def add_arguments(self, parser):
        parser.add_argument(
            "excel_path", 
            type=str, 
            help="Path to the Excel file to import"
        )
        parser.add_argument(
            "--project-name", 
            type=str, 
            default="Imported Project",
            help="Name of the project to create"
        )
        parser.add_argument(
            "--description", 
            type=str, 
            help="Optional project description"
        )

    def handle(self, *args, **options):
        excel_path = options["excel_path"]
        project_name = options["project_name"]
        description = options["description"]

        if not os.path.exists(excel_path):
            raise CommandError(f"Excel file not found at: {excel_path}")

        self.stdout.write(self.style.NOTICE(f"Importing metadata from {excel_path}..."))

        try:
            service = ExcelImportService(excel_path)
            project = service.import_metadata(project_name, description)
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully imported metadata into project '{project.name}' (ID: {project.project_id})"
                )
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Import failed: {str(e)}"))
            # Re-raise to show stack trace in dev if needed
            raise e
