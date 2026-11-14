"""`turbovault project init` passes its options on to the project setup."""

from __future__ import annotations


def test_the_default_snapshot_control_can_be_left_out(monkeypatch):
    from engine.cli.commands import init_cmd, project_cmd
    from engine.services import app_config_loader

    calls = []
    monkeypatch.setattr(app_config_loader, "require_workspace", lambda: None)
    monkeypatch.setattr(init_cmd, "init", lambda **kwargs: calls.append(kwargs))

    project_cmd.project_init(name="shop", snapshot_controls=False)
    project_cmd.project_init(name="tpch")

    assert [call["snapshot_controls"] for call in calls] == [False, True]
