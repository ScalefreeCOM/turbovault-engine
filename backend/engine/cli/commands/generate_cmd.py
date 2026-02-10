"""
Generate command for TurboVault CLI.

Generate a complete dbt project from Data Vault model.
"""

import zipfile
from pathlib import Path
from typing import Annotated

import questionary
import typer

from engine.cli.utils.console import (
    console,
    print_error,
    print_info,
    print_panel,
    print_step,
    print_success,
    print_warning,
)


def generate(
    project_name: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="Project name (interactive selection if not provided)",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Output directory path (default: ./output/{project_name})",
        ),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            "-m",
            help="Validation mode: 'strict' (stop on error) or 'lenient' (skip invalid)",
        ),
    ] = "strict",
    create_zip: Annotated[
        bool, typer.Option("--zip", "-z", help="Create ZIP archive after generation")
    ] = False,
    skip_validation: Annotated[
        bool, typer.Option("--skip-validation", help="Skip pre-generation validation")
    ] = False,
    no_v1_satellites: Annotated[
        bool,
        typer.Option("--no-v1-satellites", help="Skip generating satellite _v1 views"),
    ] = False,
    type: Annotated[
        str | None,
        typer.Option(
            "--type",
            "-t",
            help="Export type: 'dbt' or 'json' (interactive if not provided)",
        ),
    ] = None,
    json_output: Annotated[
        Path | None,
        typer.Option(
            "--json-output",
            help="JSON output file path (only for type=json, auto-generated if not provided)",
        ),
    ] = None,
    json_format: Annotated[
        str,
        typer.Option(
            "--json-format",
            help="JSON format: 'compact' or 'pretty' (only for type=json)",
        ),
    ] = "pretty",
    dbml_output: Annotated[
        Path | None,
        typer.Option(
            "--dbml-output",
            help="DBML output file path (only for type=dbml, auto-generated if not provided)",
        ),
    ] = None,
) -> None:
    """
    Generate a complete dbt project from Data Vault model.

    Creates a ready-to-use dbt project with all models (stages, hubs, links,
    satellites, PITs, reference tables) using datavault4dbt macros.

    Can also export the Data Vault model as JSON using --type json.
    """
    from engine.cli.utils.debug import debug_print

    debug_print("generate() function called")

    # Lazy imports to avoid loading before Django setup
    from engine.models import Project
    from engine.services.export.builder import ModelBuilder
    from engine.services.generation import DbtProjectGenerator, GenerationConfig
    from engine.services.generation.validators import validate_export

    debug_print("Imports complete")

    # Interactive type selection if not provided
    if not type:
        type = questionary.select(
            "Select export type:",
            choices=[
                questionary.Choice("dbt - Generate dbt project", value="dbt"),
                questionary.Choice(
                    "json - Export Data Vault model to JSON", value="json"
                ),
                questionary.Choice(
                    "dbml - Export Data Vault ER diagram to DBML", value="dbml"
                ),
            ],
        ).ask()

        if not type:
            raise typer.Exit(0)

    # Validate type
    if type not in ("dbt", "json", "dbml"):
        print_error(f"Invalid type: {type}. Must be 'dbt', 'json', or 'dbml'.")
        raise typer.Exit(1)

    # Validate JSON format
    if json_format not in ("compact", "pretty"):
        print_error(
            f"Invalid JSON format: {json_format}. Must be 'compact' or 'pretty'."
        )
        raise typer.Exit(1)

    # Validate mode
    if mode not in ("strict", "lenient"):
        print_error(f"Invalid mode: {mode}. Must be 'strict' or 'lenient'.")
        raise typer.Exit(1)

    # Determine what we're doing
    should_export_json = type == "json"
    should_export_dbml = type == "dbml"
    should_generate_dbt = type == "dbt"

    # Get available projects
    projects = list(Project.objects.all().order_by("name"))

    if not projects:
        print_error("No projects found in database!")
        print_info("Create a project first with: turbovault init")
        raise typer.Exit(1)

    # Select project
    selected_project = _select_project(projects, project_name)
    if not selected_project:
        raise typer.Exit(0)

    # Determine output path for dbt if needed
    if should_generate_dbt and not output:
        safe_name = selected_project.name.lower().replace(" ", "_")
        output = Path("./output") / safe_name

    # Calculate total steps
    total_steps = 2  # Build + Complete
    if should_export_json:
        total_steps += 1  # JSON export step
    if should_export_dbml:
        total_steps += 1  # DBML export step
    if should_generate_dbt:
        if not skip_validation:
            total_steps += 1  # Validation step
        total_steps += 1  # Generation step

    current_step = 0

    # Build export
    current_step += 1
    print_step(
        current_step,
        total_steps,
        f"Building export for project: [bold]{selected_project.name}[/bold]",
    )

    try:
        builder = ModelBuilder(selected_project)
        project_export = builder.build()
    except Exception as e:
        print_error(f"Failed to build export: {e}")
        raise typer.Exit(1)

    # JSON Export (if type is json)
    json_file_path = None
    if should_export_json:
        current_step += 1
        json_file_path = _export_json(
            current_step,
            total_steps,
            project_export,
            selected_project,
            json_output,
            json_format,
        )

        # JSON-only: show summary and return
        current_step += 1
        print_step(current_step, total_steps, "Export complete!")
        _show_json_only_summary(project_export, json_file_path)
        print_success(f"JSON export saved to: {json_file_path}")
        return

    # DBML Export (if type is dbml)
    dbml_file_path = None
    if should_export_dbml:
        current_step += 1
        dbml_file_path = _export_dbml(
            current_step,
            total_steps,
            project_export,
            selected_project,
            dbml_output,
        )

        # DBML-only: show summary and return
        current_step += 1
        print_step(current_step, total_steps, "Export complete!")
        _show_json_only_summary(project_export, dbml_file_path)
        print_success(f"DBML export saved to: {dbml_file_path}")
        return

    # From here on, we're generating dbt
    # Validate (only if generating dbt)
    if not skip_validation:
        current_step += 1
        print_step(current_step, total_steps, "Validating export data...")
        validation_result = validate_export(project_export)

        # Show warnings
        if validation_result.warnings:
            print_warning(f"Found {len(validation_result.warnings)} warning(s):")
            for warning in validation_result.warnings:
                console.print(f"  [yellow]⚠[/yellow] {warning}")

        # Handle errors
        if not validation_result.is_valid:
            print_error(f"Found {len(validation_result.errors)} validation error(s):")
            for error in validation_result.errors:
                console.print(f"  [red]✗[/red] {error}")

            if mode == "strict":
                print_error("Generation aborted due to validation errors (strict mode)")
                print_info("Use --mode lenient to skip invalid entities and continue")
                raise typer.Exit(1)
            else:
                print_warning("Continuing with valid entities only (lenient mode)")
    else:
        current_step += 1
        print_step(current_step, total_steps, "Skipping validation (--skip-validation)")

    # Configure generator
    current_step += 1
    print_step(current_step, total_steps, "Generating dbt project...")

    config = GenerationConfig(
        project_name=selected_project.name.lower().replace(" ", "_"),
        profile_name="default",
        mode=mode,  # type: ignore
        generate_satellite_v1_views=not no_v1_satellites,
        satellite_v0_naming=selected_project.get_naming_pattern("satellite_v0_naming"),
        satellite_v1_naming=selected_project.get_naming_pattern("satellite_v1_naming"),
        skip_validation=skip_validation,
        create_zip=create_zip,
    )

    # Generate dbt project
    try:
        generator = DbtProjectGenerator(
            output_path=output,
            config=config,
        )
        report = generator.generate(project_export)
    except Exception as e:
        print_error(f"Generation failed: {e}")
        raise typer.Exit(1)

    # Create ZIP if requested
    zip_path = None
    if create_zip and report.success:
        zip_path = _create_zip_archive(output)

    # Show results
    current_step += 1
    print_step(current_step, total_steps, "Generation complete!")

    _show_summary(report, output, zip_path, no_v1_satellites)

    if report.success:
        print_success(f"dbt project generated at: {output.absolute()}")
        if zip_path:
            print_success(f"ZIP archive created: {zip_path}")
    else:
        print_error("Generation completed with errors")
        raise typer.Exit(1)


def _export_json(
    current_step: int,
    total_steps: int,
    project_export,
    selected_project,
    json_output: Path | None,
    json_format: str,
) -> Path:
    """Export the project model to JSON and return the file path."""
    from datetime import datetime

    from engine.services.export.exporters.json_exporter import JSONExporter

    print_step(current_step, total_steps, "Exporting to JSON format...")

    # Determine indent based on format
    indent = 2 if json_format == "pretty" else None

    exporter = JSONExporter(indent=indent)
    export_content = exporter.export(project_export)

    # Generate default filename if not provided
    if not json_output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = (
            f"{selected_project.name.lower().replace(' ', '_')}_export_{timestamp}.json"
        )
        json_output = Path(filename)

    # Write to file
    json_output.parent.mkdir(parents=True, exist_ok=True)
    with open(json_output, "w") as f:
        f.write(export_content)

    return json_output


def _export_dbml(
    current_step: int,
    total_steps: int,
    project_export,
    selected_project,
    dbml_output: Path | None,
) -> Path:
    """Export the project model to DBML and return the file path."""
    from datetime import datetime

    from engine.services.export.exporters.dbml_exporter import DBMLExporter

    print_step(current_step, total_steps, "Exporting to DBML format (ER diagram)...")

    exporter = DBMLExporter()
    export_content = exporter.export(project_export)

    # Generate default filename if not provided
    if not dbml_output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = (
            f"{selected_project.name.lower().replace(' ', '_')}_erd_{timestamp}.dbml"
        )
        dbml_output = Path(filename)

    # Write to file
    dbml_output.parent.mkdir(parents=True, exist_ok=True)
    with open(dbml_output, "w") as f:
        f.write(export_content)

    return dbml_output


def _show_json_only_summary(project_export, json_path: Path) -> None:
    """Display summary for JSON-only export."""
    summary = f"""
[bold]Project:[/bold] {project_export.project_name}
[bold]Sources:[/bold] {len(project_export.sources)} system(s)
[bold]Hubs:[/bold] {len(project_export.hubs)} hub(s)
[bold]Links:[/bold] {len(project_export.links)} link(s)
[bold]Satellites:[/bold] {len(project_export.satellites)} satellite(s)
[bold]Stages:[/bold] {len(project_export.stages)} stage(s)
[bold]Exported to:[/bold] {json_path.absolute()}
"""
    print_panel("Export Summary", summary.strip(), style="success")


def _select_project(projects: list, project_name: str | None):
    """Select a project by name or interactively."""
    from engine.models import Project

    if project_name:
        # Use provided project name
        selected = Project.objects.filter(name=project_name).first()
        if not selected:
            print_error(f"Project '{project_name}' not found!")
            available = ", ".join(p.name for p in projects)
            print_info(f"Available projects: {available}")
            raise typer.Exit(1)
        return selected
    elif len(projects) == 1:
        # Only one project, use it
        print_info(f"Using project: {projects[0].name}")
        return projects[0]
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

        return questionary.select(
            "Select project to generate:", choices=project_choices
        ).ask()


def _create_zip_archive(output_path: Path) -> Path:
    """Create a ZIP archive of the generated dbt project."""
    zip_path = output_path.with_suffix(".zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file in output_path.rglob("*"):
            if file.is_file():
                arcname = file.relative_to(output_path.parent)
                zipf.write(file, arcname)

    return zip_path


def _show_summary(
    report, output_path: Path, zip_path: Path | None, no_v1: bool
) -> None:
    """Display generation summary."""
    status = "[green]✓ Success[/green]" if report.success else "[red]✗ Failed[/red]"

    # Build entity counts
    entity_lines = [
        f"[bold]Stages:[/bold] {report.stages_generated}",
        f"[bold]Hubs:[/bold] {report.hubs_generated}",
        f"[bold]Links:[/bold] {report.links_generated}",
        f"[bold]Satellites (v0):[/bold] {report.satellites_generated}",
    ]

    if not no_v1:
        entity_lines.append(
            f"[bold]Satellite views (v1):[/bold] {report.satellite_views_generated}"
        )

    entity_lines.extend(
        [
            f"[bold]PITs:[/bold] {report.pits_generated}",
            f"[bold]Reference tables:[/bold] {report.reference_tables_generated}",
            f"[bold]Snapshot controls:[/bold] {report.snapshot_controls_generated}",
        ]
    )

    summary_content = f"""
{status}

[bold]Output path:[/bold] {output_path.absolute()}
[bold]Total files:[/bold] {report.total_files}

{chr(10).join(entity_lines)}
"""

    if zip_path:
        summary_content += f"\n[bold]ZIP archive:[/bold] {zip_path}"

    # Show errors if any
    if report.errors:
        summary_content += f"\n\n[red]Errors ({len(report.errors)}):[/red]"
        for error in report.errors[:5]:  # Show first 5
            summary_content += f"\n  • {error}"
        if len(report.errors) > 5:
            summary_content += f"\n  ... and {len(report.errors) - 5} more"

    # Show skipped if any
    if report.skipped:
        summary_content += f"\n\n[yellow]Skipped ({len(report.skipped)}):[/yellow]"
        for skipped in report.skipped[:5]:
            summary_content += f"\n  • {skipped}"
        if len(report.skipped) > 5:
            summary_content += f"\n  ... and {len(report.skipped) - 5} more"

    print_panel(
        "Generation Summary",
        summary_content.strip(),
        style="success" if report.success else "error",
    )
