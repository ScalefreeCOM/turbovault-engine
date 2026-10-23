"""
Serialize a caller-supplied mapping of dbt profiles into ``profiles.yml``.

Like ``vars_block``, the engine stays agnostic about *which* adapter fields
exist: it renders whatever the caller supplies. Curation of adapters and their
field lists is owned by the consumer (Studio).

The one thing the engine does enforce is secret safety: a generated
``profiles.yml`` ends up on disk and in zip archives, so values of known secret
keys must be ``{{ env_var('...') }}`` references, never literals.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import yaml

from engine.services.generation.errors import Code, make_issue

if TYPE_CHECKING:
    from engine.services.generation.types import Issue

# Keys whose value is a credential in at least one dbt adapter. Matched
# case-insensitively at any depth of an output.
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


class _DuplicateKeyError(yaml.YAMLError):
    """A mapping in profiles.yml text names the same key twice."""


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode):
    """Build a mapping like SafeLoader does, but reject a key given twice.

    `safe_load` keeps only the last of two equal keys, so a literal
    `password: hunter2` followed by an env_var reference would pass the secret
    check while the text still holds the credential. Names the key and its
    line, never a value.
    """
    loader.flatten_mapping(node)
    seen = set()
    for key_node, _value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            duplicate = key in seen
        except TypeError:  # unhashable key; construct_mapping reports it
            continue
        if duplicate:
            raise _DuplicateKeyError(
                f"profiles.yml defines key {key!r} more than once "
                f"(line {key_node.start_mark.line + 1})"
            )
        seen.add(key)
    yield from loader.construct_yaml_map(node)


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys."""


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


class InvalidProfilesError(ValueError):
    """The ``profiles`` mapping is not a valid dbt profiles structure."""


class LiteralSecretError(ValueError):
    """A known secret key holds a literal value instead of an env_var reference."""


def render_profiles_yml(
    profiles: Mapping[str, Any] | None, profile_name: str | None = None
) -> str:
    """Render ``profiles.yml`` content from a caller-supplied mapping.

    Expected shape::

        {<profile>: {"target": <name>,
                     "outputs": {<name>: {"type": <adapter>, ...}}}}

    Values are rendered verbatim; keys keep their insertion order.

    `profile_name` is the profile dbt_project.yml refers to. When given, it
    must be a key of `profiles`, otherwise the generated project cannot run.

    Raises:
        LiteralSecretError: a known secret key holds a literal value. The
            message names where, never the value.
        InvalidProfilesError: the structure is invalid, `profile_name` is
            missing, or a value cannot be serialized.
    """
    _check_profiles(profiles, profile_name)
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


def validate_profiles_yaml(text: str, profile_name: str | None = None) -> list[Issue]:
    """Check a manually written ``profiles.yml`` the way generation checks one.

    Meant for callers (Studio) that accept profiles.yml text from a user: it
    parses the YAML and applies the same structure, profile-name and secret
    rules as `render_profiles_yml`. Returns an empty list when the text is
    acceptable; otherwise one error Issue per problem found.
    """
    try:
        parsed = yaml.load(text, Loader=_UniqueKeySafeLoader)  # noqa: S506 - safe
    except _DuplicateKeyError as exc:
        return [
            make_issue(
                severity="error",
                code=Code.RENDER_INVALID_PROFILES,
                stage="render",
                message=str(exc),
            )
        ]
    except yaml.YAMLError:
        return [
            make_issue(
                severity="error",
                code=Code.RENDER_INVALID_PROFILES,
                stage="render",
                message="profiles.yml is not valid YAML",
            )
        ]

    try:
        _check_profiles(parsed, profile_name)
    except LiteralSecretError as exc:
        code = Code.RENDER_LITERAL_SECRET_IN_PROFILE
        message = str(exc)
    except InvalidProfilesError as exc:
        code = Code.RENDER_INVALID_PROFILES
        message = str(exc)
    else:
        return []

    return [make_issue(severity="error", code=code, stage="render", message=message)]


def _check_profiles(profiles: Any, profile_name: str | None) -> None:
    """Run every rule that applies to a profiles mapping, in one place."""
    _validate_structure(profiles)
    for name, profile in profiles.items():
        # The whole profile is written out, so its own fields (beside
        # `target` and `outputs`) are scanned too.
        _check_secrets(
            {key: value for key, value in profile.items() if key != "outputs"},
            name,
        )
        for output_name, output in profile["outputs"].items():
            _check_secrets(output, f"{name}.outputs.{output_name}")
    if profile_name is not None and profile_name not in profiles:
        raise InvalidProfilesError(
            f"dbt_project.yml uses profile {profile_name!r}, but profiles.yml "
            "defines no such profile"
        )


def _validate_structure(profiles: Any) -> None:
    if not isinstance(profiles, Mapping):
        raise InvalidProfilesError("profiles must be a mapping")
    if not profiles:
        raise InvalidProfilesError("generate_profiles_yml is set but profiles is empty")
    for profile_name, profile in profiles.items():
        if not isinstance(profile_name, str) or not profile_name:
            raise InvalidProfilesError("profile names must be non-empty strings")
        if not isinstance(profile, Mapping):
            raise InvalidProfilesError(f"profile {profile_name!r} must be a mapping")
        outputs = profile.get("outputs")
        if not isinstance(outputs, Mapping) or not outputs:
            raise InvalidProfilesError(
                f"profile {profile_name!r} needs a non-empty 'outputs' mapping"
            )
        target = profile.get("target")
        if not isinstance(target, str) or target not in outputs:
            raise InvalidProfilesError(
                f"profile {profile_name!r}: 'target' must name one of its outputs"
            )
        for output_name, output in outputs.items():
            where = f"{profile_name}.outputs.{output_name}"
            if not isinstance(output_name, str):
                raise InvalidProfilesError(
                    f"profile {profile_name!r}: output names must be strings"
                )
            if not isinstance(output, Mapping):
                raise InvalidProfilesError(f"{where} must be a mapping")
            if not isinstance(output.get("type"), str) or not output["type"]:
                raise InvalidProfilesError(f"{where} needs an adapter 'type'")
            if any(not isinstance(key, str) for key in output):
                raise InvalidProfilesError(f"{where}: keys must be strings")


def _check_secrets(value: Any, path: str, _ancestors: tuple[int, ...] = ()) -> None:
    """Reject literal values under known secret keys, at any depth.

    `_ancestors` holds the containers on the current path. A container that
    contains itself (a recursive YAML alias such as `&loop [*loop]`) is
    rejected instead of recursing forever; one shared without a cycle is fine.
    """
    if isinstance(value, (Mapping, list, tuple)):
        if id(value) in _ancestors:
            raise InvalidProfilesError(f"{path} contains itself (recursive YAML alias)")
        _ancestors = (*_ancestors, id(value))
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if isinstance(key, str) and key.lower() in SECRET_KEYS:
                if not _is_allowed_secret_value(child):
                    raise LiteralSecretError(
                        f"{child_path} holds a literal secret; use an "
                        "{{ env_var('...') }} reference instead"
                    )
            else:
                _check_secrets(child, child_path, _ancestors)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_secrets(item, f"{path}[{index}]", _ancestors)


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
