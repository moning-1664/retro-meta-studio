"""확정한 Match가 파일 rename에도 살아남는가 (Phase 7.4).

Phase 5에서 이월된 문제다. `match_links`는 `(collection_id, system, filename)`으로
저장되는데, 사용자가 ROM 파일 이름을 바꾸면 그 키가 어긋나 **사용자가 직접 고른
Match가 조용히 끊긴다.**

파일시스템이 주는 파일 ID(NTFS의 볼륨:인덱스)는 rename과 내용 수정에도 유지되고 새
파일과는 다르다 - 실측으로 확인했다. 그걸 보조 키로 써서 되찾고, 찾으면 링크를 새
이름으로 고쳐 놓는다.

**파일 ID를 주 키로 삼지는 않는다.** 네트워크 공유나 비NTFS에서는 값이 없고, 다른
볼륨으로 옮기면 바뀐다. 그런 환경에서는 예전처럼 이름으로만 찾는다.
"""

import unittest
from pathlib import Path

from app.match import engine
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root, wait_idle


class MatchRenameTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_rename_")
        # Archive에 올릴 원본(다른 Collection)
        source_root = build_custom_esde_tree(self.dir / "source", "ps2", [
            {"filename": "Metal Gear Solid 2.iso", "title": "Metal Gear Solid 2",
             "developer": "Konami", "releasedate": "20011113T000000", "size": 1000},
        ])
        # 이름이 달라 Heuristic으로만 걸리는 대상
        self.target_root = build_custom_esde_tree(self.dir / "target", "ps2", [
            {"filename": "MGS2 Sons of Liberty.iso",
             "title": "Metal Gear Solid 2 Sons of Liberty",
             "developer": "Konami", "releasedate": "20011113T000000", "size": 1500},
        ])

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.src = self.api.create_collection("Source", "es-de", str(source_root))["data"]["id"]
        self.dst = self.api.create_collection("Target", "es-de", str(self.target_root))["data"]["id"]
        for cid in (self.src, self.dst):
            scan(self.api, cid)
        self.api.archive_ingest(self.src)

        self.row = self.api.list_rows(self.dst, limit=50)["data"]["rows"][0]
        candidates = self.api.match_candidates(self.dst, self.row["romUid"])["data"]["candidates"]
        self.chosen = candidates[0]["romIdentityId"]
        self.api.apply_match(self.dst, self.row["romUid"], self.chosen)

    def tearDown(self):
        self.api.close()

    # ------------------------------------------------------------------
    def _rename(self, old_name, new_name):
        (self.target_root / "ps2" / old_name).rename(self.target_root / "ps2" / new_name)
        # gamelist의 경로도 함께 바꿔야 실제 rename과 같은 상황이 된다.
        gamelist = self.target_root / "gamelists" / "ps2" / "gamelist.xml"
        text = gamelist.read_text(encoding="utf-8").replace(old_name, new_name)
        gamelist.write_text(text, encoding="utf-8")
        self.api.start_scan(self.dst, True)
        wait_idle(self.api)
        return self.api.list_rows(self.dst, limit=50)["data"]["rows"][0]

    def _linked(self, row):
        return self.api.match_candidates(self.dst, row["romUid"])["data"]["linkedRomIdentityId"]

    # ------------------------------------------------------------------
    def test_the_link_survives_a_rename(self):
        """이게 이 Phase의 본론이다."""
        self.assertEqual(self._linked(self.row), self.chosen, "확정 직후엔 당연히 붙어 있다")

        renamed = self._rename("MGS2 Sons of Liberty.iso", "MGS2 (USA).iso")
        self.assertEqual(renamed["file"], "MGS2 (USA).iso")
        self.assertEqual(self._linked(renamed), self.chosen,
                         "이름을 바꿨다고 사용자가 고른 Match가 끊겼다")

    def test_the_link_is_repaired_in_place(self):
        """되찾기만 하고 고쳐 놓지 않으면 매번 파일 ID로 뒤져야 한다."""
        renamed = self._rename("MGS2 Sons of Liberty.iso", "MGS2 (USA).iso")
        self._linked(renamed)   # 여기서 자가 복구가 일어난다

        links = self.api.archive.match_links_of(self.dst)
        self.assertIn(("ps2", "MGS2 (USA).iso"), links, "새 이름으로 고쳐지지 않았다")
        self.assertNotIn(("ps2", "MGS2 Sons of Liberty.iso"), links, "옛 이름이 남아 있다")

    def test_ingest_follows_the_renamed_link(self):
        """Ingest가 링크를 존중하는 것이 Match의 실제 효용이다."""
        renamed = self._rename("MGS2 Sons of Liberty.iso", "MGS2 (USA).iso")
        before = self.api.archive_rows(limit=50)["data"]["total"]
        self.api.archive_ingest(self.dst)
        after = self.api.archive_rows(limit=50)["data"]["total"]
        self.assertEqual(after, before,
                         "rename 후 Ingest가 새 Identity를 만들었다 - 링크를 못 찾았다는 뜻")

        detail = self.api.archive_detail(self.chosen)["data"]
        self.assertIn(self.dst, {s["collectionId"] for s in detail["sources"]})

    def test_a_different_file_with_the_old_name_does_not_inherit_the_link(self):
        """rename 뒤 같은 이름의 **다른 파일**이 생기면 옛 링크를 물려받으면 안 된다.

        이름만 보고 판정하면 정확히 이 사고가 난다.
        """
        self._rename("MGS2 Sons of Liberty.iso", "MGS2 (USA).iso")

        # 옛 이름으로 완전히 다른 파일을 만든다.
        (self.target_root / "ps2" / "MGS2 Sons of Liberty.iso").write_bytes(b"z" * 77)
        gamelist = self.target_root / "gamelists" / "ps2" / "gamelist.xml"
        text = gamelist.read_text(encoding="utf-8").replace(
            "</gameList>",
            "  <game><path>./MGS2 Sons of Liberty.iso</path><name>남남</name></game>\n</gameList>")
        gamelist.write_text(text, encoding="utf-8")
        self.api.start_scan(self.dst, True)
        wait_idle(self.api)

        rows = {r["file"]: r for r in self.api.list_rows(self.dst, limit=50)["data"]["rows"]}
        impostor = rows["MGS2 Sons of Liberty.iso"]
        self.assertIsNone(self._linked(impostor),
                          "옛 이름을 쓴다는 이유로 남의 Match를 물려받았다")
        self.assertEqual(self._linked(rows["MGS2 (USA).iso"]), self.chosen,
                         "정작 원래 파일의 링크가 사라졌다")

    def test_clearing_still_works_after_a_rename(self):
        renamed = self._rename("MGS2 Sons of Liberty.iso", "MGS2 (USA).iso")
        self._linked(renamed)   # 자가 복구
        self.assertTrue(self.api.clear_match(self.dst, renamed["romUid"])["data"]["cleared"])
        self.assertIsNone(self._linked(renamed))

    def test_without_a_file_id_it_behaves_as_before(self):
        """네트워크 공유나 비NTFS에서는 파일 ID가 없다 - 이름으로만 찾는다.

        그 환경에서 rename하면 링크가 끊기는 것은 예전 그대로다. 여기서 확인하는 것은
        **끊길지언정 엉뚱한 항목에 붙지는 않는다**는 것이다.
        """
        store = self.api.archive
        store.put_match_link(self.dst, "ps2", "NoId.iso", self.chosen, tier="manual")
        link = store.get_match_link(self.dst, "ps2", "NoId.iso")
        self.assertIsNotNone(link, "파일 ID 없이 저장한 링크를 이름으로 못 찾는다")
        self.assertIsNone(link["volume_file_id"])

        self.assertIsNone(store.get_match_link(self.dst, "ps2", "Renamed.iso",
                                               volume_file_id="9:9"),
                          "없는 파일 ID로 아무 링크나 물어오면 안 된다")


class MatchLinkStoreTests(unittest.TestCase):
    """저장소 수준에서 파일 ID 규칙만 따로 본다."""

    def setUp(self):
        from app.store.archive import ArchiveStore
        self.dir = temp_root("rms_linkstore_")
        self.store = ArchiveStore(self.dir / "archive.db")
        game = self.store.ensure_game("Game", "game")
        self.rid = self.store.ensure_rom_identity(game, "ps2", "game", filename="Game.iso")

    def tearDown(self):
        self.store.close()

    def test_same_name_different_file_is_not_a_match(self):
        self.store.put_match_link("c1", "ps2", "Game.iso", self.rid, volume_file_id="1:1")
        self.assertIsNone(self.store.get_match_link("c1", "ps2", "Game.iso",
                                                    volume_file_id="1:2"),
                          "이름이 같아도 다른 파일이면 남남이다")

    def test_same_file_different_name_is_a_match(self):
        self.store.put_match_link("c1", "ps2", "Game.iso", self.rid, volume_file_id="1:1")
        link = self.store.get_match_link("c1", "ps2", "Renamed.iso", volume_file_id="1:1")
        self.assertIsNotNone(link)
        self.assertEqual(link["rom_identity_id"], self.rid)
        self.assertEqual(link["filename"], "Renamed.iso", "고쳐 놓아야 한다")

    def test_the_fallback_is_scoped_to_one_collection(self):
        """다른 Collection에 같은 파일이 등록돼 있어도 남의 링크를 가져오면 안 된다."""
        self.store.put_match_link("c1", "ps2", "Game.iso", self.rid, volume_file_id="1:1")
        self.assertIsNone(self.store.get_match_link("c2", "ps2", "Other.iso",
                                                    volume_file_id="1:1"))

    def test_a_link_without_a_file_id_still_matches_by_name(self):
        self.store.put_match_link("c1", "ps2", "Game.iso", self.rid)
        link = self.store.get_match_link("c1", "ps2", "Game.iso", volume_file_id="1:1")
        self.assertIsNotNone(link, "옛 링크(파일 ID 없음)를 이름으로도 못 찾으면 회귀다")


if __name__ == "__main__":
    unittest.main()
