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

    def test_the_rom_is_never_overwritten_in_any_mode(self):
        """사용자 결정(번복) - "롬은 항상 부차적인 asset". 대상에 ROM이 있으면 어느
        모드에서도 손대지 않으므로, ROM 충돌은 구조적으로 생길 수 없다."""
        before = (self.dst_root / "ps2" / "FFX.iso").read_bytes()
        for mode in ("patch", "overwrite", "replace"):
            self.api.plan_clear(self.d)
            result = self._paste(mode)
            self.assertEqual(self._rom_conflicts(), [], mode)
            for entry in self.api._plan(self.d).entries:
                self.assertFalse(entry.source.get("rom"), mode)
        self._apply()
        self.assertEqual((self.dst_root / "ps2" / "FFX.iso").read_bytes(), before)

    def test_include_rom_off_also_keeps_the_rom_out_of_the_check(self):
        """설정에서 ROM 복사를 끈 경우도 마찬가지다."""
        self.api.save_app_settings({"transfer": {"includeRom": False}})
        self._paste("overwrite")
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


class PasteOntoAnExplicitlyChosenRowInTheSameCollectionTests(unittest.TestCase):
    """실사용 버그 리포트 - "NES의 Dragon Ball Z1 (K).zip에 Dragon Ball 2 (K).zip을
    Replace로 덮어썼는데 결과가 똑같다. Compare가 아니라 Gamelist에서 했다."

    재현: 같은 Collection 안에서 이름이 다른 두 항목. 원본을 복사한 뒤 평범한
    붙여넣기(자동 파일명 매칭)를 하면 **원본 자신의 자리**에 다시 채워질 뿐, 노리던
    다른 이름의 대상은 전혀 건드리지 못한다 - "Plan에 오르고 Apply도 되는데 결과가
    똑같다"는 증상과 정확히 같다. 대상을 직접 지목해야(target_map) 그 행에 쓴다.
    """

    def setUp(self):
        self.dir = temp_root("rms_same_collection_target_")
        self.root = build_custom_esde_tree(self.dir / "c", "nes", [
            {"filename": "Dragon Ball 2 (K).zip", "title": "Dragon Ball 2 (K)", "genre": "RPG"},
            {"filename": "Dragon Ball Z1 (K).zip", "title": "Dragon Ball Z1 (K)"},
        ])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.c = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        scan(self.api, self.c)

    def _uid(self, filename):
        return next(r["romUid"] for r in self.api.list_rows(self.c, limit=50)["data"]["rows"]
                    if r["file"] == filename)

    def _title(self, filename):
        root = ET.parse(self.root / "gamelists" / "nes" / "gamelist.xml").getroot()
        game = next(g for g in root.findall("game")
                    if (g.findtext("path") or "").endswith(filename))
        return game.findtext("name")

    def test_plain_paste_never_reaches_a_different_named_row(self):
        """전제 확인 - 이게 사용자가 겪은 "결과가 똑같다"의 정체다."""
        self.api.copy_selection(self.c, [self._uid("Dragon Ball 2 (K).zip")])
        result = self.api.paste(self.c, "replace")
        self.assertTrue(result["ok"], result.get("error"))
        # 원본 자신의 자리로만 돌아간다 - 바뀔 게 없어 보통 건너뛴다.
        self.assertEqual(self._title("Dragon Ball Z1 (K).zip"), "Dragon Ball Z1 (K)",
                         "평범한 붙여넣기가 다른 이름의 행까지 건드렸다면 이 테스트 전제가 틀렸다")

    def test_target_map_reaches_the_explicitly_chosen_row(self):
        self.api.copy_selection(self.c, [self._uid("Dragon Ball 2 (K).zip")])
        result = self.api.paste(self.c, "replace",
                                target_map={"nes|Dragon Ball 2 (K).zip": "nes|Dragon Ball Z1 (K).zip"})
        self.assertTrue(result["ok"], result.get("error"))
        self.api.start_apply(self.c)
        wait_idle(self.api)
        self.assertEqual(self._title("Dragon Ball Z1 (K).zip"), "Dragon Ball 2 (K)")
        # 원본 항목은 그대로 남아 있다 - 옮긴 것이 아니라 내용을 복사한 것이다.
        self.assertEqual(self._title("Dragon Ball 2 (K).zip"), "Dragon Ball 2 (K)")

    def test_the_rom_is_not_moved_onto_the_different_filename(self):
        """이름이 다른 대상이다 - ROM을 그 이름으로 복사하면 확장자/식별이 깨진다."""
        self.api.copy_selection(self.c, [self._uid("Dragon Ball 2 (K).zip")])
        self.api.paste(self.c, "replace",
                       target_map={"nes|Dragon Ball 2 (K).zip": "nes|Dragon Ball Z1 (K).zip"})
        for entry in self.api._plan(self.c).entries:
            self.assertFalse(entry.source.get("rom"))

    def test_clipboard_items_reports_what_is_actually_copied(self):
        """이 항목에 붙여넣기 메뉴가 "정확히 하나만 복사됐는가"를 판단하는 데 쓴다."""
        empty = self.api.clipboard_items()
        self.assertFalse(empty["ok"])
        self.api.copy_selection(self.c, [self._uid("Dragon Ball 2 (K).zip")])
        result = self.api.clipboard_items()
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["data"]["count"], 1)
        self.assertEqual(result["data"]["items"][0]["filename"], "Dragon Ball 2 (K).zip")

    def test_clipboard_items_reports_more_than_one(self):
        self.api.copy_selection(self.c, [self._uid("Dragon Ball 2 (K).zip"),
                                         self._uid("Dragon Ball Z1 (K).zip")])
        result = self.api.clipboard_items()
        self.assertEqual(result["data"]["count"], 2)


class PasteReachesNamesThatCompareDeliberatelyLeavesApartTests(unittest.TestCase):
    """**붙여넣기와 Compare는 일부러 다른 기준을 쓴다.**

    - Compare는 1:1 표라 **파일명이 글자까지 같을 때만** 짝짓는다. 지역만 다른 판이
      여럿이면(`[EU] [KR] [JP] [World]`) 어느 것과 어느 것을 맺을지 정할 근거가 없다.
    - 붙여넣기는 그럴 근거가 있다. `app/gameid.py`가 지역과 디스크 번호까지 보고
      대상을 하나 고른다 - 그래서 **Compare에서 양쪽에 따로 남는 짝도 붙여넣기로는
      처리된다.**

    실제 사용자 데이터(msx2, 84개)에서 Plan에 올라간 개수: 0개 -> 76개(overwrite).
    """

    def setUp(self):
        self.dir = temp_root("rms_same_game_rule_")
        # 같은 게임인데 한쪽은 지역 태그, 한쪽은 풀네임 - Compare는 짝지어 준다.
        self.src_root = build_custom_esde_tree(self.dir / "src", "msx2", [
            {"filename": "Aleste [J].zip", "title": "Aleste", "genre": "Shooter", "size": 100},
        ])
        self.dst_root = build_custom_esde_tree(self.dir / "dst", "msx2", [
            {"filename": "Aleste (Japan) (T-En by Tsunami v1.0).zip", "title": "Aleste", "size": 180},
        ])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.s = self.api.create_collection("S", "es-de", str(self.src_root))["data"]["id"]
        self.d = self.api.create_collection("D", "es-de", str(self.dst_root))["data"]["id"]
        scan(self.api, self.s)
        scan(self.api, self.d)

    def _copy_all(self):
        uids = [r["romUid"] for r in self.api.list_rows(self.s)["data"]["rows"]]
        self.api.copy_selection(self.s, uids)

    def test_compare_leaves_them_on_their_own_sides(self):
        """Compare는 이름이 다르면 짝짓지 않는다 - 양쪽에 따로 남는다(사용자 결정)."""
        self.api.start_compare(self.s, self.d)
        rows = self.api.compare_rows()["data"]["rows"]
        self.assertEqual({r["status"] for r in rows}, {"only_a", "only_b"})
        self.api.exit_compare()

    def test_replace_adds_a_different_filename_as_a_new_item(self):
        """확장자까지 다른 ROM 이름은 유사해도 자동으로 합치지 않는다."""
        self._copy_all()
        result = self.api.paste(self.d, "replace")["data"]
        self.assertEqual(result["added"], 1,
                         f"Compare가 짝지은 게임에 붙지 않았다: {result['skipped']}")
        entry = self.api._plan(self.d).entries[0]
        self.assertEqual(entry.filename, "Aleste [J].zip")
        self.assertEqual(entry.payload.get("genre"), "Shooter")

    def test_every_mode_adds_a_separate_variant(self):
        """다른 ROM 이름은 세 명령 모두 별도 항목으로 취급한다."""
        for mode in ("patch", "overwrite", "replace"):
            self.api.plan_clear(self.d)
            self._copy_all()
            result = self.api.paste(self.d, mode)["data"]
            self.assertEqual(result["added"], 1, f"{mode}: {result['skipped']}")
            self.assertEqual(self.api._plan(self.d).entries[0].filename,
                             "Aleste [J].zip", mode)

    def test_the_rom_keeps_its_own_filename(self):
        self._copy_all()
        self.api.paste(self.d, "replace")
        for entry in self.api._plan(self.d).entries:
            self.assertEqual(entry.filename, "Aleste [J].zip")
            self.assertTrue(entry.source.get("rom"))


class SeveralCandidatesArePickedByARuleNotAtRandomTests(unittest.TestCase):
    """후보가 여럿이면 **정해진 순서**로 하나를 고른다(사용자 결정).

    파일명 -> 디스크 번호 -> 지역 -> 알파벳. 중요한 것은 "아무거나"가 임의가 아니라는
    점이다 - 같은 입력에는 늘 같은 답이 나와야 한다."""

    def setUp(self):
        self.dir = temp_root("rms_ambiguous_")
        self.src_root = build_custom_esde_tree(self.dir / "src", "snes", [
            {"filename": "Game.zip", "title": "Game", "genre": "RPG", "size": 100},
        ])
        self.dst_root = build_custom_esde_tree(self.dir / "dst", "snes", [
            {"filename": "Game (USA).zip", "title": "Game", "size": 200},
            {"filename": "Game (Europe).zip", "title": "Game", "size": 300},
        ])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.s = self.api.create_collection("S", "es-de", str(self.src_root))["data"]["id"]
        self.d = self.api.create_collection("D", "es-de", str(self.dst_root))["data"]["id"]
        scan(self.api, self.s)
        scan(self.api, self.d)

    def test_it_picks_the_first_by_name_and_always_the_same_one(self):
        uids = [r["romUid"] for r in self.api.list_rows(self.s)["data"]["rows"]]
        chosen = set()
        for _ in range(3):
            self.api.plan_clear(self.d)
            self.api.copy_selection(self.s, uids)
            result = self.api.paste(self.d, "replace")["data"]
            self.assertEqual(result["added"], 1, result["skipped"])
            chosen.add(self.api._plan(self.d).entries[0].filename)
        self.assertEqual(chosen, {"Game.zip"}, "다른 이름의 게임을 대상으로 삼으면 안 된다")

    def test_manual_designation_still_works(self):
        """모호하다고 막아 두기만 하면 안 된다 - 사람이 지목하면 그대로 간다."""
        uids = [r["romUid"] for r in self.api.list_rows(self.s)["data"]["rows"]]
        self.api.copy_selection(self.s, uids)
        result = self.api.paste(self.d, "replace",
                                target_map={"snes|Game.zip": "snes|Game (Europe).zip"})
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["data"]["added"], 1)
        self.assertEqual(self.api._plan(self.d).entries[0].filename, "Game (Europe).zip")


class TheSelectedRowIsTheTargetTests(unittest.TestCase):
    """**화면에서 고른 행이 대상이다.**

    사용자 모델: "A를 복사하고, B를 고르고, 붙여넣으면 B에 붙는다."
    예전 Ctrl+V는 고른 행을 **아예 보지 않고** 이름으로만 대상을 찾았다. 그래서 이름이
    전혀 다른 두 게임(`Final Fantasy 7.zip` <-> `ff7.rom`)은 화면에서 대상을 골라 놓고
    붙여넣어도 닿지 않았고, 사용자는 "왜 안 되는지" 알 수도 없었다.
    """

    def setUp(self):
        self.dir = temp_root("rms_selected_target_")
        self.src_root = build_custom_esde_tree(self.dir / "src", "ps2", [
            {"filename": "Final Fantasy 7.zip", "title": "Final Fantasy VII", "genre": "RPG"},
        ])
        self.dst_root = build_custom_esde_tree(self.dir / "dst", "ps2", [
            {"filename": "ff7.rom", "title": "ff7"},
            {"filename": "Other.zip", "title": "Other"},
        ])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.s = self.api.create_collection("S", "es-de", str(self.src_root))["data"]["id"]
        self.d = self.api.create_collection("D", "es-de", str(self.dst_root))["data"]["id"]
        scan(self.api, self.s)
        scan(self.api, self.d)

    def _copy_source(self):
        uid = next(r["romUid"] for r in self.api.list_rows(self.s)["data"]["rows"])
        self.api.copy_selection(self.s, [uid])

    def test_without_a_selection_it_becomes_a_new_entry(self):
        """전제 - 고른 행이 없으면 예전처럼 새 항목이 된다(이름이 다르니 당연하다)."""
        self._copy_source()
        self.api.paste(self.d, "replace")
        self.assertEqual([e.filename for e in self.api._plan(self.d).entries],
                         ["Final Fantasy 7.zip"])

    def test_the_selected_row_receives_it(self):
        self._copy_source()
        result = self.api.paste(self.d, "replace", fallback_target="ps2|ff7.rom")
        self.assertTrue(result["ok"], result.get("error"))
        entries = self.api._plan(self.d).entries
        self.assertEqual([e.filename for e in entries], ["ff7.rom"],
                         "고른 행이 아니라 새 항목을 만들었다")
        self.assertEqual(entries[0].payload.get("name"), "Final Fantasy VII")

    def test_it_works_in_every_mode(self):
        for mode in ("patch", "overwrite", "replace"):
            self.api.plan_clear(self.d)
            self._copy_source()
            self.api.paste(self.d, mode, fallback_target="ps2|ff7.rom")
            self.assertEqual([e.filename for e in self.api._plan(self.d).entries], ["ff7.rom"], mode)

    def test_the_rom_is_not_dragged_onto_the_other_name(self):
        self._copy_source()
        self.api.paste(self.d, "replace", fallback_target="ps2|ff7.rom")
        for entry in self.api._plan(self.d).entries:
            self.assertFalse(entry.source.get("rom"))

    def test_explicit_row_wins_over_an_exact_name_match(self):
        """한 항목을 행에 붙여넣으면 명시적으로 지목한 행이 우선한다."""
        # 대상에 원본과 **같은 이름**의 항목을 만들어 둔다.
        extra = build_custom_esde_tree(self.dir / "dst2", "ps2", [
            {"filename": "Final Fantasy 7.zip", "title": "예전 제목"},
            {"filename": "ff7.rom", "title": "ff7"},
        ])
        other = self.api.create_collection("D2", "es-de", str(extra))["data"]["id"]
        scan(self.api, other)
        self._copy_source()
        self.api.paste(other, "replace", fallback_target="ps2|ff7.rom")
        self.assertEqual([e.filename for e in self.api._plan(other).entries],
                         ["ff7.rom"], "지목한 행 대신 이름이 같은 다른 행에 붙였다")

    def test_several_copied_items_never_collapse_onto_one_row(self):
        """여러 개를 한 행에 붙일 수는 없다 - 고른 행은 무시하고 평소대로 간다."""
        uids = [r["romUid"] for r in self.api.list_rows(self.s)["data"]["rows"]]
        self.api.copy_selection(self.s, uids * 1)   # 이 원본은 1개지만 계약을 못박아 둔다
        self.assertEqual(len(uids), 1)


class PastingWithinOneCollectionTests(unittest.TestCase):
    """같은 Collection 안에서 A를 복사해 B에 붙이기(실사용 리포트의 Dragon Ball 사례).

    함정: 같은 Collection이라 이름으로 찾은 "확실한 대상"이 **원본 자기 자신**이다. 그것을
    대상으로 삼으면 아무 일도 일어나지 않는데, 사용자 눈에는 "Plan에 오르고 Apply도 되는데
    결과가 똑같다"로 보인다. 고른 행이 있으면 자기 자신보다 그 행이 우선이어야 한다.
    """

    def setUp(self):
        self.dir = temp_root("rms_within_one_")
        self.root = build_custom_esde_tree(self.dir / "c", "nes", [
            {"filename": "Dragon Ball 2 (K).zip", "title": "드래곤볼 II", "genre": "RPG"},
            {"filename": "Dragon Ball Z1 (K).zip", "title": "Dragon Ball Z1 (K)"},
        ])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.c = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        scan(self.api, self.c)

    def _uid(self, filename):
        return next(r["romUid"] for r in self.api.list_rows(self.c, limit=50)["data"]["rows"]
                    if r["file"] == filename)

    def _copy_source(self):
        self.api.copy_selection(self.c, [self._uid("Dragon Ball 2 (K).zip")])

    def test_the_selected_row_wins_over_the_source_itself(self):
        self._copy_source()
        result = self.api.paste(self.c, "overwrite", fallback_target="nes|Dragon Ball Z1 (K).zip")
        self.assertTrue(result["ok"], result.get("error"))
        entries = self.api._plan(self.c).entries
        self.assertEqual([e.filename for e in entries], ["Dragon Ball Z1 (K).zip"],
                         "원본 자기 자신이 대상으로 잡혀 고른 행이 무시됐다")
        self.assertEqual(entries[0].payload.get("name"), "드래곤볼 II")

    def test_it_applies_to_the_file_for_real(self):
        self._copy_source()
        self.api.paste(self.c, "overwrite", fallback_target="nes|Dragon Ball Z1 (K).zip")
        self.api.start_apply(self.c)
        wait_idle(self.api)
        root = ET.parse(self.root / "gamelists" / "nes" / "gamelist.xml").getroot()
        titles = {(g.findtext("path") or "").lstrip("./"): g.findtext("name")
                  for g in root.findall("game")}
        self.assertEqual(titles["Dragon Ball Z1 (K).zip"], "드래곤볼 II")
        self.assertEqual(titles["Dragon Ball 2 (K).zip"], "드래곤볼 II", "원본이 망가졌다")

    def test_without_a_selection_nothing_happens_and_that_is_honest(self):
        """고른 행이 없으면 자기 자신이 대상이라 바뀔 게 없다 - 조용히 넘어가지 말고
        이유를 말해야 한다."""
        self._copy_source()
        result = self.api.paste(self.c, "overwrite")["data"]
        self.assertEqual(result["added"], 0)
        self.assertTrue(result["skipped"][0]["reason"])

    def test_patch_keeps_the_targets_own_title(self):
        """모드의 뜻은 대상이 바뀌어도 그대로다 - Patch는 대상에 있는 값을 지킨다."""
        self._copy_source()
        self.api.paste(self.c, "patch", fallback_target="nes|Dragon Ball Z1 (K).zip")
        entry = self.api._plan(self.c).entries[0]
        self.assertEqual(entry.payload.get("name"), "Dragon Ball Z1 (K)")
        self.assertEqual(entry.payload.get("genre"), "RPG", "비어 있던 값은 채워야 한다")
