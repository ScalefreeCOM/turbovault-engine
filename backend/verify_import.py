import os
import django
import pandas as pd
from unittest.mock import MagicMock

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")
django.setup()

from engine.models import Project, SourceSystem, SourceTable, StagingColumn, Satellite, SatelliteColumn, SourceColumn, Hub
from engine.services.base_import_service import BaseImportService

def verify_import_logic():
    print("Verifying BaseImportService._process_satellites() logic...")
    
    # 1. Setup Project and Metadata
    p = Project.objects.create(name="Import Test Project")
    hub = Hub.objects.create(project=p, hub_physical_name="HUB_IMPORT", hub_hashkey_name="HK_IMPORT")
    ss = SourceSystem.objects.create(project=p, name="Import System", schema_name="raw")
    st = SourceTable.objects.create(project=p, source_system=ss, physical_table_name="IMPORT_TABLE", record_source_value="RSRC", load_date_value="LDTS")
    sc1 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL1", source_column_datatype="INT")
    sc2 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL2", source_column_datatype="INT")
    sc3 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL3", source_column_datatype="INT")
    
    st_col1 = StagingColumn.objects.create(project=p, source_table=st, source_column=sc1)
    st_col2 = StagingColumn.objects.create(project=p, source_table=st, source_column=sc2)
    st_col3 = StagingColumn.objects.create(project=p, source_table=st, source_column=sc3)
    
    # 2. Setup Service with Mocks
    mock_source = MagicMock()
    service = BaseImportService(mock_source)
    service.project = p
    
    # Fill internal caches that _process_satellites uses
    service._hubs = {"HUB_IMPORT": hub}
    service._source_tables = {"IMPORT_TABLE": st}
    # Note: source_columns cache uses format "table_id|col_name" or similar
    # In base_import_service.py it seems to use source_table_identifier
    service._source_columns = {
        "IMPORT_TABLE|COL1": sc1,
        "IMPORT_TABLE|COL2": sc2,
        "IMPORT_TABLE|COL3": sc3,
    }

    # 3. Create Mock Data
    rows = [
        {
            "target_satellite_table_physical_name": "SAT_IMPORT",
            "referenced_hub": "HUB_IMPORT",
            "source_table_identifier": "IMPORT_TABLE",
            "source_column_physical_name": "COL1",
            "Target_Column_Sort_Order": 5,
            "satellite_identifier": "SAT_IMPORT_ID"
        },
        {
            "target_satellite_table_physical_name": "SAT_IMPORT",
            "referenced_hub": "HUB_IMPORT",
            "source_table_identifier": "IMPORT_TABLE",
            "source_column_physical_name": "COL2",
            "Target_Column_Sort_Order": 3,
            "satellite_identifier": "SAT_IMPORT_ID"
        },
        {
            "target_satellite_table_physical_name": "SAT_IMPORT",
            "referenced_hub": "HUB_IMPORT",
            "source_table_identifier": "IMPORT_TABLE",
            "source_column_physical_name": "COL3",
            "Target_Column_Sort_Order": None, # Should auto-increment to 6
            "satellite_identifier": "SAT_IMPORT_ID"
        }
    ]
    df = pd.DataFrame(rows)
    
    # 4. Run Import
    service._process_satellites(df, "standard_satellite")
    
    # 5. Verify results
    sat = Satellite.objects.get(satellite_physical_name="SAT_IMPORT")
    col1 = SatelliteColumn.objects.get(satellite=sat, staging_column__source_column=sc1)
    col2 = SatelliteColumn.objects.get(satellite=sat, staging_column__source_column=sc2)
    col3 = SatelliteColumn.objects.get(satellite=sat, staging_column__source_column=sc3)
    
    print(f"Imported Col1 sort_order: {col1.column_sort_order}")
    print(f"Imported Col2 sort_order: {col2.column_sort_order}")
    print(f"Imported Col3 sort_order: {col3.column_sort_order}")
    
    assert col1.column_sort_order == 5
    assert col2.column_sort_order == 3
    assert col3.column_sort_order == 6 # Max(5, 3) + 1
    
    print("Import service verification: SUCCESS")

if __name__ == "__main__":
    verify_import_logic()
