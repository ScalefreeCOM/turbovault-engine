import os
import sys

import django

sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")
django.setup()

from engine.models.links import Link
from engine.services.excel_import import ExcelImportService


def verify_l0003():
    file_path = r"c:\Users\tkirschke_scalefree\repos\turbovault-engine\turbovault-engine\TurboVault TPCH Data.xlsx"
    import uuid

    project_name = f"Test Prejoin Checks {uuid.uuid4()}"

    service = ExcelImportService(file_path)
    project = service.import_metadata(project_name=project_name)

    link = Link.objects.get(project=project, link_physical_name="nation_test_link")
    found_hub_region = False
    success_mapping = False

    print(f"Checking Link: {link.link_physical_name}")
    for ref in link.hub_references.all():
        if ref.hub.hub_physical_name == "Region_h":
            found_hub_region = True
            print("Found Reference to Region_h")
            for m in ref.source_mappings.all():
                print(f"  Mapping for {m.standard_hub_column.column_name}:")
                if m.prejoin_extraction_column:
                    print(
                        f"    -> PREJOIN Extraction: {m.prejoin_extraction_column.prejoin_extraction_column_name}"
                    )
                    success_mapping = True
                if m.source_column:
                    print(
                        f"    -> SOURCE Column: {m.source_column.source_column_physical_name}"
                    )

    if found_hub_region and success_mapping:
        print("VERIFICATION SUCCESS: Region_h mapped via PREJOIN.")
    else:
        print(
            "VERIFICATION FAILURE: Region_h NOT mapped via PREJOIN (or Hub not found)."
        )

    # Debug: Extractions related to this link
    keys = [k for k in service._extractions.keys() if "nation_test_link" in k]
    print(f"Extractions for link: {keys}")


if __name__ == "__main__":
    verify_l0003()
