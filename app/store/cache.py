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
        "CREATE TABLE scan_meta (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)",
        # 증분 판정용 디렉터리/파일 시그니처. ROM 수천 개를 매번 stat 하지 않기 위해
        # 디렉터리 mtime만 보고 "이 시스템은 통째로 변경 없음"을 판정하는 데 쓴다.
        """CREATE TABLE dir_sig (
               path TEXT PRIMARY KEY, kind TEXT NOT NULL DEFAULT '',
               mtime_ns INTEGER, ctime_ns INTEGER
           )""",
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
        """CREATE TABLE system_stats (
               system TEXT PRIMARY KEY,
               storage_id TEXT NOT NULL DEFAULT 'internal',
               rom_count INTEGER NOT NULL DEFAULT 0,
               rom_bytes INTEGER NOT NULL DEFAULT 0,
               media_count INTEGER NOT NULL DEFAULT 0,
               media_bytes INTEGER NOT NULL DEFAULT 0,
               missing_metadata INTEGER NOT NULL DEFAULT 0,
               missing_media INTEGER NOT NULL DEFAULT 0
           )""",
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
            for table in ("media", "metadata", "roms", "dir_sig", "system_stats", "scan_meta"):
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

    def get_dir_sig(self, path) -> tuple[int, int] | None:
        row = self._conn.execute("SELECT mtime_ns, ctime_ns FROM dir_sig WHERE path=?", (str(path),)).fetchone()
        return (row["mtime_ns"], row["ctime_ns"]) if row else None

    def set_dir_sig(self, path, mtime_ns, ctime_ns=None, kind=""):
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO dir_sig (path,kind,mtime_ns,ctime_ns) VALUES (?,?,?,?)"
                " ON CONFLICT(path) DO UPDATE SET kind=excluded.kind,"
                " mtime_ns=excluded.mtime_ns, ctime_ns=excluded.ctime_ns",
                (str(path), kind, mtime_ns, ctime_ns))

    # ------------------------------------------------------------------
    # 스캔 결과 반영
    # ------------------------------------------------------------------
    def replace_system(self, system, rows):
        """한 System의 스캔 결과를 통째로 교체한다.

        증분 스캔은 "변경된 System만 다시 읽는다"가 기본 단위이므로, 갱신도 System
        단위로 원자적으로 바꾸는 것이 가장 단순하고 안전하다. 부분 갱신을 지원하면
        삭제된 파일을 지우는 경로를 따로 관리해야 한다.

        rows: {"filename","rel_path","storage_id","size","mtime_ns","sha256",
               "volume_file_id","title","title_norm","has_metadata","has_media",
               "present","fields","frontend_raw","content_hash",
               "media":[{"media_type","rel_path","size","mtime_ns"}]} 의 목록
        """
        with transaction(self._conn):
            self._conn.execute("DELETE FROM roms WHERE system=?", (system,))
            for row in rows:
                cur = self._conn.execute(
                    "INSERT INTO roms (system,filename,rel_path,storage_id,size,mtime_ns,sha256,"
                    " volume_file_id,title,title_norm,has_metadata,has_media,present)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (system, row["filename"], row.get("rel_path", ""), row.get("storage_id", "internal"),
                     int(row.get("size", 0)), int(row.get("mtime_ns", 0)), row.get("sha256"),
                     row.get("volume_file_id"), row.get("title", ""), row.get("title_norm", ""),
                     1 if row.get("has_metadata") else 0, 1 if row.get("has_media") else 0,
                     1 if row.get("present", True) else 0))
                rom_uid = cur.lastrowid
                if row.get("fields") is not None or row.get("frontend_raw") is not None:
                    self._conn.execute(
                        "INSERT INTO metadata (rom_uid,fields_json,frontend_raw_json,content_hash) VALUES (?,?,?,?)",
                        (rom_uid, json.dumps(row.get("fields") or {}, ensure_ascii=False),
                         json.dumps(row.get("frontend_raw") or {}, ensure_ascii=False),
                         row.get("content_hash")))
                for m in row.get("media") or []:
                    self._conn.execute(
                        "INSERT INTO media (rom_uid,media_type,rel_path,size,mtime_ns) VALUES (?,?,?,?,?)",
                        (rom_uid, m["media_type"], m.get("rel_path", ""),
                         int(m.get("size", 0)), int(m.get("mtime_ns", 0))))

    def set_system_stats(self, system, storage_id, **counts):
        fields = {"rom_count": 0, "rom_bytes": 0, "media_count": 0, "media_bytes": 0,
                  "missing_metadata": 0, "missing_media": 0}
        fields.update({k: int(v) for k, v in counts.items() if k in fields})
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO system_stats (system,storage_id,rom_count,rom_bytes,media_count,media_bytes,"
                " missing_metadata,missing_media) VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(system) DO UPDATE SET storage_id=excluded.storage_id,"
                " rom_count=excluded.rom_count, rom_bytes=excluded.rom_bytes,"
                " media_count=excluded.media_count, media_bytes=excluded.media_bytes,"
                " missing_metadata=excluded.missing_metadata, missing_media=excluded.missing_media",
                (system, storage_id, fields["rom_count"], fields["rom_bytes"], fields["media_count"],
                 fields["media_bytes"], fields["missing_metadata"], fields["missing_media"]))

    def system_stats(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM system_stats ORDER BY system")]

    def storage_usage(self) -> dict[str, int]:
        """Storage별 실사용 바이트(Actual). Plan 계산의 기준값(§82)."""
        rows = self._conn.execute(
            "SELECT storage_id, SUM(rom_bytes + media_bytes) AS used FROM system_stats GROUP BY storage_id")
        return {r["storage_id"]: int(r["used"] or 0) for r in rows}

    # ------------------------------------------------------------------
    # 목록 조회 (정렬/필터/페이징 전부 SQL)
    # ------------------------------------------------------------------
    def query_rows(self, *, systems=None, storage_ids=None, search=None, order="title",
                   descending=False, limit=None, offset=0) -> list[dict]:
        where, params = self._build_where(systems, storage_ids, search)
        order_col = {"title": "title_norm", "filename": "filename", "size": "size",
                     "system": "system"}.get(order, "title_norm")
        sql = (f"SELECT rom_uid,system,filename,rel_path,storage_id,size,title,"
               f" has_metadata,has_media,present FROM roms{where}"
               f" ORDER BY {order_col} {'DESC' if descending else 'ASC'}, filename")
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = [*params, int(limit), int(offset)]
        return [dict(r) for r in self._conn.execute(sql, params)]

    def count_rows(self, *, systems=None, storage_ids=None, search=None) -> int:
        where, params = self._build_where(systems, storage_ids, search)
        row = self._conn.execute(f"SELECT COUNT(*) AS n FROM roms{where}", params).fetchone()
        return int(row["n"])

    @staticmethod
    def _build_where(systems, storage_ids, search):
        clauses, params = [], []
        if systems:
            clauses.append(f"system IN ({','.join('?' * len(systems))})")
            params.extend(systems)
        if storage_ids:
            clauses.append(f"storage_id IN ({','.join('?' * len(storage_ids))})")
            params.extend(storage_ids)
        if search:
            clauses.append("(title_norm LIKE ? OR filename LIKE ?)")
            needle = f"%{str(search).strip().lower()}%"
            params.extend([needle, needle])
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

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

    def set_sha256(self, rom_uid, sha256):
        """SHA256은 지연 계산이다(§5 성능). 필요해질 때만 채운다."""
        with transaction(self._conn):
            self._conn.execute("UPDATE roms SET sha256=? WHERE rom_uid=?", (sha256, rom_uid))
