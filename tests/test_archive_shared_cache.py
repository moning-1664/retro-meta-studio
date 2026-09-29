"""Portable Archive cache and the no-copy media fast path."""

import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from app.archive import legacy, projection, shared_cache
from app.store.archive import ArchiveStore
from bridge.api import Api


class SharedArchiveCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive_dir = self.root / "archive"
        self.archive_dir.mkdir()

    def test_snapshot_seeds_another_pc_without_running_directory_scan(self):
        first = ArchiveStore(self.root / "first.db")
        game = first.ensure_game("Test Game", "test game")
        first.ensure_rom_identity(game, "ps2", "test.iso", filename="Test.iso")
        saved = shared_cache.publish(first, str(self.archive_dir), None)
        first.close()
        self.assertEqual(saved["status"], "published")
        self.assertFalse(legacy.has_legacy(self.archive_dir))

        second_path = self.root / "second.db"
        digest = shared_cache.seed_if_empty(second_path, str(self.archive_dir))
        self.assertEqual(digest, saved["digest"])
        second = ArchiveStore(second_path)
        try:
            self.assertEqual(len(second.list_rows()), 1)
        finally:
            second.close()

    def test_portable_seed_never_opens_the_shared_path_as_sqlite_uri(self):
        source = ArchiveStore(self.root / "source.db")
        game = source.ensure_game("Shared", "shared")
        source.ensure_rom_identity(game, "ps2", "shared.iso", filename="Shared.iso")
        shared_cache.publish(source, str(self.archive_dir), None)
        source.close()
        snapshot = shared_cache.snapshot_path(str(self.archive_dir))
        original = Path.as_uri

        def local_uri_only(path):
            if path == snapshot:
                raise AssertionError("network snapshot was opened as a SQLite URI")
            return original(path)

        with patch.object(Path, "as_uri", local_uri_only):
            digest = shared_cache.seed_if_empty(self.root / "second.db", str(self.archive_dir))
        self.assertTrue(digest)

    def test_changing_archive_directory_during_refresh_keeps_database_open(self):
        api = Api(registry_path=self.root / "registry.db", cache_dir=self.root / "cache")
        entered, release = threading.Event(), threading.Event()
        try:
            api.save_archive_config({"archiveDir": str(self.archive_dir)})
            original_store = api.archive

            def refresh(store, config, provider, **kwargs):
                entered.set()
                self.assertTrue(release.wait(5))
                store._conn.execute("SELECT 1 FROM rom_identities")
                return {"systems": 0, "timings": {}}

            with patch("bridge.api.archive_directory.sync_from_directory", side_effect=refresh), \
                 patch.object(api, "_publish_archive_snapshot", return_value={"status": "published"}):
                started = api.start_archive_refresh()
                self.assertTrue(started["ok"])
                self.assertTrue(entered.wait(5))
                second = self.root / "other_archive"
                changed = api.save_archive_config({"archiveDir": str(second)})
                self.assertTrue(changed["ok"], changed)
                self.assertIs(api.archive, original_store)
                release.set()
                self.assertTrue(api.jobs.wait_idle(5))
                self.assertIsNone(api.jobs.get(started["data"]["jobId"])["error"])
        finally:
            release.set()
            api.close()

    def test_legacy_database_is_preserved_before_portable_upgrade(self):
        old_path = shared_cache.snapshot_path(str(self.archive_dir))
        old = ArchiveStore(old_path)
        game = old.ensure_game("Legacy", "legacy")
        old.ensure_rom_identity(game, "ps2", "legacy.iso", filename="Legacy.iso")
        old.close()
        self.assertTrue(legacy.has_legacy(self.archive_dir))

        live = ArchiveStore(self.root / "live.db")
        legacy.import_legacy(live, self.archive_dir)
        result = shared_cache.publish(live, str(self.archive_dir), None,
                                      legacy_digest=shared_cache.fingerprint(old_path))
        live.close()
        self.assertEqual(result["status"], "published")
        self.assertFalse(legacy.has_legacy(self.archive_dir))
        self.assertEqual(len(list(old_path.parent.glob("archive.legacy-*.db"))), 1)

    def test_selecting_archive_directory_loads_portable_rows_immediately(self):
        source = ArchiveStore(self.root / "source.db")
        game = source.ensure_game("Shared", "shared")
        source.ensure_rom_identity(game, "ps2", "shared.iso", filename="Shared.iso")
        shared_cache.publish(source, str(self.archive_dir), None)
        source.close()

        other = self.root / "other_pc"
        other.mkdir()
        api = Api(registry_path=other / "registry.db", cache_dir=other / "cache")
        try:
            saved = api.save_archive_config({"frontend": "es-de",
                                             "archiveDir": str(self.archive_dir)})
            self.assertTrue(saved["ok"], saved)
            self.assertEqual(api.archive_rows()["data"]["total"], 1)
        finally:
            api.close()

    def test_changed_shared_snapshot_is_not_overwritten(self):
        first = ArchiveStore(self.root / "first.db")
        saved = shared_cache.publish(first, str(self.archive_dir), None)
        snapshot = shared_cache.snapshot_path(str(self.archive_dir))
        with closing(sqlite3.connect(snapshot)) as other:
            other.execute("CREATE TABLE other_pc_change (value TEXT)")
            other.commit()
        result = shared_cache.publish(first, str(self.archive_dir), saved["digest"])
        first.close()
        self.assertEqual(result["status"], "conflict")
        with closing(sqlite3.connect(snapshot)) as verify:
            self.assertIsNotNone(verify.execute(
                "SELECT name FROM sqlite_master WHERE name='other_pc_change'").fetchone())

    def test_newer_shared_snapshot_replaces_only_an_unchanged_local_copy(self):
        first = ArchiveStore(self.root / "first.db")
        game = first.ensure_game("First", "first")
        first.ensure_rom_identity(game, "ps2", "first.iso", filename="First.iso")
        initial = shared_cache.publish(first, str(self.archive_dir), None)
        local = self.root / "second.db"
        self.assertEqual(shared_cache.seed_if_clean(local, str(self.archive_dir)), initial["digest"])

        game = first.ensure_game("Second", "second")
        first.ensure_rom_identity(game, "ps2", "second.iso", filename="Second.iso")
        updated = shared_cache.publish(first, str(self.archive_dir), initial["digest"])
        first.close()
        self.assertEqual(updated["status"], "published")
        self.assertEqual(shared_cache.seed_if_clean(local, str(self.archive_dir), initial["digest"]),
                         updated["digest"])
        second = ArchiveStore(local)
        try:
            game = second.ensure_game("Local", "local")
            second.ensure_rom_identity(game, "ps2", "local.iso", filename="Local.iso")
        finally:
            second.close()
        self.assertIsNone(shared_cache.seed_if_clean(local, str(self.archive_dir), initial["digest"]))
        third = ArchiveStore(local)
        try:
            self.assertEqual(len(third.list_rows()), 3)
        finally:
            third.close()

    def test_refresh_pulls_another_pcs_revision_into_an_open_archive(self):
        first = ArchiveStore(self.root / "first.db")
        game = first.ensure_game("First", "first")
        first.ensure_rom_identity(game, "ps2", "first.iso", filename="First.iso")
        initial = shared_cache.publish(first, str(self.archive_dir), None)
        self.assertEqual(initial["status"], "published")

        other = self.root / "other_pc"
        other.mkdir()
        api = Api(registry_path=other / "registry.db", cache_dir=other / "cache")
        try:
            self.assertTrue(api.save_archive_config({"archiveDir": str(self.archive_dir)})["ok"])
            self.assertEqual(api.archive_rows()["data"]["total"], 1)
            second = first.ensure_game("Second", "second")
            first.ensure_rom_identity(second, "ps2", "second.iso", filename="Second.iso")
            self.assertEqual(shared_cache.publish(first, str(self.archive_dir), initial["digest"])
                             ["status"], "published")

            with patch("bridge.api.archive_directory.sync_from_directory",
                       return_value={"systems": 0, "timings": {}}):
                started = api.start_archive_refresh()
                self.assertTrue(started["ok"], started)
                self.assertTrue(api.jobs.wait_idle(5))
            result = api.jobs.get(started["data"]["jobId"])
            self.assertIsNone(result["error"])
            self.assertEqual(result["result"]["sharedPull"]["status"], "loaded")
            self.assertEqual(api.archive_rows()["data"]["total"], 2)
        finally:
            api.close()
            first.close()

    def test_refresh_rejects_diverged_local_archive_without_losing_either_copy(self):
        first = ArchiveStore(self.root / "first.db")
        game = first.ensure_game("First", "first")
        first.ensure_rom_identity(game, "ps2", "first.iso", filename="First.iso")
        initial = shared_cache.publish(first, str(self.archive_dir), None)

        other = self.root / "other_pc"
        other.mkdir()
        api = Api(registry_path=other / "registry.db", cache_dir=other / "cache")
        try:
            self.assertTrue(api.save_archive_config({"archiveDir": str(self.archive_dir)})["ok"])
            local = api.archive.ensure_game("Local", "local")
            api.archive.ensure_rom_identity(local, "ps2", "local.iso", filename="Local.iso")
            remote = first.ensure_game("Remote", "remote")
            first.ensure_rom_identity(remote, "ps2", "remote.iso", filename="Remote.iso")
            self.assertEqual(shared_cache.publish(first, str(self.archive_dir), initial["digest"])
                             ["status"], "published")

            with patch("bridge.api.archive_directory.sync_from_directory") as scan:
                started = api.start_archive_refresh()
                self.assertTrue(api.jobs.wait_idle(5))
                scan.assert_not_called()
            result = api.jobs.get(started["data"]["jobId"])
            self.assertIn("자동으로 합칠 수 없습니다", result["error"])
            self.assertEqual(api.archive_rows()["data"]["total"], 2)
            self.assertEqual(len(first.list_rows()), 2)
        finally:
            api.close()
            first.close()

    def test_explicit_shared_conflict_choice_preserves_both_versions(self):
        first = ArchiveStore(self.root / "shared-source.db")
        local = ArchiveStore(self.root / "local-copy.db")
        try:
            game = first.ensure_game("Remote", "remote")
            first.ensure_rom_identity(game, "ps2", "remote.iso", filename="Remote.iso")
            published = shared_cache.publish(first, str(self.archive_dir), None)
            own = local.ensure_game("Local", "local")
            local.ensure_rom_identity(own, "ps2", "local.iso", filename="Local.iso")
            backups = self.root / "backups"
            result = shared_cache.resolve_conflict(
                local, str(self.archive_dir), published["digest"], "shared", backups)
            self.assertEqual(result["status"], "loaded")
            self.assertEqual(len(result["backups"]), 2)
            self.assertTrue(all(Path(path).is_file() for path in result["backups"]))
            self.assertEqual(len(local.list_rows()), 1)
            self.assertEqual(local.list_rows()[0]["filename"], "Remote.iso")
        finally:
            local.close()
            first.close()

    def test_shared_conflict_refuses_stale_choice(self):
        source = ArchiveStore(self.root / "source-stale.db")
        local = ArchiveStore(self.root / "local-stale.db")
        try:
            game = source.ensure_game("First", "first")
            source.ensure_rom_identity(game, "ps2", "first.iso", filename="First.iso")
            first = shared_cache.publish(source, str(self.archive_dir), None)
            more = source.ensure_game("Second", "second")
            source.ensure_rom_identity(more, "ps2", "second.iso", filename="Second.iso")
            shared_cache.publish(source, str(self.archive_dir), first["digest"])
            result = shared_cache.resolve_conflict(
                local, str(self.archive_dir), first["digest"], "local", self.root / "backups-stale")
            self.assertEqual(result["status"], "conflict")
        finally:
            local.close()
            source.close()

    def test_internal_media_already_at_frontend_path_does_not_stat_or_copy(self):
        source = self.root / "archive" / "downloaded_media" / "ps2" / "covers" / "Test.png"
        adapter = Mock()
        adapter.media_pairs.return_value = [(str(source), str(source))]
        with patch.object(projection, "effective_media", return_value={
                "covers": {"abs_path": str(source), "size": 1}}), \
             patch.object(Path, "exists", side_effect=AssertionError("unexpected file stat")):
            copied, missing = projection._copy_media(
                Mock(), adapter, Mock(), "rid", "Test.iso", {"name": "Test"})
        self.assertEqual((copied, missing), (0, 0))


if __name__ == "__main__":
    unittest.main()
