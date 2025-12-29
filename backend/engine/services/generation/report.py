"""
Generation report models for dbt project generation.

Provides dataclasses for tracking generation results, errors, and warnings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal


@dataclass
class GeneratedFile:
    """Represents a single generated file."""
    
    path: Path
    entity_type: str  # e.g., 'hub_standard', 'satellite_multi_active'
    entity_name: str  # e.g., 'hub_customer', 'sat_customer_details_v0'
    file_type: Literal["sql", "yaml"]
    
    @property
    def filename(self) -> str:
        """Get just the filename."""
        return self.path.name


@dataclass
class GenerationError:
    """Represents an error that occurred during generation."""
    
    entity_type: str
    entity_name: str
    message: str
    code: str = ""  # e.g., "HUB_001"
    
    def __str__(self) -> str:
        return f"[{self.entity_type}:{self.entity_name}] {self.message}"


@dataclass
class GenerationWarning:
    """Represents a warning during generation (non-fatal)."""
    
    entity_type: str
    entity_name: str
    message: str
    code: str = ""
    
    def __str__(self) -> str:
        return f"[{self.entity_type}:{self.entity_name}] {self.message}"


@dataclass
class SkippedEntity:
    """Represents an entity that was skipped during generation."""
    
    entity_type: str
    entity_name: str
    reason: str
    
    def __str__(self) -> str:
        return f"[{self.entity_type}:{self.entity_name}] Skipped: {self.reason}"


@dataclass
class GenerationReport:
    """
    Summary report of dbt project generation.
    
    Contains counts of generated entities, any errors/warnings,
    and the list of files that were created.
    """
    
    success: bool = True
    project_path: Path | None = None
    generated_at: datetime = field(default_factory=datetime.now)
    
    # Counts by entity type
    stages_generated: int = 0
    hubs_generated: int = 0
    links_generated: int = 0
    satellites_generated: int = 0  # _v0 models only
    satellite_views_generated: int = 0  # _v1 models only
    pits_generated: int = 0
    reference_tables_generated: int = 0
    snapshot_controls_generated: int = 0
    
    # Generated files
    files: list[GeneratedFile] = field(default_factory=list)
    
    # Issues
    errors: list[GenerationError] = field(default_factory=list)
    warnings: list[GenerationWarning] = field(default_factory=list)
    skipped: list[SkippedEntity] = field(default_factory=list)
    
    @property
    def total_files(self) -> int:
        """Total number of files generated."""
        return len(self.files)
    
    @property
    def total_entities(self) -> int:
        """Total number of entities generated."""
        return (
            self.stages_generated +
            self.hubs_generated +
            self.links_generated +
            self.satellites_generated +
            self.satellite_views_generated +
            self.pits_generated +
            self.reference_tables_generated +
            self.snapshot_controls_generated
        )
    
    def add_file(
        self,
        path: Path,
        entity_type: str,
        entity_name: str,
        file_type: Literal["sql", "yaml"]
    ) -> None:
        """Add a generated file to the report."""
        self.files.append(GeneratedFile(
            path=path,
            entity_type=entity_type,
            entity_name=entity_name,
            file_type=file_type
        ))
    
    def add_error(
        self,
        entity_type: str,
        entity_name: str,
        message: str,
        code: str = ""
    ) -> None:
        """Add an error to the report."""
        self.errors.append(GenerationError(
            entity_type=entity_type,
            entity_name=entity_name,
            message=message,
            code=code
        ))
        self.success = False
    
    def add_warning(
        self,
        entity_type: str,
        entity_name: str,
        message: str,
        code: str = ""
    ) -> None:
        """Add a warning to the report."""
        self.warnings.append(GenerationWarning(
            entity_type=entity_type,
            entity_name=entity_name,
            message=message,
            code=code
        ))
    
    def add_skipped(
        self,
        entity_type: str,
        entity_name: str,
        reason: str
    ) -> None:
        """Add a skipped entity to the report."""
        self.skipped.append(SkippedEntity(
            entity_type=entity_type,
            entity_name=entity_name,
            reason=reason
        ))
    
    def validate_yaml_files(self) -> None:
        """
        Check that every SQL file has a corresponding YAML file.
        
        Adds warnings for any SQL files that don't have YAML counterparts.
        This should be called after generation is complete.
        """
        # Group files by entity name
        sql_files: dict[str, GeneratedFile] = {}
        yaml_files: set[str] = set()
        
        for file in self.files:
            if file.file_type == "sql":
                sql_files[file.entity_name] = file
            elif file.file_type == "yaml":
                yaml_files.add(file.entity_name)
        
        # Check for missing YAML files
        for entity_name, sql_file in sql_files.items():
            # Skip project-level files that don't need YAML
            if sql_file.entity_type == "project":
                continue
            
            if entity_name not in yaml_files:
                self.add_warning(
                    entity_type=sql_file.entity_type,
                    entity_name=entity_name,
                    message=f"SQL file generated but YAML file is missing: {sql_file.path.name}",
                    code="YML_001"
                )
    
    def summary(self) -> str:
        """Get a human-readable summary of the generation."""
        lines = [
            f"Generation {'succeeded' if self.success else 'failed'}",
            f"Generated at: {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Project path: {self.project_path}",
            "",
            "Entities generated:",
            f"  - Stages: {self.stages_generated}",
            f"  - Hubs: {self.hubs_generated}",
            f"  - Links: {self.links_generated}",
            f"  - Satellites (v0): {self.satellites_generated}",
            f"  - Satellite views (v1): {self.satellite_views_generated}",
            f"  - PITs: {self.pits_generated}",
            f"  - Reference tables: {self.reference_tables_generated}",
            f"  - Snapshot controls: {self.snapshot_controls_generated}",
            "",
            f"Total files: {self.total_files}",
        ]
        
        if self.errors:
            lines.append(f"\nErrors ({len(self.errors)}):")
            for error in self.errors:
                lines.append(f"  - {error}")
        
        if self.warnings:
            lines.append(f"\nWarnings ({len(self.warnings)}):")
            for warning in self.warnings:
                lines.append(f"  - {warning}")
        
        if self.skipped:
            lines.append(f"\nSkipped ({len(self.skipped)}):")
            for skipped in self.skipped:
                lines.append(f"  - {skipped}")
        
        return "\n".join(lines)
