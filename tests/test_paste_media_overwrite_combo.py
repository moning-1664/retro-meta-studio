"""ROM 유지 + Media만 덮어쓰기 조합 (Phase 7.22 QA 재검토 항목 3, 다음 세션에서 수정).

사용자가 요청한 정확한 조합이다.

    Source: ROM A, Metadata A, Cover A
    Target: ROM A(동일 ROM, 다른 바이트), Metadata B, Cover B

Source의 Metadata + Cover를 Target에 적용하되 ROM은 기존 Target 것을 유지하는 것이
기대 결과다.

    ROM      → Target 기존 ROM 유지
    Metadata → Source Metadata
    Cover    → Source Cover

## 원인과 고친 방식

Phase 7.19가 만든 "메타데이터만"(`RESOLVE_SKIP`)은 **항목(entry) 전체**에 적용되는
단일 값이었다(`app/plan/builder.py`의 `entry.resolution`). `_plan_copies()`가
`add_destinations()`의 파일들을 훑으며 충돌마다 **그 항목의 resolution**을 그대로
적용해서, ROM도 Cover도 같은 `entry`에 속하는 이상 ROM 충돌 때문에 "메타데이터만"을
고르면 Cover 충돌도 함께 건너뛰었다.

`entry.conflicts`의 각 원소는 이미 `kind`("rom"/"media")를 갖고 있었으므로(Plan 단계에서
`plan_add()`가 채운다), 항목 전체가 아니라 **conflict 단위**로 승인 여부를 판단하도록
`approved_targets()`/`unapproved_overwrites()`(builder.py)와 `_plan_copies()`(applier.py)를
고쳤다. `RESOLVE_SKIP`은 이제 `kind == "rom"`인 충돌만 건드리지 않고, `kind != "rom"`
(media)인 충돌은 승인된 것으로 보아 계속 진행한다 - "메타데이터만"이 실제로 의미하는
것은 "큰 파일(ROM)은 보존하되 메타데이터와 media는 새 것으로 채운다"이기 때문이다.
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
        # 크기까지 달라야 진짜 충돌이다 - Media 충돌 판정은 크기만 본다(사용자 결정,
        # app/plan/builder.classify_destination의 size_only). 크기가 같으면 지금은
        # 같은 파일로 보고 조용히 건너뛰므로, 이 테스트가 보려는 "진짜 충돌"을 만들려면
        # Source와 크기 자체가 달라야 한다.
        self.dst_cover = write_file(
            self.dst / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"COVER-BB" * 20)
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
        paste = self.api.paste(self.d, "overwrite")["data"]
        # 사용자 결정(번복) - ROM은 덮어쓰지 않으므로 충돌로 잡힐 일이 없다. 예전에는
        # 여기서 ROM 충돌이 뜨고 "메타데이터만"을 골라야 비로소 Cover가 들어갔다.
        self.assertEqual(paste["conflicts"], 0)
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
        """Overwrite 모드이므로 Cover는 Source 것으로 바뀐다 - ROM을 건드리지 않는 것과
        무관하게 각 구성요소는 모드를 따른다."""
        self._paste_and_resolve_skip()
        self.assertEqual(self.dst_cover.read_bytes(), b"COVER-A" * 20)


if __name__ == "__main__":
    unittest.main()
