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


if __name__ == "__main__":
    unittest.main()
