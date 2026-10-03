from types import SimpleNamespace
from unittest.mock import patch
import pytest

from app.plan.paste_journal import PasteJournal, _state
from app.archive.undo import ArchiveUndo
from app.archive.undo import ArchiveTransaction
from app.plan.backup_retention import policy, prune


@pytest.fixture
def context(tmp_path):
    journal = PasteJournal(tmp_path / "collection")
    archive = ArchiveUndo(tmp_path / "archive")
    return SimpleNamespace(_paste_journal=journal, _archive_journal=archive, _archive_config=lambda: {})


def record(api, key, created, status="committed", **extra):
    directory = api._paste_journal.root / key
    directory.mkdir()
    (directory / "index.bak").write_bytes(b"backup")
    api._paste_journal._save(directory, {"id": key, "collectionId": "collection", "createdAt": created,
        "status": status, "files": {}, **extra})
    return directory


def test_default_retention_preserves_small_history(context):
    original = record(context, "old", 1)
    assert prune(context, "collection", None)["discarded"] == 0
    assert original.exists()


def test_oldest_records_removed_and_latest_undo_preserved(context):
    old = record(context, "old", 1)
    middle = record(context, "middle", 2)
    latest = record(context, "latest", 3)
    result = prune(context, "collection", {"enabled": True, "maxCount": 1, "maxSizeGB": 0})
    assert result["discarded"] == 2
    assert not old.exists() and not middle.exists()
    assert latest.exists()


@pytest.mark.parametrize("status", ["running", "restoring", "redoing", "recovery_failed"])
def test_pending_recovery_prevents_cleanup(context, status):
    old = record(context, "old", 1)
    pending = record(context, "pending", 2, status)
    result = prune(context, "collection", {"enabled":True, "maxCount":1, "maxSizeGB":0})
    assert result["blocked"]
    assert old.exists() and pending.exists()


def test_redo_closed_and_related_records_remain_even_above_limit(context):
    redo = record(context, "redo", 1, "undone", redoReady=True)
    closed = record(context, "closed", 2, "closed")
    related = record(context, "related", 3, relatedCollections={"other":["ps2"]})
    latest = record(context, "latest", 4)
    result = prune(context, "collection", {"enabled":True, "maxCount":1, "maxSizeGB":0})
    assert result["discarded"] == 0 and result["limitExceeded"]
    assert all(path.exists() for path in (redo, closed, related, latest))


def test_modified_external_sidecar_is_not_deleted(context, tmp_path):
    sidecar = tmp_path / "game.rom.old.rms-backup"
    sidecar.write_bytes(b"original ROM")
    before = _state(sidecar)
    old = record(context, "old", 1, files={str(tmp_path / "game.rom"): {"backup":str(sidecar)}},
        preFiles={str(tmp_path / "game.rom"):before})
    record(context, "latest", 2)
    sidecar.write_bytes(b"externally changed ROM")
    result = prune(context, "collection", {"enabled":True, "maxCount":1, "maxSizeGB":0})
    assert result["discarded"] == 0 and result["limitExceeded"]
    assert old.exists() and sidecar.read_bytes() == b"externally changed ROM"


def test_size_limit_uses_oldest_first_and_retains_large_latest(context):
    with patch("app.plan.history._backup_bytes", return_value=2 * 1024 ** 3):
        old = record(context, "old", 1)
        latest = record(context, "latest", 2)
        result = prune(context, "collection", {"enabled":True, "maxCount":0, "maxSizeGB":1})
    assert result["discarded"] == 1 and result["limitExceeded"]
    assert not old.exists() and latest.exists()


def test_permission_failure_is_reported_without_failing_cleanup(context):
    old = record(context, "old", 1)
    record(context, "latest", 2)
    with patch("app.plan.history.discard", side_effect=PermissionError("file locked")):
        result = prune(context, "collection", {"enabled":True, "maxCount":1, "maxSizeGB":0})
    assert result["errors"] and result["limitExceeded"] and old.exists()


def test_archive_retention_keeps_latest_undo(context, tmp_path):
    config = {"frontend":"es-de", "archiveDir":str(tmp_path / "frontend"), "romDir":"", "mediaInternal":True}
    context._archive_config = lambda: config
    for number in (1, 2):
        directory = context._archive_journal.root / f"archive-{number}"
        directory.mkdir()
        (directory / "before.db").write_bytes(b"backup remains owned")
        ArchiveTransaction(directory, {"id":f"archive-{number}", "createdAt":number,
            "config":config, "status":"committed", "files":{}}).save()
    result = prune(context, "__archive__", {"enabled":True, "maxCount":1, "maxSizeGB":0})
    assert result["discarded"] == 1
    assert not (context._archive_journal.root / "archive-1").exists()
    assert (context._archive_journal.root / "archive-2" / "before.db").exists()


@pytest.mark.parametrize("value", [-1, 1.5, "20", True])
def test_invalid_limits_rejected(value):
    with pytest.raises(ValueError):
        policy({"enabled":True, "maxCount":value})


def test_both_unlimited_rejected_when_enabled():
    with pytest.raises(ValueError):
        policy({"enabled":True, "maxCount":0, "maxSizeGB":0})


def test_disabled_cleanup_warns_above_20gb_without_deleting(context):
    original = record(context, "old", 1)
    with patch("app.plan.history._backup_bytes", return_value=21 * 1024 ** 3):
        result = prune(context, "collection", {"enabled":False})
    assert result["sizeWarning"] and result["discarded"] == 0
    assert original.exists()


def test_disabled_cleanup_is_quiet_below_20gb(context):
    record(context, "old", 1)
    assert not prune(context, "collection", {"enabled":False})["sizeWarning"]


def test_capacity_warning_counts_other_collections(context):
    directory = record(context, "other", 1)
    data = context._paste_journal.details("other")
    data["collectionId"] = "another-collection"
    context._paste_journal._save(directory, data)
    with patch("app.plan.history._backup_bytes", return_value=21 * 1024 ** 3):
        assert prune(context, "collection", {"enabled":False})["sizeWarning"]


def test_exit_cleanup_removes_latest_undo_and_redo(context):
    from app.plan.backup_retention import clear_on_exit
    first = record(context, 'committed', 1)
    second = record(context, 'redo', 2, status='undone', redoReady=True)
    result = clear_on_exit(context, None)
    assert result['discarded'] == 2
    assert not first.exists() and not second.exists()


def test_exit_cleanup_can_be_disabled(context):
    from app.plan.backup_retention import clear_on_exit
    first = record(context, 'committed', 1)
    assert clear_on_exit(context, {'clearOnExit':False})['discarded'] == 0
    assert first.exists()


def test_exit_cleanup_protects_pending_scope_and_closed_backups(context):
    from app.plan.backup_retention import clear_on_exit
    first = record(context, 'committed', 1)
    pending = record(context, 'failed', 2, status='recovery_failed')
    closed = record(context, 'closed', 3, status='closed')
    assert clear_on_exit(context, None)['discarded'] == 0
    assert first.exists() and pending.exists() and closed.exists()


def test_exit_cleanup_handles_archive_and_protects_its_failures(context):
    from app.plan.backup_retention import clear_on_exit
    root = context._archive_journal.root
    directory = root / 'arc'; directory.mkdir()
    ArchiveTransaction(directory, {'id':'arc','status':'committed','createdAt':1,'config':{},'files':{}}).save()
    assert clear_on_exit(context, None)['discarded'] == 1
    assert not directory.exists()


def test_exit_cleanup_keeps_archive_when_recovery_failed(context):
    from app.plan.backup_retention import clear_on_exit
    for key, status in [('done','committed'),('failed','recovery_failed')]:
        directory = context._archive_journal.root / key; directory.mkdir()
        ArchiveTransaction(directory, {'id':key,'status':status,'createdAt':1,'config':{},'files':{}}).save()
    assert clear_on_exit(context, None)['discarded'] == 0
    assert (context._archive_journal.root / 'done').exists()
    assert (context._archive_journal.root / 'failed').exists()


def test_live_file_operation_does_not_show_interruption_prompt(monkeypatch):
    from app.plan import history
    monkeypatch.setattr(history.process_owner, 'status', lambda row:'alive')
    assert not history.requires_recovery([{'status':'running'}])
    assert history.requires_recovery([{'status':'recovery_failed'}])
    monkeypatch.setattr(history.process_owner, 'status', lambda row:'dead')
    assert history.requires_recovery([{'status':'running'}])
