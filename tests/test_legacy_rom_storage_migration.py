"""예전에 만들어 둔 "ROM Storage"를 걷어내는 마이그레이션.

새로 만드는 Collection은 더 이상 ROM 폴더를 별도 Storage로 만들지 않는다. 그런데
**이미 등록해 둔 Collection은 그 배치를 registry.db에 그대로 들고 있다.** 코드만
고치고 데이터를 두면, 사용자 눈에는 아무것도 고쳐지지 않은 것과 같다 - 내비게이션에
`Internal` / `ROM`이 계속 보인다.

옮기면서 ROM 위치를 잃으면 안 된다. 그 Storage의 root_path가 곧 ROM 폴더였으므로,
System 이름을 붙여 각 System의 `rom_path`로 남긴다.
"""

import sqlite3
import unittest

from app.model.collection import STORAGE_INTERNAL
from app.store.registry import RegistryStore
from tests.fixtures import temp_root


def write_legacy_registry(path):
    """마이그레이션 2 이전 모습의 registry.db를 손으로 만든다.

    `RegistryStore`를 쓰면 최신 스키마로 만들어져 검증이 되지 않으므로, 버전 1
    상태를 직접 찍고 그 위에 옛 배치를 넣는다.
    """
    from app.store.registry import MIGRATIONS

    conn = sqlite3.connect(path)
    for statement in MIGRATIONS[0].statements:
        conn.execute(statement)
    conn.execute("PRAGMA user_version = 1")

    conn.execute(
        "INSERT INTO collections (id,name,frontend,target,os,arch,root_path,ui_state_json,"
        "created_at,updated_at) VALUES ('c1','Old','es-de',NULL,NULL,NULL,'D:\\ES-DE','{}',0,0)")
    for storage_id, kind, label, root in (
            (STORAGE_INTERNAL, "internal", "Internal", "D:\\ES-DE"),
            ("roms", "external", "ROM", "D:\\Roms")):
        conn.execute(
            "INSERT INTO collection_storages (collection_id,storage_id,kind,label,root_path)"
            " VALUES ('c1',?,?,?,?)", (storage_id, kind, label, root))
    for system, storage_id, rom_path in (
            ("famicom", STORAGE_INTERNAL, None),
            ("msx", STORAGE_INTERNAL, None),
            ("nes", "roms", None),
            ("msx1", "roms", "E:\\Elsewhere\\msx1")):
        conn.execute(
            "INSERT INTO collection_systems (collection_id,system,storage_id,rom_path,"
            "media_path,metadata_path) VALUES ('c1',?,?,?,NULL,NULL)",
            (system, storage_id, rom_path))
    conn.commit()
    conn.close()


class LegacyRomStorageMigrationTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_legacy_")
        self.path = self.dir / "registry.db"
        write_legacy_registry(self.path)
        self.registry = RegistryStore(self.path)
        self.addCleanup(self.registry.close)
        self.collection = self.registry.get_collection("c1")

    def _system(self, name):
        return next(s for s in self.collection.systems if s.system == name)

    # --- Storage 배치 -------------------------------------------------------
    def test_the_rom_storage_is_gone(self):
        ids = [s.storage_id for s in self.collection.storages]
        self.assertEqual(ids, [STORAGE_INTERNAL])

    def test_every_system_ends_up_on_one_storage(self):
        self.assertEqual({s.storage_id for s in self.collection.systems}, {STORAGE_INTERNAL})

    def test_no_system_is_lost(self):
        self.assertEqual(sorted(s.system for s in self.collection.systems),
                         ["famicom", "msx", "msx1", "nes"])

    # --- ROM 위치는 잃지 않는다 ---------------------------------------------
    def test_the_rom_location_moves_onto_the_system(self):
        self.assertEqual(self._system("nes").rom_path, "D:\\Roms\\nes")

    def test_a_system_that_already_had_its_own_rom_path_keeps_it(self):
        """더 구체적인 값이 이미 있으면 그것이 이긴다."""
        self.assertEqual(self._system("msx1").rom_path, "E:\\Elsewhere\\msx1")

    def test_systems_that_were_already_internal_are_untouched(self):
        self.assertIsNone(self._system("famicom").rom_path)
        self.assertIsNone(self._system("msx").rom_path)

    # --- 다시 열어도 그대로 -------------------------------------------------
    def test_reopening_does_not_undo_it(self):
        self.registry.close()
        again = RegistryStore(self.path)
        self.addCleanup(again.close)
        collection = again.get_collection("c1")
        self.assertEqual([s.storage_id for s in collection.storages], [STORAGE_INTERNAL])


if __name__ == "__main__":
    unittest.main()
