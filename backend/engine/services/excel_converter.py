
import pandas as pd
import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

class ExcelToSqliteConverter:
    """
    Utility to convert Excel sheets into SQLite tables.
    """
    def __init__(self, excel_path: str):
        self.excel_path = excel_path

    def convert(self, sqlite_path: str):
        """
        Reads all sheets from Excel and writes them to SQLite.
        """
        logger.info(f"Converting {self.excel_path} to {sqlite_path}")
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)
        
        # Remove existing file if it exists
        if os.path.exists(sqlite_path):
            os.remove(sqlite_path)

        excel_file = pd.ExcelFile(self.excel_path)
        conn = sqlite3.connect(sqlite_path)
        
        try:
            for sheet_name in excel_file.sheet_names:
                df = excel_file.parse(sheet_name)
                # We don't standardize names here, SqliteMetadataSource will do that.
                # However, we need to handle empty sheets or all-NA columns if necessary.
                df.to_sql(sheet_name, conn, index=False, if_exists='replace')
            logger.info("Conversion successful")
        finally:
            conn.close()
