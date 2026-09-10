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
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root, wait_job, write_file


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

    # --- ROM 위치는 System의 속성이지 Storage가 아니다 ----------------------
    def test_the_rom_folder_does_not_become_a_storage(self):
        """예전에는 여기서 `label="ROM"`인 Storage를 만들었다.

        Navigation이 Storage → System 계층을 그대로 그리기 때문에, 사용자가 요구한 적
        없는 `Internal` / `ROM` 분류가 화면에 나타났다. Storage는 용량·볼륨·파일 작업을
        위한 내부 개념이고 사용자가 보는 단위는 System이다.
        """
        cid = self._create(rom_path=str(self.roms))
        collection = self.api.workspace.registry.get_collection(cid)
        self.assertEqual([s.storage_id for s in collection.storages], [STORAGE_INTERNAL])

    def test_the_rom_location_is_recorded_on_the_system(self):
        """ROM이 어디에 있는지는 그 System이 들고 있는다 - Adapter가 이것을 우선한다."""
        cid = self._create(rom_path=str(self.roms))
        collection = self.api.workspace.registry.get_collection(cid)
        placement = {s.system: s.rom_path for s in collection.systems}
        for system in ("ps2", "snes", "gba"):
            self.assertEqual(placement[system], str(self.roms / system), system)

    def test_every_system_stays_on_one_storage(self):
        """Storage가 하나뿐이므로 Navigation이 System을 평평하게 보여줄 수 있다."""
        cid = self._create(rom_path=str(self.roms))
        collection = self.api.workspace.registry.get_collection(cid)
        self.assertEqual({s.storage_id for s in collection.systems}, {STORAGE_INTERNAL})

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

    # --- Metadata는 필수가 아니다 ------------------------------------------
    def test_rom_only_without_any_metadata_directory(self):
        """Metadata 칸을 비우고 ROM 폴더만 준다 - 사용자가 실제로 하는 일이다."""
        result = self.api.create_collection("R", "es-de", None, rom_path=str(self.roms))
        self.assertTrue(result["ok"], result.get("error"))
        rows = self._rows(result["data"]["id"])
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r["present"] for r in rows))

    def test_a_rom_only_collection_is_rooted_at_the_rom_folder(self):
        cid = self.api.create_collection("R", "es-de", None,
                                         rom_path=str(self.roms))["data"]["id"]
        collection = self.api.workspace.registry.get_collection(cid)
        self.assertEqual(collection.root_path, str(self.roms))

    def test_both_paths_empty_is_refused(self):
        result = self.api.create_collection("X", "es-de", None)
        self.assertFalse(result["ok"])


class StorageMoveWithSeparateRomPathTests(unittest.TestCase):
    """Metadata root와 ROM root가 분리된 Collection에서 System을 External
    Storage로 옮기기 (사용자 코드 리뷰로 발견된 회귀).

    Adapter.layout()은 storage_id보다 System의 rom_path를 우선한다(위 클래스가
    보이듯, ES-DE의 "ROM은 다른 폴더" 기본 사용 방식을 지원하려고 있는 값이다).
    그런데 Storage 이동(`_apply_storage_change`)이 storage_id만 바꾸고 이
    rom_path를 그대로 두면, "새 Storage로 옮긴 뒤의 위치"를 계산해도 Adapter가
    여전히 예전 rom_path를 읽어 옛 경로를 돌려준다. 그러면 이동 전후 경로가
    똑같아져서 "목적지에 이미 같은 파일이 있다"는 충돌로만 보이고 실제로는
    한 발짝도 못 옮긴다 - 이게 실사용에서 "External Storage로 드래그해도 Apply가
    항상 실패한다"로 나타난 버그다.
    """

    def setUp(self):
        self.dir = temp_root("rms_storage_move_")
        self.meta = metadata_tree(self.dir / "esde")
        self.roms = rom_tree(self.dir / "roms")
        self.external = self.dir / "external_sd"
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)

        created = self.api.create_collection("C", "es-de", str(self.meta), rom_path=str(self.roms))
        self.assertTrue(created["ok"], created.get("error"))
        self.cid = created["data"]["id"]
        scan(self.api, self.cid)

        collection = self.api.workspace.registry.get_collection(self.cid)
        # 픽스처가 실제로 "ROM이 다른 폴더"인 상태로 시작하는지 먼저 확인한다 -
        # 아니면 이 테스트가 재현하려는 조건 자체가 성립하지 않는다.
        ps2 = next(s for s in collection.systems if s.system == "ps2")
        self.assertEqual(ps2.rom_path, str(self.roms / "ps2"))

        added = self.api.add_external_storage(self.cid, "SD", str(self.external))
        self.assertTrue(added["ok"], added.get("error"))
        self.storage_id = added["data"]

    def test_moving_to_external_storage_actually_moves_the_files(self):
        r = self.api.plan_storage_change(self.cid, "ps2", self.storage_id)
        self.assertTrue(r["ok"], r.get("error"))

        job = self.api.start_apply(self.cid)
        result = wait_job(self.api, job["data"]["jobId"])
        self.assertEqual(result["result"]["applied"], 1, result["result"])
        self.assertEqual(result["result"]["failed"], 0, result["result"])

        self.assertFalse((self.roms / "ps2" / "FFX.iso").exists())
        self.assertTrue((self.external / "ps2" / "FFX.iso").exists())

    def test_the_registry_no_longer_points_at_the_old_rom_path(self):
        """옮긴 뒤에도 옛 rom_path가 남아 있으면 다음 이동에서 같은 문제가 반복된다."""
        self.api.plan_storage_change(self.cid, "ps2", self.storage_id)
        job = self.api.start_apply(self.cid)
        wait_job(self.api, job["data"]["jobId"])

        collection = self.api.workspace.registry.get_collection(self.cid)
        ps2 = next(s for s in collection.systems if s.system == "ps2")
        self.assertEqual(ps2.storage_id, self.storage_id)
        self.assertIsNone(ps2.rom_path)

    def test_a_second_move_back_to_internal_also_works(self):
        """옛 rom_path가 안 지워지는 버그였다면 이 왕복에서 다시 실패했을 것이다."""
        self.api.plan_storage_change(self.cid, "ps2", self.storage_id)
        wait_job(self.api, self.api.start_apply(self.cid)["data"]["jobId"])

        self.api.plan_storage_change(self.cid, "ps2", STORAGE_INTERNAL)
        result = wait_job(self.api, self.api.start_apply(self.cid)["data"]["jobId"])
        self.assertEqual(result["result"]["applied"], 1, result["result"])
        self.assertTrue((self.meta / "ps2" / "FFX.iso").exists())


if __name__ == "__main__":
    unittest.main()
