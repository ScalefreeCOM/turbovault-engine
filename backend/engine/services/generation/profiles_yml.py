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

# Keys whose value is a credential in at least one dbt adapter. Matched
# case-insensitively at any depth of the mapping.
SECRET_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "pass",
        "token",
        "private_key",
        "private_key_passphrase",
        "client_secret",
        "keyfile_json",
        "refresh_token",
        "access_token",
        "secret",
        "api_key",
    }
)

# A value consisting of exactly one dbt `env_var(...)` call whose arguments are
# a quoted variable name and an optional *empty* default, e.g.
# `{{ env_var('DBT_PASSWORD') }}` or `{{ env_var("DBT_PASSWORD", "") }}`.
# Nothing else may surround or follow it, so no literal text slips through.
# A non-empty default is a literal secret too: dbt uses it whenever the
# variable is unset, and it is written into profiles.yml as it stands.
_ENV_VAR_REFERENCE = re.compile(
    r"""^\s*\{\{\s*env_var\(\s*
        (['"])[^'"]+\1                  # variable name
        (?:\s*,\s*(['"])\2)?            # optional empty default
        \s*\)\s*\}\}\s*$""",
    re.VERBOSE,
)


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
            if isinstance(key, str) and key.lower() in SECRET_KEYS:
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
    return isinstance(value, str) and bool(_ENV_VAR_REFERENCE.match(value))


def _plain(value: Any) -> Any:
    """Turn any Mapping into a dict and any tuple into a list for ``safe_dump``."""
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value
