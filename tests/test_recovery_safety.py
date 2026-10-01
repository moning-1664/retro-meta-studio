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
