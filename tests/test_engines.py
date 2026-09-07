"""
tests/test_engines.py
=======================
BT(Behavior Test) 레벨 회귀 테스트 - 실제 사용자 흐름을 흉내낸 end-to-end 시나리오.
(단위 함수 하나만 검증하는 UT와 달리, "Local 등록 -> 스캔 -> Import -> Export"처럼
 여러 모듈이 엮인 실제 사용 흐름 전체가 깨지지 않는지 확인한다.)

tkinter가 필요 없는 순수 로직(엔진) 레이어만 다룬다. GUI 동작은
MANUAL_GUI_TEST_CHECKLIST.md를 참고해 Windows에서 수동 확인한다.

실행: python3 -m unittest tests.test_engines -v   (retro_manager 폴더에서)
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
from export_engine import export_masterdb_to_local, copy_local_to_local
from cleanup_engine import reset_metadata, orphan_cleanup


class BaseTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="retro_bt_"))
        self.masterdb_root = self.tmpdir / "masterdb"
        dbmod.ensure_masterdb_structure(self.masterdb_root)
        self.db = dbmod.load_db(self.masterdb_root)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def make_esde_local(self, name="local1"):
        # [일치화] GUI에서 이제 Metadata/Media 경로를 하나로 통합해서 받으므로,
        # 테스트 픽스처도 실제 ES-DE 구조(<root>/meta에 gamelists/와 downloaded_media/가 같이 있음)를 재현.
        root = self.tmpdir / name
        (root / "roms" / "snes").mkdir(parents=True)
        (root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (root / "meta" / "downloaded_media" / "snes" / "covers").mkdir(parents=True)

        local = cfgmod.new_local_entry(name, f"LOCAL ({name})", "es-de")
        local["rom_path"] = str(root / "roms")
        local["metadata_path"] = str(root / "meta")
        local["media_path"] = str(root / "meta")  # [설계 변경] metadata_path와 항상 동일
        return local, root


class TestImportExportRoundTrip(BaseTestCase):
    """시나리오: ES-DE Local 등록 -> ROM/metadata 배치 -> MasterDB Import -> 다시 Export."""

    def test_full_roundtrip(self):
        local, root = self.make_esde_local()

        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name>"
            "<desc>Adventure</desc><genre>Platform</genre></game></gameList>"
        )

        result = import_local_to_masterdb(local, self.masterdb_root, self.db)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["duplicates_skipped"], 0)
        dbmod.save_db(self.masterdb_root, self.db)

        # 재 Import 시 완전히 동일한 내용은 중복 스킵되어야 한다.
        result2 = import_local_to_masterdb(local, self.masterdb_root, self.db)
        self.assertEqual(result2["duplicates_skipped"], 1)

        # 다른 Local(빈 gamelist)로 Export했을 때 정상적으로 파일이 써지는지.
        local2, root2 = self.make_esde_local("local2")
        (root2 / "roms" / "snes" / "Mario.zip").write_text("dummy")

        export_result = export_masterdb_to_local(
            local2, self.masterdb_root, self.db,
            {"korean_only_on_conflict": True, "copy_media": True, "copy_video": True},
            conflict_resolver=lambda *a: "ok",
        )
        self.assertEqual(export_result["exported"], 1)

        written = (root2 / "meta" / "gamelists" / "snes" / "gamelist.xml").read_text()
        self.assertIn("Mario", written)


class TestVideoMediaTypeIsSoleGate(BaseTestCase):
    """[리뷰 반영] Media 선택 대화상자의 "Videos" 체크박스(selected_media)와
    export_options.copy_video(전역 설정)가 이중으로 videos 복사를 게이트하고
    있었다 - 대화상자에서 Videos를 체크해도 기존 config.json에 copy_video=false가
    남아있으면(과거 값) 조용히 복사가 안 되는 시나리오가 가능했다. media_types를
    명시했을 땐 그 안에 "videos"가 있는지만으로 결정해야 한다."""

    def test_videos_copied_when_selected_even_if_copy_video_option_is_false(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name></game></gameList>"
        )
        (root / "meta" / "downloaded_media" / "snes" / "videos").mkdir(parents=True)
        (root / "meta" / "downloaded_media" / "snes" / "videos" / "Mario.mp4").write_bytes(b"VIDEO_BYTES")

        import_local_to_masterdb(local, self.masterdb_root, self.db)

        local2, root2 = self.make_esde_local("local2")
        (root2 / "roms" / "snes" / "Mario.zip").write_text("dummy")

        export_result = export_masterdb_to_local(
            local2, self.masterdb_root, self.db,
            {"copy_media": True, "copy_video": False},  # 전역 옵션은 꺼져 있음
            conflict_resolver=lambda *a: "ok",
            media_types=["videos"],  # 대화상자에서 Videos를 명시적으로 선택
        )
        self.assertEqual(export_result["exported"], 1)
        video_path = root2 / "meta" / "downloaded_media" / "snes" / "videos" / "Mario.mp4"
        self.assertTrue(video_path.exists(), "Videos를 선택했는데 copy_video=False 전역 설정 때문에 복사가 안 됨")
        self.assertEqual(video_path.read_bytes(), b"VIDEO_BYTES")

    def test_videos_not_copied_when_not_selected_even_if_copy_video_option_is_true(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name></game></gameList>"
        )
        (root / "meta" / "downloaded_media" / "snes" / "videos").mkdir(parents=True)
        (root / "meta" / "downloaded_media" / "snes" / "videos" / "Mario.mp4").write_bytes(b"VIDEO_BYTES")
        (root / "meta" / "downloaded_media" / "snes" / "covers" / "Mario.png").write_bytes(b"COVER")

        import_local_to_masterdb(local, self.masterdb_root, self.db)

        local2, root2 = self.make_esde_local("local2")
        (root2 / "roms" / "snes" / "Mario.zip").write_text("dummy")

        export_masterdb_to_local(
            local2, self.masterdb_root, self.db,
            {"copy_media": True, "copy_video": True},  # 전역 옵션은 켜져 있음
            conflict_resolver=lambda *a: "ok",
            media_types=["covers"],  # Videos는 선택하지 않음
        )
        video_path = root2 / "meta" / "downloaded_media" / "snes" / "videos" / "Mario.mp4"
        self.assertFalse(video_path.exists())
        cover_path = root2 / "meta" / "downloaded_media" / "snes" / "covers" / "Mario.png"
        self.assertTrue(cover_path.exists())


class TestCopyLocalToLocalIndependentSteps(BaseTestCase):
    """[리뷰 반영] copy_local_to_local()의 metadata/media/ROM은 서로 독립적으로
    처리되어야 한다 - 하나가 없거나 실패해도 나머지가 통째로 스킵되면 안 되고,
    결과에도 무엇이 실제로 됐는지 세분화해서 남아야 "부분 성공"이 "성공"으로
    뭉개지지 않는다."""

    def test_metadata_missing_does_not_block_media_or_rom(self):
        local_a, root_a = self.make_esde_local("localA")
        (root_a / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text("<gameList></gameList>")
        (root_a / "roms" / "snes" / "Mario.zip").write_bytes(b"ROM_BYTES")
        (root_a / "meta" / "downloaded_media" / "snes" / "covers" / "Mario.png").write_bytes(b"COVER_BYTES")
        local_b, root_b = self.make_esde_local("localB")

        result = copy_local_to_local(local_a, local_b, target_roms=[("snes", "Mario.zip")], copy_rom=True)
        self.assertEqual(result["skipped_no_metadata"], 1)
        self.assertEqual(result["metadata_copied"], 0)
        self.assertEqual(result["rom_copied"], 1)
        self.assertEqual(result["media_copied"], 1)
        self.assertEqual(result["exported"], 1, "media/ROM은 실제로 옮겨졌으니 exported에 잡혀야 함")
        self.assertTrue((root_b / "roms" / "snes" / "Mario.zip").exists())
        self.assertEqual((root_b / "meta" / "downloaded_media" / "snes" / "covers" / "Mario.png").read_bytes(), b"COVER_BYTES")

    def test_media_write_failure_is_reported_without_losing_metadata_success(self):
        from unittest.mock import patch
        local_a, root_a = self.make_esde_local("localA")
        (root_a / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name></game></gameList>"
        )
        (root_a / "meta" / "downloaded_media" / "snes" / "covers" / "Mario.png").write_bytes(b"COVER_BYTES")
        local_b, root_b = self.make_esde_local("localB")

        with patch("exporters.es_de.write_media", side_effect=RuntimeError("disk full")):
            result = copy_local_to_local(local_a, local_b, target_roms=[("snes", "Mario.zip")], copy_rom=False)

        self.assertEqual(result["metadata_copied"], 1)
        self.assertEqual(result["media_copied"], 0)
        self.assertEqual(result["exported"], 1, "metadata는 성공했으니 exported에는 잡혀야 함")
        self.assertTrue(result["errors"], "media 실패가 errors에 안 남으면 조용히 부분 실패가 숨겨짐")
        self.assertIn("disk full", result["errors"][0])
        written = (root_b / "meta" / "gamelists" / "snes" / "gamelist.xml").read_text()
        self.assertIn("Mario", written)

    def test_dest_rom_already_present_is_left_untouched_and_counted_as_conflict(self):
        local_a, root_a = self.make_esde_local("localA")
        (root_a / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name></game></gameList>"
        )
        (root_a / "roms" / "snes" / "Mario.zip").write_bytes(b"NEW_ROM")
        local_b, root_b = self.make_esde_local("localB")
        (root_b / "roms" / "snes" / "Mario.zip").write_bytes(b"OLD_ROM")

        result = copy_local_to_local(local_a, local_b, target_roms=[("snes", "Mario.zip")], copy_rom=True)
        self.assertEqual(result["rom_conflicts"], 1)
        self.assertEqual(result["rom_copied"], 0)
        # 정책: 덮어쓰지 않는다 - 대상 ROM은 그대로여야 한다.
        self.assertEqual((root_b / "roms" / "snes" / "Mario.zip").read_bytes(), b"OLD_ROM")
        # metadata는 정상적으로 옮겨져야 한다(ROM 충돌과 무관).
        self.assertEqual(result["metadata_copied"], 1)


class TestSystemNameMapping(BaseTestCase):
    """시나리오: Local의 시스템 폴더명이 MasterDB 표준과 다를 때 매핑이 정확히 적용되는지."""

    def test_mapping_applies_on_both_directions(self):
        local, root = self.make_esde_local()
        # 폴더명을 표준과 다르게 재구성
        shutil.rmtree(root / "roms" / "snes")
        shutil.rmtree(root / "meta" / "gamelists" / "snes")
        (root / "roms" / "super_nintendo").mkdir(parents=True)
        (root / "meta" / "gamelists" / "super_nintendo").mkdir(parents=True)

        (root / "roms" / "super_nintendo" / "Zelda.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "super_nintendo" / "gamelist.xml").write_text(
            "<gameList><game><path>./Zelda.zip</path><name>Zelda</name>"
            "<desc>Legend</desc></game></gameList>"
        )
        local["system_name_map"] = {"super_nintendo": "snes"}

        result = import_local_to_masterdb(local, self.masterdb_root, self.db)
        self.assertEqual(result["imported"], 1)
        self.assertIn("snes|Zelda.zip", self.db["roms"])
        self.assertNotIn("super_nintendo|Zelda.zip", self.db["roms"])


class TestOrphanAndResetCleanup(BaseTestCase):
    """시나리오: ROM이 삭제된 뒤 Orphan Cleanup / Reset Metadata가 안전하게 동작하는지."""

    def test_orphan_cleanup_removes_only_missing_rom_entries(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Kept.zip").write_text("x")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList>"
            "<game><path>./Kept.zip</path><name>Kept</name></game>"
            "<game><path>./Ghost.zip</path><name>Ghost</name></game>"
            "</gameList>"
        )
        removed = orphan_cleanup(local)
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0]["filename"], "Ghost.zip")

        content = (root / "meta" / "gamelists" / "snes" / "gamelist.xml").read_text()
        self.assertIn("Kept", content)
        self.assertNotIn("Ghost", content)

    def test_reset_metadata_preserves_rom_files(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Kept.zip").write_text("x")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Kept.zip</path><name>Kept</name></game></gameList>"
        )
        reset_metadata(local)
        self.assertTrue((root / "roms" / "snes" / "Kept.zip").exists())
        self.assertFalse((root / "meta" / "gamelists" / "snes" / "gamelist.xml").exists())

    def test_reset_metadata_does_not_delete_roms_nested_inside_metadata_root(self):
        """[BUG FIX 회귀 방지] 실제로 흔한 ES-DE 구조 - ROM 폴더가 metadata_path 루트
        바로 밑에 형제 폴더로 같이 있는 경우(예: ES-DE/ROMs, ES-DE/gamelists,
        ES-DE/downloaded_media가 전부 ES-DE/ 밑에 있는 구조). 예전 버그는 media_path를
        es_media_root()로 좁히지 않고 그대로 순회해서, 이런 구조에서 ROM 폴더까지
        통째로 rmtree되는 심각한 데이터 손실을 일으켰다."""
        root = Path(self.tmpdir) / "nested_test"
        es_root = root / "ES-DE"
        (es_root / "ROMs" / "snes").mkdir(parents=True)
        (es_root / "gamelists" / "snes").mkdir(parents=True)
        (es_root / "downloaded_media" / "snes" / "covers").mkdir(parents=True)
        (es_root / "ROMs" / "snes" / "Important.zip").write_text("precious rom data")
        (es_root / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Important.zip</path><name>Important</name></game></gameList>"
        )
        (es_root / "downloaded_media" / "snes" / "covers" / "Important.png").write_bytes(b"X")

        local = cfgmod.new_local_entry("l1", "Local", "es-de")
        local["rom_path"] = str(es_root / "ROMs")
        local["metadata_path"] = str(es_root)  # <- 위험한 구조: metadata_path가 ES-DE 루트
        local["media_path"] = str(es_root)

        reset_metadata(local)

        self.assertTrue((es_root / "ROMs" / "snes" / "Important.zip").exists(),
                         "ROM 파일이 삭제되면 안 된다 (CleanUp 심각 버그)")
        self.assertFalse((es_root / "downloaded_media" / "snes").exists())

    def test_orphan_cleanup_actually_deletes_media_for_es_de(self):
        """[BUG FIX 회귀 방지] _remove_es_style_entry가 es_media_root()를 안 거쳐서
        ES-DE의 media 파일이 조용히 삭제 안 되던 문제 (orphan_cleanup은 성공했다고
        보고하지만 실제로 media 파일이 그대로 남아있었음)."""
        local, root = self.make_esde_local()
        (root / "meta" / "downloaded_media" / "snes" / "covers").mkdir(parents=True, exist_ok=True)
        ghost_cover = root / "meta" / "downloaded_media" / "snes" / "covers" / "Ghost.png"
        ghost_cover.write_bytes(b"X")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Ghost.zip</path><name>Ghost</name></game></gameList>"
        )
        orphan_cleanup(local)
        self.assertFalse(ghost_cover.exists(), "orphan_cleanup이 media 파일을 실제로 못 지우던 버그")


class TestEmptyLocalDoesNotCrash(BaseTestCase):
    """시나리오: 완전히 빈 Local(메타데이터/ROM 없음)을 등록/스캔/Import 해도 예외 없이 동작하는지."""

    def test_scan_and_import_on_empty_local(self):
        from importers.scan import detect_local_structure, scan_local

        local, root = self.make_esde_local()  # 폴더만 만들고 파일은 하나도 안 넣음

        status, msg = detect_local_structure(
            local["rom_path"], local["metadata_path"], local["media_path"], "es-de"
        )
        # 폴더 구조 자체는 존재하므로 "valid"가 정상이며, 데이터가 없다는 것은
        # 별도로 rom_list가 빈 배열인지로 확인한다 (구조 유효성과 데이터 존재 여부는 별개).
        self.assertIn(status, ("valid", "warning", "invalid"))  # 어떤 값이든 예외 없이 반환되어야 함

        result = scan_local(local)
        self.assertEqual(result["rom_list"], [])

        import_result = import_local_to_masterdb(local, self.masterdb_root, self.db)
        self.assertEqual(import_result["imported"], 0)
        self.assertEqual(len(import_result["unmatched"]), 0)


class ScanLocalProgressTests(BaseTestCase):
    """[P0-3 리뷰 반영] scan_local()의 progress_cb는 "Scan 전체 진행률"이라는
    합성값(예전의 min(meta, media, rom) 0~100 스케일)을 만들지 않는다 - 그 책임은
    여러 Phase를 하나의 progress bar로 이어붙이는 API Job controller(api.py)가
    진다. scan.py는 지금 실제로 진행 중인 작업(metadata 인덱싱/media 인덱싱/ROM
    순회) 각각의 실제 current/total을 있는 그대로 보고할 뿐이다 - 그래서 각
    단계 내부에서는 역행하지 않아야 하지만, 단계가 바뀌는 시점엔(예: media
    인덱싱 1/1 -> ROM 순회 1/5) current/total의 절대값이 이전 단계보다 작아지는
    게 정상이다(더 이상 하나의 0~100 스케일이 아니므로)."""

    def test_progress_never_regresses_within_rom_phase_and_reaches_final_rom_count(self):
        local, root = self.make_esde_local()
        for i in range(5):
            (root / "roms" / "snes" / f"Game{i}.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList>" + "".join(
                f"<game><path>./Game{i}.zip</path><name>Game{i}</name><desc>D{i}</desc></game>"
                for i in range(5)
            ) + "</gameList>"
        )
        from importers.scan import scan_local

        calls = []
        scan_local(local, progress_cb=lambda current, total, label: calls.append((current, total, label)))

        self.assertTrue(calls, "progress_cb가 한 번도 안 불림")
        # ROM 순회 구간(total==5)만 뽑아서 역행하지 않는지 확인한다.
        rom_phase = [c for c in calls if c[1] == 5]
        self.assertTrue(rom_phase, f"ROM 순회 단계(total=5) 호출이 없음: {calls}")
        currents = [c[0] for c in rom_phase]
        for a, b in zip(currents, currents[1:]):
            self.assertLessEqual(a, b, f"ROM 순회 진행률이 역행함: {currents}")
        self.assertEqual(rom_phase[-1][0], 5, "ROM 순회 단계는 마지막에 정확히 전체 개수에 도달해야 한다")

    def test_progress_reports_metadata_only_local_with_no_roms_without_crashing(self):
        """물리 ROM이 전혀 없는(metadata-only) Local도 예외 없이 스캔이 끝나야
        한다 - ROM 개수(분모)가 0인 상태에서 progress_cb가 호출되거나 나눗셈
        예외가 나면 안 된다."""
        local, root = self.make_esde_local()
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Ghost.zip</path><name>Ghost</name></game></gameList>"
        )
        from importers.scan import scan_local

        calls = []
        scan_local(local, progress_cb=lambda current, total, label: calls.append((current, total, label)))
        self.assertTrue(calls)
        for current, total, _label in calls:
            self.assertGreater(total, 0, "total이 0인 progress_cb 호출은 나눗셈 예외로 이어질 수 있다")


class TestRetroArchPlaylistCrossPlatformPath(BaseTestCase):
    """시나리오: 이 PC(Windows 가정)에서 생성한 .lpl을 안드로이드 등 다른 기기에 복사해서 쓸 때,
    playlist 안의 경로가 실행 OS 구분자로 오염되지 않고 항상 forward-slash로 유지되는지."""

    def test_target_path_stays_forward_slash_even_with_backslash_input(self):
        from exporters.retroarch_lpl import build_playlist_for_system

        rom_entry = dbmod.get_or_create_rom_entry(self.db, "snes", "Mario.zip")
        dbmod.add_version(rom_entry, "local1", {"name": "Mario"})
        dbmod.set_system_default_core(self.db, "snes", "snes9x")

        crc_dir = self.tmpdir / "crc_source" / "snes"
        crc_dir.mkdir(parents=True)
        (crc_dir / "Mario.zip").write_bytes(b"testdata")

        playlist = build_playlist_for_system(
            self.db, "snes", str(crc_dir), target_path_prefix="/storage/emulated/0/ROMs/snes"
        )
        self.assertEqual(playlist["items"][0]["path"], "/storage/emulated/0/ROMs/snes/Mario.zip")
        self.assertNotIn("\\", playlist["items"][0]["path"])
        self.assertNotEqual(playlist["items"][0]["crc32"], "DETECT")  # 로컬 파일 기준 CRC는 정상 계산되어야 함


class TestUnconfiguredLocalGuard(BaseTestCase):
    """시나리오: Local이 경로 미설정 상태(rom_path/metadata_path 비어있음)일 때
    엔진이 크래시하거나(더 나쁘게는) 엉뚱한 경로(cwd)를 스캔/삭제하지 않고
    명확한 LocalPathError를 내는지. (pathlib이 빈 문자열을 cwd로 해석하는 문제 방지)"""

    def test_import_with_empty_paths_raises_clear_error(self):
        from config import LocalPathError

        local = cfgmod.new_local_entry("local1", "미설정 Local", "es-de")
        # rom_path, metadata_path를 일부러 비워둠 (등록만 하고 경로 설정 안 한 상태)
        with self.assertRaises(LocalPathError):
            import_local_to_masterdb(local, self.masterdb_root, self.db)

    def test_reset_metadata_with_empty_paths_raises_clear_error(self):
        """[안전장치 검증] 삭제 작업은 특히 중요 - cwd를 잘못 지우는 사고를 막아야 한다."""
        from config import LocalPathError

        local = cfgmod.new_local_entry("local1", "미설정 Local", "es-de")
        with self.assertRaises(LocalPathError):
            reset_metadata(local)

    def test_orphan_cleanup_with_empty_paths_raises_clear_error(self):
        from config import LocalPathError

        local = cfgmod.new_local_entry("local1", "미설정 Local", "es-de")
        with self.assertRaises(LocalPathError):
            orphan_cleanup(local)


class TestSharedMediaPolicy(BaseTestCase):
    """media는 ROM 레벨 단일 관리(버전별 아님)라는 원칙은 유지하되, [정책 변경] 여러 번
    Import될 때마다 media는 항상 최신 소스 내용으로 덮어써진다 (SHA 비교/기존값 보존
    없음 - 무조건 덮어쓰기가 비교용 읽기까지 하는 것보다 오히려 I/O가 적어서 채택).
    예전엔 "최초 1회만 저장, 이후 안 건드림"이었으나 폐기됨."""

    def test_media_always_overwritten_by_later_import(self):
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name>"
            "<desc>Adventure v1</desc></game></gameList>"
        )
        (root / "meta" / "downloaded_media" / "snes" / "covers" / "Mario.png").write_bytes(b"COVER_V1")

        import_local_to_masterdb(local, self.masterdb_root, self.db)
        rom_entry = dbmod.get_or_create_rom_entry(self.db, "snes", "Mario.zip")
        self.assertTrue(rom_entry["media"])
        cover_path = rom_entry["media"]["covers"]
        self.assertEqual(Path(cover_path).read_bytes(), b"COVER_V1")

        # 다른 소스에서 다른 커버로 재 Import (내용이 달라야 새 버전이 추가됨)
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name>"
            "<desc>Adventure v2 completely different text</desc></game></gameList>"
        )
        (root / "meta" / "downloaded_media" / "snes" / "covers" / "Mario.png").write_bytes(b"COVER_V2_DIFFERENT")

        import_local_to_masterdb(local, self.masterdb_root, self.db)
        rom_entry2 = dbmod.get_or_create_rom_entry(self.db, "snes", "Mario.zip")

        # media는 이제 최신 소스 내용으로 덮어써져야 함 (실제 파일 바이트로 검증)
        cover_path2 = rom_entry2["media"]["covers"]
        self.assertEqual(Path(cover_path2).read_bytes(), b"COVER_V2_DIFFERENT")
        # 그러나 metadata는 새로운 version으로 추가되어야 함 (desc가 달라졌으므로)
        self.assertEqual(len(rom_entry2["versions"]), 2)

    def test_screenshot_set_replaced_not_accumulated_and_old_file_removed(self):
        """리스트형(screenshots)도 '누적'이 아니라 '완전 교체' - 이전 세트 파일은 지워져야 함."""
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "meta" / "downloaded_media" / "snes" / "screenshots").mkdir(parents=True)
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name></game></gameList>"
        )
        (root / "meta" / "downloaded_media" / "snes" / "screenshots" / "Mario.png").write_bytes(b"SHOT_V1")
        import_local_to_masterdb(local, self.masterdb_root, self.db)
        rom_entry = dbmod.get_or_create_rom_entry(self.db, "snes", "Mario.zip")
        old_paths = [Path(p) for p in rom_entry["media"]["screenshots"]]
        self.assertEqual(len(old_paths), 1)
        self.assertTrue(old_paths[0].exists())

        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>MarioRenamed</name></game></gameList>"
        )
        (root / "meta" / "downloaded_media" / "snes" / "screenshots" / "Mario.png").write_bytes(b"SHOT_V2")
        import_local_to_masterdb(local, self.masterdb_root, self.db)
        rom_entry2 = dbmod.get_or_create_rom_entry(self.db, "snes", "Mario.zip")

        new_paths = rom_entry2["media"]["screenshots"]
        self.assertEqual(len(new_paths), 1, "누적되면 안 되고 새 세트로 교체되어야 함")
        self.assertEqual(Path(new_paths[0]).read_bytes(), b"SHOT_V2")
        # 목적지 파일명이 재사용되는 경우(파일 1개)엔 old_paths[0]가 new_paths[0]와 같은
        # 경로일 수 있으므로, "그 경로가 사라졌는지"가 아니라 "디스크에 고아 파일 없이
        # 정확히 새 세트만 남아있는지"로 검증한다.
        dest_dir = Path(new_paths[0]).parent
        screenshot_files = sorted(dest_dir.glob("screenshots*"))
        self.assertEqual(len(screenshot_files), 1, "디스크에 고아 screenshot 파일이 남으면 안 됨")
        self.assertEqual(screenshot_files[0].read_bytes(), b"SHOT_V2")


    def test_media_shared_across_all_versions_not_per_version(self):
        """스키마 자체에 version별 media 필드가 없어야 한다 (ROM 레벨에만 존재)."""
        local, root = self.make_esde_local()
        (root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name>"
            "<desc>Adventure</desc></game></gameList>"
        )
        import_local_to_masterdb(local, self.masterdb_root, self.db)
        rom_entry = dbmod.get_or_create_rom_entry(self.db, "snes", "Mario.zip")
        for vid, vdata in rom_entry["versions"].items():
            self.assertNotIn("media", vdata, "Version dict에 media 필드가 남아있으면 안 됨 (ROM 레벨로 이동했어야 함)")
        self.assertIn("media", rom_entry, "media는 ROM 레벨에 존재해야 함")


class TestVersionIdCollisionRegression(BaseTestCase):
    """[심각 버그 회귀 방지] 과거 new_version_id()가 밀리초 단위였을 때, 같은 밀리초 안에
    여러 Version이 생성되면 ID가 충돌해 이전 Version 데이터가 덮어써져 유실되는 문제가 있었다.
    빠른 연속 생성 시에도 데이터 유실이 없는지 확인한다."""

    def test_rapid_version_creation_never_collides_or_loses_data(self):
        rom_entry = dbmod.get_or_create_rom_entry(self.db, "snes", "Mario.zip")
        vids = []
        for i in range(50):
            vid = dbmod.add_version(rom_entry, f"local{i}", {"name": "Mario", "desc": f"desc-{i}"})
            vids.append(vid)

        self.assertEqual(len(vids), len(set(vids)), "Version ID 충돌 발생 (데이터 유실 위험)")
        self.assertEqual(len(rom_entry["versions"]), 50, "일부 Version이 덮어써져 유실됨")
        # 순서 보장 확인 (created 순서 = list_versions_sorted 순서)
        sorted_ids = [vid for vid, _ in dbmod.list_versions_sorted(rom_entry)]
        self.assertEqual(sorted_ids, vids)


class TestVersionCleanupFeature(BaseTestCase):
    """Feature A: 설정 > Metadata 설정 > 버전 일괄 정리."""

    def test_latest_non_default_wins_on_conflicting_blank_fields(self):
        rom_entry = dbmod.get_or_create_rom_entry(self.db, "snes", "Mario.zip")
        dbmod.add_version(rom_entry, "l1", {"name": "Mario", "desc": ""})  # default, genre/desc 없음
        dbmod.add_version(rom_entry, "l2", {"name": "Mario", "desc": "Old", "genre": "Action"})
        dbmod.add_version(rom_entry, "l3", {"name": "Mario", "desc": "Newest", "genre": "Platform"})

        result = dbmod.cleanup_non_default_versions(self.db)
        self.assertEqual(result["roms_processed"], 1)
        self.assertEqual(result["versions_removed"], 2)

        fields = dbmod.get_default_fields(rom_entry)
        self.assertEqual(fields["desc"], "Newest")
        self.assertEqual(fields["genre"], "Platform")
        self.assertEqual(len(rom_entry["versions"]), 1)

    def test_does_not_overwrite_existing_default_field(self):
        """default에 이미 값이 있는 필드는 non-default 값으로 덮어쓰지 않아야 한다."""
        rom_entry = dbmod.get_or_create_rom_entry(self.db, "snes", "Zelda.zip")
        dbmod.add_version(rom_entry, "l1", {"name": "Zelda", "desc": "Original desc"})
        dbmod.add_version(rom_entry, "l2", {"name": "Zelda", "desc": "Should not appear"})

        dbmod.cleanup_non_default_versions(self.db)
        fields = dbmod.get_default_fields(rom_entry)
        self.assertEqual(fields["desc"], "Original desc")

    def test_media_untouched_by_version_cleanup(self):
        """media는 ROM 레벨 단일 관리이므로 버전 정리와 무관하게 그대로 유지되어야 한다."""
        rom_entry = dbmod.get_or_create_rom_entry(self.db, "snes", "Contra.zip")
        dbmod.set_rom_media(rom_entry, {"covers": "/some/path/cover.png"})
        dbmod.add_version(rom_entry, "l1", {"name": "Contra", "desc": "d1"})
        dbmod.add_version(rom_entry, "l2", {"name": "Contra", "desc": "d2"})

        dbmod.cleanup_non_default_versions(self.db)
        self.assertEqual(rom_entry["media"], {"covers": "/some/path/cover.png"})


class TestVerDiffMigrationHelper(BaseTestCase):
    """Feature B: Ver Diff 대화창에서 버전 삭제 시 고유 정보를 살아남는 버전으로 이전."""

    def test_delete_side_migrates_unique_fields_into_survivor(self):
        rom_entry = dbmod.get_or_create_rom_entry(self.db, "snes", "Mario.zip")
        v1 = dbmod.add_version(rom_entry, "l1", {"name": "Mario", "desc": "d1", "genre": ""})
        v2 = dbmod.add_version(rom_entry, "l2", {"name": "Mario", "desc": "d2", "genre": "Platform"})

        # v2를 삭제하면서 v2에만 있던 genre 정보를 v1으로 이전
        survivor_fields = dbmod.migrate_unique_fields(
            rom_entry["versions"][v2]["fields"], rom_entry["versions"][v1]["fields"]
        )
        self.assertEqual(survivor_fields["genre"], "Platform")
        self.assertEqual(survivor_fields["desc"], "d1")  # v1에 이미 있던 값은 유지

    def test_is_version_empty_requires_both_title_and_desc(self):
        self.assertTrue(dbmod.is_version_empty({"name": "", "desc": ""}))
        self.assertTrue(dbmod.is_version_empty({"name": "Mario", "desc": ""}))
        self.assertTrue(dbmod.is_version_empty({"name": "", "desc": "Some desc"}))
        self.assertFalse(dbmod.is_version_empty({"name": "Mario", "desc": "Some desc"}))


class TestMediaCopyAtomicity(BaseTestCase):
    """[P0 버그 수정] _copy_media_to_masterdb가 새 소스 복사에 실패해도 기존 파일을
    지우지 않는지 검증한다. 예전엔 호출자가 복사 전에 기존 파일을 먼저 지웠기 때문에,
    소스가 깨져서 복사가 실패하면 DB에는 예전 경로가 남아있는데 실제 파일은 이미
    사라진 상태가 될 수 있었다(리뷰에서 지적된 실제 데이터 손상 시나리오)."""

    def test_failed_copy_leaves_existing_file_untouched(self):
        from import_engine import _copy_media_to_masterdb

        src_dir = self.tmpdir / "src"
        src_dir.mkdir()
        good_cover = src_dir / "cover_v1.png"
        good_cover.write_bytes(b"COVER_V1")

        # 1차: 정상 복사.
        saved1 = _copy_media_to_masterdb(self.masterdb_root, "snes", "Mario.zip", {"covers": [str(good_cover)]})
        self.assertIn("covers", saved1)
        cover_path = Path(saved1["covers"])
        self.assertEqual(cover_path.read_bytes(), b"COVER_V1")

        # 2차: 소스가 사라진 상태(깨진 gamelist/media 경로 등)로 재시도 - 존재하지
        # 않는 경로를 그대로 넘긴다.
        missing_src = src_dir / "does_not_exist.png"
        saved2 = _copy_media_to_masterdb(self.masterdb_root, "snes", "Mario.zip", {"covers": [str(missing_src)]})

        # 실패한 타입은 반환 dict에 아예 없어야 한다 (호출자가 existing_media를
        # 그대로 유지하도록).
        self.assertNotIn("covers", saved2)
        # 기존 파일은 그대로 남아있어야 하고(삭제되면 안 됨), 내용도 그대로여야 한다.
        self.assertTrue(cover_path.exists(), "복사 실패 시 기존 media 파일이 삭제되면 안 됨")
        self.assertEqual(cover_path.read_bytes(), b"COVER_V1")
        # staging에 쓰던 .tmp 파일도 고아로 안 남아야 한다.
        leftover_tmp = list(cover_path.parent.glob("*.tmp"))
        self.assertEqual(leftover_tmp, [], "실패한 복사의 .tmp staging 파일이 정리되어야 함")

    def test_one_media_type_failing_does_not_affect_other_types(self):
        from import_engine import _copy_media_to_masterdb

        src_dir = self.tmpdir / "src"
        src_dir.mkdir()
        good_cover = src_dir / "cover.png"
        good_cover.write_bytes(b"COVER_OK")
        missing_wheel = src_dir / "missing_wheel.png"

        saved = _copy_media_to_masterdb(
            self.masterdb_root, "snes", "Mario.zip",
            {"covers": [str(good_cover)], "wheel": [str(missing_wheel)]},
        )
        self.assertIn("covers", saved)
        self.assertNotIn("wheel", saved, "존재하지 않는 소스를 가진 타입만 실패해야 하고 다른 타입은 영향받지 않아야 함")
        self.assertEqual(Path(saved["covers"]).read_bytes(), b"COVER_OK")


class TestCsvExportImport(BaseTestCase):
    """Feature C: CSV Export/Import (일괄 편집용, add/upsert 방식, media 제외)."""

    def test_export_includes_every_version_as_separate_row(self):
        from csv_engine import export_db_to_csv
        import csv as csv_mod

        rom_entry = dbmod.get_or_create_rom_entry(self.db, "snes", "Mario.zip")
        dbmod.add_version(rom_entry, "l1", {"name": "Mario", "desc": "d1"})
        dbmod.add_version(rom_entry, "l2", {"name": "Mario", "desc": "d2"})

        csv_path = self.tmpdir / "export.csv"
        count = export_db_to_csv(self.db, csv_path)
        self.assertEqual(count, 2)

        rows = list(csv_mod.DictReader(csv_path.open(encoding="utf-8-sig")))
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["desc"] for r in rows}, {"d1", "d2"})

    def test_import_upserts_existing_version_and_adds_new_rom(self):
        from csv_engine import export_db_to_csv, import_csv_to_db
        import csv as csv_mod

        rom_entry = dbmod.get_or_create_rom_entry(self.db, "snes", "Mario.zip")
        dbmod.add_version(rom_entry, "l1", {"name": "Mario", "desc": "original"})

        csv_path = self.tmpdir / "edit.csv"
        export_db_to_csv(self.db, csv_path)

        rows = list(csv_mod.DictReader(csv_path.open(encoding="utf-8-sig")))
        rows[0]["desc"] = "edited"
        new_row = {k: "" for k in rows[0].keys()}
        new_row.update({"system": "nes", "rom_filename": "Zelda.zip", "is_default": "1",
                         "name": "Zelda", "desc": "brand new"})
        rows.append(new_row)
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv_mod.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        result = import_csv_to_db(csv_path, self.db)
        self.assertEqual(result["overwritten"], 1)
        self.assertEqual(result["added"], 1)

        mario_fields = dbmod.get_default_fields(rom_entry)
        self.assertEqual(mario_fields["desc"], "edited")
        self.assertEqual(len(rom_entry["versions"]), 1)  # 덮어쓰기라 개수 그대로

        zelda = dbmod.get_or_create_rom_entry(self.db, "nes", "Zelda.zip")
        self.assertEqual(dbmod.get_default_fields(zelda)["name"], "Zelda")

    def test_import_never_touches_media(self):
        from csv_engine import export_db_to_csv, import_csv_to_db

        rom_entry = dbmod.get_or_create_rom_entry(self.db, "snes", "Mario.zip")
        dbmod.add_version(rom_entry, "l1", {"name": "Mario", "desc": "d1"})
        dbmod.set_rom_media(rom_entry, {"covers": "/some/cover.png"})

        csv_path = self.tmpdir / "roundtrip.csv"
        export_db_to_csv(self.db, csv_path)
        import_csv_to_db(csv_path, self.db)

        self.assertEqual(rom_entry["media"], {"covers": "/some/cover.png"})


if __name__ == "__main__":
    unittest.main()

class TestRomFilenameNormalization(unittest.TestCase):
    def test_match_normalization_preserves_sequel_number(self):
        from utils import normalize_rom_match_title
        self.assertEqual(normalize_rom_match_title("Game 2 (K) [ver 1.0].zip"), "game 2")
        self.assertEqual(normalize_rom_match_title("Game 3 (K).zip"), "game 3")
        self.assertNotEqual(normalize_rom_match_title("Game 2 (K).zip"), normalize_rom_match_title("Game 3 (K).zip"))

    def test_match_normalization_removes_requested_decorations(self):
        from utils import normalize_rom_match_title
        self.assertEqual(normalize_rom_match_title("Title_KOR_ver 1.0_rel20200101.zip"), "title")
        self.assertEqual(normalize_rom_match_title("Title (J) (Disc 1 of 3).chd"), "title")
        self.assertEqual(normalize_rom_match_title("Title_1of3.zip"), "title")

    def test_language_letter_in_real_title_is_not_removed(self):
        from utils import normalize_rom_match_title
        self.assertEqual(normalize_rom_match_title("E-SWAT.zip"), "e swat")

    def test_subtitle_fallback_is_ordered(self):
        from utils import rom_match_keys
        keys = rom_match_keys("Game - Long Subtitle - Extra (K).zip")
        self.assertEqual(keys[0], "game long subtitle extra")
        self.assertIn("game long subtitle", keys)
        self.assertEqual(keys[-1], "game")

class TestMasterDbFilenameMatcher(unittest.TestCase):
    def test_same_system_only_and_unique_fallback(self):
        from export_engine import _build_masterdb_match_index, _find_masterdb_rom
        db = {"roms": {}}
        a = dbmod.get_or_create_rom_entry(db, "snes", "Game 2 (J) (ver 1.0).zip")
        dbmod.add_version(a, "m", {"name": "Game 2"})
        b = dbmod.get_or_create_rom_entry(db, "genesis", "Game 2 (J).zip")
        dbmod.add_version(b, "m", {"name": "Game 2 Genesis"})
        idx = _build_masterdb_match_index(db)
        key, entry, kind = _find_masterdb_rom(db, idx, "snes", "Game 2_KOR.zip")
        self.assertEqual(entry["system"], "snes")
        self.assertEqual(entry["rom_filename"], "Game 2 (J) (ver 1.0).zip")
        self.assertEqual(kind, "normalized")

    def test_ambiguous_normalized_match_is_not_guessed(self):
        from export_engine import _build_masterdb_match_index, _find_masterdb_rom
        db = {"roms": {}}
        dbmod.get_or_create_rom_entry(db, "snes", "Game (J).zip")
        dbmod.get_or_create_rom_entry(db, "snes", "Game (K).zip")
        idx = _build_masterdb_match_index(db)
        key, entry, kind = _find_masterdb_rom(db, idx, "snes", "Game_ENG.zip")
        self.assertIsNone(entry)
