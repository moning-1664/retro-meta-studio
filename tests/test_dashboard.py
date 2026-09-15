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

    # --- 고친 뒤 다시 검사하기 (검증 리스트 #13) --------------------------
    def test_a_fixed_gamelist_stops_being_reported(self):
        """이전 결과가 캐시로 남아 있으면 고쳐도 계속 «깨졌다»고 한다."""
        path = self.root / "gamelists" / "ps2" / "gamelist.xml"
        good = path.read_text(encoding="utf-8")
        write_file(path, "<gameList><game>")
        self.assertEqual(len(self.api.validate_collection(self.cid)["data"]["invalid"]), 1)

        write_file(path, good)
        again = self.api.validate_collection(self.cid)["data"]
        self.assertEqual(again["invalid"], [], "고쳤는데 이전 결과가 남아 있다")
        self.assertEqual(again["statuses"]["invalidXml"], 0)

    def test_repeated_validation_is_stable(self):
        first = self.api.validate_collection(self.cid)["data"]
        second = self.api.validate_collection(self.cid)["data"]
        self.assertEqual(first, second, "같은 상태인데 검사할 때마다 결과가 다르다")

    def test_the_counts_also_follow_a_fix_made_outside_the_app(self):
        """리포트 안의 숫자는 **전부 같은 시점**을 가리켜야 한다.

        깨진 XML 같은 것은 파일을 그 자리에서 읽어 알아내지만, Complete/Missing
        Description은 Cache에서 온다. 맞춰 두지 않으면 앱 밖에서 설명을 채운 뒤
        검사했을 때 "Missing Description"만 옛 숫자로 남아, 한 화면에서 절반은
        지금 상태 절반은 지난번 상태가 된다.
        """
        before = self.api.validate_collection(self.cid)["data"]["statuses"]
        self.assertGreater(before["missingDescription"], 0, "전제가 깨졌다")

        path = self.root / "gamelists" / "ps2" / "gamelist.xml"
        write_file(path, path.read_text(encoding="utf-8").replace(
            "</game>", "<desc>설명을 채웠다</desc></game>"))

        after = self.api.validate_collection(self.cid)["data"]["statuses"]
        self.assertEqual(after["missingDescription"], 0,
                         "설명을 채웠는데 숫자가 지난 스캔 그대로다")

    # --- 재스캔이 실패했을 때 (P1 검토) ----------------------------------
    # 스캔 실패를 조용히 삼키면 옛 Cache로 계산한 숫자가 지금 숫자인 척 나간다 -
    # 재스캔이 막으려던 바로 그 상태인데, 이번엔 알아챌 방법조차 없다.

    def _break_scan(self):
        def boom(*_a, **_k):
            raise RuntimeError("스캔 실패")
        self.api.workspace.scan = boom

    def test_a_failed_rescan_is_reported_not_swallowed(self):
        self._break_scan()
        data = self.api.validate_collection(self.cid)["data"]
        self.assertTrue(data["countsStale"], "스캔이 실패했는데 숫자를 그대로 내보냈다")
        self.assertIn("스캔 실패", data["staleReason"])

    def test_a_successful_rescan_is_not_marked_stale(self):
        data = self.api.validate_collection(self.cid)["data"]
        self.assertFalse(data["countsStale"])
        self.assertIsNone(data["staleReason"])

    def test_file_level_findings_survive_a_failed_rescan(self):
        """Cache와 무관한 검사는 스캔이 실패해도 여전히 정확하다 - 그래서 중단하지 않는다."""
        write_file(self.root / "gamelists" / "ps2" / "gamelist.xml", "<gameList><game>")
        self._break_scan()
        data = self.api.validate_collection(self.cid)["data"]
        self.assertEqual(len(data["invalid"]), 1, "스캔 실패로 파일 검사까지 잃었다")
        self.assertEqual(data["statuses"]["invalidXml"], 1)

    def test_file_level_findings_read_the_disk_not_the_scan_cache(self):
        """파일을 앱 밖에서 고쳐도 **재스캔 없이** 바로 반영돼야 한다.

        Validate는 «지금 파일이 어떤가»를 묻는 기능이다 - 스캔 시점의 기억을
        보여주면 사용자가 고친 것을 확인할 방법이 없다.
        """
        write_file(self.root / "gamelists" / "ps2" / "gamelist.xml", "<gameList><game>")
        # 스캔을 다시 돌리지 않는다.
        result = self.api.validate_collection(self.cid)["data"]
        self.assertEqual(len(result["invalid"]), 1, "디스크가 아니라 캐시를 읽고 있다")


if __name__ == "__main__":
    unittest.main()
