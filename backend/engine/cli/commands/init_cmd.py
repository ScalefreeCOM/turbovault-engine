"""
Init command for TurboVault CLI.

Initialize new projects from config or via CLI flags (non-interactive).
The --interactive flag launches a guided wizard when needed.
"""

import os
from pathlib import Path
from typing import Annotated

import questionary
import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from engine.cli.utils.console import (
    console,
    print_error,
    print_info,
    print_panel,
    print_step,
    print_success,
)
from engine.services.config_loader import ConfigValidationError, load_config_from_path


def init(
    # ── Config file shortcut ────────────────────────────────────────
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to a config.yml file. All other flags are ignored when this is set.",
            exists=True,
        ),
    ] = None,
    # ── Core project flags ──────────────────────────────────────────
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", help="Project name"),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", help="Optional project description"),
    ] = None,
    # ── Source metadata flags ────────────────────────────────────────
    source_path: Annotated[
        Path | None,
        typer.Option(
            "--source",
            "-s",
            help="Path to source metadata file (Excel .xlsx or SQLite .db)",
        ),
    ] = None,
    # ── Schema flags ─────────────────────────────────────────────────
    stage_schema: Annotated[
        str,
        typer.Option("--stage-schema", help="Staging layer schema name"),
    ] = "stage",
    rdv_schema: Annotated[
        str,
        typer.Option("--rdv-schema", help="Raw Data Vault schema name"),
    ] = "rdv",
    bdv_schema: Annotated[
        str,
        typer.Option("--bdv-schema", help="Business Vault schema name"),
    ] = "bdv",
    stage_database: Annotated[
        str | None,
        typer.Option("--stage-database", help="Optional staging database name"),
    ] = None,
    rdv_database: Annotated[
        str | None,
        typer.Option("--rdv-database", help="Optional RDV database name"),
    ] = None,
    bdv_database: Annotated[
        str | None,
        typer.Option("--bdv-database", help="Optional BDV database name"),
    ] = None,
    # ── Output flags ─────────────────────────────────────────────────
    output_dir: Annotated[
        str,
        typer.Option("--output", "-o", help="dbt project output directory"),
    ] = "./dbt_project",  # unused; kept for backward compat with --config files
    create_zip: Annotated[
        bool,
        typer.Option(
            "--zip/--no-zip", help="Create a ZIP archive of the generated dbt project"
        ),
    ] = False,
    # ── Naming pattern flags ─────────────────────────────────────────
    hashdiff_naming: Annotated[
        str | None,
        typer.Option(
            "--hashdiff-naming",
            help="Hashdiff naming pattern (e.g. 'hd_[[ satellite_name ]]')",
        ),
    ] = None,
    hashkey_naming: Annotated[
        str | None,
        typer.Option(
            "--hashkey-naming", help="Hashkey naming pattern (e.g. 'hd_[[ entity_name ]]')"
        ),
    ] = None,
    # ── Overwrite flag ───────────────────────────────────────────────
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite", help="Overwrite existing project without prompting"
        ),
    ] = False,
    # ── Interactive mode ─────────────────────────────────────────────
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", help="Run interactive setup wizard"),
    ] = False,
) -> None:
    """
    Create a new Data Vault project in the current workspace.

    The workspace must be initialised first:

      turbovault workspace init

    Three ways to use this command:

    1. From a config file:
       turbovault project init --config config.yml

    2. With flags (fully non-interactive, great for CI/scripts):
       turbovault project init --name my_project --source ./data.xlsx

    3. Interactive wizard:
       turbovault project init --interactive
    """
    from engine.services.app_config_loader import (
        WorkspaceNotFoundError,
        require_workspace,
    )

    try:
        require_workspace()
    except WorkspaceNotFoundError as e:
        console.print(f"\n[red]✗ {e}[/red]\n")
        raise typer.Exit(1)

    if config:
        _init_from_config(config, overwrite=overwrite)
    elif interactive:
        _run_interactive_init()
    elif name:
        _init_from_flags(
            name=name,
            description=description,
            source_path=source_path,
            stage_schema=stage_schema,
            rdv_schema=rdv_schema,
            bdv_schema=bdv_schema,
            stage_database=stage_database,
            rdv_database=rdv_database,
            bdv_database=bdv_database,
            output_dir=output_dir,
            create_zip=create_zip,
            hashdiff_naming=hashdiff_naming,
            hashkey_naming=hashkey_naming,
            overwrite=overwrite,
        )
    else:
        print_error("Please provide --name, --config, or --interactive")
        console.print("\n[bold]Examples:[/bold]")
        console.print(
            "  turbovault project init --name my_project --stage-schema stage --rdv-schema rdv",
            style="dim",
        )
        console.print(
            "  turbovault project init --name my_project --source ./metadata.xlsx",
            style="dim",
        )
        console.print("  turbovault project init --config config.yml", style="dim")
        console.print("  turbovault project init --interactive", style="dim")
        raise typer.Exit(1)


def _init_from_flags(
    *,
    name: str,
    description: str | None,
    source_path: Path | None,
    stage_schema: str,
    rdv_schema: str,
    bdv_schema: str,
    stage_database: str | None,
    rdv_database: str | None,
    bdv_database: str | None,
    output_dir: str,
    create_zip: bool,
    hashdiff_naming: str | None,
    hashkey_naming: str | None,
    overwrite: bool,
) -> None:
    """Build a TurboVaultConfig from CLI flags and delegate to shared init logic."""
    from engine.services.config_schema import (
        ExcelSourceConfig,
        OutputConfiguration,
        ProjectConfiguration,
        ProjectInfo,
        SqliteSourceConfig,
        TurboVaultConfig,
    )

    # Determine source config
    source_cfg = None
    if source_path:
        suffix = source_path.suffix.lower()
        if suffix in (".xlsx", ".xls"):
            source_cfg = ExcelSourceConfig(path=source_path)
        elif suffix in (".db", ".sqlite", ".sqlite3"):
            source_cfg = SqliteSourceConfig(path=source_path)
        else:
            print_error(
                f"Unsupported source file type '{suffix}'. Use .xlsx or .db/.sqlite."
            )
            raise typer.Exit(1)

    # Build naming extras
    naming_overrides: dict = {}
    if hashdiff_naming:
        naming_overrides["hashdiff_naming"] = hashdiff_naming
    if hashkey_naming:
        naming_overrides["hashkey_naming"] = hashkey_naming

    config = TurboVaultConfig(
        project=ProjectInfo(name=name, description=description or ""),
        source=source_cfg,
        configuration=ProjectConfiguration(
            stage_schema=stage_schema,
            rdv_schema=rdv_schema,
            bdv_schema=bdv_schema,
            stage_database=stage_database or None,
            rdv_database=rdv_database or None,
            bdv_database=bdv_database or None,
            **naming_overrides,
        ),
        output=OutputConfiguration(
            dbt_project_dir=output_dir,
            create_zip=create_zip,
        ),
    )

    _create_project(config, overwrite=overwrite)


def _init_from_config(config_path: Path, *, overwrite: bool = False) -> None:
    """Initialize project from a config.yml file."""
    print_step(1, 3, "Loading configuration...")

    try:
        config = load_config_from_path(config_path)
        print_success(f"Loaded config for project: {config.project.name}")
    except ConfigValidationError as e:
        print_error(f"Configuration validation failed:\n{str(e)}")
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to load config: {str(e)}")
        raise typer.Exit(1)

    _create_project(config, overwrite=overwrite)


def _create_project(config, *, overwrite: bool = False) -> None:
    """
    Core project creation logic shared by all init paths.

    Creates the Project DB record, project folder, snapshot controls,
    and optionally imports metadata from the configured source.
    """
    # Lazy import to avoid loading models before Django setup
    from engine.models import Project

    print_step(2, 3, "Creating project in database...")

    existing_project = Project.objects.filter(name=config.project.name).first()
    if existing_project:
        if overwrite:
            existing_project.delete()
            print_info("Existing project deleted")
        else:
            print_error(f"Project '{config.project.name}' already exists!")
            overwrite_confirm = questionary.confirm(
                "Do you want to delete the existing project and start fresh?",
                default=False,
            ).ask()

            if not overwrite_confirm:
                console.print("Initialization cancelled.", style="warning")
                raise typer.Exit(0)

            existing_project.delete()
            print_info("Existing project deleted")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Creating project...", total=None)
        project = Project.objects.create(
            name=config.project.name,
            description=config.project.description or "",
        )
        progress.update(task, completed=True)

    print_success(f"Created project: {project.name}")

    # Initialize project folder structure and create config.yml
    from engine.services.project_config import initialize_project_folder

    print_info("Creating project folder and config.yml...")
    try:
        project_path = initialize_project_folder(project, config)
        print_success(f"Project folder created: {project_path}")
    except Exception as e:
        print_error(f"Failed to create project folder: {e}")
        project.delete()
        raise typer.Exit(1)

    # Create default snapshot controls
    skip_snapshots = (
        os.getenv("TURBOVAULT_SKIP_DEFAULT_SNAPSHOTS", "").lower() == "true"
    )
    if not skip_snapshots:
        from engine.cli.utils.db_utils import create_default_snapshot_controls

        create_default_snapshot_controls(project)

    # Import metadata if source is defined
    if config.source:
        _import_metadata(project, config.source)

    print_step(3, 3, "Project initialization complete!")

    summary = f"""
[bold]Project:[/bold] {project.name}
[bold]Description:[/bold] {project.description or 'N/A'}
[bold]Source:[/bold] {f"{config.source.type} ({config.source.path})" if config.source else "None (start from scratch)"}
[bold]Stage Schema:[/bold] {config.configuration.stage_schema}
[bold]RDV Schema:[/bold] {config.configuration.rdv_schema}
[bold]BDV Schema:[/bold] {config.configuration.bdv_schema}
"""
    print_panel("Project Summary", summary.strip(), style="success")

    if config.source:
        print_info("Next step: Use the admin interface to review your imported model")
    else:
        print_info("Next step: Use Django admin to define your Data Vault model")
        console.print("  Run: turbovault serve", style="dim")


def _import_metadata(project, source) -> None:
    """Import metadata from Excel or SQLite source."""
    if source.type == "excel":
        from engine.services.excel_sqlite_adapter import ExcelImport

        print_info(f"Importing metadata from {source.path}...")
        try:
            service = ExcelImport(str(source.path))
            service.import_metadata(project=project, skip_snapshots=True)
            print_success("Metadata successfully imported")
        except Exception as e:
            print_error(f"Metadata import failed: {e}")

    elif source.type == "sqlite":
        import sqlite3

        from engine.services.sqlite_import import SqliteImportService

        print_info(f"Importing metadata from {source.path}...")
        try:
            conn = sqlite3.connect(str(source.path))
            service = SqliteImportService(conn)
            service.import_metadata(project=project, skip_snapshots=True)
            conn.close()
            print_success("Metadata successfully imported")
        except Exception as e:
            print_error(f"Metadata import failed: {e}")


def _run_interactive_init() -> None:
    """Run interactive project setup wizard."""
    from engine.services.config_schema import (
        ExcelSourceConfig,
        OutputConfiguration,
        ProjectConfiguration,
        ProjectInfo,
        SqliteSourceConfig,
        TurboVaultConfig,
    )

    console.print("\n[bold magenta]TurboVault Interactive Setup[/bold magenta]\n")

    project_name = questionary.text(
        "Project name:", validate=lambda x: len(x) > 0 or "Project name cannot be empty"
    ).ask()
    if not project_name:
        raise typer.Exit(0)

    description = questionary.text("Project description (optional):", default="").ask()

    # Source config
    import_metadata = questionary.confirm(
        "Import existing metadata?", default=False
    ).ask()

    source_cfg = None

    if import_metadata:
        source_type = questionary.select(
            "Select source type:",
            choices=[
                questionary.Choice("Excel file (.xlsx)", value="excel"),
                questionary.Choice("SQLite database (.db)", value="sqlite"),
            ],
        ).ask()

        if source_type == "excel":
            path = questionary.path("Path to Excel file:").ask()
            if path:
                source_cfg = ExcelSourceConfig(path=Path(path))
        elif source_type == "sqlite":
            path = questionary.path("Path to SQLite database (.db):").ask()
            if path:
                source_cfg = SqliteSourceConfig(path=Path(path))

    # Configuration defaults
    stage_schema = "stage"
    rdv_schema = "rdv"
    bdv_schema = "bdv"
    stage_database = None
    rdv_database = None
    create_zip = False
    naming_config: dict = {}

    modify_defaults = questionary.confirm(
        "Do you want to modify default settings (schema names, naming patterns)?",
        default=False,
    ).ask()

    if modify_defaults:
        stage_schema = questionary.text("Stage schema name:", default="stage").ask()
        stage_database = (
            questionary.text("Stage database (optional):", default="").ask() or None
        )
        rdv_schema = questionary.text("RDV schema name:", default="rdv").ask()
        rdv_database = (
            questionary.text("RDV database (optional):", default="").ask() or None
        )
        bdv_schema = questionary.text("BDV schema name:", default="bdv").ask()
        bdv_database = (
            questionary.text("BDV database (optional):", default="").ask() or None
        )

        # Removed dbt output directory prompt - defaults to ./dbt_project inside project folder

        create_zip = questionary.confirm(
            "Create ZIP archive of generated project?", default=False
        ).ask()

        overwrite_naming = questionary.confirm(
            "Do you want to overwrite default naming conventions?", default=False
        ).ask()

        if overwrite_naming:
            naming_config["hashdiff_naming"] = questionary.text(
                "Hashdiff naming pattern:", default="hd_[[ satellite_name ]]"
            ).ask()
            naming_config["hashkey_naming"] = questionary.text(
                "Hashkey naming pattern:", default="hd_[[ entity_name ]]"
            ).ask()
            naming_config["satellite_v0_naming"] = questionary.text(
                "Satellite V0 naming pattern:", default="[[ satellite_name ]]_v0"
            ).ask()
            naming_config["satellite_v1_naming"] = questionary.text(
                "Satellite V1 naming pattern:", default="[[ satellite_name ]]_v1"
            ).ask()

    # Build config object
    config = TurboVaultConfig(
        project=ProjectInfo(name=project_name, description=description),
        source=source_cfg,
        configuration=ProjectConfiguration(
            stage_schema=stage_schema,
            rdv_schema=rdv_schema,
            bdv_schema=bdv_schema,
            stage_database=stage_database,
            rdv_database=rdv_database,
            **naming_config,
        ),
        output=OutputConfiguration(
            dbt_project_dir="dbt_project",  # Default relative path
            create_zip=create_zip,
        ),
    )

    # Directly create project instead of writing config.yml first
    _create_project(config)
