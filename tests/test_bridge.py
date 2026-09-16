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

    def test_list_rows_status_flags_are_independent(self):
        """Gamelist Status 아이콘(실사용 피드백 - "ROM/Media/Description/Cover를
        독립적으로") 4개가 각자 옳은 값을 내야 한다. FFX는 desc·cover·video가 전부
        있고, MGS2는 desc도 media도 없다 - 서로 다른 조합을 한 번에 본다."""
        rows = {r["file"]: r for r in self.api.list_rows(self.cid)["data"]["rows"]}
        ffx = rows["FFX.iso"]
        self.assertTrue(ffx["hasDescription"])
        self.assertTrue(ffx["hasCover"])
        self.assertTrue(ffx["hasMedia"])

        mgs2 = rows["MGS2.iso"]
        self.assertFalse(mgs2["hasDescription"])
        self.assertFalse(mgs2["hasCover"])
        self.assertFalse(mgs2["hasMedia"])

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

    def test_reassign_system_storage_does_not_touch_files(self):
        """External Storage 제거가 쓰는 경로(실사용 피드백 - "실제 롬파일은 유지되는데
        표시만 Internal로 합쳐지는 걸로 되어야 한다"). move_system(파일도 옮기는
        Storage 이동)과 달리 파일은 원래 자리에 그대로 있어야 하고, 새로 계산된
        절대 경로가 System에 고정돼야 Scan이 계속 그 파일을 찾는다."""
        storage_id = self.api.add_external_storage(self.cid, "SD", str(self.dir / "sd"))["data"]
        self.assertTrue(self.api.move_system(self.cid, "ps2", storage_id)["ok"])

        old_rom_dir = self.root / "ps2"   # ES-DE 기본 배치 - 아직 실제로 옮기지 않았다.
        self.assertTrue(old_rom_dir.exists())
        self.assertFalse((self.dir / "sd" / "ps2").exists())

        result = self.api.reassign_system_storage(self.cid, "ps2", "internal")
        self.assertTrue(result["ok"], result.get("error"))

        # 파일은 옮긴 적이 없으므로 옛 자리에 그대로다.
        self.assertTrue(old_rom_dir.exists())
        self.assertFalse((self.dir / "sd" / "ps2").exists())

        detail = self.api.collection_detail(self.cid)["data"]
        placement = {s["id"]: [x["system"] for x in s["systems"]] for s in detail["storages"]}
        self.assertEqual(placement["internal"], ["ps2"])

        # 재배치 뒤에도 Scan이 여전히 그 파일을 찾는다 - 절대 경로가 고정된
        # 덕분이다(고정하지 않으면 layout()이 Internal 기준으로 다시 계산해
        # 파일이 "사라진 것"처럼 보인다).
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])
        self.assertEqual(len(self.api.list_rows(self.cid, systems=["ps2"])["data"]["rows"]), 3)

    def test_reassign_system_storage_lets_the_now_empty_storage_be_removed(self):
        storage_id = self.api.add_external_storage(self.cid, "SD", str(self.dir / "sd"))["data"]
        self.api.move_system(self.cid, "ps2", storage_id)
        self.assertFalse(self.api.remove_storage(self.cid, storage_id)["ok"])

        self.assertTrue(self.api.reassign_system_storage(self.cid, "ps2", "internal")["ok"])
        self.assertTrue(self.api.remove_storage(self.cid, storage_id)["ok"])

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

        # 이 상태는 Storage 충돌이라 평소엔 Plan 전에 막힌다(test_storage_layout). 여기서는 그 가드를
        # 끄고, 적용 도중 파일이 생긴 경우의 마지막 안전망(적용기의 충돌 처리)을 본다.
        self.assertIn("쓰기가 막혀", self.api.plan_storage_change(self.cid, "ps2", storage_id)["error"])
        self.api._conflicts = lambda collection: {}
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

    # ------------------------------------------------------------------
    # 앱 전역 설정 (Settings 화면)
    # ------------------------------------------------------------------
    def test_app_settings_start_empty(self):
        self.assertEqual(self.api.get_app_settings()["data"], {})

    def test_app_settings_merge_one_section_at_a_time(self):
        """값 하나를 바꾸려고 섹션 전체를 다시 보낼 필요가 없어야 한다."""
        self.api.save_app_settings({"appearance": {"theme": "sfc", "scale": 110}})
        self.api.save_app_settings({"appearance": {"density": "normal"}})
        appearance = self.api.get_app_settings()["data"]["appearance"]
        self.assertEqual(appearance, {"theme": "sfc", "scale": 110, "density": "normal"})

    def test_app_settings_survive_a_restart(self):
        """브라우저 저장소가 아니라 registry에 있으므로 앱을 다시 열어도 남는다."""
        self.api.save_app_settings({"appearance": {"theme": "nes"}})
        self.api.close()
        reopened = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.get_app_settings()["data"]["appearance"]["theme"], "nes")
        self.api = reopened

    def test_app_settings_reject_a_non_object(self):
        self.assertFalse(self.api.save_app_settings("dark")["ok"])

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


class DeletedCollectionLeavesNothingBehindTests(unittest.TestCase):
    """Collection을 지우면 **그것에 딸린 상태도 함께 사라져야 한다** (검증 리스트 #3).

    메모리에 남은 Plan이나 아직 살아 있는 Cache 핸들은 다음에 같은 id가 재사용될 때
    남의 상태로 되살아난다. 지운 Collection을 가리키는 요청은 «없다»고 답해야 한다.
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_delcol_"))
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("Test", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def test_the_collection_is_gone_from_the_list(self):
        self.assertTrue(self.api.delete_collection(self.cid)["ok"])
        self.assertEqual([c["id"] for c in self.api.list_collections()["data"]], [])

    def test_its_in_memory_plan_is_dropped(self):
        self.api._plan(self.cid)          # Plan을 하나 만들어 둔다
        self.assertIn(self.cid, self.api._plans)
        self.api.delete_collection(self.cid)
        self.assertNotIn(self.cid, self.api._plans, "지운 Collection의 Plan이 메모리에 남았다")

    def test_requests_for_it_answer_that_it_is_gone(self):
        self.api.delete_collection(self.cid)
        for call in (lambda: self.api.dashboard_stats(self.cid),
                     lambda: self.api.list_rows(self.cid, limit=5),
                     lambda: self.api.collection_detail(self.cid)):
            self.assertFalse(call()["ok"], "지운 Collection이 아직 응답한다")


if __name__ == "__main__":
    unittest.main()
