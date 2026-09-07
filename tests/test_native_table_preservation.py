"""
tests/test_native_table_preservation.py
========================================
회귀 테스트: replace_from_dict()가 매번 roms 테이블 전체를 지웠다 다시 채우면서
rom_id가 바뀌고(AUTOINCREMENT는 재사용되지 않음), ON DELETE CASCADE로 인해
favorites / similar_group_members / game_list_set_roms 같은 "SQLite에만 존재하는"
데이터가 아무 관련 없는 JSON 저장 한 번에 통째로 사라지던 문제를 검증한다.
"""
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.sqlite_db import SQLiteRepository


class NativeTablePreservationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="retro_native_"))
        self.repo = SQLiteRepository(self.tmpdir / "master.db")

    def tearDown(self):
        self.repo.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _base_json(self):
        return {
            "roms": {
                "snes|Mario.zip": {
                    "system": "snes", "rom_filename": "Mario.zip",
                    "default_version_id": "v1", "core_override": None,
                    "versions": {"v1": {"created_at": "", "source_local_id": "a", "fields": {"name": "Mario"}}},
                    "media": {"covers": "/x/cover.png"},
                }
            }
        }

    def test_rom_id_stable_across_unrelated_resync(self):
        data = self._base_json()
        self.repo.replace_from_dict(data, locals_data=[])
        rom_id_before = self.repo._rom_id("snes|Mario.zip")

        # 관련 없는 재저장(다른 rom 필드 추가) - Mario는 안 바뀜
        data["roms"]["snes|Mario.zip"]["core_override"] = "snes9x"
        self.repo.replace_from_dict(data, locals_data=[])
        rom_id_after = self.repo._rom_id("snes|Mario.zip")

        self.assertEqual(rom_id_before, rom_id_after, "관련 없는 저장으로 rom_id가 바뀌면 안 됨")

    def test_favorite_survives_unrelated_json_resync(self):
        data = self._base_json()
        self.repo.replace_from_dict(data, locals_data=[])
        rom_id = self.repo._rom_id("snes|Mario.zip")
        self.repo.conn.execute("INSERT INTO favorites(rom_id) VALUES(?)", (rom_id,))
        self.repo.conn.commit()

        # 이 게임과 무관한 필드 하나를 바꾸고 저장 (예: 다른 화면에서 다른 게임 편집)
        data["roms"]["snes|Mario.zip"]["core_override"] = "snes9x"
        self.repo.replace_from_dict(data, locals_data=[])

        remaining = self.repo.conn.execute("SELECT COUNT(*) FROM favorites WHERE rom_id=?", (rom_id,)).fetchone()[0]
        self.assertEqual(remaining, 1, "관련 없는 JSON 재저장으로 favorites가 삭제되면 안 됨")

    def test_game_list_set_membership_survives_unrelated_resync(self):
        data = self._base_json()
        locals_data = [{"id": "local1", "label": "Local 1", "frontend": "es-de", "target_capacity_bytes": 1000}]
        self.repo.replace_from_dict(data, locals_data=locals_data)
        rom_id = self.repo._rom_id("snes|Mario.zip")
        self.repo.conn.execute(
            "INSERT INTO game_list_set_roms(set_id, rom_id) VALUES(?,?)", ("local1", rom_id)
        )
        self.repo.conn.commit()

        data["roms"]["snes|Mario.zip"]["core_override"] = "snes9x"
        self.repo.replace_from_dict(data, locals_data=locals_data)

        remaining = self.repo.conn.execute(
            "SELECT COUNT(*) FROM game_list_set_roms WHERE set_id=? AND rom_id=?", ("local1", rom_id)
        ).fetchone()[0]
        self.assertEqual(remaining, 1, "관련 없는 JSON 재저장으로 GameListSet 소속이 삭제되면 안 됨")

    def test_removing_rom_from_json_still_cascades_favorite(self):
        """ROM 자체가 진짜로 삭제된 경우엔 native-only 연관 데이터도 같이 사라지는 게 맞다."""
        data = self._base_json()
        self.repo.replace_from_dict(data, locals_data=[])
        rom_id = self.repo._rom_id("snes|Mario.zip")
        self.repo.conn.execute("INSERT INTO favorites(rom_id) VALUES(?)", (rom_id,))
        self.repo.conn.commit()

        del data["roms"]["snes|Mario.zip"]
        self.repo.replace_from_dict(data, locals_data=[])

        self.assertIsNone(self.repo._rom_id("snes|Mario.zip"))
        remaining = self.repo.conn.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
        self.assertEqual(remaining, 0, "실제로 삭제된 ROM의 favorite은 같이 사라져야 함(cascade)")


if __name__ == "__main__":
    unittest.main()
