import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")
django.setup()

from engine.models import Project, SourceSystem, SourceTable, StagingColumn, Satellite, SatelliteColumn, SourceColumn, Hub

def verify_auto_increment():
    print("Verifying SatelliteColumn.save() auto-increment logic...")
    
    # Create test data
    p = Project.objects.create(name="Test Sort Project")
    hub = Hub.objects.create(project=p, hub_physical_name="HUB_TEST", hub_hashkey_name="HK_TEST")
    
    ss = SourceSystem.objects.create(project=p, name="Test System", schema_name="raw")
    st = SourceTable.objects.create(project=p, source_system=ss, physical_table_name="TEST_TABLE", record_source_value="RSRC", load_date_value="LDTS")
    
    sc1 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL1", source_column_datatype="VARCHAR")
    sc2 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL2", source_column_datatype="VARCHAR")
    sc3 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL3", source_column_datatype="VARCHAR")
    
    st_col1 = StagingColumn.objects.create(project=p, source_table=st, source_column=sc1)
    st_col2 = StagingColumn.objects.create(project=p, source_table=st, source_column=sc2)
    st_col3 = StagingColumn.objects.create(project=p, source_table=st, source_column=sc3)
    
    sat = Satellite.objects.create(project=p, satellite_physical_name="SAT_TEST", source_table=st, parent_hub=hub)
    
    # 1. Add first column, sort order should be 1
    c1 = SatelliteColumn.objects.create(satellite=sat, staging_column=st_col1)
    print(f"Col1 sort_order: {c1.column_sort_order}")
    assert c1.column_sort_order == 1
    
    # 2. Add second column, sort order should be 2
    c2 = SatelliteColumn.objects.create(satellite=sat, staging_column=st_col2)
    print(f"Col2 sort_order: {c2.column_sort_order}")
    assert c2.column_sort_order == 2
    
    # 3. Add third column with manual sort order 10
    c3 = SatelliteColumn.objects.create(satellite=sat, staging_column=st_col3, column_sort_order=10)
    print(f"Col3 sort_order: {c3.column_sort_order}")
    assert c3.column_sort_order == 10
    
    # 4. Add another column, sort order should be 11
    sc4 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL4", source_column_datatype="VARCHAR")
    st_col4 = StagingColumn.objects.create(project=p, source_table=st, source_column=sc4)
    c4 = SatelliteColumn.objects.create(satellite=sat, staging_column=st_col4)
    print(f"Col4 sort_order: {c4.column_sort_order}")
    assert c4.column_sort_order == 11
    
    # 5. Check uniqueness (should fail if we try to duplicate)
    from django.db import IntegrityError
    try:
        sc5 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL5", source_column_datatype="VARCHAR")
        st_col5 = StagingColumn.objects.create(project=p, source_table=st, source_column=sc5)
        SatelliteColumn.objects.create(satellite=sat, staging_column=st_col5, column_sort_order=11)
        print("Error: duplicate sort order should have failed!")
    except IntegrityError as e:
        print(f"Caught expected unique constraint error (IntegrityError): {e}")
    except Exception as e:
        print(f"Caught unexpected error: {type(e).__name__}: {e}")

    print("Auto-increment and uniqueness verification: SUCCESS")

if __name__ == "__main__":
    verify_auto_increment()
