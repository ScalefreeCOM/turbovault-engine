"""
Init command for TurboVault CLI.

Initialize new projects from config or interactively.
"""

import os
from pathlib import Path

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
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Path to config.yml file", exists=True
    ),
    interactive: bool = typer.Option(
        False, "--interactive", "-i", help="Run interactive setup wizard"
    ),
) -> None:
    """
    Initialize a new TurboVault project.

    Create a new project in the Django database from a config file
    or using an interactive setup wizard.
    """

    if interactive:
        _run_interactive_init()
    elif config:
        _init_from_config(config)
    else:
        print_error("Please provide either --config or --interactive")
        print_info("Examples:")
        console.print("  turbovault init --config config.yml", style="dim")
        console.print("  turbovault init --interactive", style="dim")
        raise typer.Exit(1)


def _init_from_config(config_path: Path) -> None:
    """Initialize project from config file."""
    # Lazy import to avoid loading models before Django setup
    from engine.models import Project

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

    print_step(2, 3, "Creating project in database...")

    # Check if project already exists
    existing_project = Project.objects.filter(name=config.project.name).first()
    if existing_project:
        print_error(f"Project '{config.project.name}' already exists!")

        overwrite = questionary.confirm(
            "Do you want to delete the existing project and start fresh?", default=False
        ).ask()

        if not overwrite:
            console.print("Initialization cancelled.", style="warning")
            raise typer.Exit(0)

        # Delete existing project
        existing_project.delete()
        print_info("Existing project deleted")

    # Create new project
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Creating project...", total=None)

        project = Project.objects.create(
            name=config.project.name,
            description=config.project.description or "",
            config={},  # We'll store additional config here later
        )

        progress.update(task, completed=True)

    print_success(f"Created project: {project.name}")

    # Create default snapshot controls for the new project
    skip_snapshots = (
        os.getenv("TURBOVAULT_SKIP_DEFAULT_SNAPSHOTS", "").lower() == "true"
    )
    if not skip_snapshots:
        from engine.cli.utils.db_utils import create_default_snapshot_controls

        create_default_snapshot_controls(project)

    # Import metadata if source is defined
    if config.source and config.source.type == "excel":
        from engine.services.excel_import import ExcelImportService
        print_info(f"Importing metadata from {config.source.path}...")
        try:
            service = ExcelImportService(str(config.source.path))
            service.import_metadata(project=project, skip_snapshots=True)
            print_success("Metadata successfully imported")
        except Exception as e:
            print_error(f"Metadata import failed: {e}")

    # Ensure templates are populated in database
    from engine.cli.utils.db_utils import ensure_templates_populated

    ensure_templates_populated()

    print_step(3, 3, "Project initialization complete!")

    # Show summary
    summary = f"""
[bold]Project:[/bold] {project.name}
[bold]Description:[/bold] {project.description or 'N/A'}
[bold]Source:[/bold] {f'Excel ({config.source.path})' if config.source else 'None (start from scratch)'}
[bold]Stage Schema:[/bold] {config.configuration.stage_schema}
[bold]RDV Schema:[/bold] {config.configuration.rdv_schema}
[bold]Output:[/bold] {config.output.dbt_project_dir}
"""

    print_panel("Project Summary", summary.strip(), style="success")

    if config.source:
        print_info("Next step: Use the admin interface to review your imported model")
    else:
        print_info("Next step: Use Django admin to define your Data Vault model")
        console.print("  Run: turbovault serve", style="dim")


def _run_interactive_init() -> None:
    """Run interactive project setup wizard."""
    # Lazy import to avoid loading models before Django setup
    import yaml

    from engine.models import Project

    console.print("\n[bold magenta]TurboVault Interactive Setup[/bold magenta]\n")

    # Project name
    project_name = questionary.text(
        "Project name:", validate=lambda x: len(x) > 0 or "Project name cannot be empty"
    ).ask()

    if not project_name:
        raise typer.Exit(0)

    # Project description
    description = questionary.text("Project description (optional):", default="").ask()

    # Source type
    use_source = questionary.confirm("Import metadata from Excel?", default=False).ask()

    source_path = None
    if use_source:
        source_path = questionary.path("Path to Excel file:").ask()

    # Stage schema
    stage_schema = questionary.text("Stage schema name:", default="stage").ask()

    # Stage database
    stage_database = questionary.text("Stage database (optional):", default="").ask()

    # RDV schema
    rdv_schema = questionary.text("RDV schema name:", default="rdv").ask()

    # RDV database
    rdv_database = questionary.text("RDV database (optional):", default="").ask()

    # Output directory
    output_dir = questionary.text(
        "dbt project output directory:", default="./generated/dbt_project"
    ).ask()

    # Create ZIP
    create_zip = questionary.confirm(
        "Create ZIP archive of generated project?", default=False
    ).ask()

    # Generate config dictionary
    config_dict = {
        "project": {
            "name": project_name,
        },
        "configuration": {
            "stage_schema": stage_schema,
            "rdv_schema": rdv_schema,
        },
        "output": {"dbt_project_dir": output_dir, "create_zip": create_zip},
    }

    # Add optional fields
    if description:
        config_dict["project"]["description"] = description

    if source_path:
        config_dict["source"] = {"type": "excel", "path": source_path}

    if stage_database:
        config_dict["configuration"]["stage_database"] = stage_database

    if rdv_database:
        config_dict["configuration"]["rdv_database"] = rdv_database

    # Save config.yml
    config_file = Path("config.yml")

    # Check if file exists
    if config_file.exists():
        overwrite = questionary.confirm(
            "config.yml already exists. Overwrite?", default=False
        ).ask()

        if not overwrite:
            # Generate alternative name
            counter = 1
            while config_file.exists():
                config_file = Path(f"config_{counter}.yml")
                counter += 1
            print_info(f"Using alternative filename: {config_file}")

    with open(config_file, "w") as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)

    print_success(f"Created config file: {config_file}")

    # Create project
    print_step(1, 2, "Creating project in database...")

    # Check if project already exists
    existing_project = Project.objects.filter(name=project_name).first()
    if existing_project:
        print_error(f"Project '{project_name}' already exists!")

        overwrite = questionary.confirm(
            "Do you want to delete the existing project and start fresh?", default=False
        ).ask()

        if not overwrite:
            console.print("Initialization cancelled.", style="warning")
            raise typer.Exit(0)

        # Delete existing project
        existing_project.delete()
        print_info("Existing project deleted")

    project = Project.objects.create(
        name=project_name,
        description=description or "",
        config={
            "stage_schema": stage_schema,
            "rdv_schema": rdv_schema,
            "source_path": str(source_path) if source_path else None,
        },
    )

    print_success(f"Created project: {project.name}")

    # Import metadata if source is defined
    if source_path:
        from engine.services.excel_import import ExcelImportService
        print_info(f"Importing metadata from {source_path}...")
        try:
            service = ExcelImportService(str(source_path))
            service.import_metadata(project=project, skip_snapshots=True)
            print_success("Metadata successfully imported")
        except Exception as e:
            print_error(f"Metadata import failed: {e}")

    # Create default snapshot controls for the new project
    skip_snapshots = (
        os.getenv("TURBOVAULT_SKIP_DEFAULT_SNAPSHOTS", "").lower() == "true"
    )
    if not skip_snapshots:
        from engine.cli.utils.db_utils import create_default_snapshot_controls

        create_default_snapshot_controls(project)

    # Ensure templates are populated in database
    from engine.cli.utils.db_utils import ensure_templates_populated

    ensure_templates_populated()

    print_step(2, 2, "Setup complete!")
    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  • Review/edit your config: {config_file}", style="info")
    if source_path:
        console.print("  • Run 'turbovault serve' to review imported metadata", style="info")
    else:
        console.print("  • Run 'turbovault serve' to start the admin interface", style="info")
        console.print("  • Use the admin to define your Data Vault model", style="info")
    console.print(
        f"  • Re-run with: turbovault init --config {config_file}", style="dim"
    )
