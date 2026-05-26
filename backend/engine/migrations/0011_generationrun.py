# Generated for GenerationRun audit model.

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('engine', '0010_importrun'),
    ]

    operations = [
        migrations.CreateModel(
            name='GenerationRun',
            fields=[
                ('generation_run_id', models.UUIDField(default=uuid.uuid4, editable=False, help_text='Unique identifier of the generation run', primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('success', 'Success'), ('partial_success', 'Partial success'), ('failed', 'Failed'), ('validation_failed', 'Validation failed')], help_text='Terminal status of the generation', max_length=32)),
                ('is_dry_run', models.BooleanField(default=False, help_text='True if no files were written to disk')),
                ('output_type', models.CharField(help_text='Output format: dbt, json, or dbml', max_length=16)),
                ('output_path', models.CharField(blank=True, default='', help_text='Destination path requested by the caller (empty for dry-run / preview)', max_length=512)),
                ('error_strategy', models.CharField(default='best_effort', help_text='fail_fast or best_effort', max_length=32)),
                ('report', models.JSONField(default=dict, help_text='Full serialized GenerationReport (plan, artifacts, issues, timings)')),
                ('error_count', models.PositiveIntegerField(default=0)),
                ('warning_count', models.PositiveIntegerField(default=0)),
                ('files_generated', models.PositiveIntegerField(default=0)),
                ('started_at', models.DateTimeField(help_text='When the generation pipeline began')),
                ('finished_at', models.DateTimeField(blank=True, help_text='When the generation pipeline terminated', null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('project', models.ForeignKey(help_text='Project this generation targeted', on_delete=django.db.models.deletion.CASCADE, related_name='generation_runs', to='engine.project')),
            ],
            options={
                'db_table': 'generation_run',
                'ordering': ['-started_at'],
                'indexes': [
                    models.Index(fields=['project', '-started_at'], name='generation__project_247baa_idx'),
                    models.Index(fields=['status'], name='generation__status_d7f42c_idx'),
                    models.Index(fields=['output_type'], name='generation__output__85b070_idx'),
                ],
            },
        ),
    ]
