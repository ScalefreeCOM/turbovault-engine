
from abc import ABC, abstractmethod
import pandas as pd
import sqlite3
import logging

logger = logging.getLogger(__name__)

class MetadataSource(ABC):
    @abstractmethod
    def get_sheet_names(self) -> list[str]:
        pass

    @abstractmethod
    def get_data(self, sheet_name: str) -> pd.DataFrame:
        pass

class ExcelMetadataSource(MetadataSource):
    def __init__(self, file_path: str):
        self.excel_file = pd.ExcelFile(file_path)

    def get_sheet_names(self) -> list[str]:
        return self.excel_file.sheet_names

    def get_data(self, sheet_name: str) -> pd.DataFrame:
        df = self.excel_file.parse(sheet_name)
        # Standardize column names (lowercase and stripped)
        df.columns = [str(c).lower().strip() for c in df.columns]
        return df

class SqliteMetadataSource(MetadataSource):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)

    def get_sheet_names(self) -> list[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        return [row[0] for row in cursor.fetchall()]

    def get_data(self, sheet_name: str) -> pd.DataFrame:
        df = pd.read_sql(f"SELECT * FROM [{sheet_name}]", self.conn)
        # Standardize column names (lowercase and stripped)
        df.columns = [str(c).lower().strip() for c in df.columns]
        return df

    def __del__(self):
        if hasattr(self, 'conn'):
            self.conn.close()
