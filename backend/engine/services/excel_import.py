
import os
import tempfile
import logging
from engine.services.excel_converter import ExcelToSqliteConverter
from engine.services.sqlite_import import SqliteImportService
from engine.models.project import Project

logger = logging.getLogger(__name__)

class ExcelImportService:
    """
    Service to import metadata from Excel by converting it to SQLite first.
    This ensures a single, unified import logic path.
    """
    def __init__(self, excel_path: str):
        self.excel_path = excel_path

    def import_metadata(
        self,
        project_name: str | None = None,
        description: str | None = None,
        project: Project | None = None,
        skip_snapshots: bool = False,
    ) -> Project:
        logger.info(f"Importing Excel from {self.excel_path} via SQLite bridge")
        
        # 1. Convert to temporary SQLite
        temp_fd, temp_path = tempfile.mkstemp(suffix=".db")
        os.close(temp_fd)
        
        try:
            converter = ExcelToSqliteConverter(self.excel_path)
            converter.convert(temp_path)
            
            # 2. Use SqliteImportService
            sqlite_service = SqliteImportService(temp_path)
            return sqlite_service.import_metadata(
                project_name=project_name,
                description=description,
                project=project,
                skip_snapshots=skip_snapshots
            )
        finally:
            # 3. Clean up
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception as e:
                    logger.warning(f"Failed to remove temp file {temp_path}: {e}")
