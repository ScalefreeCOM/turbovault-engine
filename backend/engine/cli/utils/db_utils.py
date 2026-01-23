"""
Database utilities for TurboVault CLI.

Handles database initialization, migration checks, and automatic migration execution.
"""

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

if TYPE_CHECKING:
    from engine.models import Project

console = Console()


def create_default_snapshot_controls(project_or_name: "Project | str") -> None:
    """
    Create default snapshot control table and logic patterns for a project.

    Args:
        project_or_name: Either a Project object or project name string
    """
    from datetime import datetime, time

    from engine.models import Project, SnapshotControlLogic, SnapshotControlTable

    # Check if we should skip default snapshot creation
    if os.environ.get("TURBOVAULT_SKIP_DEFAULT_SNAPSHOTS", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        return

    # Get project
    if isinstance(project_or_name, str):
        try:
            project = Project.objects.get(project_name=project_or_name)
        except Project.DoesNotExist:
            return
    else:
        project = project_or_name

    # Check if snapshot controls already exist for this project
    if project.snapshot_controls.exists():
        return

    console.print(
        f"\n[cyan]ℹ️  Creating default snapshot controls for project '{project.name}'...[/cyan]"
    )

    try:
        # Create snapshot control table with default name
        snapshot_control = SnapshotControlTable.objects.create(
            project=project,
            name="control_snap_v0",  # Default name
            snapshot_start_date=datetime(2020, 1, 1).date(),
            snapshot_end_date=datetime(2099, 12, 31).date(),
            daily_snapshot_time=time(23, 59, 59),  # End of day
        )

        # Create common snapshot logic patterns
        snapshot_patterns = [
            {
                "snapshot_control_logic_column_name": "snap_daily",
                "snapshot_component": SnapshotControlLogic.SnapshotComponent.DAILY,
                "snapshot_duration": 1,
                "snapshot_unit": SnapshotControlLogic.SnapshotUnit.DAY,
                "snapshot_forever": False,
            },
            {
                "snapshot_control_logic_column_name": "snap_weekly",
                "snapshot_component": SnapshotControlLogic.SnapshotComponent.END_OF_WEEK,
                "snapshot_duration": 7,
                "snapshot_unit": SnapshotControlLogic.SnapshotUnit.DAY,
                "snapshot_forever": False,
            },
            {
                "snapshot_control_logic_column_name": "snap_monthly",
                "snapshot_component": SnapshotControlLogic.SnapshotComponent.END_OF_MONTH,
                "snapshot_duration": 1,
                "snapshot_unit": SnapshotControlLogic.SnapshotUnit.MONTH,
                "snapshot_forever": False,
            },
            {
                "snapshot_control_logic_column_name": "snap_quarterly",
                "snapshot_component": SnapshotControlLogic.SnapshotComponent.END_OF_QUARTER,
                "snapshot_duration": 3,
                "snapshot_unit": SnapshotControlLogic.SnapshotUnit.MONTH,
                "snapshot_forever": False,
            },
            {
                "snapshot_control_logic_column_name": "snap_yearly",
                "snapshot_component": SnapshotControlLogic.SnapshotComponent.END_OF_YEAR,
                "snapshot_duration": 1,
                "snapshot_unit": SnapshotControlLogic.SnapshotUnit.YEAR,
                "snapshot_forever": False,
            },
        ]

        created_count = 0
        for pattern in snapshot_patterns:
            SnapshotControlLogic.objects.create(
                snapshot_control_table=snapshot_control, **pattern
            )
            created_count += 1

        console.print(
            f"[dim]  Created snapshot control for project '{project.name}' with {created_count} logic patterns[/dim]"
        )
        console.print("[green]✓ Default snapshot controls ready[/green]\n")

    except Exception as e:
        console.print(f"[yellow]⚠️  Failed to create default snapshots: {e}[/yellow]")
        console.print(
            "[dim]You can create them manually in the admin interface[/dim]\n"
        )


def ensure_templates_populated() -> None:
    """
    Ensure template files are loaded into the database.

    Checks if ModelTemplate records exist, and if not, populates them
    from the file system template files. This runs automatically during
    project initialization.

    Can be disabled via TURBOVAULT_SKIP_TEMPLATE_POPULATION environment variable.
    """
    from engine.cli.utils.debug import debug_print

    debug_print("ensure_templates_populated() called")

    from engine.models.templates import ModelTemplate, TemplateCategory
    from engine.services.generation.template_resolver import TEMPLATES_DIR

    # Check if we should skip template population
    if os.environ.get("TURBOVAULT_SKIP_TEMPLATE_POPULATION", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        debug_print("Skipping template population (env var set)")
        return

    debug_print("Checking if templates exist in database...")
    # Check if templates already exist
    if ModelTemplate.objects.exists():
        debug_print("Templates already exist, returning")
        return

    console.print("\n[cyan]ℹ️  Populating database with template files...[/cyan]")

    try:
        # Get or create category
        category, _ = TemplateCategory.objects.get_or_create(
            name="File-based Defaults",
            defaults={"description": "Default templates from file system"},
        )

        sql_templates_dir = TEMPLATES_DIR / "sql"
        yaml_templates_dir = TEMPLATES_DIR / "yaml"

        created_count = 0

        # Valid entity types from ModelTemplate.EntityType
        valid_types = [choice[0] for choice in ModelTemplate.EntityType.choices]

        # Process SQL templates
        if sql_templates_dir.exists():
            for sql_file in sql_templates_dir.glob("*.sql.j2"):
                entity_type = sql_file.stem.removesuffix(".sql")
                if entity_type in valid_types:
                    content = sql_file.read_text(encoding="utf-8")
                    ModelTemplate.objects.create(
                        name=f"{entity_type} (SQL)",
                        entity_type=entity_type,
                        category=category,
                        description=f"Default SQL template for {entity_type}",
                        sql_template_content=content,
                        priority=0,
                        is_active=True,
                    )
                    created_count += 1

        # Process YAML templates
        if yaml_templates_dir.exists():
            for yaml_file in yaml_templates_dir.glob("*.yml.j2"):
                entity_type = yaml_file.stem.removesuffix(".yml")

                # Skip project-level files
                if entity_type in ["dbt_project", "packages", "sources"]:
                    continue

                if entity_type in valid_types:
                    content = yaml_file.read_text(encoding="utf-8")
                    # Check if SQL template exists for this entity
                    sql_template = ModelTemplate.objects.filter(
                        entity_type=entity_type, name=f"{entity_type} (SQL)"
                    ).first()

                    if sql_template:
                        # Update existing SQL template with YAML content
                        sql_template.yaml_template_content = content
                        sql_template.save()
                    else:
                        # Create YAML-only template
                        ModelTemplate.objects.create(
                            name=f"{entity_type} (YAML)",
                            entity_type=entity_type,
                            category=category,
                            description=f"Default YAML template for {entity_type}",
                            yaml_template_content=content,
                            priority=0,
                            is_active=True,
                        )
                    created_count += 1

        console.print(f"[dim]  Populated {created_count} template files[/dim]")
        console.print("[green]✓ Templates ready[/green]\n")

    except Exception as e:
        console.print(f"[yellow]⚠️  Failed to populate templates: {e}[/yellow]")
        console.print(
            "[dim]You can populate them manually with: python manage.py populate_templates[/dim]\n"
        )


def ensure_database_ready() -> None:
    """
    Ensure the database is initialized and all migrations are applied.

    This function:
    1. Checks if the database file exists (for SQLite)
    2. Creates and initializes the database if it doesn't exist
    3. Populates templates if needed

    Raises:
        SystemExit: If migrations fail to apply
    """
    from django.conf import settings

    from engine.cli.utils.debug import debug_print

    debug_print("ensure_database_ready() started")

    # For SQLite, check if database file exists
    db_config = settings.DATABASES["default"]
    is_sqlite = db_config["ENGINE"] == "django.db.backends.sqlite3"

    debug_print(f"Database engine: {db_config['ENGINE']}")

    if is_sqlite:
        db_path = Path(db_config["NAME"])
        db_exists = db_path.exists()
        debug_print(f"SQLite database exists: {db_exists}")

        if not db_exists:
            console.print("\n[yellow]⚠️  Database not found. Initializing...[/yellow]")
            _run_migrations(initial=True)
            console.print("[green]✓ Database initialized successfully[/green]\n")
            # Populate templates after initial setup
            ensure_templates_populated()
            debug_print("Returning after initial setup")
            return

    # Database exists - just ensure templates are populated
    debug_print("Database exists, ensuring templates are populated...")
    ensure_templates_populated()
    debug_print("ensure_database_ready() completed")


def _run_migrations(initial: bool = False) -> None:
    """
    Run Django migrations.

    Args:
        initial: If True, this is the first-time database setup

    Raises:
        SystemExit: If migrations fail
    """
    from io import StringIO

    from django.core.management import call_command

    try:
        # Capture output to avoid cluttering the console
        output = StringIO()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(
                (
                    "Applying migrations..."
                    if not initial
                    else "Creating database tables..."
                ),
                total=None,
            )

            # Run migrations with minimal output
            call_command(
                "migrate", verbosity=0, interactive=False, stdout=output, stderr=output
            )

            progress.update(task, completed=True)

        if initial:
            console.print("[dim]  Created all database tables[/dim]")
        else:
            console.print("[dim]  Applied all pending migrations[/dim]")

    except Exception as e:
        console.print(f"\n[red]✗ Migration failed: {e}[/red]")
        console.print("\n[yellow]Try running manually:[/yellow]")
        console.print("  cd backend")
        console.print("  python manage.py migrate")
        sys.exit(1)


def _ensure_superuser_exists() -> None:
    """
    Check if a superuser exists, and prompt to create one if not.

    This can be disabled via TURBOVAULT_SKIP_SUPERUSER_PROMPT environment variable.
    """
    import questionary
    from django.contrib.auth import get_user_model

    # Check if we should skip superuser creation
    if os.environ.get("TURBOVAULT_SKIP_SUPERUSER_PROMPT", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        return

    User = get_user_model()

    # Check if any superuser exists
    if User.objects.filter(is_superuser=True).exists():
        return

    console.print("\n[yellow]⚠️  No admin user found[/yellow]")

    create_superuser = questionary.confirm(
        "Would you like to create an admin user now?", default=True
    ).ask()

    if not create_superuser:
        console.print("[dim]You can create an admin user later with:[/dim]")
        console.print("  cd backend")
        console.print("  python manage.py createsuperuser\n")
        return

    _create_superuser_interactive()


def _create_superuser_interactive() -> None:
    """
    Interactively create a superuser account.
    """
    import questionary
    from django.contrib.auth import get_user_model
    from django.core import validators
    from django.core.exceptions import ValidationError

    User = get_user_model()

    console.print("\n[bold cyan]Create Admin User[/bold cyan]\n")

    # Username
    username = None
    while not username:
        username = questionary.text("Username:", default="admin").ask()

        if not username:
            console.print("[red]Username cannot be empty[/red]")
            continue

        # Check if username already exists
        if User.objects.filter(username=username).exists():
            console.print(f"[red]User '{username}' already exists[/red]")
            username = None

    # Email
    email = None
    while not email:
        email = questionary.text("Email address:", default="").ask()

        if email:
            # Validate email
            try:
                validators.validate_email(email)
            except ValidationError:
                console.print("[red]Invalid email address[/red]")
                email = None
        else:
            # Email is optional, but we'll use a placeholder
            email = ""
            break

    # Password
    password = None
    while not password:
        password = questionary.password(
            "Password:",
            validate=lambda x: len(x) >= 3 or "Password must be at least 3 characters",
        ).ask()

        if not password:
            continue

        # Confirm password
        password_confirm = questionary.password("Password (again):").ask()

        if password != password_confirm:
            console.print("[red]Passwords don't match. Try again.[/red]")
            password = None

    # Create the superuser
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Creating admin user...", total=None)

            _user = User.objects.create_superuser(
                username=username, email=email or "", password=password
            )

            progress.update(task, completed=True)

        console.print(f"[green]✓ Admin user '{username}' created successfully[/green]")
        console.print("\n[dim]You can now log in to the admin interface at:[/dim]")
        console.print("  http://127.0.0.1:8000/admin/\n")

    except Exception as e:
        console.print(f"[red]✗ Failed to create admin user: {e}[/red]")


def check_database_connection() -> bool:
    """
    Check if database connection is working.

    Returns:
        True if connection is successful, False otherwise
    """
    from django.db import connection

    try:
        connection.ensure_connection()
        return True
    except Exception as e:
        console.print(f"[red]Database connection failed: {e}[/red]")
        return False
