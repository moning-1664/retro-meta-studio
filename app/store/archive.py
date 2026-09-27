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

from app.metadata.language_priority import description_priority_sql
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

# Archive에서 직접 고친 값을 저장할 때 쓰는 가짜 source_collection_id(§40).
# 실제 Collection이 아니므로 출처 비교 목록에는 안 섞이지만, resolve_fields()의
# 우선순위(Preferred → 이 값 → 가장 최근 출처)에서는 실제 출처처럼 조회한다.
ARCHIVE_EDIT_SOURCE = "__archive__"

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
        # ROM 위치. 외부 Collection 원본과 Archive ROM 디렉토리의 보관 파일을
        # 같은 표에서 추적하며, 실제 소유권은 현재 설정된 경로 경계로 판정한다.
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
    Migration(7, (
        # ARCHIVE_REVISION_POLICY.md §6/§7/§39: "Media가 다르면 Revision을
        # 분리한다." 그런데 content_hash가 fields+frontend_raw만 봐서 Media만
        # 바뀐 Export가 새 Revision을 만들지 않았다(구현 버그,
        # tests/test_archive_revision_policy.py TCA3). media_fingerprint를
        # 따로 들고 다니며 content_hash 계산에 포함시킨다.
        "ALTER TABLE archive_records ADD COLUMN media_fingerprint TEXT NOT NULL DEFAULT ''",
    )),
    Migration(8, (
        # Revision별 Media 경로를 보존한다. archive_media는 출처별 현재 경로라서
        # 다음 Export에서 같은 slot을 갱신해도 이전 Revision의 Media를 다시 열 수 없다.
        """CREATE TABLE archive_record_media (
               record_id INTEGER NOT NULL REFERENCES archive_records(record_id) ON DELETE CASCADE,
               media_type TEXT NOT NULL,
               abs_path TEXT NOT NULL,
               size INTEGER NOT NULL DEFAULT 0,
               updated_at REAL NOT NULL,
               PRIMARY KEY (record_id, media_type)
           )""",
        # 기존 archive_media는 출처당 최신 상태였으므로 해당 최신 Revision에 연결한다.
        """INSERT OR IGNORE INTO archive_record_media (record_id,media_type,abs_path,size,updated_at)
           SELECT r.record_id,m.media_type,m.abs_path,m.size,m.updated_at
             FROM archive_media m JOIN archive_records r
               ON r.rom_identity_id=m.rom_identity_id
              AND r.source_collection_id=m.source_collection_id
              AND r.revision=(SELECT MAX(r2.revision) FROM archive_records r2
                               WHERE r2.rom_identity_id=m.rom_identity_id
                                 AND r2.source_collection_id=m.source_collection_id)""",
        "CREATE INDEX ix_record_media_record ON archive_record_media(record_id)",
    )),
    Migration(9, (
        "ALTER TABLE archive_record_media ADD COLUMN state TEXT NOT NULL DEFAULT 'present'",
    )),
    Migration(10, (
        # 같은 크기의 파일 교체도 구분하고, 내부 snapshot 경로로 옮긴 뒤에도 같은
        # media 상태의 fingerprint를 다시 만들 수 있어야 한다.
        "ALTER TABLE archive_record_media ADD COLUMN mtime_ns INTEGER NOT NULL DEFAULT 0",
    )),
    Migration(11, (
        """CREATE TABLE archive_metadata_state (
               rom_identity_id TEXT PRIMARY KEY REFERENCES rom_identities(rom_identity_id) ON DELETE CASCADE,
               cleared INTEGER NOT NULL DEFAULT 0,
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


def content_hash(fields, frontend_raw=None, media_fp="") -> str:
    """내용이 실제로 바뀌었는지 판정하는 해시(§39).

    같은 Metadata를 반복 Import해도 Revision이 늘어나지 않게 하는 것이 목적이므로,
    키 순서에 흔들리지 않도록 정렬해서 직렬화한다.

    `media_fp`는 `media_fingerprint()`가 계산한 값이다(§6/§7) - Metadata가 같아도
    Media가 바뀌면 다른 값이 되어야 새 Revision이 생긴다.
    """
    payload = json.dumps({"fields": fields or {}, "raw": frontend_raw or {}, "media": media_fp or ""},
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def media_fingerprint(media) -> str:
    """Media 상태를 판정하는 fingerprint(§6/§7). `content_hash`와 함께 써서
    Media만 바뀐 Export도 새 Revision을 만들게 한다.

    `mtime_ns`까지 포함한다 - 같은 크기의 파일로 덮어써도(예: 픽셀만 다른 같은
    바이트 수의 이미지) 실제 파일 교체는 mtime을 남긴다. 크기만 보면 이런
    교체를 "같은 상태"로 오판한다.
    """
    def fingerprint_item(item):
        state = str(item.get("state") or "present")
        media_type = str(item.get("media_type") or item.get("type") or "")
        # Collection media는 기존처럼 rel_path를 identity에 포함한다. Archive 직접
        # 편집은 내부 snapshot으로 옮기며 절대 경로가 바뀌므로 path 대신 size+mtime을
        # 쓴다. 그래야 같은 파일을 다시 붙여도 불필요한 Revision이 생기지 않는다.
        path = str(item.get("rel_path") or "")
        if state != "present":
            media_type = f"{media_type}\0{state}"
        return (media_type, path, int(item.get("size") or 0), int(item.get("mtime_ns") or 0))

    items = sorted(fingerprint_item(m) for m in (media or []))
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ArchiveStore:
    def __init__(self, path):
        self._conn = connect(path, MIGRATIONS)

    def close(self):
        self._conn.close()

    def backup_to(self, path):
        """Create a consistent single-file snapshot of the live WAL database."""
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(str(path))) as target, self._conn._lock:
            self._conn._conn.backup(target)

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
                            size=None, sha256=None, region=None, disc_info=None, title=None) -> str:
        """이 ROM의 Identity를 찾거나 만든다.

        식별 키는 **(system, rom_key)뿐이다.** rom_key는 파일명 stem을 대소문자/공백만 정리한
        값이라 "Game (USA)"와 "Game (Europe)"은 그대로 갈린다(§46) - 변종을 가르는 일은 이 키가
        이미 한다.

        **game_id는 키에 넣지 않는다.** 제목에서 나오는 값이라, 같은 ROM인데도 들어온 경로에 따라
        제목이 달라지면 Identity가 둘로 갈렸다(실사용 피드백 - ROM만 있는 폴더를 먼저 읽어
        "1941"로 잡아 두고, 나중에 메타데이터를 가져오면 "1941 (World)"라 또 하나가 생겼다).
        한 System 안에서 같은 파일명은 같은 ROM이므로 키도 그것이면 충분하다.
        """
        key = rom_key_of(filename or filename_norm)
        row = self._conn.execute(
            "SELECT rom_identity_id, game_id, filename, size, sha256, region"
            " FROM rom_identities WHERE system=? AND rom_key=?", (system, key)).fetchone()
        if row:
            self._merge_into_identity(row, game_id, size=size, sha256=sha256, region=region,
                                      title=title)
            return row["rom_identity_id"]
        rid = uuid.uuid4().hex
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO rom_identities (rom_identity_id,game_id,system,filename_norm,filename,"
                " size,sha256,region,disc_info,rom_key) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rid, game_id, system, filename_norm, filename or filename_norm,
                 size, sha256, region, disc_info, key))
        return rid

    def _merge_into_identity(self, row, game_id, *, size=None, sha256=None, region=None,
                             title=None) -> None:
        """이미 있는 Identity에 이번에 알게 된 것을 채운다. **덮어쓰지 않고 빈 칸만 메운다.**

        Game 연결은 지금 걸린 제목이 **파일명에서 나온 임시 제목일 때만** 바꾼다 - ROM만 읽어
        만들어 둔 Identity가 나중에 진짜 제목을 얻으면 그쪽으로 옮겨 가야 하고, 반대로 진짜
        제목이 이미 걸려 있는데 나중에 들어온 파일명 제목이 그것을 밀어내면 안 된다.

        `title`(이번에 알게 된 제목)도 같은 규칙으로 쓴다. `ensure_game()`은 **정규화한 제목**으로
        찾기 때문에 "1941"과 "1941 (World)"는 같은 Game에 걸린다 - 그래서 game_id는 그대로인데
        보여 줄 제목만 파일명인 채로 남는 일이 생긴다. 임시 제목일 때만 진짜 제목으로 바꾼다.
        """
        updates, params = [], []
        for column, value in (("size", size), ("sha256", sha256), ("region", region)):
            if value not in (None, "") and not row[column]:
                updates.append(f"{column}=?")
                params.append(value)
        placeholder = self._is_placeholder_game(row)
        if game_id and game_id != row["game_id"] and placeholder:
            updates.append("game_id=?")
            params.append(game_id)
        # 같은 Game에 걸려 있는데 보여 줄 제목만 파일명인 경우 - 제목을 올려 준다.
        better_title = (title or "").strip()
        if better_title and placeholder and game_id == row["game_id"]:
            with transaction(self._conn):
                self._conn.execute("UPDATE games SET title=? WHERE game_id=?",
                                   (better_title, row["game_id"]))
        if not updates:
            return
        with transaction(self._conn):
            self._conn.execute(f"UPDATE rom_identities SET {','.join(updates)}"
                               " WHERE rom_identity_id=?", (*params, row["rom_identity_id"]))

    def _is_placeholder_game(self, row) -> bool:
        """지금 걸린 Game 제목이 파일명에서 나온 것인가(= 아직 진짜 제목을 모른다)."""
        game = self._conn.execute("SELECT title FROM games WHERE game_id=?",
                                  (row["game_id"],)).fetchone()
        if game is None:
            return True
        stem = str(row["filename"] or "")
        stem = stem[:stem.rfind(".")] if "." in stem else stem
        return str(game["title"] or "").strip().lower() == stem.strip().lower()

    def get_identity(self, rom_identity_id) -> dict | None:
        row = self._conn.execute(
            "SELECT r.*, g.title, g.title_norm FROM rom_identities r"
            " JOIN games g ON g.game_id = r.game_id WHERE r.rom_identity_id=?",
            (rom_identity_id,)).fetchone()
        return dict(row) if row else None

    def find_rom_identity(self, system, filename) -> dict | None:
        row = self._conn.execute(
            "SELECT r.*, g.title, g.title_norm FROM rom_identities r"
            " JOIN games g ON g.game_id=r.game_id WHERE r.system=? AND r.rom_key=?",
            (system, rom_key_of(filename))).fetchone()
        return dict(row) if row else None

    def delete_identity(self, rom_identity_id) -> bool:
        """Archive에서 이 Identity와 DB 기록만 지운다.

        물리 파일 삭제는 호출자가 소유권을 확인한 뒤 별도로 수행한다. 이 메서드는
        Revision/출처/Media 참조/Preferred 지정만 제거한다.

        `ON DELETE CASCADE`(archive_records/archive_media/archive_rom_sources/
        preferred_revisions 모두 rom_identity_id를 참조한다)가 나머지를 정리한다 -
        연결(FK)이 켜져 있어야 하고(app/store/sqlite.py connect()), 실제로 켜져 있다.
        """
        with transaction(self._conn):
            cur = self._conn.execute(
                "DELETE FROM rom_identities WHERE rom_identity_id=?", (rom_identity_id,))
            return cur.rowcount > 0

    def metadata_is_cleared(self, rom_identity_id) -> bool:
        row = self._conn.execute(
            "SELECT cleared FROM archive_metadata_state WHERE rom_identity_id=?",
            (str(rom_identity_id),)).fetchone()
        return bool(row and row["cleared"])

    def record_ids_of_identity(self, rom_identity_id) -> list[int]:
        return [int(row["record_id"]) for row in self._conn.execute(
            "SELECT record_id FROM archive_records WHERE rom_identity_id=?",
            (str(rom_identity_id),))]

    def set_metadata_cleared(self, rom_identity_id, cleared=True) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO archive_metadata_state (rom_identity_id,cleared,updated_at)"
                " VALUES (?,?,?) ON CONFLICT(rom_identity_id) DO UPDATE SET"
                " cleared=excluded.cleared,updated_at=excluded.updated_at",
                (str(rom_identity_id), int(bool(cleared)), time.time()))

    def rom_identities_of_game(self, game_id) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM rom_identities WHERE game_id=? ORDER BY system, filename_norm", (game_id,))]

    # ------------------------------------------------------------------
    # Record / Revision
    # ------------------------------------------------------------------
    def put_record(self, rom_identity_id, source_collection_id, fields, frontend_raw=None,
                   media=None, *, retention=DEFAULT_RETENTION, created_by="import") -> tuple[int, bool]:
        """Metadata를 보관한다. 내용이 바뀐 경우에만 새 Revision을 만든다(§39).

        `media`는 이번 Export/Edit 시점의 media 목록
        (`[{"media_type","rel_path","size","mtime_ns"}]`)이다. `None`이면 "이번
        호출은 Media를 모른다"는 뜻으로, 직전 Revision의 media_fingerprint를 그대로
        이어받는다 - Archive 직접 편집(`edit()`)처럼 media 목록을 안 주는 호출이
        "Media가 전부 사라졌다"로 오판되어 새 Revision을 만들지 않도록 한다.

        `created_by`는 이 Revision이 생긴 원인이다(§17.1: "export"/"user_edit"/"import"
        등). 새 Revision의 `parent_record_id`는 같은 (identity, source) 계보에서 바로
        직전 Revision을 가리킨다(§16) - Fingerprint(content_hash)가 내용 동일성을
        판정하므로 parent는 계보 설명용일 뿐 identity 판정에는 쓰지 않는다.

        반환: (revision, created) - created=False면 같은 내용이라 아무것도 쓰지 않았다.
        """
        with transaction(self._conn):
            latest = self._conn.execute(
                "SELECT record_id, revision, content_hash, media_fingerprint FROM archive_records"
                " WHERE rom_identity_id=? AND source_collection_id=?"
                " ORDER BY revision DESC LIMIT 1",
                (rom_identity_id, source_collection_id)).fetchone()
            media_fp = (media_fingerprint(media) if media is not None
                       else (latest["media_fingerprint"] if latest else ""))
            digest = content_hash(fields, frontend_raw, media_fp)
            if latest and latest["content_hash"] == digest:
                return int(latest["revision"]), False
            revision = (int(latest["revision"]) + 1) if latest else 1
            self._conn.execute(
                "INSERT INTO archive_records (rom_identity_id,source_collection_id,revision,content_hash,"
                " fields_json,frontend_raw_json,media_fingerprint,updated_at,parent_record_id,created_by)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rom_identity_id, source_collection_id, revision, digest,
                 json.dumps(fields or {}, ensure_ascii=False),
                 json.dumps(frontend_raw or {}, ensure_ascii=False), media_fp, time.time(),
                 (latest["record_id"] if latest else None), created_by))
            record_id = int(self._conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            if media is not None:
                for item in media:
                    path = item.get("abs_path") or item.get("rel_path") or item.get("path")
                    media_type = item.get("media_type") or item.get("type")
                    state = str(item.get("state") or "present")
                    if not media_type or (state == "present" and not path):
                        continue
                    self._conn.execute(
                        "INSERT OR REPLACE INTO archive_record_media"
                        " (record_id,media_type,abs_path,size,updated_at,state,mtime_ns)"
                        " VALUES (?,?,?,?,?,?,?)",
                        (record_id, str(media_type), str(path or ""), int(item.get("size") or 0),
                         time.time(), state, int(item.get("mtime_ns") or 0)))
            elif latest:
                self._conn.execute(
                    "INSERT INTO archive_record_media"
                    " (record_id,media_type,abs_path,size,updated_at,state,mtime_ns)"
                    " SELECT ?,media_type,abs_path,size,updated_at,state,mtime_ns"
                    " FROM archive_record_media"
                    " WHERE record_id=?",
                    (record_id, int(latest["record_id"])))
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

    def media_of_revision(self, record_id) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT media_type,abs_path,size,updated_at,state,mtime_ns FROM archive_record_media"
            " WHERE record_id=? ORDER BY media_type", (record_id,))]

    def record_ids_with_media(self) -> list[int]:
        """Revision media가 있는 모든 record ID. 설정 적용 시 내부 보관에 쓴다."""
        return [int(r["record_id"]) for r in self._conn.execute(
            "SELECT DISTINCT record_id FROM archive_record_media"
            " WHERE state='present' AND abs_path<>'' ORDER BY record_id")]

    def update_revision_media_path(self, record_id, media_type, abs_path):
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE archive_record_media SET abs_path=? WHERE record_id=? AND media_type=?",
                (str(abs_path), record_id, media_type))

    def mark_revision_media_cleared(self, record_id, media_type):
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO archive_record_media"
                " (record_id,media_type,abs_path,size,updated_at,state,mtime_ns)"
                " VALUES (?,?,?,0,?,'cleared',0)",
                (record_id, media_type, "", time.time()))

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

    @staticmethod
    def _filled(value) -> bool:
        return value is not None and str(value).strip() != ""

    def resolve_fields(self, rom_identity_id) -> tuple[dict, dict]:
        """이 항목에 적용할 Metadata(desc/genre/rating 등).

        우선순위(ARCHIVE_REVISION_POLICY.md §9, §14): Preferred → (Archive에서
        직접 고친 값) → 출처들의 병합. `app/archive/service.py`의 Detail 조회와
        `list_rows()`가 같은 규칙을 쓴다 - 여기서만 다른 값을 보여주면 목록과
        상세가 어긋난다.

        **출처가 여럿이면 먼저 들어온 값이 이기고, 빈 칸만 나중 것이 채운다**(사용자 결정 -
        "컨플릭이 아니면 먼저 들어온 값이 이김"). 통째로 최신 것을 고르던 예전 방식은,
        나중에 들어온 빈약한 출처가 앞서 들어온 좋은 값을 통째로 밀어냈다.

        **순서를 정할 때 record_id를 함께 본다.** `updated_at`만 보면 두 출처가 같은
        시계 눈금 안에 기록됐을 때(Windows의 time()은 해상도가 ~15.6ms라 흔하다) 순서가
        임의로 갈려 같은 입력에 같은 답이 나오지 않는다 - 실제로 "ROM만 먼저 읽고 곧바로
        메타데이터를 수집"하면 두 출처의 시각이 같아져 제목과 장르가 실행할 때마다 달라졌다.

        **파일명에서 나온 제목은 진짜 제목에 자리를 내준다**(사용자 결정). ROM만 읽어
        만들어 둔 출처의 제목은 파일명 그대로라, 그것이 먼저 들어왔다는 이유로 이기면
        `1941`이 `1941 (World)`를 영영 밀어낸다.
        """
        return self.resolve_fields_many([rom_identity_id]).get(str(rom_identity_id), ({}, {}))

    def resolve_fields_many(self, rom_identity_ids) -> dict[str, tuple[dict, dict]]:
        """여러 Archive 행의 effective metadata를 고정된 수의 query로 계산한다.

        목록 한 페이지에서 ``resolve_fields()``를 행마다 호출하면 revision 수와
        무관하게 행당 여러 query가 생긴다. 여기서는 latest source, preferred,
        identity를 한 번씩 읽고 같은 병합 규칙을 Python에서 적용한다.
        """
        ids = list(dict.fromkeys(str(value) for value in (rom_identity_ids or []) if value))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        latest_rows = self._conn.execute(
            "SELECT ar.* FROM archive_records ar"
            " JOIN (SELECT rom_identity_id,source_collection_id,MAX(revision) AS revision"
            " FROM archive_records WHERE rom_identity_id IN (" + placeholders + ")"
            " GROUP BY rom_identity_id,source_collection_id) latest"
            " ON latest.rom_identity_id=ar.rom_identity_id"
            " AND latest.source_collection_id=ar.source_collection_id"
            " AND latest.revision=ar.revision",
            ids).fetchall()
        preferred_rows = self._conn.execute(
            "SELECT ar.* FROM preferred_revisions p"
            " JOIN archive_records ar ON ar.record_id=p.record_id"
            " WHERE p.rom_identity_id IN (" + placeholders + ")",
            ids).fetchall()
        identity_rows = self._conn.execute(
            "SELECT r.rom_identity_id,r.filename,COALESCE(m.cleared,0) AS metadata_cleared"
            " FROM rom_identities r LEFT JOIN archive_metadata_state m"
            " ON m.rom_identity_id=r.rom_identity_id"
            " WHERE r.rom_identity_id IN (" + placeholders + ")",
            ids).fetchall()

        sources_by_id = {rid: [] for rid in ids}
        for row in latest_rows:
            sources_by_id.setdefault(str(row["rom_identity_id"]), []).append(self._record_dict(row))
        preferred_by_id = {
            str(row["rom_identity_id"]): self._record_dict(row) for row in preferred_rows
        }
        filename_by_id = {
            str(row["rom_identity_id"]): str(row["filename"] or "") for row in identity_rows
        }
        cleared_ids = {str(row["rom_identity_id"]) for row in identity_rows
                       if row["metadata_cleared"]}
        return {
            rid: ({}, {}) if rid in cleared_ids else self._resolve_loaded_fields(
                sources_by_id.get(rid, []), preferred_by_id.get(rid), filename_by_id.get(rid, ""))
            for rid in ids
        }

    def _resolve_loaded_fields(self, all_sources, preferred, filename) -> tuple[dict, dict]:
        edited = next((source for source in all_sources
                       if source["source_collection_id"] == ARCHIVE_EDIT_SOURCE), None)

        # **fallback은 "다른 출처"에서만 한다 - 고른 판 자신의 이력에서는 하지 않는다.**
        #
        # 같은 출처의 Revision은 시간순 이력이라, 옛 판을 고른 것은 "그 시점으로
        # 되돌리고 싶다"는 뜻이다. 여기서 나중 판의 값을 채워 넣으면 그 되돌리기를
        # 무효로 만든다(tests/test_archive_revision_policy.py TC-A4 - R3에서 더한
        # 설명이 R2를 골랐는데도 따라왔다). 반면 **다른 Collection**이 가진 값은
        # 시간이 아니라 출처가 다른 것이라, 고른 판에 없으면 채워 주는 편이 맞다
        # (Invariant 5-6 BestEffort).
        #
        # 편집 기록도 출처가 아니다 - 맨 위 층에서 따로 덮는다(_with_edit). 여기 섞으면
        # 같은 값을 두 번 얹는 꼴이 되고, 출처 병합 순서까지 흔든다.
        skip = {ARCHIVE_EDIT_SOURCE}
        if preferred:
            skip.add(preferred["source_collection_id"])
        sources = sorted((s for s in all_sources
                          if s["source_collection_id"] not in skip),
                         key=lambda s: (s["updated_at"], s["record_id"]))
        if not sources:
            base, raw = ({}, {})
            if preferred:
                base, raw = dict(preferred["fields"] or {}), preferred["frontend_raw"] or {}
            return self._with_edit(base, raw, edited)

        stem = str(filename or "")
        stem = (stem[:stem.rfind(".")] if "." in stem else stem).strip().lower()

        def from_filename(value) -> bool:
            return bool(stem) and str(value or "").strip().lower() == stem

        merged, raw = {}, {}
        for source in sources:
            for key, value in (source["fields"] or {}).items():
                if not self._filled(value):
                    continue
                current = merged.get(key)
                # 빈 칸을 채우거나, 파일명에서 나온 제목을 진짜 제목으로 바꾼다.
                if not self._filled(current) or (key == "name" and from_filename(current)
                                            and not from_filename(value)):
                    merged[key] = value
            if not raw:
                raw = source["frontend_raw"] or {}

        # **고른 판(Preferred)은 "그 판 전체"가 아니라 "그 판이 가진 값"이 이긴다**
        # (ARCHIVE_REVISION_POLICY.md Invariant 5-6, BestEffort). 예전에는 Preferred가
        # 있으면 그 레코드를 통째로 돌려줘서, 고른 판에 없는 값(설명 등)이 다른 출처에
        # 멀쩡히 있어도 화면과 Archive->Collection Import에서 통째로 사라졌다
        # (실사용 확인 - 버전을 고르는 순간 desc가 빈 값이 됐다).
        #
        # media는 이미 이 방식이다(app/archive/projection.py effective_media - media
        # type마다 Preferred 출처를 먼저 보고 없으면 최신으로 내려간다). 같은 규칙을
        # metadata에도 맞춘다.
        #
        # 출처 쪽에는 "일부러 지웠다"가 없다 - gamelist에 값이 없다는 것은 그 Collection이
        # 그 정보를 모른다는 뜻(ABSENT)이지 삭제 의사가 아니다. 그래서 여기서는 **값이
        # 찼는지**로 덮는다. 사용자가 일부러 지운 값(CLEARED)은 편집 층이 키 유무로
        # 따로 지킨다(_with_edit).
        if preferred:
            for key, value in (preferred["fields"] or {}).items():
                if self._filled(value):
                    merged[key] = value
            raw = preferred["frontend_raw"] or raw
        return self._with_edit(merged, raw, edited)

    def rom_sources_many(self, rom_identity_ids) -> dict[str, list[dict]]:
        ids = list(dict.fromkeys(str(value) for value in (rom_identity_ids or []) if value))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        result = {rid: [] for rid in ids}
        for row in self._conn.execute(
                "SELECT * FROM archive_rom_sources WHERE rom_identity_id IN (" + placeholders + ")"
                " ORDER BY updated_at DESC", ids):
            result.setdefault(str(row["rom_identity_id"]), []).append(dict(row))
        return result

    @staticmethod
    def _with_edit(base_fields, base_raw, edited):
        """Archive에서 직접 고친 값을 바탕 값 **위에 덮는다**(통째로 바꾸지 않는다).

        예전에는 Preferred가 있으면 거기서 곧장 돌려주고 편집 기록은 보지도 않았다.
        그래서 **Preferred를 고른 항목은 Archive에서 아무리 고쳐도 화면이 그대로였다**
        (실사용 리포트로 확인 - 저장은 됐다고 하는데 값이 안 바뀜). Preferred는 "어느
        출처를 믿을지"를 고르는 것이고 편집은 "내가 정한 값"이라 층위가 다르다 - 편집이
        바탕 위에 얹히는 것이 맞다.

        덮는 기준은 **키가 있느냐**지 값이 찼느냐가 아니다. 화면의 저장(handleSaveDetail)은
        전체 필드를 통째로 보내므로, 빈 값으로 온 키는 "사용자가 일부러 지웠다"는 뜻이라
        그대로 지켜야 한다. 반대로 키 자체가 없으면 이번 편집이 건드리지 않은 값이므로
        바탕 것이 그대로 보인다(일부 필드만 고치는 호출이 나머지를 날리지 않는다).

        `frontend_raw`는 편집 기록에 없으면(직접 편집은 raw를 만들지 않는다) 바탕 것을
        유지한다 - 예전에는 편집 한 번에 Frontend 고유 필드가 통째로 사라졌다.
        """
        if not edited:
            return base_fields, base_raw
        merged = {**(base_fields or {}), **(edited["fields"] or {})}
        return merged, (edited["frontend_raw"] or base_raw)

    def clear_preferred(self, rom_identity_id) -> bool:
        with transaction(self._conn):
            cur = self._conn.execute(
                "DELETE FROM preferred_revisions WHERE rom_identity_id=?", (rom_identity_id,))
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # 목록 조회 (Archive Gamelist - 스펙 §43)
    # ------------------------------------------------------------------
    def list_rows(self, *, search=None, systems=None, limit=None, offset=0,
                  only_ids=None, priority=None, order="title", descending=False) -> list[dict]:
        """Archive도 일반 Collection과 같은 Gamelist로 보여준다(§43).

        Collection 목록과 같은 모양으로 돌려줘서 UI가 같은 렌더링을 쓰게 한다.
        """
        where, params = self._row_filter(search, systems, only_ids)
        effective_media_exists = (
            "SELECT 1 FROM archive_media pm"
            " WHERE pm.rom_identity_id=r.rom_identity_id"
            " AND NOT EXISTS (SELECT 1 FROM archive_records er"
            " JOIN archive_record_media erm ON erm.record_id=er.record_id"
            " WHERE er.rom_identity_id=r.rom_identity_id"
            " AND er.source_collection_id='__archive__'"
            " AND er.revision=(SELECT MAX(er2.revision) FROM archive_records er2"
            " WHERE er2.rom_identity_id=r.rom_identity_id"
            " AND er2.source_collection_id='__archive__')"
            " AND erm.media_type=pm.media_type AND erm.state='cleared')"
        )
        effective_media_types = effective_media_exists.replace(
            "SELECT 1 FROM archive_media pm",
            "SELECT GROUP_CONCAT(DISTINCT pm.media_type) FROM archive_media pm", 1)
        metadata_cleared = ("EXISTS (SELECT 1 FROM archive_metadata_state ms"
                            " WHERE ms.rom_identity_id=r.rom_identity_id AND ms.cleared=1)")
        priority_order = {
            "rom": "CASE WHEN EXISTS (SELECT 1 FROM archive_rom_sources s"
                   " WHERE s.rom_identity_id=r.rom_identity_id) THEN 0 ELSE 1 END,",
            "metadata": f"CASE WHEN NOT {metadata_cleared} AND EXISTS (SELECT 1 FROM archive_records ar"
                        " JOIN json_each(ar.fields_json) jf"
                        " WHERE ar.rom_identity_id=r.rom_identity_id"
                        " AND jf.value IS NOT NULL AND trim(CAST(jf.value AS TEXT))<>'')"
                        " THEN 0 ELSE 1 END,",
            "media": f"CASE WHEN EXISTS ({effective_media_exists}) THEN 0 ELSE 1 END,",
        }.get(priority, "")
        if priority in ("desc_ko", "desc_en"):
            def desc_from(alias):
                return f"NULLIF(json_extract({alias}.fields_json, '$.desc'), '')"

            # Direct Archive edits use key presence: an explicit empty desc is
            # CLEARED and must not fall through to a source description.
            edited_desc = ("(SELECT CASE WHEN json_type(e.fields_json, '$.desc') IS NOT NULL"
                           " THEN COALESCE(json_extract(e.fields_json, '$.desc'), '') END"
                           " FROM archive_records e"
                           " WHERE e.rom_identity_id=r.rom_identity_id"
                           " AND e.source_collection_id='__archive__'"
                           " ORDER BY e.revision DESC LIMIT 1)")
            preferred_desc = (f"(SELECT {desc_from('p')} FROM preferred_revisions pr"
                              " JOIN archive_records p ON p.record_id=pr.record_id"
                              " WHERE pr.rom_identity_id=r.rom_identity_id)")
            source_desc = (f"(SELECT {desc_from('s')} FROM archive_records s"
                           " WHERE s.rom_identity_id=r.rom_identity_id"
                           " AND s.source_collection_id<>'__archive__'"
                           f" AND {desc_from('s')} IS NOT NULL"
                           " ORDER BY s.updated_at,s.record_id LIMIT 1)")
            resolved_desc = (f"CASE WHEN {metadata_cleared} THEN '' ELSE"
                             f" COALESCE({edited_desc},{preferred_desc},{source_desc},'') END")
            priority_order = description_priority_sql(resolved_desc, priority) + ","
        # Keep the sort in SQL before LIMIT/OFFSET, as Collection does. Sorting
        # each loaded page in the UI gives a different order while scrolling.
        field = {"desc": "desc", "region": "region", "genre": "genre",
                 "rating": "rating", "favorite": "favorite", "title": "name"}.get(order)
        if order == "filename":
            sort_value = "LOWER(r.filename)"
        elif order == "system":
            sort_value = "LOWER(r.system)"
        elif field:
            def extracted(alias):
                payload = "frontend_raw_json" if field == "favorite" else "fields_json"
                return f"NULLIF(json_extract({alias}.{payload}, '$.{field}'), '')"
            edited = (f"(SELECT {extracted('e')} FROM archive_records e"
                      " WHERE e.rom_identity_id=r.rom_identity_id"
                      " AND e.source_collection_id='__archive__'"
                      " ORDER BY e.revision DESC LIMIT 1)")
            preferred = (f"(SELECT {extracted('p')} FROM preferred_revisions pr"
                         " JOIN archive_records p ON p.record_id=pr.record_id"
                         " WHERE pr.rom_identity_id=r.rom_identity_id)")
            source = (f"(SELECT {extracted('s')} FROM archive_records s"
                      " WHERE s.rom_identity_id=r.rom_identity_id"
                      " AND s.source_collection_id<>'__archive__'"
                      " ORDER BY s.updated_at,s.record_id LIMIT 1)")
            fallback = "g.title" if order == "title" else "''"
            # The games title is the ordinary source title; using a correlated
            # source lookup for every row made the default Archive page slow.
            sort_value = (f"COALESCE({edited},{preferred},g.title)" if order == "title"
                          else f"COALESCE({edited},{preferred},{source},{fallback})")
            if order in ("rating", "favorite"):
                sort_value = f"CAST({sort_value} AS REAL)"
            else:
                sort_value = f"LOWER({sort_value})"
            sort_value = f"CASE WHEN {metadata_cleared} THEN '' ELSE {sort_value} END"
        else:
            sort_value = "LOWER(g.title)"
        empty_last = f"({sort_value} = ''), " if order in ("desc", "region", "genre") else ""
        sort_order = f"{priority_order}{empty_last}{sort_value} {'DESC' if descending else 'ASC'}, r.filename"
        sql = (
            "SELECT r.rom_identity_id, r.game_id, r.system, r.filename, r.region,"
            "       g.title, g.title_norm,"
            f"       {metadata_cleared} AS metadata_cleared,"
            "       (SELECT COUNT(DISTINCT source_collection_id) FROM archive_records"
            "         WHERE rom_identity_id = r.rom_identity_id) AS source_count,"
            "       (SELECT MAX(updated_at) FROM archive_records"
            "         WHERE rom_identity_id = r.rom_identity_id) AS updated_at,"
            # media가 실제로 수집돼 있는지. 목록이 이 값을 안 세면 UI가 "media 없음"을
            # 하드코딩하게 되고, 저장은 됐는데 화면에는 영영 안 나오는 상태가 된다.
            f"       ({effective_media_types}) AS media_types,"
            # ROM 위치가 기록돼 있는지(실제 파일 존재는 실행할 때 확인한다 - 목록에서
            # 수천 개를 NAS까지 조회하면 목록이 멈춘다).
            "       (SELECT COUNT(*) FROM archive_rom_sources"
            "         WHERE rom_identity_id = r.rom_identity_id) AS rom_count"
            f" FROM rom_identities r JOIN games g ON g.game_id = r.game_id{where}"
            f" ORDER BY {sort_order}"
        )
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = [*params, int(limit), int(offset)]
        return [dict(r) for r in self._conn.execute(sql, params)]

    def count_rows(self, *, search=None, systems=None, only_ids=None) -> int:
        where, params = self._row_filter(search, systems, only_ids)
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM rom_identities r"
            f" JOIN games g ON g.game_id = r.game_id{where}", params).fetchone()
        return int(row["n"])

    @staticmethod
    def _row_filter(search, systems, only_ids=None):
        clauses, params = [], []
        if only_ids is not None:
            # 빈 목록이면 **아무것도 없다** - 조건을 빼 버리면 전체가 나와서 필터가 거꾸로 동작한다.
            ids = list(only_ids)
            if not ids:
                return " WHERE 1=0", []
            clauses.append(f"r.rom_identity_id IN ({','.join('?' * len(ids))})")
            params.extend(ids)
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

    def delete_rom_source(self, rom_identity_id, source_collection_id, abs_path=None) -> bool:
        """Forget one ROM location without deleting the file itself.

        ``source_collection_id`` is normally unique per Archive identity.  The
        optional path guard keeps a stale UI request from removing a source
        whose location changed after ownership was calculated.
        """
        sql = ("DELETE FROM archive_rom_sources WHERE rom_identity_id=?"
               " AND source_collection_id=?")
        params = [rom_identity_id, source_collection_id]
        if abs_path is not None:
            sql += " AND abs_path=?"
            params.append(str(abs_path))
        with transaction(self._conn):
            cur = self._conn.execute(sql, params)
        return cur.rowcount > 0

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

    def delete_media_ref(self, rom_identity_id, media_type, source_collection_id) -> bool:
        """Remove one source's reference without touching its media file."""
        with transaction(self._conn):
            cur = self._conn.execute(
                "DELETE FROM archive_media WHERE rom_identity_id=? AND media_type=?"
                " AND source_collection_id=?",
                (rom_identity_id, media_type, source_collection_id))
        return cur.rowcount > 0
