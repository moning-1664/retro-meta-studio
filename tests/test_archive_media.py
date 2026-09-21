"""Archive Media가 화면에 보이기까지 (P0).

증상: Archive에 수집하면 Metadata도 ROM도 남는데 **Media만 보이지 않는다.**

원인을 한 곳으로 단정하지 않기 위해 파이프라인을 단계별로 검증한다.

    Collection media discovery
        -> cache의 media 행
        -> archive_ingest()
        -> archive_media 테이블
        -> archive.media_refs()
        -> Archive detail
        -> 화면이 부르는 이미지 조회

실제로 끊어져 있던 곳은 **마지막 단계**였다. 저장은 처음부터 정상이었고, Archive
항목의 이미지를 가져올 수 있는 API 자체가 없어서 화면이 Collection용
`get_media_image(collection_id, rom_uid, ...)`를 부르고 있었다. Archive에는 그
두 식별자가 없으므로 조회는 언제나 실패했다.
"""

import unittest

from bridge.api import Api
from tests.fixtures import build_esde_tree, temp_root, wait_idle, write_file


class ArchiveMediaPipelineTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_amedia_")
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        self.api.start_scan(self.cid)
        wait_idle(self.api)
        self.cache = self.api.workspace.open(self.cid)

    def _uid(self, filename="FFX.iso"):
        return next(r["rom_uid"] for r in self.cache.query_rows()
                    if r["filename"] == filename)

    def _rid(self, filename="FFX.iso"):
        return next(r["romIdentityId"] for r in self.api.archive_rows()["data"]["rows"]
                    if r["file"] == filename)

    # --- 1. Collection 쪽에 media가 있는가 ----------------------------------
    def test_the_collection_actually_has_the_media(self):
        row = self.cache.get_row(self._uid())
        self.assertIn("covers", {m["media_type"] for m in row["media"]})

    def test_the_recorded_media_path_is_absolute_and_exists(self):
        """`rel_path`라는 이름과 달리 실제로는 절대 경로다(스캐너가 그렇게 넣는다).

        Archive는 이 값을 그대로 `abs_path`로 저장하므로, 여기가 상대 경로가 되면
        Archive에서 파일을 영영 찾지 못한다.
        """
        from pathlib import Path
        row = self.cache.get_row(self._uid())
        cover = next(m for m in row["media"] if m["media_type"] == "covers")
        self.assertTrue(Path(cover["rel_path"]).is_absolute())
        self.assertTrue(Path(cover["rel_path"]).exists())

    # --- 2~4. ingest -> archive_media -> media_refs -------------------------
    def test_ingest_writes_the_media_reference(self):
        self.api.archive_ingest(self.cid, scope={"kind": "all"})
        refs = self.api.workspace and self.api.archive.media_refs(self._rid())
        self.assertIn("covers", {m["media_type"] for m in refs})

    def test_the_stored_reference_still_points_at_a_real_file(self):
        from pathlib import Path
        self.api.archive_ingest(self.cid, scope={"kind": "all"})
        cover = next(m for m in self.api.archive.media_refs(self._rid())
                     if m["media_type"] == "covers")
        self.assertTrue(Path(cover["abs_path"]).exists(), cover["abs_path"])

    # --- 5. Archive detail --------------------------------------------------
    def test_archive_detail_reports_the_media(self):
        self.api.archive_ingest(self.cid, scope={"kind": "all"})
        detail = self.api.archive_detail(self._rid())["data"]
        self.assertIn("covers", {m["media_type"] for m in detail["media"]})

    def test_the_archive_list_marks_the_row_as_having_media(self):
        self.api.archive_ingest(self.cid, scope={"kind": "all"})
        row = next(r for r in self.api.archive_rows()["data"]["rows"]
                   if r["file"] == "FFX.iso")
        self.assertTrue(row["hasMedia"])

    # --- 6. 화면이 실제로 부르는 조회 ---------------------------------------
    def test_the_image_can_actually_be_fetched_for_an_archive_entry(self):
        """**여기가 끊겨 있었다.** 저장은 다 되어 있는데 가져올 방법이 없었다."""
        self.api.archive_ingest(self.cid, scope={"kind": "all"})
        result = self.api.get_archive_media_image(self._rid(), "Covers")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(str(result["data"] or "").startswith("data:image/"),
                        "Archive 항목의 Cover 이미지를 가져오지 못했다")

    def test_a_media_type_the_entry_does_not_have_is_not_an_error(self):
        self.api.archive_ingest(self.cid, scope={"kind": "all"})
        result = self.api.get_archive_media_image(self._rid("MGS2.iso"), "Covers")
        self.assertTrue(result["ok"])

    def test_a_version_specific_image_can_be_fetched_per_source(self):
        """버전(서로 다른 출처) 고르기 화면이 각 출처의 그림을 실제로 보여줄 수 있어야
        한다(실사용 피드백 - work-mtp-0917에 있던 미리보기를 다시 가져옴). preferred
        하나만 주는 `get_archive_media_image()`와 달리, 지정한 출처의 것을 그대로
        준다."""
        other_root = build_esde_tree(self.dir / "esde2")
        write_file(other_root / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"y" * 20)
        other_cid = self.api.create_collection("C2", "es-de", str(other_root))["data"]["id"]
        self.api.start_scan(other_cid)
        wait_idle(self.api)

        self.api.archive_ingest(self.cid, scope={"kind": "all"})
        self.api.archive_ingest(other_cid, scope={"kind": "all"})
        rid = self._rid()

        result = self.api.get_archive_version_media_image(rid, self.cid, "Covers")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(str(result["data"] or "").startswith("data:image/"))

        result2 = self.api.get_archive_version_media_image(rid, other_cid, "Covers")
        self.assertTrue(result2["ok"], result2.get("error"))
        self.assertTrue(str(result2["data"] or "").startswith("data:image/"))
        # 두 출처의 그림 크기가 다르니(10바이트 vs 20바이트) data URL도 달라야 한다.
        self.assertNotEqual(result["data"], result2["data"])

    def test_an_unknown_source_returns_none_not_an_error(self):
        self.api.archive_ingest(self.cid, scope={"kind": "all"})
        result = self.api.get_archive_version_media_image(self._rid(), "not-a-real-source", "Covers")
        self.assertTrue(result["ok"])
        self.assertIsNone(result["data"])
        self.assertIsNone(result["data"])

    def test_a_missing_source_file_only_skips_that_one_media(self):
        """Archive는 파일을 복제하지 않는다(§37). 원본이 사라지면 그 media만 빠진다."""
        from pathlib import Path
        self.api.archive_ingest(self.cid, scope={"kind": "all"})
        cover = next(m for m in self.api.archive.media_refs(self._rid())
                     if m["media_type"] == "covers")
        Path(cover["abs_path"]).unlink()

        result = self.api.get_archive_media_image(self._rid(), "Covers")
        self.assertTrue(result["ok"], "파일 하나가 없다고 조회 자체가 실패하면 안 된다")
        self.assertIsNone(result["data"])


if __name__ == "__main__":
    unittest.main()
