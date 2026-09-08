"""승인의 범위 (Phase 7.11 QA Audit).

Phase 7.10에서 "승인한 것은 그 시점의 그 파일"을 넣었다. 이 파일은 그 규칙에
**구멍이 있는지**를 본다 - 규칙을 넣는 것과 규칙이 모든 경로를 덮는 것은 다르다.

세 가지를 본다.

1. **승인은 항목이 아니라 파일 단위다.** 커버 하나에 "덮어쓰기"를 눌렀다고 해서
   ROM까지 덮어써도 된다는 뜻이 아니다.
2. **Plan 만들 때 없던 파일**이 Apply 직전에 생겼다면, 그것에 대한 승인은 존재한 적이
   없다.
3. **원본 media**도 ROM과 같은 수준으로 보호돼야 한다.
"""

import unittest
from pathlib import Path

import file_ops
from app.model.plan import (RESOLVE_OVERWRITE, STATUS_APPLIED, STATUS_FAILED,
                            STATUS_PARTIAL)
from app.plan import builder
from storage.local import LocalStorageProvider
from tests.test_stability_hardening import PlanCase, touch

PROVIDER = LocalStorageProvider()


class ApprovalIsPerFileTests(PlanCase):
    """커버에 대한 승인이 ROM에까지 번지면 안 된다.

    `entry.resolution`은 항목 하나에 대해 하나뿐인데 충돌은 파일마다 생긴다. 커버가
    충돌해서 "덮어쓰기"를 누른 순간 그 항목 전체가 덮어쓰기 모드가 되면, **사용자가
    본 적도 없는 ROM 파일까지 덮어쓴다.**
    """

    def setUp(self):
        super().setUp()
        # 커버만 충돌한다. ROM 자리는 비어 있다.
        self.dest_cover = (self.dst_root / "downloaded_media" / "ps2" / "covers" / "FFX.png")
        touch(self.dest_cover, b"OLDCOVER")
        self.plan_one(with_media=True)
        conflicts = self.entry().conflicts
        self.assertEqual([c["kind"] for c in conflicts], ["media"],
                         "이 테스트는 media만 충돌하는 상황을 전제한다")
        builder.resolve_conflict(self.plan, self.collection, PROVIDER,
                                 self.entry().key, RESOLVE_OVERWRITE)

    def test_a_rom_that_appeared_later_is_not_overwritten(self):
        """Plan을 만들 때는 없던 ROM이 Apply 직전에 생겼다.

        사용자는 이 파일에 대해 아무것도 승인한 적이 없다. 조용히 덮어쓰면 남의
        ROM이 사라진다.
        """
        touch(self.dest_rom, b"SOMEONE ELSE'S ROM")
        self.apply()
        self.assertEqual(self.dest_rom.read_bytes(), b"SOMEONE ELSE'S ROM",
                         "승인한 적 없는 파일을 덮어썼다")

    def test_the_approved_cover_is_still_overwritten(self):
        """승인한 것은 승인한 대로 되어야 한다 - 전부 막아버리는 것이 답이 아니다."""
        self.apply()
        self.assertEqual(self.dest_cover.read_bytes(), b"n" * 50)


class TargetAppearingAfterThePlanTests(PlanCase):
    """TC-PLAN-SAFETY-001. 충돌이 하나도 없던 항목에서도 같은 일이 생길 수 있다."""

    def test_a_target_created_after_the_plan_is_not_overwritten(self):
        self.plan_one(with_media=False)
        self.assertEqual(self.entry().conflicts, [], "충돌 없이 시작해야 하는 테스트다")

        touch(self.dest_rom, b"CREATED LATER")
        self.validate()
        self.apply()
        self.assertEqual(self.dest_rom.read_bytes(), b"CREATED LATER",
                         "Plan에 없던 파일을 덮어썼다")

    def test_the_entry_does_not_claim_success(self):
        """복사하지 않았는데 «완료»로 표시하면 사용자는 파일이 갔다고 믿는다."""
        self.plan_one(with_media=False)
        touch(self.dest_rom, b"CREATED LATER")
        self.validate()
        self.apply()
        self.assertNotEqual(self.entry().status, STATUS_APPLIED,
                            "복사하지 않았는데 완료라고 한다")


class SourceMediaSnapshotTests(PlanCase):
    """TC-MEDIA-SAFETY-001/002. 원본 media도 ROM과 같은 수준으로 본다.

    ROM은 Phase 7.10에서 막았지만 media는 «존재하는가»만 봤다. Plan을 만든 뒤 커버가
    다른 그림으로 바뀌면 그 그림이 조용히 복사된다 - 사용자는 자기가 고른 커버가
    갔다고 믿는다.
    """

    def setUp(self):
        super().setUp()
        self.plan_one(with_media=True)
        self.validate()

    def test_an_untouched_media_is_fine(self):
        self.assertTrue(self.validate()["ok"])

    def test_a_replaced_cover_is_detected(self):
        self.src_cover.unlink()
        touch(self.src_cover, b"DIFFERENT COVER")
        self.assertFalse(self.validate()["ok"], "바뀐 커버를 그대로 복사하려 한다")

    def test_a_same_size_cover_replacement_is_detected(self):
        self.src_cover.unlink()
        touch(self.src_cover, b"x" * 50)
        self.assertFalse(self.validate()["ok"], "같은 크기의 다른 커버를 못 알아봤다")


class RestoreFailureIsNotPlainFailureTests(PlanCase):
    """TC-ROLLBACK-005. 되돌리지 못했다면 «실패»가 아니라 «손봐야 한다»이다.

    사용자가 FAILED를 보면 "아무 일도 없었구나"라고 읽는다. 그런데 원본을 되돌리지
    못한 상태라면 그 파일은 이미 없다. 그 둘을 같은 이름으로 부르면 안 된다.
    """

    def setUp(self):
        super().setUp()
        touch(self.dest_rom, b"OLD" * 100)
        self.plan_one(with_media=False)
        builder.resolve_conflict(self.plan, self.collection, PROVIDER,
                                 self.entry().key, RESOLVE_OVERWRITE)
        self.validate()

    def test_a_failed_restore_is_reported_as_partial(self):
        real_move = file_ops.move_files
        calls = {"n": 0}

        def move(pairs, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return real_move(pairs, **kwargs)      # 백업은 성공시킨다
            return {str(dest): False for _src, dest in pairs}   # 복구만 실패시킨다

        file_ops.move_files = move
        self.addCleanup(lambda: setattr(file_ops, "move_files", real_move))

        def boom(*_a, **_k):
            raise OSError("gamelist를 쓸 수 없다")
        self.adapter.write_index = boom     # 싱글턴이므로 되돌릴 때 속성을 지운다
        self.addCleanup(lambda: self.adapter.__dict__.pop("write_index", None))

        self.apply()
        self.assertEqual(self.entry().status, STATUS_PARTIAL,
                         "원본을 못 되돌렸는데 단순 실패로 보고했다")


if __name__ == "__main__":
    unittest.main()
