"""
Base exporter interface for Data Vault export.

Defines the abstract interface that all exporters must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.services.export.models import ProjectExport


class BaseExporter(ABC):
    """
    Abstract base class for Data Vault exporters.

    All export formats (JSON, dbt, DBML, SQL) should inherit from this
    and implement the required methods.
    """

    @abstractmethod
    def export(self, project_export: ProjectExport) -> str:
        """
        Export project to target format.

        Args:
            project_export: The intermediate project representation

        Returns:
            Serialized string in the target format
        """
        pass

    @abstractmethod
    def get_format_name(self) -> str:
        """
        Return the format identifier.

        Returns:
            Format name (e.g., 'json', 'dbt', 'dbml')
        """
        pass

    @abstractmethod
    def get_file_extension(self) -> str:
        """
        Return the default file extension for this format.

        Returns:
            File extension without dot (e.g., 'json', 'sql')
        """
        pass
