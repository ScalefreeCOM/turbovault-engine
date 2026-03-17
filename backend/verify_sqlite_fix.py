import os
import django
import sqlite3

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")
django.setup()

from engine.models import Project, SourceSystem, SourceTable, StagingColumn, Satellite, SatelliteColumn, SourceColumn, Hub
from engine.services.sqlite_import import SqliteImportService
from engine.services.staging_service import get_or_create_staging_column

def verify_sqlite_import_fix():
    print("Verifying SqliteImportService fix for column_sort_order...")
    
    # 0. Clean up
    Project.objects.all().delete()
    
    # 1. Setup Database state
    p = Project.objects.create(name="SQLite Fix Test")
    hub = Hub.objects.create(project=p, hub_physical_name="HUB_FIX", hub_hashkey_name="HK_FIX")
    ss = SourceSystem.objects.create(project=p, name="Fix System", schema_name="raw")
    st = SourceTable.objects.create(project=p, source_system=ss, physical_table_name="FIX_TABLE", record_source_value="RSRC", load_date_value="LDTS")
    sc1 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL1", source_column_datatype="INT")
    sc2 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL2", source_column_datatype="INT")
    
    # 2. Setup in-memory SQLite with the "standard_satellite" table
    conn = sqlite3.connect(":memory:")
    # Use lowercase column names as ExcelImport would do
    conn.execute("""
        CREATE TABLE [standard_satellite] (
            [target_satellite_table_physical_name] TEXT,
            [referenced_hub] TEXT,
            [source_table_identifier] TEXT,
            [source_column_physical_name] TEXT,
            [target_column_sort_order] TEXT,
            [satellite_identifier] TEXT
        )
    """)
    
    # Insert rows matching the user's scenario
    # C_ACCTBAL (COL1) as 3, another column (COL2) as 1
    conn.execute("""
        INSERT INTO [standard_satellite] 
        VALUES ('SAT_FIX', 'HUB_FIX', 'FIX_TABLE', 'COL1', '3', 'SAT_ID')
    """)
    conn.execute("""
        INSERT INTO [standard_satellite] 
        VALUES ('SAT_FIX', 'HUB_FIX', 'FIX_TABLE', 'COL2', '1', 'SAT_ID')
    """)
    conn.commit()
    
    # 3. Run Import
    service = SqliteImportService(conn)
    service.project = p
    # Populate caches manually to skip source_data processing
    service._hubs = {"HUB_FIX": hub}
    service._source_tables = {"FIX_TABLE": st}
    service._source_columns = {
        "FIX_TABLE|COL1": sc1,
        "FIX_TABLE|COL2": sc2
    }
    
    service._process_satellites("standard_satellite")
    
    # 4. Verify results
    sat = Satellite.objects.get(satellite_physical_name="SAT_FIX")
    # Retrieve columns by name to check sort order
    sc1_col = SatelliteColumn.objects.get(satellite=sat, staging_column__source_column=sc1)
    sc2_col = SatelliteColumn.objects.get(satellite=sat, staging_column__source_column=sc2)
    
    print(f"Imported COL1 sort_order: {sc1_col.column_sort_order}")
    print(f"Imported COL2 sort_order: {sc2_col.column_sort_order}")
    
    # COL1 should be 3, COL2 should be 1
    assert sc1_col.column_sort_order == 3
    assert sc2_col.column_sort_order == 1
    
    print("SQLite import verification: SUCCESS")

if __name__ == "__main__":
    verify_sqlite_import_fix()
