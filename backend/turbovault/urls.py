"""
URL configuration for TurboVault Engine.

This is a CLI-first application. Django Admin is available for data inspection.
A static landing page is served at the root URL.
"""

from django.contrib import admin
from django.urls import path

from turbovault.views import check_project_name, create_project, home, init_wizard

urlpatterns = [
    path("", home, name="home"),
    path("init/", init_wizard, name="init_wizard"),
    path("init/check-name/", check_project_name, name="check_project_name"),
    path("init/create/", create_project, name="create_project"),
    path("admin/", admin.site.urls),
]
