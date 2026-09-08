"""ROM만 있는 Collection (Phase 7.8).

스크래핑을 한 번도 안 한 컬렉션은 ROM 폴더만 있고 gamelist.xml이 없다. 사용자의 실제
`C:\\Games\\ROMs`가 정확히 그 모습이다 - 43개 시스템 중 41개가 메타데이터 없이 ROM만
들어 있고, **그동안은 Collection으로 열리지도 않았다**(Adapter 4종 전부 confidence 0.0).

이 파일이 지키는 흐름:

    ROM만 있는 폴더 열기
      -> Collection으로 열린다 (확신은 낮게)
      -> Gamelist에 **파일명이 제목 자리에** 뜬다
      -> 편집해서 저장하면 그때 gamelist.xml이 만들어진다
      -> 또는 미리 "ROM 목록만 담은 gamelist"를 만들어 둘 수 있다
"""

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from adapters.es_de import EsDeAdapter
from bridge.api import Api
from storage.local import LocalStorageProvider
from tests.fixtures import scan, temp_root

PROVIDER = LocalStorageProvider()


def bare_rom_tree(root: Path, systems=None) -> Path:
    """gamelist도 media도 없는, ROM만 있는 폴더."""
    systems = systems or {"snes": ["Zelda.sfc", "Mario.sfc"], "gba": ["Metroid.gba"]}
    for system, names in systems.items():
        (root / system).mkdir(parents=True)
        for name in names:
            (root / system / name).write_bytes(b"r" * 256)
    return root


class BareRomDetectionTests(unittest.TestCase):
    def setUp(self):
        self.adapter = EsDeAdapter()
        self.dir = temp_root("rms_bare_")

    def test_a_rom_only_tree_is_recognised(self):
        """그동안은 여기서 막혀 Collection을 만들 수조차 없었다."""
        root = bare_rom_tree(self.dir / "roms")
        detection = self.adapter.detect(PROVIDER, root)
        self.assertTrue(detection.matched)
        self.assertEqual(detection.systems, ("gba", "snes"))
        self.assertIn("메타데이터", detection.message)

    def test_confidence_is_low_because_we_cannot_be_sure(self):
        """ES-DE라고 확신할 근거는 없다 - 어느 Frontend의 ROM 폴더든 이 모양이다."""
        root = bare_rom_tree(self.dir / "roms2")
        bare = self.adapter.detect(PROVIDER, root)

        full = self.dir / "full"
        bare_rom_tree(full)
        (full / "gamelists" / "snes").mkdir(parents=True)
        (full / "gamelists" / "snes" / "gamelist.xml").write_text(
            '<?xml version="1.0"?>\n<gameList/>\n', encoding="utf-8")
        (full / "downloaded_media" / "snes").mkdir(parents=True)

        self.assertLess(bare.confidence, self.adapter.detect(PROVIDER, full).confidence)

    def test_folders_without_roms_are_not_systems(self):
        """폴더가 있다고 전부 System으로 잡으면 사용자의 잡동사니까지 딸려 온다."""
        root = bare_rom_tree(self.dir / "roms3")
        (root / "빈폴더").mkdir()
        (root / "문서").mkdir()
        (root / "문서" / "메모.txt").write_text("hi", encoding="utf-8")

        detection = self.adapter.detect(PROVIDER, root)
        self.assertEqual(detection.systems, ("gba", "snes"))

    def test_an_empty_folder_is_still_not_a_collection(self):
        empty = self.dir / "empty"
        empty.mkdir()
        self.assertFalse(self.adapter.detect(PROVIDER, empty).matched)


class BareRomCollectionTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_bareopen_")
        self.root = bare_rom_tree(self.dir / "roms")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.cid = self.api.create_collection("ROM만", "es-de", str(self.root))["data"]["id"]

    def tearDown(self):
        self.api.close()

    def _gamelist(self, system):
        return self.root / "gamelists" / system / "gamelist.xml"

    # --- 열기 -----------------------------------------------------------
    def test_the_gamelist_shows_filenames(self):
        """메타데이터가 없으면 파일명이 제목 자리에 온다 - 빈 칸으로 두지 않는다."""
        scan(self.api, self.cid)
        rows = self.api.list_rows(self.cid, limit=50)["data"]["rows"]
        self.assertEqual(len(rows), 3)
        titles = {r["file"]: r["title"] for r in rows}
        self.assertEqual(titles["Zelda.sfc"], "Zelda")
        self.assertEqual(titles["Metroid.gba"], "Metroid")
        self.assertFalse(any(r["hasMetadata"] for r in rows))

    def test_nothing_is_written_just_by_opening(self):
        """열어 보기만 했는데 사용자 폴더에 파일이 생기면 안 된다."""
        scan(self.api, self.cid)
        self.assertFalse((self.root / "gamelists").exists())
        self.assertFalse((self.root / "downloaded_media").exists())

    # --- 편집해서 저장하면 만들어진다 ------------------------------------
    def test_editing_creates_the_gamelist(self):
        scan(self.api, self.cid)
        row = next(r for r in self.api.list_rows(self.cid, limit=50)["data"]["rows"]
                   if r["file"] == "Zelda.sfc")
        self.assertFalse(self._gamelist("snes").exists())

        saved = self.api.save_fields(self.cid, row["romUid"],
                                     {"name": "젤다의 전설", "genre": "Action"})
        self.assertTrue(saved["ok"], saved.get("error"))
        self.assertTrue(self._gamelist("snes").exists(), "저장했는데 gamelist가 안 생겼다")

        root = ET.parse(self._gamelist("snes")).getroot()
        game = root.find("game")
        self.assertEqual(game.findtext("name"), "젤다의 전설")
        self.assertEqual(game.findtext("genre"), "Action")

    def test_editing_one_game_does_not_invent_the_others(self):
        """하나를 고쳤다고 나머지까지 멋대로 써 넣지 않는다."""
        scan(self.api, self.cid)
        row = next(r for r in self.api.list_rows(self.cid, limit=50)["data"]["rows"]
                   if r["file"] == "Zelda.sfc")
        self.api.save_fields(self.cid, row["romUid"], {"name": "젤다"})
        root = ET.parse(self._gamelist("snes")).getroot()
        self.assertEqual(len(root.findall("game")), 1)

    # --- 미리 만들어 두기 -------------------------------------------------
    def test_status_reports_which_systems_lack_metadata(self):
        status = self.api.metadata_status(self.cid)["data"]
        self.assertEqual(sorted(status["missing"]), ["gba", "snes"])
        self.assertEqual(status["roms"], 3)

    def test_generate_writes_rom_only_gamelists(self):
        made = self.api.generate_metadata(self.cid)["data"]
        self.assertEqual(sorted(c["system"] for c in made["created"]), ["gba", "snes"])

        root = ET.parse(self._gamelist("snes")).getroot()
        games = {g.findtext("path"): g for g in root.findall("game")}
        self.assertEqual(sorted(games), ["./Mario.sfc", "./Zelda.sfc"])
        self.assertEqual(games["./Zelda.sfc"].findtext("name"), "Zelda")

    def test_generated_entries_leave_the_unknown_fields_empty(self):
        """추측해서 채우면 사용자가 나중에 일일이 지워야 한다."""
        self.api.generate_metadata(self.cid)
        game = ET.parse(self._gamelist("snes")).getroot().find("game")
        for tag in ("genre", "developer", "publisher", "releasedate"):
            self.assertIn((game.findtext(tag) or ""), ("", None), tag)

    def test_generate_never_touches_an_existing_gamelist(self):
        """메타데이터를 덮어쓰는 사고를 원천적으로 막는다."""
        self._gamelist("snes").parent.mkdir(parents=True)
        self._gamelist("snes").write_text(
            '<?xml version="1.0"?>\n<gameList>\n'
            '  <game><path>./Zelda.sfc</path><name>손으로 적은 제목</name></game>\n'
            '</gameList>\n', encoding="utf-8")
        before = self._gamelist("snes").read_text(encoding="utf-8")

        made = self.api.generate_metadata(self.cid)["data"]
        self.assertEqual(self._gamelist("snes").read_text(encoding="utf-8"), before)
        self.assertIn("snes", [s["system"] for s in made["skipped"]])
        self.assertEqual([c["system"] for c in made["created"]], ["gba"])

    def test_generated_gamelist_is_read_back_as_metadata(self):
        """만들어 놓고 다시 스캔하면 그 항목들이 메타데이터 있는 상태가 된다."""
        self.api.generate_metadata(self.cid)
        scan(self.api, self.cid)
        rows = self.api.list_rows(self.cid, limit=50)["data"]["rows"]
        self.assertTrue(all(r["hasMetadata"] for r in rows), "다시 읽히지 않는다")

    def test_status_is_clean_after_generating(self):
        self.api.generate_metadata(self.cid)
        self.assertEqual(self.api.metadata_status(self.cid)["data"]["missing"], [])

    def test_a_system_without_roms_is_not_offered(self):
        """ROM도 없는 빈 폴더에 gamelist를 만들어 줄 이유는 없다."""
        (self.root / "psx").mkdir()
        cid = self.api.create_collection("두번째", "es-de", str(self.root))["data"]["id"]
        status = self.api.metadata_status(cid)["data"]
        self.assertNotIn("psx", status["missing"])


if __name__ == "__main__":
    unittest.main()
