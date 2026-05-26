"""`turbovault generation-history` — list GenerationRun rows for a project."""

from __future__ import annotations

from typing import Annotated

import questionary
import typer
from rich.table import Table

from engine.cli.utils.console import console, print_error


def generation_history(
    project_name: Annotated[
        str | None,
        typer.Option("--project", "-p", help="Project to show history for"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Max rows to display"),
    ] = 20,
    output_type: Annotated[
        str | None,
        typer.Option(
            "--type", "-t",
            help="Filter to one output type: dbt | json | dbml",
        ),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive", "-i", help="Pick the project interactively"
        ),
    ] = False,
) -> None:
    """List generation runs for a project, newest first."""
    from engine.models import GenerationRun, Project

    if interactive or project_name is None:
        projects = list(Project.objects.order_by("name"))
        if not projects:
            print_error(
                "No projects exist. Create one with `turbovault project init`."
            )
            raise typer.Exit(2)
        if len(projects) == 1 and not interactive:
            project_name = projects[0].name
            console.print(
                f"[dim]Using the only project in this workspace: {project_name}[/dim]"
            )
        else:
            chosen = questionary.select(
                "Which project's generation history?",
                choices=[p.name for p in projects],
            ).ask()
            if not chosen:
                console.print("Cancelled.", style="warning")
                raise typer.Exit(0)
            project_name = chosen

    project = Project.objects.filter(name=project_name).first()
    if project is None:
        print_error(f"Project '{project_name}' not found.")
        raise typer.Exit(2)

    qs = GenerationRun.objects.filter(project=project).order_by("-started_at")
    if output_type:
        qs = qs.filter(output_type=output_type)
    runs = list(qs[:limit])
    if not runs:
        console.print("[yellow]No generation runs recorded for this project.[/yellow]")
        return

    table = Table(
        title=f"Generation history for '{project.name}'",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Started")
    table.add_column("Status")
    table.add_column("Type")
    table.add_column("Dry?")
    table.add_column("Mode")
    table.add_column("Files", justify="right")
    table.add_column("Errors", justify="right")
    table.add_column("Warnings", justify="right")
    table.add_column("ID", style="dim")

    status_colors = {
        "success": "green",
        "partial_success": "yellow",
        "failed": "red",
        "validation_failed": "red",
    }
    for run in runs:
        color = status_colors.get(run.status, "white")
        table.add_row(
            run.started_at.isoformat(timespec="seconds"),
            f"[{color}]{run.status}[/{color}]",
            run.output_type,
            "yes" if run.is_dry_run else "no",
            run.error_strategy,
            str(run.files_generated),
            str(run.error_count),
            str(run.warning_count),
            str(run.generation_run_id)[:8],
        )

    console.print(table)
