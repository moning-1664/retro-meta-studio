"""
tests/test_compare_engine.py
==============================
v0.5 9단계: Compare 화면 백엔드(compare_engine.py) 검증.
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
import compare_engine as cmp_mod


class CompareEntriesUnitTests(unittest.TestCase):
    """순수 함수 compare_entries()만 검증 - 파일시스템/DB 필요 없음."""

    def _e(self, system, filename, fields=None):
        return {"system": system, "filename": filename, "fields": fields}

    def test_matched_and_left_only_and_right_only_rows(self):
        left = [self._e("snes", "Mario.zip"), self._e("snes", "OnlyLeft.zip")]
        right = [self._e("snes", "Mario.zip"), self._e("snes", "OnlyRight.zip")]
        rows = cmp_mod.compare_entries(left, right)
        by_file = {r["file"]: r for r in rows}
        self.assertTrue(by_file["Mario.zip"]["matched"])
        self.assertIsNotNone(by_file["Mario.zip"]["right"])
        self.assertFalse(by_file["OnlyLeft.zip"]["matched"])
        self.assertIsNone(by_file["OnlyLeft.zip"]["right"])
        self.assertFalse(by_file["OnlyRight.zip"]["matched"])
        self.assertIsNone(by_file["OnlyRight.zip"]["left"])

    def test_rows_sorted_by_filename(self):
        left = [self._e("snes", "Zelda.zip"), self._e("snes", "Mario.zip")]
        right = []
        rows = cmp_mod.compare_entries(left, right)
        self.assertEqual([r["file"] for r in rows], ["Mario.zip", "Zelda.zip"])

    def test_diff_flag_set_when_fields_differ(self):
        left = [self._e("snes", "Mario.zip", {"name": "Mario", "desc": "A"})]
        right = [self._e("snes", "Mario.zip", {"name": "Mario", "desc": "B"})]
        rows = cmp_mod.compare_entries(left, right)
        self.assertTrue(rows[0]["diff"])

    def test_diff_flag_false_when_fields_equal(self):
        left = [self._e("snes", "Mario.zip", {"name": "Mario", "desc": "A"})]
        right = [self._e("snes", "Mario.zip", {"name": "Mario", "desc": "A"})]
        rows = cmp_mod.compare_entries(left, right)
        self.assertFalse(rows[0]["diff"])

    def test_diff_flag_false_when_either_side_has_no_fields(self):
        left = [self._e("snes", "Mario.zip", None)]
        right = [self._e("snes", "Mario.zip", {"name": "Mario"})]
        rows = cmp_mod.compare_entries(left, right)
        self.assertFalse(rows[0]["diff"])

    def test_cross_system_never_matched(self):
        left = [self._e("snes", "Sonic.zip")]
        right = [self._e("megadrive", "Sonic.zip")]
        rows = cmp_mod.compare_entries(left, right)
        self.assertEqual(len(rows), 2)
        self.assertFalse(any(r["matched"] for r in rows))

    def test_normalized_unique_fallback_matches(self):
        left = [self._e("snes", "Mario (Kor).zip")]
        right = [self._e("snes", "Mario.zip")]
        rows = cmp_mod.compare_entries(left, right)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["matched"])

    def test_ambiguous_normalized_match_not_guessed(self):
        left = [self._e("snes", "Mario - A.zip")]
        right = [self._e("snes", "Mario - B.zip"), self._e("snes", "Mario - C.zip")]
        rows = cmp_mod.compare_entries(left, right)
        # Ambiguous fallback -> left stays unmatched, both right entries stand alone.
        self.assertEqual(len(rows), 3)
        self.assertFalse(any(r["matched"] for r in rows))

    def test_system_filter_restricts_comparison(self):
        left = [self._e("snes", "A.zip"), self._e("nes", "B.zip")]
        right = [self._e("snes", "A.zip"), self._e("nes", "B.zip")]
        rows = cmp_mod.compare_entries(left, right, system="snes")
        self.assertEqual([r["file"] for r in rows], ["A.zip"])


class CompareMatchIndexPerformanceTests(unittest.TestCase):
    """[P1 성능 수정] 정확한 파일명 매치가 매번 전체 리스트를 다시 순회하던 O(N*M)
    문제를 (system, filename) -> index 딕셔너리로 O(1) 조회하도록 고쳤다. 실제
    벽시계 시간 assert는 CI 환경마다 편차가 커서 피하고, 대신 "이 정도 규모에서
    타임아웃 없이 끝나는지"만 넉넉한 상한으로 확인한다 - O(N²)로 되돌아가면 이
    규모에서 수십 배 이상 느려지므로 회귀를 잡기엔 충분하다."""

    def test_exact_match_at_scale_completes_quickly(self):
        import time as time_mod
        n = 4000
        left = [{"system": "snes", "filename": f"Game{i}.zip", "fields": None} for i in range(n)]
        # 오른쪽은 절반만 정확히 일치하게 구성 - 나머지 절반은 "왼쪽에만 있음"이 되어야 함.
        right = [{"system": "snes", "filename": f"Game{i}.zip", "fields": None} for i in range(0, n, 2)]

        t0 = time_mod.time()
        rows = cmp_mod.compare_entries(left, right)
        elapsed = time_mod.time() - t0

        self.assertEqual(len(rows), n)
        self.assertEqual(sum(1 for r in rows if r["matched"]), n // 2)
        self.assertLess(elapsed, 5.0, "O(N*M) 선형 스캔으로 회귀하면 이 규모에서 훨씬 오래 걸림")

    def test_duplicate_filenames_on_right_side_each_match_a_distinct_left(self):
        """exact_index를 dict(단일 값)이 아니라 list로 만든 방어 코드 검증 - 오른쪽에
        (system, filename)이 완전히 동일한 항목이 여러 개 있어도 각각 서로 다른
        왼쪽 항목과 매칭될 수 있어야 한다(현재 collect_* 함수들은 dedupe하지만,
        compare_entries 자체는 그 가정에 기대지 않아야 함)."""
        left = [
            {"system": "snes", "filename": "Game.zip", "fields": {"name": "L1"}},
            {"system": "snes", "filename": "Game.zip", "fields": {"name": "L2"}},
        ]
        right = [
            {"system": "snes", "filename": "Game.zip", "fields": {"name": "R1"}},
            {"system": "snes", "filename": "Game.zip", "fields": {"name": "R2"}},
        ]
        rows = cmp_mod.compare_entries(left, right)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["matched"] for r in rows), "중복 파일명이 있어도 둘 다 매칭되어야 함")


class CollectEntriesIntegrationTests(unittest.TestCase):
    """collect_local_entries / collect_masterdb_entries가 실제 스캔/DB에서
    올바른 entry를 만들어내는지 (BT 레벨)."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="retro_cmp_"))
        self.masterdb_root = self.tmpdir / "masterdb"
        dbmod.ensure_masterdb_structure(self.masterdb_root)
        self.db = dbmod.load_db(self.masterdb_root)

    def tearDown(self):
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
        return local, root

    def test_collect_local_entries_includes_full_fields_for_diff(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name>"
            "<desc>A</desc><developer>Nintendo</developer></game></gameList>"
        )
        entries = cmp_mod.collect_local_entries(local)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["fields"]["developer"], "Nintendo")

    def test_collect_local_entries_populates_fields_when_rom_file_is_missing(self):
        """[P0 버그 수정, 2026-09-02] gamelist.xml에는 있지만 실제 ROM 파일이 없는
        (metadata-only) 항목은 scan_local()의 metadata_entries 경로를 타는데,
        collect_local_entries()가 그 dict를 "fields" 키로 읽었지만 실제 키는
        "_fields"였다 - 항상 None이 되어 Compare에서 FILE만 보이고 TITLE/DESCRIPTION이
        비어 보이는 버그였다."""
        local, root = self.make_esde_local()
        # 물리 ROM 파일은 만들지 않는다 - gamelist.xml만 존재.
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Zelda.zip</path><name>Zelda</name><desc>Missing ROM</desc></game></gameList>"
        )
        entries = cmp_mod.collect_local_entries(local)
        self.assertEqual(len(entries), 1)
        self.assertIsNotNone(entries[0]["fields"], "metadata-only 항목의 fields가 None이면 안 됨")
        self.assertEqual(entries[0]["fields"]["name"], "Zelda")
        self.assertEqual(entries[0]["fields"]["desc"], "Missing ROM")
        self.assertFalse(entries[0]["rom_matched"], "ROM 실물이 없으므로 rom_matched=False여야 함")
        self.assertFalse(cmp_mod.summarize_entry(entries[0])["romMatched"])

    def test_collect_local_entries_marks_rom_matched_true_when_file_exists(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name><desc>A</desc></game></gameList>"
        )
        entries = cmp_mod.collect_local_entries(local)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["rom_matched"])

    def test_collect_masterdb_entries_detects_missing_rom_file_on_disk(self):
        """[신규] MasterDB는 metadata만 있고 ROM 실물 파일이 디스크에서 사라진
        ("Missing ROM") 상태일 수 있다 - masterdb_root를 넘기면 실제 파일 존재
        여부로 rom_matched를 채운다."""
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name><desc>A</desc></game></gameList>"
        )
        # import_local_to_masterdb()는 metadata/media만 옮기고 ROM 실물 파일은
        # 손대지 않는다(별도 _copy_roms_to_masterdb() 단계에서만 복사됨) - 그래서
        # 여기서는 자연스럽게 "ROM 실물 없는 MasterDB entry"가 만들어진다.
        import_local_to_masterdb(local, self.masterdb_root, self.db)

        entries_without_root = cmp_mod.collect_masterdb_entries(self.db)
        self.assertTrue(entries_without_root[0]["rom_matched"], "masterdb_root 없으면 기존 동작대로 항상 True")

        entries_with_root = cmp_mod.collect_masterdb_entries(self.db, masterdb_root=self.masterdb_root)
        self.assertFalse(entries_with_root[0]["rom_matched"], "ROM 실물을 복사 안 했으므로 False여야 함")

    def test_collect_masterdb_entries_uses_filled_fields(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name><desc>A</desc></game></gameList>"
        )
        import_local_to_masterdb(local, self.masterdb_root, self.db)
        entries = cmp_mod.collect_masterdb_entries(self.db)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["filename"], "Mario.zip")
        self.assertEqual(entries[0]["fields"]["name"], "Mario")

    def test_masterdb_vs_local_end_to_end_diff_detected(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name><desc>A</desc></game></gameList>"
        )
        import_local_to_masterdb(local, self.masterdb_root, self.db)

        # Local's own copy of the metadata is later edited independently (desc changed).
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name><desc>Edited</desc></game></gameList>"
        )

        master_entries = cmp_mod.collect_masterdb_entries(self.db)
        local_entries = cmp_mod.collect_local_entries(local)
        rows = cmp_mod.compare_entries(master_entries, local_entries)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["matched"])
        self.assertTrue(rows[0]["diff"], "desc가 달라졌으니 [d] 플래그가 켜져야 함")

    def test_msx1_local_matches_canonical_msx_in_masterdb(self):
        """[P1 버그 수정] import_engine이 MasterDB에 저장할 때 msx1 -> msx로
        canonicalize하는 것과 똑같이, Compare도 canonical system 기준으로 매칭해야
        한다. 예전엔 raw Local system("msx1")과 MasterDB의 canonical system("msx")이
        일치하지 않아 같은 게임이 "왼쪽에만 있음"/"오른쪽에만 있음"으로 잘못
        갈라져 표시됐다."""
        local, root = self.make_esde_local()
        (root / "roms" / "msx1").mkdir(parents=True)
        (root / "meta" / "gamelists" / "msx1").mkdir(parents=True)
        (root / "roms" / "msx1" / "Game.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "msx1" / "gamelist.xml").write_text(
            "<gameList><game><path>./Game.zip</path><name>MSX Game</name><desc>A</desc></game></gameList>"
        )
        import_local_to_masterdb(local, self.masterdb_root, self.db)
        # import_engine이 canonical_system()을 거쳐 "msx"로 저장했는지 사전 확인.
        self.assertIn("msx|Game.zip", self.db["roms"])

        master_entries = cmp_mod.collect_masterdb_entries(self.db)
        local_entries = cmp_mod.collect_local_entries(local)
        rows = cmp_mod.compare_entries(master_entries, local_entries)

        self.assertEqual(len(rows), 1, "같은 게임인데 두 줄(양쪽에 하나씩)로 갈라지면 안 됨")
        self.assertTrue(rows[0]["matched"])
        self.assertEqual(rows[0]["system"], "msx", "행의 system은 canonical(msx)이어야 함")
        # compare_copy_row가 실제로 쓰는 side별 system은 raw여야 한다: MasterDB
        # 쪽은 canonical(msx) 그대로, Local 쪽은 raw(msx1) - import_engine의 target_roms
        # 필터링이 raw Local system을 기준으로 하기 때문이다.
        left = cmp_mod.summarize_entry(rows[0]["left"])
        right = cmp_mod.summarize_entry(rows[0]["right"])
        self.assertEqual(left["system"], "msx")
        self.assertEqual(right["system"], "msx1")


if __name__ == "__main__":
    unittest.main()
