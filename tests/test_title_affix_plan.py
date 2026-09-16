"""Title Prefix/Postfix 일괄 적용 - 미리보기 -> Plan -> Apply(사용자 결정, app/title_affix.py).

Plan에 들어가는 유일한 텍스트 편집이라(D1의 예외, app/model/plan.py 머리말) 다른 Plan
작업(삭제, Storage 이동)과 같은 방식으로 검증한다: 미리보기는 아무것도 바꾸지 않고,
Plan에 올린 것은 Apply를 눌러야 실제 파일에 반영되며, Apply 직전 재검증도 거친다.
"""

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from bridge.api import Api
from tests.fixtures import temp_root, wait_job, write_file

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game>
    <path>./FFX (U).iso</path>
    <name>Final Fantasy X</name>
    <region>USA</region>
    <desc>A role-playing game.</desc>
  </game>
  <game>
    <path>./MGS2 (E).iso</path>
    <name>[EU] Metal Gear Solid 2</name>
    <region>Europe</region>
  </game>
  <game>
    <path>./Chrono (J).iso</path>
    <name>Chrono Trigger (Disc 1 of 2)</name>
    <region>Japan</region>
  </game>
  <game>
    <path>./Homebrew.iso</path>
    <name>Some Homebrew Game</name>
  </game>
</gameList>
"""

CONFIG = {
    "en": {"enabled": True, "mode": "prefix", "text": "EN"},
    "eu": {"enabled": True, "mode": "postfix", "text": "EU"},
    "jp": {"enabled": True, "mode": "prefix", "text": "JP"},
    "kr": {"enabled": False, "mode": "prefix", "text": "KR"},
    "global": {"enabled": False, "mode": "prefix", "text": "WORLD"},
}


class TitleAffixPlanTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_title_affix_")
        self.root = self.dir / "esde"
        (self.root / "gamelists" / "ps2").mkdir(parents=True)
        write_file(self.root / "gamelists" / "ps2" / "gamelist.xml", GAMELIST)
        (self.root / "ps2").mkdir()
        for name in ("FFX (U).iso", "MGS2 (E).iso", "Chrono (J).iso", "Homebrew.iso"):
            write_file(self.root / "ps2" / name, b"r" * 100)

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])
        self.assertTrue(self.api.save_app_settings({"titleAffix": CONFIG})["ok"])

    def uid(self, filename):
        rows = self.api.list_rows(self.cid, systems=["ps2"], limit=10)["data"]["rows"]
        return next(r["romUid"] for r in rows if r["file"] == filename)

    def gamelist_names(self):
        root = ET.parse(self.root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        return {Path(g.findtext("path")).name: g.findtext("name") for g in root.findall("game")}

    # ------------------------------------------------------------------
    def test_preview_strips_existing_decoration_and_applies_region_config(self):
        r = self.api.title_affix_preview(self.cid, system="ps2")
        self.assertTrue(r["ok"], r.get("error"))
        items = {i["filename"]: i for i in r["data"]["items"]}

        self.assertEqual(items["FFX (U).iso"]["newTitle"], "EN_Final Fantasy X")
        self.assertEqual(items["FFX (U).iso"]["regionBucket"], "en")
        self.assertTrue(items["FFX (U).iso"]["changed"])

        # 기존 [EU] 접두는 떼고, 설정대로 접미(postfix)로 다시 붙는다.
        self.assertEqual(items["MGS2 (E).iso"]["newTitle"], "Metal Gear Solid 2_EU")

        # 디스크 표시는 지역 장식과 분리해서 보존한다.
        self.assertEqual(items["Chrono (J).iso"]["newTitle"], "JP_Chrono Trigger (Disc 1 of 2)")
        self.assertEqual(items["Chrono (J).iso"]["diskMarker"], "(Disc 1 of 2)")

        # 파일명에 지역 태그가 없으면 미분류 - 자동 적용 대상에서 통째로 빠진다.
        self.assertEqual(items["Homebrew.iso"]["newTitle"], "Some Homebrew Game")
        self.assertFalse(items["Homebrew.iso"]["changed"])
        self.assertIsNone(items["Homebrew.iso"]["regionBucket"])

        self.assertEqual(r["data"]["changed"], 3)
        # 미리보기는 아무것도 쓰지 않는다.
        self.assertEqual(self.gamelist_names()["FFX (U).iso"], "Final Fantasy X")

    def test_preview_accepts_a_gamelist_selection_instead_of_a_whole_system(self):
        r = self.api.title_affix_preview(self.cid, rom_uids=[self.uid("FFX (U).iso")])
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual([i["filename"] for i in r["data"]["items"]], ["FFX (U).iso"])

    def test_an_untagged_filename_is_never_touched_even_with_every_region_enabled(self):
        """실사용 피드백: 태그가 없는 파일은 미분류로 두고 자동 적용에서 제외한다."""
        self.assertTrue(self.api.save_app_settings({"titleAffix": {
            bucket: {"enabled": True, "mode": "prefix", "text": bucket.upper()}
            for bucket in ("kr", "en", "jp", "eu", "global")
        }})["ok"])
        r = self.api.title_affix_preview(self.cid, rom_uids=[self.uid("Homebrew.iso")])
        item = r["data"]["items"][0]
        self.assertIsNone(item["regionBucket"])
        self.assertFalse(item["changed"])

    def test_missing_target_is_an_error_not_an_empty_success(self):
        self.assertFalse(self.api.title_affix_preview(self.cid, system="nonexistent")["ok"])
        self.assertFalse(self.api.title_affix_preview(self.cid, rom_uids=[999999])["ok"])

    # ------------------------------------------------------------------
    def test_plan_title_edit_only_adds_entries_that_actually_change(self):
        r = self.api.plan_title_edit(self.cid, system="ps2")
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["data"]["added"], 3)   # Homebrew.iso는 변경이 없어 빠진다

        state = self.api.plan_state(self.cid)["data"]
        self.assertEqual(state["retitled"], 3)
        self.assertEqual(state["marks"]["rows"]["ps2|FFX (U).iso"], "✎")
        self.assertNotIn("ps2|Homebrew.iso", state["marks"]["rows"])
        # Apply 전이므로 파일은 아직 그대로다.
        self.assertEqual(self.gamelist_names()["FFX (U).iso"], "Final Fantasy X")

    def test_apply_writes_the_new_titles_and_updates_the_cache(self):
        self.api.plan_title_edit(self.cid, system="ps2")
        job = self.api.start_apply(self.cid)
        self.assertTrue(job["ok"], job.get("error"))
        result = wait_job(self.api, job["data"]["jobId"])
        self.assertEqual(result["result"]["applied"], 3)

        names = self.gamelist_names()
        self.assertEqual(names["FFX (U).iso"], "EN_Final Fantasy X")
        self.assertEqual(names["MGS2 (E).iso"], "Metal Gear Solid 2_EU")
        self.assertEqual(names["Chrono (J).iso"], "JP_Chrono Trigger (Disc 1 of 2)")
        self.assertEqual(names["Homebrew.iso"], "Some Homebrew Game")   # 안 건드림

        rows = {r["file"]: r for r in self.api.list_rows(self.cid, systems=["ps2"], limit=10)["data"]["rows"]}
        self.assertEqual(rows["FFX (U).iso"]["title"], "EN_Final Fantasy X")
        self.assertEqual(self.api.plan_state(self.cid)["data"]["total"], 0)   # 성공한 항목은 Plan에서 빠진다

    def test_other_fields_survive_the_title_only_rewrite(self):
        self.api.plan_title_edit(self.cid, system="ps2")
        wait_job(self.api, self.api.start_apply(self.cid)["data"]["jobId"])
        root = ET.parse(self.root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        ffx = next(g for g in root.findall("game") if g.findtext("path") == "./FFX (U).iso")
        self.assertEqual(ffx.findtext("desc"), "A role-playing game.")
        self.assertEqual(ffx.findtext("region"), "USA")

    def test_a_title_changed_by_another_route_after_planning_is_not_silently_overwritten(self):
        """Plan을 만든 뒤 save_fields로 손으로 고치면, 그 사이 상태가 바뀐 항목은
        재검증(app/plan/validator.py)에 걸려 Apply가 덮어쓰지 않는다."""
        self.api.plan_title_edit(self.cid, system="ps2")
        self.api.save_fields(self.cid, self.uid("FFX (U).iso"), {"name": "손으로 고친 제목"})
        wait_job(self.api, self.api.start_apply(self.cid)["data"]["jobId"])
        self.assertEqual(self.gamelist_names()["FFX (U).iso"], "손으로 고친 제목")

    def test_disabling_every_region_still_strips_existing_decoration_but_nothing_more(self):
        """지역 장식을 끄더라도 1단계(기존 장식 떼기)는 여전히 일어난다 - "장식을 새로
        붙이지 않음"과 "아무것도 안 함"은 다르다. 이미 장식이 없던 항목만 진짜로
        변경이 없다."""
        self.api.save_app_settings({"titleAffix": {
            "en": {"enabled": False, "mode": "prefix", "text": ""},
            "eu": {"enabled": False, "mode": "prefix", "text": ""},
            "jp": {"enabled": False, "mode": "prefix", "text": ""},
        }})
        r = self.api.plan_title_edit(self.cid, system="ps2")
        self.assertEqual(r["data"]["added"], 1)   # [EU] Metal Gear Solid 2 -> Metal Gear Solid 2
        state = self.api.plan_state(self.cid)["data"]
        self.assertEqual(state["retitled"], 1)
        self.assertIn("ps2|MGS2 (E).iso", state["marks"]["rows"])
        self.assertNotIn("ps2|FFX (U).iso", state["marks"]["rows"])   # 장식이 없던 항목은 그대로


class TitleAffixStorageConflictTests(unittest.TestCase):
    """충돌한 System에는 Title Prefix/Postfix도 쓸 수 없다(다른 쓰기와 같은 가드)."""

    def setUp(self):
        self.dir = temp_root("rms_title_affix_conflict_")
        self.root = self.dir / "esde"
        (self.root / "gamelists" / "ps2").mkdir(parents=True)
        write_file(self.root / "gamelists" / "ps2" / "gamelist.xml", GAMELIST)
        (self.root / "ps2").mkdir()
        write_file(self.root / "ps2" / "FFX.iso", b"r" * 100)
        self.sd = self.dir / "sd"
        write_file(self.sd / "ps2" / "Other.iso", b"s" * 10)   # 같은 이름의 System 폴더 -> 충돌

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])
        self.api.add_external_storage(self.cid, "SD", str(self.sd))

    def test_preview_still_works_but_planning_is_blocked(self):
        preview = self.api.title_affix_preview(self.cid, system="ps2")
        self.assertTrue(preview["ok"], preview.get("error"))   # 읽기는 막지 않는다

        r = self.api.plan_title_edit(self.cid, system="ps2")
        self.assertFalse(r["ok"])
        self.assertIn("쓰기가 막혀", r["error"])


if __name__ == "__main__":
    unittest.main()
