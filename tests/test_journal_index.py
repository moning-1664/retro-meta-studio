import json
from pathlib import Path
from unittest.mock import patch

from app.plan import journal_index
from app.plan.paste_journal import PasteJournal


def test_status_queries_do_not_read_large_unchanged_records(tmp_path):
    journal = PasteJournal(tmp_path)
    directory = tmp_path / "operation"
    directory.mkdir()
    journal._save(directory, {"id": "operation", "collectionId": "collection", "createdAt": 1,
        "status": "committed", "files": {str(n): {"backup": "x"} for n in range(10000)}})
    with patch.object(Path, "read_text", side_effect=AssertionError("full record read")):
        assert journal.latest_committed("collection") == "operation"
        assert journal.pending("collection") == []


def test_legacy_record_is_indexed_and_external_change_detected(tmp_path):
    journal = PasteJournal(tmp_path)
    directory = tmp_path / "operation"
    directory.mkdir()
    path = directory / "operation.json"
    data = {"id": "operation", "collectionId": "collection", "createdAt": 1, "status": "running"}
    path.write_text(json.dumps(data), encoding="utf-8")
    assert journal.pending("collection")[0]["id"] == "operation"
    data["status"] = "recovery_failed"
    data["recoveryError"] = "external change"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert journal.pending("collection")[0]["recoveryError"] == "external change"
    path.unlink()
    assert journal.pending("collection") == []


def test_index_deletion_rebuilds_from_authoritative_records(tmp_path):
    journal = PasteJournal(tmp_path)
    directory = tmp_path / "operation"
    directory.mkdir()
    journal._save(directory, {"id": "operation", "status": "recovery_failed", "collectionId": "collection"})
    (tmp_path / "status-index.sqlite").unlink()
    assert journal.pending("collection")[0]["status"] == "recovery_failed"


def test_backup_size_cache_is_invalidated_on_record_change(tmp_path):
    journal = PasteJournal(tmp_path)
    directory = tmp_path / "operation"
    directory.mkdir()
    data = {"id": "operation", "status": "undone"}
    journal._save(directory, data)
    assert journal_index.backup_bytes(tmp_path, "operation", lambda: 10) == 10
    assert journal_index.backup_bytes(tmp_path, "operation", lambda: 999) == 10
    data["status"] = "closed"
    journal._save(directory, data)
    assert journal_index.backup_bytes(tmp_path, "operation", lambda: 20) == 20


def test_history_reuses_cached_size_without_walking_backup_files(tmp_path):
    from types import SimpleNamespace
    from app.plan.history import listing
    journal = PasteJournal(tmp_path / "collection")
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    directory = journal.root / "operation"
    directory.mkdir()
    journal._save(directory, {"id": "operation", "status": "committed", "collectionId": "collection", "createdAt": 1, "files": {}})
    api = SimpleNamespace(_paste_journal=journal, _archive_journal=SimpleNamespace(root=archive_root), _archive_config=lambda: {})
    first = listing(api, "collection")
    with patch.object(Path, "rglob", side_effect=AssertionError("backup walk")), patch.object(Path, "read_text", side_effect=AssertionError("record read")):
        assert listing(api, "collection") == first


def test_unavailable_index_does_not_hide_pending_recovery(tmp_path):
    journal = PasteJournal(tmp_path)
    directory = tmp_path / "operation"
    directory.mkdir()
    journal._save(directory, {"id": "operation", "status": "recovery_failed", "collectionId": "collection"})
    with patch("app.plan.journal_index.connect", side_effect=OSError("index unavailable")):
        assert journal.pending("collection")[0]["status"] == "recovery_failed"


def test_corrupt_index_falls_back_to_original_record(tmp_path):
    journal = PasteJournal(tmp_path)
    directory = tmp_path / "operation"
    directory.mkdir()
    journal._save(directory, {"id": "operation", "status": "running", "collectionId": "collection"})
    (tmp_path / "status-index.sqlite").write_bytes(b"broken index")
    assert journal.pending("collection")[0]["status"] == "running"
