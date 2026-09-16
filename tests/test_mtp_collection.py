"""MTP 기기를 Collection으로 - 기기 탐색, 만들기, 스캔, 편집.

기기 없이 검증한다(tests/fixtures.py의 가짜 MTP backend). 여기서 확인하는 것은
**"기기를 꽂았을 때 앱이 하는 일 전부"** 다 - COM 호출만 실제 기기를 필요로 한다.
"""

import unittest
import xml.etree.ElementTree as ET

from bridge.api import Api
from tests.fixtures import build_mtp_device, mtp_gamelist, temp_root, use_fake_mtp, wait_job

DEVICE = "R58N30ABCDE"
ESDE = f"mtp://{DEVICE}/Internal shared storage/ES-DE"
ROMS = f"mtp://{DEVICE}/Internal shared storage/ROMs"


class MtpDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_mtp_discovery_")
        self.backend = use_fake_mtp(self)
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)

    def test_lists_connected_devices(self):
        r = self.api.mtp_devices()
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["data"]["devices"],
                         [{"key": DEVICE, "name": "Galaxy Test", "path": f"mtp://{DEVICE}"}])
        self.assertIsNone(r["data"]["reason"])

    def test_browse_walks_the_device_one_level_at_a_time(self):
        root = self.api.mtp_browse(f"mtp://{DEVICE}")["data"]
        self.assertEqual([e["name"] for e in root["entries"]], ["Internal shared storage", "SD card"])
        self.assertIsNone(root["parent"])   # 기기 루트 위로는 못 간다

        inside = self.api.mtp_browse(root["entries"][0]["path"])["data"]
        self.assertEqual([e["name"] for e in inside["entries"]], ["ES-DE", "ROMs"])
        self.assertEqual(inside["parent"], f"mtp://{DEVICE}")

    def test_browse_shows_folders_only(self):
        gamelists = self.api.mtp_browse(f"{ESDE}/gamelists/ps2")["data"]
        self.assertEqual(gamelists["entries"], [])   # gamelist.xml은 파일이라 안 보인다

    def test_browse_rejects_a_non_device_path(self):
        self.assertFalse(self.api.mtp_browse("D:\\ES-DE")["ok"])

    def test_finds_the_esde_folder_and_rom_candidates(self):
        r = self.api.mtp_find_esde(DEVICE)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual([e["path"] for e in r["data"]["esde"]], [ESDE])
        self.assertEqual(r["data"]["roms"], [ROMS])

    def test_reports_why_the_list_is_empty_instead_of_just_showing_nothing(self):
        """comtypes가 없거나 기기가 잠겨 있으면 이유를 함께 준다 - 화면이 안내할 수 있어야 한다."""
        from storage import mtp

        class Broken:
            def devices(self):
                raise mtp.MtpError("기기가 응답하지 않습니다.")

        mtp.set_provider(mtp.MtpProvider(Broken()))
        r = self.api.mtp_devices()
        self.assertTrue(r["ok"])          # 오류가 아니라 "이유가 있는 빈 목록"이다
        self.assertEqual(r["data"]["devices"], [])
        self.assertIn("응답하지 않습니다", r["data"]["reason"])

    def test_an_unexpected_error_is_not_swallowed_into_a_silent_empty_list(self):
        """MtpError가 아닌 예외도 이유를 남긴다.

        예전에는 `except mtp.MtpError`만 있어서, COM이 던지는 다른 예외는 @guarded가
        받아 "ok=False"로 바뀌고 화면에는 그냥 빈 목록이 됐다 - 사용자에게는
        "눌러도 아무것도 없다"로만 보인다(실사용 피드백).
        """
        from storage import mtp

        class Exploding:
            def devices(self):
                raise OSError("COM이 응답하지 않습니다")

        mtp.set_provider(mtp.MtpProvider(Exploding()))
        r = self.api.mtp_devices()
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["devices"], [])
        self.assertIn("오류", r["data"]["reason"])

    def test_device_lookup_is_written_to_the_log(self):
        """기기 목록이 비었을 때 원인을 나중에라도 볼 수 있어야 한다(실사용 피드백 -
        "로그 자체가 남은 게 없다"). 요청과 결과가 모두 기록된다."""
        import logging

        with self.assertLogs("bridge.api", level=logging.INFO) as captured:
            self.api.mtp_devices()
        joined = "\n".join(captured.output)
        self.assertIn("MTP 기기 목록 요청", joined)
        self.assertIn("MTP 기기 목록 결과: 1개", joined)


class MtpCollectionTests(unittest.TestCase):
    """기기의 ES-DE 폴더를 Collection으로 열고 실제로 읽고 쓴다."""

    def setUp(self):
        self.dir = temp_root("rms_mtp_collection_")
        self.backend = use_fake_mtp(self)
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)

    def create(self, **kwargs):
        r = self.api.create_collection("Galaxy", "es-de", ESDE, "android", **kwargs)
        self.assertTrue(r["ok"], r.get("error"))
        cid = r["data"]["id"]
        wait_job(self.api, self.api.start_scan(cid)["data"]["jobId"])
        return cid

    def rows(self, cid, **kwargs):
        return {r["file"]: r for r in self.api.list_rows(cid, limit=50, **kwargs)["data"]["rows"]}

    def device_xml(self, system):
        from storage.mtp import MtpProvider

        data = MtpProvider(self.backend).read_bytes(f"{ESDE}/gamelists/{system}/gamelist.xml")
        return ET.fromstring(data)

    # ------------------------------------------------------------------
    def test_creates_a_collection_from_the_device_gamelists(self):
        cid = self.create()
        detail = self.api.collection_detail(cid)["data"]
        self.assertEqual(sorted(s["system"] for s in detail["systems"]), ["ps2", "snes"])
        self.assertEqual(detail["rootPath"], ESDE)

    def test_scan_reads_titles_from_the_device_without_any_local_file(self):
        cid = self.create()
        rows = self.rows(cid)
        self.assertEqual(rows["FFX (U).iso"]["title"], "Final Fantasy X")
        self.assertEqual(rows["SMW.sfc"]["title"], "Super Mario World")
        # ROM 폴더를 안 줬으므로 ROM 파일은 없는 것으로 본다(Metadata 전용).
        self.assertFalse(rows["FFX (U).iso"]["present"])

    def test_rom_listing_is_opt_in_via_the_rom_folder(self):
        """읽기만 하는 것은 전송이 아니라서 가능하다 - 폴더를 주면 ROM을 확인한다(사용자 결정)."""
        cid = self.create(rom_path=ROMS)
        rows = self.rows(cid)
        self.assertTrue(rows["FFX (U).iso"]["present"])
        self.assertEqual(rows["FFX (U).iso"]["size"], 2048)

    def test_a_device_without_roms_still_opens_as_a_metadata_collection(self):
        from storage.mtp import MtpProvider, set_provider

        set_provider(MtpProvider(build_mtp_device(with_roms=False)))
        cid = self.create()
        self.assertEqual(len(self.rows(cid)), 3)

    def test_the_storage_is_named_after_the_device_not_Internal(self):
        r = self.api.create_collection("Galaxy", "es-de", ESDE, "android", storage_label="Galaxy Test")
        detail = self.api.collection_detail(r["data"]["id"])["data"]
        self.assertEqual(detail["storages"][0]["label"], "Galaxy Test")

    def test_capacity_is_unknown_and_that_is_not_an_error(self):
        """용량을 못 읽는 저장소는 Capacity Check를 건너뛴다(스펙 §5)."""
        cid = self.create()
        capacity = self.api.plan_state(cid)["data"]["capacity"]
        self.assertEqual([c["capacityBytes"] for c in capacity], [64 * 1024 ** 3])

    # ------------------------------------------------------------------
    def test_editing_a_title_goes_into_the_plan_first(self):
        """기기 Collection의 편집은 Plan을 거친다(사용자 결정) - Apply해야 기기에 쓴다."""
        cid = self.create()
        uid = self.rows(cid)["SMW.sfc"]["romUid"]
        r = self.api.save_fields(cid, uid, {"name": "슈퍼 마리오 월드"})
        self.assertTrue(r["ok"], r.get("error"))
        self.assertTrue(r["data"]["planned"])

        state = self.api.plan_state(cid)["data"]
        self.assertEqual(state["edited"], 1)
        self.assertEqual(state["delta"], {})   # 용량은 바뀌지 않는다
        names = [g.findtext("name") for g in self.device_xml("snes").findall("game")]
        self.assertEqual(names, ["Super Mario World"])   # 아직 기기는 그대로다

        wait_job(self.api, self.api.start_apply(cid)["data"]["jobId"])
        names = [g.findtext("name") for g in self.device_xml("snes").findall("game")]
        self.assertIn("슈퍼 마리오 월드", names)

    def test_two_edits_to_one_game_keep_both(self):
        """한 항목을 두 번 고쳐도 Plan 엔트리는 하나 - 먼저 고친 값이 사라지면 안 된다."""
        cid = self.create()
        uid = self.rows(cid)["SMW.sfc"]["romUid"]
        self.api.save_fields(cid, uid, {"name": "슈퍼 마리오 월드"})
        self.api.save_fields(cid, uid, {"desc": "마리오가 공룡을 탄다"})
        self.assertEqual(self.api.plan_state(cid)["data"]["edited"], 1)

        wait_job(self.api, self.api.start_apply(cid)["data"]["jobId"])
        game = self.device_xml("snes").find("game")
        self.assertEqual(game.findtext("name"), "슈퍼 마리오 월드")
        self.assertEqual(game.findtext("desc"), "마리오가 공룡을 탄다")

    def test_a_cover_is_read_from_the_device_one_at_a_time(self):
        """커버는 선택한 항목부터 한 장씩 읽는다(사용자 결정) - 목록 전체를 미리 받지 않는다.

        `Path.read_bytes()`로는 기기 파일을 못 읽으므로 Provider를 거치는지 확인한다.
        """
        cid = self.create()
        uid = self.rows(cid)["FFX (U).iso"]["romUid"]
        r = self.api.get_media_image(cid, uid, "Covers")
        self.assertTrue(r["ok"], r.get("error"))
        self.assertTrue((r["data"] or "").startswith("data:image/png;base64,"))

    def test_a_write_failure_leaves_the_device_gamelist_intact(self):
        """MTP는 지우고 새로 만드는 수밖에 없다 - 실패하면 원본이 남아 있어야 한다."""
        cid = self.create()
        uid = self.rows(cid)["SMW.sfc"]["romUid"]
        self.api.save_fields(cid, uid, {"name": "안 써져야 한다"})
        self.backend.fail_next_creates = 1
        wait_job(self.api, self.api.start_apply(cid)["data"]["jobId"])
        names = [g.findtext("name") for g in self.device_xml("snes").findall("game")]
        self.assertEqual(names, ["Super Mario World"])

    # ------------------------------------------------------------------
    def test_a_metadata_only_collection_says_so(self):
        """ROM 폴더를 안 준 기기는 Metadata 전용 - 화면이 경고 대신 정상으로 그린다."""
        detail = self.api.collection_detail(self.create())["data"]
        self.assertTrue(detail["isDevice"])
        self.assertTrue(detail["metadataOnly"])

        with_roms = self.api.collection_detail(self.create(rom_path=ROMS))["data"]
        self.assertTrue(with_roms["isDevice"])
        self.assertFalse(with_roms["metadataOnly"])   # ROM을 읽을 수 있으면 전용이 아니다

    def test_file_operations_are_refused_with_a_reason(self):
        """MTP로는 대량 전송을 감당할 수 없다 - 막되 이유를 말해 준다(ADB 모드는 나중에)."""
        cid = self.create()
        uid = self.rows(cid)["SMW.sfc"]["romUid"]
        for result in (self.api.plan_delete(cid, [uid]),
                       self.api.orphan_metadata_preview(cid, "snes"),
                       self.api.media_cleanup(cid, "snes", ["covers"]),
                       self.api.plan_storage_change(cid, "snes", "internal"),
                       # mtp:// 경로는 탐색기가 열 수 있는 실제 경로가 아니다
                       # (실사용 피드백 §5의 "폴더 열기"도 기기에서는 막혀야 한다).
                       self.api.open_row_folder(cid, uid, "rom")):
            self.assertFalse(result["ok"])
            self.assertIn("ADB", result["error"])

    def test_generating_a_gamelist_creates_the_file_on_the_device(self):
        backend = build_mtp_device(with_roms=True)
        # gamelist가 없는 System을 하나 만든다 - ROM만 있는 상태.
        backend.put("Internal shared storage/ROMs/gba/Zelda (U).gba", b"z" * 128)
        from storage.mtp import MtpProvider, set_provider
        set_provider(MtpProvider(backend))

        cid = self.create(rom_path=ROMS)
        r = self.api.generate_metadata(cid, ["gba"])
        self.assertTrue(r["ok"], r.get("error"))
        created = MtpProvider(backend).read_bytes(f"{ESDE}/gamelists/gba/gamelist.xml")
        self.assertIsNotNone(created)
        self.assertIn(b"Zelda", created)


if __name__ == "__main__":
    unittest.main()
