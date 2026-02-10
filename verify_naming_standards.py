import os
import django
import sys
from pathlib import Path

# Setup Django
sys.path.append(os.path.join(os.getcwd(), "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")
django.setup()

from engine.models import Project, Hub, Link, Satellite, SourceTable, SourceSystem, Group
from engine.services.export.builder import ModelBuilder
from engine.services.generation import DbtProjectGenerator, GenerationConfig

def verify_naming():
    # 1. Setup Test Project with custom patterns
    project_name = "test_naming_project_unique"
    Project.objects.filter(name=project_name).delete()
    
    config = {
        "hashkey_naming": "TST_HK_[[ entity_name ]]",
        "hashdiff_naming": "TST_HD_[[ satellite_name ]]",
        "satellite_v0_naming": "TST_[[ satellite_name ]]_V0",
        "satellite_v1_naming": "TST_[[ satellite_name ]]_V1"
    }
    project = Project.objects.create(name=project_name, config=config)
    print(f"Created project: {project.name} with custom naming patterns.")

    try:
        # 2. Test Hub Auto-naming
        hub = Hub.objects.create(
            project=project,
            hub_physical_name="hub_test",
            hub_type="standard"
        )
        # Hub.save() should have populated it
        print(f"Hub hashkey name: {hub.hub_hashkey_name} (Expected: TST_HK_hub_test)")
        assert hub.hub_hashkey_name == "TST_HK_hub_test"

        # 3. Test Link Auto-naming
        link = Link.objects.create(
            project=project,
            link_physical_name="link_test",
            link_type="standard"
        )
        print(f"Link hashkey name: {link.link_hashkey_name} (Expected: TST_HK_link_test)")
        assert link.link_hashkey_name == "TST_HK_link_test"

        # 4. Test Hashdiff naming in Export Builder
        source_system = SourceSystem.objects.create(project=project, name="SRC_NAMING", schema_name="STST")
        source_table = SourceTable.objects.create(
            project=project,
            source_system=source_system,
            physical_table_name="STBL_NAMING",
            record_source_value="'SRC'",
            load_date_value="CURRENT_TIMESTAMP"
        )
        sat = Satellite.objects.create(
            project=project,
            satellite_physical_name="sat_test",
            satellite_type="standard",
            source_table=source_table,
            parent_hub=hub
        )
        # Add a column for hashdiff
        from engine.models import SourceColumn, SatelliteColumn
        sc = SourceColumn.objects.create(source_table=source_table, source_column_physical_name="COL1")
        SatelliteColumn.objects.create(satellite=sat, source_column=sc, include_in_delta_detection=True)

        builder = ModelBuilder(project)
        export = builder.build()
        
        # Check StageHashdiffDef
        found_hd = False
        for stage in export.stages:
            for hd in stage.hashdiffs:
                print(f"Found Stage hashdiff: {hd.hashdiff_name} for sat {hd.satellite_name}")
                if hd.satellite_name == "sat_test":
                    assert hd.hashdiff_name == "TST_HD_sat_test"
                    found_hd = True
        assert found_hd, "Hashdiff not found in stage export"

        # Check SatelliteDefinition
        found_sat_hd = False
        for sat_def in export.satellites:
            if sat_def.satellite_name == "sat_test":
                print(f"Satellite definition hashdiff name: {sat_def.hashdiff_name}")
                assert sat_def.hashdiff_name == "TST_HD_sat_test"
                found_sat_hd = True
        assert found_sat_hd, "Satellite definition not found in export"

        # 5. Test Satellite naming in Generator (Logical resolution)
        gen_config = GenerationConfig(
            project_name=project.name,
            satellite_v0_naming=project.get_naming_pattern("satellite_v0_naming"),
            satellite_v1_naming=project.get_naming_pattern("satellite_v1_naming")
        )
        
        v0_name = gen_config.resolve_entity_name(gen_config.satellite_v0_naming, "sat_test")
        v1_name = gen_config.resolve_entity_name(gen_config.satellite_v1_naming, "sat_test")
        
        print(f"Resolved V0: {v0_name} (Expected: TST_sat_test_V0)")
        print(f"Resolved V1: {v1_name} (Expected: TST_sat_test_V1)")
        assert v0_name == "TST_sat_test_V0"
        assert v1_name == "TST_sat_test_V1"

        print("\nALL VERIFICATIONS PASSED!")
    finally:
        # Cleanup
        # project.delete() # Uncomment if you want to leave DB clean
        pass

if __name__ == "__main__":
    verify_naming()
