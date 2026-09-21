"""Archive 테스트 (스펙 §37-44).

가장 중요한 규칙 둘을 고정한다.
- Archive는 Canonical Source가 아니다. Archive에서 고쳐도 Collection은 바뀌지 않는다(§40).
- 출처는 Collection 이름이 아니라 ID로 추적한다. 이름이 바뀌어도 관계가 유지된다(§38).
"""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from bridge.api import Api
from tests.fixtures import build_esde_tree, wait_idle


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_archive_"))
        self.source_root = build_esde_tree(self.dir / "source")
        self.target_root = build_esde_tree(self.dir / "target")
        # 대상에서 FFX를 통째로 없앤다 - Archive에서 새로 받아오는 시나리오.
        (self.target_root / "ps2" / "FFX.iso").unlink()
        (self.target_root / "downloaded_media" / "ps2" / "covers" / "FFX.png").unlink()
        (self.target_root / "downloaded_media" / "ps2" / "videos" / "FFX.mp4").unlink()

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("Master", "es-de", str(self.source_root))["data"]["id"]
        self.dst = self.api.create_collection("Android", "es-de", str(self.target_root))["data"]["id"]
        for cid in (self.src, self.dst):
            self.api.start_scan(cid)
            wait_idle(self.api)

    def tearDown(self):
        self.api.close()

    def _drop_from_target_gamelist(self, filename):
        """대상 gamelist에서 항목을 지운다 - "대상에 아예 없는" 상태를 만들기 위함."""
        path = self.target_root / "gamelists" / "ps2" / "gamelist.xml"
        tree = ET.parse(path)
        root = tree.getroot()
        for game in list(root.findall("game")):
            if (game.findtext("path") or "").strip() == f"./{filename}":
                root.remove(game)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        self.api.start_scan(self.dst, True)
        wait_idle(self.api)

    def _rid(self, filename):
        rows = self.api.archive_rows()["data"]["rows"]
        return next(r["romIdentityId"] for r in rows if r["file"] == filename)

    # ------------------------------------------------------------------
    # Collection -> Archive (§42)
    # ------------------------------------------------------------------
    def test_list_rows_carries_description_and_genre(self):
        # 목록(archive_rows)이 상세(archive_detail)와 다른 값을 보여주면 안 된다 -
        # 실사용에서 List 보기의 Description 칸이 늘 비어 있던 버그.
        self.api.archive_ingest(self.src)
        row = next(r for r in self.api.archive_rows()["data"]["rows"] if r["file"] == "FFX.iso")
        detail = self.api.archive_detail(row["romIdentityId"])["data"]
        self.assertEqual(row["desc"], detail["fields"].get("desc"))
        self.assertEqual(row["desc"], "A role-playing game.")
        self.assertEqual(row["genre"], "RPG")

    def test_archive_uids_returns_everything_not_just_a_page(self):
        """HERO의 "메타데이터 가져오기"가 쓴다(§4) - 화면 목록의 첫 페이지(limit=200)만
        가져오면 Archive가 그보다 크면 뒤가 조용히 빠진다."""
        self.api.archive_ingest(self.src)
        rows = self.api.archive_rows()["data"]["rows"]
        uids = self.api.archive_uids()["data"]
        self.assertEqual(sorted(uids), sorted(r["romIdentityId"] for r in rows))

    def test_archive_uids_can_be_filtered_by_system(self):
        self.api.archive_ingest(self.src)
        all_uids = set(self.api.archive_uids()["data"])
        ps2_uids = set(self.api.archive_uids(systems=["ps2"])["data"])
        self.assertTrue(ps2_uids)
        self.assertTrue(ps2_uids.issubset(all_uids))
        # snes 등 ps2가 아닌 System은 빠진다 - build_esde_tree의 3개는 전부 ps2다.
        self.assertEqual(ps2_uids, all_uids)

    def test_ingest_records_source_collection_id(self):
        result = self.api.archive_ingest(self.src)["data"]
        self.assertEqual(result["ingested"], 3)
        self.assertEqual(result["sourceCollectionId"], self.src)

        detail = self.api.archive_detail(self._rid("FFX.iso"))["data"]
        self.assertEqual(detail["title"], "Final Fantasy X")
        self.assertEqual([s["collectionId"] for s in detail["sources"]], [self.src])

    def test_reingesting_identical_data_creates_no_revision(self):
        """같은 내용을 다시 넣어도 Revision이 늘지 않는다(§39)."""
        first = self.api.archive_ingest(self.src)["data"]
        second = self.api.archive_ingest(self.src)["data"]
        self.assertEqual(first["revised"], 3)
        self.assertEqual(second["revised"], 0)
        self.assertEqual(second["unchanged"], 3)

    def test_source_tracking_survives_a_rename(self):
        """Collection 이름이 바뀌어도 출처 관계는 유지된다(§38)."""
        self.api.archive_ingest(self.src)
        self.api.rename_collection(self.src, "완전히 다른 이름")

        detail = self.api.archive_detail(self._rid("FFX.iso"))["data"]
        self.assertEqual([s["collectionId"] for s in detail["sources"]], [self.src])

    def test_two_collections_appear_as_separate_sources(self):
        """같은 게임이 여러 Collection에서 오면 출처별로 비교할 수 있어야 한다(§44)."""
        self.api.archive_ingest(self.src)
        self.api.archive_ingest(self.dst)

        detail = self.api.archive_detail(self._rid("MGS2.iso"))["data"]
        self.assertEqual({s["collectionId"] for s in detail["sources"]}, {self.src, self.dst})

    def test_archive_gamelist_supports_search(self):
        self.api.archive_ingest(self.src)
        rows = self.api.archive_rows(search="metal")["data"]
        self.assertEqual(len(rows["rows"]), 1)
        self.assertEqual(rows["rows"][0]["title"], "Metal Gear Solid 2")

    # ------------------------------------------------------------------
    # Archive 편집 (§40)
    # ------------------------------------------------------------------
    def test_editing_the_archive_does_not_touch_the_collection(self):
        """이 규칙이 Archive의 정체성이다. 자동 반영하면 MasterDB가 되어버린다."""
        self.api.archive_ingest(self.src)
        rid = self._rid("FFX.iso")
        self.api.archive_edit(rid, {"name": "Archive에서 고친 제목", "genre": "JRPG"})

        # Archive에는 반영된다.
        self.assertEqual(self.api.archive_detail(rid)["data"]["fields"]["name"],
                         "Archive에서 고친 제목")

        # Collection의 gamelist.xml은 그대로여야 한다.
        root = ET.parse(self.source_root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        game = next(g for g in root.findall("game")
                    if (g.findtext("path") or "").strip() == "./FFX.iso")
        self.assertEqual(game.findtext("name"), "Final Fantasy X",
                         "Archive 편집이 Collection에 새어나갔다")

    def test_editing_twice_with_the_same_value_creates_no_revision(self):
        self.api.archive_ingest(self.src)
        rid = self._rid("FFX.iso")
        first = self.api.archive_edit(rid, {"name": "같은 값"})["data"]
        second = self.api.archive_edit(rid, {"name": "같은 값"})["data"]
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])

    # ------------------------------------------------------------------
    # Archive -> Collection (§41, Scenario 8)
    # ------------------------------------------------------------------
    def test_existing_game_gets_metadata_immediately_without_a_plan(self):
        """이미 있는 항목은 바이트가 안 움직인다. Plan을 거치지 않고 바로 쓴다(D1)."""
        self.api.archive_ingest(self.src)
        rid = self._rid("MGS2.iso")
        self.api.archive_edit(rid, {"name": "새 제목", "genre": "Stealth"})

        result = self.api.archive_to_collection(self.dst, [rid])["data"]
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["planned"], 0)
        self.assertEqual(self.api.plan_state(self.dst)["data"]["total"], 0)

        root = ET.parse(self.target_root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        game = next(g for g in root.findall("game")
                    if (g.findtext("path") or "").strip() == "./MGS2.iso")
        self.assertEqual(game.findtext("name"), "새 제목")

    def test_completely_absent_game_goes_through_the_plan(self):
        """대상에 흔적이 아예 없는 항목은 파일을 옮겨야 하므로 Plan으로 간다."""
        self.api.archive_ingest(self.src)
        rid = self._rid("FFX.iso")
        self._drop_from_target_gamelist("FFX.iso")

        result = self.api.archive_to_collection(self.dst, [rid])["data"]
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["planned"], 1)

        # 확정 전까지 파일은 그대로다.
        self.assertFalse((self.target_root / "ps2" / "FFX.iso").exists())

        self.api.start_apply(self.dst)
        wait_idle(self.api)
        self.assertTrue((self.target_root / "ps2" / "FFX.iso").exists())
        self.assertTrue((self.target_root / "downloaded_media" / "ps2" / "covers" / "FFX.png").exists())

    def test_metadata_only_entry_gets_metadata_now_and_files_via_plan(self):
        """gamelist에는 있는데 ROM이 없는 상태(ES-DE에서 흔하다).

        Metadata와 파일은 독립적으로 다뤄야 한다. 메타데이터는 즉시 갱신하면서
        동시에 빠진 ROM을 Plan으로 가져와야 한다 - "이미 있는 항목"으로 뭉뚱그리면
        그 ROM을 영영 못 채운다.
        """
        self.api.archive_ingest(self.src)
        rid = self._rid("FFX.iso")

        result = self.api.archive_to_collection(self.dst, [rid])["data"]
        self.assertEqual(result["updated"], 1, "메타데이터가 즉시 갱신되지 않았다")
        self.assertEqual(result["planned"], 1, "빠진 ROM이 Plan에 올라가지 않았다")

        self.api.start_apply(self.dst)
        wait_idle(self.api)
        self.assertTrue((self.target_root / "ps2" / "FFX.iso").exists())

    def test_archive_edit_wins_over_the_original_source(self):
        """Archive에서 고친 값이 있으면 그것이 Collection으로 간다."""
        self.api.archive_ingest(self.src)
        rid = self._rid("FFX.iso")
        self._drop_from_target_gamelist("FFX.iso")
        self.api.archive_edit(rid, {"name": "Archive 제목"})

        self.api.archive_to_collection(self.dst, [rid])
        self.api.start_apply(self.dst)
        wait_idle(self.api)

        root = ET.parse(self.target_root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        game = next(g for g in root.findall("game")
                    if (g.findtext("path") or "").strip() == "./FFX.iso")
        self.assertEqual(game.findtext("name"), "Archive 제목")

    def test_vanished_source_files_are_reported_not_silently_dropped(self):
        """원본이 사라졌으면 건너뛰되 무엇이 빠졌는지 알린다(D3와 같은 태도)."""
        self.api.archive_ingest(self.src)
        rid = self._rid("FFX.iso")
        self._drop_from_target_gamelist("FFX.iso")
        (self.source_root / "ps2" / "FFX.iso").unlink()
        (self.source_root / "downloaded_media" / "ps2" / "covers" / "FFX.png").unlink()
        (self.source_root / "downloaded_media" / "ps2" / "videos" / "FFX.mp4").unlink()

        result = self.api.archive_to_collection(self.dst, [rid])["data"]
        self.assertEqual(result["planned"], 0)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertIn("찾을 수 없습니다", result["skipped"][0]["reason"])

    def test_preferred_revision_overrides_the_latest_source(self):
        """정책 §8-9: Preferred가 지정되면 더 최근 출처보다 우선한다."""
        self.api.archive_ingest(self.src)
        rid = self._rid("MGS2.iso")
        old = self.api.archive_revisions(rid, self.src)["data"][0]

        self.api.archive_ingest(self.dst)  # 더 최근 출처가 생긴다
        self.assertEqual(self.api.archive_detail(rid)["data"]["preferredRecordId"], None)

        self.api.archive_set_preferred(rid, old["record_id"])
        detail = self.api.archive_detail(rid)["data"]
        self.assertEqual(detail["preferredRecordId"], old["record_id"])

        self.api.archive_clear_preferred(rid)
        self.assertIsNone(self.api.archive_detail(rid)["data"]["preferredRecordId"])

    def test_frontend_specific_fields_survive_the_round_trip(self):
        """Collection -> Archive -> Collection 왕복에서 미지원 필드가 살아남아야 한다(§50)."""
        self.api.archive_ingest(self.src)
        rid = self._rid("FFX.iso")
        self._drop_from_target_gamelist("FFX.iso")
        self.api.archive_to_collection(self.dst, [rid])
        self.api.start_apply(self.dst)
        wait_idle(self.api)

        root = ET.parse(self.target_root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        game = next(g for g in root.findall("game")
                    if (g.findtext("path") or "").strip() == "./FFX.iso")
        self.assertEqual(game.findtext("favorite"), "true")
        self.assertEqual(game.findtext("playcount"), "17")
        self.assertEqual(game.get("source"), "ScreenScraper")


if __name__ == "__main__":
    unittest.main()


class ArchiveDirectoryTests(unittest.TestCase):
    """Archive 디렉토리가 진실이다 - 설정한 곳에 설정한 형식으로 완전히 써진다."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_archdir_"))
        self.source_root = build_esde_tree(self.dir / "source")
        self.archive_dir = self.dir / "Archives"
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("Master", "es-de", str(self.source_root))["data"]["id"]
        self.api.start_scan(self.src)
        wait_idle(self.api)

    def tearDown(self):
        self.api.close()

    def _ingest_all(self):
        self.api.start_archive_ingest(self.src, {"kind": "all"})
        wait_idle(self.api)

    def test_unconfigured_archive_writes_nothing(self):
        self.assertFalse(self.api.archive_config()["data"]["configured"])
        self._ingest_all()
        self.assertFalse(self.archive_dir.exists())

    def test_ingest_writes_gamelist_and_media_into_configured_directory(self):
        self.api.save_archive_config({"archiveDir": str(self.archive_dir)})
        self._ingest_all()
        gamelist = self.archive_dir / "gamelists" / "ps2" / "gamelist.xml"
        self.assertTrue(gamelist.exists())
        paths = [g.findtext("path") for g in ET.parse(gamelist).getroot().findall("game")]
        self.assertIn("./FFX.iso", paths)
        self.assertTrue((self.archive_dir / "downloaded_media" / "ps2" / "covers" / "FFX.png").exists())

    def test_changing_directory_rewrites_everything_there(self):
        self._ingest_all()
        self.api.save_archive_config({"archiveDir": str(self.archive_dir)})
        # 이미 Archive에 있던 내용이 새 디렉토리에 통째로 나타난다.
        self.assertTrue((self.archive_dir / "gamelists" / "ps2" / "gamelist.xml").exists())

    def test_media_is_optional(self):
        self.api.save_archive_config({"archiveDir": str(self.archive_dir), "mediaInternal": False})
        self._ingest_all()
        self.assertTrue((self.archive_dir / "gamelists" / "ps2" / "gamelist.xml").exists())
        self.assertFalse((self.archive_dir / "downloaded_media").exists())

    def test_archive_edit_is_projected(self):
        self.api.save_archive_config({"archiveDir": str(self.archive_dir)})
        self._ingest_all()
        rid = next(r["romIdentityId"] for r in self.api.archive_rows()["data"]["rows"]
                   if r["file"] == "FFX.iso")
        self.api.archive_edit(rid, {"name": "FFX Edited"})
        game = next(g for g in ET.parse(self.archive_dir / "gamelists" / "ps2" / "gamelist.xml")
                    .getroot().findall("game") if g.findtext("path") == "./FFX.iso")
        self.assertEqual(game.findtext("name"), "FFX Edited")

    def test_rejects_unknown_frontend(self):
        self.assertFalse(self.api.save_archive_config({"frontend": "nope"})["ok"])
