"""Metadata Validation 강화 - 단순 XML Parse 검사에서 Collection Health 검사로.

두 층위를 나눠 본다.
  1. 각 Adapter의 `raw_metadata_filenames()`/`validate_metadata_syntax()` - 형식별 정확성
     (adapters/*.py에 추가). 특히 Pegasus는 XML이 아니므로 "문법 오류"라는 개념이 없고,
     ES-DE는 read_index()가 이미 관대하게 읽는 파일(형제 <alternativeEmulator>, 이스케이프
     안 된 &)을 여기서 오탐하면 안 된다.
  2. `app/dashboard.py::validate_collection()` - System 전체를 훑어 ROM 연결/이름 없음/
     중복 Metadata를 찾고, Complete/Missing Media/Missing Description/Invalid XML
     네 상태를 집계한다(bridge.Api를 통해 실제 ES-DE 구조로 검증한다).
"""

import tempfile
import unittest
from pathlib import Path

from adapters.emulationstation import EmulationStationAdapter
from adapters.es_de import EsDeAdapter
from adapters.launchbox import LaunchBoxAdapter
from adapters.pegasus import PegasusAdapter
from app.model.collection import Collection, StorageLocation, SystemEntry, STORAGE_INTERNAL
from bridge.api import Api
from storage.local import LocalStorageProvider
from tests.fixtures import build_esde_tree, temp_root, wait_job, write_file


def make_collection(root, frontend):
    return Collection(
        id="col-1", name="Test", frontend=frontend, root_path=str(root),
        storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL, "Internal", str(root))],
        systems=[SystemEntry("ps2", STORAGE_INTERNAL)],
    )


# ----------------------------------------------------------------------
# Adapter 단위 - raw_metadata_filenames / validate_metadata_syntax
# ----------------------------------------------------------------------
class EsDeAdapterValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rms_esde_val_"))
        self.gamelist = self.root / "gamelists" / "ps2" / "gamelist.xml"
        self.adapter = EsDeAdapter()
        self.provider = LocalStorageProvider()
        self.layout = self.adapter.layout(make_collection(self.root, "es-de"), "ps2")

    def write(self, xml):
        self.gamelist.parent.mkdir(parents=True, exist_ok=True)
        self.gamelist.write_text(xml, encoding="utf-8")

    def test_raw_filenames_keep_duplicates_in_order(self):
        self.write("""<?xml version="1.0"?>
<gameList>
  <game><path>./FFX.iso</path><name>A</name></game>
  <game><path>./MGS2.iso</path><name>B</name></game>
  <game><path>./FFX.iso</path><name>A again</name></game>
</gameList>""")
        self.assertEqual(self.adapter.raw_metadata_filenames(self.provider, self.layout),
                         ["FFX.iso", "MGS2.iso", "FFX.iso"])

    def test_well_formed_xml_is_valid(self):
        self.write("<?xml version=\"1.0\"?>\n<gameList><game><path>./FFX.iso</path></game></gameList>")
        self.assertIsNone(self.adapter.validate_metadata_syntax(self.provider, self.gamelist))

    def test_genuinely_broken_xml_reports_an_error(self):
        self.write("<gameList><game>")
        error = self.adapter.validate_metadata_syntax(self.provider, self.gamelist)
        self.assertIsInstance(error, str)
        self.assertTrue(error)

    def test_alternative_emulator_sibling_is_not_invalid_xml(self):
        """ES-DE 3.x가 실제로 만드는 형태(§ read_index 주석) - 앱이 이미 정상적으로
        읽는 파일을 여기서 Invalid로 잘못 알리면 안 된다."""
        self.write("""<?xml version="1.0"?>
<alternativeEmulator>
    <label>Snes9x 2010</label>
</alternativeEmulator>
<gameList>
  <game><path>./FFX.iso</path><name>Final Fantasy X</name></game>
</gameList>""")
        self.assertIsNone(self.adapter.validate_metadata_syntax(self.provider, self.gamelist))
        # read_index()도 실제로 그 항목을 읽어낸다는 것까지 같이 확인한다(같은 파서를 쓴다).
        self.assertIn("FFX.iso", self.adapter.read_index(self.provider, self.layout))

    def test_missing_file_reports_unreadable(self):
        error = self.adapter.validate_metadata_syntax(self.provider, self.gamelist)
        self.assertEqual(error, "파일을 읽을 수 없습니다.")


class EmulationStationAdapterValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rms_es_val_"))
        self.gamelist = self.root / "gamelists" / "ps2" / "gamelist.xml"
        self.adapter = EmulationStationAdapter()
        self.provider = LocalStorageProvider()
        self.layout = self.adapter.layout(make_collection(self.root, "emulationstation"), "ps2")

    def write(self, xml):
        self.gamelist.parent.mkdir(parents=True, exist_ok=True)
        self.gamelist.write_text(xml, encoding="utf-8")

    def test_raw_filenames_keep_duplicates(self):
        self.write("<gameList><game><path>./FFX.iso</path></game>"
                   "<game><path>./FFX.iso</path></game></gameList>")
        self.assertEqual(self.adapter.raw_metadata_filenames(self.provider, self.layout),
                         ["FFX.iso", "FFX.iso"])

    def test_broken_xml_reports_an_error(self):
        self.write("<gameList><game>")
        self.assertTrue(self.adapter.validate_metadata_syntax(self.provider, self.gamelist))


class LaunchBoxAdapterValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rms_lb_val_"))
        self.platform_xml = self.root / "Data" / "Platforms" / "ps2.xml"
        self.adapter = LaunchBoxAdapter()
        self.provider = LocalStorageProvider()
        self.layout = self.adapter.layout(make_collection(self.root, "launchbox"), "ps2")

    def write(self, xml):
        self.platform_xml.parent.mkdir(parents=True, exist_ok=True)
        self.platform_xml.write_text(xml, encoding="utf-8")

    def test_raw_filenames_keep_duplicates(self):
        self.write("<LaunchBox>"
                   "<Game><ApplicationPath>Games\\ps2\\FFX.iso</ApplicationPath></Game>"
                   "<Game><ApplicationPath>Games\\ps2\\FFX.iso</ApplicationPath></Game>"
                   "</LaunchBox>")
        self.assertEqual(self.adapter.raw_metadata_filenames(self.provider, self.layout),
                         ["FFX.iso", "FFX.iso"])

    def test_broken_xml_reports_an_error(self):
        self.write("<LaunchBox><Game>")
        self.assertTrue(self.adapter.validate_metadata_syntax(self.provider, self.platform_xml))


class PegasusAdapterValidationTests(unittest.TestCase):
    """Pegasus는 XML이 아니다 - `ET.parse()`를 그대로 쓰면 정상 파일도 항상
    Invalid XML로 잘못 보고된다(수정 전 버그). 이 클래스는 그 수정을 확인한다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rms_pegasus_val_"))
        self.metadata = self.root / "ps2" / "metadata.pegasus.txt"
        self.adapter = PegasusAdapter()
        self.provider = LocalStorageProvider()
        self.layout = self.adapter.layout(make_collection(self.root, "pegasus"), "ps2")

    def write(self, text):
        self.metadata.parent.mkdir(parents=True, exist_ok=True)
        self.metadata.write_text(text, encoding="utf-8")

    def test_a_normal_pegasus_file_is_never_invalid_xml(self):
        self.write("collection: PS2\nshortname: ps2\n\ngame: Final Fantasy X\nfile: FFX.iso\n")
        self.assertIsNone(self.adapter.validate_metadata_syntax(self.provider, self.metadata))

    def test_text_that_would_break_an_xml_parser_is_still_fine(self):
        """`<`, `&` 같은 XML 특수문자가 그냥 텍스트로 있어도(Pegasus에서는 정상) 문제
        없어야 한다 - 예전 버그는 이런 파일까지 Invalid XML로 보고했다."""
        self.write("game: A & B <Special>\nfile: Weird.iso\ndescription: 5 < 10 & true\n")
        self.assertIsNone(self.adapter.validate_metadata_syntax(self.provider, self.metadata))

    def test_raw_filenames_keep_duplicates(self):
        self.write("game: A\nfile: FFX.iso\n\ngame: A again\nfile: FFX.iso\n")
        self.assertEqual(self.adapter.raw_metadata_filenames(self.provider, self.layout),
                         ["FFX.iso", "FFX.iso"])

    def test_missing_file_reports_unreadable(self):
        self.assertEqual(self.adapter.validate_metadata_syntax(self.provider, self.metadata),
                         "파일을 읽을 수 없습니다.")


# ----------------------------------------------------------------------
# app/dashboard.py::validate_collection() - 실제 ES-DE 구조 기준
# ----------------------------------------------------------------------
class ValidateCollectionHealthTests(unittest.TestCase):
    """build_esde_tree: FFX(ROM+설명+Cover+Video) / MGS2(ROM만) / MetadataOnly(ROM 없음)."""

    def setUp(self):
        self.dir = temp_root("rms_metaval_")
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def validate(self):
        r = self.api.validate_collection(self.cid)
        self.assertTrue(r["ok"], r.get("error"))
        return r["data"]

    def health(self):
        return self.api.dashboard_stats(self.cid)["data"]["health"]

    def test_metadata_only_entry_is_flagged_as_missing_rom(self):
        result = self.validate()
        self.assertIn({"system": "ps2", "filename": "MetadataOnly.iso", "issues": ["missingRom"]},
                      result["issues"])

    def test_no_duplicates_in_the_default_fixture(self):
        self.assertEqual(self.validate()["duplicates"], [])

    def test_four_summary_statuses_match_dashboard_health_exactly(self):
        """요구사항의 핵심 - Validate 결과와 Dashboard 통계가 같은 기준이어야 한다."""
        statuses = self.validate()["statuses"]
        health = self.health()
        self.assertEqual(statuses["complete"], health["complete"])
        self.assertEqual(statuses["missingMedia"], health["missingMedia"])
        self.assertEqual(statuses["missingDescription"], health["missingDescription"])
        self.assertEqual(statuses["invalidXml"], 0)
        # 픽스처 기준 실제 값도 못박아 둔다(다른 테스트가 이미 검증하지만, 여기서
        # "네 상태" 자체가 의미 있는 숫자인지 함께 본다).
        self.assertEqual(statuses["complete"], 1)
        self.assertEqual(statuses["missingMedia"], 2)
        self.assertEqual(statuses["missingDescription"], 2)

    def test_invalid_xml_is_not_treated_as_complete(self):
        """단순 ET.parse() 성공 여부만으로 Complete를 판정하지 않는다 - 실제로는
        파일이 아예 깨져서 그 System을 하나도 볼 수 없는 상태다."""
        write_file(self.root / "gamelists" / "ps2" / "gamelist.xml", "<gameList><game>")
        result = self.validate()
        self.assertEqual(result["statuses"]["invalidXml"], 1)
        self.assertEqual(len(result["invalid"]), 1)
        self.assertEqual(result["invalid"][0]["system"], "ps2")
        # 파일이 안 읽히니 그 안의 게임에 대한 개별 issue는 낼 수 없다 - 조용히 건너뛴다.
        self.assertEqual(result["issues"], [])

    def test_missing_name_is_reported_as_missing_metadata(self):
        write_file(self.root / "gamelists" / "ps2" / "gamelist.xml", """<?xml version="1.0"?>
<gameList>
  <game><path>./FFX.iso</path><name></name></game>
  <game><path>./MGS2.iso</path><name>Metal Gear Solid 2</name></game>
</gameList>""")
        result = self.validate()
        issue = next(i for i in result["issues"] if i["filename"] == "FFX.iso")
        self.assertIn("missingMetadata", issue["issues"])

    def test_duplicate_metadata_blocks_are_detected(self):
        write_file(self.root / "gamelists" / "ps2" / "gamelist.xml", """<?xml version="1.0"?>
<gameList>
  <game><path>./FFX.iso</path><name>Final Fantasy X</name></game>
  <game><path>./FFX.iso</path><name>Final Fantasy X (dup)</name></game>
  <game><path>./MGS2.iso</path><name>Metal Gear Solid 2</name></game>
</gameList>""")
        result = self.validate()
        self.assertEqual(result["duplicates"], [{"system": "ps2", "filename": "FFX.iso", "count": 2}])

    def test_alternative_emulator_sibling_is_not_flagged_invalid(self):
        write_file(self.root / "gamelists" / "ps2" / "gamelist.xml", """<?xml version="1.0"?>
<alternativeEmulator>
    <label>PCSX2</label>
</alternativeEmulator>
<gameList>
  <game><path>./FFX.iso</path><name>Final Fantasy X</name></game>
</gameList>""")
        result = self.validate()
        self.assertEqual(result["invalid"], [])
        self.assertEqual(result["statuses"]["invalidXml"], 0)

    def test_system_without_a_metadata_file_is_not_checked(self):
        # gba는 등록되어 있지 않다 - checked는 ps2 하나뿐이어야 한다(기존 동작 유지).
        result = self.validate()
        self.assertEqual(result["checked"], 1)

    def test_validation_never_writes_to_disk(self):
        before = (self.root / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
        self.validate()
        after = (self.root / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertEqual(before, after)


class ValidateCollectionPegasusRegressionTests(unittest.TestCase):
    """수정 전에는 모든 Frontend에 `ET.parse()`를 그대로 썼다 - Pegasus(텍스트 형식)
    Collection에서 Validate를 누르면 멀쩡한 파일도 전부 Invalid XML로 나왔다."""

    def setUp(self):
        self.dir = temp_root("rms_pegasus_dashboard_")
        self.root = self.dir / "lib"
        system = self.root / "ps2"
        system.mkdir(parents=True)
        write_file(system / "metadata.pegasus.txt",
                  "collection: PS2\nshortname: ps2\n\n"
                  "game: Final Fantasy X\nfile: FFX.iso\ndescription: A & B <weird> text\n")
        write_file(system / "FFX.iso", b"r" * 100)
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("P", "pegasus", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def test_pegasus_collection_is_never_reported_as_invalid_xml(self):
        result = self.api.validate_collection(self.cid)["data"]
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["invalid"], [])
        self.assertEqual(result["statuses"]["invalidXml"], 0)


if __name__ == "__main__":
    unittest.main()
