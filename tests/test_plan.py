"""Plan 엔진 테스트.

Phase 3의 핵심은 "실제 파일은 확정 전까지 절대 바뀌지 않는다"와 "용량 계산이 실제
디스크 증감과 일치한다"이다. 두 가지를 파일 시스템으로 직접 확인한다.
"""

import tempfile
import unittest
from pathlib import Path

from app.model.plan import OP_ADD, OP_DELETE, OP_STORAGE_CHANGE, Plan, PlanEntry
from bridge.api import Api
from tests.fixtures import build_esde_tree, scan, wait_idle


class PlanModelTests(unittest.TestCase):
    def test_delta_accumulates_and_reverses(self):
        plan = Plan("c1")
        plan.add(PlanEntry(op=OP_ADD, system="ps2", filename="a.iso",
                           estimated_bytes=100, physical_delta={"internal": 100}))
        plan.add(PlanEntry(op=OP_ADD, system="ps2", filename="b.iso",
                           estimated_bytes=50, physical_delta={"internal": 50}))
        self.assertEqual(plan.delta(), {"internal": 150})

        plan.remove("add|ps2|a.iso")
        self.assertEqual(plan.delta(), {"internal": 50})
        plan.clear()
        self.assertEqual(plan.delta(), {})

    def test_same_target_replaces_instead_of_stacking(self):
        plan = Plan("c1")
        for _ in range(3):
            plan.add(PlanEntry(op=OP_ADD, system="ps2", filename="a.iso",
                               physical_delta={"internal": 100}))
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan.delta(), {"internal": 100})

    def test_marks_expose_row_and_system_level_changes(self):
        plan = Plan("c1")
        plan.add(PlanEntry(op=OP_ADD, system="ps2", filename="a.iso"))
        plan.add(PlanEntry(op=OP_DELETE, system="ps2", filename="b.iso"))
        plan.add(PlanEntry(op=OP_STORAGE_CHANGE, system="snes",
                           storage_from="internal", storage_to="ext-1"))
        marks = plan.marks()
        self.assertEqual(marks["rows"]["ps2|a.iso"], "+")
        self.assertEqual(marks["rows"]["ps2|b.iso"], "-")
        self.assertEqual(marks["systems"], ["snes"])


class PlanIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_plan_"))
        self.source_root = build_esde_tree(self.dir / "source")
        self.target_root = build_esde_tree(self.dir / "target")
        # 대상에서 ROM과 gamelist를 비워 "받는 쪽" 상태로 만든다.
        # 대상에서 FFX를 통째로 없앤다 - "대상에 없는 게임을 가져오는" 시나리오다.
        (self.target_root / "ps2" / "FFX.iso").unlink()
        (self.target_root / "downloaded_media" / "ps2" / "covers" / "FFX.png").unlink()
        (self.target_root / "downloaded_media" / "ps2" / "videos" / "FFX.mp4").unlink()

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("Source", "es-de", str(self.source_root))["data"]["id"]
        self.dst = self.api.create_collection("Target", "es-de", str(self.target_root))["data"]["id"]
        scan(self.api, self.src)
        scan(self.api, self.dst)

    def tearDown(self):
        self.api.close()

    def _uid(self, cid, filename):
        rows = self.api.list_rows(cid, limit=100)["data"]["rows"]
        return next(r["romUid"] for r in rows if r["file"] == filename)

    # ------------------------------------------------------------------
    # 복사 / 붙여넣기
    # ------------------------------------------------------------------
    def test_paste_does_not_touch_the_filesystem(self):
        self.api.copy_selection(self.src, [self._uid(self.src, "FFX.iso")])
        result = self.api.paste(self.dst)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["data"]["added"], 1)

        # 확정 전까지 실제 파일은 그대로다(스펙 §27).
        self.assertFalse((self.target_root / "ps2" / "FFX.iso").exists())

        state = self.api.plan_state(self.dst)["data"]
        self.assertEqual(state["added"], 1)
        self.assertEqual(state["marks"]["rows"]["ps2|FFX.iso"], "+")

    def test_plan_delta_matches_real_bytes_after_apply(self):
        self.api.copy_selection(self.src, [self._uid(self.src, "FFX.iso")])
        self.api.paste(self.dst)

        before = self.api.plan_state(self.dst)["data"]
        planned_delta = before["delta"]["internal"]
        actual_before = self.api.collection_detail(self.dst)["data"]["storages"][0]["actualBytes"]

        self.api.start_apply(self.dst)
        wait_idle(self.api)

        actual_after = self.api.collection_detail(self.dst)["data"]["storages"][0]["actualBytes"]
        self.assertEqual(actual_after - actual_before, planned_delta,
                         "Plan이 예측한 증가량과 실제 증가량이 달라졌다")

    def test_apply_copies_rom_media_and_metadata(self):
        self.api.copy_selection(self.src, [self._uid(self.src, "FFX.iso")])
        self.api.paste(self.dst)
        self.api.start_apply(self.dst)
        wait_idle(self.api)

        self.assertTrue((self.target_root / "ps2" / "FFX.iso").exists())
        self.assertTrue((self.target_root / "downloaded_media" / "ps2" / "covers" / "FFX.png").exists())

        rows = {r["file"]: r for r in self.api.list_rows(self.dst, limit=100)["data"]["rows"]}
        self.assertEqual(rows["FFX.iso"]["title"], "Final Fantasy X")

    def test_apply_preserves_frontend_specific_fields(self):
        self.api.copy_selection(self.src, [self._uid(self.src, "FFX.iso")])
        self.api.paste(self.dst)
        self.api.start_apply(self.dst)
        wait_idle(self.api)

        import xml.etree.ElementTree as ET
        root = ET.parse(self.target_root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        game = next(g for g in root.findall("game")
                    if (g.findtext("path") or "").strip() == "./FFX.iso")
        self.assertEqual(game.findtext("favorite"), "true")
        self.assertEqual(game.findtext("playcount"), "17")

    def test_plan_is_emptied_after_successful_apply(self):
        self.api.copy_selection(self.src, [self._uid(self.src, "FFX.iso")])
        self.api.paste(self.dst)
        self.api.start_apply(self.dst)
        wait_idle(self.api)
        self.assertEqual(self.api.plan_state(self.dst)["data"]["total"], 0)

    def test_same_size_but_unverified_file_is_a_conflict_not_a_silent_overwrite(self):
        """크기가 같다는 이유로 남의 파일을 덮어쓰면 안 된다.

        `같은 이름 + 같은 크기 + 다른 내용`은 ROM 관리에서 흔하다. 확신할 수 없으면
        사용자에게 묻는다(스펙 §85). 용량은 늘지 않지만 그것과 "덮어써도 된다"는
        전혀 다른 문제다.
        """
        self.api.copy_selection(self.src, [self._uid(self.src, "MGS2.iso")])
        self.api.paste(self.dst)
        state = self.api.plan_state(self.dst)["data"]
        self.assertEqual(state["added"], 1)
        self.assertEqual(state["conflicts"], 1, "같은 크기 파일이 충돌로 잡히지 않았다")
        self.assertEqual(state["delta"].get("internal", 0), 0)

    def test_byte_identical_copy_is_skipped_without_asking(self):
        """우리가(또는 다른 도구가) 복사해둔 파일은 타임스탬프까지 같다. 이건 묻지 않는다."""
        import shutil
        source = self.source_root / "ps2" / "MGS2.iso"
        # copy2는 수정 시각을 보존한다 - 복사 도구들이 하는 것과 같다.
        shutil.copy2(source, self.target_root / "ps2" / "MGS2.iso")

        self.api.copy_selection(self.src, [self._uid(self.src, "MGS2.iso")])
        self.api.paste(self.dst)
        state = self.api.plan_state(self.dst)["data"]
        self.assertEqual(state["conflicts"], 0, "이미 같은 파일인데 충돌로 물었다")
        self.assertEqual(state["delta"].get("internal", 0), 0)

    def test_paste_skips_items_whose_source_vanished(self):
        self.api.copy_selection(self.src, [self._uid(self.src, "FFX.iso")])
        (self.source_root / "ps2" / "FFX.iso").unlink()
        result = self.api.paste(self.dst)["data"]
        self.assertEqual(result["added"], 0)
        self.assertEqual(len(result["skipped"]), 1)

    # ------------------------------------------------------------------
    # 삭제
    # ------------------------------------------------------------------
    def test_delete_is_planned_then_applied(self):
        uid = self._uid(self.dst, "MGS2.iso")
        self.api.plan_delete(self.dst, [uid])

        state = self.api.plan_state(self.dst)["data"]
        self.assertEqual(state["marks"]["rows"]["ps2|MGS2.iso"], "-")
        self.assertLess(state["delta"]["internal"], 0)
        self.assertTrue((self.target_root / "ps2" / "MGS2.iso").exists(), "확정 전에 지워졌다")

        self.api.start_apply(self.dst)
        wait_idle(self.api)
        self.assertFalse((self.target_root / "ps2" / "MGS2.iso").exists())

    # ------------------------------------------------------------------
    # 부분 삭제 (사용자 결정 - 롬 삭제 / 메타데이터 삭제 / 미디어 삭제를 따로)
    # ------------------------------------------------------------------
    def _gamelist_paths(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(self.target_root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        return [g.findtext("path") for g in root.findall("game")]

    def _apply(self):
        self.api.start_apply(self.dst)
        wait_idle(self.api)

    def _give_cover(self, filename="MGS2"):
        """대상 Collection의 이 게임에 커버를 만들어 준다(기본 트리에는 FFX만 media가 있다)."""
        path = self.target_root / "downloaded_media" / "ps2" / "covers" / f"{filename}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"c" * 50)
        self.api.start_scan(self.dst, True)
        wait_idle(self.api)
        return path

    def test_rom_only_delete_keeps_metadata_and_media(self):
        media = self._give_cover()
        self.api.plan_delete(self.dst, [self._uid(self.dst, "MGS2.iso")], ["rom"])
        state = self.api.plan_state(self.dst)["data"]
        self.assertEqual(state["marks"]["rows"]["ps2|MGS2.iso"], "◐")      # 통째로 사라지는 - 가 아니다
        self.assertEqual(state["marks"]["deleteParts"]["ps2|MGS2.iso"], ["rom"])
        self._apply()
        self.assertFalse((self.target_root / "ps2" / "MGS2.iso").exists())
        self.assertTrue(media.exists(), "롬만 지우기로 했는데 media까지 지웠다")
        self.assertIn("./MGS2.iso", self._gamelist_paths(), "롬만 지우기로 했는데 메타데이터까지 지웠다")

    def test_metadata_delete_removes_gamelist_entry_and_media_but_keeps_the_rom(self):
        media = self._give_cover()
        self.api.plan_delete(self.dst, [self._uid(self.dst, "MGS2.iso")], ["metadata", "media", "video"])
        self._apply()
        self.assertTrue((self.target_root / "ps2" / "MGS2.iso").exists(), "메타데이터 삭제가 롬을 지웠다")
        self.assertFalse(media.exists())
        self.assertNotIn("./MGS2.iso", self._gamelist_paths())

    def test_media_only_delete_touches_neither_rom_nor_gamelist(self):
        media = self._give_cover()
        self.api.plan_delete(self.dst, [self._uid(self.dst, "MGS2.iso")], ["media"])
        self._apply()
        self.assertFalse(media.exists())
        self.assertTrue((self.target_root / "ps2" / "MGS2.iso").exists())
        self.assertIn("./MGS2.iso", self._gamelist_paths())

    def test_partial_delete_only_counts_the_bytes_it_will_free(self):
        self._give_cover()
        uid = self._uid(self.dst, "MGS2.iso")
        self.api.plan_delete(self.dst, [uid], ["media"])
        media_only = self.api.plan_state(self.dst)["data"]["deletedBytes"]
        self.api.plan_clear(self.dst)
        self.api.plan_delete(self.dst, [uid], ["rom"])
        rom_only = self.api.plan_state(self.dst)["data"]["deletedBytes"]
        self.api.plan_clear(self.dst)
        self.api.plan_delete(self.dst, [uid])
        everything = self.api.plan_state(self.dst)["data"]["deletedBytes"]
        self.assertEqual(everything, media_only + rom_only)

    def test_full_delete_still_uses_the_plain_minus_mark(self):
        self.api.plan_delete(self.dst, [self._uid(self.dst, "MGS2.iso")])
        marks = self.api.plan_state(self.dst)["data"]["marks"]
        self.assertEqual(marks["rows"]["ps2|MGS2.iso"], "-")

    def test_delete_needs_at_least_one_part(self):
        result = self.api.plan_delete(self.dst, [self._uid(self.dst, "MGS2.iso")], ["nothing"])
        self.assertFalse(result["ok"])

    # ------------------------------------------------------------------
    # Storage 이동
    # ------------------------------------------------------------------
    def test_storage_change_moves_only_roms(self):
        sd = self.dir / "sd"
        sd.mkdir()
        storage_id = self.api.add_external_storage(self.dst, "SD", str(sd))["data"]
        self.api.plan_storage_change(self.dst, "ps2", storage_id)

        state = self.api.plan_state(self.dst)["data"]
        self.assertEqual(state["moved"], 1)
        self.assertLess(state["delta"]["internal"], 0)
        self.assertGreater(state["delta"][storage_id], 0)
        self.assertTrue((self.target_root / "ps2" / "MGS2.iso").exists(), "확정 전에 옮겨졌다")

        self.api.start_apply(self.dst)
        wait_idle(self.api)

        self.assertTrue((sd / "ps2" / "MGS2.iso").exists(), "ROM이 새 Storage로 옮겨지지 않았다")
        self.assertFalse((self.target_root / "ps2" / "MGS2.iso").exists(), "원본이 남아 있다")
        # media는 Collection root에 남아야 한다(ES-DE 구조).
        self.assertTrue((self.target_root / "downloaded_media" / "ps2" / "covers").exists())

    # ------------------------------------------------------------------
    # 검증
    # ------------------------------------------------------------------
    def test_validation_flags_a_vanished_source(self):
        self.api.copy_selection(self.src, [self._uid(self.src, "FFX.iso")])
        self.api.paste(self.dst)
        (self.source_root / "ps2" / "FFX.iso").unlink()

        report = self.api.validate_plan(self.dst)["data"]
        self.assertFalse(report["ok"])
        self.assertEqual(len(report["entries"]), 1)
        self.assertIn("사라졌", report["entries"][0]["error"])

    def test_validation_flags_a_changed_source(self):
        self.api.copy_selection(self.src, [self._uid(self.src, "FFX.iso")])
        self.api.paste(self.dst)
        (self.source_root / "ps2" / "FFX.iso").write_bytes(b"different size")

        report = self.api.validate_plan(self.dst)["data"]
        self.assertFalse(report["ok"])
        self.assertIn("변경", report["entries"][0]["error"])

    def test_capacity_report_is_unknown_for_unreadable_storage(self):
        self.api.add_external_storage(self.dst, "Missing", r"Z:\\nope")
        capacity = self.api.plan_state(self.dst)["data"]["capacity"]
        missing = next(c for c in capacity if c["label"] == "Missing")
        self.assertIsNone(missing["capacityBytes"])
        self.assertFalse(missing["over"], "Unknown 용량은 초과로 판정하면 안 된다")

    def test_apply_requires_a_plan(self):
        self.assertFalse(self.api.start_apply(self.dst)["ok"])

    # ------------------------------------------------------------------
    # 인스턴스 간 (결정 D5)
    # ------------------------------------------------------------------
    def test_another_instance_can_paste_what_this_one_copied(self):
        self.api.copy_selection(self.src, [self._uid(self.src, "FFX.iso")])

        other = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        try:
            result = other.paste(self.dst)
            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["data"]["added"], 1)
            self.assertEqual(other.plan_state(self.dst)["data"]["added"], 1)
            # Plan은 인스턴스 로컬이다(D2) - 이쪽 창에는 안 보인다.
            self.assertEqual(self.api.plan_state(self.dst)["data"]["added"], 0)
        finally:
            other.close()

    def test_clipboard_survives_the_source_instance_closing(self):
        source_api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        uid = next(r["romUid"] for r in source_api.list_rows(self.src, limit=100)["data"]["rows"]
                   if r["file"] == "FFX.iso")
        source_api.copy_selection(self.src, [uid])
        source_api.close()

        # 복사한 창을 닫아도 붙여넣기가 동작해야 한다 - 메타데이터를 payload에 통째로
        # 실어두기 때문이다(§9.1).
        self.assertEqual(self.api.paste(self.dst)["data"]["added"], 1)

    def test_apply_lock_blocks_a_second_instance(self):
        self.api.copy_selection(self.src, [self._uid(self.src, "FFX.iso")])
        self.api.paste(self.dst)
        self.assertTrue(self.api.registry.acquire_lock(f"apply:{self.dst}", kind="apply"))

        other = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        try:
            other.copy_selection(self.src, [self._uid(self.src, "FFX.iso")])
            other.paste(self.dst)
            result = other.start_apply(self.dst)
            self.assertFalse(result["ok"])
            self.assertIn("다른 창", result["error"])
        finally:
            other.close()
            self.api.registry.release_lock(f"apply:{self.dst}")


if __name__ == "__main__":
    unittest.main()
