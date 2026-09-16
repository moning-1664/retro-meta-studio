"""ROM 없는 항목 정리 - System 우클릭 메뉴(사용자 결정, 2026-09).

Metadata/Media는 있는데 ROM 파일이 없는 gamelist 항목을 찾아 보여주고
(`orphan_metadata_preview`), 골라서 지운다. 삭제 자체는 **새 코드가 아니라 기존
Plan 삭제(plan_delete → apply)를 그대로 재사용한다** - `_apply_delete`가 이미
`row.present`가 False면 ROM 삭제를 건너뛰고 media와 gamelist 항목만 지우도록
되어 있다(같은 코드로 이미 검증된 경로).
"""

import unittest
from pathlib import Path

from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, build_esde_tree, temp_root, wait_idle, wait_job, write_file


class OrphanMetadataPreviewTests(unittest.TestCase):
    """build_esde_tree: FFX(ROM 있음) / MGS2(ROM 있음) / MetadataOnly(ROM 없음)."""

    def setUp(self):
        self.dir = temp_root("rms_orphan_")
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def preview(self):
        r = self.api.orphan_metadata_preview(self.cid, "ps2")
        self.assertTrue(r["ok"], r.get("error"))
        return r["data"]

    def test_lists_only_the_entry_without_a_rom_file(self):
        items = self.preview()["items"]
        self.assertEqual([i["filename"] for i in items], ["MetadataOnly.iso"])
        self.assertEqual(items[0]["title"], "ROM 없는 항목")
        self.assertIn("romUid", items[0])

    def test_entries_with_a_rom_file_are_never_listed(self):
        filenames = {i["filename"] for i in self.preview()["items"]}
        self.assertNotIn("FFX.iso", filenames)
        self.assertNotIn("MGS2.iso", filenames)

    def test_unknown_system_is_an_error(self):
        r = self.api.orphan_metadata_preview(self.cid, "nope")
        self.assertFalse(r["ok"])

    def test_unknown_collection_is_an_error_not_a_crash(self):
        r = self.api.orphan_metadata_preview("nope", "ps2")
        self.assertFalse(r["ok"])

    def test_system_with_no_orphans_returns_an_empty_list(self):
        write_file(self.root / "MetadataOnly.iso", b"r" * 10)   # 이제 ROM이 생겼다
        wait_job(self.api, self.api.start_scan(self.cid, force=True)["data"]["jobId"])
        # 새 폴더 밑이 아니라 root 바로 아래 - 실제로는 ps2 폴더 밑이어야 인식되므로
        # 다시 지우고 올바른 위치에 만든다.
        write_file(self.root / "ps2" / "MetadataOnly.iso", b"r" * 10)
        wait_job(self.api, self.api.start_scan(self.cid, force=True)["data"]["jobId"])
        self.assertEqual(self.preview()["items"], [])


class OrphanMetadataDeleteTests(unittest.TestCase):
    """정리(삭제)는 기존 Plan 삭제 경로를 그대로 쓴다 - 여기서는 그 재사용이 실제로
    ROM 없는 항목에 대해 맞물리는지(파일 삭제를 시도하지 않고, media와 gamelist
    항목만 지우는지)를 확인한다."""

    def setUp(self):
        self.dir = temp_root("rms_orphan_del_")
        self.root = build_custom_esde_tree(self.dir / "esde", "ps2", [
            {"filename": "FFX.iso", "title": "Final Fantasy X"},
            {"filename": "Ghost.iso", "title": "Ghost Game", "rom": False},
        ], with_media=True)
        write_file(self.root / "downloaded_media" / "ps2" / "covers" / "Ghost.png", b"c" * 10)
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def orphan_uids(self):
        return [i["romUid"] for i in self.api.orphan_metadata_preview(self.cid, "ps2")["data"]["items"]]

    def apply(self):
        job = self.api.start_apply(self.cid)
        self.assertTrue(job["ok"], job.get("error"))
        wait_idle(self.api)
        return self.api.get_job_progress(job["data"]["jobId"])["data"].get("result") or {}

    def test_deleting_the_orphan_removes_its_gamelist_entry_and_media(self):
        uids = self.orphan_uids()
        self.assertEqual(len(uids), 1)
        r = self.api.plan_delete(self.cid, uids)
        self.assertTrue(r["ok"], r.get("error"))
        result = self.apply()
        self.assertEqual(result.get("failed"), 0, result)
        self.assertEqual(result.get("applied"), 1, result)

        gamelist = (self.root / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertNotIn("Ghost.iso", gamelist)
        self.assertFalse((self.root / "downloaded_media" / "ps2" / "covers" / "Ghost.png").exists())
        self.assertEqual(self.api.orphan_metadata_preview(self.cid, "ps2")["data"]["items"], [])

    def test_real_rom_and_its_files_are_left_alone(self):
        r = self.api.plan_delete(self.cid, self.orphan_uids())
        self.assertTrue(r["ok"], r.get("error"))
        self.apply()
        self.assertTrue((self.root / "ps2" / "FFX.iso").exists())
        gamelist = (self.root / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertIn("Final Fantasy X", gamelist)

    def test_total_game_count_drops_after_cleanup(self):
        before = self.api.list_rows(self.cid, limit=50)["data"]["total"]
        self.api.plan_delete(self.cid, self.orphan_uids())
        self.apply()
        after = self.api.list_rows(self.cid, limit=50)["data"]["total"]
        self.assertEqual(after, before - 1)


class EditingAnEntryWithoutItsRomTests(unittest.TestCase):
    """**ROM이 없어도 Metadata는 고칠 수 있어야 한다** (검증 리스트 #12-B).

    ES-DE를 실제로 쓰면 흔한 상태다 - 기기에서 ROM만 지우고 gamelist는 남겨 두거나,
    스크래핑을 먼저 해 두고 ROM을 나중에 넣는다. 그 항목을 «없는 것»으로 취급해
    저장을 막으면, 사용자는 ROM을 넣기 전까지 정리를 못 한다.
    """

    def setUp(self):
        self.dir = temp_root("rms_absent_")
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def row(self, filename="MetadataOnly.iso"):
        rows = self.api.list_rows(self.cid, limit=50)["data"]["rows"]
        return next(r for r in rows if r["file"] == filename)

    def test_the_entry_shows_up_in_the_list_marked_as_absent(self):
        row = self.row()
        self.assertFalse(row["present"], "ROM 없는 항목이 목록에서 빠졌다")
        self.assertEqual(row["title"], "ROM 없는 항목")

    def test_saving_metadata_succeeds_even_though_the_rom_is_missing(self):
        result = self.api.save_fields(self.cid, self.row()["romUid"],
                                      {"name": "고친 제목", "genre": "RPG"})
        self.assertTrue(result["ok"], result.get("error"))

    def test_the_edit_reaches_the_gamelist_on_disk(self):
        self.api.save_fields(self.cid, self.row()["romUid"], {"name": "고친 제목"})
        text = (self.root / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertIn("고친 제목", text)

    def test_the_entry_stays_absent_after_the_edit(self):
        """제목을 고쳤다고 ROM이 생긴 것처럼 보이면 안 된다."""
        self.api.save_fields(self.cid, self.row()["romUid"], {"name": "고친 제목"})
        wait_job(self.api, self.api.start_scan(self.cid, force=True)["data"]["jobId"])
        row = self.row()
        self.assertEqual(row["title"], "고친 제목")
        self.assertFalse(row["present"], "ROM이 없는데 있는 것으로 바뀌었다")


if __name__ == "__main__":
    unittest.main()
