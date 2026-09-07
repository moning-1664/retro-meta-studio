import tempfile
import unittest
from pathlib import Path

from database import SQLiteRepository
from api import Api
import config as cfgmod


class SQLiteNativeReadTests(unittest.TestCase):
    def test_repository_lists_and_loads_rom(self):
        with tempfile.TemporaryDirectory() as td:
            repo = SQLiteRepository(Path(td) / "master.db")
            data = {
                "system_cores": {"snes": {"default_core": "snes9x", "is_custom": False}},
                "roms": {
                    "snes|Mario.zip": {
                        "system": "snes", "rom_filename": "Mario.zip",
                        "default_version_id": "v1", "core_override": None,
                        "versions": {"v1": {"created_at": "2026-01-01", "source_local_id": "A", "uncertain_match": False,
                                             "fields": {"name": "Mario", "desc": "Test", "tags": []}}},
                        "media": {"covers": "cover.jpg"},
                    }
                }
            }
            repo.replace_from_dict(data)
            rows = repo.list_roms()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["romKey"], "snes|Mario.zip")
            self.assertEqual(repo.get_rom("snes|Mario.zip")["versions"][0]["fields"]["name"], "Mario")
            repo.close()

    def test_api_uses_sqlite_projection_for_list(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "masterdb"
            # Avoid config mutation by constructing Api and overriding its paths.
            api = Api()
            api.cfg = {"masterdb": {"root": str(root)}, "locals": []}
            root.mkdir(parents=True)
            import db as dbmod
            dbmod.ensure_masterdb_structure(root)
            api.db = {
                "schema_version": 2,
                "system_cores": {},
                "roms": {
                    "snes|Mario.zip": {
                        "system": "snes", "rom_filename": "Mario.zip", "default_version_id": "v1",
                        "core_override": None, "versions": {"v1": {"created_at": "2026-01-01", "source_local_id": "A", "uncertain_match": False,
                        "fields": {"name": "Mario", "desc": "Test", "genre": "Action", "region": "JP", "rating": "4"}}},
                        "media": {"covers": "cover.jpg"}
                    }
                }
            }
            api._sqlite = SQLiteRepository.from_masterdb_root(root)
            api._sqlite.replace_from_dict(api.db, [])
            result = api.list_masterdb_games()
            self.assertTrue(result["ok"])
            self.assertEqual(result["data"][0]["title"], "Mario")
            self.assertEqual(result["data"][0]["region"], "JP")
            api._sqlite.close()

    def test_api_native_detail_returns_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "masterdb"
            root.mkdir(parents=True)
            api = Api()
            api.cfg = {"masterdb": {"root": str(root)}, "locals": []}
            api.db = {"schema_version": 2, "system_cores": {}, "roms": {"snes|A.zip": {
                "system": "snes", "rom_filename": "A.zip", "default_version_id": "v1", "core_override": None,
                "versions": {"v1": {"created_at": "2026-01-01", "source_local_id": "A", "uncertain_match": False,
                "fields": {"name": "A", "desc": "D", "tags": []}}}, "media": {}}}}
            api._sqlite = SQLiteRepository.from_masterdb_root(root)
            api._sqlite.replace_from_dict(api.db, [])
            result = api.get_game_detail("snes|A.zip")
            self.assertTrue(result["ok"])
            self.assertEqual(result["data"]["versions"][0]["fields"]["name"], "A")
            api._sqlite.close()


if __name__ == "__main__":
    unittest.main()
