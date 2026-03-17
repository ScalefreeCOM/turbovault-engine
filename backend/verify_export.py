import os
import django
from unittest.mock import MagicMock

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")
django.setup()

from engine.models import Project, SourceSystem, SourceTable, StagingColumn, Satellite, SatelliteColumn, SourceColumn, Hub
from engine.services.export.builder import ModelBuilder

def verify_export_ordering():
    print("Verifying ModelBuilder ordering...")
    
    # 0. Clean up
    Project.objects.all().delete()
    
    # 1. Setup Data
    p = Project.objects.create(name="Export Test Project")
    
    # Mock load_config to avoid needing an actual directory/file
    p.load_config = MagicMock()
    mock_config = MagicMock()
    mock_config.configuration.stage_schema = "test_stage"
    mock_config.configuration.rdv_schema = "test_rdv"
    mock_config.configuration.bdv_schema = "test_bdv"
    p.load_config.return_value = mock_config
    
    hub = Hub.objects.create(project=p, hub_physical_name="HUB_EXP", hub_hashkey_name="HK_EXP")
    ss = SourceSystem.objects.create(project=p, name="Exp System", schema_name="raw")
    st = SourceTable.objects.create(project=p, source_system=ss, physical_table_name="EXP_TABLE", record_source_value="RSRC", load_date_value="LDTS")
    
    sc1 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL1", source_column_datatype="INT")
    sc2 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL2", source_column_datatype="INT")
    sc3 = SourceColumn.objects.create(source_table=st, source_column_physical_name="COL3", source_column_datatype="INT")
    
    st_col1 = StagingColumn.objects.create(project=p, source_table=st, source_column=sc1)
    st_col2 = StagingColumn.objects.create(project=p, source_table=st, source_column=sc2)
    st_col3 = StagingColumn.objects.create(project=p, source_table=st, source_column=sc3)
    
    sat = Satellite.objects.create(project=p, satellite_physical_name="SAT_EXP", source_table=st, parent_hub=hub)
    
    # Set sort orders: COL1=3, COL2=1, COL3=2
    SatelliteColumn.objects.create(satellite=sat, staging_column=st_col1, column_sort_order=3)
    SatelliteColumn.objects.create(satellite=sat, staging_column=st_col2, column_sort_order=1)
    SatelliteColumn.objects.create(satellite=sat, staging_column=st_col3, column_sort_order=2)
    
    builder = ModelBuilder(p)
    # The build() method returns ProjectExport which has satellites: list[SatelliteDefinition]
    project_export = builder.build()
    
    # Find the satellite in project_export
    sat_def = next(s for s in project_export.satellites if s.satellite_physical_name == "SAT_EXP")
    # payload is list[SatelliteColumnDef]
    payload_names = [c.source_column_physical_name for c in sat_def.payload]
    
    print(f"Exported payload order: {payload_names}")
    # Should be COL2 (1), COL3 (2), COL1 (3)
    assert payload_names == ["COL2", "COL3", "COL1"]
    
    print("Export builder verification: SUCCESS")

if __name__ == "__main__":
    verify_export_ordering()
