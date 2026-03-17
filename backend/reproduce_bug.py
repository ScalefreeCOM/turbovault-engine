import os
import django
import sqlite3
from django.db import IntegrityError

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")
django.setup()

from engine.models import Project, SourceSystem, SourceTable, StagingColumn, Satellite, SatelliteColumn, SourceColumn, Hub
from engine.services.sqlite_import import SqliteImportService

def reproduce_unique_violation():
    print("Attempting to reproduce UNIQUE constraint violation...")
    
    # 0. Clean up
    Project.objects.all().delete()
    
    # 1. Setup Data
    p = Project.objects.create(name="Repro Project")
    hub = Hub.objects.create(project=p, hub_physical_name="HUB_REPRO", hub_hashkey_name="HK_REPRO")
    ss = SourceSystem.objects.create(project=p, name="Repro System", schema_name="raw")
    st = SourceTable.objects.create(project=p, source_system=ss, physical_table_name="REPRO_TABLE", record_source_value="RSRC", load_date_value="LDTS")
    sc1 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL1", source_column_datatype="INT")
    sc2 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL2", source_column_datatype="INT")
    
    # 2. Design a "colliding" SQLite table
    # Row 1 is NULL -> gets 1 from save()
    # Row 2 is 1 -> tried to be created with 1 -> BOOM
    conn = sqlite3.connect(":memory:")
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
    
    conn.execute("INSERT INTO [standard_satellite] VALUES ('SAT', 'HUB_REPRO', 'REPRO_TABLE', 'COL1', NULL, 'SAT_ID')")
    conn.execute("INSERT INTO [standard_satellite] VALUES ('SAT', 'HUB_REPRO', 'REPRO_TABLE', 'COL2', '1', 'SAT_ID')")
    conn.commit()
    
    service = SqliteImportService(conn)
    service.project = p
    service._hubs = {"HUB_REPRO": hub}
    service._source_tables = {"REPRO_TABLE": st}
    service._source_columns = {
        "REPRO_TABLE|COL1": sc1,
        "REPRO_TABLE|COL2": sc2
    }
    
    try:
        service._process_satellites("standard_satellite")
        print("Import completed without error.")
        
        # Verify
        sat = Satellite.objects.get(satellite_physical_name="SAT")
        col1 = SatelliteColumn.objects.get(satellite=sat, staging_column__source_column=sc1) # was NULL in source
        col2 = SatelliteColumn.objects.get(satellite=sat, staging_column__source_column=sc2) # was '1' in source
        
        print(f"COL1 (NULL source) -> {col1.column_sort_order}")
        print(f"COL2 ('1' source)  -> {col2.column_sort_order}")
        
        # COL2 should be 1
        # COL1 should be something else (likely 2, because 1 was reserved)
        assert col2.column_sort_order == 1
        assert col1.column_sort_order != 1
        assert col1.column_sort_order > 0
        
        print("Verification SUCCESS: No collisions and correct orders assigned.")
        
    except IntegrityError as e:
        print(f"Reproduction SUCCESS: Caught expected error: {e}")
    except Exception as e:
        print(f"Caught unexpected error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    reproduce_unique_violation()
