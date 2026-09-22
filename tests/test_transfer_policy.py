"""Collection → Collection 복사 정책(Settings > Import / Export)과 창 위치+크기 변경.

붙여넣기는 registry의 앱 설정(ui.settings.transfer)을 읽는다.
  - includeRom / includeMedia를 끄면 Plan에 그 파일을 올리지 않는다(메타데이터는 늘 간다).
  - conflict가 skip/overwrite면 **이번 붙여넣기로 생긴 충돌만** 그렇게 정한다.
기본값(ask)은 예전 동작 그대로다 - test_metadata_only_paste.py가 그 흐름을 검증한다.
"""

import unittest

from app.model.plan import RESOLVE_OVERWRITE, RESOLVE_SKIP
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root, wait_idle, write_file


class TransferPolicyTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_transfer_")
        self.src = build_custom_esde_tree(self.dir / "src", "ps2", [
            {"filename": "FFX.iso", "title": "Final Fantasy X", "genre": "RPG"},
            {"filename": "MGS2.iso", "title": "Metal Gear Solid 2", "genre": "Action"},
        ])
        write_file(self.src / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"c" * 40)
        write_file(self.src / "downloaded_media" / "ps2" / "covers" / "MGS2.png", b"c" * 40)
        # 받는 쪽에는 FFX ROM만 이미 있다 - FFX는 충돌, MGS2는 새 항목이다.
        self.dst = self.dir / "dst"
        write_file(self.dst / "ps2" / "FFX.iso", b"r" * 256)

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.s = self.api.create_collection("S", "es-de", str(self.src))["data"]["id"]
        self.d = self.api.create_collection("D", "es-de", str(self.dst))["data"]["id"]
        scan(self.api, self.s)
        scan(self.api, self.d)

    def paste_all(self, **policy):
        if policy:
            self.api.save_app_settings({"transfer": policy})
        uids = [r["romUid"] for r in self.api.list_rows(self.s, limit=50)["data"]["rows"]]
        self.api.copy_selection(self.s, uids)
        # ROM 충돌은 "ROM 교체"를 명시했을 때만 생긴다(게임 단위 전송 - app/plan/transfer.py)
        r = self.api.paste(self.d, "overwrite", None, True)
        self.assertTrue(r["ok"], r.get("error"))
        return r["data"]

    def entries(self):
        return {e.filename: e for e in self.api._plan(self.d).entries}

    def test_default_policy_keeps_conflicts_for_the_user(self):
        result = self.paste_all()
        self.assertEqual(result["policy"], {
            "pasteMode": "overwrite", "replaceRom": True, "includeRom": True, "includeMedia": True, "conflict": "ask",
            "unmatchedRom": {"mode": "skip", "metadata": True, "media": True, "video": True},
        })
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual([e.filename for e in self.api._plan(self.d).conflict_entries()], ["FFX.iso"])

    def test_conflict_skip_resolves_only_the_new_conflicts(self):
        result = self.paste_all(conflict="skip")
        self.assertEqual(result["conflicts"], 0)
        self.assertEqual(result["autoResolved"], 1)
        self.assertEqual(self.api._plan(self.d).conflict_entries(), [])
        self.assertEqual(self.entries()["FFX.iso"].resolution, RESOLVE_SKIP)

    def test_conflict_overwrite(self):
        self.paste_all(conflict="overwrite")
        self.assertEqual(self.entries()["FFX.iso"].resolution, RESOLVE_OVERWRITE)

    def test_existing_conflicts_in_the_plan_are_not_touched(self):
        self.paste_all()                                  # ask - FFX 충돌이 Plan에 남는다
        self.api.save_app_settings({"transfer": {"conflict": "skip"}})
        self.api.copy_selection(self.s, [r["romUid"] for r in self.api.list_rows(self.s, limit=50)["data"]["rows"]
                                         if r["file"] == "MGS2.iso"])
        self.api.paste(self.d, "overwrite", None, True)
        self.assertEqual([e.filename for e in self.api._plan(self.d).conflict_entries()], ["FFX.iso"])

    def test_media_off_does_not_plan_media(self):
        self.paste_all(includeMedia=False)
        for entry in self.entries().values():
            self.assertEqual(entry.source["media"], [], entry.filename)
        self.assertTrue(self.entries()["MGS2.iso"].source["rom"])

    def test_rom_off_pastes_metadata_without_rom_conflicts(self):
        result = self.paste_all(includeRom=False)
        self.assertEqual(result["conflicts"], 0)
        for entry in self.entries().values():
            self.assertFalse(entry.source["rom"], entry.filename)
            self.assertTrue(entry.payload, entry.filename)

    def test_rom_off_apply_writes_metadata_and_media_but_not_rom(self):
        self.paste_all(includeRom=False)
        job = self.api.start_apply(self.d)
        self.assertTrue(job["ok"], job.get("error"))
        wait_idle(self.api)
        result = self.api.get_job_progress(job["data"]["jobId"])["data"]
        self.assertNotEqual(result.get("status"), "error", result)
        self.assertFalse((self.dst / "ps2" / "MGS2.iso").exists())
        self.assertEqual((self.dst / "ps2" / "FFX.iso").read_bytes(), b"r" * 256)
        self.assertTrue((self.dst / "downloaded_media" / "ps2" / "covers" / "MGS2.png").exists())
        gamelist = (self.dst / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertIn("Metal Gear Solid 2", gamelist)
        self.assertIn("Final Fantasy X", gamelist)

    def test_invalid_stored_values_fall_back_to_defaults(self):
        result = self.paste_all(conflict="explode", includeRom=0)
        self.assertEqual(result["policy"]["conflict"], "ask")
        self.assertIs(result["policy"]["includeRom"], False)


class UnmatchedRomPolicyTests(unittest.TestCase):
    """원본에 ROM 파일이 없는 항목("ROM 미매칭") - Archive처럼 메타데이터만 있는 게임.

    기본은 아무것도 복사하지 않는다(사용자 결정). "복사"를 고르면 Metadata/Media/Video를
    독립적으로 켜고 끌 수 있다.
    """

    def setUp(self):
        self.dir = temp_root("rms_unmatched_")
        self.src = build_custom_esde_tree(self.dir / "src", "ps2", [
            {"filename": "Ghost.iso", "title": "Ghost Game", "genre": "Horror", "rom": False},
        ], with_media=True)
        write_file(self.src / "downloaded_media" / "ps2" / "covers" / "Ghost.png", b"c" * 40)
        (self.src / "downloaded_media" / "ps2" / "videos").mkdir(parents=True, exist_ok=True)
        write_file(self.src / "downloaded_media" / "ps2" / "videos" / "Ghost.mp4", b"v" * 80)

        self.dst = self.dir / "dst"
        (self.dst / "ps2").mkdir(parents=True)     # System은 있지만 이 게임은 전혀 없다
        (self.dst / "gamelists" / "ps2").mkdir(parents=True)   # ES-DE로 인식되려면 필요하다
        (self.dst / "downloaded_media").mkdir()

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.s = self.api.create_collection("S", "es-de", str(self.src))["data"]["id"]
        self.d = self.api.create_collection("D", "es-de", str(self.dst))["data"]["id"]
        scan(self.api, self.s)
        scan(self.api, self.d)

    def paste_ghost(self, **policy):
        if policy:
            self.api.save_app_settings({"transfer": policy})
        row = self.api.list_rows(self.s, limit=10)["data"]["rows"][0]
        self.assertFalse(row["present"], "이 테스트는 원본에 ROM이 없는 항목을 전제로 한다")
        self.api.copy_selection(self.s, [row["romUid"]])
        r = self.api.paste(self.d, "overwrite")
        self.assertTrue(r["ok"], r.get("error"))
        return r["data"]

    def test_default_skips_unmatched_rom_entirely(self):
        result = self.paste_ghost()
        self.assertEqual(result["added"], 0)
        self.assertEqual(len(self.api._plan(self.d).entries), 0)
        self.assertEqual([s["filename"] for s in result["skipped"]], ["Ghost.iso"])
        self.assertIn("ROM 미매칭", result["skipped"][0]["reason"])

    def test_copy_mode_with_everything_on_adds_metadata_and_media_and_video(self):
        result = self.paste_ghost(unmatchedRomMode="copy")
        self.assertEqual(result["added"], 1)
        entry = self.api._plan(self.d).entries[0]
        self.assertEqual(entry.payload.get("name"), "Ghost Game")
        types = {m["type"] for m in entry.source["media"]}
        self.assertEqual(types, {"covers", "videos"})

    def test_copy_mode_can_exclude_video_only(self):
        result = self.paste_ghost(unmatchedRomMode="copy", unmatchedRomVideo=False)
        self.assertEqual(result["added"], 1)
        entry = self.api._plan(self.d).entries[0]
        types = {m["type"] for m in entry.source["media"]}
        self.assertEqual(types, {"covers"})

    def test_copy_mode_can_exclude_media_only(self):
        result = self.paste_ghost(unmatchedRomMode="copy", unmatchedRomMedia=False)
        self.assertEqual(result["added"], 1)
        entry = self.api._plan(self.d).entries[0]
        types = {m["type"] for m in entry.source["media"]}
        self.assertEqual(types, {"videos"})

    def test_copy_mode_metadata_off_still_copies_media(self):
        result = self.paste_ghost(unmatchedRomMode="copy", unmatchedRomMetadata=False)
        self.assertEqual(result["added"], 1)
        entry = self.api._plan(self.d).entries[0]
        self.assertEqual(entry.payload, {})
        types = {m["type"] for m in entry.source["media"]}
        self.assertEqual(types, {"covers", "videos"})

    def test_copy_mode_with_everything_off_skips_like_default(self):
        result = self.paste_ghost(unmatchedRomMode="copy", unmatchedRomMetadata=False,
                                  unmatchedRomMedia=False, unmatchedRomVideo=False)
        self.assertEqual(result["added"], 0)
        self.assertEqual([s["filename"] for s in result["skipped"]], ["Ghost.iso"])

    def test_matched_rom_items_are_not_affected_by_unmatched_policy(self):
        # 같은 붙여넣기에 ROM이 있는 항목도 섞여 있으면, 미매칭 정책은 미매칭 항목에만 적용된다.
        write_file(self.src / "ps2" / "RealGame.iso", b"r" * 200)
        write_file(self.src / "gamelists" / "ps2" / "gamelist.xml",
                  (self.src / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
                  .replace("</gameList>",
                          "  <game><path>./RealGame.iso</path><name>Real Game</name></game>\n</gameList>"))
        scan(self.api, self.s, force=True)
        rows = self.api.list_rows(self.s, limit=10)["data"]["rows"]
        self.api.copy_selection(self.s, [r["romUid"] for r in rows])
        result = self.api.paste(self.d, "overwrite")["data"]
        self.assertEqual(result["added"], 1)   # RealGame만 (Ghost는 기본 정책으로 건너뜀)
        self.assertEqual([e.filename for e in self.api._plan(self.d).entries], ["RealGame.iso"])
        self.assertEqual([s["filename"] for s in result["skipped"]], ["Ghost.iso"])

    def test_the_unmatched_policy_never_gates_an_existing_target(self):
        """제안서 - "ROM 없음"이 "Game 없음"은 아니다. 대상 Game이 이미 있으면(ROM이 있든
        메타데이터만 있든) `unmatchedRom` 정책과 무관하게 평소 모드 그대로 메타데이터가
        가야 한다 - 정책의 기본값(skip)에 걸려 조용히 버려지면 안 된다."""
        write_file(self.dst / "ps2" / "Ghost.iso", b"r" * 256)
        write_file(self.dst / "gamelists" / "ps2" / "gamelist.xml",
                  '<?xml version="1.0"?><gameList>'
                  '<game><path>./Ghost.iso</path><name>Old Title</name></game></gameList>')
        scan(self.api, self.d, force=True)

        result = self.paste_ghost()  # 기본 정책(unmatchedRomMode="skip")을 그대로 둔다
        self.assertEqual(result["added"], 1, "대상이 이미 있는데도 기본 정책에 걸려 건너뛰었다")
        self.assertEqual(result["skipped"], [])
        entry = self.api._plan(self.d).entries[0]
        self.assertEqual(entry.payload.get("name"), "Ghost Game")
        self.assertFalse(entry.source.get("rom"), "대상에 이미 있는 ROM을 다시 옮기려 했다")

    def test_apply_copy_mode_writes_media_without_a_rom_file(self):
        self.paste_ghost(unmatchedRomMode="copy")
        job = self.api.start_apply(self.d)
        self.assertTrue(job["ok"], job.get("error"))
        wait_idle(self.api)
        result = self.api.get_job_progress(job["data"]["jobId"])["data"]
        self.assertNotEqual(result.get("status"), "error", result)
        self.assertFalse((self.dst / "ps2" / "Ghost.iso").exists())
        self.assertTrue((self.dst / "downloaded_media" / "ps2" / "covers" / "Ghost.png").exists())
        self.assertTrue((self.dst / "downloaded_media" / "ps2" / "videos" / "Ghost.mp4").exists())
        gamelist = (self.dst / "gamelists" / "ps2" / "gamelist.xml").read_text(encoding="utf-8")
        self.assertIn("Ghost Game", gamelist)

    def test_settings_default_reads_as_nested_policy_shape(self):
        policy = self.api._transfer_policy()
        self.assertEqual(policy["unmatchedRom"],
                         {"mode": "skip", "metadata": True, "media": True, "video": True})

    def test_invalid_stored_mode_falls_back_to_skip(self):
        self.api.save_app_settings({"transfer": {"unmatchedRomMode": "bogus"}})
        policy = self.api._transfer_policy()
        self.assertEqual(policy["unmatchedRom"]["mode"], "skip")


class WindowBoundsTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_winbounds_")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)

    def test_set_bounds_moves_then_resizes(self):
        calls = []

        class FakeWindow:
            def move(self, x, y): calls.append(("move", x, y))
            def resize(self, w, h): calls.append(("resize", w, h))

        self.api._window = FakeWindow()
        self.assertTrue(self.api.window_set_bounds(120.4, 80, 1000.6, 700)["ok"])
        self.assertEqual(calls, [("move", 120, 80), ("resize", 1000, 700)])


if __name__ == "__main__":
    unittest.main()
