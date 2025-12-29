"""
File writer utilities for dbt project generation.

Provides simple utilities for writing SQL and YAML files to the dbt project.
"""
from __future__ import annotations

from pathlib import Path


def write_file(path: Path, content: str) -> None:
    """
    Write content to a file, creating parent directories if needed.
    
    Args:
        path: Path to the file to write
        content: Content to write to the file
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_sql_file(path: Path, content: str) -> None:
    """
    Write a SQL file with proper formatting.
    
    Args:
        path: Path to the SQL file (should end with .sql)
        content: SQL content to write
    """
    # Ensure .sql extension
    if not path.suffix == ".sql":
        path = path.with_suffix(".sql")
    
    # Strip trailing whitespace from lines and ensure single trailing newline
    lines = [line.rstrip() for line in content.splitlines()]
    formatted_content = "\n".join(lines).strip() + "\n"
    
    write_file(path, formatted_content)


def write_yaml_file(path: Path, content: str) -> None:
    """
    Write a YAML file with proper formatting.
    
    Args:
        path: Path to the YAML file (should end with .yml)
        content: YAML content to write
    """
    # Ensure .yml extension
    if path.suffix not in (".yml", ".yaml"):
        path = path.with_suffix(".yml")
    
    # Strip trailing whitespace from lines and ensure single trailing newline
    lines = [line.rstrip() for line in content.splitlines()]
    formatted_content = "\n".join(lines).strip() + "\n"
    
    write_file(path, formatted_content)
