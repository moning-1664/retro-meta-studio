"""ROM과 Metadata를 따로 가져오기 (Phase 7.18, GUI-01).

사용자의 실제 배치가 이렇다.

    Metadata : ES-DE 백업 폴더   (gamelists/, downloaded_media/)
    ROM      : C:\\Games\\ROMs    (<system>/*.iso)

폴더를 하나만 받던 때는 **둘 중 하나만 있는 Collection**밖에 만들 수 없었다. ROM만
넣으면 제목이 파일명뿐이고, 메타데이터만 넣으면 실행할 ROM이 없다.

ES-DE는 원래 이 둘을 떼어 놓는 Frontend다(안드로이드의 외장 SD가 그 경우다). 예외가
아니라 기본 사용 방식이므로 처음 만들 때부터 받을 수 있어야 한다.
"""

import unittest

from app.model.collection import STORAGE_INTERNAL
from app.workspace import Workspace
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root, write_file


def metadata_tree(root):
    """gamelists와 downloaded_media만 있는 폴더. ROM 파일은 없다."""
    build_custom_esde_tree(root, "ps2", [
        {"filename": "FFX.iso", "title": "Final Fantasy X", "genre": "RPG", "rom": False},
        {"filename": "MGS2.iso", "title": "Metal Gear Solid 2", "rom": False},
    ])
    build_custom_esde_tree(root, "snes", [
        {"filename": "Zelda.sfc", "title": "Zelda", "rom": False}])
    write_file(root / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"c" * 30)
    return root


def rom_tree(root):
    """ROM만 있는 폴더. gamelist도 media도 없다."""
    for system, names in (("ps2", ["FFX.iso", "MGS2.iso"]), ("snes", ["Zelda.sfc"]),
                          ("gba", ["Metroid.gba"])):
        for name in names:
            write_file(root / system / name, b"r" * 128)
    return root


class ImportBothTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_import_")
        self.meta = metadata_tree(self.dir / "esde")
        self.roms = rom_tree(self.dir / "roms")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)

    def _create(self, **kwargs):
        result = self.api.create_collection("C", "es-de", str(self.meta), **kwargs)
        self.assertTrue(result["ok"], result.get("error"))
        return result["data"]["id"]

    def _rows(self, cid):
        scan(self.api, cid)
        return self.api.list_rows(cid, limit=200)["data"]["rows"]

    # --- 셋 다 되어야 한다 ------------------------------------------------
    def test_metadata_only_still_works(self):
        rows = self._rows(self._create())
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["hasMetadata"] for r in rows))
        self.assertFalse(any(r["present"] for r in rows), "ROM이 없어야 하는데 있다")

    def test_rom_only_still_works(self):
        result = self.api.create_collection("R", "es-de", str(self.roms))
        rows = self._rows(result["data"]["id"])
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r["present"] for r in rows))

    def test_rom_and_metadata_together(self):
        """**이것이 없어서 사용자가 반쪽짜리 Collection만 만들 수 있었다.**"""
        rows = self._rows(self._create(rom_path=str(self.roms)))
        both = [r for r in rows if r["present"] and r["hasMetadata"]]
        self.assertEqual(sorted(r["file"] for r in both),
                         ["FFX.iso", "MGS2.iso", "Zelda.sfc"])

    def test_the_metadata_actually_reaches_the_rom(self):
        rows = self._rows(self._create(rom_path=str(self.roms)))
        ffx = next(r for r in rows if r["file"] == "FFX.iso")
        self.assertEqual(ffx["title"], "Final Fantasy X")
        self.assertEqual(ffx["genre"], "RPG")

    def test_a_system_only_in_the_rom_folder_comes_along(self):
        """gba는 메타데이터가 없다. 그렇다고 빼면 사용자 ROM이 사라진 것처럼 보인다."""
        rows = self._rows(self._create(rom_path=str(self.roms)))
        self.assertIn("Metroid.gba", [r["file"] for r in rows])

    def test_media_still_attaches(self):
        rows = self._rows(self._create(rom_path=str(self.roms)))
        ffx = next(r for r in rows if r["file"] == "FFX.iso")
        self.assertTrue(ffx["hasMedia"], "media가 붙지 않았다")

    # --- Storage 배치 ------------------------------------------------------
    def test_the_rom_folder_becomes_its_own_storage(self):
        """다른 디스크에 쌓이는 바이트를 한 Storage로 뭉뚱그리면 용량 표시가 틀어진다."""
        cid = self._create(rom_path=str(self.roms))
        collection = self.api.workspace.registry.get_collection(cid)
        roots = {s.storage_id: s.root_path for s in collection.storages}
        self.assertEqual(roots.get(Workspace.ROM_STORAGE_ID), str(self.roms))

    def test_systems_with_roms_live_on_the_rom_storage(self):
        cid = self._create(rom_path=str(self.roms))
        collection = self.api.workspace.registry.get_collection(cid)
        placement = {s.system: s.storage_id for s in collection.systems}
        for system in ("ps2", "snes", "gba"):
            self.assertEqual(placement[system], Workspace.ROM_STORAGE_ID, system)

    def test_the_same_folder_twice_does_not_create_a_second_storage(self):
        """ROM 폴더와 Metadata 폴더가 같으면 Storage를 나눌 이유가 없다."""
        cid = self._create(rom_path=str(self.meta))
        collection = self.api.workspace.registry.get_collection(cid)
        self.assertEqual([s.storage_id for s in collection.storages], [STORAGE_INTERNAL])

    def test_an_empty_rom_folder_is_not_an_error(self):
        empty = self.dir / "empty"
        empty.mkdir()
        cid = self._create(rom_path=str(empty))
        collection = self.api.workspace.registry.get_collection(cid)
        self.assertEqual([s.storage_id for s in collection.storages], [STORAGE_INTERNAL])

    def test_nothing_anywhere_is_still_refused(self):
        """열 것이 없으면 조용히 빈 Collection을 만들지 않는다."""
        empty = self.dir / "nothing"
        empty.mkdir()
        result = self.api.create_collection("X", "es-de", str(empty))
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
