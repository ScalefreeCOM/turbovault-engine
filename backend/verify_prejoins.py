import os
import sys

import django
import pandas as pd

# Setup Django standalone
sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")
django.setup()

from engine.models.links import Link
from engine.services.excel_import import ExcelImportService


def verify_prejoin_mapping():
    file_path = r"c:\Users\tkirschke_scalefree\repos\turbovault-engine\turbovault-engine\TurboVault TPCH Data.xlsx"
    print(f"Importing from: {file_path}")

    service = ExcelImportService(file_path)
    # Peek at Excel data for L0003
    df = pd.read_excel(file_path, sheet_name="standard_link")
    df.columns = [c.lower() for c in df.columns]

    l0003_rows = df[df["target_link_table_physical_name"] == "nation_test_link"]
    print("\n--- L0003 Raw Data Sample (Region_h rows) ---")
    for _, row in l0003_rows.iterrows():
        hub = row.get("hub_identifier")
        if hub == "Region_h":
            print(f"Hub: {hub}")
            print(f"  Prejoin Table: {row.get('prejoin_table_identifier')}")
            print(f"  Prejoin Alias: {row.get('prejoin_target_column_alias')}")
            print(f"  Extraction Col: {row.get('prejoin_extraction_column_name')}")
            print(f"  Source Col: {row.get('source_column_physical_name')}")

    # Run full import
    import uuid

    project_name = f"Test Prejoin {uuid.uuid4()}"
    project = service.import_metadata(
        project_name=project_name, description="Test Prejoin"
    )

    # Inspect _extractions keys related to L0003
    print("\n--- Captured Extractions ---")
    keys_found = [k for k in service._extractions.keys() if "nation_test_link" in k]
    print(f"Keys matching 'nation_test_link': {keys_found}")

    # Check Database Result
    link = Link.objects.get(project=project, link_physical_name="nation_test_link")
    print(f"\nChecking Link: {link.link_physical_name}")

    success = False
    for ref in link.hub_references.all():
        print(f"Reference to {ref.hub.hub_physical_name}:")
        for m in ref.source_mappings.all():
            src_str = "NONE"
            if m.prejoin_extraction_column:
                src_str = f"PREJOIN {m.prejoin_extraction_column.prejoin_extraction_column_name}"
                if ref.hub.hub_physical_name == "Region_h":
                    success = True
            elif m.source_column:
                src_str = f"SOURCE {m.source_column.source_column_physical_name}"

            print(f"  Mapping {m.standard_hub_column.column_name} -> {src_str}")

    if success:
        print("\nSUCCESS: Region_h mapped via PREJOIN extraction.")
    else:
        print("\nFAILURE: Region_h NOT mapped via PREJOIN.")


if __name__ == "__main__":
    verify_prejoin_mapping()
