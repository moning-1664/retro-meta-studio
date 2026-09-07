"""
tests/test_filled_fields.py
============================
db.get_filled_fields()의 fallback 채움 규칙 검증:
- 빈 필드만 다른(오래된 순) 버전에서 채운다.
- "."은 의도적으로 비운 것으로 보고 채우지도, 채우는 소스로 쓰지도 않는다.
- 저장된 버전 데이터 자체는 건드리지 않는다(읽기 전용 합성).
- export_engine이 실제로 이 채워진 값을 내보내는지.
"""
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as cfgmod
import db as dbmod
from import_engine import import_local_to_masterdb
from export_engine import export_masterdb_to_local


def _rom_with_versions(*version_specs):
    """version_specs: [(vid, created_at, fields_dict), ...]; 첫 번째가 default."""
    rom_entry = {"system": "snes", "rom_filename": "Mario.zip", "default_version_id": version_specs[0][0],
                 "core_override": None, "media": {}, "versions": {}}
    for vid, created_at, fields in version_specs:
        full_fields = {k: ("" if k != "tags" else []) for k in dbmod.META_FIELD_KEYS}
        full_fields.update(fields)
        rom_entry["versions"][vid] = {"created_at": created_at, "source_local_id": "x",
                                       "uncertain_match": False, "fields": full_fields}
    return rom_entry


class GetFilledFieldsTests(unittest.TestCase):
    def test_fills_blank_field_from_oldest_other_version(self):
        rom = _rom_with_versions(
            ("v2", "2020-01-02T00:00:00", {"name": "Mario", "desc": ""}),
            ("v1", "2020-01-01T00:00:00", {"name": "MarioOld", "desc": "Adventure"}),
        )
        filled = dbmod.get_filled_fields(rom)
        self.assertEqual(filled["name"], "Mario")       # default 값 유지
        self.assertEqual(filled["desc"], "Adventure")    # 빈 필드만 다른 버전에서 채움
        # 저장된 원본은 안 바뀌어야 한다
        self.assertEqual(rom["versions"]["v2"]["fields"]["desc"], "")

    def test_whitespace_only_counts_as_blank(self):
        rom = _rom_with_versions(
            ("v1", "2020-01-01T00:00:00", {"name": "Mario", "desc": "   \t"}),
            ("v0", "2019-01-01T00:00:00", {"desc": "Adventure"}),
        )
        filled = dbmod.get_filled_fields(rom)
        self.assertEqual(filled["desc"], "Adventure")

    def test_dot_sentinel_is_not_overwritten(self):
        rom = _rom_with_versions(
            ("v1", "2020-01-01T00:00:00", {"name": "Mario", "desc": "."}),
            ("v0", "2019-01-01T00:00:00", {"desc": "Adventure"}),
        )
        filled = dbmod.get_filled_fields(rom)
        self.assertEqual(filled["desc"], ".", "일부러 비운 필드는 채워지면 안 됨")

    def test_dot_sentinel_is_not_used_as_fallback_source(self):
        rom = _rom_with_versions(
            ("v2", "2020-01-02T00:00:00", {"name": "Mario", "desc": ""}),
            ("v1", "2020-01-01T00:00:00", {"desc": "."}),
            ("v0", "2019-01-01T00:00:00", {"desc": "Adventure"}),
        )
        filled = dbmod.get_filled_fields(rom)
        self.assertEqual(filled["desc"], "Adventure", "'.'을 건너뛰고 그다음 실제 값을 써야 함")

    def test_empty_tags_list_is_filled(self):
        rom = _rom_with_versions(
            ("v1", "2020-01-01T00:00:00", {"name": "Mario", "tags": []}),
            ("v0", "2019-01-01T00:00:00", {"tags": ["platformer"]}),
        )
        filled = dbmod.get_filled_fields(rom)
        self.assertEqual(filled["tags"], ["platformer"])

    def test_no_other_versions_returns_default_as_is(self):
        rom = _rom_with_versions(("v1", "2020-01-01T00:00:00", {"name": "Mario"}))
        filled = dbmod.get_filled_fields(rom)
        self.assertEqual(filled["name"], "Mario")
        self.assertEqual(filled["desc"], "")


class ExportUsesFilledFieldsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="retro_filled_"))
        self.masterdb_root = self.tmpdir / "masterdb"
        dbmod.ensure_masterdb_structure(self.masterdb_root)
        self.db = dbmod.load_db(self.masterdb_root)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def make_esde_local(self, name):
        root = self.tmpdir / name
        (root / "roms" / "snes").mkdir(parents=True)
        (root / "meta" / "gamelists" / "snes").mkdir(parents=True)
        (root / "meta" / "downloaded_media" / "snes" / "covers").mkdir(parents=True)
        local = cfgmod.new_local_entry(name, f"LOCAL ({name})", "es-de")
        local["rom_path"] = str(root / "roms")
        local["metadata_path"] = str(root / "meta")
        local["media_path"] = str(root / "meta")
        return local, root

    def test_export_writes_filled_fields_not_bare_default(self):
        local_a, root_a = self.make_esde_local("a")
        (root_a / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root_a / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario</name>"
            "<desc>Classic platformer</desc></game></gameList>"
        )
        import_local_to_masterdb(local_a, self.masterdb_root, self.db)

        local_c, root_c = self.make_esde_local("c")
        (root_c / "roms" / "snes" / "Mario.zip").write_text("dummy")
        (root_c / "meta" / "gamelists" / "snes" / "gamelist.xml").write_text(
            "<gameList><game><path>./Mario.zip</path><name>Mario2</name></game></gameList>"
        )
        import_local_to_masterdb(local_c, self.masterdb_root, self.db)

        rom_entry = self.db["roms"]["snes|Mario.zip"]
        # default(최신, c)엔 desc가 없고 oldest(a)에만 desc가 있는 상황을 재현
        default_vid = rom_entry["default_version_id"]
        self.assertEqual(rom_entry["versions"][default_vid]["fields"]["desc"], "")

        local_out, root_out = self.make_esde_local("out")
        (root_out / "roms" / "snes" / "Mario.zip").write_text("dummy")
        result = export_masterdb_to_local(
            local_out, self.masterdb_root, self.db,
            {"korean_only_on_conflict": True, "copy_media": True, "copy_video": True},
            conflict_resolver=lambda *a: "ok",
        )
        self.assertEqual(result["exported"], 1)
        written = (root_out / "meta" / "gamelists" / "snes" / "gamelist.xml").read_text()
        self.assertIn("Mario", written)
        # export가 get_default_fields 그대로였다면 desc가 안 나갔어야 함
        # get_filled_fields로 바뀌었으니 이제 나가야 한다
        self.assertIn("Classic platformer", written)


if __name__ == "__main__":
    unittest.main()
