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
from tests.fixtures import build_custom_esde_tree, build_esde_tree, wait_idle


def configure(api, patch):
    """설정을 저장하고 곧바로 적용한다(화면이 저장 뒤에 start_archive_apply를 부르는 것과 같다)."""
    saved = api.save_archive_config(patch)
    assert saved["ok"], saved
    api._apply_archive_config()
    return saved


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

    def test_same_platform_under_a_different_esde_folder_name_is_one_identity(self):
        """msx/msx1처럼 ES-DE가 같은 플랫폼에 쓰는 다른 폴더명은 하나의 Identity여야
        한다(실사용 리포트 - 완전히 같은 파일명인데 System만 msx/msx1로 갈려 두 줄로
        보였다). System 이름 정규화 없이 raw 값을 그대로 키로 쓰면 이 규칙이 깨진다."""
        from tests.fixtures import build_custom_esde_tree

        entry = [{"filename": "Gall Force-Defense of Chaos [J].zip", "title": "갈 포스"}]
        msx_root = build_custom_esde_tree(self.dir / "msx_src", "msx", entry)
        msx1_root = build_custom_esde_tree(self.dir / "msx1_src", "msx1", entry)
        msx_id = self.api.create_collection("MSX", "es-de", str(msx_root))["data"]["id"]
        msx1_id = self.api.create_collection("MSX1", "es-de", str(msx1_root))["data"]["id"]
        for cid in (msx_id, msx1_id):
            self.api.start_scan(cid)
            wait_idle(self.api)

        self.api.archive_ingest(msx_id)
        self.api.archive_ingest(msx1_id)

        rows = self.api.archive_rows()["data"]["rows"]
        matches = [r for r in rows if r["file"] == "Gall Force-Defense of Chaos [J].zip"]
        self.assertEqual(len(matches), 1, matches)
        detail = self.api.archive_detail(matches[0]["romIdentityId"])["data"]
        self.assertEqual({s["collectionId"] for s in detail["sources"]}, {msx_id, msx1_id})

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

    def test_deleting_removes_the_archive_entry_but_not_the_real_files(self):
        """실사용 버그 리포트 - 우클릭 메뉴의 "삭제"가 Collection용 API를 그대로
        불러 매번 "Collection을 찾을 수 없습니다"로 죽고 있었다. Archive는 Plan을
        거치지 않고(D1) 그 자리에서 지운다 - 단, 실제 ROM/Media 파일(§37)은 그대로다."""
        self.api.archive_ingest(self.src)
        rid = self._rid("FFX.iso")

        result = self.api.archive_delete([rid])
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["data"]["deleted"], 1)

        self.assertFalse(self.api.archive_detail(rid)["ok"])
        files = {r["file"] for r in self.api.archive_rows()["data"]["rows"]}
        self.assertNotIn("FFX.iso", files)
        # 원본 ROM은 그대로다.
        self.assertTrue((self.source_root / "ps2" / "FFX.iso").exists())

    def test_language_tag_apply_works_on_archive_rows_too(self):
        """실사용 버그 리포트 - "System 우클릭 옵션들도 다 안 되던데(prefix 붙이기...)".
        Archive의 System 목록엔 우클릭 메뉴 자체가 안 걸려 있었다. 순수 텍스트 계산
        (app/title_affix.py)이라 Archive 데이터만으로도 그대로 계산 가능한지 확인한다."""
        from tests.fixtures import build_custom_esde_tree

        tagged_root = build_custom_esde_tree(self.dir / "tagged_src", "psx", [
            {"filename": "Rogue Galaxy (USA).iso", "title": "Rogue Galaxy"},
        ])
        tagged_id = self.api.create_collection("Tagged", "es-de", str(tagged_root))["data"]["id"]
        self.api.start_scan(tagged_id)
        wait_idle(self.api)

        self.assertTrue(self.api.save_app_settings({"titleAffix": {
            "en": {"enabled": True, "mode": "prefix", "text": "EN"},
        }})["ok"])
        self.api.archive_ingest(tagged_id)

        preview = self.api.archive_title_affix_preview("psx")
        self.assertTrue(preview["ok"], preview.get("error"))
        items = {i["filename"]: i for i in preview["data"]["items"]}
        self.assertTrue(items["Rogue Galaxy (USA).iso"]["changed"])
        self.assertEqual(items["Rogue Galaxy (USA).iso"]["newTitle"], "EN_Rogue Galaxy")

        applied = self.api.archive_apply_title_affix("psx")
        self.assertTrue(applied["ok"], applied.get("error"))
        self.assertGreaterEqual(applied["data"]["applied"], 1)
        rid = self._rid("Rogue Galaxy (USA).iso")
        self.assertEqual(self.api.archive_detail(rid)["data"]["fields"]["name"], "EN_Rogue Galaxy")

        # Collection의 gamelist.xml은 그대로다 - Archive 편집은 새어나가지 않는다(§40).
        root = ET.parse(tagged_root / "gamelists" / "psx" / "gamelist.xml").getroot()
        game = next(g for g in root.findall("game")
                    if (g.findtext("path") or "").strip() == "./Rogue Galaxy (USA).iso")
        self.assertEqual(game.findtext("name"), "Rogue Galaxy")

    def test_deleting_a_whole_system_from_the_archive(self):
        self.api.archive_ingest(self.src)
        before = {r["file"] for r in self.api.archive_rows()["data"]["rows"]}
        self.assertIn("FFX.iso", before)

        result = self.api.archive_delete_system("ps2")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertGreaterEqual(result["data"]["deleted"], 1)

        after = {r["file"] for r in self.api.archive_rows()["data"]["rows"]}
        self.assertNotIn("FFX.iso", after)
        self.assertTrue((self.source_root / "ps2" / "FFX.iso").exists())

    def test_deleting_an_unknown_id_is_reported_not_silently_ignored(self):
        result = self.api.archive_delete(["no-such-id"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["deleted"], 0)

    def test_deleting_also_removes_it_from_the_configured_archive_directory(self):
        """디렉토리가 설정돼 있는데 gamelist에서 안 지우면, "디렉토리가 진실"이라는
        원칙(app/archive/directory.py) 때문에 다음 새로고침 때 지운 항목이 되살아난다."""
        archive_dir = self.dir / "archive_out"
        configure(self.api, {"frontend": "es-de", "archiveDir": str(archive_dir)})
        self.api.archive_ingest(self.src)
        rid = self._rid("FFX.iso")
        self.api._apply_archive_config()   # 처음 한 번 디렉토리에 실제로 쓴다

        result = self.api.archive_delete([rid])
        self.assertTrue(result["ok"], result.get("error"))

        root = ET.parse(archive_dir / "gamelists" / "ps2" / "gamelist.xml").getroot()
        paths = {(g.findtext("path") or "").strip() for g in root.findall("game")}
        self.assertNotIn("./FFX.iso", paths)

        # 되살아나지 않아야 한다 - sync_from_directory()가 다시 훑어도 그대로 없다.
        self.api._apply_archive_config()
        self.assertNotIn("FFX.iso", {r["file"] for r in self.api.archive_rows()["data"]["rows"]})

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

    def test_ingest_is_refused_until_a_directory_is_chosen(self):
        """사용자 피드백 - 디렉토리를 고르지도 않았는데 수집이 돌았다. 정하기 전에는 거절한다."""
        self.assertFalse(self.api.archive_config()["data"]["configured"])
        result = self.api.start_archive_ingest(self.src, {"kind": "all"})
        self.assertFalse(result["ok"])
        self.assertIn("디렉토리", result["error"])
        wait_idle(self.api)
        self.assertFalse(self.archive_dir.exists())
        self.assertEqual(self.api.archive_rows()["data"]["total"], 0)

    def test_ingest_writes_gamelist_and_media_into_configured_directory(self):
        configure(self.api, {"archiveDir": str(self.archive_dir)})
        self._ingest_all()
        gamelist = self.archive_dir / "gamelists" / "ps2" / "gamelist.xml"
        self.assertTrue(gamelist.exists())
        paths = [g.findtext("path") for g in ET.parse(gamelist).getroot().findall("game")]
        self.assertIn("./FFX.iso", paths)
        self.assertTrue((self.archive_dir / "downloaded_media" / "ps2" / "covers" / "FFX.png").exists())

    def test_changing_directory_rewrites_everything_there(self):
        first = self.dir / "FirstArchive"
        configure(self.api, {"archiveDir": str(first)})
        self._ingest_all()
        self.assertTrue((first / "gamelists" / "ps2" / "gamelist.xml").exists())
        # 디렉토리를 바꾸면 이미 Archive에 있던 내용이 새 곳에 통째로 다시 나타난다.
        configure(self.api, {"archiveDir": str(self.archive_dir)})
        self.assertTrue((self.archive_dir / "gamelists" / "ps2" / "gamelist.xml").exists())

    def test_media_is_optional(self):
        configure(self.api, {"archiveDir": str(self.archive_dir), "mediaInternal": False})
        self._ingest_all()
        self.assertTrue((self.archive_dir / "gamelists" / "ps2" / "gamelist.xml").exists())
        self.assertFalse((self.archive_dir / "downloaded_media").exists())

    def test_pointing_at_an_existing_es_de_archive_picks_up_its_media(self):
        """실사용 버그 리포트 - 이미 ES-DE 형식으로 채워져 있는(이 앱으로 수집한 적 없는)
        외부 Archive 디렉토리를 가리키면 gamelist/ROM은 읽히는데 media는 하나도 안
        잡혔다("가지고 있는데 없다고 나온다"). `sync_from_directory()`가 media를 아예
        읽지 않았던 것이 원인이다.
        """
        existing = build_esde_tree(self.dir / "existing-archive")   # FFX는 covers+videos가 있다
        configure(self.api, {"archiveDir": str(existing)})
        rows = {r["file"]: r for r in self.api.archive_rows()["data"]["rows"]}
        self.assertIn("FFX.iso", rows)
        self.assertTrue(rows["FFX.iso"]["hasMedia"], "media가 있는데도 없다고 나왔다")
        self.assertFalse(rows["MGS2.iso"]["hasMedia"], "media가 없는 게임은 그대로 없어야 한다")

    def test_archive_edit_is_projected(self):
        configure(self.api, {"archiveDir": str(self.archive_dir)})
        self._ingest_all()
        rid = next(r["romIdentityId"] for r in self.api.archive_rows()["data"]["rows"]
                   if r["file"] == "FFX.iso")
        self.api.archive_edit(rid, {"name": "FFX Edited"})
        game = next(g for g in ET.parse(self.archive_dir / "gamelists" / "ps2" / "gamelist.xml")
                    .getroot().findall("game") if g.findtext("path") == "./FFX.iso")
        self.assertEqual(game.findtext("name"), "FFX Edited")

    def test_rejects_unknown_frontend(self):
        self.assertFalse(self.api.save_archive_config({"frontend": "nope"})["ok"])


class ArchiveConflictTests(unittest.TestCase):
    """`[n]`은 Archive 안에서 **중요한 값이 실제로 다를 때만** 뜬다."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_conf_"))
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        store = self.api.archive
        game = store.ensure_game("Game", "game")
        self.rid = store.ensure_rom_identity(game, "ps2", "game", filename="game.iso")
        self.store = store

    def tearDown(self):
        self.api.close()

    def _put(self, source, **fields):
        self.store.put_record(self.rid, source, fields, {})

    def _count(self):
        return self.api.archive_conflicts()["data"].get(self.rid, 0)

    def test_identical_sources_are_not_a_conflict(self):
        self._put("a", name="Game", desc="Same text", players="1")
        self._put("b", name="Game", desc="Same text", players="1")
        self.assertEqual(self._count(), 0)

    def test_unimportant_difference_is_ignored(self):
        self._put("a", name="Game", desc="Same text", players="1", genre="RPG")
        self._put("b", name="Game", desc="Same text", players="4", genre="Action")
        self.assertEqual(self._count(), 0)

    def test_field_missing_on_one_side_is_filled_not_conflicted(self):
        self._put("a", name="Game", desc="")
        self._put("b", name="Game", desc="Has a description")
        self.assertEqual(self._count(), 0)

    def test_different_description_is_a_conflict_and_choosing_clears_it(self):
        self._put("a", name="Game", desc="One")
        self._put("b", name="Game", desc="Two")
        self.assertEqual(self._count(), 2)
        versions = self.api.archive_versions(self.rid)["data"]["versions"]
        self.assertEqual(len(versions), 2)
        self.api.archive_choose_version(self.rid, versions[0]["recordIds"][0])
        self.assertEqual(self._count(), 0)

    def test_different_cover_is_a_conflict(self):
        self._put("a", name="Game", desc="Same")
        self._put("b", name="Game", desc="Same")
        self.store.put_media_ref(self.rid, "covers", "a", "x.png", 100)
        self.store.put_media_ref(self.rid, "covers", "b", "y.png", 200)
        self.assertEqual(self._count(), 2)

    def test_same_cover_copied_from_two_collections_is_not_a_conflict(self):
        self._put("a", name="Game", desc="Same")
        self._put("b", name="Game", desc="Same")
        self.store.put_media_ref(self.rid, "covers", "a", "x.png", 100)
        self.store.put_media_ref(self.rid, "covers", "b", "y.png", 100)
        self.assertEqual(self._count(), 0)

    def test_old_revisions_do_not_count_only_latest_per_source(self):
        self._put("a", name="Game", desc="Old")
        self._put("a", name="Game", desc="Same")
        self._put("b", name="Game", desc="Same")
        self.assertEqual(self._count(), 0)


class ArchiveMediaPasteTests(unittest.TestCase):
    """Archive 안에서(또는 Collection에서) media 하나만 골라 붙인다."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_mpaste_"))
        self.source_root = build_esde_tree(self.dir / "source")
        self.archive_dir = self.dir / "Archives"
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("Master", "es-de", str(self.source_root))["data"]["id"]
        self.api.start_scan(self.src)
        wait_idle(self.api)
        configure(self.api, {"archiveDir": str(self.archive_dir)})
        self.api.start_archive_ingest(self.src, {"kind": "all"})
        wait_idle(self.api)
        rows = {r["file"]: r["romIdentityId"] for r in self.api.archive_rows()["data"]["rows"]}
        self.ffx, self.mgs = rows["FFX.iso"], rows["MGS2.iso"]

    def tearDown(self):
        self.api.close()

    def _cover_row_uid(self, filename):
        return next(r["romUid"] for r in self.api.list_rows(self.src, limit=50)["data"]["rows"]
                    if r["file"] == filename)

    def test_pasting_a_cover_from_a_collection_replaces_only_that_media(self):
        (self.source_root / "downloaded_media" / "ps2" / "covers" / "MGS2.png").write_bytes(b"MGS2-COVER!")
        self.api.start_scan(self.src, True)
        wait_idle(self.api)
        result = self.api.archive_media_paste(
            self.ffx, "Covers", {"kind": "collection", "id": self.src, "uid": self._cover_row_uid("MGS2.iso"), "key": "Covers"})
        self.assertTrue(result["ok"], result.get("error"))
        dest = self.archive_dir / "downloaded_media" / "ps2" / "covers" / "FFX.png"
        self.assertEqual(dest.read_bytes(), b"MGS2-COVER!")
        # 다른 media와 메타데이터는 그대로다.
        self.assertTrue((self.archive_dir / "downloaded_media" / "ps2" / "videos" / "FFX.mp4").exists())
        self.assertEqual(self.api.archive_detail(self.ffx)["data"]["fields"].get("desc"), "A role-playing game.")

    def test_pasting_between_archive_items_works(self):
        (self.archive_dir / "downloaded_media" / "ps2" / "covers" / "MGS2.png").write_bytes(b"ARCH-MGS2")
        self.api.archive_project()
        self.api.archive.put_media_ref(self.mgs, "covers", "__archive__",
                                       str(self.archive_dir / "downloaded_media" / "ps2" / "covers" / "MGS2.png"), 9)
        result = self.api.archive_media_paste(
            self.ffx, "Covers", {"kind": "archive", "uid": self.mgs, "key": "Covers"})
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual((self.archive_dir / "downloaded_media" / "ps2" / "covers" / "FFX.png").read_bytes(),
                         b"ARCH-MGS2")

    def test_missing_source_media_is_refused(self):
        r = self.api.archive_media_paste(self.ffx, "Covers", {"kind": "archive", "uid": self.mgs, "key": "3DBoxes"})
        self.assertFalse(r["ok"])


class ArchiveDirectoryRefreshTests(unittest.TestCase):
    """디렉토리가 진실이다 - ROM을 넣고 새로고침하면 Archive에 나타난다."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_refresh_"))
        self.archive_dir = self.dir / "Archives"
        self.rom_dir = self.dir / "ArchiveRoms"
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        configure(self.api, {"archiveDir": str(self.archive_dir), "romDir": str(self.rom_dir)})

    def tearDown(self):
        self.api.close()

    def _rows(self):
        return {r["file"]: r for r in self.api.archive_rows()["data"]["rows"]}

    def test_added_rom_shows_up_as_rom_only_after_refresh(self):
        (self.rom_dir / "snes").mkdir(parents=True)
        (self.rom_dir / "snes" / "Zelda.sfc").write_bytes(b"rom")
        self.assertEqual(self._rows(), {})
        result = self.api.archive_refresh()["data"]
        self.assertEqual(result["added"], 1)
        row = self._rows()["Zelda.sfc"]
        self.assertTrue(row["present"])
        self.assertEqual(row["title"], "Zelda")

    def test_refresh_is_idempotent(self):
        (self.rom_dir / "snes").mkdir(parents=True)
        (self.rom_dir / "snes" / "Zelda.sfc").write_bytes(b"rom")
        self.api.archive_refresh()
        self.assertEqual(self.api.archive_refresh()["data"]["added"], 0)
        self.assertEqual(len(self._rows()), 1)

    def test_gamelist_only_entry_is_metadata_only(self):
        gl = self.archive_dir / "gamelists" / "snes"
        gl.mkdir(parents=True)
        (gl / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.sfc</path><name>Super Mario</name></game></gameList>",
            encoding="utf-8")
        self.api.archive_refresh()
        row = self._rows()["Mario.sfc"]
        self.assertFalse(row["present"])
        self.assertEqual(self.api.archive_detail(row["romIdentityId"])["data"]["fields"]["name"], "Super Mario")

    def test_rom_added_for_existing_metadata_links_without_new_row(self):
        gl = self.archive_dir / "gamelists" / "snes"
        gl.mkdir(parents=True)
        (gl / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.sfc</path><name>Super Mario</name></game></gameList>",
            encoding="utf-8")
        self.api.archive_refresh()
        (self.rom_dir / "snes").mkdir(parents=True)
        (self.rom_dir / "snes" / "Mario.sfc").write_bytes(b"rom")
        result = self.api.archive_refresh()["data"]
        self.assertEqual((result["added"], result["romsLinked"]), (0, 1))
        self.assertTrue(self._rows()["Mario.sfc"]["present"])


class ArchiveRevisionGroupingTests(unittest.TestCase):
    """Revision 탭은 **같은 내용을 한 줄로 묶는다**(실사용 피드백 - "동일 버젼이 같이 보인다")."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_rev_"))
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        store = self.api.archive
        game = store.ensure_game("Game", "game")
        self.rid = store.ensure_rom_identity(game, "ps2", "game", filename="game.iso")
        self.store = store

    def tearDown(self):
        self.api.close()

    def _detail(self):
        return self.api.archive_detail(self.rid)["data"]

    def test_identical_sources_collapse_into_one_version(self):
        self.store.put_record(self.rid, "a", {"name": "Game", "desc": "Same"}, {})
        self.store.put_record(self.rid, "b", {"name": "Game", "desc": "Same"}, {})
        detail = self._detail()
        self.assertEqual(len(detail["sources"]), 2, "출처는 둘 그대로다")
        self.assertEqual(len(detail["versions"]), 1, "내용이 같은데 버전이 둘로 나왔다")
        self.assertEqual(sorted(detail["versions"][0]["sources"]), ["a", "b"])

    def test_different_sources_stay_separate(self):
        self.store.put_record(self.rid, "a", {"name": "Game", "desc": "One"}, {})
        self.store.put_record(self.rid, "b", {"name": "Game", "desc": "Two"}, {})
        self.assertEqual(len(self._detail()["versions"]), 2)

    def test_choosing_a_version_changes_the_values_the_detail_reports(self):
        """선택이 실제로 반영되어야 한다(실사용 피드백 - "선택해도 바뀌는 것이 없다")."""
        self.store.put_record(self.rid, "a", {"name": "Game", "desc": "One"}, {})
        self.store.put_record(self.rid, "b", {"name": "Game", "desc": "Two"}, {})
        versions = self._detail()["versions"]
        wanted = next(v for v in versions if v["fields"]["desc"] == "One")
        self.api.archive_set_preferred(self.rid, wanted["recordIds"][0])
        self.assertEqual(self._detail()["fields"]["desc"], "One")


class CollectionMediaPasteTests(unittest.TestCase):
    """Collection의 게임 한 개에 **그림 한 장만** 갈아 끼운다(사용자 결정 - "Media만 복붙하기")."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_cmpaste_"))
        self.src_root = build_esde_tree(self.dir / "src")
        self.dst_root = build_esde_tree(self.dir / "dst")
        (self.dst_root / "downloaded_media" / "ps2" / "covers" / "FFX.png").write_bytes(b"OLD-COVER")
        (self.src_root / "downloaded_media" / "ps2" / "covers" / "FFX.png").write_bytes(b"NEW-COVER!" * 3)
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("S", "es-de", str(self.src_root))["data"]["id"]
        self.dst = self.api.create_collection("D", "es-de", str(self.dst_root))["data"]["id"]
        for cid in (self.src, self.dst):
            self.api.start_scan(cid)
            wait_idle(self.api)

    def tearDown(self):
        self.api.close()

    def _uid(self, cid, filename):
        return next(r["romUid"] for r in self.api.list_rows(cid, limit=50)["data"]["rows"]
                    if r["file"] == filename)

    def _paste(self):
        return self.api.media_paste(self.dst, self._uid(self.dst, "FFX.iso"), "Covers",
                                    {"kind": "collection", "id": self.src,
                                     "uid": self._uid(self.src, "FFX.iso"), "key": "Covers"})

    def test_it_goes_through_the_plan_and_only_applies_on_apply(self):
        result = self._paste()
        self.assertTrue(result["ok"], result.get("error"))
        dest = self.dst_root / "downloaded_media" / "ps2" / "covers" / "FFX.png"
        self.assertEqual(dest.read_bytes(), b"OLD-COVER", "Apply 전에 파일이 바뀌었다")
        self.assertEqual(self.api.plan_state(self.dst)["data"]["added"], 1)
        self.api.start_apply(self.dst)
        wait_idle(self.api)
        self.assertEqual(dest.read_bytes(), b"NEW-COVER!" * 3)

    def test_other_media_and_the_rom_are_left_alone(self):
        video = self.dst_root / "downloaded_media" / "ps2" / "videos" / "FFX.mp4"
        rom_before = (self.dst_root / "ps2" / "FFX.iso").read_bytes()
        video_before = video.read_bytes()
        self._paste()
        self.api.start_apply(self.dst)
        wait_idle(self.api)
        self.assertEqual(video.read_bytes(), video_before)
        self.assertEqual((self.dst_root / "ps2" / "FFX.iso").read_bytes(), rom_before)

    def test_it_does_not_ask_about_the_conflict_it_was_told_to_make(self):
        result = self._paste()
        self.assertEqual(result["data"]["conflicts"], 0)
        self.assertEqual(self.api.plan_state(self.dst)["data"]["conflicts"], 0)

    def test_a_missing_source_is_refused(self):
        result = self.api.media_paste(self.dst, self._uid(self.dst, "FFX.iso"), "3DBoxes",
                                      {"kind": "collection", "id": self.src,
                                       "uid": self._uid(self.src, "FFX.iso"), "key": "3DBoxes"})
        self.assertFalse(result["ok"])


class ArchiveConflictsOnlyFilterTests(unittest.TestCase):
    """Archive 목록에서 **다른 버전이 있는 항목만** 보는 필터(사용자 결정 - 유사롬 filter)."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_onlydiff_"))
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        store = self.api.archive
        game = store.ensure_game("Game", "game")
        self.same = store.ensure_rom_identity(game, "ps2", "same", filename="Same.iso")
        self.diff = store.ensure_rom_identity(game, "ps2", "diff", filename="Diff.iso")
        store.put_record(self.same, "a", {"name": "Same", "desc": "One"}, {})
        store.put_record(self.same, "b", {"name": "Same", "desc": "One"}, {})
        store.put_record(self.diff, "a", {"name": "Diff", "desc": "One"}, {})
        store.put_record(self.diff, "b", {"name": "Diff", "desc": "Two"}, {})

    def tearDown(self):
        self.api.close()

    def _files(self, **kwargs):
        data = self.api.archive_rows(**kwargs)["data"]
        return sorted(r["file"] for r in data["rows"]), data["total"]

    def test_off_shows_everything(self):
        self.assertEqual(self._files(), (["Diff.iso", "Same.iso"], 2))

    def test_on_shows_only_rows_that_have_another_version(self):
        self.assertEqual(self._files(conflicts_only=True), (["Diff.iso"], 1))

    def test_choosing_a_version_takes_it_out_of_the_filter(self):
        versions = self.api.archive_versions(self.diff)["data"]["versions"]
        self.api.archive_choose_version(self.diff, versions[0]["recordIds"][0])
        self.assertEqual(self._files(conflicts_only=True), ([], 0))

    def test_the_filter_combines_with_a_system_filter(self):
        self.assertEqual(self._files(conflicts_only=True, systems=["snes"]), ([], 0))


class ArchiveIdentityMergeTests(unittest.TestCase):
    """같은 ROM은 들어온 경로가 달라도 **하나의 Identity**다.

    실사용 피드백 - ROM만 있는 폴더를 먼저 읽어 "1941"로 잡아 두고 나중에 메타데이터를
    가져오면, 제목이 달라서("1941 (World)") Identity가 둘로 갈렸다.
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_merge_"))
        self.archive_dir = self.dir / "Archives"
        self.rom_dir = self.dir / "ArchiveRoms"
        (self.rom_dir / "fbneo").mkdir(parents=True)
        (self.rom_dir / "fbneo" / "1941.zip").write_bytes(b"rom" * 10)

        # 메타데이터를 가진 Collection - 같은 파일명이지만 제목이 다르다.
        self.source = build_custom_esde_tree(self.dir / "src", "fbneo", [
            {"filename": "1941.zip", "title": "1941 (World)", "genre": "Shooter"}])
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("S", "es-de", str(self.source))["data"]["id"]
        self.api.start_scan(self.src)
        wait_idle(self.api)
        configure(self.api, {"archiveDir": str(self.archive_dir), "romDir": str(self.rom_dir)})

    def tearDown(self):
        self.api.close()

    def _ingest(self):
        self.api.start_archive_ingest(self.src, {"kind": "all"})
        wait_idle(self.api)

    def _rows(self):
        return self.api.archive_rows()["data"]["rows"]

    def test_rom_first_then_metadata_stays_one_row(self):
        self.api.archive_refresh()                      # ROM만 읽는다 - 제목은 파일명이다
        self.assertEqual(len(self._rows()), 1)
        self._ingest()                                  # 그 뒤 진짜 메타데이터가 들어온다
        rows = self._rows()
        self.assertEqual(len(rows), 1, "같은 ROM인데 두 줄로 갈렸다")
        self.assertEqual(rows[0]["title"], "1941 (World)", "진짜 제목으로 올라오지 않았다")
        self.assertTrue(rows[0]["present"], "ROM 연결이 끊겼다")

    def test_metadata_first_then_rom_keeps_the_real_title(self):
        self._ingest()
        self.api.archive_refresh()                      # 나중에 읽은 파일명이 제목을 밀어내면 안 된다
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "1941 (World)")
        self.assertTrue(rows[0]["present"])

    def test_the_merged_row_keeps_the_metadata(self):
        self.api.archive_refresh()
        self._ingest()
        rid = self._rows()[0]["romIdentityId"]
        self.assertEqual(self.api.archive_detail(rid)["data"]["fields"].get("genre"), "Shooter")

    def test_merging_does_not_invent_a_version_conflict(self):
        """한쪽이 비어 있는 것은 충돌이 아니라 채워 주는 같은 버전이다."""
        self.api.archive_refresh()
        self._ingest()
        self.assertEqual(self.api.archive_conflicts()["data"], {})

    def test_different_variants_stay_apart(self):
        """(USA)와 (Europe)는 rom_key가 달라 그대로 갈린다(§46)."""
        store = self.api.archive
        game = store.ensure_game("Game", "game")
        usa = store.ensure_rom_identity(game, "ps2", "game", filename="Game (USA).iso")
        eur = store.ensure_rom_identity(game, "ps2", "game", filename="Game (Europe).iso")
        self.assertNotEqual(usa, eur)


class SameTimestampSourcesResolveDeterministicallyTests(unittest.TestCase):
    """두 출처의 `updated_at`이 같을 때 어느 값을 쓸지가 **실행할 때마다 달라지면 안 된다.**

    실제로 났던 일: ROM만 먼저 읽고(제목=파일명, 장르 없음) 곧바로 메타데이터를 수집하면
    두 출처의 시각이 같은 눈금에 들어간다(Windows의 time()은 해상도가 ~15.6ms다).
    `max(key=updated_at)`는 동점에서 순서대로 먼저 온 것을 돌려주므로, 같은 입력에
    장르가 있었다 없었다 했다. 나중에 기록된 것(record_id가 큰 것)이 이겨야 한다.
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_tie_"))
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        configure(self.api, {"archiveDir": str(self.dir / "Archives")})
        self.archive = self.api.archive

    def test_the_later_record_wins_when_the_clock_ticks_the_same(self):
        game = self.archive.ensure_game("1941", "1941")
        rid = self.archive.ensure_rom_identity(game, "fbneo", "1941", filename="1941.zip")
        self.archive.put_record(rid, "col-a", {"name": "1941"}, {})
        self.archive.put_record(rid, "col-b", {"name": "1941 (World)", "genre": "Shooter"}, {})
        # 두 출처의 시각을 같은 눈금으로 맞춘다 - 실제로 연달아 기록하면 이렇게 된다.
        self.archive._conn.execute(
            "UPDATE archive_records SET updated_at=? WHERE rom_identity_id=?",
            (1_700_000_000.0, rid))
        self.archive._conn.commit()
        for _ in range(5):
            fields, _raw = self.archive.resolve_fields(rid)
            self.assertEqual(fields.get("genre"), "Shooter", "동점에서 승자가 흔들린다")


class MergingSourcesFavoursWhatCameFirstTests(unittest.TestCase):
    """출처가 여럿일 때 최종 값을 어떻게 정하는가(사용자 결정).

    - 충돌이 아니면 **먼저 들어온 값이 이기고**, 빈 칸만 나중 것이 채운다.
    - 다만 **파일명에서 나온 제목은 진짜 제목에 자리를 내준다** - 그러지 않으면
      ROM만 읽어 만든 `1941`이 나중에 들어온 `1941 (World)`를 영영 밀어낸다.
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_merge_order_"))
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        configure(self.api, {"archiveDir": str(self.dir / "Archives")})
        self.archive = self.api.archive
        game = self.archive.ensure_game("1941", "1941")
        self.rid = self.archive.ensure_rom_identity(game, "fbneo", "1941", filename="1941.zip")

    def _fields(self):
        return self.archive.resolve_fields(self.rid)[0]

    def test_the_first_source_wins_and_later_ones_only_fill_gaps(self):
        self.archive.put_record(self.rid, "first",
                                {"name": "1941 (World)", "genre": "Shooter"}, {})
        self.archive.put_record(self.rid, "second",
                                {"name": "1941 다른 제목", "genre": "Shmup", "desc": "설명"}, {})
        fields = self._fields()
        self.assertEqual(fields["name"], "1941 (World)", "나중 출처가 앞선 값을 밀어냈다")
        self.assertEqual(fields["genre"], "Shooter")
        self.assertEqual(fields["desc"], "설명", "빈 칸이 채워지지 않았다")

    def test_a_title_taken_from_the_filename_yields_to_a_real_one(self):
        self.archive.put_record(self.rid, "rom-scan", {"name": "1941"}, {})
        self.archive.put_record(self.rid, "collection",
                                {"name": "1941 (World)", "genre": "Shooter"}, {})
        fields = self._fields()
        self.assertEqual(fields["name"], "1941 (World)", "파일명에서 온 제목이 계속 이겼다")
        self.assertEqual(fields["genre"], "Shooter")

    def test_a_real_title_is_not_replaced_by_a_filename_one(self):
        """반대 방향 - 진짜 제목이 먼저 들어왔으면 나중의 파일명 제목이 밀어내지 못한다."""
        self.archive.put_record(self.rid, "collection", {"name": "1941 (World)"}, {})
        self.archive.put_record(self.rid, "rom-scan", {"name": "1941"}, {})
        self.assertEqual(self._fields()["name"], "1941 (World)")

    def test_an_empty_value_never_wins(self):
        """빈 문자열은 값 없음과 같다(사용자 결정)."""
        self.archive.put_record(self.rid, "first", {"name": "1941 (World)", "desc": ""}, {})
        self.archive.put_record(self.rid, "second", {"desc": "진짜 설명"}, {})
        self.assertEqual(self._fields()["desc"], "진짜 설명")


class ArchiveEditSitsOnTopOfWhateverIsUnderneathTests(unittest.TestCase):
    """Archive 직접 편집은 **바탕 값 위에 덮는다** - 통째로 갈아치우지 않는다.

    실사용 리포트로 드러난 두 가지를 고정한다.

    1. Preferred를 고른 항목은 Archive에서 아무리 고쳐도 화면이 그대로였다 -
       `resolve_fields()`가 Preferred에서 곧장 돌려주고 편집 기록을 보지도 않았다.
       Preferred는 "어느 출처를 믿을지", 편집은 "내가 정한 값"이라 층위가 다르다.
    2. 제목만 바꾸는 호출(`{"name": ...}`)이 나머지 값을 통째로 날렸다 - 편집 기록이
       그대로 최종값이 되는 구조였기 때문이다.

    덮는 기준은 **키의 유무**다. 화면 저장은 전체 필드를 보내므로 빈 값으로 온 키는
    "일부러 지웠다"는 뜻이고 그대로 지켜야 한다(§11.3 CLEARED와 같은 취지).
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_edit_layer_"))
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.archive = self.api.archive
        game = self.archive.ensure_game("Game", "game")
        self.rid = self.archive.ensure_rom_identity(game, "ps2", "game", filename="game.iso")

    def _fields(self):
        return self.archive.resolve_fields(self.rid)[0]

    def _preferred_to(self, source):
        record = self.archive.latest_record(self.rid, source)
        self.api.archive_set_preferred(self.rid, record["record_id"])

    def test_an_edit_shows_up_even_when_a_revision_is_preferred(self):
        self.archive.put_record(self.rid, "a", {"name": "Game A", "genre": "RPG"}, {})
        self.archive.put_record(self.rid, "b", {"name": "Game B", "desc": "설명"}, {})
        self._preferred_to("b")

        self.api.archive_edit(self.rid, {"name": "내가 고친 제목"})
        self.assertEqual(self._fields()["name"], "내가 고친 제목",
                         "Preferred가 있으면 편집이 통째로 무시됐다")

    def test_the_preferred_revision_still_supplies_what_the_edit_did_not_touch(self):
        self.archive.put_record(self.rid, "b", {"name": "Game B", "desc": "설명", "genre": "RPG"}, {})
        self._preferred_to("b")

        self.api.archive_edit(self.rid, {"name": "새 제목"})
        fields = self._fields()
        self.assertEqual(fields["name"], "새 제목")
        self.assertEqual(fields["desc"], "설명", "편집이 건드리지 않은 값이 사라졌다")
        self.assertEqual(fields["genre"], "RPG")

    def test_editing_one_field_does_not_wipe_the_merged_values(self):
        """Preferred가 없을 때도 마찬가지다."""
        self.archive.put_record(self.rid, "a", {"name": "Game A", "genre": "RPG",
                                                "developer": "Square"}, {})
        self.api.archive_edit(self.rid, {"name": "새 제목"})
        fields = self._fields()
        self.assertEqual(fields["name"], "새 제목")
        self.assertEqual(fields["genre"], "RPG", "제목만 고쳤는데 다른 값이 날아갔다")
        self.assertEqual(fields["developer"], "Square")

    def test_a_value_the_user_cleared_stays_cleared(self):
        """화면 저장은 전체 필드를 보낸다 - 빈 값으로 온 키는 되살리면 안 된다."""
        self.archive.put_record(self.rid, "a", {"name": "Game A", "genre": "RPG"}, {})
        self.api.archive_edit(self.rid, {"name": "Game A", "genre": ""})
        self.assertEqual(self._fields()["genre"], "", "일부러 지운 값이 되살아났다")

    def test_frontend_specific_fields_survive_a_plain_edit(self):
        """직접 편집은 frontend_raw를 만들지 않는다 - 바탕의 것을 지켜야 한다."""
        self.archive.put_record(self.rid, "a", {"name": "Game A"}, {"attrib": {"id": "42"}})
        self.api.archive_edit(self.rid, {"name": "새 제목"})
        _fields, raw = self.archive.resolve_fields(self.rid)
        self.assertEqual(raw, {"attrib": {"id": "42"}}, "편집 한 번에 Frontend 고유 필드가 사라졌다")


class PreferredPicksValuesNotWholeRevisionsTests(unittest.TestCase):
    """고른 판(Preferred)은 **그 판이 가진 값**이 이긴다 - 그 판 전체로 갈아치우지 않는다.

    ARCHIVE_REVISION_POLICY.md Invariant 5-6(BestEffort). 예전에는 Preferred가 있으면
    그 레코드를 통째로 돌려줘서, 고른 판에 없는 값이 다른 출처에 멀쩡히 있어도 화면과
    Archive -> Collection Import에서 함께 사라졌다.

    media는 이미 이 방식이었다(projection.effective_media) - metadata만 어긋나 있었다.
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_pref_field_"))
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.archive = self.api.archive
        game = self.archive.ensure_game("Game", "game")
        self.rid = self.archive.ensure_rom_identity(game, "ps2", "game", filename="game.iso")

    def _fields(self):
        return self.archive.resolve_fields(self.rid)[0]

    def _prefer(self, source):
        self.api.archive_set_preferred(self.rid, self.archive.latest_record(self.rid, source)["record_id"])

    def test_the_chosen_revision_overrides_a_value_the_merge_would_have_picked(self):
        """병합만으로는 먼저 들어온 "One"이 이긴다 - 고른 판이 그것을 눌러야 한다."""
        self.archive.put_record(self.rid, "a", {"name": "Game", "desc": "One"}, {})
        self.archive.put_record(self.rid, "b", {"name": "Game", "desc": "Two"}, {})
        self.assertEqual(self._fields()["desc"], "One", "전제: 병합은 먼저 들어온 값을 쓴다")

        self._prefer("b")
        self.assertEqual(self._fields()["desc"], "Two", "고른 판의 값이 반영되지 않았다")

    def test_a_field_the_chosen_revision_lacks_still_comes_from_elsewhere(self):
        self.archive.put_record(self.rid, "a", {"name": "Game", "desc": "설명", "genre": "RPG"}, {})
        self.archive.put_record(self.rid, "b", {"name": "Game B"}, {})

        self._prefer("b")
        fields = self._fields()
        self.assertEqual(fields["name"], "Game B", "고른 판의 값이 이겨야 한다")
        self.assertEqual(fields["desc"], "설명", "고른 판에 없는 값이 통째로 사라졌다")
        self.assertEqual(fields["genre"], "RPG")

    def test_an_empty_value_in_the_chosen_revision_does_not_erase_the_others(self):
        """출처에는 "일부러 지웠다"가 없다 - gamelist에 빈 값은 모른다는 뜻(ABSENT)이다."""
        self.archive.put_record(self.rid, "a", {"name": "Game", "desc": "설명"}, {})
        self.archive.put_record(self.rid, "b", {"name": "Game B", "desc": ""}, {})

        self._prefer("b")
        self.assertEqual(self._fields()["desc"], "설명")

    def test_a_direct_edit_still_sits_on_top_of_the_chosen_revision(self):
        self.archive.put_record(self.rid, "a", {"name": "Game", "desc": "설명"}, {})
        self.archive.put_record(self.rid, "b", {"name": "Game B"}, {})
        self._prefer("b")

        self.api.archive_edit(self.rid, {"name": "내가 고친 제목"})
        fields = self._fields()
        self.assertEqual(fields["name"], "내가 고친 제목")
        self.assertEqual(fields["desc"], "설명", "편집이 fallback까지 날렸다")


class BestEffortReachesTheCollectionImportTests(unittest.TestCase):
    """문서가 Invariant 6을 명시한 자리는 Archive -> Collection Import다 - 거기까지 간다."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_besteffort_"))
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        # 설명이 있는 출처와, 없는 출처(이쪽을 Preferred로 고른다).
        rich = build_custom_esde_tree(self.dir / "rich", "ps2", [
            {"filename": "FFX.iso", "title": "Final Fantasy X", "genre": "RPG"}])
        plain = build_custom_esde_tree(self.dir / "plain", "ps2", [
            {"filename": "FFX.iso", "title": "FFX 다른 제목"}])
        self.rich = self.api.create_collection("Rich", "es-de", str(rich))["data"]["id"]
        self.plain = self.api.create_collection("Plain", "es-de", str(plain))["data"]["id"]
        for cid in (self.rich, self.plain):
            self.api.start_scan(cid)
            wait_idle(self.api)
        self.api.archive_ingest(self.rich)
        self.api.archive_ingest(self.plain)
        self.rid = self.api.archive_rows()["data"]["rows"][0]["romIdentityId"]

    def test_import_takes_the_chosen_title_but_keeps_the_genre_from_the_other_source(self):
        sources = {s["collectionId"]: s["recordId"]
                   for s in self.api.archive_detail(self.rid)["data"]["sources"]}
        self.api.archive_set_preferred(self.rid, sources[self.plain])

        self.api.archive_to_collection(self.plain, [self.rid])
        row = next(r for r in self.api.list_rows(self.plain, limit=50)["data"]["rows"]
                   if r["file"] == "FFX.iso")
        self.assertEqual(row["title"], "FFX 다른 제목", "고른 판의 제목이 안 갔다")
        self.assertEqual(row["genre"], "RPG", "고른 판에 없는 값이 Import에서 사라졌다")


class FallbackCrossesSourcesButNotTimeTests(unittest.TestCase):
    """fallback의 경계 - **다른 출처에서는 채우고, 같은 출처의 나중 판에서는 안 채운다.**

    처음 고칠 때 이 구분을 놓쳐서 TC-A4(test_archive_revision_policy.py)가 깨졌다.
    같은 출처의 Revision은 시간순 이력이라 옛 판을 고른 것은 "그 시점으로 되돌린다"는
    뜻이고, 나중 판의 값을 끌어오면 그 되돌리기가 무효가 된다. 다른 Collection의 값은
    시간이 아니라 출처가 다른 것이라 채워 주는 편이 맞다(Invariant 5-6).

    두 경우를 **한 시나리오 안에** 같이 둬서 규칙이 흔들리면 바로 드러나게 한다.
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_fallback_edge_"))
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.archive = self.api.archive
        game = self.archive.ensure_game("Game", "game")
        self.rid = self.archive.ensure_rom_identity(game, "ps2", "game", filename="game.iso")

        # 출처 "a": 옛 판(고를 대상)과 그 뒤에 desc를 더한 나중 판.
        self.archive.put_record(self.rid, "a", {"name": "Game A", "genre": "RPG"}, {})
        self.old_a = self.archive.latest_record(self.rid, "a")["record_id"]
        self.archive.put_record(self.rid, "a", {"name": "Game A", "genre": "RPG",
                                                "desc": "나중에 더한 설명"}, {})
        # 출처 "b": 처음부터 developer를 갖고 있는 다른 Collection.
        self.archive.put_record(self.rid, "b", {"name": "Game B", "developer": "Square"}, {})

    def test_the_older_revision_of_the_same_source_does_not_come_back(self):
        self.api.archive_set_preferred(self.rid, self.old_a)
        fields = self.archive.resolve_fields(self.rid)[0]
        self.assertEqual(fields["name"], "Game A")
        self.assertNotIn("desc", {k: v for k, v in fields.items() if v},
                         "되돌린 시점 이후에 더해진 값이 따라왔다")

    def test_but_another_source_still_fills_what_the_chosen_revision_never_had(self):
        self.api.archive_set_preferred(self.rid, self.old_a)
        fields = self.archive.resolve_fields(self.rid)[0]
        self.assertEqual(fields["developer"], "Square",
                         "다른 출처가 가진 값까지 막혔다")
