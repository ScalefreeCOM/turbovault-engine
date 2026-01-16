# Generated migration to make record_source_value and load_date_value required

from django.db import migrations, models


def set_default_values(apps, schema_editor):
    """
    Set default values for any existing NULL record_source_value or load_date_value.
    This ensures the migration can proceed without errors for existing data.
    """
    SourceTable = apps.get_model("engine", "SourceTable")

    # Update any NULL record_source_value
    SourceTable.objects.filter(record_source_value__isnull=True).update(
        record_source_value="UNKNOWN_SOURCE"
    )

    # Update any NULL load_date_value
    SourceTable.objects.filter(load_date_value__isnull=True).update(
        load_date_value="CURRENT_TIMESTAMP"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0027_link_group_link_link_hashkey_name_and_more"),
    ]

    operations = [
        # First, set default values for any existing NULL values
        migrations.RunPython(
            set_default_values, reverse_code=migrations.RunPython.noop
        ),
        # Then alter the fields to be required
        migrations.AlterField(
            model_name="sourcetable",
            name="record_source_value",
            field=models.CharField(
                help_text="Value/expression used as record_source for this table",
                max_length=500,
            ),
        ),
        migrations.AlterField(
            model_name="sourcetable",
            name="load_date_value",
            field=models.CharField(
                help_text="Expression or column name used as load date value",
                max_length=500,
            ),
        ),
    ]
