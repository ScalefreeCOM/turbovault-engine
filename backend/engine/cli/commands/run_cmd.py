"""
Run command for TurboVault CLI.

Generate Data Vault model export from stored metadata.
"""

from pathlib import Path

import questionary
import typer

from engine.cli.utils.console import (
    print_error,
    print_info,
    print_panel,
    print_step,
    print_success,
    print_warning,
)


def run(
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Path to config.yml file (optional)"
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output file path (auto-generated if not provided)"
    ),
    format: str = typer.Option(
        "json", "--format", "-f", help="Output format: json (more coming soon)"
    ),
    project_name: str | None = typer.Option(
        None,
        "--project",
        "-p",
        help="Project name (interactive selection if not provided)",
    ),
) -> None:
    """
    Generate Data Vault model export to file.

    Exports your Data Vault model from the database to a structured file.
    If no output path is specified, creates a timestamped file in the current directory.
    Currently supports JSON output; dbt/DBML/SQL coming in future versions.
    """
    # Lazy imports to avoid loading before Django setup
    from engine.models import Project
    from engine.services.export.builder import ModelBuilder
    from engine.services.export.exporters.json_exporter import JSONExporter

    # Get available projects
    projects = list(Project.objects.all().order_by("name"))

    if not projects:
        print_error("No projects found in database!")
        print_info("Create a project first with: turbovault init")
        raise typer.Exit(1)

    # Select project
    selected_project = None

    if project_name:
        # Use provided project name
        selected_project = Project.objects.filter(name=project_name).first()
        if not selected_project:
            print_error(f"Project '{project_name}' not found!")
            available = ", ".join(p.name for p in projects)
            print_info(f"Available projects: {available}")
            raise typer.Exit(1)
    elif len(projects) == 1:
        # Only one project, use it
        selected_project = projects[0]
        print_info(f"Using project: {selected_project.name}")
    else:
        # Interactive selection
        project_choices = [
            questionary.Choice(
                title=f"{p.name}"
                + (
                    f" - {p.description[:50]}..."
                    if p.description and len(p.description) > 50
                    else f" - {p.description}" if p.description else ""
                ),
                value=p,
            )
            for p in projects
        ]

        selected_project = questionary.select(
            "Select project to export:", choices=project_choices
        ).ask()

        if not selected_project:
            raise typer.Exit(0)

    # Validate format
    supported_formats = ["json"]
    if format.lower() not in supported_formats:
        print_error(f"Unsupported format: {format}")
        print_info(f"Supported formats: {', '.join(supported_formats)}")
        raise typer.Exit(1)

    # Build export
    print_step(1, 3, f"Building export for project: {selected_project.name}")

    # Load config if provided to get export options
    export_sources = True
    generate_tests = True
    generate_dbml = False

    if config:
        from engine.services.config_loader import load_config_from_path

        try:
            config_obj = load_config_from_path(config)
            export_sources = config_obj.output.export_sources
            generate_tests = config_obj.output.generate_tests
            generate_dbml = config_obj.output.generate_dbml
        except Exception as e:
            print_warning(f"Could not load config: {e}. Using defaults.")

    try:
        builder = ModelBuilder(selected_project)
        project_export = builder.build(
            export_sources=export_sources,
            generate_tests=generate_tests,
            generate_dbml=generate_dbml,
        )
    except Exception as e:
        print_error(f"Failed to build export: {e}")
        raise typer.Exit(1)

    # Export to format
    print_step(2, 3, f"Exporting to {format.upper()} format...")

    exporter = JSONExporter(indent=2)
    export_content = exporter.export(project_export)

    # Output
    print_step(3, 3, "Export complete!")

    # Generate default filename if not provided
    if not output:
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = (
            f"{selected_project.name.lower().replace(' ', '_')}_export_{timestamp}.json"
        )
        output = Path(filename)

    # Write to file
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        f.write(export_content)

    # Show summary
    summary = f"""
[bold]Project:[/bold] {project_export.project_name}
[bold]Sources:[/bold] {len(project_export.sources)} system(s)
[bold]Hubs:[/bold] {len(project_export.hubs)} hub(s)
[bold]Links:[/bold] {len(project_export.links)} link(s)
[bold]Satellites:[/bold] {len(project_export.satellites)} satellite(s)
[bold]Stages:[/bold] {len(project_export.stages)} stage(s)
[bold]Exported to:[/bold] {output.absolute()}
"""
    print_panel("Export Summary", summary.strip(), style="success")
    print_success(f"Export saved to: {output.absolute()}")
