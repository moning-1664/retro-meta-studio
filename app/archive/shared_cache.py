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
import time
import uuid
import logging
from contextlib import closing
from pathlib import Path

PORTABLE_APPLICATION_ID = 0x524D5341  # RMSA
log = logging.getLogger(__name__)


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


def _store_snapshot_digest(store) -> str:
    """Fingerprint the live connection, including uncheckpointed WAL changes."""
    fd, temporary = tempfile.mkstemp(prefix="archive-live-compare-", suffix=".db")
    os.close(fd)
    try:
        store.backup_to(temporary)
        with closing(sqlite3.connect(temporary)) as snapshot:
            snapshot.execute(f"PRAGMA application_id={PORTABLE_APPLICATION_ID}")
        return _digest(Path(temporary))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def pull_if_clean(store, archive_dir: str, expected_digest: str | None) -> dict:
    """Load another PC's snapshot into the open store only if local data is clean.

    The ArchiveStore connection remains open. Replacing its database file while
    WebView requests can still use that connection would leave stale handles and
    can reproduce the closed-database failure seen during Archive refresh.
    """
    source = snapshot_path(archive_dir)
    if not source.is_file() or not _is_portable_snapshot(source):
        return {"status": "missing"}
    started = time.perf_counter()
    remote_digest = _digest(source)
    log.info("Archive shared pull remote digest seconds=%.3f bytes=%d",
             time.perf_counter() - started, source.stat().st_size)
    if remote_digest == expected_digest:
        return {"status": "unchanged", "digest": remote_digest}

    fd, temporary = tempfile.mkstemp(prefix="archive-pull-", suffix=".db")
    os.close(fd)
    try:
        stage_started = time.perf_counter()
        shutil.copy2(source, temporary)
        log.info("Archive shared pull stage seconds=%.3f", time.perf_counter() - stage_started)
        with closing(sqlite3.connect(temporary)) as incoming:
            if incoming.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("Archive snapshot failed quick_check")
        if _digest(source) != remote_digest:
            raise RuntimeError("Archive snapshot changed while loading")
        # The store's connection lock covers both the clean check and restore;
        # a concurrent Archive edit cannot slip between them.
        with store._conn._lock:
            live = store._conn._conn
            if live.in_transaction:
                return {"status": "conflict", "digest": remote_digest}
            has_local_rows = bool(live.execute("SELECT 1 FROM rom_identities LIMIT 1").fetchone())
            if has_local_rows and (expected_digest is None
                                   or _store_snapshot_digest(store) != expected_digest):
                return {"status": "conflict", "digest": remote_digest}
            with closing(sqlite3.connect(temporary)) as incoming:
                restore_started = time.perf_counter()
                incoming.backup(live)
                log.info("Archive shared pull restore seconds=%.3f", time.perf_counter() - restore_started)
        return {"status": "loaded", "digest": remote_digest}
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
    started = time.perf_counter()
    current = _digest(destination) if destination.is_file() else None
    log.info("Archive shared publish remote digest seconds=%.3f", time.perf_counter() - started)
    upgrading_legacy = bool(current and current == legacy_digest
                            and not _is_portable_snapshot(destination))
    if current is not None and current != expected_digest and not upgrading_legacy:
        return {"status": "conflict", "digest": current}
    fd, temporary = tempfile.mkstemp(prefix="archive-publish-", suffix=".db")
    os.close(fd)
    staging = destination.with_name(f"archive.db.{uuid.uuid4().hex}.tmp")
    backup_staging = destination.with_name(f"archive.legacy.{uuid.uuid4().hex}.tmp")
    try:
        backup_started = time.perf_counter()
        store.backup_to(temporary)
        with closing(sqlite3.connect(temporary)) as snapshot:
            snapshot.execute(f"PRAGMA application_id={PORTABLE_APPLICATION_ID}")
        digest = _digest(Path(temporary))
        log.info("Archive shared publish local snapshot seconds=%.3f bytes=%d",
                 time.perf_counter() - backup_started, Path(temporary).stat().st_size)
        stage_started = time.perf_counter()
        shutil.copy2(temporary, staging)
        log.info("Archive shared publish stage seconds=%.3f", time.perf_counter() - stage_started)
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


def resolve_conflict(store, archive_dir: str, observed_digest: str,
                     choice: str, backup_dir: Path) -> dict:
    """Preserve both databases before explicitly choosing the local or shared copy."""
    if choice not in ("local", "shared"):
        raise ValueError("Archive 충돌 해결 방법을 선택하세요.")
    source = snapshot_path(archive_dir)
    if not source.is_file() or not _is_portable_snapshot(source):
        raise ValueError("공유 Archive DB를 찾을 수 없습니다.")
    if _digest(source) != observed_digest:
        return {"status": "conflict", "digest": _digest(source)}
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:12]
    local_backup = backup_dir / f"archive-local-{token}.db"
    shared_backup = backup_dir / f"archive-shared-{token}.db"
    store.backup_to(local_backup)
    shutil.copy2(source, shared_backup)
    if _digest(source) != observed_digest or _digest(shared_backup) != observed_digest:
        return {"status": "conflict", "digest": _digest(source),
                "backups": [str(local_backup), str(shared_backup)]}
    if choice == "local":
        result = publish(store, archive_dir, observed_digest)
        return {**result, "backups": [str(local_backup), str(shared_backup)]}
    with store._conn._lock:
        if _digest(source) != observed_digest:
            return {"status": "conflict", "digest": _digest(source),
                    "backups": [str(local_backup), str(shared_backup)]}
        with closing(sqlite3.connect(shared_backup)) as incoming:
            if incoming.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("Archive snapshot failed quick_check")
            incoming.backup(store._conn._conn)
    return {"status": "loaded", "digest": observed_digest,
            "backups": [str(local_backup), str(shared_backup)]}
