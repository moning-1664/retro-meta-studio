import unittest
from unittest import mock
from pathlib import Path

from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root, write_file, wait_job
from tests.test_scraper import FakeHttp, FakeResponse, config
from app.scrape.providers.screenscraper import ScreenScraperClient, ScreenScraperError


class UserRegressions(unittest.TestCase):
    def test_french_required_parameter_error_is_localizable(self):
        client = ScreenScraperClient(config(), session=FakeHttp([
            FakeResponse(ValueError(), text="Erreur : informations obligatoires manquantes!")]))
        with self.assertRaisesRegex(ScreenScraperError, "ui.scrape.missingParameters"):
            client._get("jeuInfos.php")

    def make_api(self):
        root = temp_root("rms_p0_regressions_")
        api = Api(registry_path=root / "registry.db", cache_dir=root / "cache")
        self.addCleanup(api.close)
        return root, api

    def test_family_paste_preserves_explicit_target_after_system_remap(self):
        root, api = self.make_api()
        source = build_custom_esde_tree(root / "source", "msx", [{"filename": "1942[j].zip", "title": "Incoming", "genre": "Shooter"}])
        target = build_custom_esde_tree(root / "target", "msx2", [{"filename": "1942[j].zip", "title": "Existing"}])
        sid = api.create_collection("S", "es-de", str(source))["data"]["id"]
        tid = api.create_collection("T", "es-de", str(target))["data"]["id"]
        scan(api, sid); scan(api, tid)
        uid = api.workspace.open(sid).get_row_by_filename("msx", "1942[j].zip")["rom_uid"]
        self.assertTrue(api.copy_selection(sid, [uid])["ok"])
        result = api.paste(tid, "overwrite", system_map={"msx": "msx2"},
            target_map={"msx|1942[j].zip": "msx2|1942[j].zip"}, immediate=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["count"], 1, result)

    def test_single_explicit_paste_accepts_different_rom_names(self):
        root, api = self.make_api()
        first = "Captain Tsubasa III-Koutei no Chousen [J].sfc"
        second = "Captain Tsubasa III - Koutei no Chousen (Japan).sfc"
        source = build_custom_esde_tree(root / "source", "sfc", [{"filename": first, "title": "Incoming"}])
        target = build_custom_esde_tree(root / "target", "sfc", [{"filename": second, "title": "Existing"}])
        sid = api.create_collection("S", "es-de", str(source))["data"]["id"]
        tid = api.create_collection("T", "es-de", str(target))["data"]["id"]
        scan(api, sid); scan(api, tid)
        uid = api.workspace.open(sid).get_row_by_filename("sfc", first)["rom_uid"]
        api.copy_selection(sid, [uid])
        result = api.paste(tid, "overwrite", target_map={f"sfc|{first}": f"sfc|{second}"}, immediate=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["count"], 1, result)

    def test_archive_media_set_projects_once_and_preserves_all_types(self):
        root, api = self.make_api()
        source = build_custom_esde_tree(root / "source", "msx", [{"filename": "1942.zip", "title": "1942"}])
        sid = api.create_collection("S", "es-de", str(source))["data"]["id"]
        scan(api, sid)
        api.archive_ingest(sid, scope={"kind": "all"})
        rid = api.archive_rows()["data"]["rows"][0]["romIdentityId"]
        paths = [root / "cover.png", root / "screen.png"]
        for number, path in enumerate(paths): write_file(path, b"x" * (20 + number))
        downloaded = [(number, {"media_type": kind}, str(paths[number]))
                      for number, kind in enumerate(("covers", "screenshots"))]
        with mock.patch.object(api, "_project_archive", return_value={}) as projection:
            result = api._apply_scraped_archive_media(rid, downloaded)
        self.assertTrue(result["ok"], result)
        self.assertEqual(projection.call_count, 1)
        record = api.archive.latest_record(rid, "__archive__")
        self.assertEqual({row["media_type"] for row in api.archive.media_of_revision(record["record_id"])}, {"covers", "screenshots"})
        stats = api.dashboard_stats("archive")
        self.assertTrue(stats["ok"], stats)
        self.assertEqual(stats["data"]["health"]["total"], 1)
        self.assertEqual(stats["data"]["health"]["media"], 1)
        configured = api.save_archive_config({"frontend":"es-de", "archiveDir":str(root / "Archive"), "mediaInternal":True})
        self.assertTrue(configured["ok"], configured)
        projected = api.archive_project()
        self.assertTrue(projected["ok"], projected)
        for number, path in enumerate(paths): write_file(path, b"y" * (30 + number))
        with mock.patch.object(api, "_project_archive", wraps=api._project_archive) as projection:
            applied = api._apply_scraped_archive_media(rid, downloaded)
        self.assertTrue(applied["ok"], applied)
        self.assertEqual(projection.call_count, 1)
        self.assertIn("undoOperationId", applied["data"])
        for _, media, path in downloaded:
            display = api._archive_media_display_path(rid, media["media_type"], {"abs_path":path}, cfg=api._archive_config())
            self.assertEqual(Path(display).read_bytes(), Path(path).read_bytes())
        undo = api.paste_undo("__archive__")
        self.assertTrue(undo["ok"], undo)
        restored = wait_job(api, undo["data"]["jobId"])
        self.assertFalse(restored.get("error"), restored)
        record = api.archive.latest_record(rid, "__archive__")
        self.assertEqual({row["size"] for row in api.archive.media_of_revision(record["record_id"])}, {20, 21})
