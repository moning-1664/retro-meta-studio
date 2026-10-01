"""탐색기식 붙여넣기: 미리보기, 건별 결정, 독립 실행."""

import unittest
import os
from pathlib import Path

from bridge.api import Api
from app.plan.paste_journal import PasteJournal
from unittest import mock
from adapters import get_adapter
from tests.fixtures import build_custom_esde_tree, scan, temp_root, wait_idle, write_file


class ImmediatePasteTests(unittest.TestCase):
    def setUp(self):
        self.root = temp_root("rms_paste_immediate_")
        self.source = build_custom_esde_tree(self.root / "source", "ps2", [
            {"filename": "Same.iso", "title": "새 제목"},
            {"filename": "Other.iso", "title": "추가 게임"},
        ])
        self.target = build_custom_esde_tree(self.root / "target", "ps2", [
            {"filename": "Same.iso", "title": "기존 제목"},
            {"filename": "Other.zip", "title": "비슷한 게임"},
        ])
        self.api = Api(registry_path=self.root / "registry.db", cache_dir=self.root / "cache")
        self.addCleanup(self.api.close)
        self.src_id = self.api.create_collection("source", "es-de", str(self.source))["data"]["id"]
        self.dst_id = self.api.create_collection("target", "es-de", str(self.target))["data"]["id"]
        scan(self.api, self.src_id)
        scan(self.api, self.dst_id)
        ids = [row["romUid"] for row in self.api.list_rows(self.src_id)["data"]["rows"]]
        self.assertTrue(self.api.copy_selection(self.src_id, ids)["ok"])

    def test_local_rename_and_undo_preserve_rom_bytes(self):
        from tests.fixtures import wait_job
        cache = self.api.workspace.open(self.dst_id)
        row = cache.get_row_by_filename("ps2", "Same.iso")
        collection = self.api.registry.get_collection(self.dst_id)
        layout = get_adapter(collection.frontend).layout(collection, "ps2")
        original = Path(layout.rom_dir) / "Same.iso"
        renamed = original.with_name("Renamed.iso")
        before = original.read_bytes()
        started = self.api.rename_game(self.dst_id, row["rom_uid"], "Renamed.iso")
        self.assertTrue(started["ok"], started.get("error"))
        result = wait_job(self.api, started["data"]["jobId"])
        self.assertFalse(result.get("error"), result)
        self.assertFalse(original.exists())
        self.assertEqual(renamed.read_bytes(), before)
        self.assertIsNotNone(cache.get_row_by_filename("ps2", "Renamed.iso"))
        undo = self.api.paste_undo(self.dst_id)
        self.assertTrue(undo["ok"], undo.get("error"))
        result = wait_job(self.api, undo["data"]["jobId"])
        self.assertFalse(result.get("error"), result)
        self.assertEqual(original.read_bytes(), before)
        self.assertFalse(renamed.exists())

    def test_rename_failure_restores_rom_and_original_index(self):
        from tests.fixtures import wait_job
        cache = self.api.workspace.open(self.dst_id)
        row = cache.get_row_by_filename("ps2", "Same.iso")
        adapter = get_adapter("es-de")
        layout = adapter.layout(self.api.registry.get_collection(self.dst_id), "ps2")
        original = Path(layout.rom_dir) / "Same.iso"
        before_index = Path(layout.metadata_file).read_bytes()
        with mock.patch.object(adapter, "write_index", side_effect=OSError("injected rename failure")):
            started = self.api.rename_game(self.dst_id, row["rom_uid"], "Renamed.iso")
            self.assertTrue(started["ok"], started.get("error"))
            result = wait_job(self.api, started["data"]["jobId"])
        self.assertTrue(result.get("error"), result)
        self.assertTrue(original.exists())
        self.assertFalse(original.with_name("Renamed.iso").exists())
        self.assertEqual(Path(layout.metadata_file).read_bytes(), before_index)

    def test_cut_moves_only_after_copy_and_undo_restores_both_collections(self):
        from tests.fixtures import wait_job
        source_cache = self.api.workspace.open(self.src_id)
        row = source_cache.get_row_by_filename("ps2", "Other.iso")
        self.assertTrue(self.api.cut_selection(self.src_id, [row["rom_uid"]])["ok"])
        preview = self.api.paste(self.dst_id, "overwrite", immediate=True)
        self.assertTrue(preview["ok"], preview.get("error"))
        started = self.api.paste_execute(preview["data"]["operationId"], {})
        self.assertTrue(started["ok"], started.get("error"))
        result = wait_job(self.api, started["data"]["jobId"])
        self.assertFalse(result.get("error"), result)
        self.assertFalse((self.source / "ps2" / "Other.iso").exists())
        self.assertTrue((self.target / "ps2" / "Other.iso").exists())
        undo = self.api.paste_undo(self.dst_id)
        self.assertTrue(undo["ok"], undo.get("error"))
        result = wait_job(self.api, undo["data"]["jobId"])
        self.assertFalse(result.get("error"), result)
        self.assertTrue((self.source / "ps2" / "Other.iso").exists())
        self.assertFalse((self.target / "ps2" / "Other.iso").exists())
        self.assertIsNotNone(source_cache.get_row_by_filename("ps2", "Other.iso"))

    def test_cut_copy_failure_keeps_source_rom(self):
        from tests.fixtures import wait_job
        row = self.api.workspace.open(self.src_id).get_row_by_filename("ps2", "Other.iso")
        self.api.cut_selection(self.src_id, [row["rom_uid"]])
        preview = self.api.paste(self.dst_id, "overwrite", immediate=True)
        self.assertTrue(preview["ok"], preview.get("error"))
        with mock.patch("file_ops.copy_files", return_value={}):
            started = self.api.paste_execute(preview["data"]["operationId"], {})
            self.assertTrue(started["ok"], started.get("error"))
            result = wait_job(self.api, started["data"]["jobId"])
        self.assertTrue((self.source / "ps2" / "Other.iso").exists())
        self.assertFalse((self.target / "ps2" / "Other.iso").exists())

    def test_cut_rejects_collections_sharing_the_same_rom_files(self):
        self.api.registry.upsert_system(self.dst_id, "ps2", "internal",
            rom_path=str(self.source / "ps2"))
        scan(self.api, self.dst_id)
        row = self.api.workspace.open(self.src_id).get_row_by_filename("ps2", "Other.iso")
        self.api.cut_selection(self.src_id, [row["rom_uid"]])
        preview = self.api.paste(self.dst_id, "overwrite", immediate=True)
        self.assertTrue(preview["ok"], preview.get("error"))
        data = preview["data"]
        decisions = {c["key"]: "overwrite" for c in data["collisions"]}
        result = self.api.paste_execute(data["operationId"], decisions)
        self.assertFalse(result["ok"], result)
        self.assertIn("같은 파일", result["error"])
        self.assertTrue((self.source / "ps2" / "Other.iso").exists())

    def test_only_the_exact_name_collides_and_plan_stays_separate(self):
        preview = self.api.paste(self.dst_id, "overwrite", immediate=True)
        self.assertTrue(preview["ok"], preview.get("error"))
        data = preview["data"]
        self.assertEqual({c["filename"] for c in data["collisions"]}, {"Same.iso"})
        self.assertEqual(self.api.plan_state(self.dst_id)["data"]["total"], 0)

        started = self.api.paste_execute(data["operationId"], {"ps2|Same.iso": "skip"})
        self.assertTrue(started["ok"], started.get("error"))
        wait_idle(self.api)
        rows = {row["file"]: row for row in self.api.list_rows(self.dst_id)["data"]["rows"]}
        self.assertIn("Other.iso", rows)
        self.assertIn("Other.zip", rows)
        self.assertEqual(rows["Same.iso"]["title"], "기존 제목")

    def test_unresolved_collision_cannot_execute(self):
        preview = self.api.paste(self.dst_id, "overwrite", immediate=True)["data"]
        result = self.api.paste_execute(preview["operationId"], {})
        self.assertFalse(result["ok"])

    def test_successful_paste_runs_opt_in_backup_retention(self):
        saved = self.api.save_app_settings({"backupRetention": {"enabled":True, "maxCount":1, "maxSizeGB":0}})
        self.assertTrue(saved["ok"], saved)
        directory = self.api._paste_journal.root / "old-completed"
        directory.mkdir()
        self.api._paste_journal._save(directory, {"id":"old-completed", "collectionId":self.dst_id,
            "createdAt":1, "status":"committed", "files":{}})
        preview = self.api.paste(self.dst_id, "overwrite", immediate=True)["data"]
        started = self.api.paste_execute(preview["operationId"], {c["key"]:"overwrite" for c in preview["collisions"]})
        self.assertTrue(started["ok"], started)
        wait_idle(self.api)
        self.assertFalse(directory.exists())
        state = self.api.operation_state(self.dst_id)["data"]
        self.assertEqual(state["retention"]["discarded"], 1)
        self.assertTrue(state["undoOperationId"])

    def test_single_explicit_row_wins_over_same_named_game(self):
        rows = self.api.list_rows(self.src_id)["data"]["rows"]
        source_id = next(row["romUid"] for row in rows if row["file"] == "Same.iso")
        self.api.copy_selection(self.src_id, [source_id])
        preview = self.api.paste(self.dst_id, "overwrite",
                                 fallback_target="ps2|Other.zip", immediate=True)
        self.assertTrue(preview["ok"], preview.get("error"))
        self.assertEqual([c["filename"] for c in preview["data"]["collisions"]], ["Other.zip"])
        started = self.api.paste_execute(preview["data"]["operationId"],
                                         {"ps2|Other.zip": "overwrite"})
        self.assertTrue(started["ok"], started.get("error"))
        wait_idle(self.api)
        rows = {row["file"]: row for row in self.api.list_rows(self.dst_id)["data"]["rows"]}
        self.assertEqual(rows["Other.zip"]["title"], "새 제목")
        self.assertEqual(rows["Same.iso"]["title"], "기존 제목")

    def test_rom_replacement_is_undoable_without_a_second_rom_copy(self):
        source_rom = self.source / "ps2" / "Same.iso"
        target_rom = self.target / "ps2" / "Same.iso"
        target_rom.write_bytes(b"ORIGINAL-ROM")
        scan(self.api, self.dst_id)
        source_id = next(row["romUid"] for row in self.api.list_rows(self.src_id)["data"]["rows"]
                         if row["file"] == "Same.iso")
        self.api.copy_selection(self.src_id, [source_id])
        preview = self.api.paste(self.dst_id, "overwrite", immediate=True)["data"]
        self.assertTrue(preview["undoable"])
        started = self.api.paste_execute(preview["operationId"], {"ps2|Same.iso": "overwrite"})
        self.assertTrue(started["ok"], started.get("error"))
        wait_idle(self.api)
        job = self.api.get_job_progress(started["data"]["jobId"])["data"]
        self.assertIsNone(job["error"], job)
        self.assertEqual(target_rom.read_bytes(), source_rom.read_bytes())
        self.assertEqual(job["result"]["undoOperationId"], preview["operationId"])

        undone = self.api.paste_undo(self.dst_id)
        self.assertTrue(undone["ok"], undone.get("error"))
        wait_idle(self.api)
        self.assertEqual(target_rom.read_bytes(), b"ORIGINAL-ROM")

    def test_interrupted_replace_restores_the_original_rom_and_index(self):
        source_id = next(row["romUid"] for row in self.api.list_rows(self.src_id)["data"]["rows"]
                         if row["file"] == "Same.iso")
        self.api.copy_selection(self.src_id, [source_id])
        preview = self.api.paste(self.dst_id, "overwrite", immediate=True)["data"]
        operation_id = preview["operationId"]
        plan = self.api._paste_ops[operation_id]["plan"]
        for entry in plan.entries:
            if entry.conflicts:
                from app.plan import builder
                from app.model.plan import RESOLVE_OVERWRITE
                collection, _cache, provider = self.api._plan_context(self.dst_id)
                builder.resolve_conflict(plan, collection, provider, entry.key, RESOLVE_OVERWRITE)
        collection, _, _ = self.api._plan_context(self.dst_id)
        journal = PasteJournal(self.root / "recovery")
        suffix = journal.begin(operation_id, self.dst_id, collection, plan)
        target_rom = self.target / "ps2" / "Same.iso"
        before = target_rom.read_bytes()
        index = self.target / "gamelists" / "ps2" / "gamelist.xml"
        before_index = index.read_bytes()
        os.replace(target_rom, str(target_rom) + suffix)
        target_rom.write_bytes(b"INCOMPLETE")
        index.write_bytes(b"BROKEN")
        with mock.patch("app.plan.process_owner.alive", return_value=False):
            self.assertEqual(journal.recover_interrupted(), [operation_id])
        self.assertEqual(target_rom.read_bytes(), before)
        self.assertEqual(index.read_bytes(), before_index)

    def test_explicit_replace_can_change_media_of_the_same_size(self):
        source_cover = write_file(self.source / "downloaded_media" / "ps2" / "covers"
                                  / "Same.png", b"AAAA")
        target_cover = write_file(self.target / "downloaded_media" / "ps2" / "covers"
                                  / "Same.png", b"BBBB")
        scan(self.api, self.src_id)
        scan(self.api, self.dst_id)
        source_id = next(row["romUid"] for row in self.api.list_rows(self.src_id)["data"]["rows"]
                         if row["file"] == "Same.iso")
        self.api.copy_selection(self.src_id, [source_id])
        preview = self.api.paste(self.dst_id, "replace", immediate=True)["data"]
        started = self.api.paste_execute(preview["operationId"],
                                         {"ps2|Same.iso": "overwrite"})
        self.assertTrue(started["ok"], started.get("error"))
        wait_idle(self.api)
        self.assertEqual(target_cover.read_bytes(), source_cover.read_bytes())

    def test_replacement_capacity_counts_new_bytes_while_original_is_retained(self):
        from app.plan.builder import resolve_conflict
        source_rom = self.source / "ps2" / "Same.iso"
        source_rom.write_bytes(b"N" * 4096)
        scan(self.api, self.src_id)
        uid = next(row["romUid"] for row in self.api.list_rows(self.src_id)["data"]["rows"]
                   if row["file"] == "Same.iso")
        self.api.copy_selection(self.src_id, [uid])
        preview = self.api.paste(self.dst_id, "replace", immediate=True)["data"]
        plan = self.api._paste_ops[preview["operationId"]]["plan"]
        collection, cache, provider = self.api._plan_context(self.dst_id)
        entry = plan.entries[0]
        resolve_conflict(plan, collection, provider, entry.key, "overwrite")
        self.assertGreaterEqual(sum(plan.get(entry.key).physical_delta.values()), source_rom.stat().st_size)

    def test_partial_media_link_failure_restores_replaced_media(self):
        write_file(self.source / "downloaded_media" / "ps2" / "covers" / "Same.png", b"NEW!")
        cover = write_file(self.target / "downloaded_media" / "ps2" / "covers" / "Same.png", b"OLD!")
        scan(self.api, self.src_id)
        scan(self.api, self.dst_id)
        uid = next(row["romUid"] for row in self.api.list_rows(self.src_id)["data"]["rows"]
                   if row["file"] == "Same.iso")
        self.api.copy_selection(self.src_id, [uid])
        preview = self.api.paste(self.dst_id, "replace", immediate=True)["data"]
        def fail_after_copy(adds, collection, adapter, links, errors):
            from app.model.plan import STATUS_PARTIAL
            for entry in adds:
                entry.status = STATUS_PARTIAL
                entry.error = "index write failed"
            errors.append("index write failed")

        with mock.patch("app.plan.applier._write_media_links", side_effect=fail_after_copy):
            started = self.api.paste_execute(preview["operationId"], {"ps2|Same.iso": "overwrite"})
            self.assertTrue(started["ok"], started.get("error"))
            wait_idle(self.api)
        job = self.api.get_job_progress(started["data"]["jobId"])["data"]
        self.assertTrue(job["result"]["rolledBack"], job)
        self.assertEqual(cover.read_bytes(), b"OLD!")

    def test_replacing_an_item_with_itself_does_not_move_its_media_source(self):
        cover = write_file(self.target / "downloaded_media" / "ps2" / "covers"
                           / "Same.png", b"SELF")
        scan(self.api, self.dst_id)
        uid = next(row["romUid"] for row in self.api.list_rows(self.dst_id)["data"]["rows"]
                   if row["file"] == "Same.iso")
        self.api.copy_selection(self.dst_id, [uid])
        preview = self.api.paste(self.dst_id, "replace", immediate=True)["data"]
        if preview.get("count"):
            started = self.api.paste_execute(preview["operationId"],
                                             {"ps2|Same.iso": "overwrite"})
            self.assertTrue(started["ok"], started.get("error"))
            wait_idle(self.api)
            self.assertIsNone(self.api.get_job_progress(started["data"]["jobId"])["data"]["error"])
        self.assertEqual(cover.read_bytes(), b"SELF")

    def test_undo_refuses_to_overwrite_a_later_manual_change(self):
        source_id = next(row["romUid"] for row in self.api.list_rows(self.src_id)["data"]["rows"]
                         if row["file"] == "Same.iso")
        self.api.copy_selection(self.src_id, [source_id])
        preview = self.api.paste(self.dst_id, "overwrite", immediate=True)["data"]
        started = self.api.paste_execute(preview["operationId"],
                                         {"ps2|Same.iso": "overwrite"})
        self.assertTrue(started["ok"], started.get("error"))
        wait_idle(self.api)
        target_rom = self.target / "ps2" / "Same.iso"
        target_rom.write_bytes(b"MANUAL-LATER")
        undone = self.api.paste_undo(self.dst_id)
        self.assertTrue(undone["ok"], undone.get("error"))
        wait_idle(self.api)
        job = self.api.get_job_progress(undone["data"]["jobId"])["data"]
        self.assertIn("바뀌어", job["error"])
        self.assertEqual(target_rom.read_bytes(), b"MANUAL-LATER")

    def test_local_delete_moves_assets_to_recoverable_files_and_undo_restores_index(self):
        cover = write_file(self.target / "downloaded_media" / "ps2" / "covers"
                           / "Same.png", b"COVER")
        scan(self.api, self.dst_id)
        uid = next(row["romUid"] for row in self.api.list_rows(self.dst_id)["data"]["rows"]
                   if row["file"] == "Same.iso")
        rom = self.target / "ps2" / "Same.iso"
        before = rom.read_bytes()
        started = self.api.delete_immediate(self.dst_id, [uid])
        self.assertTrue(started["ok"], started.get("error"))
        wait_idle(self.api)
        job = self.api.get_job_progress(started["data"]["jobId"])["data"]
        self.assertIsNone(job["error"], job)
        self.assertEqual(job["result"]["applied"], 1)
        self.assertFalse(rom.exists())
        self.assertFalse(cover.exists())
        self.assertNotIn("Same.iso", [row["file"] for row in self.api.list_rows(self.dst_id)["data"]["rows"]])
        undone = self.api.paste_undo(self.dst_id)
        self.assertTrue(undone["ok"], undone.get("error"))
        wait_idle(self.api)
        self.assertEqual(rom.read_bytes(), before)
        self.assertEqual(cover.read_bytes(), b"COVER")
        self.assertIn("Same.iso", [row["file"] for row in self.api.list_rows(self.dst_id)["data"]["rows"]])

    def test_two_consecutive_deletes_can_be_undone_in_reverse_order(self):
        for filename in ("Same.iso", "Other.zip"):
            rows = {row["file"]: row["romUid"] for row in self.api.list_rows(self.dst_id)["data"]["rows"]}
            started = self.api.delete_immediate(self.dst_id, [rows[filename]])
            self.assertTrue(started["ok"], started)
            wait_idle(self.api)
        for filename in ("Other.zip", "Same.iso"):
            undone = self.api.paste_undo(self.dst_id)
            self.assertTrue(undone["ok"], undone)
            wait_idle(self.api)
            job = self.api.get_job_progress(undone["data"]["jobId"])["data"]
            self.assertIsNone(job["error"], job)
            self.assertTrue((self.target / "ps2" / filename).is_file())

    def test_local_metadata_save_is_immediate_and_undoable(self):
        uid = next(row["romUid"] for row in self.api.list_rows(self.dst_id)["data"]["rows"]
                   if row["file"] == "Same.iso")
        saved = self.api.save_fields(self.dst_id, uid, {"name": "Edited", "desc": "New description"})
        self.assertTrue(saved["ok"], saved)
        self.assertTrue(saved["data"]["undoOperationId"])
        self.assertEqual(self.api.get_row(self.dst_id, uid)["data"]["fields"]["name"], "Edited")
        self.assertEqual(self.api.plan_state(self.dst_id)["data"]["total"], 0)
        undone = self.api.paste_undo(self.dst_id)
        self.assertTrue(undone["ok"], undone)
        wait_idle(self.api)
        row = next(row for row in self.api.list_rows(self.dst_id)["data"]["rows"] if row["file"] == "Same.iso")
        self.assertEqual(row["title"], "기존 제목")

    def test_local_metadata_redo_restores_edit(self):
        uid = self.api.workspace.open(self.dst_id).get_row_by_filename("ps2", "Same.iso")["rom_uid"]
        self.api.save_fields(self.dst_id, uid, {"name": "Redo title"})
        self.api.paste_undo(self.dst_id)
        wait_idle(self.api)
        redo = self.api.paste_redo(self.dst_id)
        self.assertTrue(redo["ok"], redo)
        wait_idle(self.api)
        job = self.api.get_job_progress(redo["data"]["jobId"])["data"]
        self.assertIsNone(job["error"], job)
        row = self.api.workspace.open(self.dst_id).get_row_by_filename("ps2", "Same.iso")
        self.assertEqual(row["fields"]["name"], "Redo title")

    def test_local_rename_redo_moves_rom_without_copy(self):
        uid = self.api.workspace.open(self.dst_id).get_row_by_filename("ps2", "Same.iso")["rom_uid"]
        self.api.rename_game(self.dst_id, uid, "Again.iso")
        wait_idle(self.api)
        self.api.paste_undo(self.dst_id)
        wait_idle(self.api)
        redo = self.api.paste_redo(self.dst_id)
        wait_idle(self.api)
        job = self.api.get_job_progress(redo["data"]["jobId"])["data"]
        self.assertIsNone(job["error"], job)
        self.assertTrue((self.target / "ps2" / "Again.iso").exists())
        self.assertFalse((self.target / "ps2" / "Same.iso").exists())

    def test_history_discard_requires_confirmation(self):
        uid = self.api.workspace.open(self.dst_id).get_row_by_filename("ps2", "Same.iso")["rom_uid"]
        saved = self.api.save_fields(self.dst_id, uid, {"name": "history"})
        operation_id = saved["data"]["undoOperationId"]
        history = self.api.operation_history(self.dst_id)
        self.assertTrue(history["ok"], history)
        self.assertIn(operation_id, [row["id"] for row in history["data"]["items"]])
        self.assertFalse(self.api.discard_operation_history(self.dst_id, [operation_id])["ok"])
        result = self.api.discard_operation_history(self.dst_id, [operation_id], True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.api.operation_history(self.dst_id)["data"]["items"], [])
        self.assertEqual(self.api.workspace.open(self.dst_id).get_row_by_filename("ps2", "Same.iso")["fields"]["name"], "history")

    def test_interrupted_redo_blocks_new_writes_and_backup_discard(self):
        uid = self.api.workspace.open(self.dst_id).get_row_by_filename("ps2", "Same.iso")["rom_uid"]
        saved = self.api.save_fields(self.dst_id, uid, {"name":"first"})
        operation_id = saved["data"]["undoOperationId"]
        directory = self.api._paste_journal.root / operation_id
        data = self.api._paste_journal.details(operation_id)
        data["status"] = "redoing"
        self.api._paste_journal._save(directory, data)
        rejected = self.api.save_fields(self.dst_id, uid, {"name":"second"})
        self.assertFalse(rejected["ok"], rejected)
        self.assertEqual(self.api.workspace.open(self.dst_id).get_row_by_filename("ps2", "Same.iso")["fields"]["name"], "first")
        self.assertTrue(self.api.operation_state(self.dst_id)["data"]["recoveryError"])
        self.assertFalse(self.api.discard_operation_history(self.dst_id, [operation_id], True)["ok"])

    def test_delete_index_failure_restores_rom(self):
        uid = next(row["romUid"] for row in self.api.list_rows(self.dst_id)["data"]["rows"]
                   if row["file"] == "Same.iso")
        rom = self.target / "ps2" / "Same.iso"
        before = rom.read_bytes()
        with mock.patch.object(type(get_adapter("es-de")), "remove_entries",
                               side_effect=OSError("disk full")):
            started = self.api.delete_immediate(self.dst_id, [uid])
            self.assertTrue(started["ok"], started.get("error"))
            wait_idle(self.api)
        job = self.api.get_job_progress(started["data"]["jobId"])["data"]
        self.assertTrue(job["result"]["rolledBack"])
        self.assertEqual(rom.read_bytes(), before)

    def test_delete_redo_removes_restored_rom(self):
        uid = self.api.workspace.open(self.dst_id).get_row_by_filename("ps2", "Same.iso")["rom_uid"]
        self.api.delete_immediate(self.dst_id, [uid])
        wait_idle(self.api)
        self.api.paste_undo(self.dst_id)
        wait_idle(self.api)
        self.assertTrue((self.target / "ps2" / "Same.iso").exists())
        redo = self.api.paste_redo(self.dst_id)
        wait_idle(self.api)
        job = self.api.get_job_progress(redo["data"]["jobId"])["data"]
        self.assertIsNone(job["error"], job)
        self.assertFalse((self.target / "ps2" / "Same.iso").exists())
        files = [row["file"] for row in self.api.list_rows(self.dst_id)["data"]["rows"]]
        self.assertFalse(any(name.endswith((".rms-backup", ".rms-redo", ".rms-part")) for name in files), files)


if __name__ == "__main__":
    unittest.main()
