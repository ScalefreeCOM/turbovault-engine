"""
Generate command for TurboVault CLI.

Generate a complete dbt project from Data Vault model.
"""
from pathlib import Path
from typing import Optional
import shutil
import zipfile

import questionary
import typer
from typing_extensions import Annotated

from engine.cli.utils.console import (
    console, print_success, print_error, print_info, print_warning,
    print_step, print_panel
)


def generate(
    project_name: Annotated[Optional[str], typer.Option(
        "--project", "-p",
        help="Project name (interactive selection if not provided)"
    )] = None,
    output: Annotated[Optional[Path], typer.Option(
        "--output", "-o",
        help="Output directory path (default: ./output/{project_name})"
    )] = None,
    mode: Annotated[str, typer.Option(
        "--mode", "-m",
        help="Validation mode: 'strict' (stop on error) or 'lenient' (skip invalid)"
    )] = "strict",
    create_zip: Annotated[bool, typer.Option(
        "--zip", "-z",
        help="Create ZIP archive after generation"
    )] = False,
    skip_validation: Annotated[bool, typer.Option(
        "--skip-validation",
        help="Skip pre-generation validation"
    )] = False,
    no_v1_satellites: Annotated[bool, typer.Option(
        "--no-v1-satellites",
        help="Skip generating satellite _v1 views"
    )] = False,
) -> None:
    """
    Generate a complete dbt project from Data Vault model.
    
    Creates a ready-to-use dbt project with all models (stages, hubs, links,
    satellites, PITs, reference tables) using datavault4dbt macros.
    """
    # Lazy imports to avoid loading before Django setup
    from engine.models import Project
    from engine.services.export.builder import ModelBuilder
    from engine.services.generation import DbtProjectGenerator, GenerationConfig
    from engine.services.generation.validators import validate_export
    
    # Validate mode
    if mode not in ("strict", "lenient"):
        print_error(f"Invalid mode: {mode}. Must be 'strict' or 'lenient'.")
        raise typer.Exit(1)
    
    # Get available projects
    projects = list(Project.objects.all().order_by('name'))
    
    if not projects:
        print_error("No projects found in database!")
        print_info("Create a project first with: turbovault init")
        raise typer.Exit(1)
    
    # Select project
    selected_project = _select_project(projects, project_name)
    if not selected_project:
        raise typer.Exit(0)
    
    # Determine output path
    if not output:
        safe_name = selected_project.name.lower().replace(" ", "_")
        output = Path("./output") / safe_name
    
    # Build export
    print_step(1, 5, f"Building export for project: [bold]{selected_project.name}[/bold]")
    
    try:
        builder = ModelBuilder(selected_project)
        project_export = builder.build()
    except Exception as e:
        print_error(f"Failed to build export: {e}")
        raise typer.Exit(1)
    
    # Validate
    if not skip_validation:
        print_step(2, 5, "Validating export data...")
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
        print_step(2, 5, "Skipping validation (--skip-validation)")
    
    # Configure generator
    print_step(3, 5, "Configuring generator...")
    
    config = GenerationConfig(
        project_name=selected_project.name.lower().replace(" ", "_"),
        profile_name="default",
        mode=mode,  # type: ignore
        generate_satellite_v1_views=not no_v1_satellites,
        skip_validation=skip_validation,
        create_zip=create_zip,
    )
    
    # Generate dbt project
    print_step(4, 5, f"Generating dbt project to: [bold]{output}[/bold]")
    
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
    print_step(5, 5, "Generation complete!")
    
    _show_summary(report, output, zip_path, no_v1_satellites)
    
    if report.success:
        print_success(f"dbt project generated at: {output.absolute()}")
        if zip_path:
            print_success(f"ZIP archive created: {zip_path}")
    else:
        print_error("Generation completed with errors")
        raise typer.Exit(1)


def _select_project(projects: list, project_name: Optional[str]):
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
                title=f"{p.name}" + (f" - {p.description[:50]}..." if p.description and len(p.description) > 50 else f" - {p.description}" if p.description else ""),
                value=p
            )
            for p in projects
        ]
        
        return questionary.select(
            "Select project to generate:",
            choices=project_choices
        ).ask()


def _create_zip_archive(output_path: Path) -> Path:
    """Create a ZIP archive of the generated dbt project."""
    zip_path = output_path.with_suffix(".zip")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in output_path.rglob('*'):
            if file.is_file():
                arcname = file.relative_to(output_path.parent)
                zipf.write(file, arcname)
    
    return zip_path


def _show_summary(report, output_path: Path, zip_path: Optional[Path], no_v1: bool) -> None:
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
        entity_lines.append(f"[bold]Satellite views (v1):[/bold] {report.satellite_views_generated}")
    
    entity_lines.extend([
        f"[bold]PITs:[/bold] {report.pits_generated}",
        f"[bold]Reference tables:[/bold] {report.reference_tables_generated}",
        f"[bold]Snapshot controls:[/bold] {report.snapshot_controls_generated}",
    ])
    
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
    
    print_panel("Generation Summary", summary_content.strip(), style="success" if report.success else "error")
