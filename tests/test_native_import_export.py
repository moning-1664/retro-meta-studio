"""
tests/test_native_import_export.py
====================================
v0.5 8단계: import_engine.py/export_engine.py를 native SQLite write로 전환한
결과를 검증한다.

- sqlite_repo를 넘기면 replace_from_dict()를 한 번도 호출하지 않고도
  rom/version/media가 SQLite에 정확히 반영되는지 (engine 레벨).
- GameListSet 멤버십(game_list_set_roms)이 import/export 양쪽에서 채워지는지.
- 레거시 alias 시스템명 병합이 발생하면 alias_merge_occurred=True로 신호를
  보내는지 (그 경우 호출자는 전체 replace_from_dict()로 안전하게 재동기화해야 함).
"""
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as cfgmod
import db as dbmod
from import_engine import import_local_to_masterdb
from export_engine import export_masterdb_to_local
from database.sqlite_db import SQLiteRepository


class NativeIOBaseTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="retro_native_ie_"))
        self.masterdb_root = self.tmpdir / "masterdb"
        dbmod.ensure_masterdb_structure(self.masterdb_root)
        self.db = dbmod.load_db(self.masterdb_root)
        self.repo = SQLiteRepository(self.masterdb_root / "master.db")

    def tearDown(self):
        self.repo.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def make_esde_local(self, name="local1"):
        root = self.tmpdir / name
        (root / "roms" / "snes").mkdir(parents=True)
        (root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (root / "meta" / "downloaded_media" / "snes" / "covers").mkdir(parents=True)

        local = cfgmod.new_local_entry(name, f"LOCAL ({name})", "es-de")
        local["rom_path"] = str(root / "roms")
        local["metadata_path"] = str(root / "meta")
        local["media_path"] = str(root / "meta")
        # game_list_set_roms.set_id references game_list_sets(set_id) - register it
        # directly via SQL (NOT replace_from_dict({"roms": {}}, ...), which would treat
        # an empty roms dict as "every previously-imported rom was deleted from JSON"
        # and wipe out roms other locals already imported in this same test).
        with self.repo.conn:
            self.repo.conn.execute(
                "INSERT OR IGNORE INTO game_list_sets(set_id, name, frontend) VALUES(?,?,?)",
                (name, local["label"], "es-de"),
            )
        return local, root


class NativeImportWriteTests(NativeIOBaseTestCase):
    def test_import_writes_rom_version_media_without_full_resync(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name>"
            "<desc>Adventure</desc><genre>Platform</genre></game></gameList>"
        )
        (root / "meta" / "downloaded_media" / "snes" / "covers" / "Mario.png").write_bytes(b"\x89PNG")

        result = import_local_to_masterdb(local, self.masterdb_root, self.db, sqlite_repo=self.repo)
        self.assertEqual(result["imported"], 1)
        self.assertFalse(result["alias_merge_occurred"])

        # Never called replace_from_dict() on self.repo - only the targeted native
        # write methods (ensure_rom/insert_version/set_media) - yet the projection
        # must already be fully correct.
        row = self.repo.get_rom("snes|Mario.zip")
        self.assertIsNotNone(row)
        self.assertEqual(len(row["versions"]), 1)
        self.assertEqual(row["versions"][0]["fields"]["name"], "Mario")
        self.assertEqual(row["default_version_id"], row["versions"][0]["version_id"])
        self.assertIn("covers", row["media"])

    def test_duplicate_import_skips_native_version_write(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name>"
            "<desc>Adventure</desc></game></gameList>"
        )
        import_local_to_masterdb(local, self.masterdb_root, self.db, sqlite_repo=self.repo)
        result2 = import_local_to_masterdb(local, self.masterdb_root, self.db, sqlite_repo=self.repo)
        self.assertEqual(result2["duplicates_skipped"], 1)
        row = self.repo.get_rom("snes|Mario.zip")
        self.assertEqual(len(row["versions"]), 1, "중복 metadata는 새 Version을 만들면 안 됨")

    def test_import_populates_gamelistset_membership(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "roms" / "snes" / "NoMeta.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name>"
            "<desc>Adventure</desc></game></gameList>"
        )
        import_local_to_masterdb(local, self.masterdb_root, self.db, sqlite_repo=self.repo)
        members = self.repo.get_gamelistset_members("local1")
        self.assertEqual(members, ["snes|Mario.zip"], "gamelist에 없는(metadata/media 전혀 없는) ROM은 멤버십 대상이 아님")

    def test_full_local_import_sync_removes_stale_membership(self):
        """target_roms=None(전체 Local Import)은 이번 스캔 결과와 정확히 일치하도록
        멤버십을 교체해야 한다 - 이전에 있었지만 이번엔 없는 rom은 제거되어야 함."""
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "roms" / "snes" / "Zelda.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList>"
            "<game><path>./Mario.zip</path><name>Mario</name><desc>A</desc></game>"
            "<game><path>./Zelda.zip</path><name>Zelda</name><desc>B</desc></game>"
            "</gameList>"
        )
        import_local_to_masterdb(local, self.masterdb_root, self.db, sqlite_repo=self.repo)
        self.assertEqual(self.repo.get_gamelistset_members("local1"), ["snes|Mario.zip", "snes|Zelda.zip"])

        # Zelda disappears entirely from this Local (file removed, gamelist entry removed).
        (root / "roms" / "snes" / "Zelda.zip").unlink()
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name><desc>A</desc></game></gameList>"
        )

        import_local_to_masterdb(local, self.masterdb_root, self.db, sqlite_repo=self.repo)
        self.assertEqual(
            self.repo.get_gamelistset_members("local1"), ["snes|Mario.zip"],
            "더 이상 scan에서 발견되지 않는 rom은 전체 Import 재실행 시 멤버십에서 빠져야 함",
        )

    def test_target_roms_partial_import_only_adds_membership(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "roms" / "snes" / "Zelda.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList>"
            "<game><path>./Mario.zip</path><name>Mario</name><desc>A</desc></game>"
            "<game><path>./Zelda.zip</path><name>Zelda</name><desc>B</desc></game>"
            "</gameList>"
        )
        import_local_to_masterdb(local, self.masterdb_root, self.db, sqlite_repo=self.repo, target_roms=[("snes", "Mario.zip")])
        self.assertEqual(self.repo.get_gamelistset_members("local1"), ["snes|Mario.zip"])
        import_local_to_masterdb(local, self.masterdb_root, self.db, sqlite_repo=self.repo, target_roms=[("snes", "Zelda.zip")])
        self.assertEqual(self.repo.get_gamelistset_members("local1"), ["snes|Mario.zip", "snes|Zelda.zip"])


class ImportBatchTransactionSafetyTests(NativeIOBaseTestCase):
    """[P0 버그 수정] import_local_to_masterdb의 SQLite batch()가 수동 __enter__/
    __exit__ 대신 `with`를 쓰는지 - 루프 중간에 예상 못 한 예외가 나도 rollback되고
    batch_depth가 원복되어 이후 SQLite 쓰기가 영구히 멈추지 않는지 검증한다."""

    def test_unexpected_exception_mid_loop_rolls_back_and_does_not_wedge_batch_depth(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "roms" / "snes" / "Zelda.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList>"
            "<game><path>./Mario.zip</path><name>Mario</name><desc>A</desc></game>"
            "<game><path>./Zelda.zip</path><name>Zelda</name><desc>B</desc></game>"
            "</gameList>"
        )

        # Mario는 정상 처리되게 두고, Zelda의 version 생성 시점에 예상 못 한 예외를
        # 강제로 발생시킨다 (KeyError/버그 등 어떤 예외든 재현 가능해야 한다는 리뷰
        # 지적을 그대로 재현).
        import db as dbmod_module
        original_add_version = dbmod_module.add_version

        def boom(rom_entry, *args, **kwargs):
            if rom_entry.get("rom_filename") == "Zelda.zip" or "Zelda" in str(kwargs.get("fields", {})):
                raise RuntimeError("simulated unexpected failure mid-import")
            return original_add_version(rom_entry, *args, **kwargs)

        dbmod_module.add_version = boom
        try:
            with self.assertRaises(RuntimeError):
                import_local_to_masterdb(local, self.masterdb_root, self.db, sqlite_repo=self.repo)
        finally:
            dbmod_module.add_version = original_add_version

        # batch()의 finally가 확실히 실행되어 depth가 원복되어야 한다 - 그렇지 않으면
        # _commit()이 "batch 중"이라고 착각해서 이후 모든 쓰기가 커밋되지 않는다.
        self.assertEqual(self.repo._batch_depth, 0)

        # 트랜잭션 전체가 rollback되어야 한다 (Mario만 부분 커밋되면 안 됨) -
        # with-statement 전환 전에는 수동 __enter__/__exit__라 __exit__가 스킵되고
        # rollback도 전혀 일어나지 않았다.
        self.assertIsNone(self.repo.get_rom("snes|Mario.zip"))
        self.assertIsNone(self.repo.get_rom("snes|Zelda.zip"))

        # repo가 "영구히 막힌" 상태가 아니라는 걸 실제로 증명 - 실패 이후 재시도가
        # 정상적으로 커밋되어야 한다. 재시도는 disk에서 다시 읽은 새 self.db로 한다:
        # 이번 실패 케이스에서 in-memory self.db는 (실제 api.py 호출 경로와 동일하게)
        # 예외로 인해 한 번도 저장(_save_db)되지 않았으므로, 실제 재실행 시나리오는
        # "그 프로세스가 다음에 다시 시도할 때도 같은 in-memory self.db 객체를 그대로
        # 재사용한다"인데, 이건 SQLite와 별개로 JSON 쪽 in-memory dict 자체가 트랜잭션
        # 개념이 없어 부분 mutation이 그대로 남는 문제라 이 테스트(SQLite batch 안전성)의
        # 스코프 밖이다 - 별도 이슈로 memory.md에 기록해뒀다. 여기서는 SQLite 쪽만
        # 검증하기 위해 disk 상태를 반영한 새 dict로 재시도한다.
        fresh_db = dbmod.load_db(self.masterdb_root)
        result = import_local_to_masterdb(local, self.masterdb_root, fresh_db, sqlite_repo=self.repo)
        self.assertEqual(result["imported"], 2)
        self.assertIsNotNone(self.repo.get_rom("snes|Mario.zip"))
        self.assertIsNotNone(self.repo.get_rom("snes|Zelda.zip"))


class AliasMergeFallbackTests(NativeIOBaseTestCase):
    def test_alias_merge_sets_flag_for_full_resync_fallback(self):
        """ESDE_SYSTEM_ALIASES의 레거시 alias 키(예: 'genesis')로 이미 저장된 entry가
        있으면, 이번 Import에서 canonical 'megadrive' 키로 병합되면서
        alias_merge_occurred=True가 켜져야 한다 (api.py가 이걸 보고 native mirror 대신
        전체 replace_from_dict()로 안전하게 재동기화함)."""
        local, root = self.make_esde_local()
        shutil.rmtree(root / "roms" / "snes")
        shutil.rmtree(root / "meta" / "gamelists" / "snes")
        (root / "roms" / "megadrive").mkdir(parents=True)
        (root / "meta" / "gamelists" / "megadrive").mkdir(parents=True)
        (root / "roms" / "megadrive" / "Sonic.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "megadrive" / "gamelist.xml").write_text(
            "<gameList><game><path>./Sonic.zip</path><name>Sonic</name><desc>Fast</desc></game></gameList>"
        )
        # Pre-seed a legacy alias-keyed entry as if it were imported before the
        # canonical-key normalization existed.
        self.db["roms"]["genesis|Sonic.zip"] = {
            "system": "genesis", "rom_filename": "Sonic.zip", "default_version_id": "v_old",
            "core_override": None, "versions": {"v_old": {"created_at": "", "source_local_id": "x", "fields": {"name": "Sonic (old)"}}},
            "media": {},
        }

        result = import_local_to_masterdb(local, self.masterdb_root, self.db, sqlite_repo=self.repo)
        self.assertTrue(result["alias_merge_occurred"])
        self.assertNotIn("genesis|Sonic.zip", self.db["roms"])
        self.assertIn("megadrive|Sonic.zip", self.db["roms"])


class NativeExportMembershipTests(NativeIOBaseTestCase):
    def test_export_populates_gamelistset_membership_for_matched_roms(self):
        # Import into MasterDB first from one Local...
        src_local, src_root = self.make_esde_local("srclocal")
        (src_root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (src_root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name><desc>A</desc></game></gameList>"
        )
        import_local_to_masterdb(src_local, self.masterdb_root, self.db, sqlite_repo=self.repo)

        # ...then export it out to a second Local that merely has the ROM file present.
        dst_local, dst_root = self.make_esde_local("dstlocal")
        (dst_root / "roms" / "snes" / "Mario.zip").write_text("dummy")

        export_result = export_masterdb_to_local(
            dst_local, self.masterdb_root, self.db,
            {"korean_only_on_conflict": True, "copy_media": True, "copy_video": True},
            conflict_resolver=lambda *a: "ok", sqlite_repo=self.repo,
        )
        self.assertEqual(export_result["exported"], 1)
        self.assertEqual(self.repo.get_gamelistset_members("dstlocal"), ["snes|Mario.zip"])

    def test_export_with_no_match_does_not_add_membership(self):
        dst_local, dst_root = self.make_esde_local("dstlocal")
        (dst_root / "roms" / "snes" / "Unknown.zip").write_text("dummy")
        export_result = export_masterdb_to_local(
            dst_local, self.masterdb_root, self.db,
            {"korean_only_on_conflict": True, "copy_media": True, "copy_video": True},
            conflict_resolver=lambda *a: "ok", sqlite_repo=self.repo,
        )
        self.assertEqual(export_result["skipped_no_match"], 1)
        self.assertEqual(self.repo.get_gamelistset_members("dstlocal"), [])


if __name__ == "__main__":
    unittest.main()
