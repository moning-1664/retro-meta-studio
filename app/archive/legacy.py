"""
app/archive/legacy.py
======================
이전 버전이 만든 Archive 디렉토리(`<dir>/.rms/archive.db` + `.rms/media/...`)를 읽어
현재 Archive로 옮긴다.

옛 구조는 media를 `.rms/media/<system>/<identity>/<type>.<ext>`에 숨겨 두고 사용자가 볼 수
있는 Frontend 트리(gamelists/downloaded_media)는 일부만 채웠다. 여기서는 옛 DB의 내용을
그대로 가져오고, 숨은 media는 **참조로만** 연결한다 - 파일은 projection이 Frontend
규칙 위치(`downloaded_media/<system>/<type>/<stem>.ext`)로 복사한다.

옛 DB는 **읽기 전용으로만** 연다. 다시 실행해도 같은 결과가 되도록(idempotent) Identity는
ID로 병합한다.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path

from app.archive.shared_cache import PORTABLE_APPLICATION_ID
from app.store.archive import ARCHIVE_EDIT_SOURCE
from app.store.sqlite import transaction

LEGACY_DB = Path(".rms") / "archive.db"


def legacy_db_path(archive_dir) -> Path:
    return Path(archive_dir) / LEGACY_DB


def has_legacy(archive_dir) -> bool:
    if not archive_dir or not legacy_db_path(archive_dir).is_file():
        return False
    path = legacy_db_path(archive_dir)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        return db.execute("PRAGMA application_id").fetchone()[0] != PORTABLE_APPLICATION_ID


def _columns(conn, table) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def import_legacy(archive, archive_dir) -> dict:
    """옛 Archive DB를 현재 Archive로 병합한다. 반환: 가져온 개수 요약."""
    path = legacy_db_path(archive_dir)
    if not has_legacy(archive_dir):
        return {"found": False}
    old = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    old.row_factory = sqlite3.Row
    counts = {"found": True, "games": 0, "identities": 0, "records": 0,
              "media": 0, "roms": 0, "preferred": 0}
    tables = _tables(old)
    new = archive._conn
    try:
        with transaction(new):
            counts["games"] = _copy(old, new, "games", tables)
            counts["identities"] = _copy(old, new, "rom_identities", tables)
            id_map, counts["records"] = _copy_records(old, new, tables)
            counts["preferred"] = _copy_preferred(old, new, id_map, tables)
            counts["media"] = _copy_media(old, new, Path(archive_dir), tables)
            counts["roms"] = _copy_roms(old, new, tables)
    finally:
        old.close()
    return counts


def _copy(old, new, table, tables) -> int:
    if table not in tables:
        return 0
    cols = [c for c in _columns(old, table) if c in _columns(new, table)]
    marks = ",".join("?" * len(cols))
    n = 0
    for row in old.execute(f"SELECT {','.join(cols)} FROM {table}"):
        cur = new.execute(f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({marks})",
                          tuple(row))
        n += cur.rowcount
    return n


def _copy_records(old, new, tables):
    """record_id는 자동 증가라 그대로 못 쓴다 - (identity, source, revision)으로 옮기고
    옛 ID -> 새 ID를 돌려줘 preferred가 같은 Revision을 가리키게 한다."""
    id_map: dict[int, int] = {}
    if "archive_records" not in tables:
        return id_map, 0
    cols = [c for c in _columns(old, "archive_records")
            if c != "record_id" and c in _columns(new, "archive_records")]
    marks = ",".join("?" * len(cols))
    n = 0
    for row in old.execute(f"SELECT record_id,{','.join(cols)} FROM archive_records"):
        cur = new.execute(
            f"INSERT OR IGNORE INTO archive_records ({','.join(cols)}) VALUES ({marks})",
            tuple(row[c] for c in cols))
        n += cur.rowcount
        found = new.execute(
            "SELECT record_id FROM archive_records WHERE rom_identity_id=? AND"
            " source_collection_id=? AND revision=?",
            (row["rom_identity_id"], row["source_collection_id"], row["revision"])).fetchone()
        if found:
            id_map[row["record_id"]] = found[0]
    return id_map, n


def _copy_preferred(old, new, id_map, tables) -> int:
    if "preferred_revisions" not in tables:
        return 0
    n = 0
    for row in old.execute("SELECT rom_identity_id, record_id, updated_at FROM preferred_revisions"):
        record_id = id_map.get(row["record_id"])
        if record_id is None:
            continue
        cur = new.execute(
            "INSERT OR IGNORE INTO preferred_revisions (rom_identity_id,record_id,updated_at)"
            " VALUES (?,?,?)", (row["rom_identity_id"], record_id, row["updated_at"]))
        n += cur.rowcount
    return n


def _copy_media(old, new, archive_dir: Path, tables) -> int:
    """`.rms/media`에 숨겨 둔 사본을 우선한다(원래 Collection 경로는 사라졌을 수 있다).

    옛 원본 경로(archive_media)도 함께 가져온다 - 숨은 사본이 없는 media를 위한 대체다.
    숨은 사본은 지금 시각으로 기록해 projection에서 "가장 최근 것"이 되게 한다.
    """
    n = 0
    if "archive_media" in tables:
        cols = [c for c in _columns(old, "archive_media") if c in _columns(new, "archive_media")]
        marks = ",".join("?" * len(cols))
        for row in old.execute(f"SELECT {','.join(cols)} FROM archive_media"):
            cur = new.execute(
                f"INSERT OR IGNORE INTO archive_media ({','.join(cols)}) VALUES ({marks})",
                tuple(row))
            n += cur.rowcount
    if "archive_master_media" in tables:
        now = time.time()
        for row in old.execute("SELECT rom_identity_id, media_type, rel_path, size"
                               " FROM archive_master_media"):
            abs_path = archive_dir / str(row["rel_path"]).replace("\\", "/")
            if not abs_path.is_file():
                continue
            new.execute(
                "INSERT INTO archive_media (rom_identity_id,media_type,source_collection_id,"
                "abs_path,size,updated_at) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(rom_identity_id,media_type,source_collection_id)"
                " DO UPDATE SET abs_path=excluded.abs_path,size=excluded.size,"
                "updated_at=excluded.updated_at",
                (row["rom_identity_id"], row["media_type"], ARCHIVE_EDIT_SOURCE,
                 str(abs_path), int(row["size"] or 0), now))
            n += 1
    return n


def _copy_roms(old, new, tables) -> int:
    n = 0
    if "archive_rom_sources" in tables:
        cols = _columns(old, "archive_rom_sources")
        marks = ",".join("?" * len(cols))
        for row in old.execute(f"SELECT {','.join(cols)} FROM archive_rom_sources"):
            cur = new.execute(
                f"INSERT OR IGNORE INTO archive_rom_sources ({','.join(cols)}) VALUES ({marks})",
                tuple(row))
            n += cur.rowcount
    if "archive_master_rom" in tables:
        now = time.time()
        for row in old.execute("SELECT rom_identity_id, rel_path, size FROM archive_master_rom"):
            new.execute(
                "INSERT INTO archive_rom_sources (rom_identity_id,source_collection_id,abs_path,"
                "size,updated_at) VALUES (?,?,?,?,?)"
                " ON CONFLICT(rom_identity_id,source_collection_id)"
                " DO UPDATE SET abs_path=excluded.abs_path,size=excluded.size,"
                "updated_at=excluded.updated_at",
                (row["rom_identity_id"], ARCHIVE_EDIT_SOURCE, str(row["rel_path"]),
                 int(row["size"] or 0), now))
            n += 1
    return n
