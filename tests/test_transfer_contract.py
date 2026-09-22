"""전송 계약 - 제안서 §15의 검증 항목을 그대로 실행 가능한 형태로 옮긴 것.

각 계층의 책임이 지켜지는지를 본다.

    Match             = 같은 게임인가(판단 정보)
    Copy/Paste Mode   = 어떻게 옮길 것인가(실행 의도)
    Component 선택    = 무엇을 옮길 것인가
    Plan              = 실제로 무엇을 실행할 것인가
    File Operation    = 파일 시스템에서 안전한가

여기서 제일 중요한 것은 **위 결정이 아래로 손실 없이 전달되는가**다. 특히 옮기지 않기로 한
구성요소가 파일 충돌 검사에 끌려 들어가면 안 된다(§11).
"""

import unittest
import xml.etree.ElementTree as ET

from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root, wait_idle, write_file


class TransferContractTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_contract_")
        self.src_root = build_custom_esde_tree(self.dir / "src", "ps2", [
            {"filename": "FFX.iso", "title": "Final Fantasy X", "genre": "RPG", "size": 100},
        ])
        write_file(self.src_root / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"SRC-COVER" * 5)
        write_file(self.src_root / "downloaded_media" / "ps2" / "screenshots" / "FFX.png", b"SRC-SHOT" * 5)

        self.dst_root = build_custom_esde_tree(self.dir / "dst", "ps2", [
            {"filename": "FFX.iso", "title": "FFX", "size": 100},
        ])
        # 대상 ROM은 **원본과 다른 파일**이다 - ROM을 옮기지 않기로 했는데도 충돌이 나는지 보기 위한 것.
        write_file(self.dst_root / "ps2" / "FFX.iso", b"TARGET-ROM-DIFFERENT" * 9)
        write_file(self.dst_root / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"DST-COVER" * 7)

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.s = self.api.create_collection("S", "es-de", str(self.src_root))["data"]["id"]
        self.d = self.api.create_collection("D", "es-de", str(self.dst_root))["data"]["id"]
        scan(self.api, self.s)
        scan(self.api, self.d)

    # ------------------------------------------------------------------ 도구
    def _copy_all(self):
        uids = [r["romUid"] for r in self.api.list_rows(self.s)["data"]["rows"]]
        self.api.copy_selection(self.s, uids)

    def _paste(self, mode, **kw):
        self._copy_all()
        return self.api.paste(self.d, mode, **kw)["data"]

    def _apply(self):
        self.api.start_apply(self.d)
        wait_idle(self.api)

    def _fields(self, filename="FFX.iso"):
        root = ET.parse(self.dst_root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        game = next(g for g in root.findall("game")
                    if (g.findtext("path") or "").endswith(filename))
        return {tag: game.findtext(tag) for tag in ("name", "desc", "genre")}

    def _media(self, kind, filename="FFX.png"):
        path = self.dst_root / "downloaded_media" / "ps2" / kind / filename
        return path.read_bytes() if path.exists() else None

    def _rom_conflicts(self):
        return [e.filename for e in self.api._plan(self.d).conflict_entries()
                if any(c.get("kind") == "rom" for c in (e.conflicts or []))]

    # ------------------------------------------------------- §15.1 / §15.2
    def test_patch_keeps_the_target_and_only_fills_gaps(self):
        """§15.1 - Target 중심 병합. 있던 값과 미디어는 그대로, 없던 것만 채운다."""
        self._paste("patch")
        self._apply()
        self.assertEqual(self._media("covers"), b"DST-COVER" * 7, "Patch가 있던 커버를 덮어썼다")
        self.assertEqual(self._media("screenshots"), b"SRC-SHOT" * 5, "없던 스크린샷이 채워지지 않았다")
        self.assertEqual(self._fields()["genre"], "RPG", "비어 있던 값이 채워지지 않았다")

    def test_overwrite_lets_the_source_win(self):
        """§15.2 - Source 중심 병합."""
        self._paste("overwrite")
        self._apply()
        self.assertEqual(self._fields()["name"], "Final Fantasy X")
        self.assertEqual(self._media("covers"), b"SRC-COVER" * 5)

    # ---------------------------------------------------------------- §15.7
    def test_rom_left_out_never_becomes_a_file_conflict(self):
        """§15.7 - **이 제안서의 핵심.** 옮기지 않기로 한 ROM은 충돌 검사 대상 자체가 아니다.

        대상 ROM은 원본과 다른 파일이지만, ROM을 옮기지 않으므로 Metadata/Media 작업이
        ROM 때문에 막히면 안 된다.
        """
        result = self._paste("overwrite")
        self.assertEqual(self._rom_conflicts(), [], "옮기지도 않을 ROM이 충돌로 잡혔다")
        self.assertEqual(result["conflicts"], 0)
        self._apply()
        self.assertEqual(self._media("covers"), b"SRC-COVER" * 5, "ROM 충돌 때문에 Media가 막혔다")

    def test_rom_conflict_appears_only_when_replacing_the_rom_is_chosen(self):
        """§9 - ROM을 고른 경우에만 ROM이 파일 검사에 들어간다."""
        result = self._paste("overwrite", replace_rom=True)
        self.assertEqual(self._rom_conflicts(), ["FFX.iso"])
        self.assertEqual(result["conflicts"], 1)

    def test_include_rom_off_also_keeps_the_rom_out_of_the_check(self):
        """설정에서 ROM 복사를 끈 경우도 마찬가지다."""
        self.api.save_app_settings({"transfer": {"includeRom": False}})
        self._paste("overwrite", replace_rom=True)
        self.assertEqual(self._rom_conflicts(), [], "ROM을 끄고도 ROM이 충돌로 잡혔다")

    # ---------------------------------------------------------------- §15.5
    def test_compare_arrow_means_overwrite(self):
        """§15.5/§15.6 - Compare의 방향 명령은 Source 중심 갱신(OVERWRITE)이다."""
        self.api.start_compare(self.s, self.d)
        result = self.api.compare_copy_rows(["ps2|FFX.iso"], "toRight")
        self.assertTrue(result["ok"], result.get("error"))
        self.api.exit_compare()
        self._apply()
        self.assertEqual(self._fields()["name"], "Final Fantasy X",
                         "Compare의 >가 Source 기준으로 갱신하지 않았다")

    def test_compare_arrow_does_not_move_the_rom(self):
        """§15.7을 Compare 경로에서도 확인한다."""
        self.api.start_compare(self.s, self.d)
        self.api.compare_copy_rows(["ps2|FFX.iso"], "toRight")
        self.assertEqual(self._rom_conflicts(), [], "Compare의 >가 ROM을 끌고 들어왔다")


class ExplicitTargetTests(unittest.TestCase):
    """§15.3 / §15.4 - 자동 Match가 못 붙이거나 다른 게임이라고 본 짝에 **사용자가 명시적으로** 보낸다.

    제안서 §5: "Replace는 자동 Match 결과에 의해 제한되지 않는다." 파일명이 전혀 다른 두 항목을
    사용자가 직접 지목하면 그 대상에 써야 한다 - 새 항목을 만드는 것이 아니다.
    """

    def setUp(self):
        self.dir = temp_root("rms_explicit_")
        self.src_root = build_custom_esde_tree(self.dir / "src", "ps2", [
            {"filename": "Final Fantasy 7.zip", "title": "Final Fantasy VII", "genre": "RPG"},
        ])
        write_file(self.src_root / "downloaded_media" / "ps2" / "covers" / "Final Fantasy 7.png",
                   b"FF7-COVER" * 5)
        self.dst_root = build_custom_esde_tree(self.dir / "dst", "ps2", [
            {"filename": "ff7.rom", "title": "ff7"},
        ])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.s = self.api.create_collection("S", "es-de", str(self.src_root))["data"]["id"]
        self.d = self.api.create_collection("D", "es-de", str(self.dst_root))["data"]["id"]
        scan(self.api, self.s)
        scan(self.api, self.d)

    def _uid(self, cid, filename):
        return next(r["romUid"] for r in self.api.list_rows(cid, limit=50)["data"]["rows"]
                    if r["file"] == filename)

    def test_replace_onto_an_explicitly_chosen_target(self):
        """§15.3 - 사용자가 대상을 지목하면 그 항목에 쓴다. 새 항목을 만들지 않는다."""
        self.api.copy_selection(self.s, [self._uid(self.s, "Final Fantasy 7.zip")])
        result = self.api.paste(self.d, "replace",
                                target_map={"ps2|Final Fantasy 7.zip": "ps2|ff7.rom"})
        self.assertTrue(result["ok"], result.get("error"))
        self.api.start_apply(self.d)
        wait_idle(self.api)

        rows = {r["file"]: r for r in self.api.list_rows(self.d, limit=50)["data"]["rows"]}
        self.assertNotIn("Final Fantasy 7.zip", rows, "지목한 대상 대신 새 항목이 생겼다")
        self.assertEqual(rows["ff7.rom"]["title"], "Final Fantasy VII")

    def test_the_rom_is_not_dragged_along(self):
        """§15.3 - ROM은 끄고 Metadata/Media만 간다. 파일명이 다르므로 더더욱 옮기면 안 된다."""
        self.api.copy_selection(self.s, [self._uid(self.s, "Final Fantasy 7.zip")])
        self.api.paste(self.d, "replace", target_map={"ps2|Final Fantasy 7.zip": "ps2|ff7.rom"})
        entries = self.api._plan(self.d).entries
        self.assertTrue(entries, "Plan이 비어 있어 이 테스트는 아무것도 검증하지 못한다")
        for entry in entries:
            self.assertFalse(entry.source.get("rom"), "지목 전송이 ROM을 끌고 왔다")
        self.assertFalse((self.dst_root / "ps2" / "Final Fantasy 7.zip").exists())

    def test_media_lands_under_the_target_filename(self):
        """미디어는 **대상 파일명**으로 놓여야 프론트엔드가 찾는다."""
        self.api.copy_selection(self.s, [self._uid(self.s, "Final Fantasy 7.zip")])
        self.api.paste(self.d, "replace", target_map={"ps2|Final Fantasy 7.zip": "ps2|ff7.rom"})
        self.api.start_apply(self.d)
        wait_idle(self.api)
        self.assertTrue((self.dst_root / "downloaded_media" / "ps2" / "covers" / "ff7.png").exists(),
                        "미디어가 대상 파일명으로 놓이지 않았다")

    def test_the_match_result_is_not_rewritten_by_a_transfer(self):
        """§15.8 - 지목해서 보내는 것은 **이번 작업에 대한 승인**이지 "같은 게임이다"라는 선언이 아니다.

        Match 링크를 쓰는 것은 `apply_match()`뿐이어야 한다. 전송이 판단 정보를 몰래 고쳐 두면,
        다음에 사용자가 보는 Match 결과가 사용자가 정한 적 없는 값이 된다.
        """
        before = self.api.archive.match_links_of(self.d)
        self.api.copy_selection(self.s, [self._uid(self.s, "Final Fantasy 7.zip")])
        self.api.paste(self.d, "replace", target_map={"ps2|Final Fantasy 7.zip": "ps2|ff7.rom"})
        self.api.start_apply(self.d)
        wait_idle(self.api)
        self.assertEqual(self.api.archive.match_links_of(self.d), before,
                         "전송이 Match 결과를 바꿨다")

    def test_an_unknown_target_is_refused(self):
        """없는 대상을 지목하면 조용히 새 항목을 만들지 않고 거절한다."""
        self.api.copy_selection(self.s, [self._uid(self.s, "Final Fantasy 7.zip")])
        result = self.api.paste(self.d, "replace",
                                target_map={"ps2|Final Fantasy 7.zip": "ps2|nope.rom"})
        self.assertFalse(result["ok"])
        self.assertIn("nope.rom", result["error"], "다른 이유로 실패한 것을 통과로 읽고 있었다")
        self.assertEqual(self.api.plan_state(self.d)["data"]["total"], 0)


if __name__ == "__main__":
    unittest.main()


class CompareManualLinkTests(unittest.TestCase):
    """Compare에서 사람이 두 항목을 직접 이어 보낸다(제안서 §5, §15.3-15.4를 화면 경로로)."""

    def setUp(self):
        self.dir = temp_root("rms_manual_")
        self.src_root = build_custom_esde_tree(self.dir / "src", "ps2", [
            {"filename": "Final Fantasy 7.zip", "title": "Final Fantasy VII", "genre": "RPG"},
        ])
        write_file(self.src_root / "downloaded_media" / "ps2" / "covers" / "Final Fantasy 7.png",
                   b"FF7-COVER" * 5)
        self.dst_root = build_custom_esde_tree(self.dir / "dst", "ps2", [
            {"filename": "ff7.rom", "title": "ff7"},
        ])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.s = self.api.create_collection("S", "es-de", str(self.src_root))["data"]["id"]
        self.d = self.api.create_collection("D", "es-de", str(self.dst_root))["data"]["id"]
        scan(self.api, self.s)
        scan(self.api, self.d)
        self.api.start_compare(self.s, self.d)

    def test_automatic_pairing_leaves_them_apart(self):
        """전제 확인 - 자동 판단으로는 이 둘이 이어지지 않는다."""
        statuses = {r["file"]: r["status"] for r in self.api.compare_rows()["data"]["rows"]}
        self.assertEqual(statuses, {"Final Fantasy 7.zip": "only_a", "ff7.rom": "only_b"})

    def test_manual_link_writes_onto_the_chosen_target(self):
        result = self.api.compare_manual_copy("ps2|Final Fantasy 7.zip", "ps2|ff7.rom")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["data"]["targetFile"], "ff7.rom")
        self.api.exit_compare()
        self.api.start_apply(self.d)
        wait_idle(self.api)
        rows = {r["file"]: r for r in self.api.list_rows(self.d, limit=50)["data"]["rows"]}
        self.assertNotIn("Final Fantasy 7.zip", rows, "대상 대신 새 항목이 생겼다")
        self.assertEqual(rows["ff7.rom"]["title"], "Final Fantasy VII")

    def test_manual_link_does_not_move_the_rom(self):
        self.api.compare_manual_copy("ps2|Final Fantasy 7.zip", "ps2|ff7.rom")
        entries = self.api._plan(self.d).entries
        self.assertTrue(entries)
        for entry in entries:
            self.assertFalse(entry.source.get("rom"), "지목 전송이 ROM을 끌고 왔다")

    def test_the_direction_is_inferred_from_where_each_one_exists(self):
        """반대로 골라도 된다 - 어느 쪽에 있는지가 방향을 정한다."""
        result = self.api.compare_manual_copy("ps2|ff7.rom", "ps2|Final Fantasy 7.zip")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["data"]["targetFile"], "Final Fantasy 7.zip")
        self.assertEqual(result["data"]["targetId"], self.s)

    def test_two_items_on_the_same_side_are_refused(self):
        """둘 다 왼쪽에만 있으면 무엇을 어디로 보내려는지 알 수 없다."""
        self.assertFalse(self.api.compare_manual_copy(
            "ps2|Final Fantasy 7.zip", "ps2|Final Fantasy 7.zip")["ok"])

    def test_the_match_result_is_left_alone(self):
        """§15.8 - 이어서 보냈다고 Match가 SAME_GAME으로 바뀌지 않는다."""
        before = self.api.archive.match_links_of(self.d)
        self.api.compare_manual_copy("ps2|Final Fantasy 7.zip", "ps2|ff7.rom")
        self.assertEqual(self.api.archive.match_links_of(self.d), before)
