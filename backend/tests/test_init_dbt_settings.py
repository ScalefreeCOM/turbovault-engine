"""Tests for the dbt project settings asked and accepted by `project init`."""

from __future__ import annotations

import pytest


class _Prompt:
    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        return self._answer


class _ScriptedQuestionary:
    """Stands in for `questionary`: answers prompts in order, records questions."""

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
        return init_cmd._ask_dbt_settings(), fake

    return _ask


class TestAskDbtSettings:
    def test_declining_keeps_defaults(self, ask):
        settings, fake = ask([False])
        assert settings == {}
        assert len(fake.questions) == 1

    def test_asks_every_layer_materialization(self, ask):
        settings, fake = ask(
            [
                True,  # configure dbt settings?
                "tpch_dv",  # profile
                "ephemeral",  # staging
                "incremental",  # raw vault
                "view",  # business vault
                "table",  # control
                True,  # materialization in models
            ]
        )
        assert settings == {
            "profile_name": "tpch_dv",
            "staging_materialization": "ephemeral",
            "business_vault_materialization": "view",
            "materialization_in_models": True,
        }
        layer_questions = [q for q in fake.questions if "materialization:" in q]
        assert len(layer_questions) == 4

    def test_letters_do_not_move_the_selection(self, ask):
        """A pasted path containing "j" must not change a layer's answer."""
        _, fake = ask([True, "default", "view", "incremental", "table", "table", False])
        assert len(fake.select_kwargs) == 4
        assert all(kwargs.get("use_jk_keys") is False for kwargs in fake.select_kwargs)

    def test_pasted_text_keeps_the_default_answer(self, django_setup, monkeypatch):
        """Real questionary prompt: pasting a path, then Enter, keeps the default."""
        import questionary
        from engine.cli.commands import init_cmd
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        real_select = questionary.select
        # confirm: customize? / text: profile / confirm: materialization in models
        answers = iter([True, "default", False])
        monkeypatch.setattr(
            init_cmd.questionary, "confirm", lambda *a, **k: _Prompt(next(answers))
        )
        monkeypatch.setattr(
            init_cmd.questionary, "text", lambda *a, **k: _Prompt(next(answers))
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
        settings = init_cmd._ask_dbt_settings()

        assert selections == ["view", "incremental", "table", "table"]
        assert settings == {}

    def test_default_answers_add_nothing_to_config(self, ask):
        settings, _ = ask(
            [True, "default", "view", "incremental", "table", "table", False]
        )
        assert settings == {}

    def test_answers_build_a_valid_config(self, ask):
        from engine.services.config_schema import TurboVaultConfig

        settings, _ = ask([True, "p", "table", "table", "incremental", "view", False])
        config = TurboVaultConfig(project={"name": "p"}, configuration=settings)
        assert config.configuration.raw_vault_materialization == "table"
        assert config.configuration.control_materialization == "view"


class TestDbtOverridesFromFlags:
    def test_unset_flags_are_left_out(self, django_setup):
        from engine.cli.commands.init_cmd import _dbt_overrides

        overrides = _dbt_overrides(
            profile_name=None,
            control_schema="meta",
            staging_materialization=None,
            materialization_in_models=False,
        )
        assert overrides == {"control_schema": "meta"}

    def test_materialization_in_models_flag(self, django_setup):
        from engine.cli.commands.init_cmd import _dbt_overrides

        assert _dbt_overrides(materialization_in_models=True) == {
            "materialization_in_models": True
        }


def test_validate_schema_answer(django_setup):
    from engine.cli.commands.init_cmd import _validate_schema_answer

    assert _validate_schema_answer("meta_1") is True
    assert _validate_schema_answer("") != True  # noqa: E712
    assert _validate_schema_answer("a b") != True  # noqa: E712
