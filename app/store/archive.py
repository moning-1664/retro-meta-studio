"""
app/store/archive.py
=====================
archive.db - Metadata / Identity 보관과 출처 추적.

**Archive는 MasterDB의 대체가 아니다**(스펙 §37, §92). Canonical Source가 아니라
여러 Collection에서 수집한 정보의 보관소이며, Media 파일을 복제하지 않고 원본
위치만 가리킨다(결정 D3).

Game Identity와 ROM Identity를 분리한다(§46). 같은 게임의 Japan/USA/Korea판은
서로 다른 ROM Identity이고 하나의 Game에 묶인다. Collection의 Gamelist는 ROM 단위로
표시되지만(사용자 결정), Archive와 Match는 이 Game 묶음을 사용한다.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid

from app.store.sqlite import Migration, connect, transaction

# History Retention 정책(§39). 기본은 제한된 History.
RETENTION_NONE = "none"
RETENTION_LATEST_1 = "latest-1"
RETENTION_LATEST_5 = "latest-5"
RETENTION_UNLIMITED = "unlimited"
DEFAULT_RETENTION = RETENTION_LATEST_5

MIGRATIONS = (
    Migration(1, (
        """CREATE TABLE games (
               game_id TEXT PRIMARY KEY,
               title TEXT NOT NULL DEFAULT '',
               title_norm TEXT NOT NULL DEFAULT '',
               created_at REAL NOT NULL
           )""",
        "CREATE INDEX ix_games_title ON games(title_norm)",
        """CREATE TABLE rom_identities (
               rom_identity_id TEXT PRIMARY KEY,
               game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
               system TEXT NOT NULL,
               filename_norm TEXT NOT NULL DEFAULT '',
               size INTEGER,
               sha256 TEXT,
               region TEXT,
               disc_info TEXT
           )""",
        "CREATE INDEX ix_rom_identities_game ON rom_identities(game_id)",
        "CREATE INDEX ix_rom_identities_lookup ON rom_identities(system, filename_norm)",
        "CREATE INDEX ix_rom_identities_sha ON rom_identities(sha256)",
        # 출처는 Collection 이름이 아니라 ID로 기록한다 - 이름이 바뀌어도 관계가
        # 유지되어야 한다(§38).
        """CREATE TABLE archive_records (
               record_id INTEGER PRIMARY KEY AUTOINCREMENT,
               rom_identity_id TEXT NOT NULL REFERENCES rom_identities(rom_identity_id) ON DELETE CASCADE,
               source_collection_id TEXT NOT NULL,
               revision INTEGER NOT NULL,
               content_hash TEXT NOT NULL,
               fields_json TEXT NOT NULL DEFAULT '{}',
               frontend_raw_json TEXT NOT NULL DEFAULT '{}',
               updated_at REAL NOT NULL,
               UNIQUE (rom_identity_id, source_collection_id, revision)
           )""",
        "CREATE INDEX ix_records_identity ON archive_records(rom_identity_id)",
        # Media는 파일을 복제하지 않고 원본 경로만 기록한다. 붙여넣을 때 이 경로에서
        # 복사하고, 접근할 수 없으면 그 Media만 건너뛴다(D3).
        """CREATE TABLE archive_media (
               rom_identity_id TEXT NOT NULL REFERENCES rom_identities(rom_identity_id) ON DELETE CASCADE,
               media_type TEXT NOT NULL,
               source_collection_id TEXT NOT NULL,
               abs_path TEXT NOT NULL,
               size INTEGER NOT NULL DEFAULT 0,
               updated_at REAL NOT NULL,
               PRIMARY KEY (rom_identity_id, media_type, source_collection_id)
           )""",
    )),
)


def content_hash(fields, frontend_raw=None) -> str:
    """내용이 실제로 바뀌었는지 판정하는 해시(§39).

    같은 Metadata를 반복 Import해도 Revision이 늘어나지 않게 하는 것이 목적이므로,
    키 순서에 흔들리지 않도록 정렬해서 직렬화한다.
    """
    payload = json.dumps({"fields": fields or {}, "raw": frontend_raw or {}},
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ArchiveStore:
    def __init__(self, path):
        self._conn = connect(path, MIGRATIONS)

    def close(self):
        self._conn.close()

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    def ensure_game(self, title, title_norm) -> str:
        row = self._conn.execute("SELECT game_id FROM games WHERE title_norm=?", (title_norm,)).fetchone()
        if row:
            return row["game_id"]
        game_id = uuid.uuid4().hex
        with transaction(self._conn):
            self._conn.execute("INSERT INTO games (game_id,title,title_norm,created_at) VALUES (?,?,?,?)",
                               (game_id, title, title_norm, time.time()))
        return game_id

    def ensure_rom_identity(self, game_id, system, filename_norm, *,
                            size=None, sha256=None, region=None, disc_info=None) -> str:
        row = self._conn.execute(
            "SELECT rom_identity_id FROM rom_identities WHERE system=? AND filename_norm=? AND game_id=?",
            (system, filename_norm, game_id)).fetchone()
        if row:
            return row["rom_identity_id"]
        rid = uuid.uuid4().hex
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO rom_identities (rom_identity_id,game_id,system,filename_norm,size,sha256,region,disc_info)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (rid, game_id, system, filename_norm, size, sha256, region, disc_info))
        return rid

    def rom_identities_of_game(self, game_id) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM rom_identities WHERE game_id=? ORDER BY system, filename_norm", (game_id,))]

    # ------------------------------------------------------------------
    # Record / Revision
    # ------------------------------------------------------------------
    def put_record(self, rom_identity_id, source_collection_id, fields, frontend_raw=None,
                   *, retention=DEFAULT_RETENTION) -> tuple[int, bool]:
        """Metadata를 보관한다. 내용이 바뀐 경우에만 새 Revision을 만든다(§39).

        반환: (revision, created) - created=False면 같은 내용이라 아무것도 쓰지 않았다.
        """
        digest = content_hash(fields, frontend_raw)
        with transaction(self._conn):
            latest = self._conn.execute(
                "SELECT revision, content_hash FROM archive_records"
                " WHERE rom_identity_id=? AND source_collection_id=?"
                " ORDER BY revision DESC LIMIT 1",
                (rom_identity_id, source_collection_id)).fetchone()
            if latest and latest["content_hash"] == digest:
                return int(latest["revision"]), False
            revision = (int(latest["revision"]) + 1) if latest else 1
            self._conn.execute(
                "INSERT INTO archive_records (rom_identity_id,source_collection_id,revision,content_hash,"
                " fields_json,frontend_raw_json,updated_at) VALUES (?,?,?,?,?,?,?)",
                (rom_identity_id, source_collection_id, revision, digest,
                 json.dumps(fields or {}, ensure_ascii=False),
                 json.dumps(frontend_raw or {}, ensure_ascii=False), time.time()))
            self._apply_retention_locked(rom_identity_id, source_collection_id, retention)
            return revision, True

    def _apply_retention_locked(self, rom_identity_id, source_collection_id, retention):
        keep = {RETENTION_NONE: 1, RETENTION_LATEST_1: 1, RETENTION_LATEST_5: 5}.get(retention)
        if keep is None:  # unlimited
            return
        self._conn.execute(
            "DELETE FROM archive_records WHERE rom_identity_id=? AND source_collection_id=?"
            " AND revision <= (SELECT MAX(revision)-? FROM archive_records"
            "                  WHERE rom_identity_id=? AND source_collection_id=?)",
            (rom_identity_id, source_collection_id, keep, rom_identity_id, source_collection_id))

    def latest_record(self, rom_identity_id, source_collection_id) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM archive_records WHERE rom_identity_id=? AND source_collection_id=?"
            " ORDER BY revision DESC LIMIT 1", (rom_identity_id, source_collection_id)).fetchone()
        return self._record_dict(row) if row else None

    def sources_of(self, rom_identity_id) -> list[dict]:
        """이 ROM의 Metadata가 어느 Collection들에서 왔는지(§44 Source 비교용)."""
        rows = self._conn.execute(
            "SELECT r.* FROM archive_records r"
            " JOIN (SELECT source_collection_id, MAX(revision) AS rev FROM archive_records"
            "       WHERE rom_identity_id=? GROUP BY source_collection_id) m"
            "   ON r.source_collection_id=m.source_collection_id AND r.revision=m.rev"
            " WHERE r.rom_identity_id=?", (rom_identity_id, rom_identity_id)).fetchall()
        return [self._record_dict(r) for r in rows]

    def revisions_of(self, rom_identity_id, source_collection_id) -> list[dict]:
        return [self._record_dict(r) for r in self._conn.execute(
            "SELECT * FROM archive_records WHERE rom_identity_id=? AND source_collection_id=?"
            " ORDER BY revision DESC", (rom_identity_id, source_collection_id))]

    @staticmethod
    def _record_dict(row) -> dict:
        return {"record_id": row["record_id"], "rom_identity_id": row["rom_identity_id"],
                "source_collection_id": row["source_collection_id"], "revision": row["revision"],
                "content_hash": row["content_hash"], "fields": json.loads(row["fields_json"]),
                "frontend_raw": json.loads(row["frontend_raw_json"]), "updated_at": row["updated_at"]}

    # ------------------------------------------------------------------
    # Media 참조
    # ------------------------------------------------------------------
    def put_media_ref(self, rom_identity_id, media_type, source_collection_id, abs_path, size=0):
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO archive_media (rom_identity_id,media_type,source_collection_id,abs_path,size,updated_at)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(rom_identity_id,media_type,source_collection_id) DO UPDATE SET"
                " abs_path=excluded.abs_path, size=excluded.size, updated_at=excluded.updated_at",
                (rom_identity_id, media_type, source_collection_id, str(abs_path), int(size), time.time()))

    def media_refs(self, rom_identity_id) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM archive_media WHERE rom_identity_id=? ORDER BY media_type", (rom_identity_id,))]
