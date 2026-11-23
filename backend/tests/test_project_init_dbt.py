"""`turbovault project init --interactive` creates a project from a dbt project.

The wizard offers a dbt project next to the other sources. It shows the dbt
project's files, asks what `turbovault import` asks, and can make the dbt
project the TurboVault project's own (``dbt_project.path``). The dbt project
brings its snapshot controls and suggests the project's settings, so the
wizard asks neither for default snapshot controls nor for schemas, naming
patterns and materializations. With flags, a dbt project as ``--source``
explains how to import it instead of being read as another format.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import questionary
import typer

from tests.imports.dbt.test_dbt_mapping import (
    CUSTOMER,
    CUSTOMER_H,
    ORDERS,
    STG_CUSTOMER,
    STG_ORDERS,
    write_manifest,
)

pytestmark = pytest.mark.django_db


class _Prompt:
    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        return self._answer


class _ScriptedQuestionary:
    """Stands in for `questionary`: answers in order, records the questions."""

    Choice = questionary.Choice

    def __init__(self, answers):
        self._answers = list(answers)
        self.questions: list[str] = []
        self.choices: list[list] = []

    def _next(self, message, **kwargs):
        self.questions.append(message)
        if "choices" in kwargs:
            self.choices.append(kwargs["choices"])
        return _Prompt(self._answers.pop(0))

    select = confirm = text = path = _next


def _dbt_project(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "dbt_project.yml").write_text(
        "name: shop\nprofile: shop\n", encoding="utf-8"
    )
    write_manifest(root, [STG_CUSTOMER, STG_ORDERS, CUSTOMER_H], [CUSTOMER, ORDERS])
    return root


@pytest.mark.parametrize("own", [True, False])
def test_the_wizard_offers_a_dbt_project(tmp_path, monkeypatch, django_setup, own):
    from engine.cli.commands import init_cmd

    root = _dbt_project(tmp_path / "shop_dbt")
    # Name, description, import?, source type, path, descriptions, tags,
    # the dbt project as the project's own?
    fake = _ScriptedQuestionary(["shop", "", True, "dbt", str(root), True, False, own])
    monkeypatch.setattr(init_cmd, "questionary", fake)
    created: dict = {}
    monkeypatch.setattr(
        init_cmd,
        "_create_project",
        lambda config, **kwargs: created.update(config=config, **kwargs),
    )

    init_cmd._run_interactive_init()

    # Offered next to the other sources
    (source_types,) = fake.choices
    assert [choice.value for choice in source_types] == [
        "excel",
        "sqlite",
        "json",
        "iris",
        "dbt",
    ]
    # Nothing about snapshot controls, schemas or materializations
    assert len(fake.questions) == 8
    assert not [
        question
        for question in fake.questions
        if "snapshot control" in question
        or "default settings" in question
        or "materialization" in question
    ]
    source = created["dbt_source"]
    assert source.path == root
    assert (source.import_descriptions, source.import_tags) == (True, False)
    assert created["snapshot_controls"] is False
    assert created["config"].source is None
    dbt_project = created["config"].dbt_project
    assert (dbt_project.path if dbt_project else None) == (root if own else None)


def test_a_folder_that_isnt_a_dbt_project_stops_the_wizard(
    tmp_path, monkeypatch, django_setup
):
    from engine.cli.commands import init_cmd

    fake = _ScriptedQuestionary(["shop", "", True, "dbt", str(tmp_path)])
    monkeypatch.setattr(init_cmd, "questionary", fake)
    errors: list[str] = []
    monkeypatch.setattr(init_cmd, "print_error", errors.append)

    with pytest.raises(typer.Exit) as stopped:
        init_cmd._run_interactive_init()

    assert stopped.value.exit_code == 1
    assert "isn't a dbt project" in errors[0]


def test_a_project_is_created_from_a_dbt_project(tmp_path, monkeypatch, django_setup):
    from engine.cli.commands import init_cmd
    from engine.models import Hub, Project, SnapshotControlTable
    from engine.services import app_config_loader, project_config
    from engine.services.config_schema import (
        DbtProjectConfig,
        ProjectInfo,
        TurboVaultConfig,
    )
    from engine.services.imports import DbtSource

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for module in (app_config_loader, project_config):
        monkeypatch.setattr(module, "get_project_root", lambda: workspace)
    root = _dbt_project(tmp_path / "shop_dbt")
    config = TurboVaultConfig(
        project=ProjectInfo(name="shop"), dbt_project=DbtProjectConfig(path=root)
    )

    # Asked for default snapshot controls, the dbt project's own win
    init_cmd._create_project(
        config, snapshot_controls=True, dbt_source=DbtSource(path=root)
    )

    project = Project.objects.get(name="shop")
    assert Hub.objects.filter(project=project, hub_physical_name="customer_h").exists()
    assert not SnapshotControlTable.objects.filter(project=project).exists()
    assert project.load_config().dbt_project.path == root


def test_a_dbt_project_as_source_flag_says_how_to_import_it(
    tmp_path, monkeypatch, django_setup
):
    from engine.cli.commands import init_cmd
    from engine.models import Project
    from engine.services import app_config_loader

    monkeypatch.setattr(app_config_loader, "require_workspace", lambda: None)
    errors: list[str] = []
    monkeypatch.setattr(init_cmd, "print_error", errors.append)
    root = _dbt_project(tmp_path / "shop_dbt")

    # Its folder isn't read as IRiS files, its manifest not as a JSON export
    for source in (root, root / "manifest.json"):
        with pytest.raises(typer.Exit) as stopped:
            init_cmd.init(name="shop", source_path=source)
        assert stopped.value.exit_code == 1

    assert all("is a dbt project" in error for error in errors)
    assert len(errors) == 2
    assert not Project.objects.filter(name="shop").exists()
