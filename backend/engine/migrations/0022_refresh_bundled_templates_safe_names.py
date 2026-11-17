"""Refresh DB templates that still hold the unedited pre-#450 bundled template.

The bundled dbt templates now write names safely (#450): source table and
column names go through ``yaml_scalar`` / ``yaml_single_quote``, subject-area
tags and dbt source names through ``technical_name``, and the PIT clean-up
hook's snapshot control name through ``jinja_string``. DB templates take
precedence over the bundled files, so a workspace seeded before this change
would keep writing names unescaped.

As in ``0020_refresh_bundled_templates``, a template field is refreshed only
when its content is byte-identical (line endings aside) to an earlier bundled
version, i.e. the user never edited it. ``PRE_450_BUNDLED_HASHES`` holds the
sha256 of the version each changed template had right before #450; the
versions ``0020`` knows are checked too, for workspaces whose templates that
migration left alone because they were edited and were later reset.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from django.db import migrations

logger = logging.getLogger(__name__)

# (framework, entity_type, template_type) -> sha256 of the bundled content
# right before #450, with CRLF normalised to LF.
PRE_450_BUNDLED_HASHES: dict[tuple[str, str, str], frozenset[str]] = {
    ("dbt", "hub_reference", "sql"): frozenset(
        {"4432bb909ec64c19b33bb6ece6d151f2fd1278456e2059c3d98ff5e01e92acf0"}
    ),
    ("dbt", "hub_reference", "yaml"): frozenset(
        {"31f4e4375f7c7a56d8e59b983f73e50935f0a5af53d707f3b27008f239587e54"}
    ),
    # The pre-#450 file ends in a lone "\r". Seeding reads it with universal
    # newlines, so DB rows hold a trailing "\n" instead: both hashes needed.
    ("dbt", "hub_standard", "sql"): frozenset(
        {
            "4c5237aa279233366cce9292d5f1dd9482285e115cd7625f0d1b6bdb95d5ed88",
            "f298b2741236c61b9d472f790dad304c60a059d39dda35bfb8d10941692c1a5d",
        }
    ),
    ("dbt", "hub_standard", "yaml"): frozenset(
        {"492c3eaf8f141539d09e4a8cd935b7e28a840ede835761e2ea6b12250fc64f55"}
    ),
    ("dbt", "link_non_historized", "sql"): frozenset(
        {"7b009ff8636aebfd7a563325889917af94f74726283a33e3e423e5b246272598"}
    ),
    ("dbt", "link_non_historized", "yaml"): frozenset(
        {"452b65f4b17dcd36ffbfd0c6703a2acb99fdf4b4744cb7a78ea7190bad990282"}
    ),
    ("dbt", "link_standard", "sql"): frozenset(
        {"c384e55a7868fc6340bf4c239be351f7737a6b135247aa72a427689e3c513c66"}
    ),
    ("dbt", "link_standard", "yaml"): frozenset(
        {"0948e9e34a1fb18d3157c32a7faa2adb983b7cb68e5ce05614f57e2516861780"}
    ),
    ("dbt", "pit", "sql"): frozenset(
        {"3a8c5e1374bc3555d42ddef9fa74b47de080109c336d539d72293adead61e2d6"}
    ),
    ("dbt", "prestage", "yaml"): frozenset(
        {"f40194867b5e03c9be55d258e17131abd94dd5965c999a89d933f37eafb34925"}
    ),
    ("dbt", "reference_table", "sql"): frozenset(
        {"a9652f955e75c454499c1257c0164f9bf0f51067c2cc8464c3c92d2a057def79"}
    ),
    ("dbt", "satellite_effectivity", "sql"): frozenset(
        {"e4de52e26d48bfa3d4066d6d7cdef705ae42c3da2f5c9c5cadfb50ad29389788"}
    ),
    ("dbt", "satellite_effectivity", "yaml"): frozenset(
        {"39c61d3aa0d56c3b6db4a8b14795dcbd8bed4cdb07b6db0fa4d9eed64b6fdf1d"}
    ),
    ("dbt", "satellite_multi_active", "sql"): frozenset(
        {"be731816957c9f1f6ed1c10b17ea802a9466cf3e6d4190b87eb5458bda070ced"}
    ),
    ("dbt", "satellite_multi_active", "yaml"): frozenset(
        {"a0af410db92b4e1e8c0315448e1786ff24c209284011995b474b01754725da9d"}
    ),
    ("dbt", "satellite_non_historized", "sql"): frozenset(
        {"7b011d95ece224cb8432fd91673a14f8172fb103390d86ac0a90f9eafc0340ca"}
    ),
    ("dbt", "satellite_non_historized", "yaml"): frozenset(
        {"bd0681a4f4798585fe36af98306c149c68066dc27b9ff6fe13f68c5894e93697"}
    ),
    ("dbt", "satellite_record_tracking", "sql"): frozenset(
        {"634c1643754180f270b4e071f001de395d51d051e1bc1b276d3b2301592842a6"}
    ),
    ("dbt", "satellite_record_tracking", "yaml"): frozenset(
        {"6198930f3be6bd90f1fe3e07db1855a227105f176ab67e794e4c566e9bdd312f"}
    ),
    ("dbt", "satellite_reference", "sql"): frozenset(
        {"473c915e42661aebcd52a971c5a643eff2bee7a8f7268c1db14e8694e426348b"}
    ),
    ("dbt", "satellite_reference", "yaml"): frozenset(
        {"8ad2c80d7f5e24d4fddad234561255bd6820c3a419159151b424832fba80cac3"}
    ),
    ("dbt", "satellite_standard", "sql"): frozenset(
        {"5a71ddf3fd10283de81a160808d50e847cba6c23cc5a8fcefb6ecdbbfeb29744"}
    ),
    ("dbt", "satellite_standard", "yaml"): frozenset(
        {"8745e3a92c1fc3425e03310fa71f76b92ae2b3fea4f06f7b300ee6f7253fa179"}
    ),
    ("dbt", "satellite_v1", "sql"): frozenset(
        {"ba6e0b56f5279396d220b10d316759e112dbf880d1676b3225e4aba167994d19"}
    ),
    ("dbt", "satellite_v1", "yaml"): frozenset(
        {"4524aaef9f04afdd37eb8696b699893e3f1bcfc88b11d3f9da2dd34ba11c01be"}
    ),
    ("dbt", "stage", "sql"): frozenset(
        {"3dbceba875f998a8358e6d6a9a0cd39691716198c23ed394fb17eaa30000482e"}
    ),
    ("dbt", "stage", "yaml"): frozenset(
        {"8725b9b2767cb83a29a89c0963f1fd38b0c65c33fec56049b68d85bbbaba6b35"}
    ),
}


def refresh_bundled_templates(apps: Any, schema_editor: Any) -> None:
    """Replace unedited pre-#450 template content with the current bundle."""
    # Imported here: the bundled files are read as they are when the
    # migration runs, so an old workspace always lands on the current ones.
    from engine.services.generation.template_resolver import bundled_templates

    # Module names starting with a digit can't be imported with `import`.
    earlier = importlib.import_module(
        "engine.migrations.0020_refresh_bundled_templates"
    )
    content_hash = earlier._content_hash

    model_template = apps.get_model("engine", "ModelTemplate")
    field_by_type = {"sql": "sql_template_content", "yaml": "yaml_template_content"}

    refreshed = 0
    for template in bundled_templates("dbt"):
        key = ("dbt", template.entity_type, template.template_type)
        superseded = PRE_450_BUNDLED_HASHES.get(key, frozenset()) | (
            earlier.SUPERSEDED_BUNDLED_HASHES.get(key, frozenset())
        )
        if not superseded:
            continue
        field_name = field_by_type[template.template_type]
        current = template.path.read_text(encoding="utf-8")
        rows = model_template.objects.filter(
            framework="dbt", entity_type=template.entity_type
        )
        for row in rows:
            if content_hash(getattr(row, field_name)) in superseded:
                setattr(row, field_name, current)
                row.save(update_fields=[field_name])
                refreshed += 1
    if refreshed:
        logger.info("Refreshed %d unedited bundled template field(s)", refreshed)


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0021_merge_0019_prestages_0020_refresh_bundled_templates"),
    ]

    operations = [
        migrations.RunPython(
            refresh_bundled_templates, reverse_code=migrations.RunPython.noop
        ),
    ]
