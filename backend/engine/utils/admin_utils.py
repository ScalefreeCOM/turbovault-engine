"""
Admin user auto-creation utility for TurboVault Engine.

Creates a Django superuser from turbovault.yml credentials if configured.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def create_admin_user_if_configured() -> None:
    """
    Create admin superuser from turbovault.yml if configured.

    Only creates if:
    - admin credentials are defined in turbovault.yml
    - no superuser exists yet

    This runs on Django startup via AppConfig.ready()
    """
    from django.contrib.auth import get_user_model

    from engine.services.app_config_loader import load_application_config

    try:
        app_config = load_application_config()
    except Exception as e:
        logger.debug(f"Could not load app config for admin creation: {e}")
        return

    # Check if admin credentials are configured
    if not app_config.admin:
        return

    User = get_user_model()

    # Check if any superuser exists
    if User.objects.filter(is_superuser=True).exists():
        logger.debug("Superuser already exists, skipping auto-creation")
        return

    # Create the superuser
    try:
        User.objects.create_superuser(
            username=app_config.admin.username,
            email=app_config.admin.email,
            password=app_config.admin.password,
        )
        logger.info(
            f"✓ Created admin superuser: {app_config.admin.username} "
            f"({app_config.admin.email})"
        )
    except Exception as e:
        logger.warning(f"Failed to create admin user: {e}")
