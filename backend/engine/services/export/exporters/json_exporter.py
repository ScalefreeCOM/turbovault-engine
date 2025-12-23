"""
JSON exporter for Data Vault export.

Exports the project to a structured JSON format containing all
metadata needed for model generation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from engine.services.export.exporters.base import BaseExporter

if TYPE_CHECKING:
    from engine.services.export.models import ProjectExport


class JSONExporter(BaseExporter):
    """
    Exports Data Vault project to JSON format.
    
    Produces a structured JSON document with all sources, hubs, stages,
    and their definitions.
    """
    
    def __init__(self, indent: int = 2) -> None:
        """
        Initialize JSON exporter.
        
        Args:
            indent: JSON indentation level (default 2)
        """
        self.indent = indent
    
    def export(self, project_export: "ProjectExport") -> str:
        """
        Export project to JSON string.
        
        Args:
            project_export: The intermediate project representation
            
        Returns:
            Formatted JSON string
        """
        return project_export.model_dump_json(indent=self.indent)
    
    def get_format_name(self) -> str:
        """Return format identifier."""
        return "json"
    
    def get_file_extension(self) -> str:
        """Return file extension."""
        return "json"
