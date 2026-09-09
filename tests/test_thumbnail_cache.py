"""카드 표지 썸네일 캐시.

카드 보기는 게임 하나마다 표지를 한 번씩 요청한다. 목록을 오갈 때마다 같은 파일을
다시 열어 축소하고 base64로 만드는 것은 순전히 낭비다 - 3,000개짜리 Collection에서
이것이 곧바로 체감 속도가 된다.

파일이 그대로면 결과도 그대로이므로 (경로, 크기, 수정시각, 목표 크기)를 열쇠로 삼는다.
**파일이 바뀌면 열쇠도 바뀌므로 낡은 그림이 남지 않는다** - 그것이 mtime을 열쇠에
넣는 이유다.
"""

import unittest
from pathlib import Path

from bridge import api as api_module
from bridge.api import Api
from tests.fixtures import build_esde_tree, temp_root, wait_idle


def _png(color=(200, 30, 30), size=(400, 300)):
    from PIL import Image
    import io
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class ThumbnailCacheTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_thumb_")
        self.root = build_esde_tree(self.dir / "esde")
        # 픽스처의 커버는 진짜 이미지가 아니다. 축소하려면 실제 PNG여야 한다.
        self.cover = self.root / "downloaded_media" / "ps2" / "covers" / "FFX.png"
        self.cover.write_bytes(_png())

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        self.api.start_scan(self.cid)
        wait_idle(self.api)
        self.cache = self.api.workspace.open(self.cid)
        self.uid = next(r["rom_uid"] for r in self.cache.query_rows()
                        if r["filename"] == "FFX.iso")

    def _thumb(self):
        return self.api.get_media_image(self.cid, self.uid, "Covers", True)["data"]

    def _count_encodes(self):
        """실제로 파일을 열어 인코딩한 횟수를 센다."""
        calls = []
        original = Api._encode_image_uncached

        def counting(path, max_size=None):
            calls.append((str(path), max_size))
            return original(path, max_size)

        Api._encode_image_uncached = staticmethod(counting)
        self.addCleanup(lambda: setattr(Api, "_encode_image_uncached", staticmethod(original)))
        return calls

    # --- 캐시가 실제로 걸리는가 --------------------------------------------
    def test_the_same_thumbnail_is_encoded_only_once(self):
        calls = self._count_encodes()
        first = self._thumb()
        second = self._thumb()
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1, "같은 파일을 두 번 인코딩했다")

    def test_the_thumbnail_is_a_webp_data_uri(self):
        """WebP는 같은 화질에서 JPEG보다 작다 - 브릿지로 넘어가는 문자열이 짧아진다."""
        self.assertTrue(self._thumb().startswith("data:image/webp;base64,"))

    def test_a_full_size_image_is_not_served_from_the_thumbnail_cache(self):
        thumb = self._thumb()
        full = self.api.get_media_image(self.cid, self.uid, "Covers", False)["data"]
        self.assertNotEqual(thumb, full)
        self.assertTrue(full.startswith("data:image/png;base64,"))

    # --- 파일이 바뀌면 캐시도 바뀐다 ----------------------------------------
    def test_editing_the_file_invalidates_the_cache(self):
        """낡은 그림이 남으면 사용자는 바꾼 커버가 반영되지 않았다고 본다."""
        before = self._thumb()
        # 크기와 내용을 모두 바꾼다(같은 초에 써도 열쇠가 달라지도록).
        self.cover.write_bytes(_png(color=(20, 20, 220), size=(500, 500)))
        after = self._thumb()
        self.assertNotEqual(before, after)

    # --- 캐시가 무한정 자라지 않는다 ----------------------------------------
    def test_the_cache_is_bounded(self):
        original = api_module.THUMBNAIL_CACHE_MAX
        api_module.THUMBNAIL_CACHE_MAX = 3
        self.addCleanup(lambda: setattr(api_module, "THUMBNAIL_CACHE_MAX", original))

        for i in range(6):
            path = self.dir / f"c{i}.png"
            path.write_bytes(_png(color=(i * 30, 10, 10)))
            self.api._encode_image(path, 64)
        self.assertLessEqual(len(self.api._thumb_cache), 3)

    def test_a_missing_file_is_not_cached_as_an_image(self):
        self.assertIsNone(self.api._encode_image(self.dir / "nope.png", 64))


if __name__ == "__main__":
    unittest.main()
