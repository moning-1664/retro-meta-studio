from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.plan.paste_journal import PasteJournal, _state
from app.plan import process_owner, history


def record(journal, tmp_path, owner=None):
    directory = journal.root / "interrupted"
    directory.mkdir()
    source, destination = tmp_path / "old.rom", tmp_path / "new.rom"
    source.write_bytes(b"external original")
    destination.write_bytes(b"renamed ROM")
    data = {"id": "interrupted", "collectionId": "collection", "createdAt": 1,
            "status": "running", "files": {}, "indexes": {},
            "renames": [{"source": str(source), "destination": str(destination), "before": _state(destination)}]}
    if owner:
        data["owner"] = owner
    journal._save(directory, data)
    return source, destination


def test_second_instance_does_not_restore_live_operation(tmp_path):
    journal = PasteJournal(tmp_path / "journal")
    source, destination = record(journal, tmp_path, process_owner.owner())
    assert journal.recover_interrupted() == []
    assert journal.details("interrupted")["status"] == "running"
    assert source.exists() and destination.exists()


def test_failed_recovery_can_close_without_deleting_backups(tmp_path):
    journal = PasteJournal(tmp_path / "journal")
    source, destination = record(journal, tmp_path)
    assert journal.recover_interrupted() == []
    assert journal.details("interrupted")["status"] == "recovery_failed"
    archive_journal = SimpleNamespace(root=tmp_path / "archive-journal")
    archive_journal.root.mkdir()
    api = SimpleNamespace(_paste_journal=journal, _archive_journal=archive_journal, _archive_config=lambda: {})
    history.recovery_action(api, "collection", "interrupted", "close")
    assert journal.details("interrupted")["status"] == "closed"
    assert not journal.pending("collection")
    assert source.read_bytes() == b"external original"
    assert destination.read_bytes() == b"renamed ROM"
    assert (journal.root / "interrupted" / "operation.json").is_file()


def test_retry_after_resolving_external_collision(tmp_path):
    journal = PasteJournal(tmp_path / "journal")
    source, destination = record(journal, tmp_path)
    journal.recover_interrupted()
    source.unlink()
    journal.retry_recovery("interrupted")
    assert source.read_bytes() == b"renamed ROM"
    assert not destination.exists()
    assert journal.details("interrupted")["status"] == "recovered"


def test_collection_journal_fsyncs_before_replacing(tmp_path):
    journal = PasteJournal(tmp_path / "journal")
    directory = journal.root / "record"
    directory.mkdir()
    with patch("app.plan.paste_journal.os.fsync") as sync:
        journal._save(directory, {"id": "record"})
    sync.assert_called_once()


def test_archive_import_builds_target_index_once_and_never_guesses_language():
    from app.archive.service import to_collection
    archive, cache, provider = Mock(), Mock(), Mock()
    collection = SimpleNamespace(id="collection", frontend="es-de", systems=[SimpleNamespace(system="snes")])
    rows = [{"system": "snes", "filename": f"Game{number}.zip", "rom_uid": number, "present": True}
            for number in range(2000)]
    cache.query_rows.return_value = rows
    cache.get_row.side_effect = lambda uid: rows[uid]
    archive.get_identity.side_effect = lambda uid: {"system": "snes", "filename": f"Game{uid}.zip"}
    archive.match_links_of.return_value = {}
    archive.resolve_fields.return_value = ({"name": "Game"}, {})
    progress = Mock()
    with patch("app.archive.projection.effective_media", return_value={}):
        result = to_collection(archive, collection, cache, provider, range(2000), progress=progress)
    assert len(result["items"]) == 2000
    cache.query_rows.assert_called_once()
    assert progress.call_count == 2000


def test_archive_import_cancels_before_resolving_more_items():
    import pytest
    from bridge.jobs import JobCancelled
    from app.archive.service import to_collection
    archive, cache = Mock(), Mock()
    cache.query_rows.return_value = []
    archive.match_links_of.return_value = {}
    progress = Mock(side_effect=JobCancelled())
    with pytest.raises(JobCancelled):
        to_collection(archive, SimpleNamespace(id="collection", frontend="es-de"), cache, Mock(), [1, 2], progress=progress)
    archive.get_identity.assert_not_called()


def test_archive_import_casefold_preserves_actual_target_filename():
    from app.archive.service import to_collection
    archive, cache, provider = Mock(), Mock(), Mock()
    collection = SimpleNamespace(id="collection", frontend="es-de", systems=[SimpleNamespace(system="snes")])
    row = {"system":"snes", "filename":"Game.ZIP", "rom_uid":1, "present":False}
    cache.query_rows.return_value = [row]
    cache.get_row.return_value = row
    archive.get_identity.return_value = {"system":"snes", "filename":"game.zip"}
    archive.match_links_of.return_value = {}
    archive.resolve_fields.return_value = ({"name":"Game"}, {})
    archive.rom_sources.return_value = [{"abs_path":"source.zip", "size":3}]
    with patch("app.archive.projection.effective_media", return_value={}):
        result = to_collection(archive, collection, cache, provider, [1])
    assert result["items"][0]["filename"] == "Game.ZIP"
    assert result["items"][0]["rom"]["path"] == "source.zip"


def test_archive_import_language_variant_is_not_automatic_target():
    from app.archive.service import to_collection
    archive, cache, provider = Mock(), Mock(), Mock()
    collection = SimpleNamespace(id="collection", frontend="es-de", systems=[SimpleNamespace(system="snes")])
    cache.query_rows.return_value = [{"system":"snes", "filename":"FF3(KR).zip", "rom_uid":1, "present":True}]
    archive.get_identity.return_value = {"system":"snes", "filename":"FF3.zip"}
    archive.match_links_of.return_value = {}
    archive.resolve_fields.return_value = ({"name":"FF3"}, {})
    archive.rom_sources.return_value = [{"abs_path":"source.zip", "size":3}]
    with patch("app.archive.projection.effective_media", return_value={}):
        result = to_collection(archive, collection, cache, provider, [1])
    assert result["items"][0]["filename"] == "FF3.zip"
    cache.get_row.assert_not_called()


def test_closed_record_is_manually_discardable(tmp_path):
    journal = PasteJournal(tmp_path / "journal")
    source, destination = record(journal, tmp_path)
    journal.recover_interrupted()
    root = tmp_path / "archive"
    root.mkdir()
    api = SimpleNamespace(_paste_journal=journal, _archive_journal=SimpleNamespace(root=root), _archive_config=lambda:{})
    history.recovery_action(api, "collection", "interrupted", "close")
    assert history.listing(api, "collection")[0]["canDiscard"]
    assert history.discard(api, "collection", ["interrupted"])["discarded"] == 1
    assert source.exists() and destination.exists()


def test_force_recovery_rejects_known_live_owner(tmp_path):
    import pytest
    journal = PasteJournal(tmp_path / "journal")
    record(journal, tmp_path, process_owner.owner())
    with pytest.raises(ValueError):
        journal.retry_recovery("interrupted", force_unknown_owner=True)


def test_unknown_owner_can_recover_after_confirming_no_active_app(tmp_path):
    journal = PasteJournal(tmp_path / "journal")
    source, destination = record(journal, tmp_path, {"pid":123, "processStamp":"old"})
    source.unlink()
    with patch("app.plan.process_owner.process_stamp", return_value="unknown"):
        journal.retry_recovery("interrupted", force_unknown_owner=True)
    assert source.exists() and not destination.exists()
    assert journal.details("interrupted")["status"] == "recovered"


def test_force_recovery_preserves_unverifiable_new_file(tmp_path):
    import pytest
    journal = PasteJournal(tmp_path / "journal")
    directory = journal.root / "interrupted"
    directory.mkdir()
    destination = tmp_path / "game.zip"
    destination.write_bytes(b"external data")
    journal._save(directory, {"id":"interrupted", "status":"running", "collectionId":"collection",
        "createdAt":1, "owner":{"pid":123, "processStamp":"old"}, "indexes":{},
        "files":{str(destination):{"backup":str(destination)+".interrupted.rms-backup", "existed":False}},
        "preFiles":{str(destination):None}})
    with patch("app.plan.process_owner.process_stamp", return_value="unknown"), pytest.raises(ValueError):
        journal.retry_recovery("interrupted", force_unknown_owner=True)
    assert destination.read_bytes() == b"external data"
    assert journal.details("interrupted")["status"] == "recovery_failed"


def test_failed_manual_recovery_does_not_bypass_checks_on_retry(tmp_path):
    import pytest
    journal = PasteJournal(tmp_path / "journal")
    directory = journal.root / "op"
    directory.mkdir()
    path = tmp_path / "game.zip"
    path.write_bytes(b"external data")
    journal._save(directory, {"id":"op", "status":"recovery_failed", "recoveryStatus":"running",
        "manualOwnerRecovery":True, "indexes":{}, "files":{str(path):{"backup":str(path)+".op.rms-backup", "existed":False}},
        "preFiles":{str(path):None}})
    with pytest.raises(ValueError):
        journal.retry_recovery("op")
    assert path.read_bytes() == b"external data"


def test_archive_unknown_owner_manual_recovery_still_checks_database(tmp_path):
    import pytest
    import adapters.es_de
    from app.archive.undo import ArchiveUndo
    from app.store.archive import ArchiveStore
    root = tmp_path / "archive"
    root.mkdir()
    archive_journal = ArchiveUndo(tmp_path / "archive-journal")
    collection_journal = PasteJournal(tmp_path / "collection-journal")
    config = {"frontend":"es-de", "archiveDir":str(root), "romDir":"", "mediaInternal":True}
    store = ArchiveStore(tmp_path / "live.db")
    try:
        tx = archive_journal.begin("unknown", store, config, [])
        tx.data["owner"] = {"pid":123,"processStamp":"old"}
        tx.save()
        store.ensure_game("external change", "externalchange")
        api = SimpleNamespace(_archive_journal=archive_journal, _paste_journal=collection_journal,
            _archive_config=lambda:config, archive=store)
        with patch("app.plan.process_owner.process_stamp",return_value="unknown"), pytest.raises(ValueError):
            history.recovery_action(api, "__archive__", "unknown", "force")
        assert store._conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
        assert archive_journal.load("unknown").data["status"] == "recovery_failed"
    finally:
        store.close()
