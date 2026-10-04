"""Turn the old Record Source fallbacks into fixed text.

Imports used to give a table without a Record Source its Source System's name
(and the MCP tool ``<system>.<table>``) without the leading ``!``.
datavault4dbt reads such a value as a column name, so the stage looked for a
column the source doesn't have and failed. A value that is exactly one of those
fallbacks, and isn't a column of the table, gets its ``!``.
"""

from django.db import migrations


def _old_fallbacks(table) -> set[str]:
    system = table.source_system
    return {
        system.name,
        system.schema_name,
        f"{system.name}.{table.physical_table_name}",
    }


def prefix_fallbacks(apps, schema_editor) -> None:
    SourceTable = apps.get_model("engine", "SourceTable")
    tables = SourceTable.objects.select_related("source_system").prefetch_related(
        "columns"
    )
    for table in tables.iterator(chunk_size=500):
        value = table.record_source_value
        if not value or value not in _old_fallbacks(table):
            continue
        columns = {
            column.source_column_physical_name.lower() for column in table.columns.all()
        }
        if value.lower() in columns:
            continue
        table.record_source_value = f"!{value}"
        table.save(update_fields=["record_source_value"])


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0015_descriptions_and_derived_columns"),
    ]

    operations = [
        # Nothing to undo: a value with its ``!`` is what the user meant.
        migrations.RunPython(prefix_fallbacks, migrations.RunPython.noop),
    ]
