"""붙여넣기 모드(Patch / Overwrite / Replace).

같은 Ctrl+V가 목적에 따라 다르게 동작한다(사용자 결정):
  Patch(기본)  없는 것만 채운다. 대상에 있는 값과 미디어는 그대로 둔다.
  Overwrite    원본의 값과 미디어가 대상 것을 이긴다.
  Replace      이미 있는 항목은 원본을 무시한다. 없는 항목만 붙인다.
대상에 없는 항목은 어느 모드에서든 새로 붙는다.
"""

import shutil
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from bridge.api import Api
from tests.fixtures import (build_custom_esde_tree, build_esde_tree, scan, temp_root,
                            wait_idle, write_file)


class PasteModeTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_pastemode_")
        self.src_root = build_esde_tree(self.dir / "src")
        self.dst_root = build_esde_tree(self.dir / "dst")
        # 대상의 FFX: 설명이 비어 있고 장르가 다르고, 커버가 다른 그림이며, 영상이 없다.
        gl = self.dst_root / "gamelists" / "ps2" / "gamelist.xml"
        tree = ET.parse(gl)
        for game in tree.getroot().findall("game"):
            if (game.findtext("path") or "").endswith("FFX.iso"):
                game.find("desc").text = ""
                game.find("genre").text = "Action"
        tree.write(gl, encoding="utf-8", xml_declaration=True)
        (self.dst_root / "downloaded_media" / "ps2" / "videos" / "FFX.mp4").unlink()
        write_file(self.dst_root / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"TARGET-COVER-DIFFERENT" * 3)
        # 대상의 FFX ROM은 원본과 **같은 파일**이다(복사본) - ROM 충돌이 아니라 미디어/메타데이터만 다르다.
        shutil.copy2(self.src_root / "ps2" / "FFX.iso", self.dst_root / "ps2" / "FFX.iso")
        # 대상에서 MGS2를 통째로 없앤다 - "대상에 없는 항목"이다.
        (self.dst_root / "ps2" / "MGS2.iso").unlink()

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("S", "es-de", str(self.src_root))["data"]["id"]
        self.dst = self.api.create_collection("D", "es-de", str(self.dst_root))["data"]["id"]
        scan(self.api, self.src)
        scan(self.api, self.dst)
        self.addCleanup(self.api.close)

    def _copy_all(self):
        uids = [r["romUid"] for r in self.api.list_rows(self.src)["data"]["rows"]]
        self.api.copy_selection(self.src, uids)

    def _paste(self, mode):
        self._copy_all()
        return self.api.paste(self.dst, mode)["data"]

    def _apply(self):
        self.api.start_apply(self.dst)
        wait_idle(self.api)

    def _ffx(self):
        root = ET.parse(self.dst_root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        game = next(g for g in root.findall("game") if (g.findtext("path") or "").endswith("FFX.iso"))
        return {tag: game.findtext(tag) for tag in ("name", "desc", "genre")}

    def _cover(self):
        return (self.dst_root / "downloaded_media" / "ps2" / "covers" / "FFX.png").read_bytes()

    # ------------------------------------------------------------------ Patch
    def test_patch_fills_only_what_is_missing(self):
        self._paste("patch")
        self._apply()
        ffx = self._ffx()
        self.assertEqual(ffx["desc"], "A role-playing game.", "빈 설명이 채워지지 않았다")
        self.assertEqual(ffx["genre"], "Action", "Patch가 대상에 있던 값을 덮어썼다")

    def test_patch_keeps_the_existing_cover_but_adds_the_missing_video(self):
        self._paste("patch")
        self._apply()
        self.assertEqual(self._cover(), b"TARGET-COVER-DIFFERENT" * 3, "Patch가 있던 커버를 덮어썼다")
        self.assertTrue((self.dst_root / "downloaded_media" / "ps2" / "videos" / "FFX.mp4").exists(),
                        "없던 영상이 채워지지 않았다")

    def test_overwrite_is_the_default(self):
        self._copy_all()
        result = self.api.paste(self.dst)["data"]
        self.assertEqual(result["policy"]["pasteMode"], "overwrite")

    def test_patch_reports_why_an_item_was_left_out(self):
        """채울 것이 없는 항목은 Plan에 올리지 않고 이유를 알린다(사용자 결정)."""
        self._paste("patch")
        self._apply()
        self._copy_all()                      # 이제 대상이 원본이 가진 것을 다 가진 상태다
        result = self.api.paste(self.dst, "patch")["data"]
        reasons = [s["reason"] for s in result["skipped"] if s["filename"] == "FFX.iso"]
        self.assertTrue(reasons and "채울 것이 없습니다" in reasons[0], result["skipped"])
        self.assertEqual(result["added"], 0)
        self.assertEqual(self.api.plan_state(self.dst)["data"]["total"], 0)   # 올릴 것이 없다

    # -------------------------------------------------------------- Overwrite
    def test_overwrite_replaces_values_and_media_with_the_source(self):
        result = self._paste("overwrite")
        self.assertEqual(result["conflicts"], 0, "미디어만 충돌한 항목은 덮어쓰기 모드에서 바로 승인된다")
        self._apply()
        ffx = self._ffx()
        self.assertEqual(ffx["genre"], "RPG")
        self.assertEqual(ffx["desc"], "A role-playing game.")
        self.assertEqual(self._cover(), b"x" * 10)

    def test_overwrite_does_not_blank_a_target_value_with_an_empty_source_value(self):
        gl = self.src_root / "gamelists" / "ps2" / "gamelist.xml"
        tree = ET.parse(gl)
        for game in tree.getroot().findall("game"):
            if (game.findtext("path") or "").endswith("FFX.iso"):
                game.find("genre").text = ""
        tree.write(gl, encoding="utf-8", xml_declaration=True)
        scan(self.api, self.src, force=True) if "force" in scan.__code__.co_varnames else scan(self.api, self.src)
        self._paste("overwrite")
        self._apply()
        self.assertEqual(self._ffx()["genre"], "Action")

    # ---------------------------------------------------------------- Replace
    def test_replace_rebuilds_the_game_from_the_source(self):
        """완전 교체 - 원본을 무시하는 것이 아니라 게임의 Metadata/Media를 원본 것으로 다시 만든다.

        **한 개만 복사해서 붙인다** - 여러 개를 한 번에 붙이면 Replace는 Patch로 내려간다
        (사용자 결정, MultiPasteDowngradesReplaceTests 참고)."""
        uid = next(r["romUid"] for r in self.api.list_rows(self.src)["data"]["rows"]
                   if r["file"] == "FFX.iso")
        self.api.copy_selection(self.src, [uid])
        self.api.paste(self.dst, "replace")
        self._apply()
        ffx = self._ffx()
        self.assertEqual(ffx["desc"], "A role-playing game.")
        self.assertEqual(ffx["genre"], "RPG")
        self.assertEqual(self._cover(), b"x" * 10)

    def test_the_rom_is_never_touched_even_when_it_differs(self):
        """대상 ROM이 아주 다른 파일이어도 건드리지 않는다(사용자 결정 - 덮어쓰지 않는다)."""
        (self.dst_root / "ps2" / "FFX.iso").write_bytes(b"DIFFERENT-ROM-BYTES")
        scan(self.api, self.dst)
        self._copy_all()
        kept = self.api.paste(self.dst, "overwrite")["data"]
        self.assertEqual(kept["conflicts"], 0)
        self.assertEqual([e.filename for e in self.api._plan(self.dst).conflict_entries()], [])
        self._apply()
        self.assertEqual((self.dst_root / "ps2" / "FFX.iso").read_bytes(), b"DIFFERENT-ROM-BYTES")

    # --------------------------------------------------------------- 공통
    def test_items_missing_from_the_target_are_added_in_every_mode(self):
        for mode in ("patch", "overwrite", "replace"):
            self.api.plan_clear(self.dst)
            self._paste(mode)
            keys = self.api.plan_state(self.dst)["data"]["marks"]["rows"]
            self.assertEqual(keys.get("ps2|MGS2.iso"), "+", f"{mode}에서 대상에 없는 항목이 추가되지 않았다")

    def test_replace_still_brings_a_missing_rom_but_leaves_the_metadata_alone(self):
        """gamelist에 항목만 있고 ROM이 없는 쪽은 "없는 것"이다 - Replace도 ROM은 채운다."""
        self._paste("replace")
        self._apply()
        self.assertTrue((self.dst_root / "ps2" / "MGS2.iso").exists())

    def test_unknown_mode_falls_back_to_overwrite(self):
        self._copy_all()
        result = self.api.paste(self.dst, "nonsense")["data"]
        self.assertEqual(result["policy"]["pasteMode"], "overwrite")

    def test_the_mode_can_be_saved_in_settings(self):
        self.api.save_app_settings({"transfer": {"pasteMode": "overwrite"}})
        self._copy_all()
        result = self.api.paste(self.dst)["data"]
        self.assertEqual(result["policy"]["pasteMode"], "overwrite")


if __name__ == "__main__":
    unittest.main()


class PasteIntoAnotherSystemTests(unittest.TestCase):
    """System 이름이 달라도 고른 System으로 붙여넣는다(사용자 결정 - Pegasus의 `FBNEO ACT` → ES-DE)."""

    def setUp(self):
        self.dir = temp_root("rms_sysmap_")
        self.src_root = build_esde_tree(self.dir / "src")
        # 원본에만 있는 System - ES-DE가 허용하지 않는 이름이라고 치자.
        write_file(self.src_root / "fbneo act" / "1941.zip", b"r" * 40)
        write_file(self.src_root / "gamelists" / "fbneo act" / "gamelist.xml",
                   '<?xml version="1.0"?>\n<gameList><game><path>./1941.zip</path>'
                   '<name>1941</name></game></gameList>')
        self.dst_root = build_esde_tree(self.dir / "dst")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.src = self.api.create_collection("S", "es-de", str(self.src_root))["data"]["id"]
        self.dst = self.api.create_collection("D", "es-de", str(self.dst_root))["data"]["id"]
        scan(self.api, self.src)
        scan(self.api, self.dst)

    def _copy_1941(self):
        uid = next(r["romUid"] for r in self.api.list_rows(self.src, limit=99)["data"]["rows"]
                   if r["file"] == "1941.zip")
        self.api.copy_selection(self.src, [uid])

    def _apply(self):
        self.api.start_apply(self.dst)
        wait_idle(self.api)

    def test_it_reports_which_systems_the_target_lacks(self):
        self._copy_1941()
        data = self.api.clipboard_systems(self.dst)["data"]
        entry = next(s for s in data["systems"] if s["system"] == "fbneo act")
        self.assertFalse(entry["exists"])
        self.assertEqual(entry["count"], 1)
        self.assertIn("ps2", data["targetSystems"])

    def test_pasting_with_a_map_puts_the_rom_in_the_chosen_system(self):
        self._copy_1941()
        result = self.api.paste(self.dst, "patch", {"fbneo act": "ps2"})
        self.assertTrue(result["ok"], result.get("error"))
        self._apply()
        self.assertTrue((self.dst_root / "ps2" / "1941.zip").exists())
        self.assertFalse((self.dst_root / "fbneo act").exists())
        rows = {r["file"]: r for r in self.api.list_rows(self.dst, limit=99)["data"]["rows"]}
        self.assertEqual(rows["1941.zip"]["system"], "ps2")

    def test_system_target_preview_and_new_only_paste(self):
        self._copy_1941()
        preview = self.api.clipboard_system_target(self.dst, "ps2")
        self.assertTrue(preview["ok"], preview.get("error"))
        self.assertEqual(preview["data"]["count"], 1)
        self.assertEqual(preview["data"]["duplicates"], [])
        self.assertEqual(preview["data"]["items"][0]["system"], "fbneo act")
        result = self.api.paste(self.dst, "patch", {"fbneo act": "ps2"}, None, None, True)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["data"]["added"], 1)
        self._apply()
        self.assertTrue((self.dst_root / "ps2" / "1941.zip").exists())

    def test_system_new_only_rejects_same_game_before_staging(self):
        # Filename differs, but the shared game identity still sees the same game.
        write_file(self.dst_root / "ps2" / "1941.iso", b"existing")
        scan(self.api, self.dst)
        self._copy_1941()
        preview = self.api.clipboard_system_target(self.dst, "ps2")
        self.assertEqual(preview["data"]["duplicates"][0]["targetFilename"], "1941.iso")
        result = self.api.paste(self.dst, "overwrite", {"fbneo act": "ps2"}, None, None, True)
        self.assertFalse(result["ok"])
        self.assertIn("이미", result["error"])
        self.assertEqual(self.api.plan_state(self.dst)["data"]["total"], 0)

    def test_system_target_requires_clipboard_and_existing_system(self):
        empty = self.api.clipboard_system_target(self.dst, "ps2")
        self.assertEqual(empty["data"]["count"], 0)
        self._copy_1941()
        missing = self.api.clipboard_system_target(self.dst, "not-a-system")
        self.assertFalse(missing["ok"])
        result = self.api.paste(self.dst, "patch", {"fbneo act": "not-a-system"}, None, None, True)
        self.assertFalse(result["ok"])

    def test_without_a_map_the_original_name_is_kept(self):
        self._copy_1941()
        self.api.paste(self.dst, "patch")
        self._apply()
        self.assertTrue((self.dst_root / "fbneo act" / "1941.zip").exists())

    def test_an_empty_choice_is_ignored(self):
        self._copy_1941()
        self.api.paste(self.dst, "patch", {"fbneo act": "  "})
        self._apply()
        self.assertTrue((self.dst_root / "fbneo act" / "1941.zip").exists())

    def test_clipboard_systems_needs_something_copied(self):
        self.assertFalse(self.api.clipboard_systems(self.dst)["ok"])


class SameCollectionFixedSystemPasteTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_same_collection_system_paste_")
        self.root = build_esde_tree(self.dir / "root")
        (self.root / "fbneo").mkdir()
        write_file(self.root / "fbneo" / "existing.zip", b"existing")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.collection = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        scan(self.api, self.collection)
        rows = self.api.list_rows(self.collection, limit=99)["data"]["rows"]
        source = next(row for row in rows if row["file"] == "FFX.iso")
        self.api.copy_selection(self.collection, [source["romUid"]])

    def test_system_target_preview_and_paste_reject_other_system(self):
        preview = self.api.clipboard_system_target(self.collection, "fbneo")
        self.assertFalse(preview["ok"])
        result = self.api.paste(self.collection, "patch", {"ps2": "fbneo"},
                                new_only=True)
        self.assertFalse(result["ok"])
        self.assertIn("다른 System", result["error"])
        self.assertEqual(self.api.plan_state(self.collection)["data"]["total"], 0)

    def test_explicit_row_target_in_other_system_is_rejected(self):
        result = self.api.paste(self.collection, "overwrite", target_map={
            "ps2|FFX.iso": "fbneo|existing.zip"})
        self.assertFalse(result["ok"])
        self.assertEqual(self.api.plan_state(self.collection)["data"]["total"], 0)

    def test_fallback_row_in_other_system_is_rejected(self):
        result = self.api.paste(self.collection, "overwrite",
                                fallback_target="fbneo|existing.zip")
        self.assertFalse(result["ok"])
        self.assertEqual(self.api.plan_state(self.collection)["data"]["total"], 0)

    def test_same_system_target_is_still_available(self):
        preview = self.api.clipboard_system_target(self.collection, "ps2")
        self.assertTrue(preview["ok"], preview.get("error"))


class MultiPasteDowngradesReplaceTests(unittest.TestCase):
    """여러 개를 한 번에 붙일 때 Replace는 Patch로 내려간다(사용자 결정).

    Replace는 대상의 메타데이터를 원본 것으로 다시 만드는(= 원본에 없는 값은 지우는)
    모드라, 수십~수백 개에 한꺼번에 걸면 되돌리기 어렵다. **조용히 바꾸지 않고**
    `downgradedFrom`으로 알려 화면이 모드 토글에서 밝힐 수 있게 한다.
    """

    def setUp(self):
        self.dir = temp_root("rms_multi_downgrade_")
        self.src_root = build_custom_esde_tree(self.dir / "src", "ps2", [
            {"filename": "A.iso", "title": "A 새 제목"},
            {"filename": "B.iso", "title": "B 새 제목"},
        ])
        self.dst_root = build_custom_esde_tree(self.dir / "dst", "ps2", [
            {"filename": "A.iso", "title": "A", "genre": "RPG"},
            {"filename": "B.iso", "title": "B", "genre": "Action"},
        ])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.s = self.api.create_collection("S", "es-de", str(self.src_root))["data"]["id"]
        self.d = self.api.create_collection("D", "es-de", str(self.dst_root))["data"]["id"]
        scan(self.api, self.s)
        scan(self.api, self.d)

    def _copy(self, *files):
        uids = [r["romUid"] for r in self.api.list_rows(self.s, limit=50)["data"]["rows"]
                if r["file"] in files]
        self.api.copy_selection(self.s, uids)

    def test_one_item_keeps_replace(self):
        self._copy("A.iso")
        result = self.api.paste(self.d, "replace")["data"]
        self.assertIsNone(result["downgradedFrom"])
        self.assertEqual(result["policy"]["pasteMode"], "replace")

    def test_several_items_fall_back_to_patch_and_say_so(self):
        self._copy("A.iso", "B.iso")
        result = self.api.paste(self.d, "replace")["data"]
        self.assertEqual(result["downgradedFrom"], "replace")
        self.assertEqual(result["policy"]["pasteMode"], "patch")

    def test_the_downgrade_really_behaves_like_patch(self):
        """Patch는 대상에 있는 값을 지킨다 - Replace였다면 genre가 사라졌을 것이다."""
        self._copy("A.iso", "B.iso")
        self.api.paste(self.d, "replace")
        self.api.start_apply(self.d)
        wait_idle(self.api)
        rows = {r["file"]: r for r in self.api.list_rows(self.d, limit=50)["data"]["rows"]}
        self.assertEqual(rows["A.iso"]["title"], "A", "Patch인데 대상 제목이 바뀌었다")
        self.assertEqual(rows["A.iso"]["genre"], "RPG", "Replace처럼 값이 지워졌다")

    def test_other_modes_are_never_downgraded(self):
        for mode in ("patch", "overwrite"):
            self.api.plan_clear(self.d)
            self._copy("A.iso", "B.iso")
            result = self.api.paste(self.d, mode)["data"]
            self.assertIsNone(result["downgradedFrom"], mode)
            self.assertEqual(result["policy"]["pasteMode"], mode)


class DiscTitlesAreAppliedOnApplyTests(unittest.TestCase):
    """옵션을 켜면 **Apply할 때** 제목 뒤에 장 번호가 붙는다(사용자 결정).
    파일명은 건드리지 않는다."""

    def setUp(self):
        self.dir = temp_root("rms_disc_titles_")
        self.src_root = build_custom_esde_tree(self.dir / "src", "psx", [
            {"filename": "Metal Gear Solid (Disc 1 of 2).bin", "title": "Metal Gear Solid"},
            {"filename": "Metal Gear Solid (Disc 2 of 2).bin", "title": "Metal Gear Solid"},
        ])
        self.dst_root = build_custom_esde_tree(self.dir / "dst", "psx", [])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.s = self.api.create_collection("S", "es-de", str(self.src_root))["data"]["id"]
        self.d = self.api.create_collection("D", "es-de", str(self.dst_root))["data"]["id"]
        scan(self.api, self.s)
        scan(self.api, self.d)

    def _paste_and_apply(self):
        uids = [r["romUid"] for r in self.api.list_rows(self.s, limit=50)["data"]["rows"]]
        self.api.copy_selection(self.s, uids)
        self.api.paste(self.d, "patch")
        self.api.start_apply(self.d)
        wait_idle(self.api)
        return {r["file"]: r["title"] for r in self.api.list_rows(self.d, limit=50)["data"]["rows"]}

    def test_off_by_default(self):
        titles = self._paste_and_apply()
        self.assertEqual(set(titles.values()), {"Metal Gear Solid"})

    def test_on_appends_the_disc_number_to_the_title_only(self):
        self.api.save_app_settings({"metadata": {"discTitles": True}})
        titles = self._paste_and_apply()
        self.assertEqual(titles["Metal Gear Solid (Disc 1 of 2).bin"], "Metal Gear Solid (Disc 1/2)")
        self.assertEqual(titles["Metal Gear Solid (Disc 2 of 2).bin"], "Metal Gear Solid (Disc 2/2)")
        # 파일명은 그대로다.
        self.assertTrue((self.dst_root / "psx" / "Metal Gear Solid (Disc 1 of 2).bin").exists())

    def test_the_chosen_format_is_used(self):
        self.api.save_app_settings({"metadata": {"discTitles": True,
                                                 "discTitleFormat": "bracket_word_of"}})
        titles = self._paste_and_apply()
        self.assertEqual(titles["Metal Gear Solid (Disc 1 of 2).bin"],
                         "Metal Gear Solid [Disc 1 of 2]")

    def test_an_unknown_format_falls_back_to_the_default(self):
        self.api.save_app_settings({"metadata": {"discTitles": True, "discTitleFormat": "nope"}})
        titles = self._paste_and_apply()
        self.assertEqual(titles["Metal Gear Solid (Disc 1 of 2).bin"], "Metal Gear Solid (Disc 1/2)")
