import os
import sys

import django
import pandas as pd

sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "turbovault.settings")
django.setup()

from engine.models.links import Link
from engine.services.excel_import import ExcelImportService


class DebugImportService(ExcelImportService):
    def _process_standard_links(self, df: pd.DataFrame):
        # Hijack this method to print debug info before calling super (or copying logic)
        # Actually, let's just inspect the dataframe here for L0003
        df.columns = [c.lower() for c in df.columns]

        print("\n--- DEBUG: _process_standard_links DataFrame (L0003) ---")
        l0003_rows = df[df["target_link_table_physical_name"] == "nation_test_link"]
        print(
            l0003_rows[
                [
                    "target_link_table_physical_name",
                    "hub_identifier",
                    "prejoin_target_column_alias",
                    "prejoin_extraction_column_name",
                ]
            ].to_string()
        )

        # Call original (but we need to access _extractions first)
        pass


def debug_keys():
    file_path = r"c:\Users\tkirschke_scalefree\repos\turbovault-engine\turbovault-engine\TurboVault TPCH Data.xlsx"
    service = ExcelImportService(file_path)

    print("--- Running Import ---")
    import uuid

    project_name = f"Debug Keys {uuid.uuid4()}"
    project = service.import_metadata(project_name=project_name)

    print("\n--- Captured Prejoin Extraction Keys ---")
    keys = [k for k in service._extractions.keys() if "nation_test_link" in k]
    for k in keys:
        print(f"Key: '{k}' -> {service._extractions[k]}")

    # Now verify what we got in DB
    print("\n--- Database Results ---")
    link = Link.objects.get(project=project, link_physical_name="nation_test_link")
    for ref in link.hub_references.all():
        print(f"Hub Ref: {ref.hub.hub_physical_name}")
        for m in ref.source_mappings.all():
            src_str = "NONE"
            if m.prejoin_extraction_column:
                src_str = f"PREJOIN {m.prejoin_extraction_column.prejoin_extraction_column_name}"
            elif m.source_column:
                src_str = f"SOURCE {m.source_column.source_column_physical_name}"
            print(f"  Mapping {m.standard_hub_column.column_name} -> {src_str}")


if __name__ == "__main__":
    debug_keys()
