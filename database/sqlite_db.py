"""SQLite read repository used during the v0.5 incremental migration.

The public API intentionally returns the same semantic objects used by v0.4.
JSON remains the compatibility/write source for this transition; the API refreshes
SQLite after a JSON write, so native reads never observe stale data.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS systems (
    system TEXT PRIMARY KEY,
    default_core TEXT,
    is_custom INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS roms (
    rom_id INTEGER PRIMARY KEY AUTOINCREMENT,
    system TEXT NOT NULL,
    filename TEXT NOT NULL,
    legacy_key TEXT NOT NULL UNIQUE,
    default_version_id TEXT,
    core_override TEXT,
    UNIQUE(system, filename)
);
CREATE TABLE IF NOT EXISTS metadata_versions (
    version_id TEXT NOT NULL,
    rom_id INTEGER NOT NULL REFERENCES roms(rom_id) ON DELETE CASCADE,
    created_at TEXT,
    source_local_id TEXT,
    uncertain_match INTEGER NOT NULL DEFAULT 0,
    fields_json TEXT NOT NULL,
    PRIMARY KEY (rom_id, version_id)
);
CREATE TABLE IF NOT EXISTS media (
    media_id INTEGER PRIMARY KEY AUTOINCREMENT,
    rom_id INTEGER NOT NULL REFERENCES roms(rom_id) ON DELETE CASCADE,
    media_type TEXT NOT NULL,
    path_json TEXT NOT NULL,
    UNIQUE(rom_id, media_type)
);
CREATE TABLE IF NOT EXISTS game_list_sets (
    set_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    frontend TEXT,
    rom_path TEXT,
    metadata_path TEXT,
    media_path TEXT,
    target_capacity_bytes INTEGER
);
CREATE TABLE IF NOT EXISTS game_list_set_roms (
    set_id TEXT NOT NULL REFERENCES game_list_sets(set_id) ON DELETE CASCADE,
    rom_id INTEGER NOT NULL REFERENCES roms(rom_id) ON DELETE CASCADE,
    PRIMARY KEY(set_id, rom_id)
);
CREATE TABLE IF NOT EXISTS similar_groups (
    group_id INTEGER PRIMARY KEY AUTOINCREMENT,
    system TEXT NOT NULL,
    -- [P1 버그 수정] 예전엔 FK가 없어서 대표로 지정된 ROM이 삭제돼도 여기 값이
    -- dangling rom_id로 남을 수 있었다 (get_similar_groups()가 그 경우 조회 실패를
    -- None으로 조용히 삼켜서 화면은 안 깨졌지만, DB 자체는 참조 무결성이 깨진
    -- 상태였다). ON DELETE SET NULL로 대표 ROM 삭제 시 대표 지정만 자동 해제되게 한다.
    -- [주의] CREATE TABLE IF NOT EXISTS라 이미 만들어진 기존 master.db에는 이 FK가
    -- 소급 적용되지 않는다 (SQLite는 기존 테이블을 자동 마이그레이션하지 않음) -
    -- 이 프로젝트가 아직 스키마 마이그레이션 프레임워크 없이 v0.x로 개발 중이라는
    -- 전제(memory.md)와 같은 맥락. 기존 DB를 고치려면 새 DB로 다시 만들어야 한다.
    representative_rom_id INTEGER REFERENCES roms(rom_id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS similar_group_members (
    group_id INTEGER NOT NULL REFERENCES similar_groups(group_id) ON DELETE CASCADE,
    rom_id INTEGER NOT NULL REFERENCES roms(rom_id) ON DELETE CASCADE,
    PRIMARY KEY(group_id, rom_id)
);
CREATE TABLE IF NOT EXISTS favorites (
    rom_id INTEGER PRIMARY KEY REFERENCES roms(rom_id) ON DELETE CASCADE
);
-- [신규] ROM 실물 파일의 SHA256 - 처음 복사될 때 한 번만 계산해서 캐시한다(재계산
-- 안 함). Local->Local 직접 복사(export_engine.copy_local_to_local)는 ArchiveDB를
-- 아예 거치지 않고 동작하는 게 설계 원칙이라(memory.md 참고) roms.rom_id를 FK로
-- 걸면 그 경로에서 rom row가 없어 저장할 수 없다 - 그래서 roms 테이블과 무관하게
-- legacy_key("system|filename", db.make_rom_key와 동일 형식)만으로 독립적으로 캐시한다.
-- roms에 컬럼을 얹지 않은 이유는 favorites와 같다 - 이 프로젝트는 스키마 마이그레이션
-- 프레임워크가 없어서(위 참고) 기존 master.db에는 ALTER TABLE이 소급 적용되지 않지만,
-- CREATE TABLE IF NOT EXISTS는 새 테이블이라 기존 DB에도 안전하게 추가된다.
CREATE TABLE IF NOT EXISTS rom_hashes (
    legacy_key TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_roms_system ON roms(system);
CREATE INDEX IF NOT EXISTS idx_versions_rom ON metadata_versions(rom_id);
CREATE INDEX IF NOT EXISTS idx_media_rom ON media(rom_id);
"""


class SQLiteRepository:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        # [v0.5 8단계 성능수정] 기본 journal_mode(DELETE)+synchronous(FULL) 조합은 매
        # commit마다 fsync를 강제한다. import_engine.py의 native write(ensure_rom/
        # insert_version/set_media)가 rom 하나당 여러 번 개별 커밋하므로, 10,000-ROM
        # 규모 Import에서 이 조합이 실측상 몇 분~그 이상까지 걸리는 치명적 병목이었다
        # (300개 rom x 3커밋 테스트에서 60초 넘게 걸림). WAL + synchronous=NORMAL은
        # SQLite 공식 권장 설정으로 내구성을 크게 해치지 않으면서 커밋 비용을
        # 수십~수백 배 줄인다(WAL 파일에 순차 append 후 필요할 때만 체크포인트).
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._batch_depth = 0

    @classmethod
    def from_masterdb_root(cls, root: str | Path) -> "SQLiteRepository":
        return cls(Path(root) / "master.db")

    def close(self):
        self.conn.close()

    @contextmanager
    def batch(self):
        """Wrap many native write calls (ensure_rom/insert_version/set_media/...) in a
        single commit instead of one per call.

        [v0.5 8단계 성능수정, 2번째 라운드] WAL 전환(위 __init__ 주석)만으로는 부족했다.
        Import 루프가 rom 하나당 ensure_rom/insert_version/set_media(미디어 타입 수만큼)를
        각각 별도로 커밋하면, WAL이어도 커밋 수 자체가 수만 건에 달해 실측상
        "기존 대비 30배 이상 느림"이라는 사용자 보고로 이어졌다. 개별 메서드는 각자
        `with self.conn:` 대신 `self._commit()`을 쓰도록 바뀌었고, `_commit()`은
        `_batch_depth > 0`이면 아무것도 안 한다 - 그래서 import_engine.py가 rom
        10,000개 전체 루프를 이 batch()로 한 번만 감싸면, 커밋이 수만 건 -> 1건으로
        줄어든다. 중첩 호출도 안전하다(가장 바깥쪽만 실제로 commit/rollback).
        """
        self._batch_depth += 1
        try:
            yield self
            if self._batch_depth == 1:
                self.conn.commit()
        except Exception:
            if self._batch_depth == 1:
                self.conn.rollback()
            raise
        finally:
            self._batch_depth -= 1

    def _commit(self):
        """개별 write 메서드가 쓰는 커밋 지점. batch() 밖에서 호출되면(대부분의 단발성
        API 호출 - save_version_fields 등) 즉시 커밋해 기존과 동일하게 동작하고,
        batch() 안에서는 생략되어 바깥쪽에서 한 번에 커밋된다."""
        if self._batch_depth == 0:
            self.conn.commit()

    def replace_from_dict(self, data: Dict[str, Any], locals_data: Optional[Iterable[Dict[str, Any]]] = None):
        """Refresh the SQLite projection from a v0.4-compatible dictionary.

        This operation is atomic. It deliberately rebuilds the projection rather than
        attempting a clever incremental diff while the legacy write path is active.
        """
        locals_data = list(locals_data or [])
        with self.conn:
            self.conn.execute("DELETE FROM systems")
            for system, info in (data.get("system_cores") or {}).items():
                info = info or {}
                self.conn.execute(
                    "INSERT INTO systems(system, default_core, is_custom) VALUES(?,?,?)",
                    (system, info.get("default_core"), int(bool(info.get("is_custom", False))))
                )

            json_roms = data.get("roms") or {}

            # Only DELETE roms that genuinely disappeared from JSON. rom_id is
            # AUTOINCREMENT (never reused), and game_list_set_roms/similar_group_members/
            # favorites reference rom_id with ON DELETE CASCADE. A blanket
            # "DELETE FROM roms" here used to silently wipe every native-only
            # association (Favorites/SimilarGroup/GameListSet membership) on every
            # single JSON save, even for roms nothing changed on. Deleting only the
            # roms actually removed from JSON keeps rom_id (and its native-only
            # associations) stable for everything else.
            existing = {row["legacy_key"]: row["rom_id"] for row in self.conn.execute("SELECT rom_id, legacy_key FROM roms")}
            stale_keys = set(existing) - set(json_roms)
            if stale_keys:
                self.conn.executemany("DELETE FROM roms WHERE legacy_key=?", [(k,) for k in stale_keys])

            for legacy_key, entry in json_roms.items():
                system = str(entry.get("system", ""))
                filename = str(entry.get("rom_filename", ""))
                self.conn.execute(
                    "INSERT INTO roms(system, filename, legacy_key, default_version_id, core_override) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(legacy_key) DO UPDATE SET "
                    "system=excluded.system, filename=excluded.filename, "
                    "default_version_id=excluded.default_version_id, core_override=excluded.core_override",
                    (system, filename, legacy_key, entry.get("default_version_id"), entry.get("core_override"))
                )
                rom_id = self.conn.execute("SELECT rom_id FROM roms WHERE legacy_key=?", (legacy_key,)).fetchone()[0]

                # versions/media have no native-only dependents, so a per-rom
                # rebuild (instead of the old whole-table wipe) is still correct
                # and now scoped to just this rom.
                self.conn.execute("DELETE FROM metadata_versions WHERE rom_id=?", (rom_id,))
                for vid, version in (entry.get("versions") or {}).items():
                    version = version or {}
                    self.conn.execute(
                        "INSERT INTO metadata_versions(version_id, rom_id, created_at, source_local_id, uncertain_match, fields_json) VALUES(?,?,?,?,?,?)",
                        (vid, rom_id, version.get("created_at", ""), version.get("source_local_id", ""), int(bool(version.get("uncertain_match", False))), json.dumps(version.get("fields") or {}, ensure_ascii=False))
                    )
                self.conn.execute("DELETE FROM media WHERE rom_id=?", (rom_id,))
                for media_type, value in (entry.get("media") or {}).items():
                    self.conn.execute(
                        "INSERT INTO media(rom_id, media_type, path_json) VALUES(?,?,?)",
                        (rom_id, media_type, json.dumps(value, ensure_ascii=False))
                    )

            # GameListSet metadata (name/paths/capacity) is JSON-sourced and upserted.
            # Membership (game_list_set_roms) is native-only and is therefore left
            # untouched here, unless the owning set itself was removed from config.
            wanted_set_ids = set()
            for local in locals_data:
                set_id = str(local.get("id", ""))
                if not set_id:
                    continue
                wanted_set_ids.add(set_id)
                self.conn.execute(
                    "INSERT INTO game_list_sets(set_id,name,frontend,rom_path,metadata_path,media_path,target_capacity_bytes) "
                    "VALUES(?,?,?,?,?,?,?) ON CONFLICT(set_id) DO UPDATE SET "
                    "name=excluded.name, frontend=excluded.frontend, rom_path=excluded.rom_path, "
                    "metadata_path=excluded.metadata_path, media_path=excluded.media_path, "
                    "target_capacity_bytes=excluded.target_capacity_bytes",
                    (set_id, local.get("label", set_id), local.get("frontend", ""), local.get("rom_path", ""), local.get("metadata_path", ""), local.get("media_path", ""), local.get("target_capacity_bytes"))
                )
            existing_set_ids = {row[0] for row in self.conn.execute("SELECT set_id FROM game_list_sets")}
            removed_set_ids = existing_set_ids - wanted_set_ids
            if removed_set_ids:
                self.conn.executemany("DELETE FROM game_list_sets WHERE set_id=?", [(s,) for s in removed_set_ids])

            self.conn.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('projection_version','1')")

    def _rom_id(self, legacy_key: str) -> Optional[int]:
        row = self.conn.execute("SELECT rom_id FROM roms WHERE legacy_key=?", (legacy_key,)).fetchone()
        return int(row[0]) if row else None

    def list_roms(self):
        rows = self.conn.execute("SELECT * FROM roms ORDER BY system, filename").fetchall()
        favorite_ids = {row[0] for row in self.conn.execute("SELECT rom_id FROM favorites")}
        result = []
        for row in rows:
            versions = self.conn.execute("SELECT * FROM metadata_versions WHERE rom_id=? ORDER BY created_at, version_id", (row["rom_id"],)).fetchall()
            media_rows = self.conn.execute("SELECT media_type,path_json FROM media WHERE rom_id=?", (row["rom_id"],)).fetchall()
            media = {r["media_type"]: json.loads(r["path_json"]) for r in media_rows}
            result.append({
                "romKey": row["legacy_key"], "system": row["system"], "file": row["filename"],
                "default_version_id": row["default_version_id"], "core_override": row["core_override"],
                "versions": [dict(r, fields=json.loads(r["fields_json"])) for r in versions],
                "media": media,
                "favorite": row["rom_id"] in favorite_ids,
            })
        return result

    def get_rom(self, legacy_key: str):
        row = self.conn.execute("SELECT * FROM roms WHERE legacy_key=?", (legacy_key,)).fetchone()
        if not row:
            return None
        versions = self.conn.execute("SELECT * FROM metadata_versions WHERE rom_id=? ORDER BY created_at, version_id", (row["rom_id"],)).fetchall()
        media_rows = self.conn.execute("SELECT media_type,path_json FROM media WHERE rom_id=?", (row["rom_id"],)).fetchall()
        return {
            "romKey": row["legacy_key"], "system": row["system"], "file": row["filename"],
            "default_version_id": row["default_version_id"], "core_override": row["core_override"],
            "versions": [dict(r, fields=json.loads(r["fields_json"])) for r in versions],
            "media": {r["media_type"]: json.loads(r["path_json"]) for r in media_rows},
        }

    # ------------------------------------------------------------------
    # Native write operations used during the v0.5 incremental migration.
    # These methods intentionally operate on SQLite directly. The API layer
    # updates the legacy JSON projection as a compatibility mirror afterwards.
    # ------------------------------------------------------------------
    def ensure_rom(self, legacy_key: str, system: str, filename: str, default_version_id=None, core_override=None) -> int:
        row = self.conn.execute("SELECT rom_id FROM roms WHERE legacy_key=?", (legacy_key,)).fetchone()
        if row:
            return int(row[0])
        cur = self.conn.execute(
            "INSERT INTO roms(system,filename,legacy_key,default_version_id,core_override) VALUES(?,?,?,?,?)",
            (system, filename, legacy_key, default_version_id, core_override),
        )
        self._commit()
        return int(cur.lastrowid)

    def update_rom(self, legacy_key: str, *, default_version_id=None, core_override=None) -> bool:
        cur = self.conn.execute(
            "UPDATE roms SET default_version_id=?, core_override=? WHERE legacy_key=?",
            (default_version_id, core_override, legacy_key),
        )
        self._commit()
        return cur.rowcount == 1

    def insert_version(self, legacy_key: str, version_id: str, created_at: str, source_local_id: str,
                       uncertain_match: bool, fields: dict, set_as_default: bool = False) -> bool:
        rom_id = self._rom_id(legacy_key)
        if rom_id is None:
            return False
        self.conn.execute(
            "INSERT INTO metadata_versions(version_id,rom_id,created_at,source_local_id,uncertain_match,fields_json) VALUES(?,?,?,?,?,?)",
            (version_id, rom_id, created_at, source_local_id or "", int(bool(uncertain_match)),
             json.dumps(fields or {}, ensure_ascii=False)),
        )
        if set_as_default:
            self.conn.execute("UPDATE roms SET default_version_id=? WHERE rom_id=?", (version_id, rom_id))
        self._commit()
        return True

    def update_version_fields(self, legacy_key: str, version_id: str, fields: dict) -> bool:
        rom_id = self._rom_id(legacy_key)
        if rom_id is None:
            return False
        cur = self.conn.execute(
            "UPDATE metadata_versions SET fields_json=? WHERE rom_id=? AND version_id=?",
            (json.dumps(fields or {}, ensure_ascii=False), rom_id, version_id),
        )
        self._commit()
        return cur.rowcount == 1

    def set_default_version(self, legacy_key: str, version_id: str) -> bool:
        rom_id = self._rom_id(legacy_key)
        if rom_id is None:
            return False
        exists = self.conn.execute(
            "SELECT 1 FROM metadata_versions WHERE rom_id=? AND version_id=?", (rom_id, version_id)
        ).fetchone()
        if not exists:
            return False
        self.conn.execute("UPDATE roms SET default_version_id=? WHERE rom_id=?", (version_id, rom_id))
        self._commit()
        return True

    def delete_version(self, legacy_key: str, version_id: str, replacement_default_id=None) -> bool:
        rom_id = self._rom_id(legacy_key)
        if rom_id is None:
            return False
        cur = self.conn.execute(
            "DELETE FROM metadata_versions WHERE rom_id=? AND version_id=?", (rom_id, version_id)
        )
        if cur.rowcount != 1:
            return False
        if replacement_default_id is not None:
            self.conn.execute("UPDATE roms SET default_version_id=? WHERE rom_id=?", (replacement_default_id, rom_id))
        self._commit()
        return True

    def set_media(self, legacy_key: str, media_type: str, value) -> bool:
        rom_id = self._rom_id(legacy_key)
        if rom_id is None:
            return False
        payload = json.dumps(value, ensure_ascii=False)
        self.conn.execute(
            "INSERT INTO media(rom_id,media_type,path_json) VALUES(?,?,?) "
            "ON CONFLICT(rom_id,media_type) DO UPDATE SET path_json=excluded.path_json",
            (rom_id, media_type, payload),
        )
        self._commit()
        return True

    # ------------------------------------------------------------------
    # GameListSet membership (v0.5 "GameListSet 기반 다지기" groundwork).
    # Membership is native-only (not JSON-backed) so it survives independently
    # of the legacy JSON roms projection; only game_list_sets metadata
    # (name/paths/capacity) is JSON-sourced. ROMs that do not exist yet in the
    # roms table are silently skipped -- membership can only reference ROMs
    # already present in MasterDB.
    # ------------------------------------------------------------------
    def _ensure_gamelistset(self, set_id: str) -> None:
        """Make sure a game_list_sets row exists for set_id before membership rows
        reference it via FK. Import/export can run before the owning Local's real
        metadata (name/paths/capacity) has ever been synced from config via
        replace_from_dict() - e.g. right after add_local(), which only touches
        config.json and never calls _save_db(). A placeholder row here is
        transparently overwritten with the real values on the next
        replace_from_dict() upsert (ON CONFLICT DO UPDATE), so this never leaves
        stale data behind."""
        self.conn.execute(
            "INSERT OR IGNORE INTO game_list_sets(set_id, name) VALUES(?,?)",
            (set_id, set_id),
        )

    def get_gamelistset_members(self, set_id: str):
        rows = self.conn.execute(
            "SELECT r.legacy_key FROM game_list_set_roms gsr "
            "JOIN roms r ON r.rom_id = gsr.rom_id WHERE gsr.set_id=? ORDER BY r.legacy_key",
            (set_id,),
        ).fetchall()
        return [row[0] for row in rows]

    def add_gamelistset_members(self, set_id: str, legacy_keys: Iterable[str]) -> int:
        keys = [k for k in legacy_keys if k]
        if not keys:
            return 0
        added = 0
        self._ensure_gamelistset(set_id)
        for key in keys:
            rom_id = self._rom_id(key)
            if rom_id is None:
                continue
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO game_list_set_roms(set_id, rom_id) VALUES(?,?)",
                (set_id, rom_id),
            )
            added += cur.rowcount
        self._commit()
        return added

    def remove_gamelistset_members(self, set_id: str, legacy_keys: Iterable[str]) -> int:
        keys = [k for k in legacy_keys if k]
        if not keys:
            return 0
        removed = 0
        for key in keys:
            rom_id = self._rom_id(key)
            if rom_id is None:
                continue
            cur = self.conn.execute(
                "DELETE FROM game_list_set_roms WHERE set_id=? AND rom_id=?",
                (set_id, rom_id),
            )
            removed += cur.rowcount
        self._commit()
        return removed

    def sync_gamelistset_membership(self, set_id: str, legacy_keys: Iterable[str]) -> None:
        """Replace this GameListSet's membership so it exactly matches legacy_keys.

        Unknown legacy_keys (ROMs not present in the roms table) are skipped.
        This is the primitive scan/import call sites use instead of
        rescanning the filesystem to figure out "which MasterDB roms belong
        to this GameListSet" every time.
        """
        wanted_keys = {k for k in legacy_keys if k}
        if wanted_keys:
            self._ensure_gamelistset(set_id)
            placeholders = ",".join("?" * len(wanted_keys))
            wanted_ids = {
                row[0] for row in self.conn.execute(
                    f"SELECT rom_id FROM roms WHERE legacy_key IN ({placeholders})",
                    tuple(wanted_keys),
                )
            }
        else:
            wanted_ids = set()
        existing_ids = {
            row[0] for row in self.conn.execute(
                "SELECT rom_id FROM game_list_set_roms WHERE set_id=?", (set_id,)
            )
        }
        to_add = wanted_ids - existing_ids
        to_remove = existing_ids - wanted_ids
        if to_add:
            self.conn.executemany(
                "INSERT OR IGNORE INTO game_list_set_roms(set_id, rom_id) VALUES(?,?)",
                [(set_id, rid) for rid in to_add],
            )
        if to_remove:
            self.conn.executemany(
                "DELETE FROM game_list_set_roms WHERE set_id=? AND rom_id=?",
                [(set_id, rid) for rid in to_remove],
            )
        self._commit()

    def get_gamelistset_ids_for_rom(self, legacy_key: str):
        rom_id = self._rom_id(legacy_key)
        if rom_id is None:
            return []
        rows = self.conn.execute(
            "SELECT set_id FROM game_list_set_roms WHERE rom_id=? ORDER BY set_id", (rom_id,)
        ).fetchall()
        return [row[0] for row in rows]

    def delete_rom(self, legacy_key: str) -> bool:
        rom_id = self._rom_id(legacy_key)
        if rom_id is None:
            return False
        cur = self.conn.execute("DELETE FROM roms WHERE rom_id=?", (rom_id,))
        # rom_hashes는 roms에 FK로 안 걸려 있어(위 스키마 주석 참고) CASCADE로 안
        # 지워진다 - 같은 (system, filename)으로 나중에 내용이 다른 ROM이 다시
        # 들어오면 옛 해시가 잘못 재사용될 수 있으니 명시적으로 같이 지운다.
        self.conn.execute("DELETE FROM rom_hashes WHERE legacy_key=?", (legacy_key,))
        self._commit()
        return cur.rowcount == 1

    # ------------------------------------------------------------------
    # Favorite (0.4.1.x 단위 9): native-only 플래그. JSON(self.db)에는 저장하지 않고
    # SQLite의 favorites 테이블(rom_id PK, ON DELETE CASCADE)에만 존재한다 - 위의
    # replace_from_dict 주석대로, ROM이 실제로 사라지지 않는 한 rom_id가 안정적으로
    # 유지되므로 매 JSON 저장마다 사라지지 않는다.
    # ------------------------------------------------------------------
    def is_favorite(self, legacy_key: str) -> bool:
        rom_id = self._rom_id(legacy_key)
        if rom_id is None:
            return False
        row = self.conn.execute("SELECT 1 FROM favorites WHERE rom_id=?", (rom_id,)).fetchone()
        return row is not None

    def set_favorite(self, legacy_key: str, favorite: bool) -> bool:
        rom_id = self._rom_id(legacy_key)
        if rom_id is None:
            return False
        if favorite:
            self.conn.execute("INSERT OR IGNORE INTO favorites(rom_id) VALUES(?)", (rom_id,))
        else:
            self.conn.execute("DELETE FROM favorites WHERE rom_id=?", (rom_id,))
        self._commit()
        return True

    def list_favorite_keys(self) -> set:
        rows = self.conn.execute(
            "SELECT r.legacy_key FROM favorites f JOIN roms r ON r.rom_id = f.rom_id"
        ).fetchall()
        return {row[0] for row in rows}

    # ------------------------------------------------------------------
    # ROM 실물 파일 SHA256 캐시 - ROM이 처음 복사되는 지점(Local->ArchiveDB,
    # Local->Local, ArchiveDB->Local)마다 한 번만 계산해서 여기 저장한다. roms
    # 테이블과 무관한 독립 캐시라 rom_id를 몰라도(예: Local->Local) 쓸 수 있다.
    def get_rom_hash(self, legacy_key: str) -> Optional[str]:
        row = self.conn.execute("SELECT sha256 FROM rom_hashes WHERE legacy_key=?", (legacy_key,)).fetchone()
        return row[0] if row else None

    def set_rom_hash(self, legacy_key: str, sha256: str) -> bool:
        self.conn.execute(
            "INSERT INTO rom_hashes(legacy_key, sha256) VALUES(?,?) "
            "ON CONFLICT(legacy_key) DO UPDATE SET sha256=excluded.sha256",
            (legacy_key, sha256),
        )
        self._commit()
        return True

    # ------------------------------------------------------------------
    # SimilarGroup (v0.5 10단계): 유사롬 그룹을 native로 저장한다. 예전엔
    # self.db["similar_rom_groups"][system]이라는 별개의 JSON 키에 저장되어 고정 ID가
    # 없었고, "유사롬 찾기"를 누를 때마다 통째로 덮어써서 대표 지정을 얹을 데가 없었다.
    # group_id(AUTOINCREMENT)가 생겨서 이제 대표(representative_rom_id)를 그 위에
    # 안정적으로 얹을 수 있다. 단, 재탐색(save_similar_groups 재호출)은 여전히 해당
    # system의 그룹을 전부 새로 만든다 - 그룹 재구성 자체가 "다시 분석"을 의미하므로
    # 이전 group_id/대표 지정은 재탐색 시 초기화되는 게 맞는 설계로 판단함(재탐색 없이
    # 조회/대표 지정만 하는 동안은 group_id가 계속 안정적으로 유지됨).
    # ------------------------------------------------------------------
    def save_similar_groups(self, system: str, groups) -> None:
        """groups: similar_rom.find_similar_roms()가 반환하는
        [{"members": [legacy_key, ...], "pairs": [...]}] 형태. score/pairs는
        일회성 표시용이라 SQLite에는 저장하지 않는다(그룹 멤버십과 대표만 영속화)."""
        old_group_ids = [row[0] for row in self.conn.execute(
            "SELECT group_id FROM similar_groups WHERE system=?", (system,)
        )]
        if old_group_ids:
            self.conn.executemany(
                "DELETE FROM similar_groups WHERE group_id=?", [(g,) for g in old_group_ids]
            )
        for g in groups:
            member_ids = [rid for rid in (self._rom_id(k) for k in g.get("members", [])) if rid is not None]
            if len(member_ids) < 2:
                continue
            cur = self.conn.execute(
                "INSERT INTO similar_groups(system, representative_rom_id) VALUES(?, NULL)", (system,)
            )
            group_id = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO similar_group_members(group_id, rom_id) VALUES(?,?)",
                [(group_id, rid) for rid in member_ids],
            )
        self._commit()

    def get_similar_groups(self, system: str):
        """반환: [{"group_id": int, "members": [legacy_key, ...], "representative": legacy_key|None}]"""
        rows = self.conn.execute(
            "SELECT group_id, representative_rom_id FROM similar_groups WHERE system=? ORDER BY group_id",
            (system,),
        ).fetchall()
        result = []
        for row in rows:
            member_rows = self.conn.execute(
                "SELECT r.legacy_key FROM similar_group_members sgm JOIN roms r ON r.rom_id = sgm.rom_id "
                "WHERE sgm.group_id=? ORDER BY r.legacy_key",
                (row["group_id"],),
            ).fetchall()
            members = [m[0] for m in member_rows]
            if len(members) < 2:
                continue
            rep_key = None
            if row["representative_rom_id"] is not None:
                rr = self.conn.execute(
                    "SELECT legacy_key FROM roms WHERE rom_id=?", (row["representative_rom_id"],)
                ).fetchone()
                rep_key = rr[0] if rr else None
            result.append({"group_id": row["group_id"], "members": members, "representative": rep_key})
        return result

    def set_similar_group_representative(self, group_id: int, legacy_key: Optional[str]) -> bool:
        """legacy_key=None(또는 falsy)이면 대표 지정을 해제한다. legacy_key가 그 그룹의
        멤버가 아니면 실패(False)한다."""
        rom_id = None
        if legacy_key:
            rom_id = self._rom_id(legacy_key)
            if rom_id is None:
                return False
            is_member = self.conn.execute(
                "SELECT 1 FROM similar_group_members WHERE group_id=? AND rom_id=?", (group_id, rom_id)
            ).fetchone()
            if not is_member:
                return False
        cur = self.conn.execute(
            "UPDATE similar_groups SET representative_rom_id=? WHERE group_id=?", (rom_id, group_id)
        )
        self._commit()
        return cur.rowcount == 1

    def count_roms(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM roms").fetchone()[0])

    def total_rom_size(self, masterdb_root: str | Path) -> int:
        root = Path(masterdb_root) / "roms"
        total = 0
        for row in self.conn.execute("SELECT system, filename FROM roms"):
            try:
                total += (root / row["system"] / row["filename"]).stat().st_size
            except OSError:
                pass
        return total

    def snapshot(self):
        return {"roms": self.list_roms()}
