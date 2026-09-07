"""
tests/test_api.py
==================
api.py (pywebview Api 브릿지) 통합 테스트.
pywebview 자체는 설치돼 있지 않아도(개발 샌드박스) 테스트 가능하도록,
webview 모듈을 실제로 import하는 부분(pick_folder)만 별도로 예외 처리되어 있어
나머지 메서드는 순수 Python 레벨에서 전부 검증된다.

[중요] Claude Code 세션에서 이어서 작업할 때 반드시 이 테스트부터 통과시킬 것.
"""

import shutil
import base64
import time
import unittest
from pathlib import Path

import config as cfgmod
import db as dbmod
from api import Api


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path("/tmp/test_api_suite_" + self.id().split(".")[-1])
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        self._orig_config_path = cfgmod.CONFIG_PATH
        self._orig_backup_dir = cfgmod.BACKUP_DIR
        cfgmod.CONFIG_PATH = self.tmp / "config.json"
        cfgmod.BACKUP_DIR = self.tmp / "backup"
        self.api = Api()

    def tearDown(self):
        try:
            self.api.close()
        except Exception:
            pass
        cfgmod.CONFIG_PATH = self._orig_config_path
        cfgmod.BACKUP_DIR = self._orig_backup_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_esde_local(self, label="로컬1", korean_title="슈퍼 마리오 월드"):
        masterdb_root = str(self.tmp / "masterdb")
        r = self.api.set_masterdb_path(masterdb_root)
        self.assertTrue(r["ok"])

        local_root = self.tmp / (label + "_ES-DE")
        (local_root / "roms" / "snes").mkdir(parents=True)
        (local_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (local_root / "meta" / "downloaded_media" / "snes" / "covers").mkdir(parents=True)
        (local_root / "roms" / "snes" / "게임.zip").write_text("dummy")
        (local_root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            f'<gameList><game><path>./게임.zip</path><name>{korean_title}</name>'
            f'<desc>한글 설명 테스트</desc><genre>플랫폼</genre></game></gameList>',
            encoding="utf-8",
        )
        (local_root / "meta" / "downloaded_media" / "snes" / "covers" / "게임.png").write_bytes(b"FAKE_PNG")

        r = self.api.add_local(label, "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        self.assertTrue(r["ok"], r.get("error"))
        return r["data"]["id"]

    # ------------------------------------------------------------------
    def test_add_local_translates_gui_frontend_label_to_internal_key(self):
        """[회귀 방지] GUI가 'ES-DE' 같은 표시 라벨을 보내도 내부적으로 'es-de'로 변환되어야 함."""
        local_id = self.make_esde_local()
        locals_ = self.api.list_locals()["data"]
        self.assertEqual(locals_[0]["frontend"], "es-de")

    def test_update_local_paths_changes_paths_and_invalidates_scan_cache(self):
        """[Settings > GameListSet 경로 변경] 새 경로로 갱신되고, 이전 경로 기준으로
        쌓인 스캔 캐시는 더 이상 유효하지 않으므로 비워져야 한다 (다음 스캔이 새
        경로를 기준으로 다시 이뤄지도록)."""
        local_id = self.make_esde_local(korean_title="이전 경로 게임")
        self.api.scan_local(local_id)
        self.assertIn(local_id, self.api._local_scan_cache)

        new_root = self.tmp / "새경로_ES-DE"
        (new_root / "roms" / "snes").mkdir(parents=True)
        (new_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (new_root / "roms" / "snes" / "새게임.zip").write_text("dummy")
        (new_root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            '<gameList><game><path>./새게임.zip</path><name>새 경로 게임</name><desc>d</desc></game></gameList>',
            encoding="utf-8",
        )

        r = self.api.update_local_paths(local_id, str(new_root / "roms"), str(new_root / "meta"))
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["data"]["metadata_path"], str(new_root / "meta"))
        self.assertNotIn(local_id, self.api._local_scan_cache)

        scan = self.api.scan_local(local_id)
        self.assertTrue(scan["ok"], scan.get("error"))
        self.assertEqual(scan["data"]["games"][0]["title"], "새 경로 게임")

    def test_update_local_paths_rejects_unknown_local(self):
        r = self.api.update_local_paths("no-such-id", "", "")
        self.assertFalse(r["ok"])

    def test_scan_import_and_list_roundtrip_with_korean(self):
        local_id = self.make_esde_local(korean_title="한글 타이틀 테스트")
        scan = self.api.scan_local(local_id)
        self.assertTrue(scan["ok"])
        self.assertEqual(scan["data"]["games"][0]["title"], "한글 타이틀 테스트")

        imp = self.api.import_local_to_masterdb(local_id)
        self.assertTrue(imp["ok"])
        self.assertEqual(imp["data"]["imported"], 1)

        games = self.api.list_masterdb_games()["data"]
        self.assertEqual(games[0]["title"], "한글 타이틀 테스트")

    def test_metadata_only_esde_imports_without_physical_rom(self):
        """ES-DE gamelist/media는 ROM이 없어도 MasterDB metadata로 Import되어야 한다."""
        local_id = self.make_esde_local(korean_title="ROM없는 메타데이터")
        rom_file = self.tmp / "로컬1_ES-DE" / "roms" / "snes" / "게임.zip"
        rom_file.unlink()
        r = self.api.import_local_to_masterdb(local_id)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["data"]["imported"], 1)
        games = self.api.list_masterdb_games()["data"]
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["title"], "ROM없는 메타데이터")

    def test_media_roundtrip_as_base64_data_uri(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        detail = self.api.get_game_detail(rom_key)
        self.assertTrue(detail["data"]["media"]["Covers"].startswith("data:image/png;base64,"))
        decoded = base64.b64decode(detail["data"]["media"]["Covers"].split(",")[1])
        self.assertEqual(decoded, b"FAKE_PNG")

    def test_save_media_persists_and_updates_only_that_type(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]

        payload = base64.b64encode(b"NEW_SCREENSHOT").decode()
        r = self.api.save_media(rom_key, "Screenshots", payload, "shot.jpg")
        self.assertTrue(r["ok"], r.get("error"))

        detail = self.api.get_game_detail(rom_key)
        self.assertIn("Screenshots", detail["data"]["media"])
        # 기존 Cover는 그대로 유지되어야 함 (부분 업데이트 검증)
        self.assertIn("Covers", detail["data"]["media"])

    def test_version_lifecycle(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        detail = self.api.get_game_detail(rom_key)
        vid = detail["data"]["versions"][0]["id"]

        clone = self.api.clone_version(rom_key, vid)
        self.assertTrue(clone["ok"])
        new_vid = clone["data"]["newVersionId"]

        self.assertTrue(self.api.set_default_version(rom_key, new_vid)["ok"])
        self.assertTrue(self.api.delete_version(rom_key, vid)["ok"])

        # 마지막 1개는 삭제 불가
        last_vid = self.api.get_game_detail(rom_key)["data"]["versions"][0]["id"]
        r = self.api.delete_version(rom_key, last_vid)
        self.assertFalse(r["ok"])

    def test_korean_field_edit_survives_full_reload(self):
        """[인코딩 검증] 한글로 필드를 수정 -> 새 Api 인스턴스(디스크 재로드)로 확인."""
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        detail = self.api.get_game_detail(rom_key)
        vid = detail["data"]["versions"][0]["id"]

        edited = dict(detail["data"]["versions"][0]["fields"])
        edited["desc"] = "특수문자 테스트: 따옴표'와 줄바꿈, 이모지 포함 등"
        self.assertTrue(self.api.save_version_fields(rom_key, vid, edited)["ok"])

        fresh_api = Api()
        reloaded = fresh_api.get_game_detail(rom_key)
        self.assertEqual(reloaded["data"]["versions"][0]["fields"]["desc"], edited["desc"])
        fresh_api.close()

    def test_settings_roundtrip(self):
        r = self.api.save_settings("en", "light", 30, {
            "koreanOnly": False, "copyMedia": True, "copyVideo": False, "forceOverwrite": True,
        })
        self.assertTrue(r["ok"])
        got = self.api.get_settings()["data"]
        self.assertEqual(got["lang"], "en")
        self.assertEqual(got["theme"], "light")
        self.assertEqual(got["saveInterval"], 30)
        self.assertTrue(got["exportOptions"]["force_overwrite"])

    def test_backup_and_restore(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)

        b = self.api.do_backup()
        self.assertTrue(b["ok"], b.get("error"))
        listing = self.api.list_backups()
        self.assertTrue(listing["ok"])
        self.assertEqual(len(listing["data"]), 1)

        r = self.api.restore_backup(listing["data"][0])
        self.assertTrue(r["ok"], r.get("error"))

    def test_delete_local_removes_from_config(self):
        local_id = self.make_esde_local()
        self.assertTrue(self.api.delete_local(local_id)["ok"])
        self.assertEqual(self.api.list_locals()["data"], [])

    def test_max_locals_enforced(self):
        for i in range(4):
            self.make_esde_local(label=f"로컬{i}")
        # 5번째는 실패해야 함
        masterdb_root = str(self.tmp / "masterdb")
        local_root = self.tmp / "로컬5_ES-DE"
        (local_root / "roms" / "snes").mkdir(parents=True)
        (local_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        r = self.api.add_local("로컬5", "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        self.assertFalse(r["ok"])

    def test_daijisho_not_implemented_surfaces_gracefully(self):
        """
        [설계상 미구현] 다이지쇼는 detect_structure/list_systems는 가정 기반으로 동작하지만
        read_metadata_fields/read_media는 아직 NotImplementedError를 낸다.
        api.scan_local()은 이를 전체 실패로 처리하지 않고 notImplemented 플래그로
        우아하게 알려야 한다 (한 Local이 막혀도 앱 전체가 죽으면 안 되므로).
        """
        masterdb_root = str(self.tmp / "masterdb")
        self.api.set_masterdb_path(masterdb_root)
        local_root = self.tmp / "다이지쇼로컬"
        (local_root / "snes").mkdir(parents=True)
        (local_root / "snes" / "게임.zip").write_text("dummy")
        (local_root / "snes" / "platform.json").write_text('{"games": []}', encoding="utf-8")

        r = self.api.add_local("다이지쇼로컬", "Daijishō", str(local_root), str(local_root))
        self.assertTrue(r["ok"])
        local_id = r["data"]["id"]

        scan = self.api.scan_local(local_id)
        self.assertTrue(scan["ok"], scan.get("error"))
        self.assertTrue(scan["data"]["notImplemented"])
        # ROM 자체는 스캔되지만(구조 감지는 가정 기반으로 동작), 제목 등은 비어있어야 함
        self.assertEqual(len(scan["data"]["games"]), 1)
        self.assertEqual(scan["data"]["games"][0]["title"], "")


    # ------------------------------------------------------------------
    # [신규] 2단계에서 추가한 기능들 (region/rating, 중복 ROM, Marquees/Videos, 썸네일)
    # ------------------------------------------------------------------
    def test_region_and_rating_included_in_masterdb_list(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        games = self.api.list_masterdb_games()["data"]
        g = games[0]
        self.assertIn("region", g)
        self.assertIn("rating", g)

    def test_region_and_rating_included_in_scan_local(self):
        local_id = self.make_esde_local()
        scan = self.api.scan_local(local_id)
        g = scan["data"]["games"][0]
        self.assertIn("region", g)
        self.assertIn("rating", g)

    def test_duplicate_rom_flagged_in_masterdb_list(self):
        """동일 정규화 타이틀을 가진 ROM 2개를 등록하면 둘 다 duplicate=True 여야 한다."""
        masterdb_root = str(self.tmp / "masterdb")
        self.api.set_masterdb_path(masterdb_root)

        local_root = self.tmp / "중복테스트_ES-DE"
        (local_root / "roms" / "snes").mkdir(parents=True)
        (local_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (local_root / "roms" / "snes" / "game_a.zip").write_text("dummy")
        (local_root / "roms" / "snes" / "game_b.zip").write_text("dummy")
        (local_root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            '<gameList>'
            '<game><path>./game_a.zip</path><name>동일 게임 타이틀</name><desc>설명 A</desc></game>'
            '<game><path>./game_b.zip</path><name>동일 게임 타이틀</name><desc>설명 B</desc></game>'
            '</gameList>', encoding="utf-8",
        )
        r = self.api.add_local("중복테스트", "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        local_id = r["data"]["id"]
        self.api.import_local_to_masterdb(local_id)

        games = self.api.list_masterdb_games()["data"]
        self.assertEqual(len(games), 2)
        self.assertTrue(all(g["duplicate"] for g in games))

    def test_video_media_not_base64_encoded(self):
        """영상은 무거운 base64 대신 마커 값만 반환되어야 한다 (용량 문제 방지)."""
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]

        payload = base64.b64encode(b"FAKE_VIDEO_BYTES_NOT_REALLY_MP4").decode()
        r = self.api.save_media(rom_key, "Videos", payload, "clip.mp4")
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["data"]["dataUri"], "video://exists")

        detail = self.api.get_game_detail(rom_key)
        self.assertEqual(detail["data"]["media"]["Videos"], "video://exists")

    def test_marquees_media_type_supported(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]

        payload = base64.b64encode(b"FAKE_MARQUEE_PNG").decode()
        r = self.api.save_media(rom_key, "Marquees", payload, "marquee.png")
        self.assertTrue(r["ok"], r.get("error"))
        detail = self.api.get_game_detail(rom_key)
        self.assertIn("Marquees", detail["data"]["media"])

    def test_get_cover_thumbnail_lazy_load(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]

        r = self.api.get_cover_thumbnail(rom_key)
        self.assertTrue(r["ok"])
        self.assertTrue(r["data"].startswith("data:image/"))

    def test_get_cover_thumbnail_returns_none_when_no_cover(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        rom_entry = self.api.db["roms"][rom_key]
        rom_entry["media"] = {}  # 커버 제거
        r = self.api.get_cover_thumbnail(rom_key)
        self.assertTrue(r["ok"])
        self.assertIsNone(r["data"])

    def test_list_masterdb_games_returns_empty_for_nonexistent_cover(self):
        """list_masterdb_games는 hasCover만 주지 실제 이미지 데이터를 포함하면 안 된다 (성능)."""
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        games = self.api.list_masterdb_games()["data"]
        self.assertNotIn("media", games[0])  # 목록 응답엔 media 원본이 없어야 함
        self.assertIn("hasCover", games[0])


    def test_get_version_matches_version_py(self):
        from version import __version__
        r = self.api.get_version()
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"], __version__)


    # ------------------------------------------------------------------
    # [신규] scan_local 전면 재작성 검증 (Missing ROM 포함 전체 열거, 5단계 상태 분류,
    # Local 내 중복 판별, Local 읽기전용 상세조회)
    # ------------------------------------------------------------------
    def _make_full_media_local(self, label="풀미디어로컬"):
        """5종 media(covers/screenshots/miximages/wheel/marquees)가 전부 있는 로컬 준비."""
        masterdb_root = str(self.tmp / "masterdb")
        self.api.set_masterdb_path(masterdb_root)
        local_root = self.tmp / (label + "_ES-DE")
        (local_root / "roms" / "snes").mkdir(parents=True)
        gamelists = local_root / "meta" / "gamelists" / "snes"
        gamelists.mkdir(parents=True)
        media_root = local_root / "meta" / "downloaded_media" / "snes"
        for sub in ["covers", "screenshots", "miximages", "wheel", "marquees"]:
            (media_root / sub).mkdir(parents=True)

        (local_root / "roms" / "snes" / "full.zip").write_text("dummy")
        gamelists_xml = (
            '<gameList>'
            '<game><path>./full.zip</path><name>Full Media Game</name><desc>d1</desc></game>'
            '<game><path>./missing_rom.zip</path><name>No ROM Game</name><desc>d2</desc></game>'
            '</gameList>'
        )
        (gamelists / "gamelist.xml").write_text(gamelists_xml, encoding="utf-8")
        for sub in ["covers", "screenshots", "miximages", "wheel", "marquees"]:
            (media_root / sub / "full.png").write_bytes(b"X")

        r = self.api.add_local(label, "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        self.assertTrue(r["ok"], r.get("error"))
        return r["data"]["id"]

    def test_scan_local_includes_missing_rom_entries(self):
        """[BUG FIX] gamelist.xml엔 있지만 ROM 파일이 없는 항목도 목록에 나와야 한다."""
        local_id = self._make_full_media_local()
        scan = self.api.scan_local(local_id)
        self.assertTrue(scan["ok"], scan.get("error"))
        games = scan["data"]["games"]
        self.assertEqual(len(games), 2)  # full.zip + missing_rom.zip 둘 다 나와야 함

        missing_rom_game = next(g for g in games if g["file"] == "missing_rom.zip")
        self.assertFalse(missing_rom_game["romMatched"])
        self.assertEqual(missing_rom_game["status"], "누락")

    def test_scan_local_normal_status_when_all_media_present(self):
        local_id = self._make_full_media_local()
        scan = self.api.scan_local(local_id)
        full_game = next(g for g in scan["data"]["games"] if g["file"] == "full.zip")
        self.assertEqual(full_game["status"], "완료")
        self.assertFalse(full_game["missingMedia"])
        self.assertTrue(full_game["hasCover"])

    def test_scan_local_partial_status_when_some_media_missing(self):
        """make_esde_local 픽스처는 covers만 있고 나머지 4종이 없음 -> 부분(Partial)."""
        local_id = self.make_esde_local()
        scan = self.api.scan_local(local_id)
        g = scan["data"]["games"][0]
        self.assertTrue(g["romMatched"])
        self.assertEqual(g["status"], "부분")
        self.assertFalse(g["missingMedia"])  # media가 '일부'는 있으므로 missingMedia=False

    def test_scan_local_missing_media_flag_when_zero_media(self):
        masterdb_root = str(self.tmp / "masterdb")
        self.api.set_masterdb_path(masterdb_root)
        local_root = self.tmp / "미디어없음_ES-DE"
        (local_root / "roms" / "snes").mkdir(parents=True)
        (local_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (local_root / "roms" / "snes" / "nomedia.zip").write_text("dummy")
        (local_root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            '<gameList><game><path>./nomedia.zip</path><name>No Media</name><desc>d</desc></game></gameList>',
            encoding="utf-8",
        )
        r = self.api.add_local("미디어없음", "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        local_id = r["data"]["id"]
        scan = self.api.scan_local(local_id)
        g = scan["data"]["games"][0]
        self.assertTrue(g["romMatched"])
        self.assertEqual(g["status"], "부분")
        self.assertTrue(g["missingMedia"])

    def test_scan_local_duplicate_detection_within_local(self):
        """동일 정규화 타이틀 + media 전부 있는 게임 2개 -> 둘 다 duplicate=True."""
        masterdb_root = str(self.tmp / "masterdb")
        self.api.set_masterdb_path(masterdb_root)
        local_root = self.tmp / "로컬중복_ES-DE"
        (local_root / "roms" / "snes").mkdir(parents=True)
        (local_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        media_root = local_root / "meta" / "downloaded_media" / "snes"
        for sub in ["covers", "screenshots", "miximages", "wheel", "marquees"]:
            (media_root / sub).mkdir(parents=True)
        (local_root / "roms" / "snes" / "dup_a.zip").write_text("dummy")
        (local_root / "roms" / "snes" / "dup_b.zip").write_text("dummy")
        (local_root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            '<gameList>'
            '<game><path>./dup_a.zip</path><name>같은 게임</name><desc>d</desc></game>'
            '<game><path>./dup_b.zip</path><name>같은 게임</name><desc>d</desc></game>'
            '</gameList>', encoding="utf-8",
        )
        for fname in ["dup_a", "dup_b"]:
            for sub in ["covers", "screenshots", "miximages", "wheel", "marquees"]:
                (media_root / sub / f"{fname}.png").write_bytes(b"X")

        r = self.api.add_local("로컬중복", "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        local_id = r["data"]["id"]
        scan = self.api.scan_local(local_id)
        games = scan["data"]["games"]
        self.assertEqual(len(games), 2)
        self.assertTrue(all(g["duplicate"] for g in games))

    def test_get_local_game_detail_works_before_import(self):
        """[BUG FIX] Import 안 한 상태에서도 Local 게임 상세를 읽을 수 있어야 한다."""
        local_id = self.make_esde_local(korean_title="가져오기전게임")
        scan = self.api.scan_local(local_id)
        rom_key = scan["data"]["games"][0]["romKey"]

        r = self.api.get_local_game_detail(local_id, rom_key)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertFalse(r["data"]["readOnly"])
        self.assertEqual(r["data"]["versions"][0]["fields"]["name"], "가져오기전게임")
        self.assertIn("Covers", r["data"]["media"])

    def test_get_local_game_detail_invalid_local(self):
        r = self.api.get_local_game_detail("nonexistent-local-id", "snes|x.zip")
        self.assertFalse(r["ok"])

    def test_get_local_cover_thumbnail_before_import(self):
        local_id = self.make_esde_local()
        scan = self.api.scan_local(local_id)
        rom_key = scan["data"]["games"][0]["romKey"]
        r = self.api.get_local_cover_thumbnail(local_id, rom_key)
        self.assertTrue(r["ok"])
        self.assertTrue(r["data"].startswith("data:image/"))

    def test_daijisho_fallback_path_still_works(self):
        """list_gamelist_entries가 없는 Frontend(다이지쇼)는 기존 방식으로 안전하게 폴백해야 한다."""
        masterdb_root = str(self.tmp / "masterdb")
        self.api.set_masterdb_path(masterdb_root)
        local_root = self.tmp / "다이지쇼폴백"
        (local_root / "snes").mkdir(parents=True)
        (local_root / "snes" / "게임.zip").write_text("dummy")
        r = self.api.add_local("다이지쇼폴백", "Daijishō", str(local_root), str(local_root))
        local_id = r["data"]["id"]
        scan = self.api.scan_local(local_id)
        self.assertTrue(scan["ok"], scan.get("error"))
        self.assertTrue(scan["data"]["notImplemented"])


    # ------------------------------------------------------------------
    # [신규] Job(백그라운드 진행률) 시스템 + MasterDB ROM 저장 + 3모드 Export + 디스크체크
    # ------------------------------------------------------------------
    def test_job_system_reports_progress_and_completes(self):
        local_id = self.make_esde_local()
        r = self.api.start_reset_metadata(local_id)
        self.assertTrue(r["ok"], r.get("error"))
        job_id = r["data"]["jobId"]

        import time
        for _ in range(50):
            p = self.api.get_job_progress(job_id)
            self.assertTrue(p["ok"])
            if p["data"]["done"]:
                break
            time.sleep(0.02)
        self.assertTrue(p["data"]["done"])
        self.assertIsNone(p["data"]["error"])

    def test_job_progress_unknown_id_returns_error(self):
        r = self.api.get_job_progress("nonexistent-job-id")
        self.assertFalse(r["ok"])

    def test_start_scan_local_job_returns_same_shape_as_sync(self):
        local_id = self.make_esde_local()
        sync = self.api.scan_local(local_id)
        r = self.api.start_scan_local(local_id)
        job_id = r["data"]["jobId"]
        import time
        for _ in range(50):
            p = self.api.get_job_progress(job_id)
            if p["data"]["done"]:
                break
            time.sleep(0.02)
        self.assertIsNone(p["data"]["error"])
        self.assertEqual(len(p["data"]["result"]["games"]), len(sync["data"]["games"]))

    def test_metadata_edit_during_scan_is_not_reverted_by_stale_scan_result(self):
        """[리뷰 반영] Scan(전체 패스)이 gamelist.xml을 읽는 시점과 사용자가
        save_local_game_fields()로 metadata를 저장하는 시점이 겹치면, Scan이 그
        저장 "이전" 스냅샷으로 계산한 games를 나중에 runtime_cache["last_games"]에
        통째로 덮어써서 방금 저장한 값이 캐시에서 사라진 것처럼 보일 수 있다(파일
        자체는 항상 정확히 저장됨). importers.es_de.read_media를 막아 Scan을
        "gamelist는 이미 읽었지만 아직 안 끝난" 상태로 붙잡아두고, 그 사이에 저장을
        걸어서 최종 캐시에 저장값이 살아남는지 확인한다."""
        import threading
        from unittest.mock import patch
        import importers.es_de as es_de_mod

        local_id = self.make_esde_local(korean_title="원래 제목")
        rom_key = "snes|게임.zip"
        # [주의] 미리 한 번 스캔해두면 두 번째 호출이 scan_token 캐시 hit로 즉시
        # 반환돼(read_media를 아예 안 부름) 이 테스트가 노리는 경합 자체가 생기지
        # 않는다 - 그래서 warm-up 없이 첫 스캔 자체를 "막힌" 상태로 돌린다.

        original_read_media = es_de_mod.read_media
        read_media_started = threading.Event()
        release_read_media = threading.Event()
        called = {"n": 0}

        def blocking_read_media(*args, **kwargs):
            called["n"] += 1
            if called["n"] == 1:
                read_media_started.set()
                release_read_media.wait(timeout=5)
            return original_read_media(*args, **kwargs)

        # start_scan_local()의 2-phase job이 하는 것처럼, scan이 진행되는 동안 이
        # local을 busy로 표시해야 save_local_game_fields()가 pending_edits로 쌓는다.
        with self.api._busy_lock:
            self.api._busy_targets.add(local_id)
        result_holder = {}
        try:
            with patch.object(es_de_mod, "read_media", side_effect=blocking_read_media):
                def run_scan():
                    result_holder["r"] = self.api.scan_local(local_id, read_media_types=None)
                t = threading.Thread(target=run_scan)
                t.start()
                self.assertTrue(read_media_started.wait(timeout=5), "scan이 read_media까지 도달하지 못함")

                save_r = self.api.save_local_game_fields(local_id, rom_key, {"name": "수정된 제목", "desc": "새 설명"})
                self.assertTrue(save_r["ok"], save_r.get("error"))

                release_read_media.set()
                t.join(timeout=5)
        finally:
            with self.api._busy_lock:
                self.api._busy_targets.discard(local_id)

        self.assertTrue(result_holder["r"]["ok"], result_holder["r"].get("error"))
        cached_games = self.api._local_scan_cache[local_id]["last_games"]
        game = next(g for g in cached_games if g["romKey"] == rom_key)
        self.assertEqual(game["title"], "수정된 제목",
                          "scan 도중 저장한 metadata 수정이 캐시에서 사라짐 - scan의 stale 결과가 덮어씀")

        gamelist_text = (Path(self.api._find_local(local_id)["metadata_path"]) / "gamelists" / "snes" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertIn("수정된 제목", gamelist_text, "파일 자체에도 저장돼 있어야 한다")

    def test_phased_media_job_labels_are_prefixed_and_progress_resets_per_phase(self):
        """[리뷰 반영] 진행률 바가 "(1/2) 0->100%" -> "(2/2) 0->100%"처럼 phase별로
        독립적으로 표시된다는 주장을, 단순히 progress bar가 "보인다/숨는다"만이
        아니라 실제 label 접두사와 current/total 값 자체로 검증한다. 각 phase
        job의 최종 진행률이 그 phase 자신의 total로 끝나는지(=전체를 아우르는
        하나의 누적 카운터가 아니라 phase마다 독립적으로 리셋되는지)를 함께
        확인한다. on_phase_job_created(리뷰에서 지적된 race 수정 항목)를 이용해
        phase별 job_id를 결정적으로 잡아낸다."""
        phase_job_ids = []

        def phase1(cb):
            cb(1, 2, "a")
            cb(2, 2, "b")
            return "p1"

        def phase2(cb):
            cb(1, 3, "x")
            cb(3, 3, "z")
            return "p2"

        self.api._start_phased_media_job(
            ("localX",), [("메타데이터", phase1), ("미디어", phase2)],
            mutates_db=False, attach_followup_job_id=True,
            on_phase_job_created=lambda jid: phase_job_ids.append(jid),
        )
        for _ in range(100):
            if len(phase_job_ids) >= 2 and self.api.get_job_progress(phase_job_ids[-1])["data"]["done"]:
                break
            time.sleep(0.01)

        self.assertEqual(len(phase_job_ids), 2, f"phase job이 2개 생성돼야 하는데: {phase_job_ids}")
        job1_id, job2_id = phase_job_ids
        p1 = self.api.get_job_progress(job1_id)["data"]
        p2 = self.api.get_job_progress(job2_id)["data"]

        self.assertTrue(p1["label"].startswith("(1/2)"), f"1단계 label에 '(1/2)' 접두사가 없음: {p1['label']}")
        self.assertEqual((p1["current"], p1["total"]), (2, 2), "1단계는 자기 total(2)로 100% 완료돼야 함")

        self.assertTrue(p2["label"].startswith("(2/2)"), f"2단계 label에 '(2/2)' 접두사가 없음: {p2['label']}")
        self.assertEqual((p2["current"], p2["total"]), (3, 3),
                          "2단계는 1단계 누적과 무관하게 자기 total(3)로 새로 시작/완료돼야 함")

    def test_start_scan_local_runs_two_phases_cover_first_then_full(self):
        """[체감 속도, Scan 2단계] start_scan_local()이 (1) covers만 (2) 전체 media
        순서로 2번 self.scan_local()을 부르는지, 1단계 결과가 followUpJobId/
        partial/mediaPending을 담고 있는지, 그리고 2단계가 끝나면 media가 다
        확인돼 status가 "완료"로 정확히 확정되는지 검증한다. 1단계 시점엔 covers만
        봐서 다른 media가 안 보이므로 status가 "부분"으로만 뜨는 게 정상(불완전한
        판정) - 이게 2단계에서 정정되는지가 핵심이다."""
        from unittest.mock import patch
        original_scan_local = self.api.scan_local
        calls = []

        def spy_scan_local(*args, **kwargs):
            calls.append(kwargs.get("read_media_types"))
            return original_scan_local(*args, **kwargs)

        local_id = self.make_esde_local()
        media_root = self.tmp / "로컬1_ES-DE" / "meta" / "downloaded_media" / "snes"
        for folder in ("screenshots", "miximages", "wheel", "marquees"):
            (media_root / folder).mkdir(parents=True)
            (media_root / folder / "게임.png").write_bytes(b"X")

        with patch.object(self.api, "scan_local", side_effect=spy_scan_local):
            r = self.api.start_scan_local(local_id)
            self.assertTrue(r["ok"], r.get("error"))
            job1 = r["data"]["jobId"]
            for _ in range(100):
                if self.api.get_job_progress(job1)["data"]["done"]:
                    break
                time.sleep(0.02)
            p1 = self.api.get_job_progress(job1)
            self.assertIsNone(p1["data"]["error"], p1["data"].get("error"))
            phase1_result = p1["data"]["result"]
            self.assertTrue(phase1_result.get("partial"))
            follow_up_job_id = phase1_result.get("followUpJobId")
            self.assertTrue(follow_up_job_id)
            phase1_game = phase1_result["games"][0]
            self.assertTrue(phase1_game["mediaPending"])
            self.assertTrue(phase1_game["hasCover"])
            self.assertEqual(phase1_game["status"], "부분", "1단계는 커버만 봤으니 완료 판정을 내리면 안 된다")

            for _ in range(100):
                if self.api.get_job_progress(follow_up_job_id)["data"]["done"]:
                    break
                time.sleep(0.02)

        self.assertEqual(calls, [["covers"], None], f"1단계는 covers만, 2단계는 전체(None)여야 하는데: {calls}")
        p2 = self.api.get_job_progress(follow_up_job_id)
        self.assertIsNone(p2["data"]["error"], p2["data"].get("error"))
        phase2_game = p2["data"]["result"]["games"][0]
        self.assertFalse(phase2_game.get("partial", False))
        self.assertFalse(phase2_game["mediaPending"])
        self.assertEqual(phase2_game["status"], "완료", "2단계는 전체 media를 봤으니 완료로 정정돼야 한다")

    def test_scan_phase1_does_not_traverse_video_folder_on_filesystem(self):
        """[P0-1] "read_media_types=["covers"]" 인자를 넘기는 것만으로는 부족하다 -
        importers/scan.py::scan_local()이 내부적으로 부르는 build_media_index()가
        system 폴더 전체를 rglob("*")하면(video 포함), 인자와 무관하게 실제
        filesystem I/O는 이미 전체를 다 훑은 뒤였다. 이 테스트는 videos 폴더에
        pathlib.Path.iterdir를 스파이해서, Phase 1(covers만 요청) 동안 videos
        폴더가 실제로 열거되지 않는지 직접 확인한다."""
        from unittest.mock import patch
        import os

        local_id = self.make_esde_local()
        media_root = self.tmp / "로컬1_ES-DE" / "meta" / "downloaded_media" / "snes"
        (media_root / "videos").mkdir(parents=True)
        (media_root / "videos" / "게임.mp4").write_bytes(b"X")

        # [주의] pathlib.Path.rglob()는 내부적으로 Path.iterdir()가 아니라
        # os.scandir()를 직접 사용한다 - Path.iterdir만 스파이하면 rglob 기반의
        # 구현(수정 전 build_media_index)이 videos까지 훑어도 감지되지 않는다.
        listed_dirs = []
        original_scandir = os.scandir

        def spy_scandir(path="."):
            listed_dirs.append(str(path))
            return original_scandir(path)

        with patch("os.scandir", spy_scandir):
            r = self.api.scan_local(local_id, read_media_types=["covers"])
            self.assertTrue(r["ok"], r.get("error"))

        self.assertFalse(
            any(p.endswith("videos") for p in listed_dirs),
            f"Phase 1(covers만 요청)인데 videos 폴더가 실제로 열거됨: {listed_dirs}",
        )
        game = r["data"]["games"][0]
        self.assertTrue(game["hasCover"])
        self.assertTrue(game["mediaPending"])

        # Phase 2(전체)는 반대로 videos 폴더를 실제로 열거해야 한다.
        listed_dirs.clear()
        with patch("os.scandir", spy_scandir):
            r2 = self.api.scan_local(local_id, read_media_types=None)
            self.assertTrue(r2["ok"], r2.get("error"))
        self.assertTrue(
            any(p.endswith("videos") for p in listed_dirs),
            "Phase 2(전체)인데 videos 폴더를 열거하지 않음",
        )

    def test_start_scan_local_dedupes_concurrent_calls_for_same_local(self):
        """[P0-4] 같은 Local에 대해 start_scan_local()을 연달아 여러 번 부르면(예:
        Refresh 연타), 이미 진행 중인 Scan chain이 있는 동안엔 새 job을 또
        만들지 않고 기존 job_id를 그대로 돌려줘야 한다 - 그렇지 않으면 같은
        Local에 대해 여러 개의 job chain이 큐에 쌓인다."""
        local_id = self.make_esde_local()

        r1 = self.api.start_scan_local(local_id)
        self.assertTrue(r1["ok"], r1.get("error"))
        job1 = r1["data"]["jobId"]

        # 아직 phase 1이 끝나기 전(또는 끝난 직후 phase 2가 진행 중)에 다시 부르면
        # 같은 job_id를 돌려줘야 한다.
        r2 = self.api.start_scan_local(local_id)
        self.assertTrue(r2["ok"], r2.get("error"))
        self.assertEqual(r2["data"]["jobId"], job1,
                          "같은 Local에 대해 Scan이 진행 중인데 새 job이 또 만들어짐")

        # 체인이 완전히 끝날 때까지 기다린다(followUpJobId까지 따라간다).
        jid = job1
        for _ in range(200):
            p = self.api.get_job_progress(jid)["data"]
            if p["done"]:
                follow = (p.get("result") or {}).get("followUpJobId") if isinstance(p.get("result"), dict) else None
                if follow:
                    jid = follow
                    continue
                break
            time.sleep(0.02)

        # 체인이 다 끝난 뒤엔 다시 불렀을 때 새 job이 생성돼야 한다(재사용 X).
        r3 = self.api.start_scan_local(local_id)
        self.assertTrue(r3["ok"], r3.get("error"))
        self.assertNotEqual(r3["data"]["jobId"], job1,
                             "이전 Scan chain이 완전히 끝났는데도 예전 job_id를 계속 재사용함")

    def test_scan_full_lifecycle_refresh_dedup_then_cancel_actually_stops_current_phase(self):
        """[리뷰 반영] 다음 시퀀스 전체를 하나로 검증한다 - 각 조각은 이미
        개별적으로 테스트돼 있지만, 이 전체 흐름이 한 번에 맞물려 동작하는지가
        중요하다:

        Scan 시작 -> Phase1 완료 -> Phase2 실행 중 -> Refresh 재호출(dedup,
        새 job 생성 안 됨, 그리고 그 반환값이 "현재 실행 중인 phase"인 Phase2의
        job_id여야 함 - root/Phase1 job_id가 아니다) -> 그 job_id로 Cancel ->
        Phase2가 실제로 취소됨 -> busy 해제 -> 다시 Scan 가능."""
        import threading
        local_id = self.make_esde_local()
        original_scan_local = self.api.scan_local
        phase2_started = threading.Event()
        release_phase2 = threading.Event()

        def gated_scan_local(*args, **kwargs):
            if kwargs.get("read_media_types") is None:  # Phase 2(전체)
                phase2_started.set()
                # 실제 Phase 2도 progress_cb를 반복 호출하며 진행하므로, cancel_requested를
                # 주기적으로 체크할 수 있게 progress_cb를 계속 불러준다 - 그래야
                # cancel_job()이 표시한 취소 요청이 실제로 반영된다.
                cb = kwargs.get("progress_cb")
                for _ in range(200):
                    if release_phase2.is_set():
                        break
                    if cb:
                        cb(1, 1, "대기 중")  # progress_cb가 cancel_requested면 여기서 _JobCancelled를 던짐
                    time.sleep(0.02)
            return original_scan_local(*args, **kwargs)

        from unittest.mock import patch
        with patch.object(self.api, "scan_local", side_effect=gated_scan_local):
            r1 = self.api.start_scan_local(local_id)
            self.assertTrue(r1["ok"], r1.get("error"))
            phase1_job_id = r1["data"]["jobId"]

            for _ in range(200):
                if self.api.get_job_progress(phase1_job_id)["data"]["done"]:
                    break
                time.sleep(0.02)
            self.assertTrue(phase2_started.wait(timeout=5), "Phase 2가 시작되지 않음")

            # Refresh 재호출 - dedup되어 새 job이 생기면 안 되고, 반환값은 이미 done인
            # Phase1이 아니라 지금 실제로 도는 Phase2의 job_id여야 한다.
            r2 = self.api.start_scan_local(local_id)
            self.assertTrue(r2["ok"], r2.get("error"))
            current_job_id = r2["data"]["jobId"]
            self.assertNotEqual(current_job_id, phase1_job_id,
                                 "Refresh가 반환한 job_id가 이미 끝난 Phase1 job이다 - 현재 진행 중인 Phase2가 아님")
            self.assertFalse(self.api.get_job_progress(current_job_id)["data"]["done"],
                              "Refresh가 반환한 job_id가 이미 done - 현재 진행 중인 phase를 가리키지 않음")

            # 이 job_id로 취소하면 실제로 Phase2가 취소돼야 한다.
            cancel_r = self.api.cancel_job(current_job_id)
            self.assertTrue(cancel_r["ok"], cancel_r.get("error"))
            for _ in range(200):
                p = self.api.get_job_progress(current_job_id)["data"]
                if p["done"]:
                    break
                time.sleep(0.02)
            self.assertTrue(p["done"])
            self.assertTrue(p.get("cancelled") or p.get("error"),
                             f"Phase2 cancel 요청이 실제로 반영되지 않음: {p}")
            release_phase2.set()

        # busy가 풀려서 삭제/이름변경/재스캔이 다시 가능해야 한다.
        for _ in range(200):
            with self.api._busy_lock:
                if local_id not in self.api._busy_targets:
                    break
            time.sleep(0.02)
        self.assertIsNone(self.api._target_busy_error(local_id), "취소 이후에도 busy가 안 풀림")

        r4 = self.api.start_scan_local(local_id)
        self.assertTrue(r4["ok"], r4.get("error"))
        self.assertNotEqual(r4["data"]["jobId"], current_job_id, "취소된 이전 Scan job_id를 재사용함")

    def test_import_engine_selected_media_types_skips_video_folder_traversal(self):
        """[P1-2] import_local_to_masterdb()가 예전엔 importer.read_media()를
        selected_media_types 없이(=항상 전체) 호출하고 반환된 dict만 필터링했다 -
        "video copy는 뒤로 미룬다"는 목표는 달성해도 video 탐색 비용까지 뒤로
        미루지는 못했다(P0-1과 동일한 패턴의 문제). 이제 selected_media_types를
        read_media()에 그대로 넘겨서 videos 폴더 자체를 열거하지 않는다.

        [주의] api.py의 start_export_local_to_masterdb()는 P1-1에서 phase 시작
        전 한 번 전체 scan_result를 미리 만들어 phase끼리 공유하는데, 그 사전
        스캔 자체는(로컬 stats를 정확히 유지하기 위해 의도적으로) 여전히 전체
        media를 훑는다 - 그건 알려진 성능 한계로 남겨뒀다(요청사항: 기능상 문제와
        성능상 한계를 구분). 그래서 이 테스트는 그 API 레이어를 거치지 않고
        import_engine.import_local_to_masterdb()를 직접 호출해서, 정작 이번에
        고친 대상인 "phase당 반복되는 read_media() 호출"이 실제로 video를
        건너뛰는지만 결정적으로 검증한다."""
        from unittest.mock import patch
        import pathlib
        from importers.scan import scan_local as raw_scan_local
        from import_engine import import_local_to_masterdb as raw_import

        local_id = self.make_esde_local()
        media_root = self.tmp / "로컬1_ES-DE" / "meta" / "downloaded_media" / "snes"
        (media_root / "videos").mkdir(parents=True)
        (media_root / "videos" / "게임.mp4").write_bytes(b"X")

        local = self.api._find_local(local_id)
        # covers만 필요한 phase 1이 쓸 scan_result - 여기도 media_types를 좁혀서
        # 미리 만들어둔다(실제 read_media 호출과는 별개의 관심사이므로 부담 없음).
        scan_result = raw_scan_local(local, media_types=["covers"])

        # [주의] collect_es_style_media()는 mdir.iterdir()로 폴더를 연다 - rglob과
        # 달리 이건 os.scandir을 통해 가지 않고 pathlib.Path.iterdir 자체가
        # 호출되므로, 여기서는 Path.iterdir를 직접 스파이해야 정확히 잡힌다.
        listed_dirs = []
        original_iterdir = pathlib.Path.iterdir

        def spy_iterdir(self_path):
            listed_dirs.append(str(self_path))
            return original_iterdir(self_path)

        with patch.object(pathlib.Path, "iterdir", spy_iterdir):
            result = raw_import(local, self.api.cfg["masterdb"]["root"], self.api.db,
                                 scan_result=scan_result, sqlite_repo=self.api._sqlite,
                                 selected_media_types=["covers"])
        self.assertEqual(result.get("errors"), [])

        self.assertFalse(
            any(p.endswith("videos") for p in listed_dirs),
            f"selected_media_types=['covers']인데 read_media()가 videos 폴더를 실제로 열거함: {listed_dirs}",
        )

    def _make_local_for_rom_export(self, label="롬수출로컬"):
        masterdb_root = str(self.tmp / "masterdb")
        self.api.set_masterdb_path(masterdb_root)
        local_root = self.tmp / (label + "_ES-DE")
        (local_root / "roms" / "snes").mkdir(parents=True)
        (local_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (local_root / "roms" / "snes" / "game.zip").write_bytes(b"X" * 1000)
        (local_root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            '<gameList><game><path>./game.zip</path><name>Game</name><desc>d</desc></game></gameList>',
            encoding="utf-8",
        )
        r = self.api.add_local(label, "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        return r["data"]["id"]

    def test_export_roms_mode_copies_rom_file_to_masterdb(self):
        local_id = self._make_local_for_rom_export()
        r = self.api.start_export_local_to_masterdb(local_id, "roms")
        self.assertTrue(r["ok"], r.get("error"))
        job_id = r["data"]["jobId"]
        import time
        for _ in range(50):
            p = self.api.get_job_progress(job_id)
            if p["data"]["done"]:
                break
            time.sleep(0.02)
        self.assertIsNone(p["data"]["error"], p["data"].get("error"))
        self.assertEqual(p["data"]["result"]["romsResult"]["copied"], 1)

        stored = dbmod.rom_storage_path(self.api.cfg["masterdb"]["root"], "snes", "game.zip")
        self.assertTrue(stored.exists())
        self.assertEqual(stored.read_bytes(), b"X" * 1000)

    def test_start_export_local_to_masterdb_runs_in_three_phases(self):
        """[리뷰 반영 + 3단계 확장] "Import from ArchiveDB" 대화상자가 부르는
        start_export_local_to_masterdb()는 start_export_to_local()과 동일하게
        (1) covers (2) videos 제외 나머지 (3) videos 3단계로 나뉘어야 한다 - 처음엔
        아예 이 구조를 안 쓰다가(리뷰 반영으로 2단계까지 붙였고), 이번엔 Export와
        같은 3단계로 확장했다. 실제로 3번 나뉘어 호출되는지 spy로 확인한다."""
        from unittest.mock import patch
        import import_engine
        original_import = import_engine.import_local_to_masterdb
        calls = []

        def spy_import(*args, **kwargs):
            calls.append(kwargs.get("selected_media_types"))
            return original_import(*args, **kwargs)

        local_id = self.make_esde_local()
        (self.tmp / "로컬1_ES-DE" / "meta" / "downloaded_media" / "snes" / "videos").mkdir(parents=True)
        (self.tmp / "로컬1_ES-DE" / "meta" / "downloaded_media" / "snes" / "videos" / "게임.mp4").write_bytes(b"VIDEO")

        with patch("api.import_local_to_masterdb", side_effect=spy_import):
            r = self.api.start_export_local_to_masterdb(local_id, "metadata")
            self.assertTrue(r["ok"], r.get("error"))
            job_id = r["data"]["jobId"]
            for _ in range(100):
                if self.api.get_job_progress(job_id)["data"]["done"]:
                    break
                time.sleep(0.02)
            self.assertIsNone(self.api.get_job_progress(job_id)["data"]["error"])
            for _ in range(200):
                with self.api._busy_lock:
                    if local_id not in self.api._busy_targets and "masterdb" not in self.api._busy_targets:
                        break
                time.sleep(0.02)

        self.assertEqual(len(calls), 3, f"3단계로 나뉘어 3번 호출돼야 하는데 {len(calls)}번 호출됨: {calls}")
        self.assertEqual(calls[0], ["covers"])
        self.assertNotIn("covers", calls[1] or [])
        self.assertNotIn("videos", calls[1] or [])
        self.assertEqual(calls[2], ["videos"])

        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        detail = self.api.get_game_detail(rom_key)["data"]
        self.assertEqual(detail["media"].get("Videos"), "video://exists")

    def test_start_export_local_to_masterdb_scans_local_only_once_across_phases(self):
        """[P1-1] 3-phase Import from ArchiveDB가 phase마다 이 Local을 처음부터
        다시 스캔하면 안 된다 - api.py가 phase 시작 전 한 번만 스캔해서
        (importers.scan.scan_local) 그 결과를 모든 phase(import_local_to_masterdb/
        _copy_roms_to_masterdb)가 공유해야 한다. importers.scan.scan_local() 자체가
        몇 번 호출되는지 spy로 센다."""
        from unittest.mock import patch
        from importers import scan as scan_module
        original_scan_local = scan_module.scan_local
        calls = []

        def spy_scan_local(*args, **kwargs):
            calls.append(1)
            return original_scan_local(*args, **kwargs)

        local_id = self.make_esde_local()
        (self.tmp / "로컬1_ES-DE" / "meta" / "downloaded_media" / "snes" / "videos").mkdir(parents=True)
        (self.tmp / "로컬1_ES-DE" / "meta" / "downloaded_media" / "snes" / "videos" / "게임.mp4").write_bytes(b"VIDEO")

        with patch("api.scan_local", side_effect=spy_scan_local):
            # mode="metadata"(ROM 복사 없음)를 쓴다 - "roms"/"metadata_roms"는
            # check_export_disk_space()가 사전에 별도로(정당하게, phase 공유와는
            # 무관하게) 한 번 더 스캔하므로 그 경우를 섞으면 "phase 간 공유"만
            # 순수하게 검증하기 어렵다.
            r = self.api.start_export_local_to_masterdb(local_id, "metadata")
            self.assertTrue(r["ok"], r.get("error"))
            job_id = r["data"]["jobId"]
            for _ in range(100):
                if self.api.get_job_progress(job_id)["data"]["done"]:
                    break
                time.sleep(0.02)
            self.assertIsNone(self.api.get_job_progress(job_id)["data"]["error"])
            for _ in range(200):
                with self.api._busy_lock:
                    if local_id not in self.api._busy_targets and "masterdb" not in self.api._busy_targets:
                        break
                time.sleep(0.02)

        # api.py 레이어(start_export_local_to_masterdb)가 부르는 scan_local()은
        # phase 수(3)와 무관하게 딱 한 번이어야 한다 - import_engine.py/
        # export_engine.py 내부의 기본 폴백 경로(scan_result가 없을 때만 도는)는
        # 여기서 항상 shared scan_result가 주어지므로 호출되지 않는다.
        self.assertEqual(calls, [1], f"api.py의 scan_local()이 phase마다 반복 호출됨: {len(calls)}번")

    def test_start_export_local_to_masterdb_final_result_does_not_inflate_imported_count(self):
        """[Parent Job lifecycle 리뷰 반영] start_export_local_to_masterdb()도 Export와
        같은 문제가 있었다 - import_local_to_masterdb()가 selected_media_types와
        무관하게 매 phase마다 대상 ROM 전체를 다시 매칭하므로, 3 phase 각각의
        imported=1을 단순히 더하면 실제로는 ROM 1개인데 최종 결과가 imported=3으로
        부풀려진다(반대로 combine을 아예 안 하면 마지막 phase 혼자만의 값만 남아
        1단계에서만 나는 에러 등이 사라진다). 최종(합산된) 결과의 imported가 정확히
        1단계 값(1) 그대로인지 확인한다."""
        local_id = self.make_esde_local()
        r = self.api.start_export_local_to_masterdb(local_id, "metadata")
        self.assertTrue(r["ok"], r.get("error"))
        job_id = r["data"]["jobId"]
        for _ in range(200):
            with self.api._busy_lock:
                if local_id not in self.api._busy_targets and "masterdb" not in self.api._busy_targets:
                    break
            time.sleep(0.02)

        final = self.api.get_job_progress(job_id)["data"]
        while final.get("result") and final["result"].get("followUpJobId"):
            final = self.api.get_job_progress(final["result"]["followUpJobId"])["data"]
        self.assertIsNone(final["error"], final.get("error"))
        metadata_result = final["result"]["metadataResult"]
        self.assertEqual(metadata_result["imported"], 1,
                          f"phase마다 재평가되는 imported를 그대로 더하면 3(부풀림)이 나와야 하는데: {metadata_result}")

    def test_sha256_queue_stop_sentinel_does_not_crash_worker_when_mixed_with_real_items(self):
        """[버그 수정] _sha256_queue는 PriorityQueue라 heapq가 항목끼리 비교한다.
        예전엔 종료 신호로 그냥 None을 넣었는데, 큐 안에 실제 작업 튜플과 None이
        섞이면 heapq가 "'<' not supported between instances of 'NoneType' and
        'tuple'" TypeError를 던지고, 이게 워커 루프 밖(catch 안 됨)에서 터져서
        워커 스레드 전체가 조용히 죽는다 - 반복 테스트 중 실제로 재현/확인된
        문제. 큐에 실제 작업 여러 개와 종료 신호를 섞어 넣고도 워커가 죽지 않고
        전부(종료 신호까지) 처리하는지 확인한다."""
        # [주의] queue.PriorityQueue는 내부적으로 heapq를 쓴다 - put()이 새 항목을
        # 삽입할 때 heappush()가 기존 항목과 비교(sift-up)하는데, 항목 타입이
        # 섞여 있으면(실제 5-튜플들 사이에 bare None 하나) 그 비교 자체가
        # TypeError를 던진다. 배경 워커가 동시에 큐를 비우면 타이밍에 따라
        # 재현이 안 될 수 있으므로, 여기서는 워커를 먼저 멈춰서(stop 플래그만
        # 세우고 큐는 그대로 둠) 큐 내용물을 직접, 결정적으로 통제한다.
        self.api._sha256_stop.set()
        self.api._sha256_thread.join(timeout=2)
        for i in range(5):
            self.api.request_rom_hash("snes", f"game{i}.zip", str(self.tmp), priority=2)
        self.api._sha256_queue.put(self.api._SHA256_STOP_SENTINEL)  # 예외가 나면 여기서 바로 테스트 실패

    def test_close_waits_for_sha256_worker_before_closing_sqlite(self):
        """[P0-8 후속 버그 수정] close()가 백그라운드 SHA256 워커 스레드가 실제로
        멈추길 기다리지 않고 바로 SQLite connection을 닫으면, 그 순간 워커가
        여전히 그 connection을 쓰고 있을 수 있다 - Python 예외가 아니라
        세그폴트로 이어지는 걸 실제로 재현해서 확인한 문제(수정 전 코드로 반복
        재현 시 몇 번 안에 크래시). 워커가 해시 계산 중일 때 close()를 호출해도
        (그 결과를 그대로 쓰려 하지 않고) 프로세스가 죽지 않고 정상적으로
        join되는지 확인한다."""
        import threading
        local_id = self._make_local_for_rom_export()
        original_file_sha256 = dbmod.file_sha256
        hash_started = threading.Event()
        release_hash = threading.Event()

        def slow_file_sha256(path):
            hash_started.set()
            release_hash.wait(timeout=5)
            return original_file_sha256(path)

        dbmod.file_sha256 = slow_file_sha256
        try:
            r = self.api.start_export_local_to_masterdb(local_id, "roms")
            job_id = r["data"]["jobId"]
            for _ in range(100):
                if self.api.get_job_progress(job_id)["data"]["done"]:
                    break
                time.sleep(0.02)
            self.assertTrue(hash_started.wait(timeout=2), "백그라운드 워커가 해시 계산을 시작 안 함")

            # [주의] close()는 워커가 file_sha256()에서 빠져나올 때까지 join으로
            # 기다린다 - 그동안 release_hash를 풀어줄 별도 스레드가 없으면 close()
            # 자체가 영원히 막힌다. 여기서는 join이 실제로 워커를 기다리는지
            # 확인하는 게 목적이므로, release_hash는 짧은 지연 후 별도 스레드에서
            # 풀어준다(close() 호출과 경합하도록 close()보다 먼저 스레드를 띄움).
            def release_soon():
                time.sleep(0.1)
                release_hash.set()

            threading.Thread(target=release_soon, daemon=True).start()
            close_start = time.time()
            self.api.close()
            close_elapsed = time.time() - close_start
            # close()가 워커를 기다리지 않고 즉시 리턴해버리면(수정 전 버그) 이
            # 값이 release_soon()의 지연(0.1s)보다 한참 작게 나온다 - join이 실제로
            # 워커의 완료를 기다렸는지 이 타이밍으로 검증한다.
            self.assertGreaterEqual(close_elapsed, 0.1,
                                     "close()가 워커 스레드를 기다리지 않고 너무 빨리 리턴함")
        finally:
            dbmod.file_sha256 = original_file_sha256

    def test_sha256_computation_does_not_block_copy_job_or_db_lock(self):
        """[P0-8] SHA256 계산(파일 전체를 읽는 무거운 I/O)이 Copy Job 자체나
        _db_lock을 오래 잡고 있으면 안 된다 - 이전엔 _copy_roms_to_masterdb()가
        복사 직후 그 자리에서 동기로 file_sha256()을 계산했는데, 이게
        mutates_db=True job의 _db_lock 전체 구간 안에서 실행돼서 해시 계산이
        오래 걸리는 동안 다른 모든 DB-mutating 작업이 block됐다. file_sha256을
        느리게 만든 채로 Export(roms 모드, 실제 복사 발생) job을 돌려서, job
        자체가 해시 계산 시간과 무관하게 빨리 끝나는지 확인한다."""
        import time as time_mod
        import threading
        local_id = self._make_local_for_rom_export()

        original_file_sha256 = dbmod.file_sha256
        hash_started = threading.Event()
        release_hash = threading.Event()

        def slow_file_sha256(path):
            hash_started.set()
            release_hash.wait(timeout=5)
            return original_file_sha256(path)

        dbmod.file_sha256 = slow_file_sha256
        try:
            start = time_mod.time()
            r = self.api.start_export_local_to_masterdb(local_id, "roms")
            job_id = r["data"]["jobId"]
            for _ in range(200):
                p = self.api.get_job_progress(job_id)
                if p["data"]["done"]:
                    break
                time_mod.sleep(0.02)
            job_elapsed = time_mod.time() - start
            self.assertIsNone(p["data"]["error"], p["data"].get("error"))
            self.assertLess(job_elapsed, 2.0,
                             f"SHA256 계산(release_hash 대기 중, 5초 timeout)이 끝나길 기다리느라 "
                             f"Copy Job이 {job_elapsed:.2f}초나 걸림 - critical path에서 분리 안 됨")

            # job은 이미 끝났지만, 해시 계산은 아직 (백그라운드에서) release_hash를
            # 기다리며 막혀 있는 상태여야 한다 - 이게 "job과 무관하게 나중에 끝난다"는
            # 증거다.
            self.assertTrue(hash_started.wait(timeout=2), "백그라운드 스레드가 SHA256 계산을 시작조차 안 함")
        finally:
            release_hash.set()
            dbmod.file_sha256 = original_file_sha256

        for _ in range(100):
            if self.api._sqlite.get_rom_hash("snes|game.zip") is not None:
                break
            time_mod.sleep(0.02)
        self.assertIsNotNone(self.api._sqlite.get_rom_hash("snes|game.zip"),
                              "release 이후에도 결국 해시가 캐시되지 않음")

    def test_export_roms_mode_caches_sha256_and_does_not_recompute_on_skip(self):
        """[신규, 2026-09-02] ROM이 ArchiveDB로 처음 복사될 때 SHA256을 한 번만
        계산해 SQLite에 캐시하고(get_game_detail에도 노출), 같은 ROM을 다시
        export(이미 있어서 skip)해도 재계산하지 않아야 한다(계산량을 "처음 가져올
        때"로만 제한하려는 의도)."""
        import hashlib
        import time

        local_id = self._make_local_for_rom_export()
        r = self.api.start_export_local_to_masterdb(local_id, "roms")
        job_id = r["data"]["jobId"]
        for _ in range(50):
            p = self.api.get_job_progress(job_id)
            if p["data"]["done"]:
                break
            time.sleep(0.02)
        self.assertIsNone(p["data"]["error"], p["data"].get("error"))

        # [주의] mode="roms"는 ROM 실물만 복사하고 metadata는 안 옮기므로(별도
        # "metadata" 모드가 그 역할), SQLite에 이 rom의 metadata row 자체가 아직
        # 없다 - get_game_detail()의 sha256 노출은 별도 테스트에서 확인한다.
        # [P0-8] SHA256은 더 이상 Copy Job 안에서 동기로 계산되지 않고 별도
        # 백그라운드 큐/스레드로 넘어간다 - job이 done이어도 해시 계산은 아직
        # 안 끝났을 수 있으므로 폴링으로 기다린다.
        expected_sha256 = hashlib.sha256(b"X" * 1000).hexdigest()
        actual_sha256 = None
        for _ in range(100):
            actual_sha256 = self.api._sqlite.get_rom_hash("snes|game.zip")
            if actual_sha256 is not None:
                break
            time.sleep(0.02)
        self.assertEqual(actual_sha256, expected_sha256)

        original_file_sha256 = dbmod.file_sha256
        calls = []

        def _spy(path):
            calls.append(path)
            return original_file_sha256(path)

        dbmod.file_sha256 = _spy
        try:
            r2 = self.api.start_export_local_to_masterdb(local_id, "roms")
            job_id2 = r2["data"]["jobId"]
            for _ in range(50):
                p2 = self.api.get_job_progress(job_id2)
                if p2["data"]["done"]:
                    break
                time.sleep(0.02)
        finally:
            dbmod.file_sha256 = original_file_sha256
        self.assertIsNone(p2["data"]["error"], p2["data"].get("error"))
        self.assertEqual(p2["data"]["result"]["romsResult"]["skipped"], 1, "이미 저장된 ROM이라 skip돼야 함")
        self.assertEqual(calls, [], "skip된(이미 저장된) ROM인데 SHA256을 다시 계산함")
        self.assertEqual(self.api._sqlite.get_rom_hash("snes|game.zip"), expected_sha256)

    def test_get_game_detail_exposes_cached_sha256(self):
        import hashlib
        import time

        local_id = self._make_local_for_rom_export()
        r = self.api.start_export_local_to_masterdb(local_id, "metadata_roms")
        job_id = r["data"]["jobId"]
        for _ in range(50):
            p = self.api.get_job_progress(job_id)
            if p["data"]["done"]:
                break
            time.sleep(0.02)
        self.assertIsNone(p["data"]["error"], p["data"].get("error"))

        # [P0-8] SHA256은 백그라운드 큐에서 비동기로 계산되므로 폴링으로 기다린다.
        expected_sha256 = hashlib.sha256(b"X" * 1000).hexdigest()
        detail = None
        for _ in range(100):
            detail = self.api.get_game_detail("snes|game.zip")
            self.assertTrue(detail["ok"], detail.get("error"))
            if detail["data"].get("sha256") == expected_sha256:
                break
            time.sleep(0.02)
        self.assertEqual(detail["data"]["sha256"], expected_sha256)

    def test_export_roms_mode_skips_already_stored_roms(self):
        local_id = self._make_local_for_rom_export()
        r1 = self.api.start_export_local_to_masterdb(local_id, "roms")
        job1 = r1["data"]["jobId"]
        import time
        for _ in range(50):
            if self.api.get_job_progress(job1)["data"]["done"]:
                break
            time.sleep(0.02)

        # 두 번째 실행 -> 이미 저장되어 있으므로 skipped여야 함
        r2 = self.api.start_export_local_to_masterdb(local_id, "roms")
        job2 = r2["data"]["jobId"]
        for _ in range(50):
            p2 = self.api.get_job_progress(job2)
            if p2["data"]["done"]:
                break
            time.sleep(0.02)
        self.assertEqual(p2["data"]["result"]["romsResult"]["copied"], 0)
        self.assertEqual(p2["data"]["result"]["romsResult"]["skipped"], 1)

    def test_start_export_to_local_job_copies_metadata_and_reports_exported(self):
        """[P0 리뷰 반영] GameList의 Import from ArchiveDB / Export to GameListSet
        대화상자는 항상 api.startExportToLocal()을 호출하고 runJobWithProgress()로
        jobId를 기대하는데, 예전엔 이 job 래퍼 자체가 없었다(동기 export_to_local()만
        있었음) - pywebview 실기에서는 두 버튼 다 누르는 즉시 존재하지 않는 메서드
        호출로 죽는 상태였다. mock 기반 Playwright는 없는 메서드 호출까지 못 가서
        (undefined 함수 호출은 브릿지 계층 진입 전에 실패) 이 문제를 못 잡았었다."""
        local_id = self._make_local_for_rom_export("소스로컬")
        imp = self.api.start_export_local_to_masterdb(local_id, "metadata_roms")
        job1 = imp["data"]["jobId"]
        import time
        for _ in range(50):
            if self.api.get_job_progress(job1)["data"]["done"]:
                break
            time.sleep(0.02)

        dst_root = self.tmp / "대상로컬_ES-DE"
        (dst_root / "roms" / "snes").mkdir(parents=True)
        (dst_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (dst_root / "roms" / "snes" / "game.zip").write_bytes(b"Y" * 10)
        dst_r = self.api.add_local("대상로컬", "ES-DE", str(dst_root / "roms"), str(dst_root / "meta"))
        dst_id = dst_r["data"]["id"]

        r = self.api.start_export_to_local(dst_id)
        self.assertTrue(r["ok"], r.get("error"))
        job2 = r["data"]["jobId"]
        for _ in range(50):
            p = self.api.get_job_progress(job2)
            if p["data"]["done"]:
                break
            time.sleep(0.02)
        self.assertIsNone(p["data"]["error"], p["data"].get("error"))
        self.assertEqual(p["data"]["result"]["exported"], 1)
        written = (dst_root / "meta" / "gamelists" / "snes" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertIn("Game", written)

    def test_start_export_to_local_runs_as_a_db_mutating_job(self):
        """[P1 리뷰 반영] export_masterdb_to_local()이 sqlite_repo를 통해
        GameListSet membership을 SQLite에 기록하므로 실제 DB mutation이다.
        start_export_to_local()이 mutates_db=False로 _run_job을 호출하고
        있었는데(잘못된 값), 그러면 다른 mutation job(_db_lock)과 겹쳐서 같은
        sqlite3 connection을 동시에 건드릴 수 있었다. _run_job에 실제로
        mutates_db=True가 전달되는지 직접 확인한다."""
        local_id = self._make_local_for_rom_export("소스로컬2")
        imp = self.api.start_export_local_to_masterdb(local_id, "metadata_roms")
        job1 = imp["data"]["jobId"]
        for _ in range(50):
            if self.api.get_job_progress(job1)["data"]["done"]:
                break
            time.sleep(0.02)

        dst_root = self.tmp / "대상로컬2_ES-DE"
        (dst_root / "roms" / "snes").mkdir(parents=True)
        (dst_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (dst_root / "roms" / "snes" / "game.zip").write_bytes(b"Z" * 10)
        dst_r = self.api.add_local("대상로컬2", "ES-DE", str(dst_root / "roms"), str(dst_root / "meta"))
        dst_id = dst_r["data"]["id"]

        # [Queue 구조] Scan/Import/Export는 이제 _run_job이 아니라 _run_heavy_job을
        # 통해 도므로(_start_phased_media_job 참고) 여기도 그걸 스파이한다.
        from unittest.mock import patch
        with patch.object(self.api, "_run_heavy_job", wraps=self.api._run_heavy_job) as spy:
            r = self.api.start_export_to_local(dst_id)
            self.assertTrue(r["ok"], r.get("error"))
            self.assertEqual(spy.call_args.kwargs.get("mutates_db"), True)
        job2 = r["data"]["jobId"]
        for _ in range(50):
            if self.api.get_job_progress(job2)["data"]["done"]:
                break
            time.sleep(0.02)

    def test_start_export_to_local_runs_in_three_phases_cover_then_rest_then_video(self):
        """[체감 속도, Export 3단계] start_export_to_local()이 (1) covers (2) videos
        제외 나머지 (3) videos 순서로 3번에 걸쳐 export_masterdb_to_local()을 부르는지,
        진행률 label에 "(1/3)"/"(2/3)"/"(3/3)"이 실제로 붙는지, 그리고 3단계가 모두
        끝날 때까지 target이 계속 busy인지 spy + 실제 job 폴링으로 확인한다."""
        from unittest.mock import patch
        import export_engine as export_engine_mod
        original_export = export_engine_mod.export_masterdb_to_local
        calls = []

        def spy_export(*args, **kwargs):
            calls.append(kwargs.get("media_types"))
            return original_export(*args, **kwargs)

        local_id = self._make_local_for_rom_export("소스로컬3")
        imp = self.api.start_export_local_to_masterdb(local_id, "metadata_roms")
        job1 = imp["data"]["jobId"]
        for _ in range(50):
            if self.api.get_job_progress(job1)["data"]["done"]:
                break
            time.sleep(0.02)

        dst_root = self.tmp / "대상로컬3_ES-DE"
        (dst_root / "roms" / "snes").mkdir(parents=True)
        (dst_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (dst_root / "roms" / "snes" / "game.zip").write_bytes(b"Q" * 10)
        dst_r = self.api.add_local("대상로컬3", "ES-DE", str(dst_root / "roms"), str(dst_root / "meta"))
        dst_id = dst_r["data"]["id"]

        labels_seen = []
        with patch("api.export_masterdb_to_local", side_effect=spy_export):
            r = self.api.start_export_to_local(dst_id)
            self.assertTrue(r["ok"], r.get("error"))
            job2 = r["data"]["jobId"]
            for _ in range(200):
                p = self.api.get_job_progress(job2)
                if p["data"].get("label"):
                    labels_seen.append(p["data"]["label"])
                if p["data"]["done"]:
                    break
                time.sleep(0.01)
            # 1단계 job이 done이어도, 아직 2/3단계가 남아있을 수 있으므로 target이
            # busy에서 풀릴 때까지 별도로 기다린 뒤에 최종 상태를 검증한다.
            for _ in range(200):
                with self.api._busy_lock:
                    if dst_id not in self.api._busy_targets and "masterdb" not in self.api._busy_targets:
                        break
                time.sleep(0.01)

        self.assertEqual(len(calls), 3, f"3단계로 나뉘어 3번 호출돼야 하는데 {len(calls)}번 호출됨: {calls}")
        self.assertEqual(calls[0], ["covers"])
        self.assertNotIn("covers", calls[1] or [])
        self.assertNotIn("videos", calls[1] or [])
        self.assertEqual(calls[2], ["videos"])
        self.assertTrue(any(l.startswith("(1/3)") for l in labels_seen), labels_seen)

    def test_start_export_to_local_final_result_aggregates_all_three_phases(self):
        """[Parent Job lifecycle 리뷰 반영] _start_phased_media_job이 combine_results
        없이 마지막(비디오) phase의 결과만 최종 job.result로 남기면, 실제로는
        1단계(메타데이터 export)에서 exported=1이 났는데도 최종 토스트엔 exported가
        2/3단계 자기 혼자만의 재평가 결과(마지막 phase 값)로 잘못 표시된다.

        [주의] exported/skipped_* 를 phase마다 단순히 더하는 건 틀렸다 -
        export_masterdb_to_local()은 media_types와 무관하게 매 phase마다 대상 ROM
        전체의 metadata를 다시 매칭한다(media_types는 media만 거름). 그래서 naive
        합산은 ROM 1개를 3번 센 것처럼 exported=3으로 부풀어진다. 진짜로 의미 있는
        숫자는 1단계(대상을 처음 훑은 phase)뿐이므로, 최종 결과가 그 1단계 값을
        그대로 유지하는지 확인한다."""
        local_id = self._make_local_for_rom_export("소스로컬4")
        imp = self.api.start_export_local_to_masterdb(local_id, "metadata_roms")
        job1 = imp["data"]["jobId"]
        for _ in range(50):
            if self.api.get_job_progress(job1)["data"]["done"]:
                break
            time.sleep(0.02)

        dst_root = self.tmp / "대상로컬4_ES-DE"
        (dst_root / "roms" / "snes").mkdir(parents=True)
        (dst_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (dst_root / "roms" / "snes" / "game.zip").write_bytes(b"R" * 10)
        dst_r = self.api.add_local("대상로컬4", "ES-DE", str(dst_root / "roms"), str(dst_root / "meta"))
        dst_id = dst_r["data"]["id"]

        r = self.api.start_export_to_local(dst_id)
        self.assertTrue(r["ok"], r.get("error"))
        job_id = r["data"]["jobId"]
        for _ in range(200):
            with self.api._busy_lock:
                if dst_id not in self.api._busy_targets and "masterdb" not in self.api._busy_targets:
                    break
            time.sleep(0.02)

        # [주의] job_id는 1단계 job의 id다 - 2/3단계는 followUpJobId로 이어진 별도
        # job이라, 최종(합산된) 결과를 보려면 진짜 끝난 job까지 followUpJobId를 따라가야 한다.
        final = self.api.get_job_progress(job_id)["data"]
        while final.get("result") and final["result"].get("followUpJobId"):
            final = self.api.get_job_progress(final["result"]["followUpJobId"])["data"]
        self.assertIsNone(final["error"], final.get("error"))
        result = final["result"]
        self.assertEqual(result["exported"], 1,
                          "1단계(metadata export)의 exported=1이 최종 결과에서 유지되어야 하는데, "
                          "2/3단계 자체 값으로 덮이거나(버그) 잘못 합산돼(3배 부풀림) 어긋남")

    def test_start_export_to_local_final_result_keeps_errors_from_earlier_phases(self):
        """[Parent Job lifecycle 리뷰 반영] combine_results 없이 마지막 phase의
        결과만 최종 result로 남으면, 1단계에서만 난 에러는 3단계(비디오, 정상
        종료)의 빈 errors 리스트에 가려 최종 결과에서 통째로 사라진다. 1단계에서만
        에러가 나게 만들어서, 최종 결과의 errors에 그 에러 메시지가 살아있는지
        확인한다 - 이게 "last phase만 return"과 "제대로 합산"을 실제로 갈라주는
        시나리오다(단일 ROM으로 exported 값만 보면 두 경우 다 우연히 1이 나와
        구분이 안 됨)."""
        from unittest.mock import patch
        import exporters.es_de as es_de_exporter

        # [주의] _make_local_for_rom_export()는 cover가 없는 fixture라 media-write
        # 경로(write_media) 자체가 안 불린다 - 여기선 make_esde_local()(cover 있음)로
        # MasterDB에 cover까지 실제로 들여온 뒤, 그걸 새 Local로 export한다.
        local_id = self.make_esde_local(label="소스로컬5")
        imp_r = self.api.import_local_to_masterdb(local_id)
        self.assertTrue(imp_r["ok"], imp_r.get("error"))

        dst_root = self.tmp / "대상로컬5_ES-DE"
        (dst_root / "roms" / "snes").mkdir(parents=True)
        (dst_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (dst_root / "roms" / "snes" / "게임.zip").write_bytes(b"S" * 10)
        dst_r = self.api.add_local("대상로컬5", "ES-DE", str(dst_root / "roms"), str(dst_root / "meta"))
        dst_id = dst_r["data"]["id"]

        original_write_media = es_de_exporter.write_media
        calls = {"n": 0}

        def failing_once(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated media write failure in phase 1")
            return original_write_media(*args, **kwargs)

        with patch.object(es_de_exporter, "write_media", side_effect=failing_once):
            r = self.api.start_export_to_local(dst_id)
            self.assertTrue(r["ok"], r.get("error"))
            job_id = r["data"]["jobId"]
            for _ in range(200):
                with self.api._busy_lock:
                    if dst_id not in self.api._busy_targets and "masterdb" not in self.api._busy_targets:
                        break
                time.sleep(0.02)

        final = self.api.get_job_progress(job_id)["data"]
        while final.get("result") and final["result"].get("followUpJobId"):
            final = self.api.get_job_progress(final["result"]["followUpJobId"])["data"]
        self.assertIsNone(final["error"], final.get("error"))
        errors = final["result"]["errors"]
        self.assertTrue(any("simulated media write failure in phase 1" in e for e in errors),
                         f"1단계에서 난 에러가 최종 결과에서 사라짐(마지막 phase 결과로 덮임): {errors}")

    def test_export_metadata_only_mode_does_not_copy_rom(self):
        local_id = self._make_local_for_rom_export()
        r = self.api.start_export_local_to_masterdb(local_id, "metadata")
        job_id = r["data"]["jobId"]
        import time
        for _ in range(50):
            p = self.api.get_job_progress(job_id)
            if p["data"]["done"]:
                break
            time.sleep(0.02)
        self.assertIsNone(p["data"]["result"]["romsResult"])
        stored = dbmod.rom_storage_path(self.api.cfg["masterdb"]["root"], "snes", "game.zip")
        self.assertFalse(stored.exists())

    def test_export_local_to_masterdb_media_types_filters_which_media_is_copied(self):
        """[GameList Export 모달 통일] media_types를 넘기면 선택 안 된 타입은 아예
        복사되지 않아야 한다 - Settings > Media와 동일한 선택 UI를 지원하기 위함."""
        import time
        local_id = self.make_esde_local()  # covers 미디어 1개 보유

        def run(media_types):
            r = self.api.start_export_local_to_masterdb(local_id, "metadata", media_types=media_types)
            self.assertTrue(r["ok"], r.get("error"))
            job_id = r["data"]["jobId"]
            for _ in range(50):
                p = self.api.get_job_progress(job_id)
                if p["data"]["done"]:
                    return p
                time.sleep(0.02)
            self.fail("job did not finish")

        run(media_types=[])  # covers를 선택 목록에서 제외
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        self.assertNotIn("covers", self.api._sqlite.get_rom(rom_key)["media"])

        run(media_types=["covers"])  # 다시 선택하면 반영됨
        self.assertIn("covers", self.api._sqlite.get_rom(rom_key)["media"])

    def test_export_invalid_mode_rejected(self):
        local_id = self._make_local_for_rom_export()
        r = self.api.start_export_local_to_masterdb(local_id, "bogus_mode")
        self.assertFalse(r["ok"])

    def test_check_export_disk_space_accounts_for_already_stored_roms(self):
        local_id = self._make_local_for_rom_export()
        r1 = self.api.check_export_disk_space(local_id, "roms")
        self.assertTrue(r1["ok"])
        self.assertEqual(r1["data"]["required"], 1000)  # 아직 저장 안 됨 -> 전체 필요

        # 저장 후 다시 확인하면 필요량이 0이어야 함
        self.api.start_export_local_to_masterdb(local_id, "roms")
        import time
        time.sleep(0.3)
        r2 = self.api.check_export_disk_space(local_id, "roms")
        self.assertEqual(r2["data"]["required"], 0)

    def test_check_export_disk_space_metadata_mode_needs_no_space(self):
        local_id = self._make_local_for_rom_export()
        r = self.api.check_export_disk_space(local_id, "metadata")
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["required"], 0)

    def test_export_fails_upfront_when_disk_space_insufficient(self):
        """디스크 용량 부족 시 복사를 시작하지도 않고 바로 실패해야 한다."""
        local_id = self._make_local_for_rom_export()
        # disk_utils를 몽키패치해서 강제로 용량 부족 상황을 재현
        import api as api_module
        original = api_module.disk_utils.check_space_for_copy
        api_module.disk_utils.check_space_for_copy = lambda *a, **k: {
            "ok": False, "free": 100, "required": 999999999999, "shortage": 999999999899,
        }
        try:
            r = self.api.start_export_local_to_masterdb(local_id, "roms")
            self.assertFalse(r["ok"])
            self.assertIn("용량", r["error"])
        finally:
            api_module.disk_utils.check_space_for_copy = original

        # 실패했으니 ROM이 실제로 복사되지 않았어야 함
        stored = dbmod.rom_storage_path(self.api.cfg["masterdb"]["root"], "snes", "game.zip")
        self.assertFalse(stored.exists())


    # ------------------------------------------------------------------
    # [신규] Dashboard 통계 정확도 개선 (Local scope를 근사매칭 대신 scan_local 직접 사용)
    # ------------------------------------------------------------------
    def test_dashboard_local_scope_uses_accurate_scan_not_approximation(self):
        """두 Local이 같은 시스템(snes)을 쓰더라도, 각 Local 통계는 서로 섞이면 안 된다."""
        masterdb_root = str(self.tmp / "masterdb")
        self.api.set_masterdb_path(masterdb_root)

        def make(label, count):
            root = self.tmp / (label + "_ES-DE")
            (root / "roms" / "snes").mkdir(parents=True)
            (root / "meta" / "gamelists" / "snes").mkdir(parents=True)
            games_xml = "<gameList>" + "".join(
                f'<game><path>./g{i}.zip</path><name>G{i}</name><desc>d</desc></game>' for i in range(count)
            ) + "</gameList>"
            (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(games_xml, encoding="utf-8")
            for i in range(count):
                (root / "roms" / "snes" / f"g{i}.zip").write_bytes(b"X" * 100)
            r = self.api.add_local(label, "ES-DE", str(root / "roms"), str(root / "meta"))
            return r["data"]["id"]

        local_a = make("로컬A", 3)
        local_b = make("로컬B", 7)

        stats_a = self.api.get_dashboard_stats(local_a)
        stats_b = self.api.get_dashboard_stats(local_b)
        self.assertEqual(stats_a["data"]["romCount"], 3)
        self.assertEqual(stats_b["data"]["romCount"], 7)

    def test_dashboard_masterdb_scope_missing_rom_reflects_actual_stored_file(self):
        """MasterDB scope의 Missing ROM은 이제 '실물 파일이 저장돼 있는지' 기준이어야 한다."""
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)  # metadata만 (ROM 실물은 아직 없음)
        stats = self.api.get_dashboard_stats("masterdb")
        self.assertTrue(stats["ok"])
        self.assertEqual(stats["data"]["missingRom"], 1)  # 실물 없음 -> Missing

        self.api.start_export_local_to_masterdb(local_id, "roms")
        import time
        time.sleep(0.3)
        stats2 = self.api.get_dashboard_stats("masterdb")
        self.assertEqual(stats2["data"]["missingRom"], 0)  # 이제 실물 있음

    def test_dashboard_returns_six_metrics_and_per_system_sizes(self):
        local_id = self.make_esde_local()
        stats = self.api.get_dashboard_stats(local_id)
        self.assertTrue(stats["ok"])
        d = stats["data"]
        for key in ("romCount", "romSizeBytes", "metadataCount", "mediaSizeBytes", "missingRom", "missingMedia", "systems"):
            self.assertIn(key, d)
        self.assertGreater(len(d["systems"]), 0)
        self.assertIn("romSizeBytes", d["systems"][0])
        self.assertIn("mediaSizeBytes", d["systems"][0])

    def test_dashboard_metadata_only_local_shows_real_metadata_and_media(self):
        """[버그 수정] ES-DE metadata-only Local(rom_path 미설정 - gamelist/media는
        있지만 물리 ROM은 등록하지 않는 방식)은 Dashboard의 metadataCount/mediaSizeBytes가
        항상 0으로 나왔다 - 두 값 모두 물리 ROM에 매칭된 항목만 세던 코드였기 때문이다.
        실제로는 gamelist/media가 있으므로 둘 다 0이 아니어야 한다."""
        masterdb_root = str(self.tmp / "masterdb")
        self.api.set_masterdb_path(masterdb_root)

        root = self.tmp / "메타전용_ES-DE"
        (root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (root / "meta" / "downloaded_media" / "snes" / "covers").mkdir(parents=True)
        (root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            '<gameList><game><path>./Game1.zip</path><name>Game1</name><desc>d</desc></game>'
            '<game><path>./Game2.zip</path><name>Game2</name><desc>d</desc></game></gameList>',
            encoding="utf-8",
        )
        (root / "meta" / "downloaded_media" / "snes" / "covers" / "Game1.png").write_bytes(b"X" * 5000)

        r = self.api.add_local("메타전용", "ES-DE", "", str(root / "meta"))
        self.assertTrue(r["ok"], r.get("error"))
        local_id = r["data"]["id"]

        # 라이브 스캔 캐시 경로 (같은 프로세스 안에서 GameList를 한 번 본 상태)
        scan = self.api.scan_local(local_id)
        self.assertTrue(scan["ok"], scan.get("error"))
        live = self.api.get_dashboard_stats(local_id, True)
        self.assertTrue(live["ok"])
        self.assertEqual(live["data"]["metadataCount"], 2)
        self.assertGreater(live["data"]["mediaSizeBytes"], 0)

        # 콜드스타트 경로 (새 Api 인스턴스 - 프로세스 재시작을 흉내냄, 라이브 스캔 캐시 없음)
        fresh_api = Api()
        cold = fresh_api.get_dashboard_stats(local_id, True)
        self.assertTrue(cold["ok"])
        self.assertEqual(cold["data"]["metadataCount"], 2)
        self.assertGreater(cold["data"]["mediaSizeBytes"], 0)
        fresh_api.close()

    def test_health_info(self):
        local_id = self.make_esde_local()
        r = self.api.get_health_info()
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["localCount"], 1)
        self.assertEqual(r["data"]["localMax"], 4)
        self.assertIn(str(self.tmp), r["data"]["masterdbPath"])


    # ------------------------------------------------------------------
    # [신규] 게임 삭제 (Local: metadata/ROM 개별, MasterDB: metadata만)
    # ------------------------------------------------------------------
    def test_delete_local_games_metadata_only_keeps_rom(self):
        local_id = self.make_esde_local()
        scan = self.api.scan_local(local_id)
        rom_key = scan["data"]["games"][0]["romKey"]

        r = self.api.delete_local_games(local_id, [rom_key], True, False)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["data"]["metadataDeleted"], 1)
        self.assertEqual(r["data"]["romDeleted"], 0)

        rescan = self.api.scan_local(local_id)
        # [신규 기능 반영] gamelist 항목은 지워졌지만 ROM 파일은 남아있으므로, 이제
        # "metadata 없는 고아 ROM"으로 계속 표시되어야 한다 (noMetadata=True).
        self.assertEqual(len(rescan["data"]["games"]), 1)
        self.assertTrue(rescan["data"]["games"][0]["noMetadata"])
        self.assertEqual(rescan["data"]["games"][0]["title"], "")

    def test_delete_local_games_rom_only_keeps_metadata(self):
        local_id = self.make_esde_local()
        scan = self.api.scan_local(local_id)
        rom_key = scan["data"]["games"][0]["romKey"]

        r = self.api.delete_local_games(local_id, [rom_key], False, True)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["data"]["romDeleted"], 1)
        self.assertEqual(r["data"]["metadataDeleted"], 0)

        rescan = self.api.scan_local(local_id)
        # ROM 파일이 없어졌으니 이제 Missing ROM(누락) 상태로 나와야 하지만 항목 자체는 남아있어야 함
        self.assertEqual(len(rescan["data"]["games"]), 1)
        self.assertFalse(rescan["data"]["games"][0]["romMatched"])

    def test_delete_local_games_both_removes_completely(self):
        local_id = self.make_esde_local()
        scan = self.api.scan_local(local_id)
        rom_key = scan["data"]["games"][0]["romKey"]

        r = self.api.delete_local_games(local_id, [rom_key], True, True)
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["metadataDeleted"], 1)
        self.assertEqual(r["data"]["romDeleted"], 1)

        rescan = self.api.scan_local(local_id)
        self.assertEqual(len(rescan["data"]["games"]), 0)

    def test_delete_local_games_requires_at_least_one_target(self):
        local_id = self.make_esde_local()
        r = self.api.delete_local_games(local_id, ["snes|x.zip"], False, False)
        self.assertFalse(r["ok"])

    def test_delete_local_games_multi_select(self):
        local_id = self._make_full_media_local()  # full.zip + missing_rom.zip 2개
        scan = self.api.scan_local(local_id)
        rom_keys = [g["romKey"] for g in scan["data"]["games"]]
        self.assertEqual(len(rom_keys), 2)

        r = self.api.delete_local_games(local_id, rom_keys, True, False)
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["metadataDeleted"], 2)

    def test_delete_masterdb_games_removes_entry_only_from_masterdb(self):
        """MasterDB에서 삭제하면 MasterDB만 지워지고, 원본 Local 파일은 안 건드려야 한다."""
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]

        r = self.api.delete_masterdb_games([rom_key])
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["deleted"], 1)
        self.assertEqual(self.api.list_masterdb_games()["data"], [])

        # Local 쪽은 그대로 남아있어야 함
        local_scan = self.api.scan_local(local_id)
        self.assertEqual(len(local_scan["data"]["games"]), 1)

    def test_delete_masterdb_games_does_not_affect_local_view(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        self.api.delete_masterdb_games([rom_key])
        # Local 재-Import 하면 다시 나타나야 함 (진짜로 로컬 파일이 안 건드려졌다는 증거)
        r = self.api.import_local_to_masterdb(local_id)
        self.assertEqual(r["data"]["imported"], 1)

    # ------------------------------------------------------------------
    # [0.4.1.x F2] ArchiveDB ROM 파일명 변경
    # ------------------------------------------------------------------
    def _wait_job(self, job_id):
        """[버그 수정] 여러 phase로 나뉘는 job(Export/Import 등)은 phase 1의
        job_id만 done이어도 전체 chain은 아직 안 끝났을 수 있다(다음 phase가
        바로 이어서 별도 스레드로 시작됨) - 이전엔 phase 1만 확인하고 바로
        rename/delete 등 다음 동작을 시도해서, 실제로는 아직 Export가 진행
        중인데 P0-6/P0-7의 busy 체크에 막히는 (타이밍에 따라) 간헐적 실패가
        있었다. followUpJobId를 따라가서 chain 전체가 끝날 때까지 기다린다."""
        import time
        p = None
        for _ in range(50):
            p = self.api.get_job_progress(job_id)
            if p["data"]["done"]:
                break
            time.sleep(0.02)
        self.assertIsNone(p["data"]["error"], p["data"].get("error"))
        follow = (p["data"].get("result") or {}).get("followUpJobId") if isinstance(p["data"].get("result"), dict) else None
        if follow:
            return self._wait_job(follow)
        return p["data"]["result"]

    def test_rename_masterdb_rom_moves_file_and_media_and_updates_key(self):
        local_id = self.make_esde_local()
        r0 = self.api.start_export_local_to_masterdb(local_id, "metadata_roms")
        self.assertTrue(r0["ok"], r0.get("error"))
        self._wait_job(r0["data"]["jobId"])
        old_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        system, old_filename = old_key.split("|", 1)

        r = self.api.rename_masterdb_rom(old_key, "Renamed.zip")
        self.assertTrue(r["ok"], r.get("error"))
        new_key = r["data"]["romKey"]
        self.assertEqual(new_key, f"{system}|Renamed.zip")

        games = self.api.list_masterdb_games()["data"]
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["romKey"], new_key)
        self.assertEqual(games[0]["file"], "Renamed.zip")

        root = Path(self.api.cfg["masterdb"]["root"])
        self.assertTrue((root / "roms" / system / "Renamed.zip").exists())
        self.assertFalse((root / "roms" / system / old_filename).exists())

    def test_rename_masterdb_rom_rejects_name_collision(self):
        local_id = self.make_esde_local()
        # 충돌을 만들기 위해 gamelist에 두 번째 게임 항목을 추가한다.
        local = self.api.cfg["locals"][0]
        gamelist_path = Path(local["metadata_path"]) / "gamelists" / "snes" / "gamelist.xml"
        (Path(local["rom_path"]) / "snes" / "Other.zip").write_text("dummy")
        gamelist_path.write_text(
            '<gameList>'
            '<game><path>./게임.zip</path><name>슈퍼 마리오 월드</name><desc>d</desc><genre>g</genre></game>'
            '<game><path>./Other.zip</path><name>Other Game</name><desc>d2</desc><genre>g2</genre></game>'
            '</gameList>',
            encoding="utf-8",
        )
        self.api.import_local_to_masterdb(local_id)

        games = self.api.list_masterdb_games()["data"]
        self.assertEqual(len(games), 2)
        target_key = games[0]["romKey"]
        other_filename = games[1]["file"]

        r = self.api.rename_masterdb_rom(target_key, other_filename)
        self.assertFalse(r["ok"])
        # 충돌 시 아무 것도 바뀌지 않아야 한다.
        self.assertEqual(self.api.list_masterdb_games()["data"], games)

    def test_rename_masterdb_rom_missing_key_errors(self):
        r = self.api.rename_masterdb_rom("snes|NoSuchFile.zip", "New.zip")
        self.assertFalse(r["ok"])

    # ------------------------------------------------------------------
    # [0.4.1.x 단위 9] Favorite
    # ------------------------------------------------------------------
    def test_set_rom_favorite_persists_and_shows_in_list(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        self.assertFalse(self.api.list_masterdb_games()["data"][0]["favorite"])

        r = self.api.set_rom_favorite(rom_key, True)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertTrue(self.api.list_masterdb_games()["data"][0]["favorite"])

        r2 = self.api.set_rom_favorite(rom_key, False)
        self.assertTrue(r2["ok"])
        self.assertFalse(self.api.list_masterdb_games()["data"][0]["favorite"])

    def test_favorite_survives_save_db_json_roundtrip(self):
        """replace_from_dict가 rom_id를 안정적으로 유지하는 한, JSON 저장(_save_db)을
        여러 번 거쳐도 native-only favorite 플래그는 사라지지 않아야 한다."""
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        self.api.set_rom_favorite(rom_key, True)

        # 아무 값도 안 바뀌었지만 JSON 저장 경로를 다시 태운다 (예: 설정 저장 등).
        self.api._save_db()
        self.assertTrue(self.api.list_masterdb_games()["data"][0]["favorite"])

        fresh_api = Api()
        self.assertTrue(fresh_api.list_masterdb_games()["data"][0]["favorite"])
        fresh_api.close()

    def test_delete_masterdb_games_skips_favorites(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        self.api.set_rom_favorite(rom_key, True)

        r = self.api.delete_masterdb_games([rom_key])
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["data"]["deleted"], 0)
        self.assertEqual(r["data"]["favoriteSkipped"], 1)
        # 여전히 목록에 남아있어야 한다.
        self.assertEqual(len(self.api.list_masterdb_games()["data"]), 1)

    def test_delete_masterdb_games_skips_only_favorited_ones_in_a_batch(self):
        local_id = self.make_esde_local()
        local = self.api.cfg["locals"][0]
        gamelist_path = Path(local["metadata_path"]) / "gamelists" / "snes" / "gamelist.xml"
        (Path(local["rom_path"]) / "snes" / "Other.zip").write_text("dummy")
        gamelist_path.write_text(
            '<gameList>'
            '<game><path>./게임.zip</path><name>슈퍼 마리오 월드</name><desc>d</desc></game>'
            '<game><path>./Other.zip</path><name>Other Game</name><desc>d2</desc></game>'
            '</gameList>', encoding="utf-8",
        )
        self.api.import_local_to_masterdb(local_id)
        games = self.api.list_masterdb_games()["data"]
        self.assertEqual(len(games), 2)
        fav_key = games[0]["romKey"]
        other_key = games[1]["romKey"]
        self.api.set_rom_favorite(fav_key, True)

        r = self.api.delete_masterdb_games([fav_key, other_key])
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["data"]["deleted"], 1)
        self.assertEqual(r["data"]["favoriteSkipped"], 1)
        remaining = self.api.list_masterdb_games()["data"]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["romKey"], fav_key)

    # ------------------------------------------------------------------
    # [신규] ROM만 있고 metadata(gamelist 항목)가 없는 경우도 목록에 표시
    # ------------------------------------------------------------------
    def test_scan_local_shows_orphan_rom_with_no_metadata(self):
        masterdb_root = str(self.tmp / "masterdb")
        self.api.set_masterdb_path(masterdb_root)
        local_root = self.tmp / "고아롬로컬_ES-DE"
        (local_root / "roms" / "snes").mkdir(parents=True)
        (local_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        # gamelist.xml엔 등록된 게임이 하나도 없지만, ROM 파일은 존재
        (local_root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList></gameList>", encoding="utf-8"
        )
        (local_root / "roms" / "snes" / "orphan.zip").write_text("dummy")

        r = self.api.add_local("고아롬로컬", "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        local_id = r["data"]["id"]
        scan = self.api.scan_local(local_id)
        self.assertTrue(scan["ok"], scan.get("error"))
        games = scan["data"]["games"]
        self.assertEqual(len(games), 1)
        g = games[0]
        self.assertEqual(g["file"], "orphan.zip")
        self.assertTrue(g["noMetadata"])
        self.assertTrue(g["romMatched"])
        self.assertEqual(g["title"], "")

    def test_scan_local_normal_entries_have_no_metadata_false(self):
        local_id = self.make_esde_local()
        scan = self.api.scan_local(local_id)
        self.assertFalse(scan["data"]["games"][0]["noMetadata"])


    # ------------------------------------------------------------------
    # [신규] 유사롬(Comparable ROM) 알고리즘
    # ------------------------------------------------------------------
    def _make_two_similar_games_in_masterdb(self):
        """같은 게임의 서로 다른 두 버전(한글화 등)을 MasterDB에 등록."""
        masterdb_root = str(self.tmp / "masterdb")
        self.api.set_masterdb_path(masterdb_root)
        local_root = self.tmp / "유사롬로컬_ES-DE"
        (local_root / "roms" / "snes").mkdir(parents=True)
        (local_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (local_root / "roms" / "snes" / "smw.zip").write_text("a")
        (local_root / "roms" / "snes" / "smw_kr.zip").write_text("b")
        (local_root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            '<gameList>'
            '<game><path>./smw.zip</path><name>Super Mario World</name><desc>d</desc>'
            '<developer>Nintendo</developer><releasedate>19901121T000000</releasedate></game>'
            '<game><path>./smw_kr.zip</path><name>Super Mario World [한글화]</name><desc>d</desc>'
            '<developer>Nintendo</developer><releasedate>19901121T000000</releasedate></game>'
            '</gameList>', encoding="utf-8",
        )
        r = self.api.add_local("유사롬로컬", "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        local_id = r["data"]["id"]
        self.api.import_local_to_masterdb(local_id)
        return local_id

    def test_auto_pick_similar_representative_prefers_favorite(self):
        """[0.4.1.x 단위 8] favorite=True인 멤버가 있으면 다른 조건과 무관하게 대표로 뽑힌다."""
        self._make_two_similar_games_in_masterdb()
        self.api.set_rom_favorite("snes|smw_kr.zip", True)
        r = self.api.start_find_similar_roms("snes")
        self._wait_job(r["data"]["jobId"])
        got = self.api.get_similar_rom_groups("snes")["data"]
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["representative"], "snes|smw_kr.zip")

    def test_auto_pick_similar_representative_falls_back_to_description_length(self):
        """favorite/필드개수가 동률이면 description이 더 긴 쪽이 대표가 된다."""
        self._make_two_similar_games_in_masterdb()
        long_desc_entry = self.api.db["roms"]["snes|smw_kr.zip"]
        long_desc_entry["versions"][long_desc_entry["default_version_id"]]["fields"]["desc"] = "d" * 200
        r = self.api.start_find_similar_roms("snes")
        self._wait_job(r["data"]["jobId"])
        got = self.api.get_similar_rom_groups("snes")["data"]
        self.assertEqual(got[0]["representative"], "snes|smw_kr.zip")

    def test_similar_rom_settings_roundtrip(self):
        r = self.api.save_similar_rom_settings(
            {"title": 40, "filename": 10, "developer": 10, "year": 15, "screenshot": 25}, 65
        )
        self.assertTrue(r["ok"])
        got = self.api.get_similar_rom_settings()["data"]
        self.assertEqual(got["weights"]["title"], 40)
        self.assertEqual(got["threshold"], 65)

    def test_similar_rom_settings_defaults(self):
        got = self.api.get_similar_rom_settings()["data"]
        self.assertEqual(got["weights"]["title"], 35)
        self.assertEqual(got["threshold"], 60)

    def test_find_similar_roms_groups_similar_titles(self):
        self._make_two_similar_games_in_masterdb()
        r = self.api.start_find_similar_roms("snes")
        self.assertTrue(r["ok"], r.get("error"))
        job_id = r["data"]["jobId"]
        import time
        for _ in range(50):
            p = self.api.get_job_progress(job_id)
            if p["data"]["done"]:
                break
            time.sleep(0.02)
        self.assertIsNone(p["data"]["error"], p["data"].get("error"))
        groups = p["data"]["result"]["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["members"]), 2)

    def test_get_similar_rom_groups_persisted_and_enriched(self):
        """결과가 DB에 저장되어, 재계산 없이도 나중에 다시 조회 가능해야 한다."""
        self._make_two_similar_games_in_masterdb()
        r = self.api.start_find_similar_roms("snes")
        job_id = r["data"]["jobId"]
        import time
        for _ in range(50):
            if self.api.get_job_progress(job_id)["data"]["done"]:
                break
            time.sleep(0.02)

        # 새 Api 인스턴스(디스크 재로드)로도 결과가 그대로 남아있어야 함
        fresh_api = Api()
        got = fresh_api.get_similar_rom_groups("snes")
        self.assertTrue(got["ok"])
        self.assertEqual(len(got["data"]), 1)
        titles = {m["title"] for m in got["data"][0]["members"]}
        self.assertIn("Super Mario World", titles)
        fresh_api.close()

    def test_find_similar_roms_different_systems_never_grouped(self):
        """system이 다르면 애초에 비교 후보에도 안 들어가야 한다."""
        local_id = self._make_two_similar_games_in_masterdb()
        # 완전히 다른 system(psx)에 같은 제목의 게임을 하나 더 등록
        local_root = self.tmp / "psx로컬_ES-DE"
        (local_root / "roms" / "psx").mkdir(parents=True)
        (local_root / "meta" / "gamelists" / "psx").mkdir(parents=True)
        (local_root / "roms" / "psx" / "smw.bin").write_text("c")
        (local_root / "meta" / "gamelists" / "psx" / "gamelist.xml").write_text(
            '<gameList><game><path>./smw.bin</path><name>Super Mario World</name><desc>d</desc></game></gameList>',
            encoding="utf-8",
        )
        r2 = self.api.add_local("psx로컬", "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        self.api.import_local_to_masterdb(r2["data"]["id"])

        r = self.api.start_find_similar_roms("snes")
        job_id = r["data"]["jobId"]
        import time
        for _ in range(50):
            p = self.api.get_job_progress(job_id)
            if p["data"]["done"]:
                break
            time.sleep(0.02)
        # snes 안에서만 비교했으므로 psx 게임은 절대 섞여 들어가면 안 됨
        for g in p["data"]["result"]["groups"]:
            self.assertEqual(len(g["members"]), 2)  # snes 2개만

    def test_set_similar_group_representative_persists_and_is_enriched(self):
        """v0.5 10단계: 유사롬 그룹에 대표를 지정하면 get_similar_rom_groups()로 다시
        조회해도(새 Api 인스턴스에서도) 유지되어야 한다."""
        self._make_two_similar_games_in_masterdb()
        r = self.api.start_find_similar_roms("snes")
        job_id = r["data"]["jobId"]
        import time
        for _ in range(50):
            if self.api.get_job_progress(job_id)["data"]["done"]:
                break
            time.sleep(0.02)

        got = self.api.get_similar_rom_groups("snes")["data"]
        self.assertEqual(len(got), 1)
        group_id = got[0]["groupId"]
        # [0.4.1.x 단위 8] 탐색 직후 자동 대표 지정이 이미 채워져 있어야 한다.
        self.assertIsNotNone(got[0]["representative"])
        rep_rom_key = got[0]["members"][1]["romKey"]

        set_r = self.api.set_similar_group_representative(group_id, rep_rom_key)
        self.assertTrue(set_r["ok"], set_r.get("error"))

        fresh_api = Api()
        got2 = fresh_api.get_similar_rom_groups("snes")["data"]
        self.assertEqual(got2[0]["representative"], rep_rom_key)
        fresh_api.close()

    def test_set_similar_group_representative_rejects_non_member(self):
        self._make_two_similar_games_in_masterdb()
        r = self.api.start_find_similar_roms("snes")
        job_id = r["data"]["jobId"]
        import time
        for _ in range(50):
            if self.api.get_job_progress(job_id)["data"]["done"]:
                break
            time.sleep(0.02)
        group_id = self.api.get_similar_rom_groups("snes")["data"][0]["groupId"]
        bad = self.api.set_similar_group_representative(group_id, "snes|does-not-exist.zip")
        self.assertFalse(bad["ok"])

    # ------------------------------------------------------------------
    # v0.5 SQLite native write-path regression tests
    # ------------------------------------------------------------------
    def test_native_save_version_fields_updates_sqlite_and_json(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        vid = self.api.get_game_detail(rom_key)["data"]["versions"][0]["id"]
        fields = {"name": "SQLite 저장 테스트", "desc": "설명", "tags": ["A", "B"]}
        r = self.api.save_version_fields(rom_key, vid, fields)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(self.api._sqlite.get_rom(rom_key)["versions"][0]["fields"]["name"], "SQLite 저장 테스트")
        self.assertEqual(self.api.db["roms"][rom_key]["versions"][vid]["fields"]["tags"], ["A", "B"])

    def test_native_clone_version_is_unique_and_persisted(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        vid = self.api.get_game_detail(rom_key)["data"]["versions"][0]["id"]
        a = self.api.clone_version(rom_key, vid)
        b = self.api.clone_version(rom_key, vid)
        self.assertTrue(a["ok"] and b["ok"])
        self.assertNotEqual(a["data"]["newVersionId"], b["data"]["newVersionId"])
        self.assertEqual(len(self.api._sqlite.get_rom(rom_key)["versions"]), 3)

    def test_native_default_version_and_delete_version(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        vid = self.api.get_game_detail(rom_key)["data"]["versions"][0]["id"]
        new_id = self.api.clone_version(rom_key, vid)["data"]["newVersionId"]
        self.assertTrue(self.api.set_default_version(rom_key, new_id)["ok"])
        self.assertEqual(self.api._sqlite.get_rom(rom_key)["default_version_id"], new_id)
        self.assertTrue(self.api.delete_version(rom_key, new_id)["ok"])
        self.assertNotIn(new_id, [v["version_id"] for v in self.api._sqlite.get_rom(rom_key)["versions"]])

    def test_native_delete_last_version_is_rejected_without_mutation(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        vid = self.api.get_game_detail(rom_key)["data"]["versions"][0]["id"]
        r = self.api.delete_version(rom_key, vid)
        self.assertFalse(r["ok"])
        self.assertIsNotNone(self.api._sqlite.get_rom(rom_key))
        self.assertEqual(len(self.api._sqlite.get_rom(rom_key)["versions"]), 1)

    def test_native_media_write_updates_sqlite_and_preserves_other_media(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        payload = base64.b64encode(b"native-media").decode()
        r = self.api.save_media(rom_key, "Screenshots", payload, "native.jpg")
        self.assertTrue(r["ok"], r.get("error"))
        media = self.api._sqlite.get_rom(rom_key)["media"]
        self.assertIn("screenshots", media)
        self.assertIn("covers", media)

    def test_native_delete_masterdb_game_removes_sqlite_and_json(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        self.assertIsNotNone(self.api._sqlite.get_rom(rom_key))
        r = self.api.delete_masterdb_games([rom_key], delete_metadata=True, delete_rom=False)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertIsNone(self.api._sqlite.get_rom(rom_key))
        self.assertNotIn(rom_key, self.api.db["roms"])

    def test_delete_masterdb_games_keeps_media_when_sqlite_delete_fails(self):
        """[P1 버그 수정] 예전엔 media 파일을 먼저 지우고 그 다음 SQLite delete_rom()을
        시도했다 - SQLite 삭제가 실패하면 DB entry(JSON+SQLite)는 그대로 남는데 media만
        이미 사라져서, DB가 존재하지 않는 파일을 가리키는 상태가 될 수 있었다. 지금은
        DB 삭제를 먼저 확정한 뒤에만 media를 지우므로, SQLite 삭제가 실패하면 media도
        건드리지 않은 채 그대로 남아야 한다."""
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]

        root = Path(self.api.cfg["masterdb"]["root"])
        media_dir = root / "media" / "snes" / "게임"
        self.assertTrue(media_dir.exists())

        original_delete_rom = self.api._sqlite.delete_rom
        self.api._sqlite.delete_rom = lambda legacy_key: False
        try:
            r = self.api.delete_masterdb_games([rom_key])
        finally:
            self.api._sqlite.delete_rom = original_delete_rom

        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["data"]["metadataDeleted"], 0)
        self.assertTrue(r["data"]["errors"])
        self.assertTrue(media_dir.exists(), "SQLite 삭제 실패 시 media가 지워지면 안 됨")
        self.assertIn(rom_key, self.api.db["roms"])
        self.assertIsNotNone(self.api._sqlite.get_rom(rom_key))

    def test_native_delete_rom_only_keeps_database_record(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        system, filename = rom_key.split("|", 1)
        root = Path(self.api.cfg["masterdb"]["root"])
        rom_path = root / "roms" / system / filename
        rom_path.parent.mkdir(parents=True, exist_ok=True)
        rom_path.write_bytes(b"physical-rom")
        r = self.api.delete_masterdb_games([rom_key], delete_metadata=False, delete_rom=True)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertFalse(rom_path.exists())
        self.assertIsNotNone(self.api._sqlite.get_rom(rom_key))

    def test_native_write_unknown_version_does_not_change_data(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        before = self.api._sqlite.get_rom(rom_key)
        r = self.api.save_version_fields(rom_key, "v_missing", {"name": "bad"})
        self.assertFalse(r["ok"])
        self.assertEqual(self.api._sqlite.get_rom(rom_key), before)

    def test_native_write_with_unicode_and_empty_fields(self):
        local_id = self.make_esde_local()
        self.api.import_local_to_masterdb(local_id)
        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        vid = self.api.get_game_detail(rom_key)["data"]["versions"][0]["id"]
        fields = {"name": "한글/日本語/한국어", "desc": "", "tags": []}
        self.assertTrue(self.api.save_version_fields(rom_key, vid, fields)["ok"])
        got = self.api._sqlite.get_rom(rom_key)["versions"][0]["fields"]
        self.assertEqual(got["name"], fields["name"])
        self.assertEqual(got["tags"], [])


if __name__ == "__main__":
    unittest.main()

class TestEsdeMetadataOnlyAndLatestVersion(unittest.TestCase):
    def test_esde_metadata_only_lists_missing_rom(self):
        import tempfile
        from pathlib import Path
        from importers.scan import scan_local
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "gamelists" / "ps2").mkdir(parents=True)
            (root / "downloaded_media" / "ps2" / "covers").mkdir(parents=True)
            (root / "gamelists" / "ps2" / "gamelist.xml").write_text(
                '<gameList><game><path>./Final Fantasy VII.zip</path><name>Final Fantasy VII</name><desc>ok</desc></game></gameList>',
                encoding="utf-8")
            local = {"id":"local1", "label":"LOCAL1", "frontend":"es-de", "rom_path":"", "metadata_path":str(root), "media_path":str(root), "system_name_map":{}, "stats":{}}
            result = scan_local(local, runtime_cache={})
            self.assertEqual(len(result["rom_list"]), 0)
            self.assertIn("ps2", result["per_system"])

    def test_imported_new_version_becomes_default(self):
        import db as dbmod
        from import_engine import import_local_to_masterdb
        db = {"roms": {}}
        entry = dbmod.get_or_create_rom_entry(db, "snes", "Game.zip")
        v1 = dbmod.add_version(entry, "l1", {"name":"Wrong"}, set_as_default=True)
        v2 = dbmod.add_version(entry, "l2", {"name":"Right"}, set_as_default=True)
        self.assertEqual(entry["default_version_id"], v2)
        self.assertEqual(dbmod.get_default_fields(entry)["name"], "Right")

class JobSerializationTests(unittest.TestCase):
    """[P0 버그 수정] mutates_db=True로 실행되는 job들은 서로 겹치지 않고 항상
    하나씩만 실행되어야 한다 - 예전엔 `_save_db()`를 호출하는 순간에만 `_db_lock`을
    짧게 잡아서, 그 사이(특히 SQLite batch 트랜잭션이 열려있는 동안)에 다른 job이나
    동기 호출이 같은 sqlite3 connection을 동시에 건드릴 수 있었다.

    ApiTestCase를 상속하지 않는다 - unittest는 서브클래스가 부모의 test_* 메서드를
    전부 재실행하므로, 상속하면 이 클래스가 ApiTestCase의 테스트 전부를 중복
    실행하게 된다 (fixture만 재사용하고 싶을 뿐이었는데). 최소 fixture를 그대로
    복사해서 씀."""

    def setUp(self):
        self.tmp = Path("/tmp/test_api_suite_" + self.id().split(".")[-1])
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        self._orig_config_path = cfgmod.CONFIG_PATH
        self._orig_backup_dir = cfgmod.BACKUP_DIR
        cfgmod.CONFIG_PATH = self.tmp / "config.json"
        cfgmod.BACKUP_DIR = self.tmp / "backup"
        self.api = Api()

    def tearDown(self):
        try:
            self.api.close()
        except Exception:
            pass
        cfgmod.CONFIG_PATH = self._orig_config_path
        cfgmod.BACKUP_DIR = self._orig_backup_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_two_mutating_jobs_never_run_their_bodies_concurrently(self):
        import threading
        started = []
        job1_started = threading.Event()
        release_job1 = threading.Event()

        def job1(cb):
            started.append(("job1_start", time.time()))
            job1_started.set()
            release_job1.wait(timeout=5)
            started.append(("job1_end", time.time()))
            return "job1"

        def job2(cb):
            started.append(("job2_start", time.time()))
            return "job2"

        job_id_1 = self.api._run_job(job1, mutates_db=True)
        self.assertTrue(job1_started.wait(timeout=5), "job1이 시작되지 않음")

        # job2를 job1이 아직 실행 중인 동안 시작한다 - mutates_db=True라면 job1이
        # release될 때까지 job2의 fn 본문은 절대 실행되면 안 된다.
        job_id_2 = self.api._run_job(job2, mutates_db=True)
        time.sleep(0.2)
        self.assertEqual(
            [e for e in started if e[0] == "job2_start"], [],
            "job1이 아직 _db_lock을 쥐고 있는데 job2 본문이 이미 실행됨 - 직렬화 실패",
        )

        release_job1.set()
        for _ in range(100):
            if self.api.get_job_progress(job_id_1)["data"]["done"] and self.api.get_job_progress(job_id_2)["data"]["done"]:
                break
            time.sleep(0.02)

        job1_end = next(t for name, t in started if name == "job1_end")
        job2_start = next(t for name, t in started if name == "job2_start")
        self.assertGreaterEqual(job2_start, job1_end, "job2는 job1이 끝난 뒤에만 시작되어야 한다")

    def test_do_backup_waits_for_in_progress_mutating_job(self):
        """[P1] 리뷰에서 별도 항목으로 지적됐던 "backup과 mutation job의 동시 실행"은
        사실 P0-3에서 도입한 _db_lock 공유로 이미 해결되어 있었다 - do_backup()/
        restore_backup()은 원래부터 self._db_lock을 잡고 있었고, mutates_db=True
        job도 이제 같은 락을 전체 구간 동안 잡으므로 서로 자동으로 직렬화된다.
        새 코드 변경 없이, 그 사실을 명시적으로 검증해두는 회귀 테스트."""
        import threading
        self.api.set_masterdb_path(str(self.tmp / "masterdb"))
        job_started = threading.Event()
        release_job = threading.Event()

        def slow_job(cb):
            job_started.set()
            release_job.wait(timeout=5)
            return "done"

        self.api._run_job(slow_job, mutates_db=True)
        self.assertTrue(job_started.wait(timeout=5))

        result_holder = {}
        def call_backup():
            result_holder["result"] = self.api.do_backup()
            result_holder["finished_at"] = time.time()

        t = threading.Thread(target=call_backup)
        t.start()
        time.sleep(0.2)
        self.assertNotIn("result", result_holder, "do_backup이 job 실행 중에도 즉시 반환됨 - lock을 안 잡고 있음")

        release_job.set()
        t.join(timeout=5)
        self.assertIn("result", result_holder)
        self.assertTrue(result_holder["result"]["ok"], result_holder["result"].get("error"))

    def test_delete_masterdb_games_waits_for_in_progress_mutating_job(self):
        """delete_masterdb_games()도 같은 _db_lock을 잡아야, 실행 중인 background
        job(import 등)과 self.db/self._sqlite를 동시에 건드리지 않는다."""
        import threading
        self.api.set_masterdb_path(str(self.tmp / "masterdb"))
        job_started = threading.Event()
        release_job = threading.Event()

        def slow_job(cb):
            job_started.set()
            release_job.wait(timeout=5)
            return "done"

        self.api._run_job(slow_job, mutates_db=True)
        self.assertTrue(job_started.wait(timeout=5))

        result_holder = {}
        def call_delete():
            result_holder["result"] = self.api.delete_masterdb_games(["snes|NoSuchRom.zip"])
            result_holder["finished_at"] = time.time()

        t = threading.Thread(target=call_delete)
        t.start()
        time.sleep(0.2)
        self.assertNotIn("result", result_holder, "delete_masterdb_games가 job 실행 중에도 즉시 반환됨 - lock을 안 잡고 있음")

        release_job.set()
        t.join(timeout=5)
        self.assertIn("result", result_holder)
        self.assertTrue(result_holder["result"]["ok"])

    def test_two_local_scans_never_run_concurrently(self):
        """[크래시 리포트 반영] 사용자가 실제로 "Local1을 스캔 중일 때 Local2를
        불러오니 앱이 강제종료됨"을 재현했다. start_scan_local()이 mutates_db=False라
        _db_lock을 안 쓰고 있었고, 서로 다른 Local의 스캔은 완전히 독립된 백그라운드
        스레드에서 동시에 돌 수 있었다 - 두 스캔이 파일시스템/이미지 처리를 동시에
        겹쳐 돌리며 리소스를 과하게 소모하는 것으로 의심된다. Scan끼리만 직렬화하는
        _scan_lock을 추가했고, 여기서는 실제로 두 스캔의 본문이 절대 겹치지 않는지
        확인한다(정확한 네이티브 크래시 재현은 이 sandbox에서 불가능 - Windows
        pywebview 실기 확인 필요)."""
        import threading
        from unittest.mock import patch

        local1_root = self.tmp / "local1_ES-DE"
        (local1_root / "roms" / "snes").mkdir(parents=True)
        (local1_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        r1 = self.api.add_local("Local1", "ES-DE", str(local1_root / "roms"), str(local1_root / "meta"))
        self.assertTrue(r1["ok"], r1.get("error"))
        local2_root = self.tmp / "local2_ES-DE"
        (local2_root / "roms" / "snes").mkdir(parents=True)
        (local2_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        r2 = self.api.add_local("Local2", "ES-DE", str(local2_root / "roms"), str(local2_root / "meta"))
        self.assertTrue(r2["ok"], r2.get("error"))

        # [체감 속도, Scan 2단계] start_scan_local()이 이제 Local당 self.scan_local()을
        # 2번(커버 phase + 나머지 phase) 부르므로, fake는 media_types kwarg도 받아야
        # 하고, 검증도 "Local1 전체가 끝난 뒤에만 Local2가 시작"이 아니라 "어떤 두
        # 호출도 절대 겹치지 않는다"는 더 일반적인 형태로 바꾼다 - _scan_lock이
        # phase 단위로 걸리므로 Local1의 phase2와 Local2의 phase1이 서로 경합할 수
        # 있고, 그 경우에도 겹치지만 않으면(직렬화만 되면) 정상이다.
        started = []
        scan1_first_call_started = threading.Event()
        release_scan1_first_call = threading.Event()
        lock = threading.Lock()

        def fake_scan_local(local_id, progress_cb=None, read_media_types=None):
            with lock:
                started.append((local_id, read_media_types, "start", time.time()))
            if local_id == r1["data"]["id"] and not scan1_first_call_started.is_set():
                scan1_first_call_started.set()
                release_scan1_first_call.wait(timeout=5)
            with lock:
                started.append((local_id, read_media_types, "end", time.time()))
            return {"ok": True, "data": {"stats": {}, "status": "정상", "games": [], "notImplemented": False}}

        with patch.object(self.api, "scan_local", side_effect=fake_scan_local):
            job1 = self.api.start_scan_local(r1["data"]["id"])
            self.assertTrue(job1["ok"], job1.get("error"))
            self.assertTrue(scan1_first_call_started.wait(timeout=5), "Local1 스캔이 시작되지 않음")

            job2 = self.api.start_scan_local(r2["data"]["id"])
            self.assertTrue(job2["ok"], job2.get("error"))
            time.sleep(0.2)
            self.assertEqual(
                [e for e in started if e[0] == r2["data"]["id"]], [],
                "Local1 스캔이 아직 끝나지 않았는데 Local2 스캔이 이미 시작됨 - 직렬화 실패",
            )

            release_scan1_first_call.set()
            # 두 Local 모두 phase1+phase2가 끝날 때까지(= busy가 완전히 풀릴 때까지) 대기.
            for _ in range(300):
                with self.api._busy_lock:
                    if r1["data"]["id"] not in self.api._busy_targets and r2["data"]["id"] not in self.api._busy_targets:
                        break
                time.sleep(0.02)

        # 어떤 두 호출(local/phase 무관)도 시간 구간이 겹치면 안 된다 - _scan_lock이
        # 제대로 전체를 직렬화하고 있는지 일반적으로 검증.
        intervals = []
        starts = {}
        for lid, mt, ev, t in started:
            key = (lid, id(mt) if mt is None else tuple(mt))
            if ev == "start":
                starts.setdefault(lid, []).append(t)
            else:
                s = starts[lid].pop(0)
                intervals.append((s, t))
        intervals.sort()
        for (s1, e1), (s2, e2) in zip(intervals, intervals[1:]):
            self.assertLessEqual(e1, s2, "두 scan_local() 호출의 시간 구간이 겹침 - 직렬화 실패")
        self.assertGreaterEqual(len(intervals), 4, f"Local당 2phase씩 최소 4번 호출돼야 하는데 {len(intervals)}번: {started}")

    # ------------------------------------------------------------------
    # [체감 속도] videos는 1차 패스에서 빼고 2차(지연) job으로 따로 처리한다.
    # ------------------------------------------------------------------
    def test_split_media_for_deferred_video_defaults_on(self):
        primary, deferred = self.api._split_media_for_deferred_video(None)
        self.assertNotIn("videos", primary)
        self.assertEqual(deferred, ["videos"])

    def test_split_media_for_deferred_video_off_keeps_everything_together(self):
        self.api.cfg.setdefault("performance", {})["defer_video_media"] = False
        primary, deferred = self.api._split_media_for_deferred_video(None)
        self.assertIsNone(primary)
        self.assertIsNone(deferred)

    def test_split_media_for_deferred_video_respects_explicit_selection_without_videos(self):
        """사용자가 대화상자에서 이미 "커버만"처럼 videos 없이 명시적으로 선택했다면
        지연시킬 게 없으므로 그 선택을 그대로 존중해야 한다."""
        primary, deferred = self.api._split_media_for_deferred_video(["covers"])
        self.assertEqual(primary, ["covers"])
        self.assertIsNone(deferred)

    def test_start_media_job_keeps_target_busy_until_deferred_pass_finishes(self):
        import threading
        release_video = threading.Event()
        video_started = threading.Event()

        def run_primary(cb):
            return "primary-done"

        def make_deferred_run():
            def run_videos(cb):
                video_started.set()
                release_video.wait(timeout=5)
                return "videos-done"
            return run_videos

        job_id = self.api._start_media_job(("local-x",), run_primary, make_deferred_run, mutates_db=False)
        for _ in range(100):
            if self.api.get_job_progress(job_id)["data"]["done"]:
                break
            time.sleep(0.02)
        # [핵심] 1차 job은 끝났지만 2차(비디오) job이 아직 안 끝났으므로 target은 계속 busy여야 한다.
        self.assertTrue(video_started.wait(timeout=5))
        self.assertIsNotNone(self.api._target_busy_error("local-x"), "2차(비디오) job이 진행 중인데 target이 busy로 안 잡혀 있음")

        release_video.set()
        for _ in range(100):
            with self.api._busy_lock:
                if "local-x" not in self.api._busy_targets:
                    break
            time.sleep(0.02)
        self.assertIsNone(self.api._target_busy_error("local-x"), "2차 job이 끝났는데도 busy가 안 풀림")

    def test_start_media_job_releases_busy_immediately_when_nothing_deferred(self):
        job_id = self.api._start_media_job(("local-y",), lambda cb: "ok", None, mutates_db=False)
        for _ in range(100):
            if self.api.get_job_progress(job_id)["data"]["done"]:
                break
            time.sleep(0.02)
        self.assertIsNone(self.api._target_busy_error("local-y"))

    def test_start_media_job_skips_deferred_pass_when_primary_fails(self):
        """[리뷰 반영] 1차가 예외로 실패했으면 2차(비디오)는 아예 돌면 안 된다 -
        예전엔 finally에서 무조건 2차를 띄워서, 예를 들어 SQLite 오류로 1차 import
        자체가 실패했는데도 videos만 따로 복사를 시도했다. 또한 1차의 예외가 job
        결과에 그대로 에러로 기록되는지도 함께 확인한다."""
        deferred_started = []

        def run_primary(cb):
            raise RuntimeError("primary boom")

        def make_deferred_run():
            def run_videos(cb):
                deferred_started.append(True)
                return "videos-done"
            return run_videos

        job_id = self.api._start_media_job(("local-z",), run_primary, make_deferred_run, mutates_db=False)
        for _ in range(100):
            if self.api.get_job_progress(job_id)["data"]["done"]:
                break
            time.sleep(0.02)

        self.assertEqual(deferred_started, [], "1차가 실패했는데 2차(비디오) job이 시작됨")
        self.assertIn("primary boom", self.api.get_job_progress(job_id)["data"]["error"] or "")
        # 1차가 실패해도 busy는 즉시 풀려야 한다(2차가 안 도니까).
        self.assertIsNone(self.api._target_busy_error("local-z"))

    def test_import_defers_video_via_two_passes_then_allows_delete(self):
        """[통합] 실제 import job이 covers/videos를 정확히 두 번(1차: videos 제외,
        2차: videos만)에 걸쳐 나눠 호출하는지, 그리고 두 패스가 모두 끝난 뒤에는
        최종적으로 covers+videos가 다 채워지고 삭제도 다시 허용되는지 검증한다.
        (busy-lock이 2차 job이 끝날 때까지 유지되는지는 타이밍을 직접 제어할 수 있는
        test_start_media_job_keeps_target_busy_until_deferred_pass_finishes에서
        결정적으로 검증한다 - 이 테스트의 실제 fixture는 너무 작아 1차/2차가 거의
        동시에 끝나버려서 "아직 busy"인 순간을 안정적으로 붙잡을 수 없다.)"""
        local_root = self.tmp / "video_local_ES-DE"
        (local_root / "roms" / "snes").mkdir(parents=True)
        (local_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (local_root / "meta" / "downloaded_media" / "snes" / "covers").mkdir(parents=True)
        (local_root / "meta" / "downloaded_media" / "snes" / "videos").mkdir(parents=True)
        (local_root / "roms" / "snes" / "game.zip").write_text("dummy")
        (local_root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            '<gameList><game><path>./game.zip</path><name>Game</name><desc>d</desc></game></gameList>',
            encoding="utf-8",
        )
        (local_root / "meta" / "downloaded_media" / "snes" / "covers" / "game.png").write_bytes(b"COVER")
        (local_root / "meta" / "downloaded_media" / "snes" / "videos" / "game.mp4").write_bytes(b"VIDEO")

        self.api.set_masterdb_path(str(self.tmp / "masterdb"))
        r = self.api.add_local("VideoLocal", "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        self.assertTrue(r["ok"], r.get("error"))
        local_id = r["data"]["id"]

        # [타이밍 안정성] 테스트 fixture가 아주 작아서 1차/2차 job이 눈 깜짝할 새
        # 둘 다 끝날 수 있다 - "1차 완료 시점에 videos가 아직 없다"를 직접 타이밍으로
        # 검증하는 대신, import_local_to_masterdb에 실제로 전달되는 selected_media_types가
        # 1차엔 videos 없이, 2차엔 videos만으로 호출되는지 spy로 확인한다(핵심 동작
        # 자체는 이렇게 결정적으로 검증하고, busy-lock 유지는 위 mock 기반 단위
        # 테스트에서 이미 확인했다).
        from unittest.mock import patch
        import import_engine
        original_import = import_engine.import_local_to_masterdb
        calls = []

        def spy_import(*args, **kwargs):
            calls.append(kwargs.get("selected_media_types"))
            return original_import(*args, **kwargs)

        with patch("api.import_local_to_masterdb", side_effect=spy_import):
            r = self.api.start_import_local_to_masterdb(local_id)
            self.assertTrue(r["ok"], r.get("error"))
            job_id = r["data"]["jobId"]
            for _ in range(100):
                if self.api.get_job_progress(job_id)["data"]["done"]:
                    break
                time.sleep(0.02)
            self.assertIsNone(self.api.get_job_progress(job_id)["data"]["error"])

            for _ in range(200):
                with self.api._busy_lock:
                    if local_id not in self.api._busy_targets and "masterdb" not in self.api._busy_targets:
                        break
                time.sleep(0.02)

        # 1차는 videos 없이, 2차는 videos만으로 호출됐어야 한다.
        self.assertEqual(len(calls), 2, f"1차+2차 총 2번 호출돼야 하는데 {len(calls)}번 호출됨: {calls}")
        self.assertNotIn("videos", calls[0] or [])
        self.assertEqual(calls[1], ["videos"])

        rom_key = self.api.list_masterdb_games()["data"][0]["romKey"]
        detail_final = self.api.get_game_detail(rom_key)["data"]
        self.assertIn("Covers", detail_final["media"])
        self.assertEqual(detail_final["media"].get("Videos"), "video://exists", "2차 job이 끝났으면 videos도 채워져 있어야 한다")

        # busy가 풀렸으니 이제는 삭제가 다시 허용되어야 한다(실제로 지운다).
        r_del = self.api.delete_masterdb_games([rom_key])
        self.assertTrue(r_del["ok"], r_del.get("error"))

    # ------------------------------------------------------------------
    # [Queue 구조] Scan/Import/Export는 _run_heavy_job()의 명시적 FIFO 큐를 통해서만
    # 실행된다 - 실행 중인 heavy job worker thread는 항상 최대 1개고, 나머지는
    # self._jobs에 queued=True 상태로 남아 몇 번째로 대기 중인지가 label에 보인다.
    # ------------------------------------------------------------------
    def test_second_heavy_job_stays_queued_with_no_worker_thread_until_first_finishes(self):
        import threading
        started = []
        release_first = threading.Event()

        def slow_job(cb):
            started.append("first")
            release_first.wait(timeout=5)
            return "first-done"

        def quick_job(cb):
            started.append("second")
            return "second-done"

        job1 = self.api._run_heavy_job(slow_job, mutates_db=False, kind="scan")
        for _ in range(100):
            if "first" in started:
                break
            time.sleep(0.02)
        self.assertIn("first", started)

        job2 = self.api._run_heavy_job(quick_job, mutates_db=False, kind="scan")
        # job2는 아직 queued 상태여야 하고, worker thread 자체가 없으니 fn이 아직
        # 호출되면 안 된다.
        time.sleep(0.2)
        p2 = self.api.get_job_progress(job2)["data"]
        self.assertTrue(p2.get("queued"), p2)
        self.assertFalse(p2["done"])
        self.assertNotIn("second", started, "1차 heavy job이 아직 안 끝났는데 2차가 이미 실행됨 - 큐가 안 지켜짐")

        release_first.set()
        for _ in range(100):
            if self.api.get_job_progress(job2)["data"]["done"]:
                break
            time.sleep(0.02)

        self.assertEqual(started, ["first", "second"], "2차는 1차가 끝난 뒤에만 실행돼야 한다")
        p1 = self.api.get_job_progress(job1)["data"]
        self.assertEqual(p1["result"], "first-done")
        p2 = self.api.get_job_progress(job2)["data"]
        self.assertFalse(p2.get("queued", False), "실행이 끝났으면 더 이상 queued가 아니어야 한다")
        self.assertEqual(p2["result"], "second-done")

    def test_heavy_job_queue_serializes_scan_across_different_locals_but_not_export(self):
        import threading
        """[하이브리드 범위 축소] Scan끼리는 서로 다른 Local이라도 여전히 전역으로
        직렬화한다(원래 크래시 재현 조건이었기 때문 - kind="scan"). 반면 Export는
        대상(target_ids)이 실제로 겹치지 않는 한 Scan이 도는 중이라도 동시에 실행될
        수 있어야 한다(item 14의 범위를 "같은 대상"으로 좁힌 결과)."""
        started = []
        release_scan = threading.Event()

        def slow_scan(cb):
            started.append(("scanA", "start"))
            release_scan.wait(timeout=5)
            started.append(("scanA", "end"))
            return "scan-done"

        def export_b(cb):
            started.append(("exportB", "start"))
            return "export-done"

        scan_job = self.api._run_heavy_job(slow_scan, mutates_db=False, target_ids=("localA",), kind="scan")
        for _ in range(100):
            if ("scanA", "start") in started:
                break
            time.sleep(0.02)

        export_job = self.api._run_heavy_job(export_b, mutates_db=True, target_ids=("localB",), kind="other")
        for _ in range(100):
            if self.api.get_job_progress(export_job)["data"]["done"]:
                break
            time.sleep(0.02)

        self.assertIn(
            ("exportB", "start"), started,
            "서로 다른 대상(Local A Scan vs Local B Export)인데도 Export가 Scan이 끝날 때까지 막혀 있음",
        )
        release_scan.set()
        for _ in range(100):
            if self.api.get_job_progress(scan_job)["data"]["done"]:
                break
            time.sleep(0.02)

    def test_heavy_job_queue_still_serializes_same_target_non_scan_jobs(self):
        import threading
        """[하이브리드 범위 축소] Scan이 아니더라도(Export/Import), 같은 대상(target_ids
        가 겹침)이면 여전히 직렬화되어야 한다 - 범위를 좁힌 건 "다른 대상"에 대해서만."""
        started = []
        release_first = threading.Event()

        def slow_export(cb):
            started.append(("exportA", "start"))
            release_first.wait(timeout=5)
            started.append(("exportA", "end"))
            return "export-done"

        def import_a(cb):
            started.append(("importA", "start"))
            return "import-done"

        job1 = self.api._run_heavy_job(slow_export, mutates_db=True, target_ids=("localA",), kind="other")
        for _ in range(100):
            if ("exportA", "start") in started:
                break
            time.sleep(0.02)

        job2 = self.api._run_heavy_job(import_a, mutates_db=True, target_ids=("localA",), kind="other")
        time.sleep(0.2)
        self.assertEqual(
            [e for e in started if e[0] == "importA"], [],
            "같은 대상(localA)인데 Export가 안 끝났는데 Import가 이미 시작됨 - 같은 대상 직렬화 실패",
        )

        release_first.set()
        for _ in range(100):
            if self.api.get_job_progress(job2)["data"]["done"]:
                break
            time.sleep(0.02)

        self.assertEqual(
            [e[0] for e in started], ["exportA", "exportA", "importA"],
            f"같은 대상의 Import는 Export가 끝난 뒤에만 시작되어야 한다: {started}",
        )

    def test_update_local_paths_blocked_while_local_busy(self):
        """[P0-6] Scan/Import/Export가 진행 중인 Local의 경로를 바꾸면, 아직 안
        끝난 phase가 이전/이후 경로가 섞인 상태로 파일을 읽을 수 있다 -
        Delete/Rename과 동일하게 busy 동안은 막아야 한다."""
        self.api.set_masterdb_path(str(self.tmp / "masterdb"))
        r = self.api.add_local("로컬1", "ES-DE", str(self.tmp / "roms"), str(self.tmp / "meta"))
        self.assertTrue(r["ok"], r.get("error"))
        local_id = r["data"]["id"]
        with self.api._busy_lock:
            self.api._busy_targets.add(local_id)
        try:
            r = self.api.update_local_paths(local_id, "/tmp/new_rom", "/tmp/new_meta")
            self.assertFalse(r["ok"], "Local이 busy인데 경로 변경이 그대로 허용됨")
        finally:
            with self.api._busy_lock:
                self.api._busy_targets.discard(local_id)
        r2 = self.api.update_local_paths(local_id, "/tmp/new_rom", "/tmp/new_meta")
        self.assertTrue(r2["ok"], "busy가 풀린 뒤에도 경로 변경이 막힘")

    def test_set_masterdb_path_and_restore_backup_blocked_while_masterdb_busy(self):
        """[P0-7] Import/Export처럼 self.db/self._sqlite를 사용 중인 job이
        "masterdb"를 busy로 잡고 있는 동안 set_masterdb_path()/restore_backup()이
        그 객체를 통째로 교체하면 worker가 마저 쓰던 DB가 도중에 바뀔 수 있다."""
        self.api.set_masterdb_path(str(self.tmp / "masterdb"))
        with self.api._busy_lock:
            self.api._busy_targets.add("masterdb")
        try:
            r1 = self.api.set_masterdb_path(str(self.tmp / "masterdb2"))
            self.assertFalse(r1["ok"], "masterdb가 busy인데 set_masterdb_path가 그대로 허용됨")
            r2 = self.api.restore_backup("nonexistent.zip")
            self.assertFalse(r2["ok"], "masterdb가 busy인데 restore_backup이 그대로 허용됨")
        finally:
            with self.api._busy_lock:
                self.api._busy_targets.discard("masterdb")
        r3 = self.api.set_masterdb_path(str(self.tmp / "masterdb2"))
        self.assertTrue(r3["ok"], "busy가 풀린 뒤에도 set_masterdb_path가 막힘")

    def test_metadata_edit_blocked_while_import_or_export_busy_but_allowed_during_scan(self):
        """[P1-3] Scan은 read-only이므로 Metadata/Media 편집을 계속 허용해야
        하지만(디스크가 항상 최종 진실 - pending_edits_during_scan으로 안전하게 재적용),
        Import/Export는 실제로 그 Local의 metadata/media 파일을 읽거나 쓰므로
        동시 편집을 허용하면 마지막 write가 서로 덮어쓸 수 있다 - 편집 자체를
        막아야 한다. kind만 다르게 busy_target_kind에 직접 표시해서 두 경우를
        모두 검증한다."""
        self.api.set_masterdb_path(str(self.tmp / "masterdb"))
        r = self.api.add_local("로컬1", "ES-DE", str(self.tmp / "roms"), str(self.tmp / "meta"))
        self.assertTrue(r["ok"], r.get("error"))
        local_id = r["data"]["id"]

        with self.api._busy_lock:
            self.api._busy_targets.add(local_id)
            self.api._busy_target_kind[local_id] = "other"  # Import/Export
        try:
            r1 = self.api.save_local_game_fields(local_id, "snes|game.zip", {"name": "x"})
            self.assertFalse(r1["ok"], "Import/Export 진행 중인데 metadata 편집이 그대로 허용됨")
            r2 = self.api.save_local_media(local_id, "snes|game.zip", "Cover", "", "x.png")
            self.assertFalse(r2["ok"], "Import/Export 진행 중인데 media 편집이 그대로 허용됨")
        finally:
            with self.api._busy_lock:
                self.api._busy_targets.discard(local_id)
                self.api._busy_target_kind.pop(local_id, None)

        with self.api._busy_lock:
            self.api._busy_targets.add(local_id)
            self.api._busy_target_kind[local_id] = "scan"
        try:
            r3 = self.api._metadata_edit_busy_error(local_id)
            self.assertIsNone(r3, "Scan 진행 중인데 metadata 편집 자체가 막힘 - Scan은 read-only라 허용돼야 함")
        finally:
            with self.api._busy_lock:
                self.api._busy_targets.discard(local_id)
                self.api._busy_target_kind.pop(local_id, None)

    def test_completed_jobs_older_than_ttl_are_pruned_on_next_job_start(self):
        """[P1-4] 완료된 job(특히 Scan 결과처럼 큰 result를 담은 job)이 아무도
        다시 조회하지 않는 채로 self._jobs에 무기한 남아있으면 안 된다. 새 job이
        시작될 때마다 기회적으로 오래된(완료된 지 TTL을 넘긴) job을 정리하는지
        확인한다."""
        job_id = self.api._run_job(lambda cb: "old-result", mutates_db=False)
        for _ in range(100):
            if self.api.get_job_progress(job_id)["data"]["done"]:
                break
            time.sleep(0.02)
        self.assertIn(job_id, self.api._jobs)

        # TTL을 이미 넘긴 것처럼 done_at을 과거로 조작한다.
        self.api._jobs[job_id]["done_at"] = time.time() - self.api._JOB_TTL_SECONDS - 1

        # 아직 정리되지 않았어야 한다(새 job이 시작돼야 기회적으로 정리됨).
        self.assertIn(job_id, self.api._jobs)

        # 새 job을 하나 더 시작하면 그 시점에 오래된 job이 정리돼야 한다.
        job_id2 = self.api._run_job(lambda cb: "new-result", mutates_db=False)
        self.assertNotIn(job_id, self.api._jobs, "TTL을 넘긴 완료 job이 새 job 시작 시점에 정리되지 않음")
        self.assertIn(job_id2, self.api._jobs)

    def test_cancel_queued_heavy_job_removes_it_without_ever_running(self):
        import threading
        started = []
        release_first = threading.Event()

        def slow_job(cb):
            started.append("first")
            release_first.wait(timeout=5)
            return "first-done"

        def never_run(cb):
            started.append("second-should-not-run")
            return "second-done"

        job1 = self.api._run_heavy_job(slow_job, mutates_db=False, kind="scan")
        for _ in range(100):
            if "first" in started:
                break
            time.sleep(0.02)

        job2 = self.api._run_heavy_job(never_run, mutates_db=False, kind="scan")
        time.sleep(0.1)
        self.assertTrue(self.api.get_job_progress(job2)["data"].get("queued"))

        cancel_r = self.api.cancel_job(job2)
        self.assertTrue(cancel_r["ok"], cancel_r.get("error"))
        p2 = self.api.get_job_progress(job2)["data"]
        self.assertTrue(p2["done"])
        self.assertTrue(p2["cancelled"])

        release_first.set()
        for _ in range(100):
            if self.api.get_job_progress(job1)["data"]["done"]:
                break
            time.sleep(0.02)
        time.sleep(0.1)
        self.assertNotIn("second-should-not-run", started, "취소된 queued job의 fn이 실제로 실행됨")

    def test_cancel_queued_heavy_job_releases_busy_target(self):
        import threading
        """[P0-5] _start_phased_media_job()은 phase 0이 시작되기 전에 이미
        target을 busy로 예약해둔다. 그 job이 아직 queued 상태에서 취소되면
        fn(및 마지막 phase의 release())이 한 번도 안 불리므로, 예전엔
        busy_targets에 target이 영구히 남아 이후 Delete/Rename까지 계속
        막힐 수 있었다. 취소 시 target이 반드시 풀려야 하고, 그 뒤엔
        Delete/Rename 계열 작업이 다시 가능해야 한다."""
        release_first = threading.Event()
        started = []

        def slow_job(cb):
            started.append("first")
            release_first.wait(timeout=5)
            return "first-done"

        def never_run(cb):
            started.append("second-should-not-run")
            return "second-done"

        # 첫 번째 heavy job이 "localX"를 점유한 채로 실행 중이게 만든다.
        job1 = self.api._run_heavy_job(slow_job, mutates_db=False, target_ids=("localX",), kind="scan")
        for _ in range(100):
            if "first" in started:
                break
            time.sleep(0.02)

        # _start_phased_media_job()과 동일하게, phase가 시작되기 전에 미리
        # busy_targets를 예약해둔 뒤 큐에 들어가는 job을 만든다.
        with self.api._busy_lock:
            self.api._busy_targets.add("localX")
        job2 = self.api._run_heavy_job(never_run, mutates_db=False, target_ids=("localX",), kind="scan")
        time.sleep(0.1)
        self.assertTrue(self.api.get_job_progress(job2)["data"].get("queued"))
        self.assertIn("localX", self.api._busy_targets)

        cancel_r = self.api.cancel_job(job2)
        self.assertTrue(cancel_r["ok"], cancel_r.get("error"))
        p2 = self.api.get_job_progress(job2)["data"]
        self.assertTrue(p2["done"])
        self.assertTrue(p2["cancelled"])

        self.assertNotIn("localX", self.api._busy_targets,
                          "queued job을 취소했는데 busy_targets에 target이 영구 잔류함")
        busy_err = self.api._target_busy_error("localX")
        self.assertIsNone(busy_err, "취소 이후에도 target이 busy로 남아 Delete/Rename이 계속 막힘")

        release_first.set()
        for _ in range(100):
            if self.api.get_job_progress(job1)["data"]["done"]:
                break
            time.sleep(0.02)


class DbRollbackGuardTests(unittest.TestCase):
    """[P0 후속 수정, PR #1 리뷰] SQLite는 batch()의 `with` 덕분에 예외 시 정확히
    rollback되지만, self.db는 평범한 Python dict라 import 도중 예외가 나도 이미
    mutate된 상태가 그대로 남을 수 있었다(Api._db_rollback_guard 추가 전). 여기서는
    Api.import_local_to_masterdb()가 실패한 뒤 self.db["roms"]가 SQLite와 동일하게
    깨끗이 원복되는지, 그리고 재시도가 "이미 있는 걸로 착각"하지 않고 정상적으로
    끝까지 성공하는지 검증한다.

    ApiTestCase를 상속하지 않는다 - unittest는 서브클래스가 부모의 test_* 메서드를
    전부 재실행하므로, 상속하면 이 클래스가 ApiTestCase의 테스트 전부를 중복
    실행하게 된다. 최소 fixture를 그대로 복사해서 씀."""

    def setUp(self):
        self.tmp = Path("/tmp/test_api_suite_" + self.id().split(".")[-1])
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        self._orig_config_path = cfgmod.CONFIG_PATH
        self._orig_backup_dir = cfgmod.BACKUP_DIR
        cfgmod.CONFIG_PATH = self.tmp / "config.json"
        cfgmod.BACKUP_DIR = self.tmp / "backup"
        self.api = Api()

    def tearDown(self):
        try:
            self.api.close()
        except Exception:
            pass
        cfgmod.CONFIG_PATH = self._orig_config_path
        cfgmod.BACKUP_DIR = self._orig_backup_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_esde_local_with_two_roms(self):
        masterdb_root = str(self.tmp / "masterdb")
        r = self.api.set_masterdb_path(masterdb_root)
        self.assertTrue(r["ok"])

        local_root = self.tmp / "로컬1_ES-DE"
        (local_root / "roms" / "snes").mkdir(parents=True)
        (local_root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (local_root / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (local_root / "roms" / "snes" / "Zelda.zip").write_text("dummy")
        (local_root / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList>"
            "<game><path>./Mario.zip</path><name>Mario</name><desc>A</desc></game>"
            "<game><path>./Zelda.zip</path><name>Zelda</name><desc>B</desc></game>"
            "</gameList>"
        )
        r = self.api.add_local("로컬1", "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        self.assertTrue(r["ok"], r.get("error"))
        return r["data"]["id"]

    def test_failed_import_leaves_self_db_unchanged_and_retry_succeeds(self):
        local_id = self._make_esde_local_with_two_roms()

        original_add_version = dbmod.add_version

        def boom(rom_entry, *args, **kwargs):
            if rom_entry.get("rom_filename") == "Zelda.zip":
                raise RuntimeError("simulated unexpected failure mid-import")
            return original_add_version(rom_entry, *args, **kwargs)

        dbmod.add_version = boom
        try:
            r = self.api.import_local_to_masterdb(local_id)
        finally:
            dbmod.add_version = original_add_version

        self.assertFalse(r["ok"])
        # self.db["roms"]는 SQLite와 마찬가지로 아무것도 반영되지 않은 상태로
        # 남아야 한다 - _db_rollback_guard가 없으면 Mario는 이미 add_version 전에
        # get_or_create_rom_entry로 self.db["roms"]에 삽입돼 있어서 여기 남는다.
        self.assertEqual(self.api.db.get("roms", {}), {}, "실패한 import의 부분 mutation이 self.db에 남아있으면 안 됨")

        # 무관한 다른 작업이 _save_db()를 호출해도(예: 다음 import) stale 데이터가
        # 되살아나지 않아야 한다 - 재시도가 정상적으로 처음부터 끝까지 성공해야 함.
        retry = self.api.import_local_to_masterdb(local_id)
        self.assertTrue(retry["ok"], retry.get("error"))
        self.assertEqual(retry["data"]["imported"], 2)
        games = self.api.list_masterdb_games()["data"]
        self.assertEqual(len(games), 2)


class AliasMergeSqliteResyncTests(unittest.TestCase):
    """[버그 수정, 2026-09-02] import_local_to_masterdb 계열 api.py 메서드들이
    `self._save_db(sync_sqlite=not result.get("alias_merge_occurred", False))`처럼
    `not`이 반대로 붙어있어서, 정확히 alias 시스템명 병합이 일어난 회차에만 SQLite
    재동기화를 건너뛰고 있었다 - import_engine.py가 문서화한 계약("alias 병합이
    일어난 rom은 native mirror 대신 호출자가 반드시 전체 replace_from_dict()로
    재동기화해야 함")과 정반대였다. 결과적으로 self.db(JSON)에는 병합된 canonical
    ROM이 들어가지만 self._sqlite에는 반영되지 않아서, list_masterdb_games()
    (SQLite 기반)에서 그 ROM이 안 보이는데 get_masterdb_info()의 romCount(JSON
    기반)는 정상으로 뜨는 - "ArchiveDB 목록은 비어있는데 전체 개수는 맞다"는
    실사용 리포트로 이어졌다.

    ApiTestCase를 상속하지 않는다(DbRollbackGuardTests와 동일한 이유 - 상속하면
    unittest가 부모의 test_* 전부를 중복 실행한다)."""

    def setUp(self):
        self.tmp = Path("/tmp/test_api_suite_" + self.id().split(".")[-1])
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        self._orig_config_path = cfgmod.CONFIG_PATH
        self._orig_backup_dir = cfgmod.BACKUP_DIR
        cfgmod.CONFIG_PATH = self.tmp / "config.json"
        cfgmod.BACKUP_DIR = self.tmp / "backup"
        self.api = Api()

    def tearDown(self):
        try:
            self.api.close()
        except Exception:
            pass
        cfgmod.CONFIG_PATH = self._orig_config_path
        cfgmod.BACKUP_DIR = self._orig_backup_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_alias_merge_import_stays_visible_in_sqlite_backed_list(self):
        masterdb_root = str(self.tmp / "masterdb")
        r = self.api.set_masterdb_path(masterdb_root)
        self.assertTrue(r["ok"], r.get("error"))

        # 레거시 alias 키("genesis")로 이미 저장된 entry를 미리 심어둔다 - canonical화
        # 이전 버전에서 import된 것처럼. _save_db()(기본 sync_sqlite=True)로 SQLite에도
        # 반영해 "이미 SQLite에 있던 entry가 alias 병합으로 canonical 키로 옮겨간다"는
        # 실제 상황을 재현한다.
        self.api.db["roms"]["genesis|Sonic.zip"] = {
            "system": "genesis", "rom_filename": "Sonic.zip", "default_version_id": "v_old",
            "core_override": None,
            "versions": {"v_old": {"created_at": "", "source_local_id": "x", "fields": {"name": "Sonic (old)"}}},
            "media": {},
        }
        self.api._save_db()
        self.assertIsNotNone(self.api._sqlite.get_rom("genesis|Sonic.zip"))

        local_root = self.tmp / "로컬1_ES-DE"
        (local_root / "roms" / "megadrive").mkdir(parents=True)
        (local_root / "meta" / "gamelists" / "megadrive").mkdir(parents=True)
        (local_root / "roms" / "megadrive" / "Sonic.zip").write_text("dummy")
        (local_root / "meta" / "gamelists" / "megadrive" / "gamelist.xml").write_text(
            "<gameList><game><path>./Sonic.zip</path><name>Sonic</name><desc>Fast</desc></game></gameList>"
        )
        r = self.api.add_local("로컬1", "ES-DE", str(local_root / "roms"), str(local_root / "meta"))
        self.assertTrue(r["ok"], r.get("error"))
        local_id = r["data"]["id"]

        result = self.api.import_local_to_masterdb(local_id)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["data"]["alias_merge_occurred"])

        # JSON(self.db) 쪽은 버그가 있어도 항상 정확했다 - 이 assert만으로는 버그를 못 잡는다.
        self.assertIn("megadrive|Sonic.zip", self.api.db["roms"])
        self.assertNotIn("genesis|Sonic.zip", self.api.db["roms"])

        # 진짜 회귀 포인트: list_masterdb_games()는 SQLite만 읽는다 - 재동기화가
        # 빠졌다면(고치기 전 버그) 병합된 ROM이 여기서 안 보이거나 예전 alias 키가
        # 유령처럼 남아있다.
        games = self.api.list_masterdb_games()["data"]
        keys = {g["romKey"] for g in games}
        self.assertIn("megadrive|Sonic.zip", keys)
        self.assertNotIn("genesis|Sonic.zip", keys)


class TestRomanNumeralFilenameMatching(unittest.TestCase):
    def test_arabic_and_roman_sequel_numbers_match(self):
        from utils import normalize_rom_match_title
        self.assertEqual(normalize_rom_match_title("Game VII (J).zip"), normalize_rom_match_title("Game 7 (K).zip"))
        self.assertEqual(normalize_rom_match_title("Game XXX.zip"), normalize_rom_match_title("Game 30.zip"))
