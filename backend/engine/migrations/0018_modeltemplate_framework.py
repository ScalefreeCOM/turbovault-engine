from django.db import migrations, models


class Migration(migrations.Migration):
    """Add framework dimension to ModelTemplate.

    All existing templates are dbt templates (the only framework supported
    before this migration), so the default 'dbt' is applied to every row.
    """

    dependencies = [
        ("engine", "0017_source_value_inheritance"),
    ]

    operations = [
        migrations.AddField(
            model_name="modeltemplate",
            name="framework",
            field=models.CharField(
                choices=[("dbt", "dbt"), ("sqlmesh", "SQLMesh")],
                default="dbt",
                help_text="Generation framework this template applies to (dbt or sqlmesh)",
                max_length=20,
            ),
        ),
        migrations.AlterUniqueTogether(
            name="modeltemplate",
            unique_together={("framework", "entity_type", "name")},
        ),
    ]
