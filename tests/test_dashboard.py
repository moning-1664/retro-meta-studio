"""Collection Dashboard - 통계와 Metadata 파일 검증 (app/dashboard.py, bridge).

픽스처(build_esde_tree)의 ps2: FFX(ROM·설명·Cover·Video), MGS2(ROM만),
MetadataOnly(gamelist에만 있고 ROM 없음). ROM 3000 B, Media 110 B.
"""

import unittest

from bridge.api import Api
from tests.fixtures import build_esde_tree, temp_root, wait_job, write_file


class DashboardStatsTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_dash_")
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        created = self.api.create_collection("C", "es-de", str(self.root))
        self.assertTrue(created["ok"], created.get("error"))
        self.cid = created["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def stats(self):
        result = self.api.dashboard_stats(self.cid)
        self.assertTrue(result["ok"], result.get("error"))
        return result["data"]

    def test_totals_match_the_gamelist(self):
        totals = self.stats()["totals"]
        self.assertEqual(totals["games"], 3)
        self.assertEqual(totals["romBytes"], 3000)
        self.assertEqual(totals["mediaBytes"], 110)

    def test_storage_buckets_add_up_to_the_totals(self):
        data = self.stats()
        internal = next(s for s in data["storages"] if s["id"] == "internal")
        self.assertEqual(internal["romBytes"], data["totals"]["romBytes"])
        self.assertEqual(internal["mediaBytes"], data["totals"]["mediaBytes"])
        self.assertIn("capacityBytes", internal)

    def test_each_system_reports_its_own_numbers(self):
        ps2 = next(s for s in self.stats()["systems"] if s["system"] == "ps2")
        self.assertEqual(ps2["games"], 3)
        self.assertEqual(ps2["romBytes"], 3000)
        self.assertEqual(ps2["storageId"], "internal")

    def test_metadata_health_counts_what_each_game_has(self):
        health = self.stats()["health"]
        self.assertEqual(health["total"], 3)
        self.assertEqual(health["present"], 2)
        self.assertEqual(health["description"], 1)
        self.assertEqual(health["cover"], 1)
        self.assertEqual(health["complete"], 1)
        self.assertEqual(health["missingRom"], 1)
        self.assertEqual(health["missingCover"], 2)

    def test_unknown_collection_is_an_error_not_a_crash(self):
        self.assertFalse(self.api.dashboard_stats("nope")["ok"])


class ValidateCollectionTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_validate_")
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def test_a_well_formed_gamelist_passes(self):
        result = self.api.validate_collection(self.cid)["data"]
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["invalid"], [])

    def test_a_broken_gamelist_is_reported_with_its_path(self):
        write_file(self.root / "gamelists" / "ps2" / "gamelist.xml", "<gameList><game>")
        result = self.api.validate_collection(self.cid)["data"]
        self.assertEqual(len(result["invalid"]), 1)
        self.assertEqual(result["invalid"][0]["system"], "ps2")
        self.assertTrue(result["invalid"][0]["path"].endswith("gamelist.xml"))

    def test_validation_never_changes_the_file(self):
        broken = "<gameList><game>"
        path = write_file(self.root / "gamelists" / "ps2" / "gamelist.xml", broken)
        self.api.validate_collection(self.cid)
        self.assertEqual(path.read_text(encoding="utf-8"), broken)


if __name__ == "__main__":
    unittest.main()
