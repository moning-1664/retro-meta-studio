"""System 전체 미디어 정리 - System 우클릭 메뉴(사용자 결정, 2026-09).

Cover/Screenshot/Video 등 media type을 골라서 그 System 전체에서만 지운다. ROM과
Metadata, 고르지 않은 type은 절대 건드리지 않는다. 지운 뒤에는 System을 다시 스캔해
Cache(has_media 등)를 실제 디스크 상태로 맞춘다(app/media_cleanup.py).
"""

import unittest

from bridge.api import Api
from tests.fixtures import build_esde_tree, temp_root, wait_job, write_file


class MediaCleanupPreviewTests(unittest.TestCase):
    """build_esde_tree: FFX는 covers 1개 + videos 1개를 갖고, MGS2/MetadataOnly는
    media가 없다."""

    def setUp(self):
        self.dir = temp_root("rms_mediaclean_")
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def preview(self):
        r = self.api.media_cleanup_preview(self.cid, "ps2")
        self.assertTrue(r["ok"], r.get("error"))
        return r["data"]["types"]

    def test_lists_only_types_that_actually_have_files(self):
        types = {t["type"]: t for t in self.preview()}
        self.assertEqual(set(types), {"covers", "videos"})
        self.assertEqual(types["covers"]["count"], 1)
        self.assertEqual(types["videos"]["count"], 1)
        self.assertEqual(types["covers"]["label"], "Covers")
        self.assertEqual(types["videos"]["bytes"], 100)   # build_esde_tree writes b"v" * 100

    def test_unknown_system_is_an_error(self):
        self.assertFalse(self.api.media_cleanup_preview(self.cid, "nope")["ok"])

    def test_unknown_collection_is_an_error_not_a_crash(self):
        self.assertFalse(self.api.media_cleanup_preview("nope", "ps2")["ok"])


class MediaCleanupTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_mediaclean2_")
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def ffx_row(self):
        return next(r for r in self.api.list_rows(self.cid, limit=50)["data"]["rows"] if r["file"] == "FFX.iso")

    def test_cleaning_videos_only_removes_the_video_file_and_nothing_else(self):
        r = self.api.media_cleanup(self.cid, "ps2", ["videos"])
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["data"], {"removed": 1, "failed": []})

        self.assertFalse((self.root / "downloaded_media" / "ps2" / "videos" / "FFX.mp4").exists())
        self.assertTrue((self.root / "downloaded_media" / "ps2" / "covers" / "FFX.png").exists())
        self.assertTrue((self.root / "ps2" / "FFX.iso").exists())
        gamelist = (self.root / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertIn("Final Fantasy X", gamelist)

    def test_has_media_stays_true_while_another_type_remains(self):
        self.api.media_cleanup(self.cid, "ps2", ["videos"])
        self.assertTrue(self.ffx_row()["hasMedia"])

    def test_has_media_turns_false_once_every_type_is_gone(self):
        self.api.media_cleanup(self.cid, "ps2", ["videos", "covers"])
        self.assertFalse(self.ffx_row()["hasMedia"])

    def test_cache_reflects_the_cleanup_immediately(self):
        self.api.media_cleanup(self.cid, "ps2", ["videos", "covers"])
        types = {t["type"] for t in self.api.media_cleanup_preview(self.cid, "ps2")["data"]["types"]}
        self.assertEqual(types, set())

    def test_dashboard_media_bytes_drop_after_cleanup(self):
        before = self.api.dashboard_stats(self.cid)["data"]["totals"]["mediaBytes"]
        self.api.media_cleanup(self.cid, "ps2", ["videos"])
        after = self.api.dashboard_stats(self.cid)["data"]["totals"]["mediaBytes"]
        self.assertLess(after, before)

    def test_choosing_no_type_is_an_error_and_deletes_nothing(self):
        r = self.api.media_cleanup(self.cid, "ps2", [])
        self.assertFalse(r["ok"])
        self.assertTrue((self.root / "downloaded_media" / "ps2" / "covers" / "FFX.png").exists())

    def test_unknown_system_is_an_error(self):
        self.assertFalse(self.api.media_cleanup(self.cid, "nope", ["covers"])["ok"])

    def test_a_type_with_no_files_is_a_harmless_no_op(self):
        r = self.api.media_cleanup(self.cid, "ps2", ["screenshots"])
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["data"], {"removed": 0, "failed": []})
        self.assertTrue((self.root / "downloaded_media" / "ps2" / "covers" / "FFX.png").exists())

    def test_other_systems_are_never_touched(self):
        write_file(self.root / "gamelists" / "snes" / "gamelist.xml",
                  '<?xml version="1.0"?>\n<gameList>\n<game><path>./SMW.sfc</path><name>SMW</name></game>\n</gameList>')
        write_file(self.root / "snes" / "SMW.sfc", b"r" * 10)
        write_file(self.root / "downloaded_media" / "snes" / "covers" / "SMW.png", b"c" * 10)
        wait_job(self.api, self.api.start_scan(self.cid, force=True)["data"]["jobId"])

        self.api.media_cleanup(self.cid, "ps2", ["covers"])
        self.assertTrue((self.root / "downloaded_media" / "snes" / "covers" / "SMW.png").exists())


if __name__ == "__main__":
    unittest.main()
