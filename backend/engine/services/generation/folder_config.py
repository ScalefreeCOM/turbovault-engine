"""
Folder configuration for dbt project generation.

Defines the directory structure for generated dbt projects and provides
utilities for creating folders and resolving paths.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Where each kind of model goes: patterns relative to the dbt project, like
# the naming patterns (spec D27). [[ group ]] and [[ source_system ]] stand for
# the entity's group and its source system as folder names (lowercase, spaces
# and dashes as underscores); [[ group_name ]] and [[ source_system_name ]] as
# they are spelled. A stage's source system is its table's; an entity's that
# of its (primary) source tables (main_source_system). A part whose
# placeholder has no value (an entity without a group) is left out. The
# defaults are TurboVault's layer folders (D12).
DEFAULT_FOLDERS: dict[str, str] = {
    "control": "models/00_control",
    "sources": "models/10_sources",
    "prestaging": "models/15_prestaging",
    "staging": "models/20_staging/[[ source_system ]]",
    "raw_vault": "models/30_raw_vault/[[ group ]]",
    "business_vault": "models/40_business_vault",
    "pit": "models/40_business_vault/pits/[[ group ]]",
}
# Layers: dbt_project.yml configures each on the fixed part of its pattern.
LAYERS = ("control", "sources", "prestaging", "staging", "raw_vault", "business_vault")
# Kinds of model with a pattern of their own; without one, their layer's.
KIND_LAYERS: dict[str, str] = {
    "stage": "staging",
    "hub": "raw_vault",
    "link": "raw_vault",
    "satellite": "raw_vault",
    "satellite_v1": "raw_vault",
    "effectivity_satellite": "raw_vault",
    "record_tracking_satellite": "raw_vault",
    "reference_table": "raw_vault",
    "pit": "business_vault",
    "snapshot_control": "control",
}
FOLDER_KEYS = frozenset(LAYERS) | frozenset(KIND_LAYERS)
FOLDER_PLACEHOLDERS = frozenset(
    {"group", "group_name", "source_system", "source_system_name"}
)
_PLACEHOLDER = re.compile(r"\[\[\s*(\w+)\s*\]\]")


def main_source_system(systems: Iterable[str | None]) -> str | None:
    """The source system an entity's folder names: of the systems of its
    source tables (a Hub's primary ones), the most common; on a tie the
    first by name. None without any."""
    counts = Counter(system for system in systems if system)
    if not counts:
        return None
    top = max(counts.values())
    return min(system for system, count in counts.items() if count == top)


def folder_name(name: str) -> str:
    """A name as a folder name: lowercase, spaces and dashes as underscores."""
    return name.lower().replace(" ", "_").replace("-", "_")


def folder_pattern_error(pattern: str) -> str | None:
    """Why *pattern* can't place models, or None when it can."""
    unknown = sorted(
        {m.group(1) for m in _PLACEHOLDER.finditer(pattern)} - FOLDER_PLACEHOLDERS
    )
    if unknown:
        return (
            f"Folder pattern '{pattern}' uses unknown placeholders: "
            + ", ".join(unknown)
            + " (use group, group_name, source_system, source_system_name)"
        )
    raw = pattern.strip()
    if not raw or raw.startswith(("/", "\\", "~")) or re.match(r"[A-Za-z]:", raw):
        return f"Folder pattern '{pattern}' must be relative to the dbt project"
    parts = [part for part in raw.replace("\\", "/").split("/") if part]
    if any(part in ("..", ".") for part in parts):
        return f"Folder pattern '{pattern}' must stay inside the dbt project"
    if len(parts) < 2 or _PLACEHOLDER.search(parts[0]):
        return (
            f"Folder pattern '{pattern}' needs a model path and a folder (e.g. "
            "models/raw_vault)"
        )
    return None


@dataclass
class FolderConfig:
    """
    Where generated models go: a folder pattern per layer and kind of model.

    ``patterns`` override ``DEFAULT_FOLDERS``; a kind without a pattern of its
    own uses its layer's.
    """

    patterns: dict[str, str] = field(default_factory=dict)

    # -- patterns ---------------------------------------------------------------

    def pattern(self, key: str) -> str:
        """The folder pattern of a layer or kind of model."""
        if self.patterns.get(key):
            return self.patterns[key].strip().replace("\\", "/").strip("/")
        if key in DEFAULT_FOLDERS:
            return DEFAULT_FOLDERS[key]
        if key in KIND_LAYERS:
            return self.pattern(KIND_LAYERS[key])
        raise KeyError(key)

    def has_own(self, key: str) -> bool:
        """Whether a kind of model has a pattern of its own (not its layer's)."""
        return bool(self.patterns.get(key)) or (
            key in DEFAULT_FOLDERS and key not in LAYERS
        )

    def is_default(self) -> bool:
        """Whether every pattern is TurboVault's default layout."""
        return all(self.pattern(key) == self._default(key) for key in FOLDER_KEYS)

    def _default(self, key: str) -> str:
        return DEFAULT_FOLDERS.get(key) or DEFAULT_FOLDERS[KIND_LAYERS[key]]

    def layer_folder(self, layer: str) -> str:
        """The fixed part of a layer's pattern: where dbt_project.yml
        configures the layer (e.g. models/30_raw_vault)."""
        return fixed_part(self.pattern(layer))

    def folder(
        self,
        key: str,
        *,
        group: str | None = None,
        source_system: str | None = None,
    ) -> str:
        """A model's folder, relative to the project: its pattern filled in."""
        values = {
            "group": folder_name(group) if group else "",
            "group_name": group or "",
            "source_system": folder_name(source_system) if source_system else "",
            "source_system_name": source_system or "",
        }
        parts = []
        for part in self.pattern(key).split("/"):
            names = [m.group(1) for m in _PLACEHOLDER.finditer(part)]
            filled = _PLACEHOLDER.sub(lambda m: values.get(m.group(1), ""), part)
            if names and not all(values.get(name) for name in names):
                continue  # a placeholder without value: the part is left out
            if filled:
                parts.append(filled)
        return "/".join(parts)

    def model_paths(self) -> list[str]:
        """The top folders the patterns place models in (dbt's model-paths)."""
        paths: list[str] = []
        for key in sorted(FOLDER_KEYS):
            top = self.pattern(key).split("/")[0]
            if top and top not in paths:
                paths.append(top)
        return paths

    # -- TurboVault's default layout, by name (kept for callers) ------------

    @property
    def control_path(self) -> str:
        return self.layer_folder("control")

    @property
    def source_path(self) -> str:
        return self.layer_folder("sources")

    @property
    def prestaging_path(self) -> str:
        return self.layer_folder("prestaging")

    @property
    def staging_path(self) -> str:
        return self.layer_folder("staging")

    @property
    def raw_vault_path(self) -> str:
        return self.layer_folder("raw_vault")

    @property
    def business_vault_path(self) -> str:
        return self.layer_folder("business_vault")

    def get_source_path(self, output_root: Path) -> Path:
        """Get the source directory path."""
        return output_root / self.folder("sources")

    def get_staging_path(self, source_system: str, output_root: Path) -> Path:
        """The folder of a source system's stages."""
        return output_root / self.folder("stage", source_system=source_system)

    def get_staging_base_path(self, output_root: Path) -> Path:
        """Get the base staging directory path."""
        return output_root / self.layer_folder("staging")

    def get_raw_vault_path(self, group: str | None, output_root: Path) -> Path:
        """The folder of a group's raw vault models."""
        return output_root / self.folder("hub", group=group)

    def get_business_vault_pits_path(
        self, group: str | None, output_root: Path
    ) -> Path:
        """The folder of a group's PITs."""
        return output_root / self.folder("pit", group=group)

    def get_raw_vault_reference_tables_path(self, output_root: Path) -> Path:
        """Get the path for reference table models."""
        return output_root / self.folder("reference_table")

    def get_control_path(self, output_root: Path) -> Path:
        """Get the path for control models (snapshot control)."""
        return output_root / self.folder("snapshot_control")

    def create_project_structure(self, output_root: Path) -> None:
        """
        Create the complete dbt project directory structure.

        Args:
            output_root: Root directory for the dbt project.
        """
        directories = [
            output_root / self.layer_folder(layer)
            for layer in (
                "sources",
                "staging",
                "raw_vault",
                "business_vault",
                "control",
            )
        ]
        directories.append(output_root / fixed_part(self.pattern("pit")))
        directories += [
            output_root / name
            for name in ("macros", "tests", "seeds", "analyses", "snapshots")
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def ensure_path_exists(self, path: Path) -> None:
        """Ensure a directory path exists, creating it if necessary."""
        path.mkdir(parents=True, exist_ok=True)

    def _sanitize_name(self, name: str) -> str:
        """A name as a folder name (see ``folder_name``)."""
        return folder_name(name)


def fixed_part(pattern: str) -> str:
    """The folders of a pattern before its first placeholder."""
    parts = []
    for part in pattern.split("/"):
        if _PLACEHOLDER.search(part):
            break
        parts.append(part)
    return "/".join(parts)


@dataclass
class GenerationConfig:
    """
    Configuration options for dbt project generation.

    Controls behavior like satellite v1 view generation and validation mode.
    """

    # Folder structure configuration
    folder_config: FolderConfig = field(default_factory=FolderConfig)

    # Models go to the folders stored for them; off: TurboVault's layer folders
    use_model_folders: bool = True

    # Models carry TurboVault's default tags (their stored tags either way)
    add_default_tags: bool = True

    # Satellite v0/v1 generation. The naming patterns only apply to exports
    # that carry no resolved model names (see ModelOutputDef).
    generate_satellite_v1_views: bool = True
    satellite_v0_naming: str = "[[ satellite_name ]]_v0"
    satellite_v1_naming: str = "[[ satellite_name ]]_v1"
    record_tracking_satellite_naming: str = "[[ satellite_name ]]_ts"
    effectivity_satellite_naming: str = "[[ satellite_name ]]_es"

    # Schemas (None: no custom schema)
    stage_schema: str | None = "stage"
    rdv_schema: str | None = "rdv"
    bdv_schema: str | None = "bdv"

    def resolve_entity_name(self, pattern: str, entity_name: str) -> str:
        """Resolve a naming pattern with placeholder replacement."""
        return pattern.replace("[[ entity_name ]]", entity_name).replace(
            "[[ satellite_name ]]", entity_name
        )

    # Validation mode
    mode: Literal["strict", "lenient"] = "strict"
    skip_validation: bool = False

    # Output options
    create_zip: bool = False

    # Project metadata
    project_name: str = "turbovault_project"
    profile_name: str = "default"

    # datavault4dbt global variables rendered into the dbt_project.yml vars: block
    global_vars: dict[str, Any] = field(default_factory=dict)

    # An imported dbt project's dbt_project.yml (spec D20, D25): the project's
    # models: block (folder-level settings) and its other top-level settings
    dbt_project_models: dict[str, Any] = field(default_factory=dict)
    dbt_project_settings: dict[str, Any] = field(default_factory=dict)
    # Its packages (spec D28), written into packages.yml with datavault4dbt
    dbt_packages: list[dict[str, Any]] = field(default_factory=list)

    # Generating into an existing dbt project (spec D17): its dbt_project.yml
    # and packages.yml aren't written, and stand in for TurboVault's layer
    # blocks (dbt_project_models is then the project's models: block). Its
    # vars and packages, to report what the models need.
    write_project_files: bool = True
    existing_variables: dict[str, Any] = field(default_factory=dict)
    existing_packages: list[dict[str, Any]] = field(default_factory=list)

    # Per-layer settings of the dbt_project.yml models: block
    control_schema: str | None = "control"
    control_materialization: str = "table"
    staging_materialization: str = "view"
    raw_vault_materialization: str = "incremental"
    business_vault_materialization: str = "table"
    # Keep the own materialization of models that differ from their layer
    model_specific_materializations: bool = True
    # Overrides of those own materializations, keyed by model kind
    model_materializations: dict[str, str] = field(default_factory=dict)

    # Optional profiles.yml, rendered from a caller-supplied mapping
    generate_profiles_yml: bool = False
    profiles: dict[str, Any] = field(default_factory=dict)


def get_model_filename(
    entity_name: str, suffix: str = "", extension: str = "sql"
) -> str:
    """
    Generate a model filename from entity name.

    Args:
        entity_name: Name of the entity (hub, link, satellite, etc.)
        suffix: Optional suffix (e.g., '_v0', '_v1')
        extension: File extension (default 'sql')

    Returns:
        Filename string.
    """
    return f"{entity_name}{suffix}.{extension}"
