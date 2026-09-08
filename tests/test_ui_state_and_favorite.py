"""GUI 이식이 기대는 백엔드 두 조각 (Phase 7.15).

이전 프로젝트에는 있었지만 여기서는 저장할 곳이 없던 것들이다.

1. **화면 상태** - 컬럼 너비, 정렬, 미리보기 on/off. `collections.ui_state_json`은
   처음부터 있었는데 읽고 쓰는 길이 없어서, 앱을 닫으면 사용자가 맞춰 놓은 것이
   전부 사라졌다.
2. **즐겨찾기** - 사용자에게는 별표 하나지만 저장 위치는 Frontend마다 다르고 우리
   공통 필드도 아니다. **Frontend의 파일에 적어야 한다** - 우리 DB에만 적으면
   ES-DE를 열었을 때 그 별표가 없다.
"""

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from adapters import get_adapter
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root


class UiStateTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_uistate_")
        self.root = build_custom_esde_tree(self.dir / "esde", "ps2",
                                           [{"filename": "FFX.iso", "title": "FFX"}])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]

    def test_it_starts_empty(self):
        self.assertEqual(self.api.get_ui_state(self.cid)["data"], {})

    def test_what_is_saved_comes_back(self):
        self.api.save_ui_state(self.cid, {"colWidths": {"title": 240, "desc": 380}})
        self.assertEqual(self.api.get_ui_state(self.cid)["data"]["colWidths"],
                         {"title": 240, "desc": 380})

    def test_saving_one_key_does_not_erase_the_others(self):
        """정렬을 바꿨다고 컬럼 너비가 사라지면 안 된다."""
        self.api.save_ui_state(self.cid, {"colWidths": {"title": 240}})
        self.api.save_ui_state(self.cid, {"sort": {"key": "title", "desc": False}})
        state = self.api.get_ui_state(self.cid)["data"]
        self.assertEqual(state["colWidths"], {"title": 240})
        self.assertEqual(state["sort"], {"key": "title", "desc": False})

    def test_it_survives_reopening_the_app(self):
        """**이것이 요점이다.** 앱을 닫았다 열어도 같은 폭이어야 한다."""
        self.api.save_ui_state(self.cid, {"colWidths": {"title": 321}})
        self.api.close()

        reopened = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.get_ui_state(self.cid)["data"]["colWidths"]["title"], 321)

    def test_each_collection_remembers_its_own(self):
        other = build_custom_esde_tree(self.dir / "other", "snes",
                                       [{"filename": "Z.sfc", "title": "Z"}])
        cid2 = self.api.create_collection("D", "es-de", str(other))["data"]["id"]
        self.api.save_ui_state(self.cid, {"colWidths": {"title": 100}})
        self.api.save_ui_state(cid2, {"colWidths": {"title": 200}})
        self.assertEqual(self.api.get_ui_state(self.cid)["data"]["colWidths"]["title"], 100)
        self.assertEqual(self.api.get_ui_state(cid2)["data"]["colWidths"]["title"], 200)


class FavoriteTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_fav_")
        self.root = build_custom_esde_tree(self.dir / "esde", "ps2", [
            {"filename": "FFX.iso", "title": "Final Fantasy X"},
            {"filename": "MGS2.iso", "title": "Metal Gear Solid 2"},
        ])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        scan(self.api, self.cid)
        self.uid = next(r["romUid"] for r in self.api.list_rows(self.cid)["data"]["rows"]
                        if r["file"] == "FFX.iso")

    def _gamelist(self):
        return ET.parse(self.root / "gamelists" / "ps2" / "gamelist.xml").getroot()

    def _game(self, filename="./FFX.iso"):
        return next(g for g in self._gamelist().findall("game")
                    if (g.findtext("path") or "").strip() == filename)

    def test_the_star_reaches_the_gamelist_file(self):
        """**우리 DB에만 적으면 ES-DE에서는 즐겨찾기가 아니다.**"""
        self.assertTrue(self.api.set_favorite(self.cid, self.uid, True)["ok"])
        self.assertEqual(self._game().findtext("favorite"), "true")

    def test_turning_it_off_reaches_the_file_too(self):
        self.api.set_favorite(self.cid, self.uid, True)
        self.api.set_favorite(self.cid, self.uid, False)
        self.assertNotEqual(self._game().findtext("favorite"), "true")

    def test_the_adapter_reads_it_back(self):
        self.api.set_favorite(self.cid, self.uid, True)
        adapter = get_adapter("es-de")
        row = self.api.workspace.open(self.cid).get_row(self.uid)
        self.assertTrue(adapter.is_favorite(row["frontend_raw"]))

    def test_it_survives_a_rescan(self):
        self.api.set_favorite(self.cid, self.uid, True)
        scan(self.api, self.cid)
        # 재스캔은 그 System의 행을 통째로 다시 넣으므로 rom_uid가 새로 발급된다.
        uid = next(r["romUid"] for r in self.api.list_rows(self.cid)["data"]["rows"]
                   if r["file"] == "FFX.iso")
        adapter = get_adapter("es-de")
        row = self.api.workspace.open(self.cid).get_row(uid)
        self.assertTrue(adapter.is_favorite(row["frontend_raw"]), "다시 스캔했더니 별표가 사라졌다")

    def test_it_does_not_touch_the_other_games(self):
        self.api.set_favorite(self.cid, self.uid, True)
        self.assertNotEqual(self._game("./MGS2.iso").findtext("favorite"), "true")

    def test_the_title_is_not_disturbed(self):
        """별표를 눌렀다고 제목이 바뀌면 안 된다."""
        self.api.set_favorite(self.cid, self.uid, True)
        self.assertEqual(self._game().findtext("name"), "Final Fantasy X")

    def test_a_frontend_without_favorites_says_so(self):
        """Pegasus는 즐겨찾기가 없다. 조용히 성공한 척하지 않는다."""
        self.assertIsNone(get_adapter("pegasus").FAVORITE_TAG)


if __name__ == "__main__":
    unittest.main()
