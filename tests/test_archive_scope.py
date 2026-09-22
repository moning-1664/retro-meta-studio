"""Archive 수집 범위 (P0).

사용자가 보고한 증상은 이것이다.

    Navigation에서 MSX1을 고른다
        -> "Archive에 수집"을 누른다
        -> Collection 전체가 Archive에 들어간다

원인은 화면이 대상을 전달하지 않은 것이었다. 선택한 게임이 없으면 GUI가 `null`을
보냈고, 백엔드는 그것을 "Collection 전체"로 해석했다. 화면에는 MSX1만 보이는데 실제
작업 대상은 전체였다.

그래서 여기서 고정하는 불변식은 하나다.

    **화면에서 고른 대상 == 실제로 Archive에 들어간 대상**

`ingestedRomUids`를 결과에 실어 보내는 이유가 이것이다. "몇 개 들어갔다"만으로는
*무엇이* 들어갔는지 확인할 수 없다.
"""

import unittest

from app.archive import service as archive_service
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, temp_root, wait_idle


def multi_system_tree(root):
    """System 넷. 개수를 다르게 해서 "전체"와 "하나"를 구분할 수 있게 한다."""
    build_custom_esde_tree(root, "msx1", [
        {"filename": "Aleste.rom", "title": "Aleste"},
        {"filename": "Nemesis.rom", "title": "Nemesis"},
    ])
    build_custom_esde_tree(root, "nes", [
        {"filename": "Mario.nes", "title": "Super Mario Bros"},
        {"filename": "Zelda.nes", "title": "The Legend of Zelda"},
        {"filename": "Metroid.nes", "title": "Metroid"},
    ])
    build_custom_esde_tree(root, "famicom", [
        {"filename": "Gradius.fc", "title": "Gradius"}])
    build_custom_esde_tree(root, "snes", [
        {"filename": "Chrono.sfc", "title": "Chrono Trigger"}])
    return root


class ArchiveScopeTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_scope_")
        self.root = multi_system_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        self.api.start_scan(self.cid)
        wait_idle(self.api)
        self.cache = self.api.workspace.open(self.cid)

    def _uids(self, system=None):
        rows = self.cache.query_rows(systems=[system] if system else None)
        return {r["rom_uid"] for r in rows}

    def _files(self, uids):
        return sorted(self.cache.get_row(u)["filename"] for u in uids)

    def _ingest(self, scope):
        return self.api.archive_ingest(self.cid, scope=scope)["data"]

    # --- scope 해석 -------------------------------------------------------
    def test_all_scope_covers_every_system(self):
        kind, uids = archive_service.resolve_scope(self.cache, {"kind": "all"})
        self.assertEqual(kind, "all")
        self.assertEqual(set(uids), self._uids())
        self.assertEqual(len(uids), 7)

    def test_system_scope_covers_only_that_system(self):
        kind, uids = archive_service.resolve_scope(
            self.cache, {"kind": "system", "system": "msx1"})
        self.assertEqual(kind, "system")
        self.assertEqual(set(uids), self._uids("msx1"))
        self.assertEqual(self._files(uids), ["Aleste.rom", "Nemesis.rom"])

    def test_selected_scope_covers_exactly_the_selection(self):
        chosen = sorted(self._uids("nes"))[:2]
        kind, uids = archive_service.resolve_scope(
            self.cache, {"kind": "selected", "romUids": chosen})
        self.assertEqual(kind, "selected")
        self.assertEqual(sorted(uids), chosen)

    def test_an_unknown_scope_is_not_silently_widened_to_everything(self):
        """모르는 값이 오면 전체로 확대하지 않는다 - selected에 빈 목록이면 0개다."""
        _kind, uids = archive_service.resolve_scope(
            self.cache, {"kind": "selected", "romUids": []})
        self.assertEqual(uids, [])

    # --- 실제 ingest 결과 --------------------------------------------------
    def test_ingesting_a_system_does_not_pull_in_the_whole_collection(self):
        """**이것이 사용자가 보고한 P0다.**"""
        result = self._ingest({"kind": "system", "system": "msx1"})
        self.assertEqual(set(result["ingestedRomUids"]), self._uids("msx1"))
        self.assertEqual(result["ingested"], 2)

        # System 이름 자체는 여기서 확인하지 않는다 - msx/msx1처럼 같은 플랫폼을
        # 가리키는 폴더명은 Archive Identity 키에서 정규화된다(실사용 리포트,
        # app/model/constants.py normalize_system). 이 테스트가 지키려는 불변식은
        # "고른 System의 게임만 들어갔는가"이므로 **파일명**으로 확인한다.
        files = {r["file"] for r in self.api.archive_rows()["data"]["rows"]}
        self.assertEqual(files, {"Aleste.rom", "Nemesis.rom"},
                         "MSX1만 골랐는데 다른 System의 게임이 Archive에 들어갔다")

    def test_ingesting_a_selection_ingests_only_those_games(self):
        chosen = sorted(self._uids("nes"))[:2]
        result = self._ingest({"kind": "selected", "romUids": chosen})
        self.assertEqual(sorted(result["ingestedRomUids"]), chosen)

        files = {r["file"] for r in self.api.archive_rows()["data"]["rows"]}
        self.assertEqual(files, set(self._files(chosen)))

    def test_ingesting_everything_still_ingests_everything(self):
        result = self._ingest({"kind": "all"})
        self.assertEqual(set(result["ingestedRomUids"]), self._uids())
        self.assertEqual(len(self.api.archive_rows()["data"]["rows"]), 7)

    def test_a_selection_wins_over_the_navigation_system(self):
        """게임을 고른 것이 System을 고른 것보다 구체적인 의도다(사용자 결정).

        화면은 그때 `kind: "selected"`를 보내므로, System 값이 함께 실려 와도
        선택한 게임만 들어가야 한다.
        """
        chosen = sorted(self._uids("nes"))[:1]
        result = self._ingest({"kind": "selected", "system": "msx1", "romUids": chosen})
        self.assertEqual(result["ingestedRomUids"], chosen)

    # --- 미리보기(버튼 라벨) ------------------------------------------------
    def test_preview_reports_the_same_count_that_will_be_ingested(self):
        """버튼에 적히는 개수와 실제 결과가 다르면 그 표시는 거짓말이 된다."""
        scope = {"kind": "system", "system": "nes"}
        preview = self.api.archive_ingest_preview(self.cid, scope)["data"]
        result = self._ingest(scope)
        self.assertEqual(preview["count"], len(result["ingestedRomUids"]))
        self.assertEqual(preview["count"], 3)


if __name__ == "__main__":
    unittest.main()
