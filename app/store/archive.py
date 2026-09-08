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

# History Retention 정책. ARCHIVE_REVISION_POLICY.md §23/§26: Revision은 자동
# 삭제하지 않는 것이 기본값이다 - Archive의 목적이 historical preservation이므로,
# 개수 제한(예: 최신 5개만 유지)을 기본으로 걸면 사용자 의도와 무관하게 과거
# 상태가 조용히 사라진다. 제한된 History가 필요하면 호출부가 명시적으로 골라야
# 한다(예: `put_record(..., retention=RETENTION_LATEST_5)`).
RETENTION_NONE = "none"
RETENTION_LATEST_1 = "latest-1"
RETENTION_LATEST_5 = "latest-5"
RETENTION_UNLIMITED = "unlimited"
DEFAULT_RETENTION = RETENTION_UNLIMITED

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
    Migration(5, (
        # 파일을 rename하면 (collection_id, system, filename) 키가 어긋나 사용자가
        # 확정해 둔 Match가 조용히 끊긴다. 파일시스템이 주는 파일 ID(NTFS의
        # 볼륨:인덱스)는 **rename과 내용 수정에도 유지되고 새 파일과는 다르므로**,
        # 이름이 바뀐 뒤에도 같은 파일임을 알아볼 수 있다(실측으로 확인).
        #
        # 파일 ID를 주 키로 삼지는 않는다 - 네트워크 공유나 비NTFS에서는 값이 없고,
        # 다른 볼륨으로 옮기면 바뀐다. 이름으로 먼저 찾고, 어긋날 때 이 값으로
        # 되찾아 링크를 고쳐 놓는 보조 수단이다.
        "ALTER TABLE match_links ADD COLUMN volume_file_id TEXT",
        "CREATE INDEX ix_match_links_file ON match_links(collection_id, volume_file_id)",
    )),
    Migration(6, (
        # ARCHIVE_REVISION_POLICY.md §16-17: 변경 계보(provenance)와 생성 원인을
        # 남긴다. Fingerprint(= content_hash)가 이미 내용 동일성을 판정하므로
        # parent는 identity가 아니라 "무엇을 보고 있다가 고쳤는가"만 설명한다.
        "ALTER TABLE archive_records ADD COLUMN parent_record_id INTEGER",
        "ALTER TABLE archive_records ADD COLUMN created_by TEXT NOT NULL DEFAULT 'import'",
        # ARCHIVE_REVISION_POLICY.md §8: Preferred는 Revision의 속성이 아니라
        # ROM Identity가 "지금 어느 Revision을 선호하는가"를 가리키는 별도 상태다.
        # Revision 내용을 바꾸지 않으므로 archive_records와 분리한 테이블에 둔다.
        """CREATE TABLE preferred_revisions (
               rom_identity_id TEXT PRIMARY KEY REFERENCES rom_identities(rom_identity_id) ON DELETE CASCADE,
               record_id INTEGER NOT NULL REFERENCES archive_records(record_id) ON DELETE CASCADE,
               updated_at REAL NOT NULL
           )""",
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
                   *, retention=DEFAULT_RETENTION, created_by="import") -> tuple[int, bool]:
        """Metadata를 보관한다. 내용이 바뀐 경우에만 새 Revision을 만든다(§39).

        `created_by`는 이 Revision이 생긴 원인이다(§17.1: "export"/"user_edit"/"import"
        등). 새 Revision의 `parent_record_id`는 같은 (identity, source) 계보에서 바로
        직전 Revision을 가리킨다(§16) - Fingerprint(content_hash)가 내용 동일성을
        판정하므로 parent는 계보 설명용일 뿐 identity 판정에는 쓰지 않는다.

        반환: (revision, created) - created=False면 같은 내용이라 아무것도 쓰지 않았다.
        """
        digest = content_hash(fields, frontend_raw)
        with transaction(self._conn):
            latest = self._conn.execute(
                "SELECT record_id, revision, content_hash FROM archive_records"
                " WHERE rom_identity_id=? AND source_collection_id=?"
                " ORDER BY revision DESC LIMIT 1",
                (rom_identity_id, source_collection_id)).fetchone()
            if latest and latest["content_hash"] == digest:
                return int(latest["revision"]), False
            revision = (int(latest["revision"]) + 1) if latest else 1
            self._conn.execute(
                "INSERT INTO archive_records (rom_identity_id,source_collection_id,revision,content_hash,"
                " fields_json,frontend_raw_json,updated_at,parent_record_id,created_by)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (rom_identity_id, source_collection_id, revision, digest,
                 json.dumps(fields or {}, ensure_ascii=False),
                 json.dumps(frontend_raw or {}, ensure_ascii=False), time.time(),
                 (latest["record_id"] if latest else None), created_by))
            self._apply_retention_locked(rom_identity_id, source_collection_id, retention)
            return revision, True

    def _apply_retention_locked(self, rom_identity_id, source_collection_id, retention):
        keep = {RETENTION_NONE: 1, RETENTION_LATEST_1: 1, RETENTION_LATEST_5: 5}.get(retention)
        if keep is None:  # unlimited
            return
        # ARCHIVE_REVISION_POLICY.md §27.1: Preferred Revision은 개수 제한으로도
        # 삭제하지 않는다. 지워질 후보에 Preferred가 끼어 있으면 그 행만 보존한다.
        preferred = self._conn.execute(
            "SELECT record_id FROM preferred_revisions WHERE rom_identity_id=?",
            (rom_identity_id,)).fetchone()
        preferred_id = preferred["record_id"] if preferred else None
        self._conn.execute(
            "DELETE FROM archive_records WHERE rom_identity_id=? AND source_collection_id=?"
            " AND revision <= (SELECT MAX(revision)-? FROM archive_records"
            "                  WHERE rom_identity_id=? AND source_collection_id=?)"
            " AND record_id IS NOT ?",
            (rom_identity_id, source_collection_id, keep, rom_identity_id, source_collection_id,
             preferred_id))

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

    def record_by_id(self, record_id) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM archive_records WHERE record_id=?", (record_id,)).fetchone()
        return self._record_dict(row) if row else None

    @staticmethod
    def _record_dict(row) -> dict:
        return {"record_id": row["record_id"], "rom_identity_id": row["rom_identity_id"],
                "source_collection_id": row["source_collection_id"], "revision": row["revision"],
                "content_hash": row["content_hash"], "fields": json.loads(row["fields_json"]),
                "frontend_raw": json.loads(row["frontend_raw_json"]), "updated_at": row["updated_at"],
                "parent_record_id": row["parent_record_id"], "created_by": row["created_by"]}

    # ------------------------------------------------------------------
    # Preferred Revision (ARCHIVE_REVISION_POLICY.md §8-9)
    # ------------------------------------------------------------------
    def set_preferred(self, rom_identity_id, record_id) -> None:
        """이 Identity가 `record_id`를 Preferred Revision으로 선호하게 한다.

        Preferred는 Revision 자체의 속성이 아니라 선택 상태이므로, 지정해도
        `archive_records`의 내용은 전혀 바뀌지 않는다(§8).
        """
        record = self.record_by_id(record_id)
        if record is None or record["rom_identity_id"] != rom_identity_id:
            raise ValueError("해당 Identity의 Revision이 아닙니다.")
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO preferred_revisions (rom_identity_id,record_id,updated_at) VALUES (?,?,?)"
                " ON CONFLICT(rom_identity_id) DO UPDATE SET"
                "   record_id=excluded.record_id, updated_at=excluded.updated_at",
                (rom_identity_id, record_id, time.time()))

    def get_preferred(self, rom_identity_id) -> dict | None:
        row = self._conn.execute(
            "SELECT record_id FROM preferred_revisions WHERE rom_identity_id=?",
            (rom_identity_id,)).fetchone()
        return self.record_by_id(row["record_id"]) if row else None

    def clear_preferred(self, rom_identity_id) -> bool:
        with transaction(self._conn):
            cur = self._conn.execute(
                "DELETE FROM preferred_revisions WHERE rom_identity_id=?", (rom_identity_id,))
        return cur.rowcount > 0

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
            "         WHERE rom_identity_id = r.rom_identity_id) AS updated_at,"
            # media가 실제로 수집돼 있는지. 목록이 이 값을 안 세면 UI가 "media 없음"을
            # 하드코딩하게 되고, 저장은 됐는데 화면에는 영영 안 나오는 상태가 된다.
            "       (SELECT COUNT(*) FROM archive_media"
            "         WHERE rom_identity_id = r.rom_identity_id) AS media_count"
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

    def identities_matching(self, system, *, filename_norm=None, title_norm=None,
                            sha256=None, exclude_collection=None) -> list[dict]:
        """이름/해시로 **인덱스를 타고** 좁혀지는 후보만.

        `identities_in_system()`은 그 System의 Identity를 전부 돌려주므로, Gamelist처럼
        행마다 부르는 자리에서 쓰면 (보이는 행 수 x System Identity 수)만큼의 비교가
        파이썬에서 일어난다. 여기서는 세 인덱스
        (`ix_rom_identities_lookup`, `ix_games_title`, `ix_rom_identities_sha`)로
        SQL이 먼저 걸러내므로 보통 0~수 건만 돌아온다.

        Heuristic은 이름이 어긋난 뒤에 보는 것이라 이 질의로는 못 찾는다 - 그건
        `identities_in_system()`을 쓰는 deep 경로의 몫이다.
        """
        clauses, params = [], [system]
        if filename_norm:
            clauses.append("r.filename_norm=?")
            params.append(filename_norm)
        if title_norm:
            clauses.append("g.title_norm=?")
            params.append(title_norm)
        if sha256:
            clauses.append("r.sha256=?")
            params.append(sha256)
        if not clauses:
            return []

        sql = ("SELECT r.*, g.title, g.title_norm FROM rom_identities r"
               " JOIN games g ON g.game_id = r.game_id"
               f" WHERE r.system=? AND ({' OR '.join(clauses)})")
        if exclude_collection:
            sql += (" AND EXISTS (SELECT 1 FROM archive_records ar"
                    "   WHERE ar.rom_identity_id = r.rom_identity_id"
                    "     AND ar.source_collection_id <> ?)")
            params.append(exclude_collection)
        return [dict(row) for row in self._conn.execute(sql, params)]

    def put_match_link(self, collection_id, system, filename, rom_identity_id, *,
                       tier="", score=0.0, volume_file_id=None):
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO match_links (collection_id,system,filename,rom_identity_id,tier,score,"
                " created_at,volume_file_id) VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(collection_id,system,filename) DO UPDATE SET"
                "   rom_identity_id=excluded.rom_identity_id, tier=excluded.tier,"
                "   score=excluded.score, created_at=excluded.created_at,"
                "   volume_file_id=excluded.volume_file_id",
                (collection_id, system, filename, rom_identity_id, tier, float(score),
                 time.time(), volume_file_id))

    def get_match_link(self, collection_id, system, filename, *, volume_file_id=None) -> dict | None:
        """확정해 둔 Match를 찾는다. 이름이 바뀌었으면 파일 ID로 되찾아 고쳐 놓는다.

        `volume_file_id`를 넘기면 두 가지가 달라진다.

        1. **이름이 같아도 파일 ID가 다르면 남남으로 본다.** rename 뒤에 같은 이름의
           다른 파일이 생기면, 이름만 보고 옛 링크를 물려주게 되기 때문이다.
        2. 이름으로 못 찾으면 파일 ID로 찾아보고, 찾으면 **그 자리에서 filename을
           고쳐 놓는다**(자가 복구). 다음부터는 이름으로 바로 찾힌다.
        """
        row = self._conn.execute(
            "SELECT * FROM match_links WHERE collection_id=? AND system=? AND filename=?",
            (collection_id, system, filename)).fetchone()
        if row is not None:
            known = row["volume_file_id"]
            if not (volume_file_id and known and volume_file_id != known):
                return dict(row)
            # 이름은 같은데 다른 파일이다. 아래에서 파일 ID로 다시 찾는다.

        if not volume_file_id:
            return None
        found = self._conn.execute(
            "SELECT * FROM match_links WHERE collection_id=? AND volume_file_id=?",
            (collection_id, volume_file_id)).fetchone()
        if found is None:
            return None

        link = dict(found)
        if link["filename"] != filename or link["system"] != system:
            with transaction(self._conn):
                # 자리를 옮겨 적는다. 새 자리에 이름만 같은 옛 링크가 있으면 그건
                # 다른 파일의 것이므로 밀어낸다(위에서 이미 남남으로 판정했다).
                self._conn.execute(
                    "DELETE FROM match_links WHERE collection_id=? AND system=? AND filename=?",
                    (collection_id, system, filename))
                self._conn.execute(
                    "UPDATE match_links SET system=?, filename=? WHERE collection_id=?"
                    "  AND system=? AND filename=?",
                    (system, filename, collection_id, link["system"], link["filename"]))
            link["system"], link["filename"] = system, filename
        return link

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
