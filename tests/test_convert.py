"""Convert 테스트 (스펙 §53).

지키는 것 둘:
- **원본은 보존된다.** Convert는 source를 읽어 target에 만드는 일이다.
- **미리보기는 아무것도 바꾸지 않고, 무엇을 잃는지 정직하게 센다.** Frontend 간 변환은
  반드시 무언가를 잃으므로(§50-51), 그 숫자가 실제와 다르면 미리보기가 있으나 마나다.
"""

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from adapters.base import COMMON_FIELDS
from adapters.pegasus import PegasusAdapter
from bridge.api import Api
from storage.local import LocalStorageProvider
from tests.fixtures import build_custom_esde_tree, scan, temp_root, wait_idle

EMPTY_GAMELIST = '<?xml version="1.0"?>\n<gameList/>\n'

PEGASUS_METADATA = """collection: PlayStation 2
shortname: ps2

"""


def build_pegasus_tree(root: Path, system="ps2") -> Path:
    (root / system).mkdir(parents=True)
    (root / system / "metadata.pegasus.txt").write_text(PEGASUS_METADATA, encoding="utf-8")
    return root


class ConvertPreviewTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_convert_")
        # source: ES-DE. region과 frontend 고유 태그가 있는 항목을 섞어 둔다.
        source_root = build_custom_esde_tree(self.dir / "esde", "ps2", [
            {"filename": "FFX.iso", "title": "Final Fantasy X", "genre": "RPG",
             "developer": "Square", "size": 100},
            {"filename": "MGS2.iso", "title": "Metal Gear Solid 2", "size": 200},
        ])
        # region과 playcount를 직접 심는다 - fixture 빌더가 다루지 않는 값들이다.
        gamelist = source_root / "gamelists" / "ps2" / "gamelist.xml"
        tree = ET.parse(gamelist)
        for game in tree.getroot().findall("game"):
            ET.SubElement(game, "region").text = "USA"
            ET.SubElement(game, "playcount").text = "17"
        tree.write(gamelist, encoding="utf-8", xml_declaration=True)

        # media 하나 - ES-DE에는 있고 Pegasus에도 있는 타입.
        covers = source_root / "downloaded_media" / "ps2" / "covers"
        covers.mkdir(parents=True, exist_ok=True)
        (covers / "FFX.png").write_bytes(b"c" * 40)
        # 3dboxes는 ES-DE에만 있는 타입이다 - Pegasus로는 못 간다.
        boxes = source_root / "downloaded_media" / "ps2" / "3dboxes"
        boxes.mkdir(parents=True, exist_ok=True)
        (boxes / "FFX.png").write_bytes(b"b" * 30)

        target_root = build_pegasus_tree(self.dir / "pegasus")

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("ES-DE", "es-de", str(source_root))["data"]["id"]
        self.dst = self.api.create_collection("Pegasus", "pegasus", str(target_root))["data"]["id"]
        for cid in (self.src, self.dst):
            scan(self.api, cid)

    def tearDown(self):
        self.api.close()

    # ------------------------------------------------------------------
    def test_preview_counts_what_moves(self):
        data = self.api.convert_preview(self.src, self.dst)["data"]
        self.assertEqual(data["sourceFrontend"], "ES-DE")
        self.assertEqual(data["targetFrontend"], "Pegasus")
        self.assertEqual(data["games"], 2)
        self.assertEqual(data["metadata"], 2)
        self.assertEqual(data["media"], 1, "Pegasus가 받을 수 있는 covers 하나")

    def test_preview_counts_media_the_target_cannot_hold(self):
        """ES-DE의 3dboxes는 Pegasus에 자리가 없다 - 조용히 사라지면 안 된다."""
        data = self.api.convert_preview(self.src, self.dst)["data"]
        self.assertEqual(data["droppedMedia"], 1)

    def test_preview_counts_fields_the_target_format_lacks(self):
        """Pegasus 포맷에는 region 키가 없다."""
        data = self.api.convert_preview(self.src, self.dst)["data"]
        self.assertEqual(data["unsupportedFields"], 2, "두 게임 모두 region 값이 있다")
        self.assertEqual(data["unsupportedFieldNames"], ["region"])

    def test_preview_ignores_empty_values(self):
        """값이 비어 있으면 잃을 것이 없다 - 겁주는 숫자를 만들지 않는다."""
        gamelist = Path(self.api.registry.get_collection(self.src).root_path) \
            / "gamelists" / "ps2" / "gamelist.xml"
        tree = ET.parse(gamelist)
        for game in tree.getroot().findall("game"):
            game.find("region").text = ""
        tree.write(gamelist, encoding="utf-8", xml_declaration=True)
        self.api.start_scan(self.src, True)
        wait_idle(self.api)

        data = self.api.convert_preview(self.src, self.dst)["data"]
        self.assertEqual(data["unsupportedFields"], 0)
        self.assertEqual(data["unsupportedFieldNames"], [])

    def test_preview_counts_frontend_specific_values(self):
        """frontend_raw는 다른 Frontend로 건너가지 못한다(§50-51)."""
        data = self.api.convert_preview(self.src, self.dst)["data"]
        self.assertGreaterEqual(data["frontendSpecific"], 2, "playcount 두 개는 최소한 있다")

    def test_preview_changes_nothing(self):
        target_file = Path(self.api.registry.get_collection(self.dst).root_path) \
            / "ps2" / "metadata.pegasus.txt"
        before = target_file.read_text(encoding="utf-8")
        self.api.convert_preview(self.src, self.dst)
        self.assertEqual(target_file.read_text(encoding="utf-8"), before)
        self.assertEqual(self.api.plan_state(self.dst)["data"]["total"], 0,
                         "미리보기가 Plan을 건드렸다")

    def test_converting_to_itself_is_refused(self):
        self.assertFalse(self.api.convert_preview(self.src, self.src)["ok"])
        self.assertFalse(self.api.start_convert(self.src, self.src)["ok"])

    def test_fields_and_media_are_counted_separately(self):
        """필드와 media는 서로 다른 축이다 - 하나가 0이라고 다른 것도 0은 아니다.

        EmulationStation은 공통 필드 9개를 전부 담을 수 있어 unsupportedFields가 0이지만,
        3dboxes에 해당하는 태그가 없어 그 media는 여전히 못 받는다. 두 숫자를 하나로
        합치면 사용자가 무엇을 잃는지 알 수 없게 된다.
        """
        es_root = self.dir / "es"
        (es_root / "gamelists" / "ps2").mkdir(parents=True)
        (es_root / "gamelists" / "ps2" / "gamelist.xml").write_text(
            EMPTY_GAMELIST, encoding="utf-8")
        cid = self.api.create_collection("ES", "emulationstation", str(es_root))["data"]["id"]
        scan(self.api, cid)

        data = self.api.convert_preview(self.src, cid)["data"]
        self.assertEqual(data["unsupportedFields"], 0, "ES는 공통 필드를 전부 담는다")
        self.assertEqual(data["unsupportedFieldNames"], [])
        self.assertEqual(data["droppedMedia"], 1, "그래도 3dboxes는 받을 자리가 없다")


class ConvertPlanTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_convert_plan_")
        source_root = build_custom_esde_tree(self.dir / "esde", "ps2", [
            {"filename": "FFX.iso", "title": "Final Fantasy X", "genre": "RPG", "size": 100},
        ])
        covers = source_root / "downloaded_media" / "ps2" / "covers"
        covers.mkdir(parents=True, exist_ok=True)
        (covers / "FFX.png").write_bytes(b"c" * 40)
        self.source_root = source_root
        self.target_root = build_pegasus_tree(self.dir / "pegasus")

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("ES-DE", "es-de", str(source_root))["data"]["id"]
        self.dst = self.api.create_collection("Pegasus", "pegasus", str(self.target_root))["data"]["id"]
        for cid in (self.src, self.dst):
            scan(self.api, cid)

    def tearDown(self):
        self.api.close()

    def test_convert_only_plans_it(self):
        """Plan 계약 그대로 - 확정은 Apply의 몫이다."""
        result = self.api.start_convert(self.src, self.dst)["data"]
        self.assertEqual(result["added"], 1)

        self.assertEqual(self.api.plan_state(self.dst)["data"]["total"], 1)
        self.assertFalse((self.target_root / "ps2" / "FFX.iso").exists(),
                         "Plan 단계에서 파일이 생겼다")
        text = (self.target_root / "ps2" / "metadata.pegasus.txt").read_text(encoding="utf-8")
        self.assertNotIn("FFX", text, "Plan 단계에서 metadata가 쓰였다")

    def test_apply_writes_the_target_format(self):
        """변환의 결과물은 **target Frontend의 포맷**이어야 한다."""
        self.api.start_convert(self.src, self.dst)
        job = self.api.start_apply(self.dst)["data"]["jobId"]
        wait_idle(self.api)
        result = self.api.get_job_progress(job)["data"]["result"]
        self.assertEqual(result["applied"], 1, result["errors"])

        # Pegasus의 블록 포맷으로 적혀 있어야 한다.
        text = (self.target_root / "ps2" / "metadata.pegasus.txt").read_text(encoding="utf-8")
        self.assertIn("game: Final Fantasy X", text)
        self.assertIn("file: FFX.iso", text)
        self.assertIn("collection: PlayStation 2", text, "기존 헤더가 사라지면 안 된다")

        # media도 Pegasus 규칙(게임 폴더 안의 boxFront)으로 놓여야 한다.
        self.assertTrue((self.target_root / "ps2" / "media" / "FFX" / "boxFront.png").exists())

    def test_the_source_collection_is_untouched(self):
        """§53 - 원본 Collection을 기본적으로 보존한다."""
        gamelist = self.source_root / "gamelists" / "ps2" / "gamelist.xml"
        before = gamelist.read_text(encoding="utf-8")
        rom_before = (self.source_root / "ps2" / "FFX.iso").read_bytes()

        self.api.start_convert(self.src, self.dst)
        self.api.start_apply(self.dst)
        wait_idle(self.api)

        self.assertEqual(gamelist.read_text(encoding="utf-8"), before)
        self.assertEqual((self.source_root / "ps2" / "FFX.iso").read_bytes(), rom_before)
        self.assertTrue((self.source_root / "downloaded_media" / "ps2" / "covers" / "FFX.png").exists())

    def test_converting_twice_does_not_duplicate(self):
        """이미 있는 항목은 붙여넣기와 같은 규칙으로 처리된다."""
        self.api.start_convert(self.src, self.dst)
        self.api.start_apply(self.dst)
        wait_idle(self.api)
        self.api.start_scan(self.dst, True)
        wait_idle(self.api)

        self.api.start_convert(self.src, self.dst)
        self.api.start_apply(self.dst)
        wait_idle(self.api)

        adapter = PegasusAdapter()
        collection = self.api.registry.get_collection(self.dst)
        index = adapter.read_index(LocalStorageProvider(), adapter.layout(collection, "ps2"))
        self.assertEqual(list(index), ["FFX.iso"])

    def test_unsupported_field_really_does_not_appear(self):
        """미리보기가 "잃는다"고 말한 것이 실제로도 안 넘어가는지."""
        self.api.start_convert(self.src, self.dst)
        self.api.start_apply(self.dst)
        wait_idle(self.api)
        text = (self.target_root / "ps2" / "metadata.pegasus.txt").read_text(encoding="utf-8")
        self.assertNotIn("region", text)


if __name__ == "__main__":
    unittest.main()
