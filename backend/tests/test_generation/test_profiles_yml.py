"""Tests for render_profiles_yml(): structure, verbatim rendering, secret safety."""

import pytest
import yaml
from engine.services.generation.profiles_yml import (
    InvalidProfilesError,
    LiteralSecretError,
    render_profiles_yml,
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

    def test_shape_is_left_to_the_caller(self):
        """Only secrets are checked; a mapping dbt cannot use renders as given."""
        profiles = {"p": {"target": "prod", "outputs": {"dev": {"host": "h"}}}}
        assert yaml.safe_load(render_profiles_yml(profiles)) == profiles

    def test_non_serializable_value_raises(self):
        with pytest.raises(InvalidProfilesError, match="serialized"):
            render_profiles_yml(_profiles(threads=object()))


class TestSecretBypasses:
    """Regressions for literal secrets that slipped past the checks."""

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

    def test_profile_level_secret_rejected(self):
        profiles = _profiles()
        profiles["my_profile"]["password"] = "hunter2"
        with pytest.raises(LiteralSecretError, match="my_profile.password"):
            render_profiles_yml(profiles)

    def test_secret_inside_tuple_rejected(self):
        with pytest.raises(LiteralSecretError, match=r"extras\[0\]\.password"):
            render_profiles_yml(_profiles(extras=({"password": "hunter2"},)))

    def test_tuple_values_render_as_lists(self):
        content = render_profiles_yml(_profiles(scopes=("a", "b")))
        parsed = yaml.safe_load(content)
        assert parsed["my_profile"]["outputs"]["dev"]["scopes"] == ["a", "b"]


class TestFinalReviewSecrets:
    """Final review: suffix-matched secret keys, identifier-only env_var names,
    `| as_native` and inline BigQuery keyfile_json."""

    @pytest.mark.parametrize(
        "key",
        [
            "oauth_client_secret",  # Snowflake
            "aws_secret_access_key",  # Athena
            "aws_session_token",  # Athena
            "jwt_token",  # Trino
            "private_key_passphrase",
            "pass",
            "keyfile_json",
        ],
    )
    def test_adapter_secret_keys_rejected(self, key):
        with pytest.raises(LiteralSecretError, match=key):
            render_profiles_yml(_profiles(**{key: "hunter2"}))

    @pytest.mark.parametrize(
        "key", ["token_uri", "private_key_path", "private_key_id", "authenticator"]
    )
    def test_non_secret_fields_stay_plain(self, key):
        content = render_profiles_yml(_profiles(**{key: "some/value"}))
        output = yaml.safe_load(content)["my_profile"]["outputs"]["dev"]
        assert output[key] == "some/value"

    def test_literal_hidden_in_a_quoted_variable_name_rejected(self):
        with pytest.raises(LiteralSecretError):
            render_profiles_yml(
                _profiles(password="{{ env_var('A) }}hunter2{{ env_var(B') }}")
            )

    @pytest.mark.parametrize(
        "value",
        [
            "{{ env_var('BQ_KEYFILE') | as_native }}",
            "{{env_var('BQ_KEYFILE')|as_native}}",
        ],
    )
    def test_as_native_allowed(self, value):
        content = render_profiles_yml(_profiles(keyfile_json=value))
        output = yaml.safe_load(content)["my_profile"]["outputs"]["dev"]
        assert output["keyfile_json"] == value

    def test_inline_keyfile_json_with_env_var_secrets_allowed(self):
        keyfile = {
            "type": "service_account",
            "project_id": "my-project",
            "private_key_id": "abc123",
            "private_key": "{{ env_var('BQ_PRIVATE_KEY') }}",
            "client_email": "dbt@example.com",
            "token_uri": "https://oauth2.example.com/token",
        }
        content = render_profiles_yml(_profiles(keyfile_json=keyfile))
        output = yaml.safe_load(content)["my_profile"]["outputs"]["dev"]
        assert output["keyfile_json"] == keyfile

    def test_inline_keyfile_json_with_literal_key_rejected(self):
        keyfile = {"type": "service_account", "private_key": "-----BEGIN KEY-----"}
        with pytest.raises(LiteralSecretError, match=r"keyfile_json\.private_key"):
            render_profiles_yml(_profiles(keyfile_json=keyfile))

    def test_other_secret_keys_still_reject_mappings(self):
        with pytest.raises(LiteralSecretError):
            render_profiles_yml(_profiles(password={"value": "hunter2"}))
