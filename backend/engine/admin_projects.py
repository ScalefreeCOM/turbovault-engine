"""
Projects in the admin's dropdowns.

A workspace holds several projects, and their columns and entities often
share names (two projects importing the same source). The admin's selects
and autocomplete lists therefore name each item's project ("[source]
Customer.C_NAME · shop"), and on an existing object's page offer only the
items of that object's project. On an add page the project isn't known yet:
everything is offered, labelled with its project.
"""

from __future__ import annotations

from functools import cache
from typing import Any
from urllib.parse import urlparse

from django.apps import apps
from django.contrib.admin.views.autocomplete import AutocompleteJsonView
from django.urls import Resolver404, resolve

# Relations through which a model without a project of its own reaches one,
# tried in this order.
_PARENTS = (
    "source_table",
    "source_system",
    "hub",
    "link",
    "satellite",
    "hub_column",
    "link_column",
    "staging_column",
    "reference_table",
    "pit",
    "snapshot_control_table",
    "snapshot_control",
    "prejoin",
)


@cache
def project_path(model: type) -> str | None:
    """The lookup from ``model`` to its project (``project``,
    ``source_table__project``, ...), or None for a model outside projects."""
    if model._meta.label == "engine.Project":
        return None
    relations = {
        field.name: field
        for field in model._meta.get_fields()
        if getattr(field, "many_to_one", False) and field.related_model is not None
    }
    if "project" in relations:
        return "project"
    for name in _PARENTS:
        if name in relations and relations[name].related_model is not model:
            sub = project_path(relations[name].related_model)
            if sub:
                return f"{name}__{sub}"
    return None


def project_of(obj: Any) -> Any:
    """The project an object belongs to (a project: itself), or None."""
    if obj is None:
        return None
    if obj._meta.label == "engine.Project":
        return obj
    path = project_path(type(obj))
    if path is None:
        return None
    current = obj
    for name in path.split("__"):
        current = getattr(current, name, None)
        if current is None:
            return None
    return current


def with_project(obj: Any) -> str:
    """An object's label with its project's name, e.g.
    ``[source] Customer.C_NAME · shop``."""
    project = project_of(obj)
    return f"{obj} · {project.name}" if project is not None else str(obj)


def _project_of_page(path: str) -> Any:
    """The project of the object an admin change page shows, or None."""
    try:
        match = resolve(path)
    except Resolver404:
        return None
    name = match.url_name or ""
    object_id = match.kwargs.get("object_id")
    if not object_id or not name.endswith("_change"):
        return None
    app_label, _, rest = name.partition("_")
    model_name = rest.removesuffix("_change")
    try:
        model = apps.get_model(app_label, model_name)
        obj = model._default_manager.filter(pk=object_id).first()
    except Exception:  # an unknown model, a malformed id, ...
        return None
    return project_of(obj)


def page_project(request: Any) -> Any:
    """The project of the object being edited: of the page itself, or (for
    an autocomplete request) of the page that asks."""
    match = getattr(request, "resolver_match", None)
    if match is not None and (match.url_name or "").endswith("_change"):
        return _project_of_page(request.path)
    referer = request.META.get("HTTP_REFERER")
    if referer:
        return _project_of_page(urlparse(referer).path)
    return None


def in_project(queryset: Any, project: Any) -> Any:
    """``queryset`` limited to ``project``, where its model belongs to one."""
    path = project_path(queryset.model)
    if project is None or path is None:
        return queryset
    return queryset.filter(**{path: project})


class ProjectFieldsMixin:
    """For admins and inlines: foreign key selects name each item's project
    and, on an existing object's page, offer only that object's project's."""

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if field is None or project_path(db_field.related_model) is None:
            return field
        field.label_from_instance = with_project
        project = page_project(request)
        if project is not None:
            field.queryset = in_project(field.queryset, project)
        return field


class ProjectAutocompleteJsonView(AutocompleteJsonView):
    """Autocomplete results named with their project, limited to the
    project of the page that asks when it shows an existing object."""

    def get_queryset(self):
        queryset = in_project(super().get_queryset(), page_project(self.request))
        if not queryset.ordered:
            # Paged results need an order: by project, so a list across
            # projects groups them
            path = project_path(queryset.model)
            queryset = queryset.order_by(*([f"{path}__name"] if path else []), "pk")
        return queryset

    def serialize_result(self, obj, to_field_name):
        return {"id": str(getattr(obj, to_field_name)), "text": with_project(obj)}
