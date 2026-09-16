"""빈 System 삭제와 System 폴더 열기.

게임이 있는 System은 절대 지우지 않고, Collection/Storage root나 이름이 다른 공용
폴더도 남긴다(app/system_ops.py).
"""

import unittest
from pathlib import Path
from unittest import mock

import bridge.api as bridge_api
from bridge.api import Api
from tests.fixtures import build_esde_tree, temp_root, wait_job, write_file


def add_empty_system(root: Path, name="gba"):
    """ES-DE가 만들어 두는 모양의 빈 System - 안내 파일, 게임 없는 gamelist, 빈 media 폴더."""
    write_file(root / name / "systeminfo.txt", b"info")
    write_file(root / "gamelists" / name / "gamelist.xml", b'<?xml version="1.0"?>\n<gameList />\n')
    (root / "downloaded_media" / name / "covers").mkdir(parents=True)


class SystemOpsTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_sysops_")
        self.root = build_esde_tree(self.dir / "esde")
        add_empty_system(self.root)
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        self.scan()

    def scan(self):
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def nav_systems(self):
        return {s["system"]: s["count"] for s in self.api.collection_detail(self.cid)["data"]["systems"]}

    # ------------------------------------------------------------------ 삭제
    def test_empty_system_preview_lists_its_folders(self):
        self.assertEqual(self.nav_systems().get("gba"), 0)
        preview = self.api.system_removal_preview(self.cid, "gba")["data"]
        self.assertEqual(preview["blockers"], [])
        self.assertEqual({t["kind"] for t in preview["targets"]}, {"rom", "metadata", "media"})
        rom = next(t for t in preview["targets"] if t["kind"] == "rom")
        self.assertEqual(rom["fileCount"], 1)
        self.assertTrue(rom["files"][0].endswith("systeminfo.txt"))

    def test_remove_empty_system_deletes_folders_and_stays_gone_after_rescan(self):
        r = self.api.remove_system(self.cid, "gba")
        self.assertTrue(r["ok"], r.get("error"))
        for path in (self.root / "gba", self.root / "gamelists" / "gba", self.root / "downloaded_media" / "gba"):
            self.assertFalse(path.exists(), path)
        self.assertNotIn("gba", self.nav_systems())
        self.scan()
        self.assertNotIn("gba", self.nav_systems())
        # 다른 System은 그대로다.
        self.assertTrue((self.root / "ps2" / "FFX.iso").exists())
        self.assertEqual(self.nav_systems()["ps2"], 3)

    def test_system_with_games_is_refused_and_nothing_is_deleted(self):
        preview = self.api.system_removal_preview(self.cid, "ps2")["data"]
        self.assertTrue(preview["blockers"])
        r = self.api.remove_system(self.cid, "ps2")
        self.assertFalse(r["ok"])
        self.assertTrue((self.root / "ps2" / "FFX.iso").exists())
        self.assertTrue((self.root / "gamelists" / "ps2" / "gamelist.xml").exists())
        self.assertIn("ps2", self.nav_systems())

    def test_leftover_media_file_blocks_removal(self):
        write_file(self.root / "downloaded_media" / "gba" / "covers" / "Zelda.png", b"x")
        r = self.api.remove_system(self.cid, "gba")
        self.assertFalse(r["ok"])
        self.assertIn("Media", r["error"])
        self.assertTrue((self.root / "downloaded_media" / "gba" / "covers" / "Zelda.png").exists())

    def test_leftover_rom_file_blocks_removal_even_if_cache_is_stale(self):
        write_file(self.root / "gba" / "Zelda.gba", b"r")   # 스캔 전이라 캐시는 아직 0개
        r = self.api.remove_system(self.cid, "gba")
        self.assertFalse(r["ok"])
        self.assertTrue((self.root / "gba" / "Zelda.gba").exists())

    def test_folder_not_named_after_the_system_is_kept(self):
        shared = self.root / "handhelds"
        write_file(shared / "readme.txt", b"shared")
        self.api.registry.upsert_system(self.cid, "gba", "internal", rom_path=str(shared))
        preview = self.api.system_removal_preview(self.cid, "gba")["data"]
        self.assertIn(str(shared), [k["path"] for k in preview["kept"]])
        self.assertTrue(self.api.remove_system(self.cid, "gba")["ok"])
        self.assertTrue((shared / "readme.txt").exists())

    def test_storage_root_is_never_deleted(self):
        self.api.registry.upsert_system(self.cid, "gba", "internal", rom_path=str(self.root))
        self.api.remove_system(self.cid, "gba")
        self.assertTrue(self.root.exists())
        self.assertTrue((self.root / "ps2" / "FFX.iso").exists())

    # ------------------------------------------------------------------ 전체 삭제(force)
    def test_force_preview_has_no_blockers_and_counts_files(self):
        preview = self.api.system_removal_preview(self.cid, "ps2", True)["data"]
        self.assertEqual(preview["blockers"], [])
        self.assertEqual(preview["games"], 3)
        self.assertGreaterEqual(preview["totalFiles"], 5)   # ISO 2 + gamelist + 커버 + 동영상
        self.assertGreater(preview["totalBytes"], 3000)
        self.assertNotIn("_all", preview["targets"][0])

    def test_force_removes_system_with_games_and_its_plan_entries(self):
        uid = self.api.list_rows(self.cid, limit=10)["data"]["rows"][0]["romUid"]
        self.api.plan_delete(self.cid, [uid])
        self.assertTrue(any(e.system == "ps2" for e in self.api._plan(self.cid).entries))

        r = self.api.remove_system(self.cid, "ps2", True)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertGreaterEqual(r["data"]["planRemoved"], 1)
        for path in (self.root / "ps2", self.root / "gamelists" / "ps2", self.root / "downloaded_media" / "ps2"):
            self.assertFalse(path.exists(), path)
        self.assertFalse(any(e.system == "ps2" for e in self.api._plan(self.cid).entries))
        self.assertNotIn("ps2", self.nav_systems())
        self.scan()
        self.assertNotIn("ps2", self.nav_systems())
        # 다른 System과 Collection root는 그대로다.
        self.assertTrue((self.root / "gba" / "systeminfo.txt").exists())
        self.assertTrue(self.root.exists())

    def test_force_in_shared_folder_deletes_only_that_systems_roms(self):
        shared = self.root / "handhelds"
        write_file(shared / "Zelda.gba", b"r" * 10)
        write_file(shared / "readme.txt", b"shared")
        self.api.registry.upsert_system(self.cid, "gba", "internal", rom_path=str(shared))
        self.assertFalse(self.api.remove_system(self.cid, "gba")["ok"])   # 기본 삭제는 거절
        r = self.api.remove_system(self.cid, "gba", True)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertFalse((shared / "Zelda.gba").exists())
        self.assertTrue((shared / "readme.txt").exists())

    def test_force_never_deletes_storage_root(self):
        write_file(self.root / "Loose.gba", b"r" * 10)
        self.api.registry.upsert_system(self.cid, "gba", "internal", rom_path=str(self.root))
        self.assertTrue(self.api.remove_system(self.cid, "gba", True)["ok"])
        self.assertTrue(self.root.exists())
        self.assertTrue((self.root / "ps2" / "FFX.iso").exists())
        self.assertTrue((self.root / "gamelists" / "ps2" / "gamelist.xml").exists())

    # ------------------------------------------------------------------ 폴더 열기
    def test_open_system_folders_follow_the_layout(self):
        opened = []
        with mock.patch.object(bridge_api, "_reveal_path", opened.append):
            for kind in ("rom", "metadata", "media"):
                r = self.api.open_system_folder(self.cid, "ps2", kind)
                self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual([Path(p) for p in opened], [
            self.root / "ps2", self.root / "gamelists" / "ps2", self.root / "downloaded_media" / "ps2"])

    def test_open_missing_folder_reports_error(self):
        (self.root / "downloaded_media" / "gba" / "covers").rmdir()
        (self.root / "downloaded_media" / "gba").rmdir()
        with mock.patch.object(bridge_api, "_reveal_path") as reveal:
            r = self.api.open_system_folder(self.cid, "gba", "media")
        self.assertFalse(r["ok"])
        self.assertIn("폴더가 없습니다", r["error"])
        reveal.assert_not_called()

    def test_open_folder_rejects_unknown_kind_and_system(self):
        with mock.patch.object(bridge_api, "_reveal_path") as reveal:
            self.assertFalse(self.api.open_system_folder(self.cid, "ps2", "saves")["ok"])
            self.assertFalse(self.api.open_system_folder(self.cid, "nope", "rom")["ok"])
        reveal.assert_not_called()

    # -------------------------------------------------- Windows 탐색기 선택 열기
    # 실사용 피드백 - "Gamelist에서 ROM/Metadata/Media 폴더 열기를 선택하면 문서
    # 폴더가 열림(System에서는 잘 열림)". System 쪽은 select=False라 os.startfile()을
    # 쓰고, 개별 게임 쪽만 select=True라 explorer /select,를 쓴다 - 거기서만 재현된다.
    def test_경로에_공백이_있어도_explorer_select가_올바른_명령줄을_받는다(self):
        """`["explorer", f"/select,{path}"]`처럼 리스트로 넘기면 Windows가 그
        인자 전체를 다시 따옴표로 감싸는데, explorer.exe는 자기만의 명령줄
        파서를 쓰기 때문에 그 형태를 못 읽고 조용히 기본 폴더(문서)로
        폴백한다. 문자열 하나로 넘겨 `/select,"경로"` 형태가 그대로 explorer에
        전달되는지 본다.
        """
        # _reveal_path()는 subprocess/sys를 함수 안에서 지역으로 import한다 - 실제
        # 모듈을 패치해야 그 지역 import가 같은 객체를 가져온다.
        path = "C:/Users/tester/My Games/ps2/Final Fantasy X.iso"
        with mock.patch("sys.platform", "win32"), mock.patch("subprocess.Popen") as popen:
            bridge_api._reveal_path(path, select=True)
        (call_arg,), _kwargs = popen.call_args
        self.assertIsInstance(call_arg, str, "리스트로 넘기면 다시 이 버그가 재현된다")
        self.assertEqual(call_arg, f'explorer /select,"{path}"')

    # ------------------------------------------------------------ 게임 한 개씩 폴더 열기
    # 실사용 피드백 §5 - "롬/메타데이터/미디어 디렉토리 이동(=탐색기로 열기)을 각
    # 롬별로도 지원". System 폴더 열기와 다른 점은 **파일 자체를 고른 채로** 연다는
    # 것이다(System 안에 파일이 많으면 폴더만 열어서는 다시 찾아야 한다).
    def _uid(self, filename):
        rows = self.api.list_rows(self.cid, limit=50)["data"]["rows"]
        return next(r["romUid"] for r in rows if r["file"] == filename)

    def test_rom_is_opened_selected_not_just_the_folder(self):
        opened = []
        with mock.patch.object(bridge_api, "_reveal_path", lambda p, select=False: opened.append((p, select))):
            r = self.api.open_row_folder(self.cid, self._uid("FFX.iso"), "rom")
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(opened, [(str(self.root / "ps2" / "FFX.iso"), True)])

    def test_metadata_opens_the_shared_gamelist_file_selected(self):
        opened = []
        with mock.patch.object(bridge_api, "_reveal_path", lambda p, select=False: opened.append((p, select))):
            r = self.api.open_row_folder(self.cid, self._uid("FFX.iso"), "metadata")
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(opened, [(str(self.root / "gamelists" / "ps2" / "gamelist.xml"), True)])

    def test_media_opens_one_of_its_files_selected(self):
        opened = []
        with mock.patch.object(bridge_api, "_reveal_path", lambda p, select=False: opened.append((p, select))):
            r = self.api.open_row_folder(self.cid, self._uid("FFX.iso"), "media")
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0][1], "select=True가 아니었다")
        self.assertTrue(str(self.root / "downloaded_media" / "ps2") in opened[0][0])

    def test_missing_rom_is_reported_not_opened(self):
        """MGS2는 ROM이 있다 - 지워서 "없음" 상태를 만든다."""
        (self.root / "ps2" / "MGS2.iso").unlink()
        self.scan()
        with mock.patch.object(bridge_api, "_reveal_path") as reveal:
            r = self.api.open_row_folder(self.cid, self._uid("MGS2.iso"), "rom")
        self.assertFalse(r["ok"])
        self.assertIn("ROM 파일이 없습니다", r["error"])
        reveal.assert_not_called()

    def test_a_game_without_media_reports_that_not_a_crash(self):
        with mock.patch.object(bridge_api, "_reveal_path") as reveal:
            r = self.api.open_row_folder(self.cid, self._uid("MGS2.iso"), "media")
        self.assertFalse(r["ok"])
        self.assertIn("Media 파일이 없습니다", r["error"])
        reveal.assert_not_called()

    def test_unknown_kind_and_row_are_rejected(self):
        with mock.patch.object(bridge_api, "_reveal_path") as reveal:
            self.assertFalse(self.api.open_row_folder(self.cid, self._uid("FFX.iso"), "saves")["ok"])
            self.assertFalse(self.api.open_row_folder(self.cid, 999999, "rom")["ok"])
        reveal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
