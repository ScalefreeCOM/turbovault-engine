"""
Unit tests for the TurboVault Engine telemetry module.

These tests use only stdlib mocking — no Django setup required.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

# ─── Helpers ──────────────────────────────────────────────────────────────────
# Import the module under test
from engine.cli.utils.telemetry import (
    _build_event_payload,
    _detect_install_type,
    _is_ci,
    _is_telemetry_disabled,
    _load_or_create_installation_id,
    _send_payload,
    send_telemetry_event,
)

# ─── CI detection ─────────────────────────────────────────────────────────────


class TestIsCi:
    def test_ci_detected_from_ci_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CI=true should mark the run as CI."""
        monkeypatch.setenv("CI", "true")
        assert _is_ci() is True

    def test_ci_detected_from_github_actions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GITHUB_ACTIONS env var should mark the run as CI."""
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        assert _is_ci() is True

    def test_ci_detected_from_gitlab(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GITLAB_CI env var should mark the run as CI."""
        monkeypatch.setenv("GITLAB_CI", "true")
        assert _is_ci() is True

    def test_ci_not_detected_without_env_vars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No CI env vars set → not CI."""
        for var in (
            "CI",
            "GITHUB_ACTIONS",
            "GITLAB_CI",
            "JENKINS_URL",
            "CIRCLECI",
            "TRAVIS",
            "BUILDKITE",
            "TEAMCITY_VERSION",
            "AZURE_PIPELINES",
        ):
            monkeypatch.delenv(var, raising=False)
        assert _is_ci() is False


# ─── Opt-out checks ───────────────────────────────────────────────────────────


class TestIsTelemetryDisabled:
    def test_disabled_by_env_var_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TURBOVAULT_DISABLE_TELEMETRY", "1")
        assert _is_telemetry_disabled() is True

    def test_disabled_by_env_var_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TURBOVAULT_DISABLE_TELEMETRY", "TRUE")
        assert _is_telemetry_disabled() is True

    def test_disabled_by_env_var_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TURBOVAULT_DISABLE_TELEMETRY", "yes")
        assert _is_telemetry_disabled() is True

    def test_not_disabled_by_env_var_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TURBOVAULT_DISABLE_TELEMETRY", "0")
        # Config check will run — patch it to return False
        with patch(
            "engine.services.app_config_loader.load_application_config"
        ) as mock_cfg:
            mock_cfg.return_value = MagicMock(disable_anonymous_usage_stats=False)
            assert _is_telemetry_disabled() is False

    def test_disabled_by_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """disable_anonymous_usage_stats=True in config → disabled."""
        monkeypatch.delenv("TURBOVAULT_DISABLE_TELEMETRY", raising=False)
        with patch(
            "engine.services.app_config_loader.load_application_config"
        ) as mock_cfg:
            mock_cfg.return_value = MagicMock(disable_anonymous_usage_stats=True)
            assert _is_telemetry_disabled() is True

    def test_enabled_when_config_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TURBOVAULT_DISABLE_TELEMETRY", raising=False)
        with patch(
            "engine.services.app_config_loader.load_application_config"
        ) as mock_cfg:
            mock_cfg.return_value = MagicMock(disable_anonymous_usage_stats=False)
            assert _is_telemetry_disabled() is False

    def test_enabled_when_config_load_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If config load raises, telemetry is assumed enabled (not disabled)."""
        monkeypatch.delenv("TURBOVAULT_DISABLE_TELEMETRY", raising=False)
        with patch(
            "engine.services.app_config_loader.load_application_config",
            side_effect=RuntimeError("no config"),
        ):
            assert _is_telemetry_disabled() is False


# ─── Installation ID persistence ──────────────────────────────────────────────


class TestLoadOrCreateInstallationId:
    def test_creates_new_id_when_file_missing(self, tmp_path: Path) -> None:
        """A new UUID is generated and written when installation.json doesn't exist."""
        installation_file = tmp_path / "installation.json"
        with patch(
            "engine.cli.utils.telemetry._get_installation_file",
            return_value=installation_file,
        ):
            result = _load_or_create_installation_id()

        assert result is not None
        assert len(result) == 36  # standard UUID4 string length
        assert installation_file.exists()
        data = json.loads(installation_file.read_text())
        assert data["installation_id"] == result

    def test_returns_same_id_on_second_call(self, tmp_path: Path) -> None:
        """Subsequent calls return the same persisted UUID."""
        installation_file = tmp_path / "installation.json"
        with patch(
            "engine.cli.utils.telemetry._get_installation_file",
            return_value=installation_file,
        ):
            first = _load_or_create_installation_id()
            second = _load_or_create_installation_id()

        assert first == second

    def test_returns_none_when_write_fails(self, tmp_path: Path) -> None:
        """Returns None gracefully when the file cannot be written (read-only dir)."""
        non_existent_readonly = Path("/no/such/dir/installation.json")
        with patch(
            "engine.cli.utils.telemetry._get_installation_file",
            return_value=non_existent_readonly,
        ):
            result = _load_or_create_installation_id()

        assert result is None

    def test_existing_file_is_read(self, tmp_path: Path) -> None:
        """If installation.json already exists with a valid UUID, it is returned as-is."""
        installation_file = tmp_path / "installation.json"
        expected_id = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
        installation_file.write_text(
            json.dumps({"installation_id": expected_id}), encoding="utf-8"
        )
        with patch(
            "engine.cli.utils.telemetry._get_installation_file",
            return_value=installation_file,
        ):
            result = _load_or_create_installation_id()

        assert result == expected_id


# ─── Install type detection ───────────────────────────────────────────────────


class TestDetectInstallType:
    def test_venv_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """sys.prefix != sys.base_prefix → 'venv'."""
        monkeypatch.delenv("DOCKER_CONTAINER", raising=False)
        with (
            patch("engine.cli.utils.telemetry.Path") as mock_path_cls,
            patch("engine.cli.utils.telemetry.sys") as mock_sys,
            patch(
                "engine.cli.utils.telemetry.importlib.metadata.distribution",
                side_effect=Exception("no dist"),
            ),
        ):
            mock_path_cls.return_value.exists.return_value = False
            mock_sys.prefix = "/venv"
            mock_sys.base_prefix = "/usr"
            result = _detect_install_type()

        assert result == "venv"

    def test_system_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When not in venv and not docker/editable → 'system'."""
        monkeypatch.delenv("DOCKER_CONTAINER", raising=False)
        with (
            patch("engine.cli.utils.telemetry.Path") as mock_path_cls,
            patch("engine.cli.utils.telemetry.sys") as mock_sys,
            patch(
                "engine.cli.utils.telemetry.importlib.metadata.distribution",
                side_effect=Exception("no dist"),
            ),
        ):
            mock_path_cls.return_value.exists.return_value = False
            mock_sys.prefix = "/usr"
            mock_sys.base_prefix = "/usr"
            result = _detect_install_type()

        assert result == "system"


# ─── Event payload ────────────────────────────────────────────────────────────


class TestBuildEventPayload:
    def test_all_required_fields_present(self) -> None:
        """Built payload must contain all schema v1 fields."""
        required_fields = {
            "schema_version",
            "event",
            "session_id",
            "installation_id",
            "command",
            "turbovault_version",
            "python_version",
            "os_family",
            "os_version",
            "arch",
            "install_type",
            "ci",
            "timestamp",
            "properties",
        }
        payload = _build_event_payload(
            event="command_invoked",
            command="generate",
            installation_id="test-id",
            session_id="test-session",
            properties={"foo": "bar"},
        )
        assert required_fields.issubset(payload.keys())

    def test_schema_version_is_1(self) -> None:
        payload = _build_event_payload(
            event="command_invoked",
            command="generate",
            installation_id="id",
            session_id="sid",
            properties={},
        )
        assert payload["schema_version"] == 1

    def test_properties_are_included(self) -> None:
        payload = _build_event_payload(
            event="command_invoked",
            command="generate",
            installation_id="id",
            session_id="sid",
            properties={"mode": "strict"},
        )
        assert payload["properties"] == {"mode": "strict"}

    def test_ci_field_is_bool(self) -> None:
        payload = _build_event_payload(
            event="test",
            command="test",
            installation_id="id",
            session_id="sid",
            properties={},
        )
        assert isinstance(payload["ci"], bool)


# ─── HTTP dispatch ────────────────────────────────────────────────────────────


class TestSendPayload:
    def test_swallows_url_error(self) -> None:
        """URLError must not propagate out of _send_payload."""
        with patch(
            "engine.cli.utils.telemetry.urllib_request.urlopen",
            side_effect=URLError("connection refused"),
        ):
            # Should not raise
            _send_payload("https://example.com", {"event": "test"})

    def test_swallows_generic_exception(self) -> None:
        """Any unexpected exception must not propagate out of _send_payload."""
        with patch(
            "engine.cli.utils.telemetry.urllib_request.urlopen",
            side_effect=RuntimeError("unexpected"),
        ):
            _send_payload("https://example.com", {"event": "test"})


# ─── Public API ───────────────────────────────────────────────────────────────


class TestSendTelemetryEvent:
    def test_no_payload_sent_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When telemetry is disabled, _send_payload must never be called."""
        monkeypatch.setenv("TURBOVAULT_DISABLE_TELEMETRY", "1")
        with patch("engine.cli.utils.telemetry._send_payload") as mock_send:
            send_telemetry_event(event="command_invoked", command="generate")
        mock_send.assert_not_called()

    def test_no_payload_sent_when_no_installation_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When installation_id cannot be resolved, _send_payload must not be called."""
        monkeypatch.delenv("TURBOVAULT_DISABLE_TELEMETRY", raising=False)
        with (
            patch(
                "engine.cli.utils.telemetry._is_telemetry_disabled", return_value=False
            ),
            patch(
                "engine.cli.utils.telemetry._load_or_create_installation_id",
                return_value=None,
            ),
            patch("engine.cli.utils.telemetry._send_payload") as mock_send,
        ):
            send_telemetry_event(event="command_invoked", command="generate")
        mock_send.assert_not_called()

    def test_thread_started_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When telemetry is enabled and ID is available, a non-daemon thread is started
        and joined so the HTTP request completes before the process exits."""
        monkeypatch.delenv("TURBOVAULT_DISABLE_TELEMETRY", raising=False)
        with (
            patch(
                "engine.cli.utils.telemetry._is_telemetry_disabled", return_value=False
            ),
            patch(
                "engine.cli.utils.telemetry._load_or_create_installation_id",
                return_value="test-id",
            ),
            patch("engine.cli.utils.telemetry.threading.Thread") as mock_thread_cls,
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            send_telemetry_event(event="command_invoked", command="generate")

        mock_thread_cls.assert_called_once()
        # Thread must be non-daemon so the OS doesn't kill it when the CLI exits
        _, kwargs = mock_thread_cls.call_args
        assert kwargs.get("daemon") is False
        mock_thread.start.assert_called_once()
        # join() must be called so the process waits for the request to finish
        mock_thread.join.assert_called_once()

    def test_swallows_unexpected_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Any unexpected error inside send_telemetry_event must not propagate."""
        monkeypatch.delenv("TURBOVAULT_DISABLE_TELEMETRY", raising=False)
        with patch(
            "engine.cli.utils.telemetry._is_telemetry_disabled",
            side_effect=RuntimeError("unexpected"),
        ):
            # Must not raise
            send_telemetry_event(event="command_invoked", command="generate")
