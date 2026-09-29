"""Collection 간 가져오기도 Archive와 동일하게 Plan/Apply를 거친다."""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, wait_idle


class CollectionImportTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rms_collection_import_"))
        self.source_root = build_custom_esde_tree(
            self.root / "source", "msx",
            [{"filename": "ws90.zip", "title": "World Soccer 90", "genre": "Sports"}])
        self.target_root = build_custom_esde_tree(
            self.root / "target", "msx1",
            [{"filename": "ws90.zip", "title": "Old title"}])
        self.api = Api(registry_path=self.root / "registry.db", cache_dir=self.root / "cache")
        self.source = self.api.create_collection("Source", "es-de", str(self.source_root))["data"]["id"]
        self.target = self.api.create_collection("Target", "es-de", str(self.target_root))["data"]["id"]
        for collection_id in (self.source, self.target):
            self.api.start_scan(collection_id)
            wait_idle(self.api)

    def tearDown(self):
        self.api.close()

    def _title_on_disk(self):
        root = ET.parse(self.target_root / "gamelists" / "msx1" / "gamelist.xml").getroot()
        return root.find("game/name").text

    def test_candidate_and_explicit_plan_do_not_write_before_apply(self):
        target_row = self.api.workspace.open(self.target).all_entries()[0]
        source_row = self.api.workspace.open(self.source).all_entries()[0]
        result = self.api.collection_import_candidates(self.target, target_row["rom_uid"], self.source)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["data"]["candidates"][0]["romUid"], source_row["rom_uid"])

        staged = self.api.collection_import_plan(
            self.target, self.source, [source_row["rom_uid"]], target_row["rom_uid"],
            mode="overwrite")
        self.assertTrue(staged["ok"], staged.get("error"))
        self.assertEqual(staged["data"]["planned"], 1)
        self.assertEqual(len(staged["data"]["keys"]), 1)
        plan_entry = self.api.plan_state(self.target)["data"]["entries"][0]
        self.assertEqual(plan_entry["sourceName"], "Source")
        self.assertTrue(plan_entry["parts"]["metadata"])
        self.assertEqual(self._title_on_disk(), "Old title")
        self.api.start_apply(self.target)
        wait_idle(self.api)
        self.assertEqual(self._title_on_disk(), "World Soccer 90")

    def test_bulk_import_maps_source_system_to_target_system(self):
        staged = self.api.collection_import_plan(self.target, self.source, target_system="msx1",
                                                 mode="overwrite")
        self.assertTrue(staged["ok"], staged.get("error"))
        self.assertEqual(staged["data"]["planned"], 1)
        self.assertEqual(self.api.plan_state(self.target)["data"]["entries"][0]["system"], "msx1")


if __name__ == "__main__":
    unittest.main()
