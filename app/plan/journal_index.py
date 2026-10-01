"""Rebuildable status index; checkpoint plus durable events are authoritative."""
import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from app.plan import journal_events

log = logging.getLogger(__name__)
KEYS = ("id", "collectionId", "config", "relatedCollections", "status", "createdAt",
        "undoneAt", "redoReady", "action", "recoveryError", "owner")


def connect(root):
    conn = sqlite3.connect(Path(root) / "status-index.sqlite", timeout=5)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, stamp TEXT, summary TEXT, bytes INTEGER)")
    except sqlite3.Error:
        conn.close()
        raise
    return conn


def stamp(path):
    stat = path.stat()
    signature = f"{stat.st_mtime_ns}:{stat.st_size}:{stat.st_ino}"
    events = path.parent / "events.jsonl"
    if events.exists():
        info = events.stat()
        signature += f":{info.st_mtime_ns}:{info.st_size}"
    return signature


def update(root, directory, data):
    try:
        with closing(connect(root)) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,NULL)",
                (directory.name, stamp(directory / "operation.json"),
                 json.dumps({key: data[key] for key in KEYS if key in data}, ensure_ascii=False)))
    except (OSError, sqlite3.Error):
        log.warning("Journal status index unavailable; journal retained", exc_info=True)


def records(root):
    root = Path(root)
    try:
        with closing(connect(root)) as conn, conn:
            cached = {row[0]: row for row in conn.execute("SELECT id,stamp,summary FROM records")}
            seen, result = set(), []
            for path in root.glob("*/operation.json"):
                key = path.parent.name
                seen.add(key)
                signature = stamp(path)
                entry = cached.get(key)
                if entry and entry[1] == signature:
                    result.append(json.loads(entry[2]))
                    continue
                data = journal_events.load(path.parent)
                summary = {key: data[key] for key in KEYS if key in data}
                conn.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,NULL)",
                    (path.parent.name, signature, json.dumps(summary, ensure_ascii=False)))
                result.append(summary)
            for key in cached.keys() - seen:
                conn.execute("DELETE FROM records WHERE id=?", (key,))
            return result
    except (OSError, ValueError, sqlite3.Error):
        log.warning("Journal index read failed; reading authoritative records", exc_info=True)
        return [journal_events.load(path.parent) for path in root.glob("*/operation.json")]


def backup_bytes(root, operation_id, calculate):
    try:
        with closing(connect(root)) as conn, conn:
            row = conn.execute("SELECT bytes FROM records WHERE id=?", (operation_id,)).fetchone()
            if row and row[0] is not None:
                return row[0]
            size = calculate()
            conn.execute("UPDATE records SET bytes=? WHERE id=?", (size, operation_id))
            return size
    except (OSError, sqlite3.Error):
        return calculate()
