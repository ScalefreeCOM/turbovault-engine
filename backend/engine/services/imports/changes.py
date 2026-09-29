"""
Change-aware writes for the executor.

The executor writes every row through these helpers instead of
``update_or_create``. They compare what the project has with what the source
says, write only the fields that differ, and record each difference as an
``EntityChange`` on the plan entity being applied. A row that already
matches costs no write at all, so re-importing the same source leaves the
project (and its ``updated_at`` stamps) untouched and every entity is
reported as ``unchanged``.

Because the same code runs for a dry run (inside a transaction that is rolled
back), the changes a dry run reports are exactly the ones the import makes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import models

from engine.services.imports.types import ChangeKind, EntityChange

# `existing=LOOKUP` asks `upsert` to find the row itself.
LOOKUP: Any = object()


@dataclass(slots=True)
class OpOutcome:
    """What applying one plan entity did."""

    # The entity's own row exists after the handler ran (found or inserted).
    touched: bool = False
    # The entity's own row was inserted by this op.
    created: bool = False
    changes: list[EntityChange] = field(default_factory=list)
    # Codes of the errors recorded while applying it.
    error_codes: list[str] = field(default_factory=list)
    # Set when the entity could not be written at all; the skip reason.
    failed: str | None = None

    def record(
        self,
        path: tuple[str, ...],
        *,
        kind: ChangeKind,
        before: Any = None,
        after: Any = None,
    ) -> EntityChange | None:
        """Note a change, unless the entity itself is new.

        A new entity is reported as created; listing every column and mapping
        it was created with would only repeat the source.
        """
        if self.created:
            return None
        change = EntityChange(
            field=".".join(path),
            path=list(path),
            kind=kind,
            before=before,
            after=after,
        )
        self.changes.append(change)
        return change


# ---------------------------------------------------------------------------
# Display values
# ---------------------------------------------------------------------------

# The attribute that names a row of each model, for change values: a group
# change reads "sales → finance", not two UUIDs.
_LABEL_ATTRS: dict[str, str] = {
    "Group": "group_name",
    "Hub": "hub_physical_name",
    "Link": "link_physical_name",
    "Satellite": "satellite_physical_name",
    "SourceSystem": "name",
    "SourceTable": "physical_table_name",
    "SourceColumn": "source_column_physical_name",
    "SnapshotControlTable": "name",
    "SnapshotControlLogic": "snapshot_control_logic_column_name",
}


def display(value: Any) -> Any:
    """A JSON-native form of a field value for the report."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, models.Model):
        attr = _LABEL_ATTRS.get(type(value).__name__)
        return getattr(value, attr) if attr else str(value.pk)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal | UUID):
        return str(value)
    return str(value)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _same(model_field: models.Field, current: Any, new: Any) -> bool:
    """Whether writing ``new`` would leave the stored value as it is.

    Foreign keys compare by primary key. Text treats NULL and "" as the same
    value, as the formats do: none of them tells an empty value from a
    missing one.
    """
    if model_field.is_relation:
        new_pk = new.pk if isinstance(new, models.Model) else new
        return current == new_pk
    if isinstance(model_field, models.CharField | models.TextField):
        return (current or "") == (new or "")
    return current == new


def _auto_now_fields(model: type[models.Model]) -> list[str]:
    return [
        f.name for f in model._meta.concrete_fields if getattr(f, "auto_now", False)
    ]


def _written(obj: models.Model, names: Iterable[str]) -> dict[str, Any]:
    """The values a new child row was written with, empty ones left out."""
    values = {}
    for name in names:
        value = display(getattr(obj, name))
        if value not in (None, ""):
            values[name] = value
    return values


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def upsert(
    model: type[models.Model],
    *,
    lookup: Mapping[str, Any],
    values: Mapping[str, Any],
    outcome: OpOutcome,
    create_values: Mapping[str, Any] | None = None,
    existing: Any = LOOKUP,
    path: tuple[str, ...] = (),
) -> tuple[Any, bool]:
    """Insert the row, or bring an existing one in line with ``values``.

    ``lookup`` identifies the row, ``values`` are what the source says about
    it, and ``create_values`` apply only to a new row (defaults for what a
    format doesn't carry, which must not overwrite what the project has).
    ``existing`` is the row when the caller already has it (``None`` if it
    knows there is none); by default it is looked up.

    ``path`` places the row in its entity: empty for the entity's own row,
    else the (collection, key) pairs down to this child. Returns the row and
    whether it was inserted.
    """
    if existing is LOOKUP:
        existing = model._default_manager.filter(**lookup).first()

    if existing is None:
        written = {**(create_values or {}), **values}
        obj = model(**lookup, **written)
        # A full save, so the model's own hooks (sort orders, hashkey names)
        # and the signals that create staging columns run as they always do.
        obj.save()
        if path:
            outcome.record(path, kind="added", after=_written(obj, written))
        else:
            outcome.touched = True
            outcome.created = True
        return obj, True

    if not path:
        outcome.touched = True
    changed: list[str] = []
    for name, new in values.items():
        model_field = model._meta.get_field(name)
        if _same(model_field, getattr(existing, model_field.attname), new):
            continue
        before = display(getattr(existing, name))
        setattr(existing, name, new)
        changed.append(name)
        outcome.record((*path, name), kind="changed", before=before, after=display(new))
    if changed:
        existing.save(update_fields=[*changed, *_auto_now_fields(model)])
    return existing, False


def sync_members(
    obj: models.Model,
    relation: str,
    desired: Iterable[models.Model],
    *,
    key: Callable[[Any], str],
    outcome: OpOutcome,
    path: tuple[str, ...] = (),
) -> None:
    """Make a many-to-many relation hold exactly ``desired``.

    Writes nothing when it already does, and records each member added or
    removed under ``path + (relation, key(member))``.
    """
    manager = getattr(obj, relation)
    current = {member.pk: member for member in manager.all()}
    wanted = {member.pk: member for member in desired}
    if current.keys() == wanted.keys():
        return
    manager.set(list(wanted.values()))
    for pk in sorted(current.keys() - wanted.keys(), key=lambda pk: key(current[pk])):
        outcome.record((*path, relation, key(current[pk])), kind="removed")
    for pk in sorted(wanted.keys() - current.keys(), key=lambda pk: key(wanted[pk])):
        outcome.record((*path, relation, key(wanted[pk])), kind="added")


def remove(
    obj: models.Model,
    *,
    outcome: OpOutcome,
    path: tuple[str, ...],
) -> None:
    """Delete a child row the source no longer has, and record it."""
    obj.delete()
    outcome.record(path, kind="removed")
