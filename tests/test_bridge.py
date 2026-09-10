"""브릿지(bridge/api.py) 테스트.

UI가 실제로 부르는 경로를 그대로 통과시켜서, JS 없이도 Phase 2의 백엔드 쪽이
맞물리는지 확인한다. 특히 저장(D1)이 진짜 파일에 기록되면서 Frontend 고유 필드를
망가뜨리지 않는지를 본다.
"""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from bridge.api import Api
from tests.fixtures import build_esde_tree, wait_job


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_bridge_"))
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        created = self.api.create_collection("Test", "es-de", str(self.root), "windows", "x64")
        self.assertTrue(created["ok"], created.get("error"))
        self.cid = created["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def tearDown(self):
        self.api.close()

    # ------------------------------------------------------------------
    def test_collection_detail_shapes_header_and_nav(self):
        detail = self.api.collection_detail(self.cid)["data"]
        self.assertEqual(detail["name"], "Test")
        self.assertEqual(detail["target"], "windows")
        self.assertEqual(detail["totalGames"], 3)

        internal = detail["storages"][0]
        self.assertEqual(internal["id"], "internal")
        self.assertEqual([s["system"] for s in internal["systems"]], ["ps2"])
        # 네비게이션 개수는 목록 개수와 같아야 한다(게임 수, 물리 ROM 파일 수 아님).
        self.assertEqual(internal["systems"][0]["count"], 3)
        self.assertEqual(internal["actualBytes"], 3110)

    def test_list_rows_paginates_and_reports_total(self):
        page = self.api.list_rows(self.cid, limit=2, offset=0)["data"]
        self.assertEqual(page["total"], 3)
        self.assertEqual(len(page["rows"]), 2)
        self.assertEqual(page["rows"][0]["title"], "Final Fantasy X")

        second = self.api.list_rows(self.cid, limit=2, offset=2)["data"]
        self.assertEqual(len(second["rows"]), 1)

    def test_search_and_system_filter(self):
        self.assertEqual(len(self.api.list_rows(self.cid, search="metal")["data"]["rows"]), 1)
        self.assertEqual(len(self.api.list_rows(self.cid, systems=["ps2"])["data"]["rows"]), 3)
        self.assertEqual(len(self.api.list_rows(self.cid, systems=["snes"])["data"]["rows"]), 0)

    def test_get_row_returns_fields_and_media_markers(self):
        uid = self._uid("FFX.iso")
        row = self.api.get_row(self.cid, uid)["data"]
        self.assertEqual(row["fields"]["name"], "Final Fantasy X")
        # 실제 이미지는 화면에 보일 때 낱개로 가져온다 - 여기서는 표시만 온다.
        self.assertEqual(row["media"]["Covers"], "pending")
        self.assertEqual(row["media"]["Videos"], "video://exists")

    def test_media_image_returns_data_uri(self):
        uid = self._uid("FFX.iso")
        data = self.api.get_media_image(self.cid, uid, "Covers")["data"]
        self.assertTrue(str(data).startswith("data:image/"), data)
        # 비디오는 이미지로 인코딩하지 않는다.
        self.assertIsNone(self.api.get_media_image(self.cid, uid, "Videos")["data"])

    # ------------------------------------------------------------------
    # 저장 (결정 D1)
    # ------------------------------------------------------------------
    def test_save_writes_to_disk_immediately(self):
        uid = self._uid("FFX.iso")
        result = self.api.save_fields(self.cid, uid, {"name": "파이널 판타지 X", "genre": "JRPG"})
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["data"]["title"], "파이널 판타지 X")

        gamelist = self.root / "gamelists" / "ps2" / "gamelist.xml"
        game = self._game(gamelist, "./FFX.iso")
        self.assertEqual(game.findtext("name"), "파이널 판타지 X")
        self.assertEqual(game.findtext("genre"), "JRPG")

    def test_save_preserves_frontend_specific_fields(self):
        """편집 저장이 favorite/playcount 같은 값을 지우면 안 된다(스펙 §50)."""
        uid = self._uid("FFX.iso")
        self.api.save_fields(self.cid, uid, {"name": "Renamed"})

        game = self._game(self.root / "gamelists" / "ps2" / "gamelist.xml", "./FFX.iso")
        self.assertEqual(game.findtext("favorite"), "true")
        self.assertEqual(game.findtext("playcount"), "17")
        self.assertEqual(game.get("source"), "ScreenScraper")

    def test_save_does_not_touch_other_entries(self):
        self.api.save_fields(self.cid, self._uid("FFX.iso"), {"name": "Renamed"})
        game = self._game(self.root / "gamelists" / "ps2" / "gamelist.xml", "./MGS2.iso")
        self.assertEqual(game.findtext("name"), "Metal Gear Solid 2")

    def test_save_updates_the_cached_list_title(self):
        uid = self._uid("FFX.iso")
        self.api.save_fields(self.cid, uid, {"name": "ZZZ Last"})
        titles = [r["title"] for r in self.api.list_rows(self.cid)["data"]["rows"]]
        self.assertIn("ZZZ Last", titles)

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    def test_add_external_storage_and_move_system(self):
        storage_id = self.api.add_external_storage(self.cid, "SD", str(self.dir / "sd"))["data"]
        self.assertEqual(storage_id, "ext-1")

        self.assertTrue(self.api.move_system(self.cid, "ps2", storage_id)["ok"])
        detail = self.api.collection_detail(self.cid)["data"]
        placement = {s["id"]: [x["system"] for x in s["systems"]] for s in detail["storages"]}
        self.assertEqual(placement["ext-1"], ["ps2"])
        self.assertEqual(placement["internal"], [])

    def test_storage_with_systems_cannot_be_removed(self):
        storage_id = self.api.add_external_storage(self.cid, "SD", str(self.dir / "sd"))["data"]
        self.api.move_system(self.cid, "ps2", storage_id)
        result = self.api.remove_storage(self.cid, storage_id)
        self.assertFalse(result["ok"])
        self.assertIn("ps2", result["error"])

    def test_plan_storage_change_is_visible_as_a_pending_move_before_apply(self):
        """Navigator가 Apply 전에도 목표 Storage 밑에 미리 보여줄 수 있어야 한다
        (실사용 피드백: 드래그해도 화면이 그대로면 "안 먹었다"처럼 보였다)."""
        storage_id = self.api.add_external_storage(self.cid, "SD", str(self.dir / "sd"))["data"]
        self.api.plan_storage_change(self.cid, "ps2", storage_id)
        state = self.api.plan_state(self.cid)["data"]
        self.assertEqual(state["pendingMoves"], {"ps2": storage_id})

    def test_a_failed_storage_change_reports_why_and_can_be_removed(self):
        """대상에 이미 같은 이름의 파일이 있으면 이동이 실패한다 - 그 이유가
        failedEntries에 남아야 사용자가 "왜 계속 실패하는지" 알 수 있다."""
        storage_id = self.api.add_external_storage(self.cid, "SD", str(self.dir / "sd"))["data"]
        # 대상에 이미 같은 이름의 파일을 심어 충돌을 강제로 만든다.
        (self.dir / "sd").mkdir(parents=True, exist_ok=True)
        (self.dir / "sd" / "ps2").mkdir(parents=True, exist_ok=True)
        (self.dir / "sd" / "ps2" / "FFX.iso").write_bytes(b"already here")

        self.api.plan_storage_change(self.cid, "ps2", storage_id)
        job = self.api.start_apply(self.cid)
        result = wait_job(self.api, job["data"]["jobId"])
        self.assertEqual(result["result"]["failed"], 1)

        state = self.api.plan_state(self.cid)["data"]
        self.assertEqual(state["failed"], 1)
        self.assertEqual(len(state["failedEntries"]), 1)
        self.assertIn("파일이", state["failedEntries"][0]["error"])

        # Plan에서 제거하면 더 이상 실패로 남지 않는다(openFailedDialog의 "Plan에서 제거").
        key = state["failedEntries"][0]["key"]
        self.assertTrue(self.api.plan_remove_entry(self.cid, key)["ok"])
        self.assertEqual(self.api.plan_state(self.cid)["data"]["failed"], 0)

    def test_unknown_capacity_is_reported_as_none(self):
        """용량을 못 읽는 저장소는 오류가 아니라 Unknown이다(스펙 §5)."""
        self.api.add_external_storage(self.cid, "Missing", r"Z:\\does-not-exist")
        detail = self.api.collection_detail(self.cid)["data"]
        missing = next(s for s in detail["storages"] if s["label"] == "Missing")
        self.assertIsNone(missing["capacityBytes"])

    # ------------------------------------------------------------------
    def test_scan_is_incremental_on_second_run(self):
        job = wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])
        self.assertIsNone(job["error"])
        # 마지막 phase 결과만 보면 된다 - 변경이 없으니 전부 건너뛰어야 한다.
        self.assertEqual(job["result"]["skipped"], 1)
        self.assertEqual(job["result"]["scanned"], 0)

    def test_errors_come_back_as_ok_false(self):
        result = self.api.get_row("no-such-collection", 1)
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"])

    # ------------------------------------------------------------------
    def _uid(self, filename):
        rows = self.api.list_rows(self.cid, limit=100)["data"]["rows"]
        return next(r["romUid"] for r in rows if r["file"] == filename)

    @staticmethod
    def _game(gamelist, path_text):
        root = ET.parse(gamelist).getroot()
        return next(g for g in root.findall("game") if (g.findtext("path") or "").strip() == path_text)


if __name__ == "__main__":
    unittest.main()
