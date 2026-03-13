"""
Lightweight telemetry for TurboVault Engine.

Events are sent in a daemon thread so they NEVER block CLI operation.
All networking and I/O errors are silently swallowed (logged at DEBUG level only).

Public API
----------
send_telemetry_event(event, command, properties) -> None

Opt-out
-------
1. Set env var  TURBOVAULT_DISABLE_TELEMETRY=1  (any truthy value)
2. Add  disable_anonymous_usage_stats: true  to turbovault.yml

Event schema version: 1
"""

from __future__ import annotations

import importlib.metadata
import json
import logging
import os
import platform
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import request as urllib_request
from urllib.error import URLError

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_TELEMETRY_ENDPOINT = "https://telemetry.turbovault.app/v1/events"
_TELEMETRY_TIMEOUT_SECONDS = 5
_SCHEMA_VERSION = 1

_CI_ENV_VARS = (
    "CI",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "JENKINS_URL",
    "CIRCLECI",
    "TRAVIS",
    "BUILDKITE",
    "TEAMCITY_VERSION",
    "AZURE_PIPELINES",
)

_DISABLE_ENV_VAR = "TURBOVAULT_DISABLE_TELEMETRY"


# ─── Installation ID ──────────────────────────────────────────────────────────


def _get_installation_file() -> Path:
    """
    Return the path to installation.json inside the installed engine package.

    This resolves to <site-packages>/engine/installation.json, which is
    co-located with the application installation (venv or system).
    The file is NOT inside the workspace directory or the user home directory.
    """
    return Path(__file__).parent.parent / "installation.json"


def _load_or_create_installation_id() -> str | None:
    """
    Load the installation ID from installation.json, creating it if absent.

    Returns None if the file cannot be read or written (e.g. read-only install).
    """
    installation_file = _get_installation_file()

    # Try to read existing ID
    if installation_file.exists():
        try:
            data = json.loads(installation_file.read_text(encoding="utf-8"))
            installation_id = data.get("installation_id")
            if isinstance(installation_id, str) and installation_id:
                return installation_id
        except Exception as exc:
            logger.debug("Could not read installation.json: %s", exc)

    # Generate and persist new ID
    new_id = str(uuid.uuid4())
    try:
        installation_file.write_text(
            json.dumps({"installation_id": new_id}, indent=2),
            encoding="utf-8",
        )
        logger.debug("Created new installation ID: %s", new_id)
        return new_id
    except OSError as exc:
        # Read-only install dir (e.g. system-wide pip install) — skip gracefully
        logger.debug("Could not write installation.json (read-only install?): %s", exc)
        return None


# ─── Opt-out check ────────────────────────────────────────────────────────────


def _is_telemetry_disabled() -> bool:
    """
    Return True if telemetry has been disabled by the user.

    Check order:
      1. TURBOVAULT_DISABLE_TELEMETRY env var (any truthy value)
      2. disable_anonymous_usage_stats: true in turbovault.yml
    """
    env_value = os.environ.get(_DISABLE_ENV_VAR, "").strip().lower()
    if env_value in ("1", "true", "yes"):
        logger.debug("Telemetry disabled via env var.")
        return True

    try:
        from engine.services.app_config_loader import load_application_config

        config = load_application_config()
        if config.disable_anonymous_usage_stats:
            logger.debug("Telemetry disabled via turbovault.yml config.")
            return True
    except Exception as exc:
        logger.debug("Could not read app config for telemetry check: %s", exc)

    return False


# ─── Context helpers ──────────────────────────────────────────────────────────


def _is_ci() -> bool:
    """Return True if a known CI environment variable is set."""
    return any(os.environ.get(var) for var in _CI_ENV_VARS)


def _detect_install_type() -> str:
    """
    Detect how TurboVault Engine was installed.

    Returns one of: 'docker', 'editable', 'venv', 'system'.
    """
    # Docker container detection
    if Path("/.dockerenv").exists() or os.environ.get("DOCKER_CONTAINER"):
        return "docker"

    # Editable install detection via dist-info direct_url.json
    try:
        dist = importlib.metadata.distribution("turbovault-engine")
        direct_url_text = dist.read_text("direct_url.json")
        if direct_url_text:
            direct_url = json.loads(direct_url_text)
            if direct_url.get("dir_info", {}).get("editable"):
                return "editable"
    except Exception:
        pass

    # Virtual environment detection
    if sys.prefix != sys.base_prefix:
        return "venv"

    return "system"


def _get_package_version() -> str:
    """Return the installed turbovault-engine package version, or 'unknown'."""
    try:
        return importlib.metadata.version("turbovault-engine")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


# ─── Event payload ────────────────────────────────────────────────────────────


def _build_event_payload(
    event: str,
    command: str,
    installation_id: str,
    session_id: str,
    properties: dict[str, Any],
) -> dict[str, Any]:
    """
    Build the versioned telemetry event payload dict.

    Schema version 1 — bump _SCHEMA_VERSION when adding breaking fields.
    """
    return {
        "schema_version": _SCHEMA_VERSION,
        "event": event,
        "session_id": session_id,
        "installation_id": installation_id,
        "command": command,
        "turbovault_version": _get_package_version(),
        "python_version": platform.python_version(),
        "os_family": platform.system(),
        "os_version": platform.version(),
        "arch": platform.machine(),
        "install_type": _detect_install_type(),
        "ci": _is_ci(),
        "timestamp": datetime.now(UTC).isoformat(),
        "properties": properties,
    }


# ─── HTTP send ────────────────────────────────────────────────────────────────


def _send_payload(endpoint: str, payload: dict[str, Any]) -> None:
    """
    POST the serialised payload to the telemetry endpoint.

    Runs in a daemon thread; all exceptions are swallowed silently.
    """
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib_request.urlopen(req, timeout=_TELEMETRY_TIMEOUT_SECONDS)
        logger.debug("Telemetry event '%s' sent successfully.", payload.get("event"))
    except URLError as exc:
        logger.debug("Telemetry HTTP request failed (network): %s", exc)
    except Exception as exc:
        logger.debug("Telemetry HTTP request failed: %s", exc)


# ─── Public API ───────────────────────────────────────────────────────────────


def send_telemetry_event(
    event: str,
    command: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """
    Fire-and-forget telemetry event. Returns immediately.

    The event is serialised and sent in a background daemon thread so it
    never delays or breaks normal CLI operation. All errors are silently
    suppressed.

    Does nothing when:
    - Telemetry is disabled (env var or turbovault.yml config).
    - The installation ID cannot be resolved (read-only install dir).

    Args:
        event:      Event name, e.g. ``"command_invoked"``.
        command:    The CLI sub-command being executed, e.g. ``"generate"``.
        properties: Optional dict of event-specific properties.
    """
    try:
        if _is_telemetry_disabled():
            return

        installation_id = _load_or_create_installation_id()
        if not installation_id:
            # Cannot identify this installation — skip to keep data clean.
            logger.debug("Skipping telemetry: installation_id unavailable.")
            return

        session_id = str(uuid.uuid4())
        payload = _build_event_payload(
            event=event,
            command=command,
            installation_id=installation_id,
            session_id=session_id,
            properties=properties or {},
        )

        thread = threading.Thread(
            target=_send_payload,
            args=(_TELEMETRY_ENDPOINT, payload),
            daemon=True,
        )
        thread.start()

    except Exception as exc:
        # Telemetry must never surface exceptions to the user.
        logger.debug("Telemetry setup failed unexpectedly: %s", exc)
