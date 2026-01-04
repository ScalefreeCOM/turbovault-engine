"""
Views for TurboVault Engine.

This module contains views for the static landing page.
"""

from django.shortcuts import render
from django.http import HttpRequest, HttpResponse


def home(request: HttpRequest) -> HttpResponse:
    """
    Render the TurboVault Engine landing page.

    Returns the static home page with project information
    and a link to the Django admin area.
    """
    return render(request, 'home.html')
