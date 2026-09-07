"""
tests/test_similar_rom_sqlite.py
==================================
v0.5 10단계: 유사롬 그룹의 SQLite 이전(similar_groups/similar_group_members) +
대표(representative) 지정 기능 검증.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from database.sqlite_db import SQLiteRepository


class SimilarGroupRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="retro_similar_"))
        self.repo = SQLiteRepository(self.tmpdir / "master.db")
        data = {
            "roms": {
                "snes|A.zip": {"system": "snes", "rom_filename": "A.zip", "default_version_id": "v1",
                               "core_override": None, "versions": {"v1": {"fields": {"name": "A"}}}, "media": {}},
                "snes|B.zip": {"system": "snes", "rom_filename": "B.zip", "default_version_id": "v1",
                               "core_override": None, "versions": {"v1": {"fields": {"name": "B"}}}, "media": {}},
                "snes|C.zip": {"system": "snes", "rom_filename": "C.zip", "default_version_id": "v1",
                               "core_override": None, "versions": {"v1": {"fields": {"name": "C"}}}, "media": {}},
                "nes|D.zip": {"system": "nes", "rom_filename": "D.zip", "default_version_id": "v1",
                              "core_override": None, "versions": {"v1": {"fields": {"name": "D"}}}, "media": {}},
            }
        }
        self.repo.replace_from_dict(data, locals_data=[])

    def tearDown(self):
        self.repo.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_get_groups(self):
        groups = [{"members": ["snes|A.zip", "snes|B.zip"], "pairs": []}]
        self.repo.save_similar_groups("snes", groups)
        got = self.repo.get_similar_groups("snes")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["members"], ["snes|A.zip", "snes|B.zip"])
        self.assertIsNone(got[0]["representative"])
        self.assertIsInstance(got[0]["group_id"], int)

    def test_group_with_single_member_is_dropped(self):
        groups = [{"members": ["snes|A.zip"], "pairs": []}]
        self.repo.save_similar_groups("snes", groups)
        self.assertEqual(self.repo.get_similar_groups("snes"), [])

    def test_unknown_member_key_silently_skipped(self):
        groups = [{"members": ["snes|A.zip", "snes|NoSuchRom.zip", "snes|B.zip"], "pairs": []}]
        self.repo.save_similar_groups("snes", groups)
        got = self.repo.get_similar_groups("snes")
        self.assertEqual(got[0]["members"], ["snes|A.zip", "snes|B.zip"])

    def test_set_and_clear_representative(self):
        self.repo.save_similar_groups("snes", [{"members": ["snes|A.zip", "snes|B.zip"], "pairs": []}])
        group_id = self.repo.get_similar_groups("snes")[0]["group_id"]

        self.assertTrue(self.repo.set_similar_group_representative(group_id, "snes|B.zip"))
        got = self.repo.get_similar_groups("snes")
        self.assertEqual(got[0]["representative"], "snes|B.zip")

        self.assertTrue(self.repo.set_similar_group_representative(group_id, None))
        got = self.repo.get_similar_groups("snes")
        self.assertIsNone(got[0]["representative"])

    def test_representative_must_be_group_member(self):
        self.repo.save_similar_groups("snes", [{"members": ["snes|A.zip", "snes|B.zip"], "pairs": []}])
        group_id = self.repo.get_similar_groups("snes")[0]["group_id"]
        # C.zip exists in MasterDB but is not a member of this group.
        self.assertFalse(self.repo.set_similar_group_representative(group_id, "snes|C.zip"))
        self.assertIsNone(self.repo.get_similar_groups("snes")[0]["representative"])

    def test_resave_resets_groups_and_representative(self):
        """재탐색은 해당 system의 그룹을 전부 새로 만든다(재분석) - 이전 대표 지정은
        초기화되는 게 의도된 설계."""
        self.repo.save_similar_groups("snes", [{"members": ["snes|A.zip", "snes|B.zip"], "pairs": []}])
        group_id = self.repo.get_similar_groups("snes")[0]["group_id"]
        self.repo.set_similar_group_representative(group_id, "snes|A.zip")

        self.repo.save_similar_groups("snes", [{"members": ["snes|B.zip", "snes|C.zip"], "pairs": []}])
        got = self.repo.get_similar_groups("snes")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["members"], ["snes|B.zip", "snes|C.zip"])
        self.assertIsNone(got[0]["representative"])
        self.assertNotEqual(got[0]["group_id"], group_id)

    def test_groups_scoped_per_system(self):
        self.repo.save_similar_groups("snes", [{"members": ["snes|A.zip", "snes|B.zip"], "pairs": []}])
        self.assertEqual(self.repo.get_similar_groups("nes"), [])

    def test_resaving_one_system_does_not_touch_another(self):
        self.repo.save_similar_groups("snes", [{"members": ["snes|A.zip", "snes|B.zip"], "pairs": []}])
        self.repo.save_similar_groups("nes", [])  # nes has < 2 candidates in this fixture; empty result
        self.assertEqual(len(self.repo.get_similar_groups("snes")), 1)

    def test_deleting_representative_rom_clears_representative_via_fk(self):
        """[P1 버그 수정] representative_rom_id에 FK(ON DELETE SET NULL)가 없으면,
        대표로 지정된 ROM이 삭제돼도 그 컬럼에 dangling rom_id가 그대로 남는다.
        get_similar_groups()가 조회 시점에 조용히 None으로 처리해서 화면은 안
        깨지지만, DB 원본 컬럼 값 자체는 깨진 참조로 남는다 - 여기서는 그 raw
        컬럼 값을 직접 SQL로 확인해서 실제로 NULL이 되는지 검증한다."""
        # 삭제 후에도 그룹이 (2명 미만이 되어 사라지지 않고) 계속 보이도록 3명으로 구성.
        self.repo.save_similar_groups("snes", [{"members": ["snes|A.zip", "snes|B.zip", "snes|C.zip"], "pairs": []}])
        group_id = self.repo.get_similar_groups("snes")[0]["group_id"]
        self.assertTrue(self.repo.set_similar_group_representative(group_id, "snes|B.zip"))

        row = self.repo.conn.execute(
            "SELECT representative_rom_id FROM similar_groups WHERE group_id=?", (group_id,)
        ).fetchone()
        self.assertIsNotNone(row["representative_rom_id"], "사전 조건: 대표가 설정되어 있어야 함")

        self.assertTrue(self.repo.delete_rom("snes|B.zip"))

        raw_row = self.repo.conn.execute(
            "SELECT representative_rom_id FROM similar_groups WHERE group_id=?", (group_id,)
        ).fetchone()
        self.assertIsNone(
            raw_row["representative_rom_id"],
            "FK(ON DELETE SET NULL)가 없으면 대표 ROM 삭제 후에도 이 raw 컬럼 값이 dangling rom_id로 남는다",
        )
        # 상위 API(get_similar_groups)의 동작도 그대로 유지되어야 한다 (대표 해제된 채로 그룹은 남음).
        got = self.repo.get_similar_groups("snes")
        self.assertEqual(len(got), 1)
        self.assertIsNone(got[0]["representative"])
        self.assertEqual(got[0]["members"], ["snes|A.zip", "snes|C.zip"], "삭제된 ROM은 멤버 목록에서도 CASCADE로 빠져야 함")


if __name__ == "__main__":
    unittest.main()
