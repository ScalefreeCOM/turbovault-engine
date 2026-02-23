"""
Django settings for TurboVault Engine.

This is a CLI-first Django configuration. No HTTP views, DRF, or templates are used.
The Engine uses Django for:
- ORM and migrations
- Management commands
- Configuration and app wiring
"""

from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-&-o!d9e&9m9zu1f6--ppzjm7=f5+hizogbl5alest6chep_2u&"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []


# Application definition
# Apps for CLI-first usage with Django Admin available for data inspection
INSTALLED_APPS = [
    # Django admin and supporting apps (for future data inspection/debugging)
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # TurboVault Engine app
    "engine.apps.EngineConfig",
]

# Middleware required for admin functionality
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "turbovault.urls"

# Templates - needed for Django Admin and landing page
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "turbovault" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "turbovault.wsgi.application"


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases
# Database configuration loaded from turbovault.yml (global application config)


def get_database_config() -> dict[str, dict[str, str | int | dict]]:
    """
    Get database configuration from turbovault.yml.

    Loads application-level database config from turbovault.yml.
    Auto-creates turbovault.yml with SQLite defaults if not present.

    Returns:
        Django DATABASES configuration dictionary
    """
    from engine.services.app_config_loader import load_application_config

    try:
        app_config = load_application_config()
        if app_config.database:
            return {"default": app_config.database.to_django_config(Path.cwd())}
    except Exception as e:
        # If config loading fails, fall back to default SQLite
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(
            f"Failed to load database config from turbovault.yml: {e}. "
            "Using default SQLite."
        )

    # Fallback: Default SQLite configuration in current directory (workspace)
    from engine.services.config_schema import DatabaseConfig, DatabaseEngine

    default_db = DatabaseConfig(
        engine=DatabaseEngine.SQLITE,
        name="db.sqlite3",  # Relative to cwd (the user's workspace)
    )
    return {"default": default_db.to_django_config(Path.cwd())}


DATABASES = get_database_config()


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# Used for the landing page styling
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "turbovault" / "static"]

# Default primary key field type
# https://docs.djangoproject.com/en/6.0/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
