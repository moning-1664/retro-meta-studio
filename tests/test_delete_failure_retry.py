"""Delete가 중간에 실패했을 때, 그리고 그 뒤에 다시 시도했을 때 (Phase 7.21, QA 재검토 #6).

`_apply_delete()`는 파일을 먼저 지우고 gamelist 항목을 나중에 지운다. 둘 사이에서
실패하는 두 지점을 각각 검증한다.

    파일 삭제 실패        -> 아무것도 지워지지 않은 것처럼 남아야 한다(gamelist 그대로)
    gamelist 제거 실패    -> 파일은 이미 지워졌다. 이것은 단순 실패가 아니라 PARTIAL이다

그리고 **둘 다 재시도가 실제로 되는지**까지 본다 - 실패했다고 보고하는 것과, 그 상태를
사용자가 다시 시도해서 벗어날 수 있는 것은 다른 문제다.

이 파일을 쓰다가 실제로 걸린 함정 하나를 적어 둔다: `EsDeAdapter`는 registry가 물고
있는 **싱글턴**이고 `remove_entries`는 그 클래스에 직접 정의돼 있다. 거기에
`EsDeAdapter.remove_entries = boom`으로 **클래스 속성**을 덮어쓴 뒤 `delattr`로
되돌리면, "되돌리기"가 아니라 **원래 구현 자체를 지우는 것**이 된다 - 부모 클래스의
`NotImplementedError` 스텁으로 떨어지고, 그 뒤로 같은 프로세스에서 도는 다른 테스트
전부가 ES-DE의 gamelist 삭제가 깨진 채로 남는다. 인스턴스 속성으로만 덮어써야
안전하다 - `del adapter.remove_entries`는 인스턴스 오버라이드만 지우고 클래스의
원래 메서드를 그대로 드러낸다.
"""

import unittest
import xml.etree.ElementTree as ET

import file_ops
from adapters import get_adapter
from app.model.plan import STATUS_APPLIED, STATUS_FAILED, STATUS_PARTIAL
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root, wait_idle


class DeleteFailureRetryTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_delfail_")
        self.root = build_custom_esde_tree(self.dir / "esde", "ps2",
                                           [{"filename": "FFX.iso", "title": "Final Fantasy X"}])
        media = self.root / "downloaded_media" / "ps2" / "covers"
        media.mkdir(parents=True, exist_ok=True)
        (media / "FFX.png").write_bytes(b"c" * 30)

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        scan(self.api, self.cid)
        self.uid = self.api.list_rows(self.cid)["data"]["rows"][0]["romUid"]

    def _rom(self):
        return self.root / "ps2" / "FFX.iso"

    def _gamelist_has_ffx(self):
        gl = self.root / "gamelists" / "ps2" / "gamelist.xml"
        root = ET.parse(gl).getroot()
        return any((g.findtext("path") or "").strip() == "./FFX.iso" for g in root.findall("game"))

    def _entry(self):
        plan = self.api._plans[self.cid]
        return next(e for e in plan.entries if e.filename == "FFX.iso")

    def _apply(self):
        job = self.api.start_apply(self.cid)["data"]["jobId"]
        wait_idle(self.api)
        return self.api.get_job_progress(job)["data"].get("result")

    def _break_gamelist_removal(self):
        """gamelist에서 항목을 지우는 단계를 실패시킨다. **인스턴스에만** 덮어쓴다 -
        위 모듈 docstring에 적어둔 이유 때문이다."""
        adapter = get_adapter("es-de")

        def boom(*_a, **_k):
            raise OSError("gamelist를 쓸 수 없다")
        adapter.remove_entries = boom
        self.addCleanup(lambda: adapter.__dict__.pop("remove_entries", None))
        return adapter

    # --- 파일 삭제 자체가 실패한다 ------------------------------------------
    def test_a_file_delete_failure_leaves_everything_as_if_nothing_happened(self):
        self.api.plan_delete(self.cid, [self.uid])

        real = file_ops.delete_files
        file_ops.delete_files = lambda paths, **k: {str(p): False for p in paths}
        self.addCleanup(lambda: setattr(file_ops, "delete_files", real))

        self._apply()
        self.assertEqual(self._entry().status, STATUS_FAILED)
        self.assertTrue(self._rom().exists(), "삭제에 실패했는데 ROM이 사라졌다")
        self.assertTrue(self._gamelist_has_ffx(), "삭제에 실패했는데 gamelist에서 빠졌다")

    def test_retrying_after_a_delete_failure_succeeds(self):
        self.api.plan_delete(self.cid, [self.uid])
        entry = self._entry()   # 성공하면 Plan에서 빠지므로 미리 잡아 둔다

        real = file_ops.delete_files
        file_ops.delete_files = lambda paths, **k: {str(p): False for p in paths}
        self._apply()
        self.assertEqual(entry.status, STATUS_FAILED)

        file_ops.delete_files = real   # 실패 원인을 없앤다
        self._apply()
        self.assertEqual(entry.status, STATUS_APPLIED)
        self.assertFalse(self._rom().exists())
        self.assertFalse(self._gamelist_has_ffx())

    # --- 파일은 지워졌는데 gamelist 항목 제거가 실패한다 ----------------------
    def test_a_gamelist_removal_failure_is_partial_not_plain_failed(self):
        """**여기가 이 파일의 핵심이다.** 파일은 이미 없다 - 단순 실패로 보고하면
        사용자는 "아무 일도 없었다"고 오해한다."""
        self.api.plan_delete(self.cid, [self.uid])
        self._break_gamelist_removal()

        self._apply()
        self.assertEqual(self._entry().status, STATUS_PARTIAL)
        self.assertFalse(self._rom().exists(), "PARTIAL인데 ROM이 아직 있다 - 파일은 이미 지워졌어야 한다")
        self.assertTrue(self._gamelist_has_ffx(),
                        "PARTIAL인데 gamelist에서도 빠졌다 - 실패한 단계가 반영됐다")

    def test_retrying_after_a_gamelist_removal_failure_finishes_the_job(self):
        """파일은 이미 지워진 상태에서 재시도한다 - 다시 지우려 하면 안 되고,
        gamelist 제거만 마저 해야 한다."""
        self.api.plan_delete(self.cid, [self.uid])
        entry = self._entry()
        adapter = self._break_gamelist_removal()

        self._apply()
        self.assertEqual(entry.status, STATUS_PARTIAL)
        adapter.__dict__.pop("remove_entries", None)   # 원인을 없앤다

        self._apply()
        self.assertEqual(entry.status, STATUS_APPLIED)
        self.assertFalse(self._gamelist_has_ffx(), "재시도했는데도 gamelist 항목이 안 지워졌다")

    def test_a_partial_entry_is_not_silently_dropped_from_the_plan(self):
        """PARTIAL은 성공이 아니다 - Plan에 남아서 사용자가 다시 봐야 한다."""
        self.api.plan_delete(self.cid, [self.uid])
        self._break_gamelist_removal()

        result = self._apply()
        self.assertEqual(result.get("partial"), 1)
        self.assertEqual(self.api.plan_state(self.cid)["data"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
