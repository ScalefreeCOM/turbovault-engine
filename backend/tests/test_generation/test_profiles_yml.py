"""Tests for render_profiles_yml(): structure, verbatim rendering, secret safety."""

import pytest
import yaml
from engine.services.generation.profiles_yml import (
    InvalidProfilesError,
    LiteralSecretError,
    render_profiles_yml,
    validate_profiles_yaml,
)


def _profiles(**output_fields):
    return {
        "my_profile": {
            "target": "dev",
            "outputs": {
                "dev": {"type": "postgres", "host": "localhost", **output_fields},
            },
        }
    }


class TestRenderProfilesYml:
    def test_nested_outputs_round_trip(self):
        profiles = {
            "my_profile": {
                "target": "dev",
                "outputs": {
                    "dev": {
                        "type": "postgres",
                        "host": "localhost",
                        "port": 5432,
                        "user": "{{ env_var('DBT_USER') }}",
                        "password": "{{ env_var('DBT_PASSWORD') }}",
                        "threads": 4,
                    },
                    "prod": {
                        "type": "postgres",
                        "host": "db.example.com",
                        "port": 5432,
                        "password": "{{ env_var('DBT_PROD_PASSWORD', '') }}",
                    },
                },
            }
        }
        content = render_profiles_yml(profiles)
        assert yaml.safe_load(content) == profiles

    def test_env_var_reference_passes_through_unchanged(self):
        content = render_profiles_yml(
            _profiles(password="{{ env_var('DBT_PASSWORD') }}")
        )
        parsed = yaml.safe_load(content)
        assert (
            parsed["my_profile"]["outputs"]["dev"]["password"]
            == "{{ env_var('DBT_PASSWORD') }}"
        )

    def test_preserves_insertion_order(self):
        content = render_profiles_yml(_profiles(zeta=1, alpha=2))
        keys = list(yaml.safe_load(content)["my_profile"]["outputs"]["dev"])
        assert keys == ["type", "host", "zeta", "alpha"]

    @pytest.mark.parametrize(
        "key",
        [
            "password",
            "token",
            "private_key",
            "private_key_passphrase",
            "client_secret",
            "keyfile_json",
            "Password",  # case-insensitive
        ],
    )
    def test_literal_secret_rejected(self, key):
        with pytest.raises(LiteralSecretError) as exc_info:
            render_profiles_yml(_profiles(**{key: "hunter2"}))
        # Names where, never echoes the value.
        assert f"my_profile.outputs.dev.{key}" in str(exc_info.value)
        assert "hunter2" not in str(exc_info.value)

    def test_literal_secret_mapping_rejected(self):
        """keyfile_json as an inline dict is a literal credential too."""
        with pytest.raises(LiteralSecretError):
            render_profiles_yml(_profiles(keyfile_json={"private_key": "x"}))

    def test_nested_literal_secret_rejected(self):
        with pytest.raises(LiteralSecretError, match="extras.token"):
            render_profiles_yml(_profiles(extras={"token": "abc"}))

    def test_empty_secret_allowed(self):
        content = render_profiles_yml(_profiles(password=""))
        assert yaml.safe_load(content)["my_profile"]["outputs"]["dev"]["password"] == ""

    def test_env_var_embedded_in_literal_rejected(self):
        with pytest.raises(LiteralSecretError):
            render_profiles_yml(_profiles(password="pre{{ env_var('DBT_PASSWORD') }}"))

    def test_non_mapping_raises(self):
        with pytest.raises(InvalidProfilesError, match="must be a mapping"):
            render_profiles_yml(["x"])  # type: ignore[arg-type]

    def test_empty_raises(self):
        with pytest.raises(InvalidProfilesError, match="empty"):
            render_profiles_yml({})

    def test_missing_outputs_raises(self):
        with pytest.raises(InvalidProfilesError, match="outputs"):
            render_profiles_yml({"p": {"target": "dev"}})

    def test_target_not_in_outputs_raises(self):
        with pytest.raises(InvalidProfilesError, match="target"):
            render_profiles_yml(
                {"p": {"target": "prod", "outputs": {"dev": {"type": "duckdb"}}}}
            )

    def test_output_without_type_raises(self):
        with pytest.raises(InvalidProfilesError, match="type"):
            render_profiles_yml(
                {"p": {"target": "dev", "outputs": {"dev": {"host": "h"}}}}
            )

    def test_non_serializable_value_raises(self):
        with pytest.raises(InvalidProfilesError, match="serialized"):
            render_profiles_yml(_profiles(threads=object()))


class TestProfileNameConsistency:
    def test_profile_name_must_exist(self):
        with pytest.raises(InvalidProfilesError, match="no such profile"):
            render_profiles_yml(_profiles(), profile_name="other")

    def test_existing_profile_name_passes(self):
        content = render_profiles_yml(_profiles(), profile_name="my_profile")
        assert "my_profile" in yaml.safe_load(content)

    def test_no_profile_name_skips_the_check(self):
        render_profiles_yml(_profiles())


class TestValidateProfilesYaml:
    VALID = "my_profile:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n"

    def test_valid_text_has_no_issues(self):
        assert validate_profiles_yaml(self.VALID) == []

    def test_env_var_reference_is_accepted(self):
        text = self.VALID.replace(
            "type: duckdb", "type: duckdb\n      password: \"{{ env_var('PW') }}\""
        )
        assert validate_profiles_yaml(text) == []

    def test_literal_secret_gets_its_code(self):
        text = self.VALID.replace(
            "type: duckdb", "type: duckdb\n      password: hunter2"
        )
        issues = validate_profiles_yaml(text)
        assert [i.code for i in issues] == ["render.literal_secret_in_profile"]
        assert "hunter2" not in issues[0].message

    def test_broken_yaml_gets_invalid_code(self):
        issues = validate_profiles_yaml("a: [unclosed")
        assert [i.code for i in issues] == ["render.invalid_profiles"]

    def test_non_mapping_gets_invalid_code(self):
        issues = validate_profiles_yaml("- just\n- a list\n")
        assert [i.code for i in issues] == ["render.invalid_profiles"]

    def test_profile_name_check_applies(self):
        issues = validate_profiles_yaml(self.VALID, profile_name="missing")
        assert [i.code for i in issues] == ["render.invalid_profiles"]


class TestSecretBypasses:
    """Regressions for literal secrets that slipped past the checks."""

    SMUGGLED = "{{ env_var('A') }}hunter2{{ env_var('B') }}"

    @pytest.mark.parametrize(
        "value",
        [
            "{{ env_var('DBT_PASSWORD') }}",
            '{{ env_var("DBT_PASSWORD") }}',
            "{{ env_var('DBT_PASSWORD', '') }}",
            "  {{env_var('DBT_PASSWORD','')}}  ",
        ],
    )
    def test_single_env_var_reference_accepted(self, value):
        render_profiles_yml(_profiles(password=value))

    @pytest.mark.parametrize(
        "value",
        [
            "{{ env_var('A') }}hunter2{{ env_var('B') }}",
            "{{ env_var('A') }} {{ env_var('B') }}",
            "{{ env_var('A') ~ 'hunter2' }}",
            "{{ env_var(hunter2) }}",
            "{{ env_var('') }}",
            # A non-empty default is used whenever the variable is unset.
            "{{ env_var('DBT_PASSWORD', 'hunter2') }}",
            "  {{env_var('DBT_PASSWORD','fallback')}}  ",
            '{{ env_var("DBT_PASSWORD", "hunter2") }}',
        ],
    )
    def test_anything_but_one_env_var_call_rejected(self, value):
        with pytest.raises(LiteralSecretError):
            render_profiles_yml(_profiles(password=value))

    def test_smuggled_literal_rejected_by_validate(self):
        text = (
            "my_profile:\n  target: dev\n  outputs:\n    dev:\n"
            "      type: duckdb\n"
            f'      password: "{self.SMUGGLED}"\n'
        )
        issues = validate_profiles_yaml(text)
        assert [i.code for i in issues] == ["render.literal_secret_in_profile"]

    def test_profile_level_secret_rejected(self):
        profiles = _profiles()
        profiles["my_profile"]["password"] = "hunter2"
        with pytest.raises(LiteralSecretError, match="my_profile.password"):
            render_profiles_yml(profiles)

    def test_profile_level_secret_rejected_by_validate(self):
        text = (
            "my_profile:\n  target: dev\n  password: hunter2\n"
            "  outputs:\n    dev:\n      type: duckdb\n"
        )
        issues = validate_profiles_yaml(text)
        assert [i.code for i in issues] == ["render.literal_secret_in_profile"]

    def test_profile_and_output_names_are_not_secret_keys(self):
        """A profile or output called like a secret key is not a secret."""
        profiles = {
            "token": {
                "target": "password",
                "outputs": {"password": {"type": "duckdb"}},
            }
        }
        render_profiles_yml(profiles)

    def test_secret_inside_tuple_rejected(self):
        with pytest.raises(LiteralSecretError, match=r"extras\[0\]\.password"):
            render_profiles_yml(_profiles(extras=({"password": "hunter2"},)))

    def test_tuple_values_render_as_lists(self):
        content = render_profiles_yml(_profiles(scopes=("a", "b")))
        parsed = yaml.safe_load(content)
        assert parsed["my_profile"]["outputs"]["dev"]["scopes"] == ["a", "b"]


class TestReviewRegressions:
    """Second PR review: defaults, duplicate keys and recursive aliases."""

    HEAD = "p:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n"

    def test_non_empty_default_rejected_by_validate(self):
        text = self.HEAD + "      password: \"{{ env_var('PW', 'hunter2') }}\"\n"
        issues = validate_profiles_yaml(text)
        assert [i.code for i in issues] == ["render.literal_secret_in_profile"]
        assert "hunter2" not in issues[0].message

    def test_duplicate_key_hiding_a_literal_rejected(self):
        text = (
            self.HEAD
            + "      password: hunter2\n"
            + "      password: \"{{ env_var('PW') }}\"\n"
        )
        issues = validate_profiles_yaml(text)
        assert [i.code for i in issues] == ["render.invalid_profiles"]
        assert "'password'" in issues[0].message
        assert "hunter2" not in issues[0].message

    def test_duplicate_profile_rejected(self):
        issues = validate_profiles_yaml(self.HEAD + self.HEAD)
        assert [i.code for i in issues] == ["render.invalid_profiles"]

    @pytest.mark.parametrize(
        "extras",
        ["&loop [*loop]", "&loop {self: *loop}", "&loop [1, {nested: *loop}]"],
    )
    def test_recursive_alias_reported_not_crashed(self, extras):
        issues = validate_profiles_yaml(self.HEAD + f"      extras: {extras}\n")
        assert [i.code for i in issues] == ["render.invalid_profiles"]
        assert "recursive" in issues[0].message

    def test_recursive_python_value_rejected(self):
        loop: dict = {}
        loop["self"] = loop
        with pytest.raises(InvalidProfilesError, match="recursive"):
            render_profiles_yml(_profiles(extras=loop))

    def test_shared_alias_without_cycle_allowed(self):
        text = self.HEAD + "      a: &shared [1, 2]\n      b: *shared\n"
        assert validate_profiles_yaml(text) == []

    def test_merge_key_still_works(self):
        text = (
            "p:\n  target: dev\n  outputs:\n"
            "    base: &base\n      type: duckdb\n"
            "    dev:\n      <<: *base\n      path: x.duckdb\n"
        )
        assert validate_profiles_yaml(text) == []
