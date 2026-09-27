"""Portable Archive snapshot for opening an Archive on another computer.

The live SQLite database stays local because the application's WAL connection
must not be used across a network filesystem.  The copy in ``.rms`` is a
single-file, read-only seed.  Publication replaces it atomically and refuses
to overwrite a snapshot that changed since this computer last read it.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing
from pathlib import Path

PORTABLE_APPLICATION_ID = 0x524D5341  # RMSA


def snapshot_path(archive_dir: str) -> Path:
    return Path(archive_dir) / ".rms" / "archive.db"


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def fingerprint(path: Path) -> str:
    return _digest(path)


def _has_archive_rows(path: Path) -> bool:
    if not path.is_file() or not path.stat().st_size:
        return False
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            return bool(db.execute("SELECT 1 FROM rom_identities LIMIT 1").fetchone())
    except sqlite3.DatabaseError:
        # An uninitialized local DB may exist before its first Archive setup.
        return False


def _is_portable_snapshot(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            header = stream.read(72)
        return (len(header) >= 72 and header[:16] == b"SQLite format 3\0"
                and int.from_bytes(header[68:72], "big") == PORTABLE_APPLICATION_ID)
    except OSError:
        return False


def _local_snapshot_digest(local_path: Path) -> str:
    fd, temporary = tempfile.mkstemp(prefix="archive-compare-", suffix=".db")
    os.close(fd)
    try:
        with closing(sqlite3.connect(local_path.as_uri() + "?mode=ro", uri=True)) as origin:
            with closing(sqlite3.connect(temporary)) as target:
                origin.backup(target)
        with closing(sqlite3.connect(temporary)) as target:
            target.execute(f"PRAGMA application_id={PORTABLE_APPLICATION_ID}")
        return _digest(Path(temporary))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def seed_if_clean(local_path: Path, archive_dir: str,
                  expected_digest: str | None = None) -> str | None:
    """Load newer shared data when the local DB has no unpublished changes."""
    source = snapshot_path(archive_dir)
    if (not source.is_file() or not _is_portable_snapshot(source)
            or Path(f"{local_path}-wal").exists()
            or Path(f"{local_path}-shm").exists()):
        return None
    remote_digest = _digest(source)
    if remote_digest == expected_digest:
        return None
    if _has_archive_rows(local_path):
        if expected_digest is None or _local_snapshot_digest(local_path) != expected_digest:
            return None
    local_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="archive-seed-", suffix=".db", dir=local_path.parent)
    os.close(fd)
    try:
        before = _digest(source)
        # SQLite rejects file://server/share URIs (invalid URI authority), and
        # opening a live SQLite connection over SMB is unsafe. Validate a
        # local copy of the immutable portable snapshot instead.
        shutil.copy2(source, temporary)
        with closing(sqlite3.connect(temporary)) as target:
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("Archive snapshot failed quick_check")
        if _digest(source) != before:
            raise RuntimeError("Archive snapshot changed while loading")
        os.replace(temporary, local_path)
        return before
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def seed_if_empty(local_path: Path, archive_dir: str) -> str | None:
    """Backward-compatible name for first-time seeding."""
    return seed_if_clean(local_path, archive_dir)


def publish(store, archive_dir: str, expected_digest: str | None,
            *, legacy_digest: str | None = None) -> dict:
    """Publish one consistent snapshot without replacing another PC's update."""
    destination = snapshot_path(archive_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    current = _digest(destination) if destination.is_file() else None
    upgrading_legacy = bool(current and current == legacy_digest
                            and not _is_portable_snapshot(destination))
    if current is not None and current != expected_digest and not upgrading_legacy:
        return {"status": "conflict", "digest": current}
    fd, temporary = tempfile.mkstemp(prefix="archive-publish-", suffix=".db")
    os.close(fd)
    staging = destination.with_name(f"archive.db.{uuid.uuid4().hex}.tmp")
    backup_staging = destination.with_name(f"archive.legacy.{uuid.uuid4().hex}.tmp")
    try:
        store.backup_to(temporary)
        with closing(sqlite3.connect(temporary)) as snapshot:
            snapshot.execute(f"PRAGMA application_id={PORTABLE_APPLICATION_ID}")
        digest = _digest(Path(temporary))
        shutil.copy2(temporary, staging)
        if destination.is_file() and _digest(destination) != current:
            return {"status": "conflict", "digest": _digest(destination)}
        if upgrading_legacy:
            backup = destination.with_name(f"archive.legacy-{current[:12]}.db")
            if not backup.exists():
                shutil.copy2(destination, backup_staging)
                os.replace(backup_staging, backup)
        os.replace(staging, destination)
        return {"status": "published", "digest": digest}
    finally:
        if staging.exists():
            staging.unlink()
        if backup_staging.exists():
            backup_staging.unlink()
        if os.path.exists(temporary):
            os.unlink(temporary)
