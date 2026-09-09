"""ROM 유지 + Media만 덮어쓰기 조합 (Phase 7.22, QA 재검토 항목 3).

사용자가 요청한 정확한 조합이다.

    Source: ROM A, Metadata A, Cover A
    Target: ROM A(동일 ROM, 다른 바이트), Metadata B, Cover B

Source의 Metadata + Cover를 Target에 적용하되 ROM은 기존 Target 것을 유지하는 것이
기대 결과다.

    ROM      → Target 기존 ROM 유지
    Metadata → Source Metadata
    Cover    → Source Cover

**실제로 돌려 보니 다르다.** ROM은 정확히 유지되고 Metadata도 정확히 반영되지만,
**Cover는 Target 것이 그대로 남는다** - Source의 Cover로 바뀌지 않는다.

## 원인 추적

Phase 7.19가 만든 "메타데이터만"(`RESOLVE_SKIP`)은 **항목(entry) 전체**에 적용되는
단일 값이다(`app/plan/builder.py`의 `entry.resolution`). `_plan_copies()`는
`add_destinations()`가 돌려주는 파일들을 순서대로 훑으면서, 충돌한 파일을 만날 때마다
**그 항목의 resolution**을 그대로 적용한다.

```python
if action == ACTION_CONFLICT:
    if entry.resolution == RESOLVE_SKIP:
        continue   # 이 파일은 건드리지 않는다
```

ROM도 Cover도 같은 `entry`에 속하므로, ROM 충돌 때문에 "메타데이터만"을 고르면
**Cover 충돌도 함께 건너뛴다.** 사용자는 "ROM은 두고 Cover는 새것으로"를 표현할
방법이 없다 - 지금 UI/API의 해상도는 파일 단위가 아니라 항목 단위다.

이건 IMPLEMENTATION BUG로 분류한다. Media snapshot·승인 범위(§Phase 7.10/7.11)는
파일 단위로 이미 설계돼 있는데, 여기서만 항목 단위로 뭉뚱그려진다.
"""

import unittest

from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root, wait_idle, write_file


class RomKeptMediaOverwrittenTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_romkeep_")
        self.src = build_custom_esde_tree(self.dir / "src", "ps2", [
            {"filename": "FFX.iso", "title": "Final Fantasy X", "genre": "RPG"}])
        self.src_cover = write_file(
            self.src / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"COVER-A" * 20)

        self.dst = build_custom_esde_tree(self.dir / "dst", "ps2",
                                          [{"filename": "FFX.iso", "title": "Old Title"}])
        self.dst_cover = write_file(
            self.dst / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"COVER-B" * 20)
        # Target ROM은 Source와 바이트가 다르다 - 진짜 충돌 상황을 만든다.
        self.dst_rom = write_file(self.dst / "ps2" / "FFX.iso", b"TARGET-ROM-BYTES" * 20)
        self.target_rom_before = self.dst_rom.read_bytes()

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.s = self.api.create_collection("S", "es-de", str(self.src))["data"]["id"]
        self.d = self.api.create_collection("D", "es-de", str(self.dst))["data"]["id"]
        scan(self.api, self.s)
        scan(self.api, self.d)

    def _paste_and_resolve_skip(self):
        u = next(r["romUid"] for r in self.api.list_rows(self.s)["data"]["rows"]
                 if r["file"] == "FFX.iso")
        self.api.copy_selection(self.s, [u])
        paste = self.api.paste(self.d)["data"]
        self.assertEqual(paste["conflicts"], 1, "ROM과 Cover 둘 다 달라야 충돌로 잡힌다")
        self.api.plan_resolve_all_conflicts(self.d, "skip")
        job = self.api.start_apply(self.d)["data"]["jobId"]
        wait_idle(self.api)
        return self.api.get_job_progress(job)["data"].get("result")

    def _target_row(self):
        uid = next(r["romUid"] for r in self.api.list_rows(self.d)["data"]["rows"]
                  if r["file"] == "FFX.iso")
        return self.api.workspace.open(self.d).get_row(uid)

    def test_the_apply_succeeds(self):
        result = self._paste_and_resolve_skip()
        self.assertEqual(result.get("applied"), 1)

    def test_rom_is_preserved_exactly(self):
        """정책대로 되는 부분 - ROM은 손대지 않는다."""
        self._paste_and_resolve_skip()
        self.assertEqual(self.dst_rom.read_bytes(), self.target_rom_before)

    def test_metadata_comes_from_source(self):
        """정책대로 되는 부분 - 메타데이터는 Source 것이 반영된다."""
        self._paste_and_resolve_skip()
        self.assertEqual(self._target_row()["title"], "Final Fantasy X")

    def test_cover_is_overwritten_with_the_source_cover(self):
        """**IMPLEMENTATION BUG.** 사용자가 기대한 조합은 "ROM은 유지, Cover는 새것"
        인데, 지금은 ROM 충돌 때문에 고른 "메타데이터만"이 같은 항목의 Cover 충돌까지
        함께 건너뛴다. Cover가 Target 것(COVER-B)으로 그대로 남는다 - 실패를 그대로
        남겨 둔다.
        """
        self._paste_and_resolve_skip()
        self.assertEqual(self.dst_cover.read_bytes(), b"COVER-A" * 20,
                         "IMPLEMENTATION BUG: ROM 충돌 때문에 고른 '메타데이터만'이 "
                         "Cover 충돌까지 함께 건너뛰어, Source의 Cover로 바뀌지 않았다")

    def test_the_target_actually_still_has_its_own_cover(self):
        """위 실패의 반대편을 증명한다 - Target의 예전 Cover가 여전히 남아 있다는
        사실 자체는 확실하다(버그가 "아무것도 안 바뀜"이 아니라 "선택적으로 못 바뀜"
        임을 보인다)."""
        self._paste_and_resolve_skip()
        self.assertEqual(self.dst_cover.read_bytes(), b"COVER-B" * 20)


if __name__ == "__main__":
    unittest.main()
