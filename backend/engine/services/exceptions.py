from typing import Dict, List

class MetadataSchemaError(Exception):
    """Raised when the input metadata file is missing required columns."""
    
    # Required columns per sheet/table
    REQUIRED_COLUMNS: Dict[str, List[str]] = {
        "source_data": [
            "source_system", "source_schema_physical_name", 
            "source_table_physical_name", "source_table_identifier"
        ],
        "standard_hub": [
            "target_hub_table_physical_name", "source_table_identifier", 
            "source_column_physical_name"
        ],
        "ref_hub": [
            "target_reference_table_physical_name", "source_table_identifier", 
            "source_column_physical_name"
        ],
        "standard_link": [
            "target_link_table_physical_name", "source_table_identifier", 
            "source_column_physical_name"
        ],
        "non_historized_link": [
            "target_link_table_physical_name", "source_table_identifier", 
            "source_column_physical_name"
        ],
        "standard_satellite": [
            "target_satellite_table_physical_name", "parent_identifier", 
            "source_table_identifier", "source_column_physical_name"
        ],
        "non_historized_satellite": [
            "target_satellite_table_physical_name", "parent_identifier", 
            "source_table_identifier", "source_column_physical_name"
        ],
        "multiactive_satellite": [
            "target_satellite_table_physical_name", "parent_identifier", 
            "source_table_identifier", "source_column_physical_name",
            "multi_active_attributes"
        ],
        "ref_sat": [
            "target_reference_table_physical_name",
            "source_table_identifier", "source_column_physical_name"
        ],
        "ref_table": [
            "target_reference_table_physical_name", "referenced_hub"
        ],
        "pit": [
            "pit_physical_table_name", "tracked_entity", "satellite_identifiers"
        ]
    }

    def __init__(self, sheet_name: str, missing_columns: List[str]):
        self.sheet_name = sheet_name
        self.missing_columns = missing_columns
        message = f"Invalid schema in '{sheet_name}': Missing required columns: {', '.join(missing_columns)}"
        super().__init__(message)