"""
tests/test_compare_api.py
===========================
v0.5 9단계: api.py의 Compare 메서드(list_compare_sources/compare_sources/
compare_copy_row) 통합 테스트.
"""
import shutil
import unittest
from pathlib import Path

import config as cfgmod
import db as dbmod
from api import Api


class CompareApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path("/tmp/test_compare_api_" + self.id().split(".")[-1])
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        self._orig_config_path = cfgmod.CONFIG_PATH
        self._orig_backup_dir = cfgmod.BACKUP_DIR
        cfgmod.CONFIG_PATH = self.tmp / "config.json"
        cfgmod.BACKUP_DIR = self.tmp / "backup"
        self.api = Api()
        r = self.api.set_masterdb_path(str(self.tmp / "masterdb"))
        self.assertTrue(r["ok"], r)

    def tearDown(self):
        try:
            self.api.close()
        except Exception:
            pass
        cfgmod.CONFIG_PATH = self._orig_config_path
        cfgmod.BACKUP_DIR = self._orig_backup_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_esde_local(self, label, filename="Mario.zip", title="Mario", desc="A", with_rom=True):
        return self.make_esde_local_for(self.api, label, filename=filename, title=title, desc=desc, with_rom=with_rom)

    def make_esde_local_for(self, api, label, filename="Mario.zip", title="Mario", desc="A", with_rom=True):
        local_root = self.tmp / (label + "_ES-DE")
        (local_root / "roms" / "snes").mkdir(parents=True)
        (local_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (local_root / "meta" / "downloaded_media" / "snes" / "covers").mkdir(parents=True)
        if with_rom:
            (local_root / "roms" / "snes" / filename).write_text("dummy")
        (local_root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            f"<gameList><game><path>./{filename}</path><name>{title}</name><desc>{desc}</desc></game></gameList>",
            encoding="utf-8",
        )
        r = api.add_local(label, "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        self.assertTrue(r["ok"], r.get("error"))
        return r["data"]["id"], local_root

    def test_list_compare_sources_includes_masterdb_and_locals(self):
        local_id, _ = self.make_esde_local("Local1")
        sources = self.api.list_compare_sources()["data"]
        ids = {s["id"] for s in sources}
        self.assertIn("masterdb", ids)
        self.assertIn(local_id, ids)

    def test_compare_requires_two_distinct_sources(self):
        local_id, _ = self.make_esde_local("Local1")
        r = self.api.compare_sources(local_id, local_id)
        self.assertFalse(r["ok"])

    def test_compare_masterdb_vs_local_before_import_shows_local_only_row(self):
        local_id, _ = self.make_esde_local("Local1")
        r = self.api.compare_sources("masterdb", local_id)
        self.assertTrue(r["ok"], r)
        rows = r["data"]
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["left"])
        self.assertIsNotNone(rows[0]["right"])
        self.assertEqual(rows[0]["right"]["title"], "Mario")
        self.assertFalse(rows[0]["matched"])

    def test_compare_masterdb_vs_local_after_import_shows_matched_row(self):
        local_id, _ = self.make_esde_local("Local1")
        self.assertTrue(self.api.import_local_to_masterdb(local_id)["ok"])
        r = self.api.compare_sources("masterdb", local_id)
        rows = r["data"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["matched"])
        self.assertFalse(rows[0]["diff"])

    def test_compare_masterdb_entries_carry_favorite_flag(self):
        """[신규] Compare 필터바의 즐겨찾기 필터용. favorite은 SQLite-only라
        MasterDB(ArchiveDB) 쪽 entry에만 존재하고, Local 쪽은 항상 False다."""
        local_id, _ = self.make_esde_local("Local1")
        self.assertTrue(self.api.import_local_to_masterdb(local_id)["ok"])
        rom_key = next(iter(self.api.db["roms"].keys()))
        self.assertTrue(self.api.set_rom_favorite(rom_key, True)["ok"])

        r = self.api.compare_sources("masterdb", local_id)
        rows = r["data"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["left"]["favorite"])
        self.assertFalse(rows[0]["right"]["favorite"])

    def test_compare_sources_exposes_cached_sha256_and_none_when_not_cached(self):
        """[SHA256 Compare 컬럼] compare_sources()가 새로 SHA256을 계산하지 않고
        기존 SQLite hash cache(get_rom_hash)에서 조회만 하는지 확인한다 - 캐시가
        있으면 전체 64자 값 그대로 노출하고(자르지 않음 - 자르는 건 UI에서만),
        없으면 None을 돌려줘서 JS가 "-"로 표시할 수 있게 한다."""
        import hashlib
        local_id, _ = self.make_esde_local("Local1")
        self.assertTrue(self.api.import_local_to_masterdb(local_id)["ok"])
        rom_key = next(iter(self.api.db["roms"].keys()))
        system, filename = rom_key.split("|", 1)

        # 아직 SHA256이 캐시되기 전 - None이어야 한다.
        r1 = self.api.compare_sources("masterdb", local_id)
        self.assertTrue(r1["ok"], r1.get("error"))
        self.assertIsNone(r1["data"][0]["left"]["sha256"], "캐시되지 않은 SHA256이 None이 아님")

        # SHA256 background worker/cache 로직은 그대로 두고, 이미 캐시된 상태를
        # 직접 만들어서(set_rom_hash) 노출 여부만 검증한다.
        digest = hashlib.sha256(b"dummy-rom-bytes").hexdigest()
        self.assertEqual(len(digest), 64)
        self.api._sqlite.set_rom_hash(rom_key, digest)

        r2 = self.api.compare_sources("masterdb", local_id)
        self.assertTrue(r2["ok"], r2.get("error"))
        exposed = r2["data"][0]["left"]["sha256"]
        self.assertEqual(exposed, digest, "compare_sources가 캐시된 SHA256 전체 64자를 그대로 노출하지 않음")
        self.assertEqual(len(exposed), 64, "compare_sources가 SHA256을 잘라서 노출함 - 전체 64자를 유지해야 함")

    def test_compare_local_vs_local_left_only_and_right_only(self):
        local_a, _ = self.make_esde_local("LocalA", filename="OnlyA.zip", title="A")
        local_b, _ = self.make_esde_local("LocalB", filename="OnlyB.zip", title="B")
        r = self.api.compare_sources(local_a, local_b)
        rows = r["data"]
        self.assertEqual(len(rows), 2)
        by_file = {row["file"]: row for row in rows}
        self.assertIsNotNone(by_file["OnlyA.zip"]["left"])
        self.assertIsNone(by_file["OnlyA.zip"]["right"])
        self.assertIsNone(by_file["OnlyB.zip"]["left"])
        self.assertIsNotNone(by_file["OnlyB.zip"]["right"])

    def test_copy_row_masterdb_to_local(self):
        local_a, _ = self.make_esde_local("LocalA")
        self.assertTrue(self.api.import_local_to_masterdb(local_a)["ok"])
        local_b, root_b = self.make_esde_local("LocalB", with_rom=False, title="Placeholder", desc="")
        (root_b / "roms" / "snes" / "Mario.zip").write_text("dummy")

        r = self.api.compare_copy_row("masterdb", local_b, "toRight", "snes", "Mario.zip")
        self.assertTrue(r["ok"], r)

        written = (root_b / "meta" / "gamelists" / "snes" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertIn("Mario", written)

    def test_copy_row_local_to_local_bypasses_masterdb(self):
        """[v0.4.2] Local->Local은 이제 ArchiveDB를 거치지 않고 직접 복사된다
        (copy_local_to_local). ArchiveDB JSON에는 아무 것도 반영되지 않아야 한다."""
        local_a, _ = self.make_esde_local("LocalA", title="FromA", desc="desc-a")
        local_b, root_b = self.make_esde_local("LocalB", title="Placeholder", desc="")

        r = self.api.compare_copy_row(local_a, local_b, "toRight", "snes", "Mario.zip")
        self.assertTrue(r["ok"], r)

        # ArchiveDB는 전혀 건드리지 않아야 한다 - 직접 복사라 경유 안 함.
        games = self.api.list_masterdb_games()["data"]
        self.assertEqual(len(games), 0)

        written = (root_b / "meta" / "gamelists" / "snes" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertIn("FromA", written)

    def test_copy_row_local_to_local_works_without_masterdb_configured(self):
        """[v0.4.2] 직접 복사라 ArchiveDB가 아예 설정 안 돼 있어도 동작해야 한다."""
        cfgmod.CONFIG_PATH = self.tmp / "config_no_masterdb.json"
        api = Api()
        try:
            local_a, _ = self.make_esde_local_for(api, "LocalA2", title="FromA2")
            local_b, root_b = self.make_esde_local_for(api, "LocalB2", title="Placeholder", desc="")

            r = api.compare_copy_row(local_a, local_b, "toRight", "snes", "Mario.zip")
            self.assertTrue(r["ok"], r)
            written = (root_b / "meta" / "gamelists" / "snes" / "gamelist.xml").read_text(encoding="utf-8")
            self.assertIn("FromA2", written)
        finally:
            api.close()

    def test_copy_row_local_to_masterdb_only(self):
        local_a, _ = self.make_esde_local("LocalA", title="OnlyToMaster")
        r = self.api.compare_copy_row(local_a, "masterdb", "toRight", "snes", "Mario.zip")
        self.assertTrue(r["ok"], r)
        games = self.api.list_masterdb_games()["data"]
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["title"], "OnlyToMaster")

    def test_copy_row_direction_toleft(self):
        local_a, root_a = self.make_esde_local("LocalA", with_rom=False, title="Placeholder", desc="")
        (root_a / "roms" / "snes" / "Mario.zip").write_text("dummy")
        local_b, _ = self.make_esde_local("LocalB", title="FromB")

        # toLeft means source_b -> source_a.
        r = self.api.compare_copy_row(local_a, local_b, "toLeft", "snes", "Mario.zip")
        self.assertTrue(r["ok"], r)
        written = (root_a / "meta" / "gamelists" / "snes" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertIn("FromB", written)


    def test_copy_row_copies_rom_file_when_target_has_no_rom_file(self):
        """[v0.4.2] Compare 화면의 ArchiveDB->GameListSet 복사는 이제 ROM 파일
        자체도 새로 복사한다(copy_rom=True로 배선됨). 예전엔 대상 GameListSet에
        ROM 파일이 물리적으로 이미 있어야만 매칭/복사가 됐지만(P0 버그 수정 당시엔
        "실패해야 정상"이었음), 이제는 ArchiveDB가 ROM 원본을 들고 있으니 대상에
        아예 없던 ROM도 새로 만들어 복사할 수 있어야 사용성이 올라간다."""
        local_a, _ = self.make_esde_local("LocalA")
        self.assertTrue(self.api.import_local_to_masterdb(local_a)["ok"])
        # ArchiveDB가 ROM 실물도 들고 있는 상태를 시뮬레이션한다(별도의
        # "Export to ArchiveDB > ROM 포함" 경로로 이미 저장돼 있었다고 가정).
        stored = dbmod.rom_storage_path(self.api.cfg["masterdb"]["root"], "snes", "Mario.zip")
        stored.parent.mkdir(parents=True, exist_ok=True)
        stored.write_bytes(b"dummy-rom-bytes")
        # LocalB는 ROM 파일 없이 만든다 (with_rom=False이고 이후에도 추가 안 함).
        local_b, root_b = self.make_esde_local("LocalB", with_rom=False, title="Placeholder", desc="")
        self.assertFalse((root_b / "roms" / "snes" / "Mario.zip").exists())

        r = self.api.compare_copy_row("masterdb", local_b, "toRight", "snes", "Mario.zip")
        self.assertTrue(r["ok"], r)

        # ROM 파일 자체가 새로 복사되어 있어야 한다.
        copied_rom = root_b / "roms" / "snes" / "Mario.zip"
        self.assertTrue(copied_rom.exists())
        self.assertEqual(copied_rom.read_bytes(), b"dummy-rom-bytes")
        written = (root_b / "meta" / "gamelists" / "snes" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertIn("Mario", written)

    def test_copy_row_local_to_local_copies_rom_file_when_target_missing_it(self):
        """[v0.4.2] Local->Local 직접 복사도 ROM 실물을 옮긴다(ArchiveDB는
        전혀 거치지 않는다 - test_copy_row_local_to_local_bypasses_masterdb 참고)."""
        local_a, _ = self.make_esde_local("LocalA", title="FromA")
        local_b, root_b = self.make_esde_local("LocalB", with_rom=False, title="Placeholder", desc="")
        self.assertFalse((root_b / "roms" / "snes" / "Mario.zip").exists())

        r = self.api.compare_copy_row(local_a, local_b, "toRight", "snes", "Mario.zip")
        self.assertTrue(r["ok"], r)

        copied_rom = root_b / "roms" / "snes" / "Mario.zip"
        self.assertTrue(copied_rom.exists())
        # ArchiveDB 저장소로는 복사되지 않아야 한다 - 직접 경로라 안 거침.
        stored = dbmod.rom_storage_path(self.api.cfg["masterdb"]["root"], "snes", "Mario.zip")
        self.assertFalse(stored.exists())

    def test_copy_row_success_reports_exported_count(self):
        local_a, _ = self.make_esde_local("LocalA")
        self.assertTrue(self.api.import_local_to_masterdb(local_a)["ok"])
        local_b, root_b = self.make_esde_local("LocalB", with_rom=False, title="Placeholder", desc="")
        (root_b / "roms" / "snes" / "Mario.zip").write_text("dummy")

        r = self.api.compare_copy_row("masterdb", local_b, "toRight", "snes", "Mario.zip")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["exported"], 1)

    def test_copy_rows_batch_copies_multiple_and_reports_partial_failure(self):
        """[신규] Compare 다중 선택 일괄 복사. 한 항목이 실패해도 나머지는
        계속 진행하고, 실패 항목을 개별적으로 보고해야 한다(조용히 감추면 안 됨)."""
        local_a, _ = self.make_esde_local("LocalA", filename="A1.zip", title="A1")
        (self.tmp / "LocalA_ES-DE" / "roms" / "snes" / "A2.zip").write_text("dummy")
        (self.tmp / "LocalA_ES-DE" / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            '<gameList>'
            '<game><path>./A1.zip</path><name>A1</name><desc>d</desc></game>'
            '<game><path>./A2.zip</path><name>A2</name><desc>d</desc></game>'
            '</gameList>', encoding="utf-8",
        )
        local_b, root_b = self.make_esde_local("LocalB", with_rom=False, title="Placeholder", desc="")

        r = self.api.compare_copy_rows(local_a, local_b, "toRight", [
            {"system": "snes", "filename": "A1.zip"},
            {"system": "snes", "filename": "A2.zip"},
            {"system": "snes", "filename": "DoesNotExist.zip"},
        ])
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["copied"], 2)
        self.assertEqual(r["data"]["total"], 3)
        self.assertEqual(len(r["data"]["failed"]), 1)
        self.assertEqual(r["data"]["failed"][0]["filename"], "DoesNotExist.zip")

        self.assertTrue((root_b / "roms" / "snes" / "A1.zip").exists())
        self.assertTrue((root_b / "roms" / "snes" / "A2.zip").exists())

    def test_copy_rows_rejects_empty_items(self):
        local_a, _ = self.make_esde_local("LocalA")
        local_b, _ = self.make_esde_local("LocalB", with_rom=False, title="Placeholder", desc="")
        r = self.api.compare_copy_rows(local_a, local_b, "toRight", [])
        self.assertFalse(r["ok"])

    def test_copy_row_local_to_local_copies_rom_even_when_source_has_no_metadata(self):
        """[리뷰 반영] metadata/media/ROM은 서로 독립적으로 처리해야 한다. 예전엔
        metadata가 없으면(gamelist.xml에 항목이 없음) 그 자리에서 continue해서
        ROM이 실제로 존재하는데도 통째로 복사가 안 됐다."""
        local_a, root_a = self.make_esde_local("LocalA", with_rom=False, title="Placeholder", desc="")
        # gamelist.xml에는 아무 항목도 없다(metadata 없음) - 하지만 ROM 파일은 있다.
        (root_a / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList></gameList>", encoding="utf-8",
        )
        (root_a / "roms" / "snes" / "Mario.zip").write_bytes(b"ROM_BYTES")
        local_b, root_b = self.make_esde_local("LocalB", with_rom=False, title="Placeholder", desc="")

        r = self.api.compare_copy_row(local_a, local_b, "toRight", "snes", "Mario.zip")
        self.assertTrue(r["ok"], r)

        copied_rom = root_b / "roms" / "snes" / "Mario.zip"
        self.assertTrue(copied_rom.exists(), "metadata가 없다는 이유로 ROM까지 통째로 스킵됨")
        self.assertEqual(copied_rom.read_bytes(), b"ROM_BYTES")

    def test_copy_row_local_to_local_reports_partial_when_dest_rom_already_exists(self):
        """[리뷰 반영] 대상에 이미 같은 이름의 ROM이 있으면(정책: 덮어쓰지 않고
        건너뜀) metadata는 정상적으로 옮겨지므로 API는 ok=True를 반환하지만,
        ROM은 조용히 안 옮겨진 걸 GUI가 구분할 수 있도록 partial=True와
        romConflicts를 같이 돌려줘야 한다 - "성공"으로만 뭉개면 안 된다."""
        local_a, _ = self.make_esde_local("LocalA", title="FromA")
        local_b, root_b = self.make_esde_local("LocalB", title="Placeholder", desc="")
        original_rom_bytes = (root_b / "roms" / "snes" / "Mario.zip").read_bytes()

        r = self.api.compare_copy_row(local_a, local_b, "toRight", "snes", "Mario.zip")
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["data"].get("partial"), "대상 ROM 충돌이 있는데 partial 플래그가 안 뜸")
        self.assertEqual(r["data"].get("romConflicts"), 1)
        # 대상 ROM 실물은 손대지 않아야 한다(덮어쓰기 정책 아님).
        self.assertEqual((root_b / "roms" / "snes" / "Mario.zip").read_bytes(), original_rom_bytes)
        # metadata는 정상적으로 옮겨졌어야 한다.
        written = (root_b / "meta" / "gamelists" / "snes" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertIn("FromA", written)


if __name__ == "__main__":
    unittest.main()
