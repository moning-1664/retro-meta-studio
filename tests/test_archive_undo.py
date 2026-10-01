from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import adapters.es_de  # Register the standalone service test's frontend.
from adapters import get_adapter

from app.archive.undo import ArchiveUndo
from app.archive.file_copy import copy_complete
from app.archive import shared_cache
from app.store.archive import ArchiveStore


class ArchiveUndoTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ArchiveStore(self.root / "live.db")
        self.addCleanup(self.store.close)
        self.cfg = {"frontend": "es-de", "archiveDir": str(self.root / "archive"),
                    "romDir": "", "mediaInternal": True}
        self.journal = ArchiveUndo(self.root / "undo")
        self.dest = self.root / "archive" / "media.png"
        self.dest.parent.mkdir()
        self.dest.write_bytes(b"old image")
        self.source = self.root / "source.png"
        self.source.write_bytes(b"new image")

    def perform(self, publish=False):
        tx = self.journal.begin("op", self.store, self.cfg, ["ps2"])
        with tx.tracking():
            self.store.ensure_game("new game", "newgame")
            copy_complete(self.source, self.dest, replace=True)
        if publish:
            tx.prepare_publish(self.store)
            result = shared_cache.publish(self.store, self.cfg["archiveDir"], tx.data["sharedBefore"])
            self.assertEqual(result["status"], "published")
        tx.commit(self.store)
        return tx

    def games(self):
        return self.store._conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]

    def test_undo_restores_files_and_database(self):
        tx = self.perform()
        self.assertEqual(self.games(), 1)
        tx.restore(self.store)
        self.assertEqual(self.games(), 0)

    def test_recorded_copy_temporary_is_removed_during_recovery(self):
        from app.archive.undo import track_temporary
        tx = self.journal.begin("interrupted", self.store, self.cfg, ["ps2"])
        temporary = self.dest.with_name(".media.png.interrupted.rms-part")
        with tx.tracking():
            track_temporary(self.dest, temporary)
            temporary.write_bytes(b"partial")
        tx.restore(self.store)
        self.assertFalse(temporary.exists())
        self.assertEqual(self.dest.read_bytes(), b"old image")
        self.assertEqual(self.dest.read_bytes(), b"old image")
        self.assertEqual(self.source.read_bytes(), b"new image")
        self.assertIsNone(self.journal.latest(self.cfg))

    def test_external_file_change_blocks_everything(self):
        tx = self.perform()
        self.dest.write_bytes(b"external changed file")
        with self.assertRaisesRegex(ValueError, "파일이 바뀌어"):
            tx.restore(self.store)
        self.assertEqual(self.games(), 1)
        self.assertEqual(self.dest.read_bytes(), b"external changed file")

    def test_deleted_file_is_not_accepted_as_unchanged(self):
        tx = self.perform()
        self.dest.unlink()
        with self.assertRaises(ValueError):
            tx.restore(self.store)
        self.assertEqual(self.games(), 1)

    def test_later_metadata_change_blocks_undo(self):
        tx = self.perform()
        self.store.ensure_game("later", "later")
        with self.assertRaisesRegex(ValueError, "DB가 바뀌었"):
            tx.restore(self.store)
        self.assertEqual(self.games(), 2)
        self.assertEqual(self.dest.read_bytes(), b"new image")

    def test_new_shared_snapshot_is_removed_when_undoing_initial_paste(self):
        tx = self.perform(publish=True)
        tx.restore(self.store)
        self.assertFalse(shared_cache.snapshot_path(self.cfg["archiveDir"]).exists())
        self.assertEqual(self.games(), 0)

    def test_existing_shared_snapshot_is_restored(self):
        initial = shared_cache.publish(self.store, self.cfg["archiveDir"], None)["digest"]
        tx = self.perform(publish=True)
        tx.restore(self.store)
        self.assertEqual(shared_cache.fingerprint(shared_cache.snapshot_path(self.cfg["archiveDir"])), initial)

    def test_another_pc_update_blocks_undo_before_file_changes(self):
        tx = self.perform(publish=True)
        shared = shared_cache.snapshot_path(self.cfg["archiveDir"])
        shared.write_bytes(b"another pc snapshot")
        with self.assertRaisesRegex(ValueError, "다른 PC"):
            tx.restore(self.store)
        self.assertEqual(self.dest.read_bytes(), b"new image")
        self.assertEqual(self.games(), 1)
        self.assertTrue((tx.directory / "before.db").is_file())

    def test_copy_failure_rolls_back_database(self):
        tx = self.journal.begin("op", self.store, self.cfg, ["ps2"])
        with tx.tracking():
            self.store.ensure_game("new", "new")
            with patch("app.archive.file_copy.shutil.copy2", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    copy_complete(self.source, self.dest, replace=True)
        tx.failed(self.store)
        tx.restore(self.store)
        self.assertEqual(self.games(), 0)
        self.assertEqual(self.dest.read_bytes(), b"old image")

    def test_interruption_after_publish_can_recover_from_record(self):
        tx = self.perform(publish=True)
        tx.data["status"] = "running"
        tx.save()
        self.journal.recover(self.store, self.cfg)
        self.assertEqual(self.dest.read_bytes(), b"old image")
        self.assertEqual(self.games(), 0)

    def test_untagged_db_change_after_interruption_is_kept(self):
        tx = self.journal.begin("op", self.store, self.cfg, ["ps2"])
        self.store.ensure_game("partial", "partial")
        with self.assertRaises(ValueError):
            self.journal.recover(self.store, self.cfg)
        self.assertTrue((tx.directory / "before.db").exists())
        self.assertEqual(self.games(), 1)

    def test_new_file_is_removed_on_undo(self):
        tx = self.journal.begin("op", self.store, self.cfg, ["ps2"])
        new = self.dest.with_name("new.png")
        with tx.tracking():
            copy_complete(self.source, new)
        tx.commit(self.store)
        tx.restore(self.store)
        self.assertFalse(new.exists())

    def test_missing_database_backup_blocks_file_restoration(self):
        tx = self.perform()
        (tx.directory / "before.db").unlink()
        with self.assertRaisesRegex(ValueError, "DB 백업이 없습니다"):
            tx.restore(self.store)
        self.assertEqual(self.dest.read_bytes(), b"new image")
        self.assertEqual(self.games(), 1)

    def test_external_destination_is_not_owned_by_archive(self):
        tx = self.journal.begin("op", self.store, self.cfg, [])
        external = self.root / "other-collection.png"
        external.write_bytes(b"external original")
        with tx.tracking():
            with self.assertRaisesRegex(ValueError, "소유하지 않은"):
                copy_complete(self.source, external, replace=True)
        self.assertEqual(external.read_bytes(), b"external original")

    def test_successive_undos_restore_file_ids_safely(self):
        first = self.perform()
        second = self.journal.begin("second", self.store, self.cfg, [])
        self.source.write_bytes(b"third image")
        with second.tracking():
            copy_complete(self.source, self.dest, replace=True)
        second.commit(self.store)
        second.restore(self.store)
        self.journal.load(first.data["id"]).restore(self.store)
        self.assertEqual(self.dest.read_bytes(), b"old image")

    def test_restore_can_resume_after_file_publish_interruption(self):
        tx = self.perform()
        import os
        real_replace = os.replace
        def interrupted(source, destination):
            real_replace(source, destination)
            if Path(destination) == self.dest:
                raise OSError("interrupted after file restoration")
        with patch("app.archive.undo.os.replace", side_effect=interrupted):
            with self.assertRaises(OSError):
                tx.restore(self.store)
        self.journal.recover(self.store, self.cfg)
        self.assertEqual(self.dest.read_bytes(), b"old image")
        self.assertEqual(self.games(), 0)


class ArchiveUndoApiTests(TestCase):
    def setUp(self):
        from bridge.api import Api
        from tests.fixtures import build_esde_tree, wait_idle
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = build_esde_tree(self.root / "source")
        self.api = Api(registry_path=self.root / "registry.db", cache_dir=self.root / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("source", "es-de", str(self.source))["data"]["id"]
        self.api.start_scan(self.cid)
        wait_idle(self.api)
        self.api.save_archive_config({"archiveDir": str(self.root / "archive")})
        self.api._apply_archive_config()
        self.api.archive_ingest(self.cid)
        self.rid = self.api.archive_rows()["data"]["rows"][0]["romIdentityId"]
        self.filename = self.api.archive.get_identity(self.rid)["filename"]
        uid = next(row["romUid"] for row in self.api.list_rows(self.cid)["data"]["rows"]
                   if row["file"] == self.filename)
        self.api.archive_edit(self.rid, {"genre": "old genre"})
        self.api.copy_selection(self.cid, [uid])

    def execute(self):
        from tests.fixtures import wait_idle
        preview = self.api.archive_paste("overwrite", immediate=True)["data"]
        self.assertTrue(preview["undoable"])
        decisions = {row["key"]: "overwrite" for row in preview["collisions"]}
        started = self.api.paste_execute(preview["operationId"], decisions)
        self.assertTrue(started["ok"], started)
        wait_idle(self.api)
        return self.api.get_job_progress(started["data"]["jobId"])["data"]

    def test_api_paste_and_undo_restore_metadata_and_shared_digest(self):
        from tests.fixtures import wait_idle
        cfg = self.api._archive_config()
        shared = shared_cache.snapshot_path(cfg["archiveDir"])
        before = shared_cache.fingerprint(shared)
        result = self.execute()
        self.assertIsNone(result["error"], result)
        self.assertTrue(result["result"]["undoOperationId"])
        self.assertNotEqual(self.api.archive.resolve_fields(self.rid)[0]["genre"], "old genre")
        undo = self.api.paste_undo("__archive__")
        self.assertTrue(undo["ok"], undo)
        wait_idle(self.api)
        job = self.api.get_job_progress(undo["data"]["jobId"])["data"]
        self.assertIsNone(job["error"], job)
        self.assertEqual(self.api.archive.resolve_fields(self.rid)[0]["genre"], "old genre")
        self.assertEqual(shared_cache.fingerprint(shared), before)

    def test_projection_failure_rolls_back_metadata_and_frontend(self):
        with patch("bridge.api.archive_projection.project", side_effect=OSError("frontend unavailable")):
            result = self.execute()
        self.assertIsNotNone(result["error"])
        self.assertEqual(self.api.archive.resolve_fields(self.rid)[0]["genre"], "old genre")
        self.assertIsNone(self.api._archive_recovery_error)

    def test_later_edit_is_undone_before_paste(self):
        from tests.fixtures import wait_idle
        result = self.execute()
        self.assertIsNone(result["error"], result)
        self.api.archive_edit(self.rid, {"genre": "later edit"})
        undo = self.api.paste_undo("__archive__")
        wait_idle(self.api)
        job = self.api.get_job_progress(undo["data"]["jobId"])["data"]
        self.assertIsNone(job["error"], job)
        self.assertNotEqual(self.api.archive.resolve_fields(self.rid)[0]["genre"], "later edit")

    def test_metadata_edit_redo(self):
        from tests.fixtures import wait_idle
        self.api.archive_edit(self.rid, {"genre": "redo genre"})
        undo = self.api.paste_undo("__archive__")
        wait_idle(self.api)
        self.assertIsNone(self.api.get_job_progress(undo["data"]["jobId"])["data"]["error"])
        redo = self.api.paste_redo("__archive__")
        self.assertTrue(redo["ok"], redo)
        wait_idle(self.api)
        job = self.api.get_job_progress(redo["data"]["jobId"])["data"]
        self.assertIsNone(job["error"], job)
        self.assertEqual(self.api.archive.resolve_fields(self.rid)[0]["genre"], "redo genre")

    def test_archive_delete_undo_restores_identity(self):
        from tests.fixtures import wait_idle
        result = self.api.archive_delete([self.rid])
        self.assertTrue(result["ok"], result)
        self.assertIsNone(self.api.archive.get_identity(self.rid))
        undo = self.api.paste_undo("__archive__")
        wait_idle(self.api)
        job = self.api.get_job_progress(undo["data"]["jobId"])["data"]
        self.assertIsNone(job["error"], job)
        self.assertIsNotNone(self.api.archive.get_identity(self.rid))

    def test_restart_recovers_recorded_interruption_before_seeding_shared_db(self):
        from bridge.api import Api
        result = self.execute()
        self.assertIsNone(result["error"], result)
        tx = self.api._archive_journal.load(result["result"]["undoOperationId"])
        tx.data["status"] = "running"
        tx.save()
        self.api.close()
        restarted = Api(registry_path=self.root / "registry.db", cache_dir=self.root / "cache")
        self.addCleanup(restarted.close)
        self.assertIsNone(restarted._archive_recovery_error)
        self.assertEqual(restarted.archive.resolve_fields(self.rid)[0]["genre"], "old genre")

    def test_shared_change_rejects_paste_before_any_metadata_write(self):
        shared = shared_cache.snapshot_path(self.api._archive_config()["archiveDir"])
        shared.write_bytes(b"foreign snapshot changed")
        result = self.execute()
        self.assertIsNotNone(result["error"])
        self.assertEqual(self.api.archive.resolve_fields(self.rid)[0]["genre"], "old genre")

    def test_archive_journal_does_not_depend_on_local_collection_undo(self):
        with patch("bridge.api.supports_local_undo", return_value=False):
            preview = self.api.archive_paste("overwrite", immediate=True)["data"]
        self.assertTrue(preview["undoable"])
        decisions = {row["key"]: "overwrite" for row in preview["collisions"]}
        started = self.api.paste_execute(preview["operationId"], decisions)
        self.assertTrue(started["ok"], started)
        from tests.fixtures import wait_idle
        wait_idle(self.api)
        self.assertIsNone(self.api.get_job_progress(started["data"]["jobId"])["data"]["error"])


class ArchiveOwnedOperationsTests(TestCase):
    def setUp(self):
        from bridge.api import Api
        from tests.fixtures import build_esde_tree, wait_idle
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = build_esde_tree(self.root / "source")
        self.api = Api(registry_path=self.root / "registry.db", cache_dir=self.root / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("source", "es-de", str(self.source))["data"]["id"]
        self.api.start_scan(self.cid)
        wait_idle(self.api)
        self.uid = next(row["romUid"] for row in self.api.list_rows(self.cid)["data"]["rows"] if row["file"] == "FFX.iso")
        self.api.save_archive_config({"archiveDir": str(self.root / "archive")})
        self.api._apply_archive_config()
        self.api.copy_selection(self.cid, [self.uid])
        result = self.api.archive_paste("overwrite")
        self.assertTrue(result["ok"], result)
        self.rid = self.api.archive.find_rom_identity("ps2", "FFX.iso")["rom_identity_id"]
        self.rom = self.root / "archive" / "ps2" / "FFX.iso"

    def job(self, started):
        from tests.fixtures import wait_idle
        self.assertTrue(started["ok"], started)
        wait_idle(self.api)
        result = self.api.get_job_progress(started["data"]["jobId"])["data"]
        self.assertIsNone(result["error"], result)
        return result["result"]

    def test_archive_rename_undo_redo_without_rom_copy(self):
        result = self.job(self.api.rename_game("__archive__", self.rid, "FFX new.iso"))
        self.assertFalse(self.rom.exists())
        renamed = self.rom.with_name("FFX new.iso")
        self.assertTrue(renamed.exists())
        self.job(self.api.paste_undo("__archive__"))
        self.assertTrue(self.rom.exists())
        self.assertFalse(renamed.exists())
        self.job(self.api.paste_redo("__archive__"))
        self.assertTrue(renamed.exists())

    def test_owned_rom_delete_undo_redo(self):
        original = self.rom.read_bytes()
        result = self.api.archive_rom_delete([self.rid])
        self.assertTrue(result["ok"], result)
        self.assertFalse(self.rom.exists())
        self.job(self.api.paste_undo("__archive__"))
        self.assertEqual(self.rom.read_bytes(), original)
        self.job(self.api.paste_redo("__archive__"))
        self.assertFalse(self.rom.exists())

    def test_archive_replace_rom_copies_once_and_undo_restores_old_rom(self):
        self.rom.write_bytes(b"old archive ROM")
        source_rom = self.source / "ps2" / "FFX.iso"
        source_rom.write_bytes(b"new ROM contents")
        self.api.copy_selection(self.cid, [self.uid])
        preview = self.api.archive_paste("replace", immediate=True)["data"]
        decisions = {row["key"]: "overwrite" for row in preview["collisions"]}
        import shutil
        real_copy = shutil.copy2
        calls = []
        def copy(source, destination, *args, **kwargs):
            calls.append(str(source))
            return real_copy(source, destination, *args, **kwargs)
        with patch("app.archive.file_copy.shutil.copy2", side_effect=copy):
            self.job(self.api.paste_execute(preview["operationId"], decisions))
        self.assertEqual(calls.count(str(source_rom)), 1)
        self.assertNotIn(str(self.rom), calls)
        self.assertEqual(self.rom.read_bytes(), b"new ROM contents")
        self.job(self.api.paste_undo("__archive__"))
        self.assertEqual(self.rom.read_bytes(), b"old archive ROM")

    def test_archive_cut_to_collection_and_undo_both_sides(self):
        cut = self.api.cut_selection("__archive__", [self.rid])
        self.assertTrue(cut["ok"], cut)
        preview = self.api.paste(self.cid, immediate=True)["data"]
        decisions = {row["key"]: "overwrite" for row in preview["collisions"]}
        self.job(self.api.paste_execute(preview["operationId"], decisions))
        self.assertIsNone(self.api.archive.get_identity(self.rid))
        self.assertFalse(self.rom.exists())
        self.assertTrue((self.source / "ps2" / "FFX.iso").exists())
        self.job(self.api.paste_undo(self.cid))
        self.assertIsNotNone(self.api.archive.get_identity(self.rid))
        self.assertTrue(self.rom.exists())

    def test_collection_cut_to_archive_and_undo_both_sides(self):
        # Remove the existing Archive identity first; source ROM stays external.
        self.api.archive_delete_owned([self.rid])
        cut = self.api.cut_selection(self.cid, [self.uid])
        self.assertTrue(cut["ok"], cut)
        preview = self.api.archive_paste("overwrite", immediate=True)
        self.assertTrue(preview["ok"], preview)
        self.job(self.api.paste_execute(preview["data"]["operationId"], {}))
        self.assertFalse((self.source / "ps2" / "FFX.iso").exists())
        self.assertTrue(self.rom.exists())
        self.job(self.api.paste_undo("__archive__"))
        self.assertTrue((self.source / "ps2" / "FFX.iso").exists())
        self.assertFalse(self.rom.exists())

    def test_move_rejects_source_index_changed_after_preview(self):
        self.api.archive_delete_owned([self.rid])
        self.api.cut_selection(self.cid, [self.uid])
        preview = self.api.archive_paste("overwrite", immediate=True)["data"]
        collection = self.api.registry.get_collection(self.cid)
        index = Path(get_adapter(collection.frontend).layout(collection, "ps2").metadata_file)
        index.write_text(index.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        from tests.fixtures import wait_idle
        started = self.api.paste_execute(preview["operationId"], {})
        wait_idle(self.api)
        job = self.api.get_job_progress(started["data"]["jobId"])["data"]
        self.assertIsNotNone(job["error"])
        self.assertTrue((self.source / "ps2" / "FFX.iso").exists())
        self.assertFalse(self.rom.exists())

    def test_related_collection_redo_restores_move(self):
        self.api.cut_selection("__archive__", [self.rid])
        preview = self.api.paste(self.cid, immediate=True)["data"]
        self.job(self.api.paste_execute(preview["operationId"], {row["key"]:"overwrite" for row in preview["collisions"]}))
        self.job(self.api.paste_undo(self.cid))
        self.assertTrue(self.api.operation_state(self.cid)["data"]["redoOperationId"])
        self.job(self.api.paste_redo(self.cid))
        self.assertFalse(self.rom.exists())
        self.assertIsNone(self.api.archive.get_identity(self.rid))
