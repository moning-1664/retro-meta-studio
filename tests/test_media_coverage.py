"""ES-DE가 실제로 쓰는 media를 빠짐없이 보는가 (Phase 7.17).

사용자의 실제 백업 `downloaded_media/<system>/` 아래 폴더는 이렇다.

    3dboxes  backcovers  covers  fanart  manuals
    marquees  miximages  physicalmedia  screenshots  titlescreens  videos

그런데 Adapter는 7종만 알고 있었고 확장자도 그림/영상만 인정했다. 그 결과 실제
백업에서 **4,814개 파일이 앱에 아예 보이지 않았다**(backcovers 1,114 · titlescreens
1,207 · fanart 1,060 · physicalmedia 871 · manuals 562).

이건 화면 문제가 아니다. 스캔이 못 본 파일은 **Plan의 복사 대상에서도, 용량 계산에서도
빠진다** - 다른 Collection으로 옮기면 그 파일들만 조용히 남겨진다.
"""

import unittest

from adapters.es_de import MEDIA_EXTENSIONS, MEDIA_FOLDERS
from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root, write_file

#: 실제 ES-DE 3.1 백업에서 확인한 폴더 이름 그대로.
REAL_FOLDERS = ("3dboxes", "backcovers", "covers", "fanart", "manuals", "marquees",
                "miximages", "physicalmedia", "screenshots", "titlescreens", "videos")


class AdapterKnowsEveryFolderTests(unittest.TestCase):
    def test_every_real_folder_is_declared(self):
        missing = [name for name in REAL_FOLDERS if name not in MEDIA_FOLDERS.values()]
        self.assertEqual(missing, [], f"실제 백업에 있는데 Adapter가 모르는 폴더: {missing}")

    def test_manuals_are_pdfs_and_pdfs_are_allowed(self):
        """설명서는 그림이 아니다. 그렇다고 media가 아닌 것은 아니다."""
        self.assertIn(".pdf", MEDIA_EXTENSIONS)

    def test_videos_cover_the_usual_containers(self):
        for ext in (".mp4", ".avi", ".webm"):
            self.assertIn(ext, MEDIA_EXTENSIONS, ext)


class ScanFindsEveryMediaTypeTests(unittest.TestCase):
    """폴더 이름을 아는 것과 실제로 스캔에 잡히는 것은 다르다."""

    def setUp(self):
        self.dir = temp_root("rms_mediacov_")
        self.root = build_custom_esde_tree(self.dir / "esde", "ps2",
                                           [{"filename": "FFX.iso", "title": "FFX"}])
        media = self.root / "downloaded_media" / "ps2"
        for folder in REAL_FOLDERS:
            suffix = ".pdf" if folder == "manuals" else (".mp4" if folder == "videos" else ".png")
            write_file(media / folder / f"FFX{suffix}", b"m" * 24)

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        scan(self.api, self.cid)
        uid = self.api.list_rows(self.cid)["data"]["rows"][0]["romUid"]
        self.row = self.api.workspace.open(self.cid).get_row(uid)

    def _types(self):
        return sorted(m["media_type"] for m in self.row["media"])

    def test_all_eleven_types_are_scanned(self):
        self.assertEqual(self._types(), sorted(REAL_FOLDERS))

    def test_the_manual_is_among_them(self):
        """PDF라 확장자 목록에서 빠져 있었다 - 실제 백업 기준 562개가 사라졌다."""
        self.assertIn("manuals", self._types())

    def test_the_types_that_used_to_be_invisible_are_there(self):
        for name in ("backcovers", "fanart", "physicalmedia", "titlescreens"):
            self.assertIn(name, self._types(), name)

    def test_the_detail_panel_gets_them_too(self):
        """Cache가 알아도 화면에 안 넘어가면 사용자에게는 없는 것과 같다."""
        detail = self.api.get_row(self.cid, self.row["rom_uid"])["data"]
        for label in ("BackCovers", "FanArt", "Manuals", "PhysicalMedia", "TitleScreens"):
            self.assertIn(label, detail["media"], label)

    def test_they_count_toward_the_stored_size(self):
        """스캔이 못 본 파일은 용량 계산에서도 빠진다."""
        stats = self.api.workspace.open(self.cid).system_stats()[0]
        self.assertGreaterEqual(int(stats["media_count"]), 1)
        self.assertGreaterEqual(int(stats["media_bytes"]), 24 * len(REAL_FOLDERS))


if __name__ == "__main__":
    unittest.main()
