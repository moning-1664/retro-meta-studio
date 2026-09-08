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
    Migration(2, (
        # 표시용 원본 파일명. filename_norm은 매칭용이라 사람이 읽기엔 부적합하다.
        "ALTER TABLE rom_identities ADD COLUMN filename TEXT NOT NULL DEFAULT ''",
        # ROM 원본 위치. Archive는 파일을 복제하지 않지만(§37), Archive -> Collection
        # 복사에서 "어디서 가져올지"는 알아야 한다. media와 같은 취급이다(결정 D3):
        # 경로가 살아 있으면 가져오고, 사라졌으면 그 항목만 건너뛴다.
        """CREATE TABLE archive_rom_sources (
               rom_identity_id TEXT NOT NULL REFERENCES rom_identities(rom_identity_id) ON DELETE CASCADE,
               source_collection_id TEXT NOT NULL,
               abs_path TEXT NOT NULL,
               size INTEGER NOT NULL DEFAULT 0,
               updated_at REAL NOT NULL,
               PRIMARY KEY (rom_identity_id, source_collection_id)
           )""",
    )),
    Migration(3, (
        # ROM Identity를 가르는 진짜 키(§46). filename_norm은 괄호 안 정보를 통째로
        # 버리기 때문에(normalize_title) "Game (USA)"와 "Game (Europe)"이 같은 값이
        # 되어, 서로 다른 ROM이 하나의 Identity로 합쳐지고 있었다 - Archive에 먼저
        # 들어온 쪽의 파일명/크기만 남고 나머지는 사라져, Archive -> Collection이
        # 엉뚱한 지역판 파일을 가져오는 상태였다.
        #
        # rom_key는 파일명 stem을 대소문자/공백만 정리하고 괄호 내용은 **보존**한다.
        # 매칭용 느슨한 정규화(filename_norm)는 그대로 두고 Match 엔진이 쓴다.
        "ALTER TABLE rom_identities ADD COLUMN rom_key TEXT NOT NULL DEFAULT ''",
        # 기존 행은 표시용 filename에서 채운다(없으면 filename_norm).
        "UPDATE rom_identities SET rom_key = lower(trim(CASE WHEN filename <> ''"
        "   THEN filename ELSE filename_norm END))",
        "CREATE INDEX ix_rom_identities_key ON rom_identities(system, rom_key)",
    )),
    Migration(4, (
        # 사용자가 확정한 Match(§49). 자동으로 붙지 않는 티어는 사용자가 고른 결과를
        # 여기 남겨야 다음 Import/Ingest에서도 같은 Identity로 이어진다.
        #
        # 키를 rom_uid로 잡지 않는 이유: cache의 rom_uid는 AUTOINCREMENT이고
        # replace_system()이 System 단위로 통째 DELETE 후 재삽입하므로 재스캔마다
        # 값이 바뀐다. (system, filename)이 roms 테이블의 UNIQUE 자연키다.
        """CREATE TABLE match_links (
               collection_id TEXT NOT NULL,
               system TEXT NOT NULL,
               filename TEXT NOT NULL,
               rom_identity_id TEXT NOT NULL REFERENCES rom_identities(rom_identity_id) ON DELETE CASCADE,
               tier TEXT NOT NULL DEFAULT '',
               score REAL NOT NULL DEFAULT 0,
               created_at REAL NOT NULL,
               PRIMARY KEY (collection_id, system, filename)
           )""",
        "CREATE INDEX ix_match_links_identity ON match_links(rom_identity_id)",
    )),
)


def rom_key_of(filename: str) -> str:
    """ROM Identity를 가르는 키. 확장자를 떼고 대소문자/공백만 정리한다.

    괄호 안 정보((USA)/(Europe)/(Rev 1)/(Disc 1))는 **일부러 남긴다** - 그게 변종을
    구분하는 유일한 단서인 경우가 대부분이기 때문이다. 느슨하게 묶는 일은 Match
    엔진이 별도 티어에서 한다.
    """
    stem = str(filename or "").rsplit(".", 1)[0] if "." in str(filename or "") else str(filename or "")
    return " ".join(stem.split()).strip().lower()


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

    def ensure_rom_identity(self, game_id, system, filename_norm, *, filename="",
                            size=None, sha256=None, region=None, disc_info=None) -> str:
        """이 ROM의 Identity를 찾거나 만든다.

        식별 키는 `rom_key`(파일명 stem을 대소문자/공백만 정리한 값)다. filename_norm은
        괄호 안 정보를 버리므로 "Game (USA)"와 "Game (Europe)"이 같아져 서로 다른 ROM이
        한 Identity로 합쳐진다 - §46이 금지하는 바로 그 상황이다. 두 변종은 같은
        `game_id` 아래 **서로 다른** rom_identity로 남아야 하고, 그 둘을 잇는 것은
        Match 엔진(Phase 5)의 일이다.
        """
        key = rom_key_of(filename or filename_norm)
        row = self._conn.execute(
            "SELECT rom_identity_id FROM rom_identities WHERE system=? AND rom_key=? AND game_id=?",
            (system, key, game_id)).fetchone()
        if row:
            return row["rom_identity_id"]
        rid = uuid.uuid4().hex
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO rom_identities (rom_identity_id,game_id,system,filename_norm,filename,"
                " size,sha256,region,disc_info,rom_key) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rid, game_id, system, filename_norm, filename or filename_norm,
                 size, sha256, region, disc_info, key))
        return rid

    def get_identity(self, rom_identity_id) -> dict | None:
        row = self._conn.execute(
            "SELECT r.*, g.title, g.title_norm FROM rom_identities r"
            " JOIN games g ON g.game_id = r.game_id WHERE r.rom_identity_id=?",
            (rom_identity_id,)).fetchone()
        return dict(row) if row else None

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
    # 목록 조회 (Archive Gamelist - 스펙 §43)
    # ------------------------------------------------------------------
    def list_rows(self, *, search=None, systems=None, limit=None, offset=0) -> list[dict]:
        """Archive도 일반 Collection과 같은 Gamelist로 보여준다(§43).

        Collection 목록과 같은 모양으로 돌려줘서 UI가 같은 렌더링을 쓰게 한다.
        """
        where, params = self._row_filter(search, systems)
        sql = (
            "SELECT r.rom_identity_id, r.game_id, r.system, r.filename, r.region,"
            "       g.title, g.title_norm,"
            "       (SELECT COUNT(DISTINCT source_collection_id) FROM archive_records"
            "         WHERE rom_identity_id = r.rom_identity_id) AS source_count,"
            "       (SELECT MAX(updated_at) FROM archive_records"
            "         WHERE rom_identity_id = r.rom_identity_id) AS updated_at"
            f" FROM rom_identities r JOIN games g ON g.game_id = r.game_id{where}"
            " ORDER BY g.title_norm, r.filename"
        )
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = [*params, int(limit), int(offset)]
        return [dict(r) for r in self._conn.execute(sql, params)]

    def count_rows(self, *, search=None, systems=None) -> int:
        where, params = self._row_filter(search, systems)
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM rom_identities r"
            f" JOIN games g ON g.game_id = r.game_id{where}", params).fetchone()
        return int(row["n"])

    @staticmethod
    def _row_filter(search, systems):
        clauses, params = [], []
        if systems:
            clauses.append(f"r.system IN ({','.join('?' * len(systems))})")
            params.extend(systems)
        if search:
            clauses.append("(g.title_norm LIKE ? OR r.filename LIKE ?)")
            needle = f"%{str(search).strip().lower()}%"
            params.extend([needle, needle])
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def systems(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT system, COUNT(*) AS count FROM rom_identities GROUP BY system ORDER BY system")]

    # ------------------------------------------------------------------
    # ROM / Media 원본 참조
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Match (§45-49)
    # ------------------------------------------------------------------
    def identities_in_system(self, system, *, exclude_collection=None) -> list[dict]:
        """Match 후보 풀. 같은 System만 본다 - 시스템이 다르면 애초에 비교 대상이 아니다.

        `exclude_collection`을 주면 그 Collection에서만 온 Identity는 뺀다. 자기
        자신이 후보로 뜨는 것을 막기 위한 것이다.
        """
        sql = ("SELECT r.*, g.title, g.title_norm FROM rom_identities r"
               " JOIN games g ON g.game_id = r.game_id WHERE r.system=?")
        params = [system]
        if exclude_collection:
            sql += (" AND EXISTS (SELECT 1 FROM archive_records ar"
                    "   WHERE ar.rom_identity_id = r.rom_identity_id"
                    "     AND ar.source_collection_id <> ?)")
            params.append(exclude_collection)
        return [dict(row) for row in self._conn.execute(sql, params)]

    def put_match_link(self, collection_id, system, filename, rom_identity_id, *, tier="", score=0.0):
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO match_links (collection_id,system,filename,rom_identity_id,tier,score,created_at)"
                " VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(collection_id,system,filename) DO UPDATE SET"
                "   rom_identity_id=excluded.rom_identity_id, tier=excluded.tier,"
                "   score=excluded.score, created_at=excluded.created_at",
                (collection_id, system, filename, rom_identity_id, tier, float(score), time.time()))

    def get_match_link(self, collection_id, system, filename) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM match_links WHERE collection_id=? AND system=? AND filename=?",
            (collection_id, system, filename)).fetchone()
        return dict(row) if row else None

    def match_links_of(self, collection_id) -> dict:
        """{(system, filename): rom_identity_id} - 목록 한 번에 표시할 때 쓴다."""
        return {(r["system"], r["filename"]): r["rom_identity_id"] for r in self._conn.execute(
            "SELECT system, filename, rom_identity_id FROM match_links WHERE collection_id=?",
            (collection_id,))}

    def delete_match_link(self, collection_id, system, filename) -> bool:
        with transaction(self._conn):
            cur = self._conn.execute(
                "DELETE FROM match_links WHERE collection_id=? AND system=? AND filename=?",
                (collection_id, system, filename))
        return cur.rowcount > 0

    def put_rom_source(self, rom_identity_id, source_collection_id, abs_path, size=0):
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO archive_rom_sources (rom_identity_id,source_collection_id,abs_path,size,updated_at)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(rom_identity_id,source_collection_id) DO UPDATE SET"
                " abs_path=excluded.abs_path, size=excluded.size, updated_at=excluded.updated_at",
                (rom_identity_id, source_collection_id, str(abs_path), int(size), time.time()))

    def rom_sources(self, rom_identity_id) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM archive_rom_sources WHERE rom_identity_id=? ORDER BY updated_at DESC",
            (rom_identity_id,))]

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
