"""
Serialize a caller-supplied mapping of dbt profiles into ``profiles.yml``.

Like ``vars_block``, the engine stays agnostic about *which* profiles, targets
and adapter fields exist: it renders whatever the caller supplies. Curating
adapters and their fields, and checking that the mapping is a usable dbt
profile, is owned by the consumer (Studio).

The one thing the engine does enforce is secret safety: a generated
``profiles.yml`` ends up on disk and in zip archives, so values of known secret
keys must be ``{{ env_var('...') }}`` references, never literals.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import yaml

# A key is a credential when it ends in one of these (case-insensitive, at any
# depth of the mapping): `password`, `oauth_client_secret` (Snowflake),
# `aws_secret_access_key` / `aws_session_token` (Athena), `jwt_token` (Trino),
# `private_key_passphrase`, … Suffixes rather than whole names catch adapter
# prefixes, while fields like `token_uri` or `private_key_path` (a file path)
# stay plain.
SECRET_KEY_SUFFIXES: tuple[str, ...] = (
    "password",
    "passphrase",
    "secret",
    "token",
    "private_key",
    "access_key",
    "api_key",
)
# Credential keys matched by their whole name.
SECRET_KEYS: frozenset[str] = frozenset({"pass", "keyfile_json"})

# BigQuery's service-account key: dbt-bigquery needs a mapping, so besides an
# env_var reference it may be given inline, with its own secret fields
# (`private_key`, …) checked like any other.
_KEYFILE_JSON = "keyfile_json"

# A value consisting of exactly one dbt `env_var(...)` call whose arguments are
# a quoted variable name and an optional *empty* default, optionally piped to
# `as_native` (which turns a JSON variable into the mapping BigQuery's
# `keyfile_json` needs), e.g. `{{ env_var('DBT_PASSWORD') }}`,
# `{{ env_var("DBT_PASSWORD", "") }}` or `{{ env_var('BQ_KEYFILE') | as_native }}`.
# The name must be an identifier and nothing else may surround or follow the
# call, so no literal text slips through. A non-empty default is a literal
# secret too: dbt uses it whenever the variable is unset, and it is written
# into profiles.yml as it stands.
_ENV_VAR_REFERENCE = re.compile(
    r"""\s*\{\{\s*env_var\(\s*
        (['"])[A-Za-z_][A-Za-z0-9_]*\1  # variable name
        (?:\s*,\s*(['"])\2)?            # optional empty default
        \s*\)
        (?:\s*\|\s*as_native)?          # optional as_native filter
        \s*\}\}\s*""",
    re.VERBOSE,
)


def is_secret_key(key: object) -> bool:
    """Whether a profile field named `key` holds a credential."""
    if not isinstance(key, str):
        return False
    name = key.lower()
    return name in SECRET_KEYS or name.endswith(SECRET_KEY_SUFFIXES)


class InvalidProfilesError(ValueError):
    """The ``profiles`` value is not a mapping or cannot be written as YAML."""


class LiteralSecretError(ValueError):
    """A known secret key holds a literal value instead of an env_var reference."""


def render_profiles_yml(profiles: Mapping[str, Any] | None) -> str:
    """Render ``profiles.yml`` content from a caller-supplied mapping.

    Expected shape (not checked — that is the caller's concern)::

        {<profile>: {"target": <name>,
                     "outputs": {<name>: {"type": <adapter>, ...}}}}

    Values are rendered verbatim; keys keep their insertion order.

    Raises:
        LiteralSecretError: a known secret key, at any depth, holds anything
            but an empty value or one `env_var` reference without a default.
            The message names where, never the value.
        InvalidProfilesError: `profiles` is not a mapping or holds a value that
            cannot be written as YAML.
    """
    if not isinstance(profiles, Mapping):
        raise InvalidProfilesError("profiles must be a mapping")
    _check_secrets(profiles)
    try:
        return yaml.safe_dump(
            _plain(profiles),
            sort_keys=False,  # preserve caller insertion order
            default_flow_style=False,
            allow_unicode=True,
        )
    except yaml.YAMLError as exc:
        # Report no value — profiles may hold credentials.
        raise InvalidProfilesError(
            "profiles contains a value that cannot be serialized to YAML"
        ) from exc


def _check_secrets(value: Any, path: str = "") -> None:
    """Reject literal values under known secret keys, at any depth."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if (
                isinstance(key, str)
                and key.lower() == _KEYFILE_JSON
                and isinstance(child, Mapping)
            ):
                # An inline service-account key: check its own fields.
                _check_secrets(child, child_path)
            elif is_secret_key(key):
                if not _is_allowed_secret_value(child):
                    raise LiteralSecretError(
                        f"{child_path} holds a literal secret; use an "
                        "{{ env_var('...') }} reference without a default instead"
                    )
            else:
                _check_secrets(child, child_path)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_secrets(item, f"{path}[{index}]")


def _is_allowed_secret_value(value: Any) -> bool:
    if value is None or value == "":
        return True
    return isinstance(value, str) and bool(_ENV_VAR_REFERENCE.fullmatch(value))


def _plain(value: Any) -> Any:
    """Turn any Mapping into a dict and any tuple into a list for ``safe_dump``."""
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value
