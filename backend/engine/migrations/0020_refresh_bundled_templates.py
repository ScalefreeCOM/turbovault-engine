"""Refresh DB templates that still hold an unedited, older bundled template.

Templates are seeded into ``ModelTemplate`` once, when a workspace is created,
and DB templates take precedence over the bundled files. Workspaces seeded
before the output-attributes change (#442) therefore kept templates that
hardcode the ``_v0``/``_v1`` model names and ignore the new ``v0_name``,
``v1_name``, ``satellite_v0_names`` and ``model_*`` variables, which breaks
references to models with stored names.

A template field is refreshed only when its content is byte-identical (line
endings aside) to an earlier version of the bundled file, i.e. the user never
edited it. ``SUPERSEDED_BUNDLED_HASHES`` lists the sha256 of every earlier git
version of each bundled per-entity template. Edited templates are left alone.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from django.db import migrations

logger = logging.getLogger(__name__)

# (framework, entity_type, template_type) -> sha256 of the content of every
# earlier bundled version, with CRLF normalised to LF. Generated from git
# history; the SQLMesh templates have not changed since they were added.
SUPERSEDED_BUNDLED_HASHES: dict[tuple[str, str, str], frozenset[str]] = {
    ("dbt", "hub_reference", "sql"): frozenset(
        {
            "098772f5528f9be94fcb389edb922f69be97d39c8f83a1fce5a72cb6c2a9bae0",
            "729fcb2c515ca00b3335f494a644e53e7dce138b23140715a854585836cc9ce2",
            "7d337b7bfc5f3f938c3c449b1fb5ff7345470e6edbaff41c5315db6952c5a770",
            "ac52e1a2e9e331fd6630bbef6846c1462f0c18fa39d538ddc5f979bc0ac08176",
            "ca412354225b7f116927cc31f051f193c5aa85a1f89c5d037e43ef24f286457f",
            "d09e7981e90e62852538586bba1a83f15755d449042c70a2e4ada76bd2a32cc8",
            "ee8a3ba9251531f1a940d9fa83ef786e8af0bab1cf67995a47eb0dc327b80c84",
        }
    ),
    ("dbt", "hub_standard", "sql"): frozenset(
        {
            "0a5a75d20854b76e65b1b07c27c0370aee80469e1c2cc865c00bf4ac6713c8be",
            "0e70b5c1733c2d76a3ae457b2d6f7129c5b86ca02974616fb4b805c699140250",
            "7d7637b6e4d77e3811190cc9e10fe249c056c14c04861d98e8b0caecc55fc49a",
            "843074fb3768eaac157ade6862d14bcca0a41e3e9d6b92915244bf6695540aed",
            "a730b126e43658dd7e4f2758fe72ff82f50cc9fb111ec77295958f31def68916",
            "e532e240415f17319e16716ebf38106a8c007c3842d57c64171720cf338568a2",
        }
    ),
    ("dbt", "link_non_historized", "sql"): frozenset(
        {
            "16aa6e32e33da25d1983b97db40a57b52825c21232ebcd2282b58531ff7bdaf4",
            "39d2708fb5047b5ae01e75e4b7dcc11477974f89c31882f2fcbea9fa5f6f2e75",
            "57038759c4dd36296e96c1251b56aa9120d8ad98c7accefbd3317ca5a764168c",
            "b6d4274bf4130211b07839fe5c7139799ae9248e4ffb2f7cb4dcaad253b66529",
            "eb69f33a1d8323d04559e9b9e4527e0ae3cd3ef843218897776f151ddbf77935",
        }
    ),
    ("dbt", "link_standard", "sql"): frozenset(
        {
            "5ac24599df251d6658007c95adb580d1f8b09c1db780467ac035bfdd7a62f2a4",
            "68f7ffd1912a859f637d3dc36e67811bb92e1c71596c193184f91af207219f12",
            "9d4be829a1180e8182cbe428104382a4bc9eb675d4472333f6fce34cefe9307d",
            "af7e5bb2bf738f219186b79dd4c448d7bbc4926dcd193bfbf2072f5ceb5b7875",
            "f40c5d6d1cbee30216ef1e5255318809047f98d0da4874523f8519ba9ae4a2e5",
        }
    ),
    ("dbt", "pit", "sql"): frozenset(
        {
            "13b7e19f8ca633dafef4e352947daa2cf8f1968d20d044e056e184b570528f08",
            "532a2775aa331dd2fe8686b6000959c57b33a8ac2f1b287832213ef59c47ace0",
            "b8f445e0f557030aa4b377d3b7c6557d2f156a1ffc447508f02aac00ad0c4e6c",
            "d14c6d9d3ab8274ee8bb3da2138b0689bb77be4ca6d0d7fe7e28db4f12e30d54",
        }
    ),
    ("dbt", "reference_table", "sql"): frozenset(
        {
            "18a6527ced612d20c79274c4954423b3ef7f32ed27b019b2351ac732d79c13bc",
            "19bf91548a5d2c5653012968599ce0c34af2d538a53d9f25eb2c282c2c5a48cf",
            "50aacda433c3317e308fa84249d94c7c4bdbcd0649c7295995359fdb1ba201a7",
            "9a8f992ebbea1295100b428a6f935570b069c91ea79329ba09fb70cf7cd05720",
            "a52d45781530cd64477af7ea46df93e4a6e300eca0f43ca86d50dd9fb1beae1e",
            "f576f6510eacdecdf076469752fade11e691644d5a11155a3ac9f37b6361572f",
            "ff0cf44df304a9e3ce3676652c33ac7935ca7e9f383f932edc9e865b9d82659a",
        }
    ),
    ("dbt", "satellite_effectivity", "sql"): frozenset(
        {
            "4de876fcd84203c59c0701349501bc4f7870355fe595ef80016d2fd9e3c428b4",
            "6e7642997e5dd91537a28d5282224229197e7e38c83695d4bf2fd309cf449e01",
            "8dc544f1a05468c2eae7940d6c93c8fc00a204b3db3be53fc1338c9b05c55185",
            "a98a9698088ad238a9ba9b73000ad438e0f40a73adda93828ab46ee2c3ceba07",
            "f7a116704895ea7f20f30198224358462601b71a7d6435e0820ad5cb12e14b84",
        }
    ),
    ("dbt", "satellite_multi_active", "sql"): frozenset(
        {
            "042507218c5333fa907197886d940b237d506fe5f76e083227856285ae1f1bf3",
            "3ea090e6ca5d163e764ea36e7ef0d90e289096ae4e774416f31d98d31164c69a",
            "45d9f482233b5f484f64054a0bb72e7010dcdca49d66975e53f67b87e9d92740",
            "675e7382542501028a5cdd060fb250ff903472d5205638b76c735856dfbb4c58",
            "f61cda335ad24536818a70a78f9130f73889b4d243cd2ab65d621c1f06d82073",
        }
    ),
    ("dbt", "satellite_non_historized", "sql"): frozenset(
        {
            "051cff6abb48140d4a730de18b88a1249469cb423355c7e016db42e1957ed706",
            "1fcd42b0a1928ab89aeddd5d7694a03353e5a04e8e7e089e0e378412953fefd9",
            "3ef5f9bd44e00bf6ac825a0fba0b8cf84ca63ac3c9177cb1a6ff0e7959eaeb4e",
            "b510615fa5a9452ef2a295842939759f7a241d8276a6934f5464ce84db021e3e",
        }
    ),
    ("dbt", "satellite_record_tracking", "sql"): frozenset(
        {
            "09b8d01e27c84925ff26d7c1d680696c448cffb1ad9aa87f22c229b6f19d9a95",
            "6c557b7dd3b9a11ab1d9a2844ef4365450cebc4d25896bf72729659585b87b91",
            "e3df5ac404b98779209be4730220c01b469d89b3d807686e5f91897bd668385a",
            "e5aa4c381ec52f52b40c5f9e4b8408beb9c5b1aba1f78c60549c39fb4291186c",
            "f43177c6209dffdacc7d5093f901df5b2134a0322a4ed738882d3d27eb70069a",
        }
    ),
    ("dbt", "satellite_reference", "sql"): frozenset(
        {
            "17490eb925d35df384e6ea491a1db8f5587f17b5fc5a41caaf823c0e64e2aeed",
            "464b8f0cb7dd52a5e8415e612632a72047edf387cfebd98a8d06f36e90426c81",
            "8d1a23d22ca908c453b60337a459d5939f596db7da4de6194cbade709a78aa25",
            "c71ad9f4495772769fb80aaa3f9b66916d3a9a184bf05a6bb0b536f36e6f79da",
        }
    ),
    ("dbt", "satellite_standard", "sql"): frozenset(
        {
            "550a1c477943bab9800e0b7c1b33330842ceb41d70ff863cc9fa84f75f9f98db",
            "c928d7cb9600efee9f2a00720b9ccc4a07c4e9fbb854d824e458f6c09f5003d5",
            "c9407fead0e9daa626bddf28ab1d8ad7b069202cdd54f76908949e31d77ba29f",
            "dae2e7c9c1d9df0a3f1d609c39afd14459d57455cd876f9cac7dd4a852c07ede",
        }
    ),
    ("dbt", "satellite_v1", "sql"): frozenset(
        {
            "5963ded429dc03509290c99f464dacff7974520ba9818bfda56ce77e0d7f0883",
            "bcd5b868bece00c831807c664e94c9b0026d835929faafd0df8b1e10ae817ce6",
            "bd4f993e2699f19fe8fa86e738df70aabd02d95a5ff709f8d711f6196ef35b55",
            "d0cc9eb3598023caee049bb7882d5cd51c897f9c3acf531e7783b26fa8d74d44",
        }
    ),
    ("dbt", "snapshot_control_v0", "sql"): frozenset(
        {
            "08c2cab4a5f85de7ba495594f9a04c1a908f5c2446cc87e55c44970669d0fc4f",
            "1d92976f42fddb0d3d45d491b1798681c08c7141dc687fec0b35a6d1e2774e22",
            "b910f9dfbe40704c149406aef46e15b200c03599f9bcd394e4da56d01e6f01e0",
            "c5c3f724071443d7cda0ae397c79d50220e80af382e9676de6f0ee26bd835cd1",
        }
    ),
    ("dbt", "snapshot_control_v1", "sql"): frozenset(
        {
            "2503191e02e267e382bb93df9fd011bd8bac156773e8cb240dc1dd86ea8b2885",
            "2a7e8716f812c3ab593496294406887dbf4d368f5f4416694fa4b91b8a0a34c0",
            "6f14debf23d74b301b6c07bac56549254d7025633b5b51991bfc3677c1062b04",
            "b4c72383181616aef8cc342e055cf87a0355370ccf45eaacfee1d2f6c171d36e",
        }
    ),
    ("dbt", "stage", "sql"): frozenset(
        {
            "352b9e8e37f5f03889bd76a9093e2afb4e92b1b6623586414fba67ae7fc1e60b",
            "419888028aea7bf49c0946e4aaf584a5e000a5e171813af7db1c97a522773bdb",
            "5ea5d9a048ec30f1bd6ea7dc04c07025a8a4d3618beae6e9ea670c0f3d22abc1",
            "82c480178ca5bd2eddb7e0b56faa97ba91c7998bff0affaa82d62ef0e97124a9",
            "959911a64dbf7190ccd83d619c59b1b119bd45a8b63a260c01626ce34bde2e16",
            "a3ac52a4e898f7ce97646a05ec974aa5ad301d96ed815d32a472f8190b8fd0ef",
            "d9da79a9531b9523514cff1128792f299df983905bfad61bc7e98e205acd7df5",
            "efeda55672cc1c182489f2d32f1558b9d12b70e911111c3acf1d0a0a02c3b6fb",
            "f090c0e390e114bbc95f2f177786e85d6f1ae5b943a6db3a5973f32e5384c458",
            "f3e9f2808b7713da83cf19e2cea56c4440a646c84504dd32ba2770ae1fad4d4c",
            "fe83fce652af08c62eff2655338d982e6cf68581280e577faf4e7592578370ff",
        }
    ),
    ("dbt", "hub_reference", "yaml"): frozenset(
        {
            "2f78443978c029bbc1c5da99362f064ee58cc17cafdbabb1cb62efa4b6338149",
            "be4a9a0a33b0a42ee2fd63dc66ad5b74ccf372e4f903deb15500680154601901",
        }
    ),
    ("dbt", "hub_standard", "yaml"): frozenset(
        {
            "8a6608e1eb8c7a272feb119ea41e66ece1dfc5c5f3bf3a632b8b64bc58bda19d",
            "a10b0821cba99fb99accba14d1a97b75230642de001e3f1628153cd7b305b39b",
        }
    ),
    ("dbt", "link_non_historized", "yaml"): frozenset(
        {
            "66c593d29109398ceb980583eac232ee2a1733e95bf8007d87e79f8c6b2c8af2",
            "fa20a4d49ea099ffc6fb25682c38afe2843a96c8ff4cc114708a7c1e412dc72c",
        }
    ),
    ("dbt", "link_standard", "yaml"): frozenset(
        {
            "ee08c7fa10083dd9200bdbc5ee5b4df8ff69b8ad8ce40f6747765a489434c683",
            "ff019d02b4af9b4a03bca2cd3607bf1d9dd34ee71e87e6a98399f6faac2ad005",
        }
    ),
    ("dbt", "pit", "yaml"): frozenset(
        {
            "c96743ec71edf761f60fbbb6f25e4ce0e89c296808cfdca5228aa6d1fc982f15",
        }
    ),
    ("dbt", "reference_table", "yaml"): frozenset(
        {
            "61f4a22801575cf29130321e10cd9b2834fb87d7e839f728644f1413bca9afbb",
            "6b780e3b305c9b5a573dfef9de7b405b085e2f3d5ac925e5de27571a17c0aff8",
            "703372f1d5a7db749cb03a8fb2ca6e437b096680c81b3888be45d4a26741a486",
        }
    ),
    ("dbt", "satellite_effectivity", "yaml"): frozenset(
        {
            "ae42ee8bfa43ec36a7894f533bf35bc1f6985dcee08ba4dd4fa365dfdb5b4f5f",
        }
    ),
    ("dbt", "satellite_multi_active", "yaml"): frozenset(
        {
            "2fd2764901e6aa94c3d94645f49d81b622830d26b550720bab8a9da26d3507d8",
            "4ac05543582fc1dabab7cbf6f9f00b5d7d35cf25affd94fa7b453867d57f25b1",
            "c4ddbe5b8035866816590356f346bb0e0d978613a71d62ba928f1d8a69c73635",
        }
    ),
    ("dbt", "satellite_non_historized", "yaml"): frozenset(
        {
            "b249ff1621c9aa06645aa7e8a39e89673cb903fdf765fe9773dea4b5ea9fd177",
            "c4ddbe5b8035866816590356f346bb0e0d978613a71d62ba928f1d8a69c73635",
            "f2c506b8e7c698e5dc810c2c2c7b393a228f91c2309643862b6a250f33ccd822",
        }
    ),
    ("dbt", "satellite_record_tracking", "yaml"): frozenset(
        {
            "042b5f8dbec387391767f77d2fd4fc72fc2bf9bbfc149a146df2ccd168d5923f",
        }
    ),
    ("dbt", "satellite_reference", "yaml"): frozenset(
        {
            "334b645ddde6f84656a6d9ff1e9efbdc1713b38da2523687e17d661ac6bf2c48",
            "345698499ae4cfd16555afa7094e9254bca36adc23339d46ed0189957ae0540c",
            "c4ddbe5b8035866816590356f346bb0e0d978613a71d62ba928f1d8a69c73635",
        }
    ),
    ("dbt", "satellite_standard", "yaml"): frozenset(
        {
            "4c67b4a6cf1fe21afc458f7fe11f91d27eef4b92efbfb5777b4eb72ed27fb521",
            "c4ddbe5b8035866816590356f346bb0e0d978613a71d62ba928f1d8a69c73635",
        }
    ),
    ("dbt", "satellite_v1", "yaml"): frozenset(
        {
            "7fc2663e60f1bc10a100b3abaf5ba0f51e008c1aa680996fdd44ca8c77dd3c51",
            "8e67764cd5a9b985f69bfd3e80c5a8d47ecc3eb9758bb4045ea5f5c2f9a9bbf9",
            "d8f661104e55c191906bb20f1aefe9d270292750a8e9a28777b21b2a7107c6d2",
        }
    ),
    ("dbt", "snapshot_control_v0", "yaml"): frozenset(
        {
            "9e0d52bd03de29348fec29ce2390bbe66e40e087a588f2cc2cfd6429654f8ff4",
            "a80e12c36af24d0fd0f1528c4eab3bf14a872e6aeec4f55744e77f4f1d40e01d",
        }
    ),
    ("dbt", "snapshot_control_v1", "yaml"): frozenset(
        {
            "6719d96ce2a1c7eb265cc1381b314e96e78d7d4a9c43a4915c31b75380540b45",
            "e3280d9fcb111786cfcca8472e343edb5760a6bb493cd3544fe28773c0ed7f51",
        }
    ),
    ("dbt", "stage", "yaml"): frozenset(
        {
            "1148994d1fd726972ea20c41a96f8f39b883ea110940763d82291abb1dce2a91",
            "2f5c17006c3cffefd50a5993cbf51e4cccc21dd33fcda9d580c70e9ebe68d178",
        }
    ),
}


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def refresh_bundled_templates(apps: Any, schema_editor: Any) -> None:
    """Replace unedited, superseded template content with the current bundle."""
    # Imported here: the bundled files are read as they are when the
    # migration runs, so an old workspace always lands on the current ones.
    from engine.services.generation.template_resolver import bundled_templates

    model_template = apps.get_model("engine", "ModelTemplate")
    field_by_type = {"sql": "sql_template_content", "yaml": "yaml_template_content"}

    refreshed = 0
    for framework in ("dbt", "sqlmesh"):
        for template in bundled_templates(framework):
            superseded = SUPERSEDED_BUNDLED_HASHES.get(
                (framework, template.entity_type, template.template_type)
            )
            if not superseded:
                continue
            field_name = field_by_type[template.template_type]
            current = template.path.read_text(encoding="utf-8")
            rows = model_template.objects.filter(
                framework=framework, entity_type=template.entity_type
            )
            for row in rows:
                if _content_hash(getattr(row, field_name)) in superseded:
                    setattr(row, field_name, current)
                    row.save(update_fields=[field_name])
                    refreshed += 1
    if refreshed:
        logger.info("Refreshed %d unedited bundled template field(s)", refreshed)


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0019_output_attributes"),
    ]

    operations = [
        migrations.RunPython(
            refresh_bundled_templates, reverse_code=migrations.RunPython.noop
        ),
    ]
