"""
tests/test_gamelistset_membership.py
=====================================
v0.5 11단계(GameListSet 기반 다지기): SQLiteRepository의 game_list_set_roms
멤버십 native write 헬퍼(add/remove/sync/get)를 검증한다. import/export 엔진이
실제로 이 헬퍼를 호출하도록 배선하는 건 8단계에서 진행 - 여기서는 저장소
레벨 프리미티브 자체의 정확성만 검증한다.
"""
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.sqlite_db import SQLiteRepository


class GameListSetMembershipTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="retro_gls_"))
        self.repo = SQLiteRepository(self.tmpdir / "master.db")

    def tearDown(self):
        self.repo.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed_roms(self):
        data = {
            "roms": {
                "snes|Mario.zip": {
                    "system": "snes", "rom_filename": "Mario.zip",
                    "default_version_id": "v1", "core_override": None,
                    "versions": {"v1": {"created_at": "", "source_local_id": "a", "fields": {"name": "Mario"}}},
                    "media": {},
                },
                "snes|Zelda.zip": {
                    "system": "snes", "rom_filename": "Zelda.zip",
                    "default_version_id": "v1", "core_override": None,
                    "versions": {"v1": {"created_at": "", "source_local_id": "a", "fields": {"name": "Zelda"}}},
                    "media": {},
                },
                "snes|Metroid.zip": {
                    "system": "snes", "rom_filename": "Metroid.zip",
                    "default_version_id": "v1", "core_override": None,
                    "versions": {"v1": {"created_at": "", "source_local_id": "a", "fields": {"name": "Metroid"}}},
                    "media": {},
                },
            }
        }
        locals_data = [{"id": "local1", "label": "Local 1", "frontend": "es-de", "target_capacity_bytes": 5000}]
        self.repo.replace_from_dict(data, locals_data=locals_data)
        return data

    def test_add_and_get_members(self):
        self._seed_roms()
        added = self.repo.add_gamelistset_members("local1", ["snes|Mario.zip", "snes|Zelda.zip"])
        self.assertEqual(added, 2)
        self.assertEqual(self.repo.get_gamelistset_members("local1"), ["snes|Mario.zip", "snes|Zelda.zip"])

    def test_add_is_idempotent(self):
        self._seed_roms()
        self.repo.add_gamelistset_members("local1", ["snes|Mario.zip"])
        added_again = self.repo.add_gamelistset_members("local1", ["snes|Mario.zip"])
        self.assertEqual(added_again, 0)
        self.assertEqual(self.repo.get_gamelistset_members("local1"), ["snes|Mario.zip"])

    def test_unknown_legacy_key_is_skipped(self):
        self._seed_roms()
        added = self.repo.add_gamelistset_members("local1", ["snes|DoesNotExist.zip"])
        self.assertEqual(added, 0)
        self.assertEqual(self.repo.get_gamelistset_members("local1"), [])

    def test_remove_members(self):
        self._seed_roms()
        self.repo.add_gamelistset_members("local1", ["snes|Mario.zip", "snes|Zelda.zip"])
        removed = self.repo.remove_gamelistset_members("local1", ["snes|Mario.zip"])
        self.assertEqual(removed, 1)
        self.assertEqual(self.repo.get_gamelistset_members("local1"), ["snes|Zelda.zip"])

    def test_sync_membership_adds_and_removes(self):
        self._seed_roms()
        self.repo.add_gamelistset_members("local1", ["snes|Mario.zip", "snes|Zelda.zip"])
        self.repo.sync_gamelistset_membership("local1", ["snes|Zelda.zip", "snes|Metroid.zip"])
        self.assertEqual(
            self.repo.get_gamelistset_members("local1"),
            ["snes|Metroid.zip", "snes|Zelda.zip"],
        )

    def test_sync_membership_to_empty_clears_all(self):
        self._seed_roms()
        self.repo.add_gamelistset_members("local1", ["snes|Mario.zip", "snes|Zelda.zip"])
        self.repo.sync_gamelistset_membership("local1", [])
        self.assertEqual(self.repo.get_gamelistset_members("local1"), [])

    def test_get_gamelistset_ids_for_rom(self):
        data = self._seed_roms()
        # game_list_set_roms.set_id references game_list_sets(set_id), so local2
        # must exist there too before it can hold membership rows.
        locals_data = [
            {"id": "local1", "label": "Local 1", "frontend": "es-de", "target_capacity_bytes": 5000},
            {"id": "local2", "label": "Local 2", "frontend": "es-de"},
        ]
        self.repo.replace_from_dict(data, locals_data=locals_data)
        self.repo.add_gamelistset_members("local1", ["snes|Mario.zip"])
        self.repo.add_gamelistset_members("local2", ["snes|Mario.zip"])
        ids = self.repo.get_gamelistset_ids_for_rom("snes|Mario.zip")
        self.assertEqual(ids, ["local1", "local2"])
        self.assertEqual(self.repo.get_gamelistset_ids_for_rom("snes|Zelda.zip"), [])

    def test_membership_survives_unrelated_resync_via_sync_helper(self):
        """sync_gamelistset_membership로 심어둔 멤버십도 관련 없는 JSON 재저장(replace_from_dict)에
        영향받지 않아야 한다 - test_native_table_preservation.py의 수동 INSERT 버전과 동일한 계약."""
        self._seed_roms()
        self.repo.sync_gamelistset_membership("local1", ["snes|Mario.zip"])

        data = self.repo.snapshot()
        # 관련 없는 다른 rom을 건드리는 재저장을 흉내낸다.
        raw = {
            "roms": {
                "snes|Mario.zip": {"system": "snes", "rom_filename": "Mario.zip", "default_version_id": "v1",
                                    "core_override": "snes9x", "versions": {"v1": {"fields": {"name": "Mario"}}}, "media": {}},
                "snes|Zelda.zip": {"system": "snes", "rom_filename": "Zelda.zip", "default_version_id": "v1",
                                    "core_override": None, "versions": {"v1": {"fields": {"name": "Zelda"}}}, "media": {}},
                "snes|Metroid.zip": {"system": "snes", "rom_filename": "Metroid.zip", "default_version_id": "v1",
                                      "core_override": None, "versions": {"v1": {"fields": {"name": "Metroid"}}}, "media": {}},
            }
        }
        locals_data = [{"id": "local1", "label": "Local 1", "frontend": "es-de", "target_capacity_bytes": 5000}]
        self.repo.replace_from_dict(raw, locals_data=locals_data)
        self.assertEqual(self.repo.get_gamelistset_members("local1"), ["snes|Mario.zip"])


if __name__ == "__main__":
    unittest.main()
