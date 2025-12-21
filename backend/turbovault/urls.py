"""
URL configuration for TurboVault Engine.

This is a CLI-first application. Django Admin is available for data inspection.
"""
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path('admin/', admin.site.urls),
]

