"""Archive로 보내기도 Apply 전에는 Revision이나 frontend 파일을 쓰지 않는다."""

import unittest

from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, temp_root, wait_idle


class ArchiveIngestPlanTests(unittest.TestCase):
    def setUp(self):
        self.root = temp_root("rms_archive_ingest_plan_")
        self.collection_root = build_custom_esde_tree(
            self.root / "collection", "ps2",
            [{"filename": "One (USA).iso", "title": "One"},
             {"filename": "Two.iso", "title": "Two"}])
        self.archive_root = self.root / "archive"
        self.api = Api(registry_path=self.root / "registry.db", cache_dir=self.root / "cache")
        self.addCleanup(self.api.close)
        self.collection_id = self.api.create_collection(
            "Source", "es-de", str(self.collection_root))["data"]["id"]
        self.api.start_scan(self.collection_id)
        wait_idle(self.api)
        saved = self.api.save_archive_config({"archiveDir": str(self.archive_root)})
        self.assertTrue(saved["ok"], saved.get("error"))
        self.api._apply_archive_config()

    def test_stage_then_apply_records_revisions_once(self):
        scope = {"kind": "system", "system": "ps2"}
        first = self.api.plan_archive_ingest(self.collection_id, scope)
        self.assertTrue(first["ok"], first.get("error"))
        self.assertEqual(first["data"]["planned"], 2)
        self.assertEqual(self.api.archive_rows()["data"]["total"], 0)
        self.assertEqual(self.api.plan_state(self.collection_id)["data"]["archived"], 2)
        self.assertFalse((self.archive_root / "gamelists" / "ps2" / "gamelist.xml").exists())
        again = self.api.plan_archive_ingest(self.collection_id, scope)
        self.assertEqual(again["data"]["planned"], 2)
        self.assertEqual(self.api.plan_state(self.collection_id)["data"]["archived"], 2)

        started = self.api.start_apply(self.collection_id)
        self.assertTrue(started["ok"], started.get("error"))
        wait_idle(self.api)
        self.assertEqual(self.api.archive_rows()["data"]["total"], 2)
        self.assertEqual(self.api.plan_state(self.collection_id)["data"]["total"], 0)
        self.assertTrue((self.archive_root / "gamelists" / "ps2" / "gamelist.xml").exists())

    def test_clearing_plan_leaves_archive_unchanged(self):
        self.api.plan_archive_ingest(self.collection_id, {"kind": "all"})
        self.api.plan_clear(self.collection_id)
        self.assertEqual(self.api.plan_state(self.collection_id)["data"]["total"], 0)
        self.assertEqual(self.api.archive_rows()["data"]["total"], 0)

    def test_changed_source_is_invalid_before_apply(self):
        row = self.api.workspace.open(self.collection_id).query_rows()[0]
        self.api.plan_archive_ingest(self.collection_id,
            {"kind": "selected", "romUids": [row["rom_uid"]]})
        cache = self.api.workspace.open(self.collection_id)
        cache.update_metadata(row["rom_uid"], {"name": "Edited after staging"})
        report = self.api.validate_plan(self.collection_id)
        self.assertTrue(report["ok"], report.get("error"))
        self.assertEqual(len(report["data"]["entries"]), 1)
        started = self.api.start_apply(self.collection_id)
        self.assertFalse(started["ok"])
        self.assertEqual(self.api.archive_rows()["data"]["total"], 0)

    def test_archive_and_title_edit_apply_in_one_plan(self):
        self.assertTrue(self.api.save_app_settings({"titleAffix": {
            "en": {"enabled": True, "mode": "prefix", "text": "EN_"}
        }})["ok"])
        self.api.plan_archive_ingest(self.collection_id, {"kind": "all"})
        title = self.api.plan_title_edit(self.collection_id, system="ps2")
        self.assertTrue(title["ok"], title.get("error"))
        self.assertEqual(title["data"]["added"], 1)
        started = self.api.start_apply(self.collection_id)
        self.assertTrue(started["ok"], started.get("error"))
        wait_idle(self.api)
        self.assertEqual(self.api.archive_rows()["data"]["total"], 2)
        self.assertEqual(self.api.plan_state(self.collection_id)["data"]["total"], 0)

    def test_mixed_plan_counts_invalid_archive_once(self):
        self.api.plan_archive_ingest(self.collection_id, {"kind": "all"})
        self.assertTrue(self.api.save_app_settings({"titleAffix": {
            "en": {"enabled": True, "mode": "prefix", "text": "EN_"}
        }})["ok"])
        title = self.api.plan_title_edit(self.collection_id, system="ps2")
        self.assertTrue(title["ok"])
        self.assertGreater(title["data"]["added"], 0)
        cache = self.api.workspace.open(self.collection_id)
        row = next(r for r in cache.query_rows() if r["filename"] == "Two.iso")
        cache.update_metadata(row["rom_uid"], {"name": "Changed since staging"})
        started = self.api.start_apply(self.collection_id)
        self.assertTrue(started["ok"], started.get("error"))
        wait_idle(self.api)
        result = self.api.jobs.get(started["data"]["jobId"])
        self.assertIsNone(result["error"])
        follow = result["result"].get("followUpJobId")
        if follow:
            wait_idle(self.api)
            result = self.api.jobs.get(follow)
        self.assertEqual(result["result"]["invalid"], 1, result["result"])


if __name__ == "__main__":
    unittest.main()
