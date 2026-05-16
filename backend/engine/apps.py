from django.apps import AppConfig


class EngineCoreConfig(AppConfig):
    name = "engine"
    verbose_name = "Base Metadata"

    def ready(self) -> None:
        """Register model signals required by Engine domain models."""
        import engine.models.signals  # noqa: F401


class EngineStandaloneConfig(EngineCoreConfig):
    """
    Engine app config for the standalone CLI/admin application.

    Embedders such as Turbovault Studio should use ``EngineCoreConfig`` so
    startup does not depend on ``turbovault.yml`` or mutate the host admin site.
    """

    def ready(self) -> None:
        """
        Configure admin site customizations.
        This method is called when Django starts.
        """
        super().ready()

        from django.contrib import admin

        # Customize admin site headers and titles
        admin.site.site_header = "Turbovault Engine"
        admin.site.site_title = "Turbovault Engine Admin"
        admin.site.index_title = "Turbovault Engine Administration"

        # Import admin_site to apply monkey patch for model grouping
        from engine import admin_site  # noqa: F401

        # Auto-create admin user from turbovault.yml if configured
        from engine.utils.admin_utils import create_admin_user_if_configured

        create_admin_user_if_configured()


# Backward-compatible default for existing standalone installs.
EngineConfig = EngineStandaloneConfig
