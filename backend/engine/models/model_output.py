"""
Model outputs: how an entity's dbt models are generated.

Every entity becomes one or more dbt models: a source table its stage, a
satellite its v0 table and v1 view, a hub its hub model and possibly an
effectivity and a record-tracking satellite, and so on. A ``ModelOutput``
stores what differs from TurboVault's defaults for one of these models: its
name, the folder it is written to, and the settings of its ``config()``
block. An imported dbt project keeps its models' names, folders and settings
this way. Without a row, or with empty fields, a model is generated as
TurboVault derives it.
"""

from __future__ import annotations

import re
import uuid
from pathlib import PurePosixPath
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from engine.models.project import Project

# The entity field each kind of model belongs to.
ENTITY_FIELDS = (
    "source_table",
    "hub",
    "link",
    "satellite",
    "pit",
    "reference_table",
    "snapshot_control",
)

# A model name is a file name: no path separators, no leading dot, no
# whitespace or control characters.
_MODEL_NAME = re.compile(r"[^/\\\s.][^/\\\s]*")

# config() keys with a field of their own.
_FIELD_CONFIG_KEYS = {
    "materialized": "materialized",
    "alias": "alias",
    "schema": "schema_name",
    "database": "database_name",
    "tags": "tags",
}


def model_name_error(name: str) -> str | None:
    """Why *name* can't be a model's name, or None when it can."""
    if not _MODEL_NAME.fullmatch(name) or "\x00" in name:
        return (
            f"'{name}' can't name a dbt model: use letters, digits and "
            "underscores, without spaces, dots or slashes"
        )
    return None


def normalize_folder(folder: str) -> str:
    """A folder relative to the dbt project: forward slashes, no outer slashes."""
    return folder.strip().replace("\\", "/").strip("/")


def folder_error(folder: str) -> str | None:
    """Why *folder* can't hold a model, or None when it can.

    The folder is relative to the dbt project. It must stay inside it: no
    absolute paths, drive letters or ``..`` segments.
    """
    if not folder:
        return None
    raw = folder.strip()
    if raw.startswith(("/", "\\", "~")) or re.match(r"[A-Za-z]:", raw):
        return f"Folder '{folder}' must be relative to the dbt project"
    parts = PurePosixPath(normalize_folder(raw)).parts
    if any(part in ("..", ".") for part in parts) or "\x00" in raw:
        return f"Folder '{folder}' must stay inside the dbt project (no '..' or '.')"
    return None


class ModelOutput(models.Model):
    """How one dbt model of an entity is generated.

    Exactly one entity field is set; ``kind`` says which of the entity's
    models this is. Empty fields keep TurboVault's defaults.
    """

    class Kind(models.TextChoices):
        STAGE = "stage", "Stage"
        PRESTAGE = "prestage", "Pre-stage"
        HUB = "hub", "Hub"
        LINK = "link", "Link"
        SATELLITE_V0 = "satellite_v0", "Satellite (v0)"
        SATELLITE_V1 = "satellite_v1", "Satellite (v1 view)"
        EFFECTIVITY_SATELLITE = "effectivity_satellite", "Effectivity satellite"
        RECORD_TRACKING_SATELLITE = (
            "record_tracking_satellite",
            "Record-tracking satellite",
        )
        PIT = "pit", "PIT"
        REFERENCE_TABLE = "reference_table", "Reference table"
        SNAPSHOT_CONTROL_V0 = "snapshot_control_v0", "Snapshot control table (v0)"
        SNAPSHOT_CONTROL_V1 = "snapshot_control_v1", "Snapshot control logic (v1)"

    # The entities each kind of model can belong to.
    KIND_ENTITIES: dict[str, tuple[str, ...]] = {
        Kind.STAGE: ("source_table",),
        Kind.PRESTAGE: ("source_table",),
        Kind.HUB: ("hub",),
        Kind.LINK: ("link",),
        Kind.SATELLITE_V0: ("satellite",),
        Kind.SATELLITE_V1: ("satellite",),
        Kind.EFFECTIVITY_SATELLITE: ("hub", "link"),
        Kind.RECORD_TRACKING_SATELLITE: ("hub", "link"),
        Kind.PIT: ("pit",),
        Kind.REFERENCE_TABLE: ("reference_table",),
        Kind.SNAPSHOT_CONTROL_V0: ("snapshot_control",),
        Kind.SNAPSHOT_CONTROL_V1: ("snapshot_control",),
    }

    # Kinds named after their entity's physical name: no model_name of their own.
    NAMED_BY_ENTITY = frozenset({Kind.HUB, Kind.LINK, Kind.PIT, Kind.REFERENCE_TABLE})

    model_output_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier of the model output",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="model_outputs",
        help_text="Project this model belongs to (set from its entity)",
    )

    kind = models.CharField(
        max_length=40,
        choices=Kind.choices,
        help_text="Which of the entity's dbt models this is",
    )

    source_table = models.ForeignKey(
        "engine.SourceTable",
        on_delete=models.CASCADE,
        related_name="model_outputs",
        null=True,
        blank=True,
        help_text="Source table of a stage or pre-stage model",
    )
    hub = models.ForeignKey(
        "engine.Hub",
        on_delete=models.CASCADE,
        related_name="model_outputs",
        null=True,
        blank=True,
        help_text="Hub of a hub, effectivity or record-tracking satellite model",
    )
    link = models.ForeignKey(
        "engine.Link",
        on_delete=models.CASCADE,
        related_name="model_outputs",
        null=True,
        blank=True,
        help_text="Link of a link, effectivity or record-tracking satellite model",
    )
    satellite = models.ForeignKey(
        "engine.Satellite",
        on_delete=models.CASCADE,
        related_name="model_outputs",
        null=True,
        blank=True,
        help_text="Satellite of a v0 or v1 model",
    )
    pit = models.ForeignKey(
        "engine.PIT",
        on_delete=models.CASCADE,
        related_name="model_outputs",
        null=True,
        blank=True,
        help_text="PIT of a PIT model",
    )
    reference_table = models.ForeignKey(
        "engine.ReferenceTable",
        on_delete=models.CASCADE,
        related_name="model_outputs",
        null=True,
        blank=True,
        help_text="Reference table of a reference table model",
    )
    snapshot_control = models.ForeignKey(
        "engine.SnapshotControlTable",
        on_delete=models.CASCADE,
        related_name="model_outputs",
        null=True,
        blank=True,
        help_text="Snapshot control of a v0 or v1 model",
    )

    model_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=(
            "Name of the dbt model (and its file). Empty: derived from the "
            "project's naming patterns. Hubs, links, PITs and reference tables "
            "are named by their physical name instead"
        ),
    )
    folder = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text=(
            "Folder of the model's files, relative to the dbt project (e.g. "
            "models/raw_vault/hubs). Empty: TurboVault's layer folder"
        ),
    )
    alias = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="config(alias=...): the relation name in the warehouse",
    )
    schema_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="config(schema=...): the model's custom schema",
    )
    database_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="config(database=...)",
    )
    materialized = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="config(materialized=...). Empty: the layer's materialization",
    )
    tags = models.JSONField(
        blank=True,
        null=True,
        help_text=(
            "The model's own tags, added to TurboVault's default tags (which the "
            "project setting add_default_tags turns off)"
        ),
    )
    config = models.JSONField(
        blank=True,
        null=True,
        help_text=(
            "Further config() keys, written as they are (e.g. unique_key, "
            "post_hook, on_schema_change)"
        ),
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the model output was created"
    )
    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the model output was last updated"
    )

    class Meta:
        db_table = "model_output"
        verbose_name = "Model Output"
        verbose_name_plural = "Model Outputs"
        ordering = ["kind", "model_name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    *[
                        Q(
                            **{f"{field}__isnull": False},
                            **{
                                f"{other}__isnull": True
                                for other in ENTITY_FIELDS
                                if other != field
                            },
                        )
                        for field in ENTITY_FIELDS
                    ],
                    _connector=Q.OR,
                ),
                name="model_output_one_entity",
            ),
            *[
                models.UniqueConstraint(
                    fields=[field, "kind"], name=f"model_output_unique_{field}_kind"
                )
                for field in ENTITY_FIELDS
            ],
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.model_name or self.entity}"

    @property
    def entity_field(self) -> str | None:
        """Name of the entity field that is set."""
        set_fields = [f for f in ENTITY_FIELDS if getattr(self, f"{f}_id") is not None]
        return set_fields[0] if len(set_fields) == 1 else None

    @property
    def entity(self) -> Any:
        """The entity this model belongs to."""
        field = self.entity_field
        return getattr(self, field) if field else None

    def settings(self) -> dict[str, Any]:
        """The stored config() settings, without empty values."""
        values = {
            "materialized": self.materialized,
            "alias": self.alias,
            "schema": self.schema_name,
            "database": self.database_name,
        }
        settings: dict[str, Any] = {k: v for k, v in values.items() if v}
        if self.tags:
            settings["tags"] = list(self.tags)
        settings.update(self.config or {})
        return settings

    def clean(self) -> None:
        """Check the entity, the kind and every value."""
        super().clean()
        errors: dict[str, list[str]] = {}

        set_fields = [f for f in ENTITY_FIELDS if getattr(self, f"{f}_id") is not None]
        if len(set_fields) != 1:
            raise ValidationError(
                "Set exactly one of: " + ", ".join(ENTITY_FIELDS) + "."
            )
        field = set_fields[0]
        allowed = self.KIND_ENTITIES.get(self.kind, ())
        if field not in allowed:
            errors.setdefault("kind", []).append(
                f"A {self.get_kind_display()} model belongs to a "
                f"{' or '.join(a.replace('_', ' ') for a in allowed) or 'nothing'}, "
                f"not a {field.replace('_', ' ')}."
            )

        if self.model_name:
            if self.kind in self.NAMED_BY_ENTITY:
                errors.setdefault("model_name", []).append(
                    f"A {self.get_kind_display()} model is named by its physical "
                    "name: rename the entity instead."
                )
            elif error := model_name_error(self.model_name):
                errors.setdefault("model_name", []).append(error)

        if self.kind == self.Kind.PRESTAGE and any(
            (
                self.folder,
                self.alias,
                self.schema_name,
                self.database_name,
                self.materialized,
                self.tags,
                self.config,
            )
        ):
            errors.setdefault("kind", []).append(
                "A pre-stage's model belongs to the dbt project: only its name "
                "is stored."
            )

        if self.folder and (error := folder_error(self.folder)):
            errors.setdefault("folder", []).append(error)

        if self.tags is not None and (
            not isinstance(self.tags, list)
            or not all(isinstance(tag, str) for tag in self.tags)
        ):
            errors.setdefault("tags", []).append("Tags are a list of strings.")

        if self.config is not None:
            if not isinstance(self.config, dict) or not all(
                isinstance(key, str) for key in self.config
            ):
                errors.setdefault("config", []).append(
                    "Config is a mapping of config() keys to values."
                )
            else:
                for key in self.config:
                    if key in _FIELD_CONFIG_KEYS:
                        errors.setdefault("config", []).append(
                            f"Set '{key}' in its own field "
                            f"({_FIELD_CONFIG_KEYS[key]}), not in config."
                        )

        if self.model_name and not errors.get("model_name"):
            project = self.project if self.project_id else self._entity_project()
            duplicate = (
                ModelOutput.objects.filter(project=project, model_name=self.model_name)
                .exclude(pk=self.pk)
                .exists()
            )
            if duplicate:
                errors.setdefault("model_name", []).append(
                    f"Another model of the project is named '{self.model_name}'."
                )

        if errors:
            raise ValidationError(errors)

    def _entity_project(self) -> Project | None:
        entity = self.entity
        return getattr(entity, "project", None) if entity is not None else None

    def save(self, *args, **kwargs) -> None:
        """Take the project from the entity, and store the folder normalized."""
        if not self.project_id:
            project = self._entity_project()
            if project is not None:
                self.project = project
        if self.folder:
            self.folder = normalize_folder(self.folder) or None
        super().save(*args, **kwargs)
