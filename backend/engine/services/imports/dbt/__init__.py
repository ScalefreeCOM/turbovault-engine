"""
Importing datavault4dbt projects from dbt artifacts.

- ``artifacts``: reading ``manifest.json`` (v12), ``catalog.json``,
  ``dbt_project.yml`` and the package files.
- ``extract``: rendering each model's Jinja in a sandbox that records its
  package macro calls, whatever notation the metadata uses.
- ``datavault4dbt``: resolving ``yaml_metadata`` and normalizing arguments
  the way datavault4dbt does.

See ``backend/docs/07_dbt_project_import_specification.md``.
"""
