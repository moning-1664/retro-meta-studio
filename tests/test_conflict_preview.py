"""충돌 창의 미디어 미리보기 - Plan이 든 충돌의 두 파일만 읽는다."""

import unittest

from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root, write_file



def _png(color):
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


PNG = _png("red")


class ConflictPreviewTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_root("rms_cpreview_")
        self.src = build_custom_esde_tree(self.dir / "src", "ps2",
                                          [{"filename": "FFX.iso", "title": "FFX"}])
        write_file(self.src / "downloaded_media" / "ps2" / "covers" / "FFX.png", PNG)
        self.dst = build_custom_esde_tree(self.dir / "dst", "ps2",
                                          [{"filename": "FFX.iso", "title": "FFX"}])
        write_file(self.dst / "downloaded_media" / "ps2" / "covers" / "FFX.png", PNG + b"\0" * 9)
        write_file(self.dst / "ps2" / "FFX.iso", b"rom")
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.s = self.api.create_collection("S", "es-de", str(self.src))["data"]["id"]
        self.d = self.api.create_collection("D", "es-de", str(self.dst))["data"]["id"]
        scan(self.api, self.s)
        scan(self.api, self.d)

    def test_media_conflict_returns_both_images(self):
        from app.plan import builder
        collection, cache, provider = self.api._plan_context(self.d)
        items = [{"system": "ps2", "filename": "FFX.iso", "rom": None, "fields": {"name": "FFX"},
                  "frontend_raw": {}, "media": [{"type": "covers", "size": len(PNG),
                                                  "path": str(self.src / "downloaded_media" / "ps2" / "covers" / "FFX.png")}]}]
        out = builder.plan_add(self.api._plan(self.d), collection, provider, items)
        key = out["conflictKeys"][0]
        r = self.api.plan_conflict_preview(self.d, key, 0)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertTrue(r["data"]["existing"].startswith("data:image"))
        self.assertTrue(r["data"]["incoming"].startswith("data:image"))

    def test_unknown_conflict_is_an_error(self):
        self.assertFalse(self.api.plan_conflict_preview(self.d, "nope", 0)["ok"])


if __name__ == "__main__":
    unittest.main()
