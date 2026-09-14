"""영상 스트리밍 서버(bridge/media_server.py)와 bridge의 영상 URL 발급."""

import unittest
import urllib.error
import urllib.request

from bridge.api import Api
from bridge.media_server import MediaServer
from tests.fixtures import build_esde_tree, temp_root, wait_job, write_file


def fetch(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, dict(response.headers), response.read()


class MediaServerTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_media_srv_")
        self.video = write_file(self.dir / "clip.mp4", bytes(range(256)) * 40)   # 10,240 B
        self.server = MediaServer()
        self.addCleanup(self.server.stop)

    def test_full_file_with_video_type(self):
        status, headers, body = fetch(self.server.url_for(self.video))
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "video/mp4")
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(body, self.video.read_bytes())

    def test_range_requests_return_206_with_the_exact_bytes(self):
        url = self.server.url_for(self.video)
        status, headers, body = fetch(url, {"Range": "bytes=100-199"})
        self.assertEqual(status, 206)
        self.assertEqual(headers["Content-Range"], "bytes 100-199/10240")
        self.assertEqual(body, self.video.read_bytes()[100:200])
        status, _, body = fetch(url, {"Range": "bytes=-16"})
        self.assertEqual((status, body), (206, self.video.read_bytes()[-16:]))
        status, _, body = fetch(url, {"Range": "bytes=10000-"})
        self.assertEqual(body, self.video.read_bytes()[10000:])

    def test_unknown_token_is_404_and_paths_are_not_in_the_url(self):
        url = self.server.url_for(self.video)
        self.assertNotIn("clip", url)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            fetch(url.rsplit("/", 1)[0] + "/not-a-token.mp4")
        self.assertEqual(caught.exception.code, 404)

    def test_unplayable_or_missing_files_get_no_url(self):
        self.assertIsNone(self.server.url_for(write_file(self.dir / "clip.avi", b"x")))
        self.assertIsNone(self.server.url_for(self.dir / "gone.mp4"))

    def test_same_file_reuses_its_url(self):
        self.assertEqual(self.server.url_for(self.video), self.server.url_for(self.video))

    def test_bound_to_loopback_only(self):
        self.assertTrue(self.server.url_for(self.video).startswith("http://127.0.0.1:"))


class BridgeVideoUrlTests(unittest.TestCase):
    """build_esde_tree: FFX에 videos/FFX.mp4가 있고 MGS2는 영상이 없다."""

    def setUp(self):
        self.dir = temp_root("rms_video_url_")
        self.root = build_esde_tree(self.dir / "esde")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("C", "es-de", str(self.root))["data"]["id"]
        wait_job(self.api, self.api.start_scan(self.cid)["data"]["jobId"])

    def uid(self, filename):
        return next(r["romUid"] for r in self.api.list_rows(self.cid, limit=10)["data"]["rows"] if r["file"] == filename)

    def test_game_with_video_gets_a_streamable_url(self):
        r = self.api.get_media_video_url(self.cid, self.uid("FFX.iso"))
        self.assertTrue(r["ok"], r.get("error"))
        status, _, body = fetch(r["data"]["url"])
        self.assertEqual(status, 200)
        self.assertEqual(body, (self.root / "downloaded_media" / "ps2" / "videos" / "FFX.mp4").read_bytes())

    def test_game_without_video_gets_none(self):
        self.assertIsNone(self.api.get_media_video_url(self.cid, self.uid("MGS2.iso"))["data"])


if __name__ == "__main__":
    unittest.main()
