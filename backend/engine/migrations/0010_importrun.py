# Generated for ImportRun audit model.

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('engine', '0009_pit_group'),
    ]

    operations = [
        migrations.CreateModel(
            name='ImportRun',
            fields=[
                ('import_run_id', models.UUIDField(default=uuid.uuid4, editable=False, help_text='Unique identifier of the import run', primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('success', 'Success'), ('partial_success', 'Partial success'), ('failed', 'Failed'), ('validation_failed', 'Validation failed')], help_text='Terminal status of the import', max_length=32)),
                ('is_dry_run', models.BooleanField(default=False, help_text='True if this was a validate-only run with no DB writes')),
                ('source_type', models.CharField(help_text='Source format: excel, sqlite, or json', max_length=16)),
                ('source_name', models.CharField(blank=True, default='', help_text='Original filename or display name of the source', max_length=512)),
                ('conflict_strategy', models.CharField(default='merge', help_text='merge, replace_all, or update_only', max_length=32)),
                ('error_strategy', models.CharField(default='fail_fast', help_text='fail_fast or best_effort', max_length=32)),
                ('report', models.JSONField(default=dict, help_text='Full serialized ImportReport (issues, plan, counts, timings)')),
                ('error_count', models.PositiveIntegerField(default=0)),
                ('warning_count', models.PositiveIntegerField(default=0)),
                ('started_at', models.DateTimeField(help_text='When the import pipeline began')),
                ('finished_at', models.DateTimeField(blank=True, help_text='When the import pipeline terminated', null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('project', models.ForeignKey(help_text='Project this import targeted', on_delete=django.db.models.deletion.CASCADE, related_name='import_runs', to='engine.project')),
            ],
            options={
                'db_table': 'import_run',
                'ordering': ['-started_at'],
                'indexes': [
                    models.Index(fields=['project', '-started_at'], name='import_run_project_cca581_idx'),
                    models.Index(fields=['status'], name='import_run_status_ab697c_idx'),
                ],
            },
        ),
    ]
