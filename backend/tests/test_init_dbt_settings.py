"""Tests for the dbt project settings asked and accepted by `project init`."""

from __future__ import annotations

import pytest
import questionary


class _Prompt:
    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        return self._answer


class _ScriptedQuestionary:
    """Stands in for `questionary`: answers prompts in order, records questions."""

    Choice = questionary.Choice

    def __init__(self, answers):
        self._answers = list(answers)
        self.questions: list[str] = []
        self.select_kwargs: list[dict] = []

    def _next(self, message, **_kwargs):
        self.questions.append(message)
        return _Prompt(self._answers.pop(0))

    def select(self, message, **kwargs):
        self.select_kwargs.append(kwargs)
        return self._next(message)

    confirm = text = _next


@pytest.fixture
def ask(monkeypatch, django_setup):
    from engine.cli.commands import init_cmd

    def _ask(answers):
        fake = _ScriptedQuestionary(answers)
        monkeypatch.setattr(init_cmd, "questionary", fake)
        return init_cmd._ask_materializations(), fake

    return _ask


class TestAskMaterializations:
    """Two levels: layer materializations first, then model-specific ones."""

    def test_keeping_everything_adds_nothing(self, ask):
        settings, fake = ask([False, "own"])
        assert settings == {}
        assert len(fake.questions) == 2

    def test_layer_question_comes_first(self, ask):
        _, fake = ask([False, "own"])
        assert "layer materializations in dbt_project.yml" in fake.questions[0]
        assert "satellite _v1" in fake.questions[1]

    def test_changing_layers_asks_every_layer(self, ask):
        settings, fake = ask(
            [
                True,  # change layer materializations?
                "ephemeral",  # staging
                "incremental",  # raw vault
                "view",  # business vault
                "table",  # control
                "own",  # model-specific materializations
            ]
        )
        assert settings == {
            "staging_materialization": "ephemeral",
            "business_vault_materialization": "view",
        }
        layer_questions = [q for q in fake.questions if "layer materialization:" in q]
        assert len(layer_questions) == 4

    def test_layer_for_all_models_switches_specific_off(self, ask):
        settings, _ = ask([False, "layer"])
        assert settings == {"model_specific_materializations": False}

    def test_layer_for_all_with_incremental_raw_vault_warns(self, ask, monkeypatch):
        from engine.cli.commands import init_cmd

        warnings = []
        monkeypatch.setattr(init_cmd, "print_warning", warnings.append)
        ask([False, "layer"])
        assert any("duplicates" in w for w in warnings)

    def test_letters_do_not_move_any_selection(self, ask):
        """A pasted path containing "j" must not change an answer."""
        _, fake = ask([True, "view", "incremental", "table", "table", "own"])
        assert len(fake.select_kwargs) == 5
        assert all(kwargs.get("use_jk_keys") is False for kwargs in fake.select_kwargs)

    def test_pasted_text_keeps_the_default_answers(self, django_setup, monkeypatch):
        """Real questionary prompts: pasting a path, then Enter, keeps defaults."""
        from engine.cli.commands import init_cmd
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        real_select = questionary.select
        monkeypatch.setattr(
            init_cmd.questionary, "confirm", lambda *a, **k: _Prompt(True)
        )
        pasted = r"C:\Users\jane_doe\Projects\metadata.xlsx" + "\r"
        selections = []

        def select_with_paste(message, **kwargs):
            with create_pipe_input() as inp:
                inp.send_text(pasted)
                answer = real_select(
                    message, input=inp, output=DummyOutput(), **kwargs
                ).ask()
            selections.append(answer)
            return _Prompt(answer)

        monkeypatch.setattr(init_cmd.questionary, "select", select_with_paste)
        settings = init_cmd._ask_materializations()

        assert selections == ["view", "incremental", "table", "table", "own"]
        assert settings == {}

    def test_answers_build_a_valid_config(self, ask):
        from engine.services.config_schema import TurboVaultConfig

        settings, _ = ask([True, "table", "table", "incremental", "view", "layer"])
        config = TurboVaultConfig(project={"name": "p"}, configuration=settings)
        assert config.configuration.raw_vault_materialization == "table"
        assert config.configuration.control_materialization == "view"
        assert config.configuration.model_specific_materializations is False


class TestDbtOverridesFromFlags:
    def test_unset_flags_are_left_out(self, django_setup):
        from engine.cli.commands.init_cmd import _dbt_overrides

        overrides = _dbt_overrides(
            profile_name=None,
            control_schema="meta",
            staging_materialization=None,
            model_specific_materializations=True,
        )
        assert overrides == {"control_schema": "meta"}

    def test_no_model_specific_materializations_flag(self, django_setup):
        from engine.cli.commands.init_cmd import _dbt_overrides

        assert _dbt_overrides(model_specific_materializations=False) == {
            "model_specific_materializations": False
        }


def test_validate_schema_answer(django_setup):
    from engine.cli.commands.init_cmd import _validate_schema_answer

    assert _validate_schema_answer("meta_1") is True
    assert _validate_schema_answer("") != True  # noqa: E712
    assert _validate_schema_answer("a b") != True  # noqa: E712


class TestCustomizeEachModel:
    def test_offered_as_third_option(self, ask):
        _, fake = ask([False, "own"])
        choices = fake.select_kwargs[-1]["choices"]
        assert [c.value for c in choices] == ["own", "layer", "customize"]
        assert choices[0].title.startswith("Keep their own defaults")

    def test_asks_each_model_with_its_default_preselected(self, ask):
        _, fake = ask(
            [False, "customize", "view", "view", "incremental", "incremental", "view"]
        )
        model_selects = fake.select_kwargs[1:]
        assert [k["default"] for k in model_selects] == [
            "view",
            "view",
            "incremental",
            "incremental",
            "view",
        ]
        assert all(k.get("use_jk_keys") is False for k in model_selects)

    def test_only_changed_models_are_stored(self, ask):
        settings, _ = ask(
            [False, "customize", "table", "view", "table", "incremental", "view"]
        )
        assert settings == {
            "model_materializations": {"satellite_v1": "table", "pit": "table"}
        }

    def test_all_defaults_store_nothing(self, ask):
        settings, _ = ask(
            [False, "customize", "view", "view", "incremental", "incremental", "view"]
        )
        assert settings == {}

    def test_incremental_derived_view_warns(self, ask, monkeypatch):
        from engine.cli.commands import init_cmd

        warnings = []
        monkeypatch.setattr(init_cmd, "print_warning", warnings.append)
        ask(
            [
                False,
                "customize",
                "incremental",
                "view",
                "incremental",
                "incremental",
                "view",
            ]
        )
        assert any("duplicates" in w for w in warnings)

    def test_answers_build_a_valid_config(self, ask):
        from engine.services.config_schema import TurboVaultConfig

        settings, _ = ask(
            [False, "customize", "table", "view", "incremental", "table", "view"]
        )
        config = TurboVaultConfig(project={"name": "p"}, configuration=settings)
        assert config.configuration.model_materializations == {
            "satellite_v1": "table",
            "snapshot_control_v0": "table",
        }
