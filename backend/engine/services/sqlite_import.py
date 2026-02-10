
from engine.services.metadata_source import SqliteMetadataSource
from engine.services.base_import_service import BaseImportService

class SqliteImportService(BaseImportService):
    """
    Service to import metadata from SQLite database.
    """
    def __init__(self, db_path: str):
        super().__init__(SqliteMetadataSource(db_path))
