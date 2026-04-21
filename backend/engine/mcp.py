"""
TurboVault MCP tools.

Autodiscovered by django-mcp-server on startup (mirrors the admin.py pattern).
Available at http://localhost:8000/mcp when `turbovault serve` is running.

Configure in Claude Code / Claude Desktop:
    {
      "mcpServers": {
        "turbovault": {
          "type": "http",
          "url": "http://localhost:8000/mcp"
        }
      }
    }
"""

from __future__ import annotations

import json

from mcp_server import MCPToolset


class TurboVaultToolset(MCPToolset):
    """MCP tools for Data Vault modeling with TurboVault."""

    # ── Workspace & project ───────────────────────────────────────────────────

    def workspace_status(self) -> dict:
        """
        Return workspace health, database connection, and project count.

        Use this to verify the TurboVault workspace is properly configured
        before running other tools.
        """
        from engine.models import Project
        from engine.services.app_config_loader import (
            WorkspaceNotFoundError,
            find_turbovault_config,
            load_application_config,
        )

        try:
            config_path = find_turbovault_config()
            app_config = load_application_config()
            project_count = Project.objects.count()
            db_cfg = app_config.database
            engine_val = db_cfg.engine if db_cfg else "sqlite3"
            return {
                "status": "ok",
                "workspace": str(config_path.parent) if config_path else None,
                "database_engine": engine_val.value if hasattr(engine_val, "value") else str(engine_val),
                "project_count": project_count,
            }
        except WorkspaceNotFoundError as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def project_list(self) -> list[dict]:
        """
        List all projects in the current workspace.

        Returns name, description, and schema configuration for each project.
        """
        from engine.models import Project

        projects = Project.objects.all().order_by("name")
        return [
            {
                "name": p.name,
                "description": p.description,
                "stage_schema": p.get_schema("stage"),
                "rdv_schema": p.get_schema("rdv"),
                "bdv_schema": p.get_schema("bdv"),
            }
            for p in projects
        ]

    def project_create(
        self,
        name: str,
        source_path: str,
        description: str = "",
        stage_schema: str = "stage",
        rdv_schema: str = "rdv",
        bdv_schema: str = "bdv",
    ) -> dict:
        """
        Create a new Data Vault project by importing source metadata.

        Args:
            name: Project name (must be unique in this workspace).
            source_path: Absolute path to source file (.xlsx, .db, or exported .json).
            description: Optional project description.
            stage_schema: Staging schema name (default: stage).
            rdv_schema: Raw Data Vault schema name (default: rdv).
            bdv_schema: Business Data Vault schema name (default: bdv).

        Returns status, project name, and entity counts after import.
        """
        from pathlib import Path

        from engine.cli.commands.init_cmd import _create_project
        from engine.services.config_schema import ProjectConfiguration, SourceType

        src = Path(source_path)
        if not src.exists():
            return {"status": "error", "message": f"Source file not found: {source_path}"}

        suffix = src.suffix.lower()
        if suffix == ".xlsx":
            from engine.services.config_schema import ExcelSourceConfig
            source_cfg = ExcelSourceConfig(path=src)
        elif suffix in (".db", ".sqlite", ".sqlite3"):
            from engine.services.config_schema import SqliteSourceConfig
            source_cfg = SqliteSourceConfig(path=src)
        elif suffix == ".json":
            from engine.services.config_schema import JsonSourceConfig
            source_cfg = JsonSourceConfig(path=src)
        else:
            return {"status": "error", "message": f"Unsupported source type: {suffix}"}

        config = ProjectConfiguration(
            name=name,
            description=description or None,
            source=source_cfg,
            stage_schema=stage_schema,
            rdv_schema=rdv_schema,
            bdv_schema=bdv_schema,
        )

        try:
            project = _create_project(config, overwrite=False)
            from engine.models import Hub, Link, Satellite
            return {
                "status": "ok",
                "project": project.name,
                "hubs": Hub.objects.filter(project=project).count(),
                "links": Link.objects.filter(project=project).count(),
                "satellites": Satellite.objects.filter(project=project).count(),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    # ── Model inspection ──────────────────────────────────────────────────────

    def list_entities(
        self,
        project_name: str,
        entity_type: str = "all",
    ) -> dict:
        """
        List Data Vault entities (hubs, links, satellites, PITs) in a project.

        Args:
            project_name: Name of the project to inspect.
            entity_type: One of 'hubs', 'links', 'satellites', 'pits', or 'all'.

        Returns a dict with one list per entity type requested.
        """
        from engine.models import Hub, Link, PIT, Project, Satellite

        try:
            project = Project.objects.get(name=project_name)
        except Project.DoesNotExist:
            return {"error": f"Project '{project_name}' not found"}

        result: dict = {}
        show_all = entity_type == "all"

        if show_all or entity_type == "hubs":
            result["hubs"] = [
                {
                    "name": h.hub_physical_name,
                    "type": h.hub_type,
                    "hashkey": h.hub_hashkey_name,
                    "business_keys": list(
                        h.columns.filter(column_type="business_key")
                        .values_list("column_name", flat=True)
                    ),
                }
                for h in Hub.objects.filter(project=project).order_by("hub_physical_name")
            ]

        if show_all or entity_type == "links":
            result["links"] = [
                {
                    "name": lnk.link_physical_name,
                    "type": lnk.link_type,
                    "hashkey": lnk.link_hashkey_name,
                    "hubs": list(
                        lnk.hub_references.values_list(
                            "hub__hub_physical_name", flat=True
                        )
                    ),
                }
                for lnk in Link.objects.filter(project=project).order_by(
                    "link_physical_name"
                )
            ]

        if show_all or entity_type == "satellites":
            result["satellites"] = [
                {
                    "name": sat.satellite_physical_name,
                    "type": sat.satellite_type,
                    "parent_hub": sat.parent_hub.hub_physical_name
                    if sat.parent_hub
                    else None,
                    "parent_link": sat.parent_link.link_physical_name
                    if sat.parent_link
                    else None,
                }
                for sat in Satellite.objects.filter(project=project).order_by(
                    "satellite_physical_name"
                )
            ]

        if show_all or entity_type == "pits":
            result["pits"] = [
                {
                    "name": pit.pit_physical_name,
                    "tracked_type": pit.tracked_entity_type,
                    "tracked_entity": pit.tracked_hub.hub_physical_name
                    if pit.tracked_hub
                    else (
                        pit.tracked_link.link_physical_name if pit.tracked_link else None
                    ),
                    "satellites": list(
                        pit.satellites.values_list(
                            "satellite_physical_name", flat=True
                        )
                    ),
                }
                for pit in PIT.objects.filter(project=project).order_by(
                    "pit_physical_name"
                )
            ]

        return result

    # ── Model building ────────────────────────────────────────────────────────

    def propose_model_from_source(self, source_tables: list[dict]) -> dict:
        """
        Return the ModelImportSchema structure for the given source tables.

        This tool does NOT write anything. It returns the empty proposal schema
        and a description of each source table so that you (the LLM) can reason
        about the Data Vault model and fill in the proposal, which you can then
        pass to commit_model.

        Data Vault naming conventions:
        - Hubs: HUB_<ENTITY> with business keys (natural identifiers)
        - Links: LNK_<ENTITY1>_<ENTITY2> connecting two or more hubs
        - Satellites: SAT_<ENTITY>_<CONTEXT> capturing descriptive attributes
        - Reference data (small lookup tables) → reference hub type

        Args:
            source_tables: List of source table descriptions, each with:
                - name (str): physical table name
                - columns (list[dict]): each with 'name', 'type', optionally 'is_pk'
                - record_source (str, optional): source system identifier
                - load_date_column (str, optional): column used as load date

        Returns the proposal schema template and source table summaries.
        """
        from engine.services.model_import_schema import ModelImportSchema

        schema_example = {
            "hubs": [
                {
                    "name": "HUB_<ENTITY>",
                    "business_keys": ["<natural_key_column>"],
                    "hashkey": "hk_<entity>",
                    "hub_type": "standard",
                }
            ],
            "links": [
                {
                    "name": "LNK_<ENTITY1>_<ENTITY2>",
                    "hubs": ["HUB_<ENTITY1>", "HUB_<ENTITY2>"],
                    "link_type": "standard",
                }
            ],
            "satellites": [
                {
                    "name": "SAT_<ENTITY>_<CONTEXT>",
                    "parent_hub": "HUB_<ENTITY>",
                    "satellite_type": "standard",
                    "columns": ["<descriptive_col1>", "<descriptive_col2>"],
                }
            ],
            "reasoning": "<explain your modeling decisions here>",
            "reference_candidates": ["<column_names_that_look_like_lookup_data>"],
        }

        return {
            "instructions": (
                "Analyse the source_tables below and produce a Data Vault model proposal "
                "matching the schema_template. Then call commit_model with your proposal."
            ),
            "schema_template": schema_example,
            "source_tables": source_tables,
        }

    def commit_model(self, project_name: str, proposal: dict) -> dict:
        """
        Write an approved model proposal into the TurboVault project.

        The proposal must match the ModelImportSchema format (same structure
        returned by propose_model_from_source's schema_template). Existing
        entities with the same name are skipped (idempotent).

        Args:
            project_name: Target project name.
            proposal: Dict matching ModelImportSchema — keys: hubs, links,
                      satellites, reasoning (optional), reference_candidates (optional).

        Returns import counts and any skipped/error messages.
        """
        from pydantic import ValidationError

        from engine.services.model_import_schema import ModelImportSchema
        from engine.services.model_import_service import import_model

        try:
            schema = ModelImportSchema.model_validate(proposal)
        except ValidationError as exc:
            return {"status": "error", "message": f"Invalid proposal: {exc}"}

        result = import_model(project_name, schema)

        return {
            "status": "ok" if result.success else "error",
            "hubs_created": result.hubs_created,
            "links_created": result.links_created,
            "satellites_created": result.satellites_created,
            "skipped": result.skipped,
            "errors": result.errors,
        }

    # ── Validation & generation ───────────────────────────────────────────────

    def validate_model(self, project_name: str) -> dict:
        """
        Validate the Data Vault model for a project.

        Checks entity completeness rules (hashkeys, business keys, parent
        entities, etc.) and returns any errors or warnings.

        Args:
            project_name: Name of the project to validate.

        Returns validation status, error list, and warning list.
        """
        from engine.models import Project
        from engine.services.export.builder import ModelBuilder
        from engine.services.generation.validators import validate_export

        try:
            project = Project.objects.get(name=project_name)
        except Project.DoesNotExist:
            return {"status": "error", "message": f"Project '{project_name}' not found"}

        try:
            export = ModelBuilder(project).build()
        except Exception as exc:
            return {"status": "error", "message": f"Failed to build export: {exc}"}

        result = validate_export(export)
        return {
            "valid": result.is_valid,
            "errors": [
                {
                    "code": e.code,
                    "entity_type": e.entity_type,
                    "entity": e.entity_name,
                    "message": e.message,
                }
                for e in result.errors
            ],
            "warnings": [
                {
                    "code": w.code,
                    "entity_type": w.entity_type,
                    "entity": w.entity_name,
                    "message": w.message,
                }
                for w in result.warnings
            ],
        }

    def export_model_json(self, project_name: str) -> dict:
        """
        Export the current Data Vault model as a JSON object.

        Returns the full ProjectExport representation including all hubs,
        links, satellites, stages, PITs, and source mappings. This is the
        same format that can be re-imported via project_create.

        Args:
            project_name: Name of the project to export.
        """
        from engine.models import Project
        from engine.services.export.builder import ModelBuilder
        from engine.services.export.exporters.json_exporter import JSONExporter

        try:
            project = Project.objects.get(name=project_name)
        except Project.DoesNotExist:
            return {"error": f"Project '{project_name}' not found"}

        try:
            export = ModelBuilder(project).build()
            json_str = JSONExporter(indent=2).export(export)
            return json.loads(json_str)
        except Exception as exc:
            return {"error": str(exc)}

    def generate_dbt(
        self,
        project_name: str,
        output_path: str | None = None,
        mode: str = "strict",
        dry_run: bool = False,
    ) -> dict:
        """
        Generate a complete dbt project from the Data Vault model.

        Args:
            project_name: Name of the project to generate.
            output_path: Absolute path for output directory (uses project default if omitted).
            mode: Validation mode — 'strict' (stop on error) or 'lenient' (skip invalid).
            dry_run: If true, validate only — no files written. Returns counts and issues.

        Returns generation report with file counts, errors, and output path.
        """
        from pathlib import Path

        from engine.models import Project
        from engine.services.export.builder import ModelBuilder
        from engine.services.generation import DbtProjectGenerator, GenerationConfig
        from engine.services.generation.validators import validate_export

        try:
            project = Project.objects.get(name=project_name)
        except Project.DoesNotExist:
            return {"status": "error", "message": f"Project '{project_name}' not found"}

        try:
            export = ModelBuilder(project).build()
        except Exception as exc:
            return {"status": "error", "message": f"Failed to build export: {exc}"}

        validation = validate_export(export)

        if dry_run:
            return {
                "status": "dry_run",
                "valid": validation.is_valid,
                "hubs": len(export.hubs),
                "links": len(export.links),
                "satellites": len(export.satellites),
                "stages": len(export.stages),
                "pits": len(export.pits),
                "errors": [str(e) for e in validation.errors],
                "warnings": [str(w) for w in validation.warnings],
            }

        if not validation.is_valid and mode == "strict":
            return {
                "status": "error",
                "message": "Validation failed (use mode='lenient' to skip invalid entities)",
                "errors": [str(e) for e in validation.errors],
            }

        resolved_output = Path(output_path) if output_path else None
        if not resolved_output:
            from engine.services.app_config_loader import resolve_project_path
            try:
                project_dir = resolve_project_path(project.project_directory)
                resolved_output = project_dir / "exports" / "dbt_project"
            except Exception:
                resolved_output = Path(f"./exports/{project_name}/dbt_project")
        resolved_output.mkdir(parents=True, exist_ok=True)

        config = GenerationConfig(
            project_name=project_name.lower().replace(" ", "_"),
            profile_name="default",
            mode=mode,
            stage_schema=project.get_schema("stage"),
            rdv_schema=project.get_schema("rdv"),
            bdv_schema=project.get_schema("bdv"),
        )

        try:
            report = DbtProjectGenerator(output_path=resolved_output, config=config).generate(export)
            return {
                "status": "ok" if report.success else "error",
                "output_path": str(resolved_output.absolute()),
                "total_files": report.total_files,
                "hubs_generated": report.hubs_generated,
                "links_generated": report.links_generated,
                "satellites_generated": report.satellites_generated,
                "pits_generated": report.pits_generated,
                "errors": report.errors[:10],
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
