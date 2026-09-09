"""좌측 Navigation이 보여주는 것 (P0/P1).

두 가지를 고정한다.

1. **Navigation은 System 목록이지 Storage 계층이 아니다.** 예전에는 ROM 폴더를 따로
   주면 `label="ROM"`인 Storage가 생기고, 화면이 Storage → System 계층을 그대로 그려서

       Internal
        ├─ Famicom
        └─ MSX
       ROM
        ├─ NES
        └─ MSX1

   처럼 사용자가 요구한 적 없는 분류가 나타났다. Storage는 용량·볼륨·파일 작업을 위한
   내부 개념이다.

2. **빈 System을 별도 묶음으로 만들지 않는다.** 하나의 목록 안에서 정렬 순서만
   다르게 한다 - 게임이 있는 것이 먼저, 없는 것이 나중, 같으면 이름순.
"""

import unittest

from app.model.collection import STORAGE_INTERNAL
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, temp_root, wait_idle, write_file


class NavigationSystemTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_nav_")
        self.meta = self.dir / "esde"
        build_custom_esde_tree(self.meta, "famicom", [
            {"filename": "Gradius.fc", "title": "Gradius"},
            {"filename": "Xevious.fc", "title": "Xevious"}])
        build_custom_esde_tree(self.meta, "msx", [
            {"filename": "Aleste.rom", "title": "Aleste"}])
        # ROM은 없고 gamelist 항목만 있는 System. 목록에는 게임 1개로 뜬다.
        build_custom_esde_tree(self.meta, "ps2", [
            {"filename": "FFX.iso", "title": "Final Fantasy X", "rom": False}])

        self.roms = self.dir / "roms"
        for system, name in (("nes", "Mario.nes"), ("msx1", "Nemesis.rom")):
            write_file(self.roms / system / name, b"r" * 64)
        # 폴더만 있고 아무것도 없는 System - 이것이 진짜 "빈 System"이다.
        (self.roms / "snes").mkdir(parents=True)

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection(
            "C", "es-de", str(self.meta), rom_path=str(self.roms))["data"]["id"]
        self.api.start_scan(self.cid)
        wait_idle(self.api)

    def _detail(self):
        return self.api.collection_detail(self.cid)["data"]

    # --- Storage를 System의 부모로 쓰지 않는다 -------------------------------
    def test_a_separate_rom_folder_does_not_create_a_second_storage(self):
        detail = self._detail()
        self.assertEqual([s["id"] for s in detail["storages"]], [STORAGE_INTERNAL])

    def test_there_is_no_storage_named_rom(self):
        labels = {s["label"].lower() for s in self._detail()["storages"]}
        self.assertNotIn("rom", labels)

    def test_the_navigation_gets_one_flat_system_list(self):
        names = [s["system"] for s in self._detail()["systems"]]
        self.assertEqual(sorted(names), ["famicom", "msx", "msx1", "nes", "ps2", "snes"])

    def test_every_system_appears_exactly_once(self):
        names = [s["system"] for s in self._detail()["systems"]]
        self.assertEqual(len(names), len(set(names)),
                         "같은 System이 두 그룹에 나뉘어 두 번 나타났다")

    def test_each_system_still_knows_its_storage(self):
        """계층으로 만들지는 않지만 정보 자체는 화면이 배지/툴팁으로 쓸 수 있어야 한다."""
        for entry in self._detail()["systems"]:
            self.assertIn("storageId", entry)

    # --- 빈 System 정렬 -----------------------------------------------------
    def test_populated_systems_come_before_empty_ones(self):
        systems = self._detail()["systems"]
        counts = [s["count"] for s in systems]
        self.assertEqual(counts, sorted(counts, key=lambda c: c == 0),
                         f"빈 System이 앞에 끼어 있다: {systems}")

    def test_ties_are_broken_by_name(self):
        systems = self._detail()["systems"]
        empty = [s["system"] for s in systems if s["count"] == 0]
        self.assertEqual(empty, sorted(empty))
        populated = [s["system"] for s in systems if s["count"]]
        self.assertEqual(populated, sorted(populated))

    def test_empty_systems_are_not_put_in_a_separate_group(self):
        """"Empty Systems" 같은 별도 묶음을 만들지 않는다 - 목록은 하나다."""
        detail = self._detail()
        self.assertEqual(len(detail["storages"]), 1)
        self.assertEqual(len(detail["systems"]), 6)

    def test_an_empty_system_is_still_listed(self):
        systems = {s["system"]: s["count"] for s in self._detail()["systems"]}
        self.assertEqual(systems["snes"], 0, "빈 System이 목록에서 사라졌다")
        self.assertEqual(systems["ps2"], 1, "ROM은 없어도 gamelist 항목은 게임으로 센다")


if __name__ == "__main__":
    unittest.main()
