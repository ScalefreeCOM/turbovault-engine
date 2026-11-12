"""Bring dbt templates stored in the database in line with issue #442.

`turbovault init` copies the bundled templates into ModelTemplate once and
generation prefers those rows, so the bundled template changes of #442 never
reach an existing workspace on their own. Without them, stored output
attributes (generation_config) are partly ignored and renamed satellites or
snapshot controls get broken references (`<name>_v0` / `<name>_v1` were
hard-coded).

This migration applies the same edits to every stored dbt template:

- `config()` gets the `model_config` settings, and the tags line (SQL and
  YAML) is replaced by `model_tags` when set;
- satellite v1, PIT, reference table and snapshot control templates refer to
  the resolved model names instead of appending `_v0` / `_v1`;
- the PIT writes its own post_hook only when the stored config sets none.

Each edit only applies where the exact text it replaces is found, so
templates that were customized there are left alone. The edits render the
same output as before when no attributes are stored and the default naming
patterns are used, so they are safe for customized templates too.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from django.db import migrations

# Tags line at the end of a SQL config() call, right after the
# `[% if materialization %]` block. Group 1: the default tags list, group 2:
# a trailing comma (PIT has a post_hook after it).
_SQL_TAGS = re.compile(r"\[% endif %\]\n    tags=(\[[^\n]*\])(,?)\n")
_YAML_TAGS = re.compile(r"\n      tags: (\[[^\n]*\])\n")
# The PIT's tags line (as `_sql_config_hook` leaves it) followed by its own
# post_hook. Group 1: the tags line, group 2: the post_hook setting.
_PIT_POST_HOOK = re.compile(
    r"(    tags=[^\n]*)\[% endif %\],\n(    post_hook=[^\n]*[^,\n])\n\) \}\}"
)
_SNAPSHOT_V0_NAME = re.compile(
    r"\[# Compute v0_name from name \(remove any suffix and add _v0\) #\]\n"
    r"\[% set base_name = [^\n]*%\]\n"
    r"\[% set control_v0_name = [^\n]*%\]\n\n"
)


def _sql_config_hook(content: str) -> str:
    if "model_config" in content:
        return content

    def replace(match: re.Match[str]) -> str:
        default_tags, comma = match.group(1), match.group(2)
        # `+%]` keeps the newline that trim_blocks would remove after the tag.
        end = "[% endif %]," if comma else "[% endif +%]"
        return (
            "[% endif %]\n"
            "[% for key, value in (model_config or {}).items() %]\n"
            "    [[ key ]]=[[ value ]],\n"
            "[% endfor %]\n"
            f"    tags=[% if model_tags %][[ model_tags ]][% else %]{default_tags}"
            f"{end}\n"
        )

    return _SQL_TAGS.sub(replace, content, count=1)


def _yaml_tags_hook(content: str) -> str:
    if "model_tags" in content:
        return content
    return _YAML_TAGS.sub(
        lambda m: (
            "\n      tags: [% if model_tags %][[ model_tags ]][% else %]"
            f"{m.group(1)}[% endif +%]\n"
        ),
        content,
        count=1,
    )


def _replacing(*pairs: tuple[str, str]) -> Callable[[str], str]:
    def apply(content: str) -> str:
        for old, new in pairs:
            content = content.replace(old, new)
        return content

    return apply


def _pit_post_hook(content: str) -> str:
    """Write the PIT's own post_hook only when the stored config sets none."""
    return _PIT_POST_HOOK.sub(
        lambda m: (
            "[% if 'post_hook' not in (model_config or {}) %]\n"
            f"{m.group(2)},\n"
            "[% endif %]\n"
            f"{m.group(1)}[% endif +%]\n"
            ") }}"
        ),
        content,
        count=1,
    )


def _pit_sql(content: str) -> str:
    content = content.replace(
        "[% for sat in satellites %]\n    - [[ sat ]]_v0",
        "[% for sat in satellite_models %]\n    - [[ sat ]]",
    )
    return _pit_post_hook(content)


def _snapshot_v1_sql(content: str) -> str:
    return _SNAPSHOT_V0_NAME.sub("", content, count=1)


# Edits by entity type, beyond the config/tags hooks every template gets.
_SQL_EDITS: dict[str, Callable[[str], str]] = {
    "satellite_v1": _replacing(
        ("ref_sat_v0: [[ satellite_name ]]_v0", "ref_sat_v0: [[ v0_name ]]"),
        ("sat_v0: [[ satellite_name ]]_v0", "sat_v0: [[ v0_name ]]"),
    ),
    "pit": _pit_sql,
    "reference_table": _replacing(
        (
            "    [[ sat.satellite_name ]]_v1:",
            "    [[ satellite_models[sat.satellite_name] ]]:",
        )
    ),
    "snapshot_control_v1": _snapshot_v1_sql,
}
_YAML_EDITS: dict[str, Callable[[str], str]] = {
    "satellite_v1": _replacing(
        ("  - name: [[ satellite_name ]]_v1", "  - name: [[ model_name ]]")
    ),
    "snapshot_control_v0": _replacing(
        ("  - name: [[ name ]]_v0", "  - name: [[ model_name ]]")
    ),
    "snapshot_control_v1": _replacing(
        ("  - name: [[ name ]]_v1", "  - name: [[ model_name ]]")
    ),
}


def _edit(content: str, edits: list[Callable[[str], str]]) -> str:
    """Apply `edits`, keeping the content's line endings."""
    if not content:
        return content
    crlf = "\r\n" in content
    text = content.replace("\r\n", "\n") if crlf else content
    for edit in edits:
        text = edit(text)
    return text.replace("\n", "\r\n") if crlf else text


def upgrade_sql(entity_type: str, content: str) -> str:
    """The #442 version of a stored dbt SQL template."""
    edits = [_sql_config_hook]
    if entity_type in _SQL_EDITS:
        edits.append(_SQL_EDITS[entity_type])
    return _edit(content, edits)


def upgrade_yaml(entity_type: str, content: str) -> str:
    """The #442 version of a stored dbt YAML template."""
    edits = [_yaml_tags_hook]
    if entity_type in _YAML_EDITS:
        edits.append(_YAML_EDITS[entity_type])
    return _edit(content, edits)


def forwards(apps, schema_editor) -> None:
    ModelTemplate = apps.get_model("engine", "ModelTemplate")
    for template in ModelTemplate.objects.filter(framework="dbt"):
        sql = upgrade_sql(template.entity_type, template.sql_template_content or "")
        yaml = upgrade_yaml(template.entity_type, template.yaml_template_content or "")
        changed = []
        if sql != (template.sql_template_content or ""):
            template.sql_template_content = sql
            changed.append("sql_template_content")
        if yaml != (template.yaml_template_content or ""):
            template.yaml_template_content = yaml
            changed.append("yaml_template_content")
        if changed:
            template.save(update_fields=changed)


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0019_generation_config"),
    ]

    # The old templates keep working with the new generator for unchanged
    # projects, so there is nothing to undo.
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
