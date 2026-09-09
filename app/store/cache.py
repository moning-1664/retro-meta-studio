"""
app/store/cache.py
===================
cache/<collection-id>.db - 파일시스템 Scan 결과.

Cache는 **언제든 버리고 다시 만들 수 있어야 한다**(스펙 §66). 실제 파일 시스템이
언제나 Source of Physical Truth이고, Cache는 Collection을 빠르게 다시 여는 수단일
뿐이다(§62). 그래서 스키마 버전이 안 맞으면 마이그레이션하지 않고 그냥 지우고
Full Scan으로 복구한다.

이전 프로젝트의 스캐너는 같은 증분 판정을 하면서도 결과를 **런타임 메모리에만**
들고 있었다. 그래서 앱을 다시 켜면 매번 Full Scan이었다. 여기서는 그 결과를
그대로 이 DB에 눕힌다.

목록 조회 성능이 이 파일의 존재 이유다. title/title_norm/has_metadata/has_media를
`roms`에 직접 컬럼으로 두어 정렬·필터·검색·페이징을 전부 SQL로 처리한다. 별도
비정규화 테이블을 두지 않으므로 동기화가 어긋날 여지도 없다.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.store.sqlite import Migration, connect, transaction, user_version

SCHEMA_VERSION = 1

MIGRATIONS = (
    Migration(1, (
        # scan_meta는 증분 판정용 System별 시그니처("sig:<system>")도 담는다.
        # ROM 수천 개를 매번 stat 하지 않고 디렉터리 mtime만 보고 "이 시스템은
        # 통째로 변경 없음"을 판정하기 위한 것이다.
        "CREATE TABLE scan_meta (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)",
        """CREATE TABLE roms (
               rom_uid INTEGER PRIMARY KEY AUTOINCREMENT,
               system TEXT NOT NULL,
               filename TEXT NOT NULL,
               rel_path TEXT NOT NULL DEFAULT '',
               storage_id TEXT NOT NULL DEFAULT 'internal',
               size INTEGER NOT NULL DEFAULT 0,
               mtime_ns INTEGER NOT NULL DEFAULT 0,
               sha256 TEXT,
               volume_file_id TEXT,
               title TEXT NOT NULL DEFAULT '',
               title_norm TEXT NOT NULL DEFAULT '',
               has_metadata INTEGER NOT NULL DEFAULT 0,
               has_media INTEGER NOT NULL DEFAULT 0,
               -- 물리 ROM 파일이 실제로 있는지. ES-DE는 gamelist/media만 있고 ROM이
               -- 없는 metadata-only 항목이 정상적으로 존재할 수 있다.
               present INTEGER NOT NULL DEFAULT 1,
               UNIQUE (system, filename)
           )""",
        "CREATE INDEX ix_roms_sort ON roms(system, title_norm)",
        "CREATE INDEX ix_roms_title ON roms(title_norm)",
        "CREATE INDEX ix_roms_storage ON roms(storage_id)",
        """CREATE TABLE metadata (
               rom_uid INTEGER PRIMARY KEY REFERENCES roms(rom_uid) ON DELETE CASCADE,
               fields_json TEXT NOT NULL DEFAULT '{}',
               -- 공통 모델로 옮기면서 버려질 Frontend 고유 필드의 원본. Round-trip
               -- 손실 방지(스펙 §50-51)의 저장소다.
               frontend_raw_json TEXT NOT NULL DEFAULT '{}',
               content_hash TEXT
           )""",
        """CREATE TABLE media (
               rom_uid INTEGER NOT NULL REFERENCES roms(rom_uid) ON DELETE CASCADE,
               media_type TEXT NOT NULL,
               rel_path TEXT NOT NULL,
               size INTEGER NOT NULL DEFAULT 0,
               mtime_ns INTEGER NOT NULL DEFAULT 0,
               PRIMARY KEY (rom_uid, media_type)
           )""",
        # storage_id는 ROM이 놓인 Storage, media_storage_id는 media가 놓인
        # Storage다. ES-DE는 ROM만 System별 Storage를 따라가고 media는 Collection
        # root에 남기 때문에 둘이 다를 수 있다.
        """CREATE TABLE system_stats (
               system TEXT PRIMARY KEY,
               storage_id TEXT NOT NULL DEFAULT 'internal',
               media_storage_id TEXT NOT NULL DEFAULT 'internal',
               rom_count INTEGER NOT NULL DEFAULT 0,
               rom_bytes INTEGER NOT NULL DEFAULT 0,
               media_count INTEGER NOT NULL DEFAULT 0,
               media_bytes INTEGER NOT NULL DEFAULT 0,
               missing_metadata INTEGER NOT NULL DEFAULT 0,
               missing_media INTEGER NOT NULL DEFAULT 0
           )""",
    )),
    Migration(2, (
        # 즐겨찾기는 사용자가 직접 켜고 끄는 값이라 정렬·필터 대상이다. `frontend_raw`
        # 안을 문자열로 뒤지면 SQL이 다루지 못하고 값이 false인 경우까지 걸린다.
        "ALTER TABLE roms ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0",
    )),
)


class CacheStore:
    def __init__(self, path):
        self.path = Path(path)
        self._conn = connect(self.path, MIGRATIONS)

    @classmethod
    def open_for_collection(cls, cache_dir, collection_id):
        return cls(Path(cache_dir) / f"{collection_id}.db")

    def close(self):
        self._conn.close()

    def reset(self):
        """Cache 전체를 비운다. 스키마 불일치/손상 시 Full Scan 복구 경로(§66)."""
        with transaction(self._conn):
            for table in ("media", "metadata", "roms", "system_stats", "scan_meta"):
                self._conn.execute(f"DELETE FROM {table}")

    @property
    def schema_version(self) -> int:
        return user_version(self._conn)

    # ------------------------------------------------------------------
    # scan 메타 / 디렉터리 시그니처
    # ------------------------------------------------------------------
    def get_meta(self, key, default=None):
        row = self._conn.execute("SELECT value_json FROM scan_meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else default

    def set_meta(self, key, value):
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO scan_meta (key,value_json) VALUES (?,?)"
                " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (key, json.dumps(value, ensure_ascii=False)))

    def get_system_sig(self, system):
        """System 하나의 증분 판정 시그니처. 스캐너가 정의한 구조를 그대로 보관한다."""
        return self.get_meta(f"sig:{system}")

    def set_system_sig(self, system, sig):
        self.set_meta(f"sig:{system}", sig)

    def forget_system(self, system):
        """System이 사라졌을 때 캐시에서 제거한다."""
        with transaction(self._conn):
            self._conn.execute("DELETE FROM roms WHERE system=?", (system,))
            self._conn.execute("DELETE FROM system_stats WHERE system=?", (system,))
            self._conn.execute("DELETE FROM scan_meta WHERE key=?", (f"sig:{system}",))

    # ------------------------------------------------------------------
    # 스캔 결과 반영
    # ------------------------------------------------------------------
    def replace_system(self, system, rows, media_types=None):
        """한 System의 스캔 결과를 통째로 교체한다.

        증분 스캔은 "변경된 System만 다시 읽는다"가 기본 단위이므로, 갱신도 System
        단위로 원자적으로 바꾸는 것이 가장 단순하고 안전하다. 부분 갱신을 지원하면
        삭제된 파일을 지우는 경로를 따로 관리해야 한다.

        **`media_types`를 주면 그 타입의 media만 갈아끼운다.** 스캐너는 체감 속도를
        위해 "커버 먼저, 비디오 나중"으로 나눠 읽는데, 그때 `rows`에는 이번에 읽은
        타입의 media만 들어 있다. 그대로 통째로 교체하면 **읽지도 않은 비디오/휠
        정보가 캐시에서 사라진다** - 사용자에게는 "비디오가 갑자기 없어졌다"로 보이고,
        그 상태로 Plan을 만들면 비디오가 복사 대상에서 통째로 빠진다.

        그래서 이번에 건드리지 않는 타입의 행은 파일명 기준으로 들고 있다가 다시
        넣는다. 읽은 타입 안에서 사라진 파일은 그대로 사라진다 - "아무것도 안 지운다"가
        답이 아니라 "읽은 것만 지운다"가 답이다.

        rows: {"filename","rel_path","storage_id","size","mtime_ns","sha256",
               "volume_file_id","title","title_norm","has_metadata","has_media",
               "present","fields","frontend_raw","content_hash",
               "media":[{"media_type","rel_path","size","mtime_ns"}]} 의 목록
        """
        with transaction(self._conn):
            carried = ({} if media_types is None
                       else self._media_of_other_types(system, media_types))
            self._conn.execute("DELETE FROM roms WHERE system=?", (system,))
            for row in rows:
                cur = self._conn.execute(
                    "INSERT INTO roms (system,filename,rel_path,storage_id,size,mtime_ns,sha256,"
                    " volume_file_id,title,title_norm,has_metadata,has_media,present,favorite)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (system, row["filename"], row.get("rel_path", ""), row.get("storage_id", "internal"),
                     int(row.get("size", 0)), int(row.get("mtime_ns", 0)), row.get("sha256"),
                     row.get("volume_file_id"), row.get("title", ""), row.get("title_norm", ""),
                     1 if row.get("has_metadata") else 0,
                     1 if (row.get("has_media") or carried.get(row["filename"])) else 0,
                     1 if row.get("present", True) else 0,
                     1 if row.get("favorite") else 0))
                rom_uid = cur.lastrowid
                if row.get("fields") is not None or row.get("frontend_raw") is not None:
                    self._conn.execute(
                        "INSERT INTO metadata (rom_uid,fields_json,frontend_raw_json,content_hash) VALUES (?,?,?,?)",
                        (rom_uid, json.dumps(row.get("fields") or {}, ensure_ascii=False),
                         json.dumps(row.get("frontend_raw") or {}, ensure_ascii=False),
                         row.get("content_hash")))
                for m in (row.get("media") or []) + carried.get(row["filename"], []):
                    self._conn.execute(
                        "INSERT INTO media (rom_uid,media_type,rel_path,size,mtime_ns) VALUES (?,?,?,?,?)",
                        (rom_uid, m["media_type"], m.get("rel_path", ""),
                         int(m.get("size", 0)), int(m.get("mtime_ns", 0))))

    def _media_of_other_types(self, system, media_types):
        """이번 스캔이 건드리지 않는 media type의 행. {filename: [media, ...]}"""
        scanned = set(media_types)
        kept: dict[str, list] = {}
        for row in self._conn.execute(
                "SELECT r.filename, m.media_type, m.rel_path, m.size, m.mtime_ns"
                "  FROM media m JOIN roms r ON r.rom_uid = m.rom_uid"
                " WHERE r.system = ?", (system,)):
            if row["media_type"] in scanned:
                continue
            kept.setdefault(row["filename"], []).append(dict(row))
        return kept

    def set_system_stats(self, system, storage_id, media_storage_id=None, **counts):
        fields = {"rom_count": 0, "rom_bytes": 0, "media_count": 0, "media_bytes": 0,
                  "missing_metadata": 0, "missing_media": 0}
        fields.update({k: int(v) for k, v in counts.items() if k in fields})
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO system_stats (system,storage_id,media_storage_id,rom_count,rom_bytes,"
                " media_count,media_bytes,missing_metadata,missing_media) VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(system) DO UPDATE SET storage_id=excluded.storage_id,"
                " media_storage_id=excluded.media_storage_id,"
                " rom_count=excluded.rom_count, rom_bytes=excluded.rom_bytes,"
                " media_count=excluded.media_count, media_bytes=excluded.media_bytes,"
                " missing_metadata=excluded.missing_metadata, missing_media=excluded.missing_media",
                (system, storage_id, media_storage_id or storage_id, fields["rom_count"],
                 fields["rom_bytes"], fields["media_count"], fields["media_bytes"],
                 fields["missing_metadata"], fields["missing_media"]))

    def system_stats(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM system_stats ORDER BY system")]

    def storage_usage(self) -> dict[str, int]:
        """Storage별 실사용 바이트(Actual). Plan 계산의 기준값(§82).

        ROM과 media를 각자 실제로 놓인 Storage에 더한다 - 둘은 다른 Storage일 수 있다.
        """
        usage: dict[str, int] = {}
        for row in self._conn.execute(
                "SELECT storage_id, media_storage_id, rom_bytes, media_bytes FROM system_stats"):
            usage[row["storage_id"]] = usage.get(row["storage_id"], 0) + int(row["rom_bytes"] or 0)
            key = row["media_storage_id"] or row["storage_id"]
            usage[key] = usage.get(key, 0) + int(row["media_bytes"] or 0)
        return usage

    # ------------------------------------------------------------------
    # 목록 조회 (정렬/필터/페이징 전부 SQL)
    # ------------------------------------------------------------------
    #: Header를 눌러 정렬할 수 있는 컬럼. 화면이 이 이름을 그대로 쓴다.
    ORDERS = {
        "title": "r.title_norm", "filename": "r.filename", "size": "r.size",
        "system": "r.system", "favorite": "r.favorite",
        "desc": "LOWER(COALESCE(json_extract(m.fields_json,'$.desc'),''))",
        "region": "LOWER(COALESCE(json_extract(m.fields_json,'$.region'),''))",
        "genre": "LOWER(COALESCE(json_extract(m.fields_json,'$.genre'),''))",
        "rating": "CAST(COALESCE(json_extract(m.fields_json,'$.rating'),0) AS REAL)",
    }

    def query_rows(self, *, systems=None, storage_ids=None, search=None, order="title",
                   descending=False, limit=None, offset=0, favorites_only=False) -> list[dict]:
        """목록 한 페이지. **정렬·필터·검색은 전부 SQL이 한다.**

        Description/Region/Rating/Genre는 `metadata.fields_json` 안에 있어 JOIN해서
        함께 꺼낸다 - 행마다 따로 물어보면 1,500개 목록에서 1,500번을 더 묻게 된다.
        """
        where, params = self._build_where(systems, storage_ids, search, favorites_only, "r.")
        order_col = self.ORDERS.get(order, "r.title_norm")
        # sha256을 함께 싣는다 - Match 뱃지가 목록 경로에서 계산되는데, 해시가 빠지면
        # 뱃지와 Match 다이얼로그가 서로 다른 근거로 판정하게 된다.
        sql = (f"SELECT r.rom_uid,r.system,r.filename,r.rel_path,r.storage_id,r.size,"
               f" r.title,r.sha256,r.has_metadata,r.has_media,r.present,r.favorite,"
               f" json_extract(m.fields_json,'$.desc') AS desc_text,"
               f" json_extract(m.fields_json,'$.region') AS region,"
               f" json_extract(m.fields_json,'$.genre') AS genre,"
               f" json_extract(m.fields_json,'$.rating') AS rating"
               f" FROM roms r LEFT JOIN metadata m ON m.rom_uid = r.rom_uid{where}"
               f" ORDER BY {order_col} {'DESC' if descending else 'ASC'}, r.filename")
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = [*params, int(limit), int(offset)]
        return [dict(r) for r in self._conn.execute(sql, params)]

    def count_by_system(self) -> dict[str, int]:
        """System별 **게임 수**. 좌측 네비게이션과 목록이 같은 것을 세게 하기 위한 것.

        `system_stats.rom_count`를 쓰면 안 된다 - 그것은 물리 ROM 파일 수라서,
        gamelist와 media만 있고 ROM이 없는 Collection(ES-DE에서 정상이다)에서는
        전부 0이 된다. 실제로 사용자의 백업을 열었을 때 목록에는 1,539개가 뜨는데
        네비게이션은 28개 System이 전부 0으로 표시됐다.
        """
        return {row["system"]: int(row["n"]) for row in self._conn.execute(
            "SELECT system, COUNT(*) AS n FROM roms GROUP BY system")}

    def count_rows(self, *, systems=None, storage_ids=None, search=None,
                   favorites_only=False) -> int:
        where, params = self._build_where(systems, storage_ids, search, favorites_only)
        row = self._conn.execute(f"SELECT COUNT(*) AS n FROM roms{where}", params).fetchone()
        return int(row["n"])

    @staticmethod
    def _build_where(systems, storage_ids, search, favorites_only=False, prefix=""):
        """`prefix`는 JOIN이 있는 쿼리에서 컬럼이 어느 표의 것인지 밝히기 위한 것이다."""
        clauses, params = [], []
        if systems:
            clauses.append(f"{prefix}system IN ({','.join('?' * len(systems))})")
            params.extend(systems)
        if storage_ids:
            clauses.append(f"{prefix}storage_id IN ({','.join('?' * len(storage_ids))})")
            params.extend(storage_ids)
        if search:
            clauses.append(f"({prefix}title_norm LIKE ? OR {prefix}filename LIKE ?)")
            needle = f"%{str(search).strip().lower()}%"
            params.extend([needle, needle])
        if favorites_only:
            clauses.append(f"{prefix}favorite = 1")
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def all_entries(self, systems=None) -> list[dict]:
        """Compare가 쓰는 전량 조회 - Metadata 필드와 Media 종류까지 한 번에 싣는다.

        `query_rows()`는 목록 표시용이라 fields를 빼고, `get_row()`는 한 건마다 질의를
        세 번 한다. Compare는 두 Collection을 통째로 맞대므로 행마다 get_row를 부르면
        (좌 N + 우 M)번의 질의가 된다 - 여기서는 세 번으로 끝낸다.
        """
        where, params = "", []
        if systems:
            where = f" WHERE system IN ({','.join('?' * len(systems))})"
            params = list(systems)
        rows = {}
        for row in self._conn.execute(
                "SELECT rom_uid,system,filename,storage_id,size,sha256,title,title_norm,"
                f" has_metadata,has_media,present FROM roms{where}", params):
            entry = dict(row)
            entry["fields"] = {}
            entry["media_types"] = []
            rows[entry["rom_uid"]] = entry

        if not rows:
            return []
        for meta in self._conn.execute("SELECT rom_uid,fields_json FROM metadata"):
            entry = rows.get(meta["rom_uid"])
            if entry is not None:
                entry["fields"] = json.loads(meta["fields_json"])
        for media in self._conn.execute("SELECT rom_uid,media_type FROM media"):
            entry = rows.get(media["rom_uid"])
            if entry is not None:
                entry["media_types"].append(media["media_type"])
        for entry in rows.values():
            entry["media_types"].sort()
        return list(rows.values())

    def get_row(self, rom_uid) -> dict | None:
        row = self._conn.execute("SELECT * FROM roms WHERE rom_uid=?", (rom_uid,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        meta = self._conn.execute("SELECT * FROM metadata WHERE rom_uid=?", (rom_uid,)).fetchone()
        result["fields"] = json.loads(meta["fields_json"]) if meta else {}
        result["frontend_raw"] = json.loads(meta["frontend_raw_json"]) if meta else {}
        result["media"] = [dict(m) for m in self._conn.execute(
            "SELECT media_type,rel_path,size,mtime_ns FROM media WHERE rom_uid=? ORDER BY media_type", (rom_uid,))]
        return result

    def get_row_by_filename(self, system, filename) -> dict | None:
        """rom_uid가 아니라 System·파일명으로 찾는다.

        Plan은 만들 때 본 rom_uid를 들고 있는데, 그 사이 그 System이 (부분적으로만
        성공한 Apply 뒤처럼) 다시 스캔되면 uid가 전부 새로 매겨진다 - 파일은 그대로인데
        번호만 바뀐다. `get_row(stale_uid)`가 None을 돌려줄 때, 정말 없어진 것인지
        번호만 바뀐 것인지 구별하려면 이 경로가 필요하다.
        """
        row = self._conn.execute(
            "SELECT rom_uid FROM roms WHERE system=? AND filename=?",
            (system, filename)).fetchone()
        return self.get_row(row["rom_uid"]) if row else None

    def set_favorite(self, rom_uid, favorite):
        """즐겨찾기 컬럼만 갱신한다. 파일 쓰기는 호출부(Adapter)가 한다."""
        with transaction(self._conn):
            self._conn.execute("UPDATE roms SET favorite=? WHERE rom_uid=?",
                               (1 if favorite else 0, int(rom_uid)))

    def update_metadata(self, rom_uid, fields, *, title=None, title_norm=None,
                        content_hash=None, frontend_raw=None):
        """한 항목의 메타데이터를 갱신한다(사용자 편집 반영).

        **`frontend_raw`는 기본적으로 건드리지 않는다** - 사용자가 편집하는 것은 공통
        필드뿐이고, Frontend 고유 값은 읽은 그대로 보존되어야 한다(§50).

        예외는 즐겨찾기처럼 **사용자가 직접 바꾸는 Frontend 고유 값**이다. ES-DE의
        `<favorite>`은 우리 공통 필드가 아니지만 별표를 누르는 것은 분명 사용자
        편집이다. 그럴 때만 명시적으로 넘긴다.
        """
        with transaction(self._conn):
            if frontend_raw is None:
                self._conn.execute(
                    "INSERT INTO metadata (rom_uid,fields_json,content_hash) VALUES (?,?,?)"
                    " ON CONFLICT(rom_uid) DO UPDATE SET fields_json=excluded.fields_json,"
                    " content_hash=excluded.content_hash",
                    (rom_uid, json.dumps(fields or {}, ensure_ascii=False), content_hash))
            else:
                self._conn.execute(
                    "INSERT INTO metadata (rom_uid,fields_json,frontend_raw_json,content_hash)"
                    " VALUES (?,?,?,?)"
                    " ON CONFLICT(rom_uid) DO UPDATE SET fields_json=excluded.fields_json,"
                    " frontend_raw_json=excluded.frontend_raw_json,"
                    " content_hash=excluded.content_hash",
                    (rom_uid, json.dumps(fields or {}, ensure_ascii=False),
                     json.dumps(frontend_raw, ensure_ascii=False), content_hash))
            self._conn.execute("UPDATE roms SET has_metadata=1 WHERE rom_uid=?", (rom_uid,))
            if title is not None:
                self._conn.execute("UPDATE roms SET title=?, title_norm=? WHERE rom_uid=?",
                                   (title, title_norm or "", rom_uid))

    def set_sha256(self, rom_uid, sha256):
        """SHA256은 지연 계산이다(§5 성능). 필요해질 때만 채운다."""
        with transaction(self._conn):
            self._conn.execute("UPDATE roms SET sha256=? WHERE rom_uid=?", (sha256, rom_uid))
