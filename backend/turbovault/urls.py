"""
URL configuration for TurboVault Engine.

This is a CLI-first application. Django Admin is available for data inspection.
A static landing page is served at the root URL.
"""

from django.contrib import admin
from django.urls import path

from turbovault.views import home

urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
]
