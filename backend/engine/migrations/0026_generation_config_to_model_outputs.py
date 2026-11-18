"""Move the entities' ``generation_config`` onto ``ModelOutput`` rows.

Migration 0019 stored each entity's output attributes (#442) in a JSON field,
``{"dbt": {output kind: attributes}}``. The project now keeps them as one
``model_output`` row per model, which the dbt import also writes. Each stored
output kind becomes a row (framework ``dbt``):

- ``file_path`` (relative to ``models/``) gives the folder; its file name is
  the model's name unless ``model_name`` says so already;
- ``schema`` / ``database`` / ``custom_config_json`` become ``schema_name`` /
  ``database_name`` / ``config``; the other attributes keep their names.

Hubs, links, PITs and reference tables are named after their entity, and a
pre-stage's model belongs to the dbt project (only its name is kept): values
the rows can't hold are logged, not stored. A model that already has a row
keeps it. The fields are dropped afterwards.
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import Any

from django.db import migrations

logger = logging.getLogger(__name__)

# (model, ModelOutput foreign key, the entity's own name field or None)
ENTITIES = (
    ("SourceTable", "source_table", None),
    ("Hub", "hub", "hub_physical_name"),
    ("Link", "link", "link_physical_name"),
    ("Satellite", "satellite", None),
    ("PIT", "pit", "pit_physical_name"),
    ("ReferenceTable", "reference_table", "reference_table_physical_name"),
    ("SnapshotControlTable", "snapshot_control", None),
)

# Kinds named after their entity: no model name of their own.
NAMED_BY_ENTITY = frozenset({"hub", "link", "pit", "reference_table"})

# config() keys hooks take in a config() call.
HOOK_KEYS = {"pre-hook": "pre_hook", "post-hook": "post_hook"}


def _values(kind: str, attributes: dict[str, Any]) -> dict[str, Any]:
    """The row values of one output kind's attributes."""
    model_name = attributes.get("model_name") or None
    folder = None
    file_path = attributes.get("file_path")
    if file_path:
        path = PurePosixPath(file_path)
        folder = "models" if str(path.parent) == "." else f"models/{path.parent}"
        model_name = model_name or path.name.removesuffix(".sql")
    config = {
        HOOK_KEYS.get(key, key): value
        for key, value in (attributes.get("custom_config_json") or {}).items()
    }
    return {
        "model_name": model_name,
        "folder": folder,
        "alias": attributes.get("alias") or None,
        "schema_name": attributes.get("schema") or None,
        "database_name": attributes.get("database") or None,
        "materialized": attributes.get("materialized") or None,
        "tags": (
            list(attributes["tags"]) if attributes.get("tags") is not None else None
        ),
        "config": config or None,
    }


def move_generation_config(apps: Any, schema_editor: Any) -> None:
    ModelOutput = apps.get_model("engine", "ModelOutput")
    moved = 0
    for model_name, entity_field, name_field in ENTITIES:
        model = apps.get_model("engine", model_name)
        for entity in model.objects.all():
            by_kind = (entity.generation_config or {}).get("dbt") or {}
            for kind, attributes in by_kind.items():
                if not attributes:
                    continue
                exists = ModelOutput.objects.filter(
                    **{entity_field: entity}, framework="dbt", kind=kind
                ).exists()
                if exists:
                    logger.info(
                        "%s %s: keeping its stored %s model output",
                        model_name,
                        entity.pk,
                        kind,
                    )
                    continue
                values = _values(kind, attributes)
                if kind in NAMED_BY_ENTITY and values["model_name"]:
                    own = getattr(entity, name_field)
                    if values["model_name"] != own:
                        logger.warning(
                            "%s '%s': model name '%s' not kept (the model is "
                            "named after the entity)",
                            model_name,
                            own,
                            values["model_name"],
                        )
                    values["model_name"] = None
                if kind == "prestage":
                    dropped = [k for k, v in values.items() if v and k != "model_name"]
                    if dropped:
                        logger.warning(
                            "Pre-stage of source table %s: %s not kept (its model "
                            "belongs to the dbt project)",
                            entity.pk,
                            ", ".join(dropped),
                        )
                    values = {"model_name": values["model_name"]}
                if not any(value is not None for value in values.values()):
                    continue
                ModelOutput.objects.create(
                    project_id=entity.project_id,
                    framework="dbt",
                    kind=kind,
                    **{entity_field: entity},
                    **values,
                )
                moved += 1
    if moved:
        logger.info("Moved %d stored output attribute(s) to model outputs", moved)


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0025_hub_link_pit_snapshot_options"),
    ]

    operations = [
        migrations.RunPython(
            move_generation_config, reverse_code=migrations.RunPython.noop
        ),
        migrations.RemoveField(model_name="sourcetable", name="generation_config"),
        migrations.RemoveField(model_name="hub", name="generation_config"),
        migrations.RemoveField(model_name="link", name="generation_config"),
        migrations.RemoveField(model_name="satellite", name="generation_config"),
        migrations.RemoveField(model_name="pit", name="generation_config"),
        migrations.RemoveField(model_name="referencetable", name="generation_config"),
        migrations.RemoveField(
            model_name="snapshotcontroltable", name="generation_config"
        ),
    ]
