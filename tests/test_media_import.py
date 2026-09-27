"""Local image drag/drop and clipboard staging through existing media actions."""

import base64
import io
import unittest
from pathlib import Path

from PIL import Image

from app.media_import import stage_image
from bridge.api import Api
from tests.fixtures import build_esde_tree, scan, temp_root, wait_idle


def encoded_png():
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


class MediaImportTests(unittest.TestCase):
    def setUp(self):
        self.root = temp_root("rms_media_import_")
        self.api = Api(registry_path=self.root / "registry.db", cache_dir=self.root / "cache")

    def tearDown(self):
        self.api.close()

    def test_only_verified_images_are_staged(self):
        path = stage_image(encoded_png(), self.root / "staged")
        self.assertEqual(path.suffix, ".png")
        self.assertTrue(path.is_file())
        with self.assertRaises(ValueError):
            stage_image(base64.b64encode(b"not an image").decode("ascii"), self.root / "staged")

    def test_collection_import_uses_plan_and_archive_import_applies_directly(self):
        collection_root = build_esde_tree(self.root / "collection")
        cid = self.api.create_collection("Games", "es-de", str(collection_root))["data"]["id"]
        scan(self.api, cid)
        row = self.api.list_rows(cid)["data"]["rows"][0]
        planned = self.api.import_media_image("collection", cid, row["romUid"],
                                              "Covers", encoded_png())
        self.assertTrue(planned["ok"], planned.get("error"))
        self.assertGreater(self.api.plan_state(cid)["data"]["total"], 0)

        archive_dir = self.root / "archive"
        self.api.save_archive_config({"archiveDir": str(archive_dir), "mediaInternal": True})
        self.api.archive_ingest(cid)
        rid = self.api.archive_rows()["data"]["rows"][0]["romIdentityId"]
        imported = self.api.import_media_image("archive", None, rid, "Covers", encoded_png())
        self.assertTrue(imported["ok"], imported.get("error"))
        self.assertIn("covers", {item["media_type"] for item in
                        self.api.archive_detail(rid)["data"]["media"]})
