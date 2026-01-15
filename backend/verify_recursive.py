import os
import sys

import django

# Setup Django standalone
sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")
django.setup()

from engine.models.links import Link
from engine.services.excel_import import ExcelImportService


def verify_recursive_link():
    file_path = r"c:\Users\tkirschke_scalefree\repos\turbovault-engine\turbovault-engine\TurboVault TPCH Data.xlsx"
    print(f"Importing from: {file_path}")

    # Run Import
    try:
        service = ExcelImportService(file_path)
        import uuid

        project_name = f"Test Recursive {uuid.uuid4()}"
        project = service.import_metadata(
            project_name=project_name, description="Test Recursive Link"
        )
        print(f"Imported Project: {project.name}")

        link_name = "customer_duplicate_customer_l"
        link = Link.objects.filter(
            project=project, link_physical_name=link_name
        ).first()

        if not link:
            print(f"Link {link_name} not found!")
            return

        print(f"Found Link: {link.link_physical_name}")
        refs = link.hub_references.all().order_by("sort_order", "link_hub_reference_id")
        print(f"Reference Count: {refs.count()}")

        for ref in refs:
            print(
                f"  Ref to Hub: {ref.hub.hub_physical_name} (ID: {ref.hub.hub_physical_name})"
            )
            print(f"  Alias in Link: '{ref.hub_hashkey_alias_in_link}'")
            print(f"  Sort Order: {ref.sort_order}")

            for m in ref.source_mappings.all():
                src = (
                    m.source_column.source_column_physical_name
                    if m.source_column
                    else (
                        m.prejoin_extraction_column.prejoin_extraction_column_name
                        if m.prejoin_extraction_column
                        else "None"
                    )
                )
                print(f"    Mapping: {m.standard_hub_column.column_name} <- {src}")

        # Validation Logic:
        # Check if we have multiple references (Scenario B) or one (Scenario A)
        distinct_aliases = {ref.hub_hashkey_alias_in_link for ref in refs}
        if len(refs) > 1 and len(distinct_aliases) > 1:
            print(
                "CONCLUSION: Scenario B detected (Multiple References with different roles)."
            )
        elif len(refs) == 1 and refs[0].source_mappings.count() > 1:
            print(
                "CONCLUSION: Scenario A detected (Single Reference with multiple mappings/composite key)."
            )
        else:
            print("CONCLUSION: Uncertain or Mixed Scenario.")

    except Exception as e:
        print(f"Error during verification: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    verify_recursive_link()
