import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.archive.undo import ArchiveTransaction, ArchiveUndo, track_temporary
from app.plan import journal_events, journal_index


def transaction(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    directory = tmp_path / "journal" / "op"
    directory.mkdir(parents=True)
    tx = ArchiveTransaction(directory, {"id": "op", "createdAt": 1, "status": "running",
        "config": {"archiveDir": str(root)}, "files": {}})
    tx.save()
    return tx, root


def test_capture_and_expected_state_replay_without_checkpoint(tmp_path):
    tx, root = transaction(tmp_path)
    path = root / "game.zip"
    path.write_bytes(b"original")
    checkpoint = (tx.directory / "operation.json").read_bytes()
    tx.capture(path, moved=True)
    tx.expect_file(path, [2, 3, 4])
    assert (tx.directory / "operation.json").read_bytes() == checkpoint
    loaded = ArchiveUndo(tx.directory.parent).load("op")
    assert loaded.data == tx.data


def test_events_fsync_before_mutation_and_are_small(tmp_path):
    tx, root = transaction(tmp_path)
    with patch.object(tx, "save", side_effect=AssertionError("full checkpoint per file")):
        for number in range(100):
            tx.capture(root / f"{number}.zip")
    lines = (tx.directory / "events.jsonl").read_bytes().splitlines()
    assert len(lines) == 100
    assert max(map(len, lines)) < 1500
    assert len(journal_events.load(tx.directory)["files"]) == 100


def test_torn_final_append_is_ignored(tmp_path):
    tx, root = transaction(tmp_path)
    tx.capture(root / "one.zip")
    with (tx.directory / "events.jsonl").open("ab") as stream:
        stream.write(b'{"sequence":2')
    assert len(journal_events.load(tx.directory)["files"]) == 1


def test_corrupt_complete_append_and_sequence_gap_are_rejected(tmp_path):
    tx, root = transaction(tmp_path)
    (tx.directory / "events.jsonl").write_bytes(b"broken\n")
    with pytest.raises(ValueError):
        journal_events.load(tx.directory)
    (tx.directory / "events.jsonl").write_text(json.dumps({"sequence": 2,
        "section": "files", "key": "x", "value": {}}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        journal_events.load(tx.directory)


def test_checkpoint_deduplicates_old_events_after_interruption(tmp_path):
    tx, root = transaction(tmp_path)
    tx.capture(root / "one.zip")
    old_events = (tx.directory / "events.jsonl").read_bytes()
    tx.save()
    (tx.directory / "events.jsonl").write_bytes(old_events)
    assert journal_events.load(tx.directory) == tx.data
    tx.capture(root / "two.zip")
    assert len(journal_events.load(tx.directory)["files"]) == 2


def test_temporary_paths_replay(tmp_path):
    tx, root = transaction(tmp_path)
    with tx.tracking():
        track_temporary(root / "a.zip", root / "a.rms-part")
    assert journal_events.load(tx.directory)["temporaryFiles"] == tx.data["temporaryFiles"]


def test_append_failure_blocks_removal(tmp_path):
    tx, root = transaction(tmp_path)
    path = root / "game.zip"
    path.write_bytes(b"keep me")
    with patch("app.plan.journal_events.os.fsync", side_effect=OSError("disk error")):
        with pytest.raises(OSError):
            tx.remove(path)
    assert path.read_bytes() == b"keep me"


def test_event_changes_invalidate_index_size_cache(tmp_path):
    tx, root = transaction(tmp_path)
    assert journal_index.backup_bytes(tx.directory.parent, "op", lambda: 10) == 10
    tx.capture(root / "a.zip")
    journal_index.records(tx.directory.parent)
    assert journal_index.backup_bytes(tx.directory.parent, "op", lambda: 20) == 20


def test_rename_event_replays_before_checkpoint(tmp_path):
    tx, root = transaction(tmp_path)
    source, target = root / "old.zip", root / "new.zip"
    source.write_bytes(b"ROM")
    checkpoint = (tx.directory / "operation.json").read_bytes()
    tx.rename(source, target)
    assert target.exists() and not source.exists()
    assert (tx.directory / "operation.json").read_bytes() == checkpoint
    assert journal_events.load(tx.directory)["renames"] == tx.data["renames"]
