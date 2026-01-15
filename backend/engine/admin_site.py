"""
Custom Django Admin Site for TurboVault Engine.

Provides custom model grouping in the admin index by monkey-patching
the default admin site's get_app_list method.
"""

from typing import Any

from django.contrib import admin

# Store the original get_app_list method
_original_get_app_list = admin.site.__class__.get_app_list


def custom_get_app_list(
    self: admin.AdminSite, request: Any, app_label: str | None = None
) -> list[dict[str, Any]]:
    """
    Override to reorganize models into custom groups.

    This method is stable across Django versions and is the recommended way
    to customize the admin index page grouping.
    """
    # Get the default app list
    app_dict = self._build_app_dict(request, app_label)

    # Define custom groupings
    base_metadata_models = {
        "project",
        "group",
        "sourcesystem",
        "sourcetable",
        "sourcecolumn",
        "snapshotcontroltable",
        "snapshotcontrollogic",
    }

    data_vault_models = {
        "hub",
        "hubcolumn",
        "hubsourcemapping",
        "link",
        "linkhubreference",
        "linkhubsourcemapping",
        "linkcolumn",
        "linksourcemapping",
        "satellite",
        "satellitecolumn",
        "referencetable",
        "referencetablesatelliteassignment",
        "pit",
        "prejoindefinition",
        "prejoinextractioncolumn",
    }

    dbt_metadata_models = {"templatecategory", "modeltemplate"}

    # Extract models from the engine app
    engine_app = app_dict.get("engine", {})
    engine_models = engine_app.get("models", [])

    # Create custom app groups
    custom_apps = []

    # Base Metadata group
    base_models = [
        model
        for model in engine_models
        if model.get("object_name", "").lower() in base_metadata_models
    ]
    if base_models:
        custom_apps.append(
            {
                "name": "Base Metadata",
                "app_label": "base_metadata",
                "app_url": "/admin/engine/",
                "has_module_perms": True,
                "models": sorted(base_models, key=lambda x: x["name"]),
            }
        )

    # Data Vault Metadata group
    vault_models = [
        model
        for model in engine_models
        if model.get("object_name", "").lower() in data_vault_models
    ]
    if vault_models:
        custom_apps.append(
            {
                "name": "Data Vault Metadata",
                "app_label": "data_vault_metadata",
                "app_url": "/admin/engine/",
                "has_module_perms": True,
                "models": sorted(vault_models, key=lambda x: x["name"]),
            }
        )

    # dbt Metadata group
    template_models = [
        model
        for model in engine_models
        if model.get("object_name", "").lower() in dbt_metadata_models
    ]
    if template_models:
        custom_apps.append(
            {
                "name": "dbt Metadata",
                "app_label": "dbt_metadata",
                "app_url": "/admin/engine/",
                "has_module_perms": True,
                "models": sorted(template_models, key=lambda x: x["name"]),
            }
        )

    # Add any other apps (auth, etc.) that aren't from engine
    for app_label_key, app_data in app_dict.items():
        if app_label_key != "engine":
            custom_apps.append(app_data)

    # Sort apps: custom groups first, then others
    custom_group_names = {"base_metadata", "data_vault_metadata", "dbt_metadata"}
    custom_groups = [
        app for app in custom_apps if app.get("app_label") in custom_group_names
    ]
    other_apps = [
        app for app in custom_apps if app.get("app_label") not in custom_group_names
    ]

    return custom_groups + sorted(other_apps, key=lambda x: x.get("name", ""))


# Monkey-patch the admin site to use our custom get_app_list
admin.site.get_app_list = custom_get_app_list.__get__(admin.site, admin.site.__class__)
