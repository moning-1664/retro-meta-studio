"""이미 가진 ROM에 메타데이터만 채우기 (Phase 7.19, GUI-17).

사용자가 겪은 것:

    메타데이터가 있는 Collection에서 Ctrl+C
    ROM만 있는 Collection에서 같은 ROM에 Ctrl+V
    -> 아무 일도 일어나지 않는다

**이것은 이 앱의 핵심 사용 흐름 중 하나다.** 스크래핑한 컬렉션의 정보를 ROM만 있는
컬렉션에 옮기는 것이 그 자체로 목적이기 때문이다.

예전에는 이 흐름에 ROM 충돌이 끼어 있었다 - 같은 파일명이 대상에 있으니 ROM이 충돌로
잡히고, 사용자가 "파일은 그대로 두라"를 골라야 비로소 메타데이터가 들어갔다.

지금은 **ROM을 아예 덮어쓰지 않는다**(사용자 결정 - "롬은 항상 부차적인 asset이고
대상에 ROM이 없을 때만 복사"). 그래서 이 시나리오에서 충돌은 생기지 않고, 메타데이터와
media는 모드에 따라 그냥 들어간다. 이 파일은 그 결과를 지킨다.
"""

import unittest
from pathlib import Path

from app.model.plan import RESOLVE_OVERWRITE, RESOLVE_SKIP
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root, wait_idle, write_file


class MetadataOnlyPasteTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_metapaste_")
        self.src = build_custom_esde_tree(self.dir / "src", "ps2", [
            {"filename": "FFX.iso", "title": "Final Fantasy X", "genre": "RPG"},
            {"filename": "MGS2.iso", "title": "Metal Gear Solid 2", "genre": "Action"},
        ])
        write_file(self.src / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"c" * 40)

        # 받는 쪽은 ROM만 있다 - 스크래핑을 한 번도 안 한 컬렉션의 모습이다.
        self.dst = self.dir / "dst"
        for name in ("FFX.iso", "MGS2.iso"):
            write_file(self.dst / "ps2" / name, b"r" * 256)

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.s = self.api.create_collection("S", "es-de", str(self.src))["data"]["id"]
        self.d = self.api.create_collection("D", "es-de", str(self.dst))["data"]["id"]
        scan(self.api, self.s)
        scan(self.api, self.d)

    def _uid(self, cid, filename):
        return next(r["romUid"] for r in self.api.list_rows(cid, limit=50)["data"]["rows"]
                    if r["file"] == filename)

    def _paste(self, filename="FFX.iso"):
        self.api.copy_selection(self.s, [self._uid(self.s, filename)])
        return self.api.paste(self.d, "overwrite")["data"]

    def _apply(self):
        job = self.api.start_apply(self.d)["data"]["jobId"]
        wait_idle(self.api)
        return self.api.get_job_progress(job)["data"].get("result") or {}

    def _target_row(self, filename="FFX.iso"):
        return self.api.workspace.open(self.d).get_row(self._uid(self.d, filename))

    def _dest_rom(self, filename="FFX.iso"):
        return self.dst / "ps2" / filename

    # --- ROM은 아예 충돌하지 않는다 ---------------------------------------
    def test_pasting_onto_an_existing_rom_never_conflicts(self):
        """사용자 결정(번복) - ROM은 덮어쓰지 않으므로 물어볼 일 자체가 없다."""
        self.assertEqual(self._paste()["conflicts"], 0)

    # --- «파일은 두고 메타데이터만»이 실제로 되어야 한다 ---------------------
    def test_the_metadata_lands_without_any_extra_step(self):
        """**이것이 사용자가 하려던 일이고, 아무 일도 일어나지 않던 일이다.**"""
        self._paste()
        self.assertEqual(self._apply().get("applied"), 1)

        row = self._target_row()
        self.assertEqual(row["title"], "Final Fantasy X")
        self.assertEqual(row["fields"].get("genre"), "RPG")

    def test_the_target_rom_is_left_alone(self):
        self._paste()
        self._apply()
        self.assertEqual(self._dest_rom().stat().st_size, 256, "ROM을 건드렸다")
        self.assertNotEqual(self._dest_rom().read_bytes(),
                            (self.src / "ps2" / "FFX.iso").read_bytes())

    def test_the_media_comes_across(self):
        """ROM은 두더라도 커버는 가져와야 한다 - 대상에 없던 것이다."""
        self._paste()
        self._apply()
        self.assertTrue((self.dst / "downloaded_media" / "ps2" / "covers" / "FFX.png").exists())

    def test_it_works_again_the_second_time(self):
        """«딱 한 번만 되고 그 뒤로는 안 된다»가 사용자가 본 증상이다."""
        self._paste()
        self.assertEqual(self._apply().get("applied"), 1)
        for _ in range(2):
            # 두 번째부터는 바뀔 것이 없으므로 올릴 것도 없다 - 그것이 정상이다.
            self.assertEqual(self._paste()["added"], 0)
        self.assertEqual(self._target_row()["title"], "Final Fantasy X")

    def test_a_second_game_works_too(self):
        self._paste("FFX.iso")
        self._apply()
        self._paste("MGS2.iso")
        self._apply()
        self.assertEqual(self._target_row("MGS2.iso")["title"], "Metal Gear Solid 2")

    def test_the_plan_is_emptied_after_success(self):
        """성공한 항목이 Plan에 남아 있으면 다음 붙여넣기가 무엇인지 알 수 없다."""
        self._paste()
        self._apply()
        self.assertEqual(self.api.plan_state(self.d)["data"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
