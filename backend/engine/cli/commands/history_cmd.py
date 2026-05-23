"""`turbovault import-history` — list ImportRun rows for a project."""

from __future__ import annotations

from typing import Annotated

import questionary
import typer
from rich.table import Table

from engine.cli.utils.console import console, print_error


def import_history(
    project_name: Annotated[
        str | None,
        typer.Option("--project", "-p", help="Project to show history for"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Max rows to display"),
    ] = 20,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive", "-i", help="Pick the project interactively"
        ),
    ] = False,
) -> None:
    """List import runs for a project, newest first.

    Examples:
        turbovault import-history --project my_project
        turbovault import-history             # picks the project interactively
        turbovault import-history --interactive
    """
    from engine.models import ImportRun, Project

    # Drop into interactive selection if no project given or --interactive set.
    if interactive or project_name is None:
        projects = list(Project.objects.order_by("name"))
        if not projects:
            print_error(
                "No projects exist in this workspace. "
                "Create one first with `turbovault project init`."
            )
            raise typer.Exit(2)

        # If exactly one project exists and we weren't asked to be interactive,
        # use it without prompting.
        if len(projects) == 1 and not interactive:
            project_name = projects[0].name
            console.print(
                f"[dim]Using the only project in this workspace: {project_name}[/dim]"
            )
        else:
            chosen = questionary.select(
                "Which project's import history?",
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

    runs = list(
        ImportRun.objects.filter(project=project).order_by("-started_at")[:limit]
    )
    if not runs:
        console.print("[yellow]No import runs recorded for this project.[/yellow]")
        return

    table = Table(
        title=f"Import history for '{project.name}'",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Started")
    table.add_column("Status")
    table.add_column("Mode")
    table.add_column("Dry?")
    table.add_column("Source")
    table.add_column("Errors", justify="right")
    table.add_column("Warnings", justify="right")
    table.add_column("ID", style="dim")

    for run in runs:
        status_color = {
            "success": "green",
            "partial_success": "yellow",
            "failed": "red",
            "validation_failed": "red",
        }.get(run.status, "white")
        table.add_row(
            run.started_at.isoformat(timespec="seconds"),
            f"[{status_color}]{run.status}[/{status_color}]",
            run.conflict_strategy,
            "yes" if run.is_dry_run else "no",
            f"{run.source_type}: {run.source_name}",
            str(run.error_count),
            str(run.warning_count),
            str(run.import_run_id)[:8],
        )

    console.print(table)
