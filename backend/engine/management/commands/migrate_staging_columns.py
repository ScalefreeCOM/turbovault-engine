from django.core.management.base import BaseCommand

from engine.models.hubs import HubSourceMapping
from engine.models.links import LinkHubSourceMapping, LinkSourceMapping
from engine.models.satellites import SatelliteColumn
from engine.services.staging_service import get_or_create_staging_column


class Command(BaseCommand):
    help = "Populates the staging_column field for all metadata mapping records."

    def handle(self, *args, **options):
        # 1. LinkHubSourceMapping (in case any were missed or new ones created)
        self.migrate_fk_model(
            LinkHubSourceMapping,
            "staging_column",
            ["source_column", "prejoin_extraction_column"],
        )

        # 2. HubSourceMapping
        self.migrate_fk_model(HubSourceMapping, "staging_column", ["source_column"])

        # 3. SatelliteColumn
        self.migrate_fk_model(SatelliteColumn, "staging_column", ["source_column"])

        # 4. LinkSourceMapping
        self.migrate_fk_model(LinkSourceMapping, "staging_column", ["source_column"])

    def migrate_fk_model(self, model_class, staging_field_name, legacy_field_names):
        self.stdout.write(f"Migrating {model_class.__name__}...")
        mappings = model_class.objects.filter(**{f"{staging_field_name}__isnull": True})
        count = 0

        for mapping in mappings:
            legacy_col = None
            for field_name in legacy_field_names:
                if hasattr(mapping, field_name) and getattr(mapping, field_name):
                    legacy_col = getattr(mapping, field_name)
                    break

            if legacy_col:
                setattr(
                    mapping,
                    staging_field_name,
                    get_or_create_staging_column(legacy_col),
                )
                mapping.save()
                count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully migrated {count} {model_class.__name__} records."
            )
        )
