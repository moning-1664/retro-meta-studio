"""Plan Apply의 실패 복구 테스트 (실패 주입).

정상 경로는 `test_plan.py`가 본다. 여기서는 **실패했을 때 데이터가 망가지지 않는지**를
본다. ROM 관리 도구에서 가장 위험한 것은 기능이 없는 게 아니라 "정상 상황에서는 잘
되는데 예외 상황에서 DB와 실제 파일 상태가 서로 달라지는 것"이다.

각 테스트는 실제 실패 모드를 주입하고, 그 뒤 파일 시스템과 Registry가 서로 어긋나지
않는지 확인한다.
"""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import file_ops
from app.model.plan import STATUS_FAILED, STATUS_PARTIAL
from bridge.api import Api
from tests.test_es_de_adapter import build_esde_tree


def wait_idle(api, timeout=15.0):
    if not api.jobs.wait_idle(timeout):
        raise AssertionError("작업이 끝나지 않았습니다.")


class PlanRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_recover_"))
        self.source_root = build_esde_tree(self.dir / "source")
        self.target_root = build_esde_tree(self.dir / "target")
        # 대상에서 FFX를 통째로 없앤다 - "대상에 없는 게임을 가져오는" 시나리오다.
        (self.target_root / "ps2" / "FFX.iso").unlink()
        (self.target_root / "downloaded_media" / "ps2" / "covers" / "FFX.png").unlink()
        (self.target_root / "downloaded_media" / "ps2" / "videos" / "FFX.mp4").unlink()
        # 부분 이동 실패를 재현하려면 옮길 ROM이 둘 이상이어야 한다.
        (self.target_root / "ps2" / "EXTRA.iso").write_bytes(b"e" * 500)

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("Source", "es-de", str(self.source_root))["data"]["id"]
        self.dst = self.api.create_collection("Target", "es-de", str(self.target_root))["data"]["id"]
        for cid in (self.src, self.dst):
            self.api.start_scan(cid)
            wait_idle(self.api)

    def tearDown(self):
        self.api.close()

    def _uid(self, cid, filename):
        rows = self.api.list_rows(cid, limit=100)["data"]["rows"]
        return next(r["romUid"] for r in rows if r["file"] == filename)

    def _stage_paste(self, filename="FFX.iso"):
        self.api.copy_selection(self.src, [self._uid(self.src, filename)])
        return self.api.paste(self.dst)["data"]

    def _entries(self):
        return self.api.plan_state(self.dst)["data"]

    # ------------------------------------------------------------------
    # 목적지 충돌
    # ------------------------------------------------------------------
    def test_different_file_at_destination_becomes_a_conflict(self):
        """같은 이름 + 같은 크기라도 다른 파일이면 조용히 덮어쓰면 안 된다."""
        source = self.source_root / "ps2" / "FFX.iso"
        victim = self.target_root / "ps2" / "FFX.iso"
        victim.write_bytes(b"D" * source.stat().st_size)  # 같은 크기, 다른 내용

        result = self._stage_paste()
        self.assertEqual(result["conflicts"], 1)

        state = self._entries()
        self.assertEqual(state["conflicts"], 1)
        self.assertEqual(state["conflictEntries"][0]["conflicts"][0]["kind"], "rom")

        # 미해결 충돌은 Apply 대상이 아니다.
        self.api.start_apply(self.dst)
        wait_idle(self.api)
        self.assertEqual(victim.read_bytes(), b"D" * source.stat().st_size,
                         "해결되지 않은 충돌인데 기존 파일이 덮어써졌다")

    def test_conflict_resolved_as_skip_leaves_the_file_alone(self):
        source = self.source_root / "ps2" / "FFX.iso"
        victim = self.target_root / "ps2" / "FFX.iso"
        victim.write_bytes(b"D" * source.stat().st_size)
        self._stage_paste()

        key = self._entries()["conflictEntries"][0]["key"]
        self.assertTrue(self.api.plan_resolve_conflict(self.dst, key, "skip")["ok"])
        self.api.start_apply(self.dst)
        wait_idle(self.api)
        self.assertEqual(victim.read_bytes(), b"D" * source.stat().st_size)

    def test_conflict_resolved_as_overwrite_replaces_the_file(self):
        source = self.source_root / "ps2" / "FFX.iso"
        victim = self.target_root / "ps2" / "FFX.iso"
        victim.write_bytes(b"D" * source.stat().st_size)
        self._stage_paste()

        key = self._entries()["conflictEntries"][0]["key"]
        self.api.plan_resolve_conflict(self.dst, key, "overwrite")
        self.api.start_apply(self.dst)
        wait_idle(self.api)
        self.assertEqual(victim.read_bytes(), source.read_bytes())

    def test_overwrite_capacity_counts_only_the_difference(self):
        """500MB를 700MB로 덮어쓰면 +200MB지 +700MB가 아니다(스펙 §82)."""
        source = self.source_root / "ps2" / "FFX.iso"
        victim = self.target_root / "ps2" / "FFX.iso"
        victim.write_bytes(b"D" * 400)  # 원본은 1000바이트
        self._stage_paste()

        key = self._entries()["conflictEntries"][0]["key"]
        before = self._entries()["delta"].get("internal", 0)
        self.api.plan_resolve_conflict(self.dst, key, "overwrite")
        after = self._entries()["delta"].get("internal", 0)
        self.assertEqual(after - before, source.stat().st_size - 400)

    # ------------------------------------------------------------------
    # ADD 롤백
    # ------------------------------------------------------------------
    def test_metadata_failure_rolls_back_copied_files(self):
        """파일은 복사됐는데 gamelist 기록이 실패하면 복사한 파일을 되돌려야 한다.

        안 그러면 다음 Apply가 "이미 존재하는 ROM"을 만나 충돌로 막히거나 중복 처리한다.
        """
        self._stage_paste()
        rom = self.target_root / "ps2" / "FFX.iso"
        cover = self.target_root / "downloaded_media" / "ps2" / "covers" / "FFX.png"

        from adapters.es_de import EsDeAdapter
        original = EsDeAdapter.write_index
        EsDeAdapter.write_index = lambda *a, **k: (_ for _ in ()).throw(OSError("디스크 오류"))
        try:
            self.api.start_apply(self.dst)
            wait_idle(self.api)
        finally:
            EsDeAdapter.write_index = original

        self.assertFalse(rom.exists(), "metadata 실패인데 복사된 ROM이 남아 있다")
        self.assertFalse(cover.exists(), "metadata 실패인데 복사된 media가 남아 있다")

        state = self._entries()
        self.assertEqual(state["failed"], 1)
        self.assertEqual(state["failedEntries"][0]["status"], STATUS_FAILED)

    def test_metadata_failure_keeps_pre_existing_files(self):
        """되돌릴 때 이번에 만든 것만 지운다. 원래 있던 파일은 건드리지 않는다."""
        self._stage_paste("MGS2.iso")  # 대상에 이미 있는 ROM
        victim = self.target_root / "ps2" / "MGS2.iso"
        before = victim.read_bytes()

        from adapters.es_de import EsDeAdapter
        original = EsDeAdapter.write_index
        EsDeAdapter.write_index = lambda *a, **k: (_ for _ in ()).throw(OSError("디스크 오류"))
        try:
            self.api.start_apply(self.dst)
            wait_idle(self.api)
        finally:
            EsDeAdapter.write_index = original

        self.assertTrue(victim.exists(), "원래 있던 파일이 롤백으로 지워졌다")
        self.assertEqual(victim.read_bytes(), before)

    # ------------------------------------------------------------------
    # Storage 이동 트랜잭션
    # ------------------------------------------------------------------
    def _prepare_move(self):
        sd = self.dir / "sd"
        sd.mkdir(exist_ok=True)
        storage_id = self.api.add_external_storage(self.dst, "SD", str(sd))["data"]
        self.api.plan_storage_change(self.dst, "ps2", storage_id)
        return sd, storage_id

    def test_registry_failure_after_move_restores_the_files(self):
        """파일은 옮겼는데 Registry 갱신이 실패하면 파일을 원래 자리로 되돌려야 한다.

        되돌리지 않으면 "파일은 External, Registry는 Internal"이 되어 앱이 ROM을
        찾지 못한다.
        """
        sd, storage_id = self._prepare_move()
        origin = self.target_root / "ps2" / "MGS2.iso"
        self.assertTrue(origin.exists())

        original = self.api.registry.move_system
        self.api.registry.move_system = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("DB 잠김"))
        try:
            self.api.start_apply(self.dst)
            wait_idle(self.api)
        finally:
            self.api.registry.move_system = original

        self.assertTrue(origin.exists(), "Registry 실패인데 파일이 원래 자리로 돌아오지 않았다")
        self.assertFalse((sd / "ps2" / "MGS2.iso").exists(), "되돌렸는데 새 위치에도 파일이 남아 있다")

        # Registry는 여전히 원래 Storage를 가리켜야 한다 - 파일과 일치한다.
        detail = self.api.collection_detail(self.dst)["data"]
        placement = {s["id"]: [x["system"] for x in s["systems"]] for s in detail["storages"]}
        self.assertEqual(placement["internal"], ["ps2"])
        self.assertEqual(placement[storage_id], [])

    def test_partial_move_failure_restores_everything(self):
        """일부만 옮겨진 상태로 끝내면 안 된다. 전부 되돌려 원래 상태로 만든다."""
        sd, _ = self._prepare_move()
        origin_dir = self.target_root / "ps2"
        before = sorted(p.name for p in origin_dir.iterdir())

        real_move = file_ops.move_files

        def partial_move(pairs, **kwargs):
            # 첫 번째 파일만 실제로 옮기고 나머지는 실패했다고 보고한다.
            results = real_move(pairs[:1], **kwargs)
            for _, dest in pairs[1:]:
                results[str(dest)] = False
            return results

        file_ops.move_files = partial_move
        try:
            self.api.start_apply(self.dst)
            wait_idle(self.api)
        finally:
            file_ops.move_files = real_move

        self.assertEqual(sorted(p.name for p in origin_dir.iterdir()), before,
                         "부분 실패 후 원래 위치가 복구되지 않았다")
        state = self._entries()
        self.assertIn(state["failedEntries"][0]["status"], (STATUS_FAILED, STATUS_PARTIAL))

    def test_destination_collision_blocks_the_move(self):
        """대상 Storage에 같은 이름의 파일이 있으면 무엇을 덮어쓸지 사용자가 정해야 한다."""
        sd, _ = self._prepare_move()
        (sd / "ps2").mkdir(parents=True)
        (sd / "ps2" / "MGS2.iso").write_bytes(b"already here")

        self.api.start_apply(self.dst)
        wait_idle(self.api)

        self.assertEqual((sd / "ps2" / "MGS2.iso").read_bytes(), b"already here",
                         "충돌인데 덮어써졌다")
        self.assertTrue((self.target_root / "ps2" / "MGS2.iso").exists(), "원본이 사라졌다")
        state = self._entries()
        self.assertEqual(state["failed"], 1)
        self.assertIn("같은 이름", state["failedEntries"][0]["error"])

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------
    def test_delete_removes_the_gamelist_entry_too(self):
        """게임 삭제는 ROM/Media뿐 아니라 gamelist 항목까지 없애야 한다.

        항목을 남기면 다음 스캔에서 metadata-only 항목으로 되살아난 것처럼 보인다.
        """
        uid = self._uid(self.dst, "MGS2.iso")
        self.api.plan_delete(self.dst, [uid])
        self.api.start_apply(self.dst)
        wait_idle(self.api)

        self.assertFalse((self.target_root / "ps2" / "MGS2.iso").exists())
        root = ET.parse(self.target_root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        paths = [(g.findtext("path") or "").strip() for g in root.findall("game")]
        self.assertNotIn("./MGS2.iso", paths, "gamelist 항목이 남아 있다")
        # 우리가 해석하지 않는 요소는 그대로 있어야 한다.
        self.assertIsNotNone(root.find("folder"))

    def test_delete_rejects_a_file_changed_behind_our_back(self):
        """Plan을 만든 뒤 외부에서 파일이 바뀌었으면 지우지 않는다."""
        uid = self._uid(self.dst, "MGS2.iso")
        self.api.plan_delete(self.dst, [uid])
        (self.target_root / "ps2" / "MGS2.iso").write_bytes(b"replaced with different content")

        report = self.api.validate_plan(self.dst)["data"]
        self.assertFalse(report["ok"])
        self.assertIn("변경", report["entries"][0]["error"])

    def test_cache_reflects_deletion_right_after_apply(self):
        """Apply 직후 목록에 지운 게임이 남아 있으면 안 된다."""
        uid = self._uid(self.dst, "MGS2.iso")
        self.api.plan_delete(self.dst, [uid])
        self.api.start_apply(self.dst)
        wait_idle(self.api)

        files = [r["file"] for r in self.api.list_rows(self.dst, limit=100)["data"]["rows"]]
        self.assertNotIn("MGS2.iso", files, "Apply 후에도 Cache에 지운 게임이 남아 있다")


if __name__ == "__main__":
    unittest.main()
