"""이전 버전이 만든 Archive 디렉토리(`.rms/archive.db` + `.rms/media`)를 읽는다."""

import shutil
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import app.workspace  # noqa: F401  - Adapter 등록
from app.archive import legacy, projection
from app.store.archive import ArchiveStore


def build_legacy_archive(root: Path) -> str:
    """옛 구조를 흉내 낸다: DB + 숨은 media(.rms/media), 사용자에게 보이는 트리는 비어 있음."""
    (root / ".rms" / "media" / "cps1" / "rid1").mkdir(parents=True)
    cover = root / ".rms" / "media" / "cps1" / "rid1" / "covers.png"
    cover.write_bytes(b"png")
    store = ArchiveStore(root / ".rms" / "archive.db")
    game = store.ensure_game("Ghouls", "ghouls")
    rid = store.ensure_rom_identity(game, "cps1", "ghouls", filename="ghouls.zip")
    store.put_record(rid, "col-old", {"name": "Ghouls'n Ghosts", "desc": "d"}, {})
    record = store.latest_record(rid, "col-old")
    store.set_preferred(rid, record["record_id"])
    store._conn.execute(
        "CREATE TABLE archive_master_media (rom_identity_id TEXT, media_type TEXT,"
        " rel_path TEXT, size INTEGER, sha256 TEXT, source_record_id INTEGER, updated_at REAL)")
    store._conn.execute(
        "INSERT INTO archive_master_media VALUES (?,?,?,?,?,?,?)",
        (rid, "covers", ".rms\\media\\cps1\\rid1\\covers.png", 3, None, None, 1.0))
    store._conn.commit()
    store.close()
    return rid


class LegacyArchiveTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_legacy_"))
        self.arch = self.dir / "Archives"
        self.rid = build_legacy_archive(self.arch)
        self.archive = ArchiveStore(self.dir / "new.db")

    def tearDown(self):
        self.archive.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_detects_legacy_directory(self):
        self.assertTrue(legacy.has_legacy(self.arch))
        self.assertFalse(legacy.has_legacy(self.dir / "nothing"))

    def test_imports_identities_records_and_preferred(self):
        counts = legacy.import_legacy(self.archive, self.arch)
        self.assertEqual(counts["identities"], 1)
        self.assertEqual(counts["records"], 1)
        self.assertEqual(counts["preferred"], 1)
        fields, _ = self.archive.resolve_fields(self.rid)
        self.assertEqual(fields["name"], "Ghouls'n Ghosts")

    def test_import_is_idempotent(self):
        legacy.import_legacy(self.archive, self.arch)
        again = legacy.import_legacy(self.archive, self.arch)
        self.assertEqual(again["identities"], 0)
        self.assertEqual(again["records"], 0)
        self.assertEqual(self.archive.count_rows(), 1)

    def test_hidden_media_surfaces_in_frontend_layout(self):
        """숨은 `.rms/media`가 사용자에게 보이는 downloaded_media로 나온다 - 일부만
        보이던 문제의 핵심."""
        legacy.import_legacy(self.archive, self.arch)
        projection.project(self.archive, {"archiveDir": str(self.arch)})
        self.assertTrue((self.arch / "downloaded_media" / "cps1" / "covers" / "ghouls.png").exists())
        game = ET.parse(self.arch / "gamelists" / "cps1" / "gamelist.xml").getroot().find("game")
        self.assertEqual(game.findtext("name"), "Ghouls'n Ghosts")

    def test_old_database_is_left_untouched(self):
        before = (self.arch / ".rms" / "archive.db").read_bytes()
        legacy.import_legacy(self.archive, self.arch)
        self.assertEqual((self.arch / ".rms" / "archive.db").read_bytes(), before)
        sqlite3.connect(self.arch / ".rms" / "archive.db").close()


if __name__ == "__main__":
    unittest.main()


class ApplyConfigTests(unittest.TestCase):
    """설정 화면이 쓰는 경로: 저장 -> 적용(job). 옛 Archive 디렉토리를 고르면 내용이 나타난다."""

    def setUp(self):
        from bridge.api import Api
        self.dir = Path(tempfile.mkdtemp(prefix="rms_apply_"))
        self.arch = self.dir / "Archives"
        self.rid = build_legacy_archive(self.arch)
        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")

    def tearDown(self):
        self.api.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_saving_only_saves_and_reports_what_to_do_next(self):
        saved = self.api.save_archive_config({"archiveDir": str(self.arch)})["data"]
        self.assertTrue(saved["needsApply"])
        self.assertTrue(saved["hasLegacy"])
        self.assertEqual(self.api.archive_rows()["data"]["total"], 0)   # 아직 적용 전

    def test_apply_job_imports_legacy_and_writes_the_frontend_tree(self):
        from tests.fixtures import wait_job
        self.api.save_archive_config({"archiveDir": str(self.arch)})
        job = self.api.start_archive_apply()["data"]["jobId"]
        result = wait_job(self.api, job)
        self.assertEqual(self.api.archive_rows()["data"]["total"], 1)
        self.assertTrue((self.arch / "gamelists" / "cps1" / "gamelist.xml").exists())
        self.assertTrue((self.arch / "downloaded_media" / "cps1" / "covers" / "ghouls.png").exists())

    def test_apply_needs_a_directory(self):
        self.assertFalse(self.api.start_archive_apply()["ok"])
