from django.apps import AppConfig


class EngineConfig(AppConfig):
    name = "engine"
    verbose_name = "Base Metadata"

    def ready(self) -> None:
        """
        Configure admin site customizations.
        This method is called when Django starts.
        """
        from django.contrib import admin

        # Customize admin site headers and titles
        admin.site.site_header = "Turbovault Engine"
        admin.site.site_title = "Turbovault Engine Admin"
        admin.site.index_title = "Turbovault Engine Administration"

        # Import admin_site to apply monkey patch for model grouping
        # Register signals
        import engine.models.signals  # noqa: F401
        from engine import admin_site  # noqa: F401

        # Auto-create admin user from turbovault.yml if configured
        from engine.utils.admin_utils import create_admin_user_if_configured

        create_admin_user_if_configured()
