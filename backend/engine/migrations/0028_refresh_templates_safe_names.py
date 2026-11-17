"""Refresh DB templates that still hold the unedited pre-#450 bundled template.

The bundled dbt templates now write names safely (#450): source table and
column names go through ``yaml_scalar`` / ``yaml_single_quote``, subject-area
tags and dbt source names through ``technical_name``, and the PIT clean-up
hook's snapshot control name through ``jinja_string``. DB templates take
precedence over the bundled files, so a workspace seeded before this change
would keep writing names unescaped.

Copies of older bundled versions are refreshed by ``0020`` and ``0027``, which
read the bundled files as they are when they run and so already land on these
templates. This one covers copies of #238's bundled version (commit 3d4be12),
the one right before #450. As there, a template field is refreshed only when
its content is byte-identical (line endings aside) to that version, i.e. the
user never edited it.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from django.db import migrations

logger = logging.getLogger(__name__)

# (framework, entity_type, template_type) -> sha256 of #238's bundled content
# (commit 3d4be12), with CRLF normalised to LF. Generated from git; only the
# templates #450 changes.
PRE_450_BUNDLED_HASHES: dict[tuple[str, str, str], frozenset[str]] = {
    ("dbt", "hub_reference", "sql"): frozenset(
        {"7623a63f81aecc6816c7825b75bf818e5d122a98429f412a38cac6507a216c4a"}
    ),
    ("dbt", "hub_standard", "sql"): frozenset(
        {"a6ac351615d28b2d6a6687331da844512c9b90a3a2335621f4f9c316503b064f"}
    ),
    ("dbt", "link_non_historized", "sql"): frozenset(
        {"13d2b1756c145a1f67536e36039b7c96d0b524e4ff25c1e2efab5d64e03f88d3"}
    ),
    ("dbt", "link_standard", "sql"): frozenset(
        {"3e4c0361a044c6b9a801853ab767dd7c58f34e87a4f157f5518343c0b4e2303f"}
    ),
    ("dbt", "pit", "sql"): frozenset(
        {"a598f6fb05613e227e7d3d31bcbd9caeed8f6743dcc1a8209fce838506e8849a"}
    ),
    ("dbt", "reference_table", "sql"): frozenset(
        {"a2c4d0485478c2211c6ea9f90d62d2d42d450aa5d422577ee0358d4885e6bbd2"}
    ),
    ("dbt", "satellite_effectivity", "sql"): frozenset(
        {"c49b9e297f4030da71ed4f71e8abb0eb683111b4d16b55ff978728793a8e7062"}
    ),
    ("dbt", "satellite_multi_active", "sql"): frozenset(
        {"3d77043c57b636f8105010791ac17d8b08da05c00abdea4518d9505f254413b9"}
    ),
    ("dbt", "satellite_non_historized", "sql"): frozenset(
        {"abc97fbd003cfae214a38c888d996e015ee59fcb84c73c21f7447c1433251328"}
    ),
    ("dbt", "satellite_record_tracking", "sql"): frozenset(
        {"3c243c9106566b2cbeda5bcc3a69652f6bca83a25970fc927524931283f34646"}
    ),
    ("dbt", "satellite_reference", "sql"): frozenset(
        {"39c3d9df6d08a8a720fc90cfdb93d3ab40f442851b95ec7e7198ebce54cdd5dd"}
    ),
    ("dbt", "satellite_standard", "sql"): frozenset(
        {"10f4b60c9cf0d85c9c920f03aee732f6b84f67afa942121fc9488d94ae75aa20"}
    ),
    ("dbt", "satellite_v1", "sql"): frozenset(
        {"0e9f7028e2a093e18878a6ffc2462793f30c5dd5e5244bfdad8b26e9d95f2c40"}
    ),
    ("dbt", "stage", "sql"): frozenset(
        {"7c741eb190a4d798fd476c3df9a485ee1759d59532410cc648ef8aed8dcff452"}
    ),
    ("dbt", "hub_reference", "yaml"): frozenset(
        {"939271641de316402ee3b42154672f1e8fccb27847aa3c1a464bbbbb293bddea"}
    ),
    ("dbt", "hub_standard", "yaml"): frozenset(
        {"1974239c21edae9978ff991eb847b652e6ea88cc3fb6cfaf7a02819e4e2345e4"}
    ),
    ("dbt", "link_non_historized", "yaml"): frozenset(
        {"1925e90ce04437cbd18b1fe894de3f9dae77bdaf2ed9fd9a0476df19c1b8acb7"}
    ),
    ("dbt", "link_standard", "yaml"): frozenset(
        {"11242e66f39276f29ef3d1bd622bf51344f07d88f459cd238064c87a4062e26c"}
    ),
    ("dbt", "satellite_effectivity", "yaml"): frozenset(
        {"4943ebb5466ae2d0e5d6906463ceb141580d85cbae2677a46ee95de3ea3d9aeb"}
    ),
    ("dbt", "satellite_multi_active", "yaml"): frozenset(
        {"1ce0c6e37c748596f8c650034f73ac6f6116e523cd8c8f2ad2627090ed0f9796"}
    ),
    ("dbt", "satellite_non_historized", "yaml"): frozenset(
        {"3296adf953b36043f9330a6ba808d0c256e5e7e0f742ea65c453fad6694452fd"}
    ),
    ("dbt", "satellite_record_tracking", "yaml"): frozenset(
        {"500eb7f7d12526ffda2dd00b6210ab9861e6fbee842c6781aa5bf37a80ff8d52"}
    ),
    ("dbt", "satellite_reference", "yaml"): frozenset(
        {"ee7948d713cc5c07a15e022756c80fbc5d1bdef751f29c77c22c73bf832407af"}
    ),
    ("dbt", "satellite_standard", "yaml"): frozenset(
        {"1d3cf03259cc4188f1b74b18312bbff90924cca592582103ffd0d84ae21523de"}
    ),
    ("dbt", "satellite_v1", "yaml"): frozenset(
        {"16375ae9d426fd745a81669949828cdcc5c09d987948a9dc133acce9baef7329"}
    ),
    ("dbt", "stage", "yaml"): frozenset(
        {"4904c897e75b9e6b282af3c36ee8d0f81d219e6194fbab87f349cc62aaa506b2"}
    ),
}


def refresh_bundled_templates(apps: Any, schema_editor: Any) -> None:
    """Replace unedited copies of #238's templates with the current bundle."""
    # Imported here: the bundled files are read as they are when the
    # migration runs, so an old workspace always lands on the current ones.
    from engine.services.generation.template_resolver import bundled_templates

    # Module names starting with a digit can't be imported with `import`.
    content_hash = importlib.import_module(
        "engine.migrations.0027_refresh_templates_after_235"
    )._content_hash

    model_template = apps.get_model("engine", "ModelTemplate")
    field_by_type = {"sql": "sql_template_content", "yaml": "yaml_template_content"}

    refreshed = 0
    for template in bundled_templates("dbt"):
        superseded = PRE_450_BUNDLED_HASHES.get(
            ("dbt", template.entity_type, template.template_type)
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
        ("engine", "0027_refresh_templates_after_235"),
    ]

    operations = [
        migrations.RunPython(
            refresh_bundled_templates, reverse_code=migrations.RunPython.noop
        ),
    ]
