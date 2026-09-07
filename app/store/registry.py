"""
app/store/registry.py
======================
registry.db - Collection 등록, Storage/System 배치, 인스턴스 간 변경 전파, 잠금.

이전 프로젝트는 Local 목록을 `config.json`에 두고 통째로 다시 썼다. 그래서
(1) 두 곳에서 동시에 저장하면 파일이 깨질 수 있었고, (2) 스캔 결과를 실수로
넣으면 매번 수천 개 항목을 직렬화하는 사고로 이어졌다. 여기서는 DB로 옮겨
두 문제를 구조적으로 없앤다.

Plan은 여기에 저장하지 않는다(결정 D2 - Plan은 세션 한정).
"""

from __future__ import annotations

import json
import time
import uuid

from app.model.collection import Collection, StorageLocation, SystemEntry, STORAGE_INTERNAL
from app.store.sqlite import Migration, connect, transaction

# 동시에 Open 가능한 Collection 수(스펙 §2.2). 저장 가능한 개수 제한이 아니다.
MAX_OPEN_COLLECTIONS = 10

# change_log kind
CHANGE_COLLECTION_CREATED = "collection.created"
CHANGE_COLLECTION_UPDATED = "collection.updated"
CHANGE_COLLECTION_DELETED = "collection.deleted"
CHANGE_LAYOUT_UPDATED = "collection.layout"      # storage/system 배치 변경
CHANGE_SCAN_UPDATED = "collection.scan"          # cache 갱신됨
CHANGE_APPLIED = "collection.applied"            # Plan Apply로 파일이 바뀜

MIGRATIONS = (
    Migration(1, (
        """CREATE TABLE collections (
               id TEXT PRIMARY KEY,
               name TEXT NOT NULL,
               frontend TEXT NOT NULL,
               target TEXT, os TEXT, arch TEXT,
               root_path TEXT NOT NULL DEFAULT '',
               ui_state_json TEXT NOT NULL DEFAULT '{}',
               created_at REAL NOT NULL,
               updated_at REAL NOT NULL
           )""",
        """CREATE TABLE collection_storages (
               collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
               storage_id TEXT NOT NULL,
               kind TEXT NOT NULL,
               label TEXT NOT NULL DEFAULT '',
               root_path TEXT NOT NULL DEFAULT '',
               volume_key TEXT,
               capacity_bytes INTEGER,
               PRIMARY KEY (collection_id, storage_id)
           )""",
        # storage_id가 단일 컬럼이라는 사실이 스펙 §8("하나의 System은 하나의
        # Storage")을 스키마 수준에서 보장한다. 양쪽에 동시에 두는 상태는 표현 불가.
        """CREATE TABLE collection_systems (
               collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
               system TEXT NOT NULL,
               storage_id TEXT NOT NULL,
               rom_path TEXT, media_path TEXT, metadata_path TEXT,
               PRIMARY KEY (collection_id, system)
           )""",
        """CREATE TABLE change_log (
               seq INTEGER PRIMARY KEY AUTOINCREMENT,
               collection_id TEXT,
               kind TEXT NOT NULL,
               payload_json TEXT NOT NULL DEFAULT '{}',
               instance_id TEXT NOT NULL,
               at REAL NOT NULL
           )""",
        "CREATE INDEX ix_change_log_collection ON change_log(collection_id)",
        """CREATE TABLE locks (
               name TEXT PRIMARY KEY,
               instance_id TEXT NOT NULL,
               kind TEXT NOT NULL DEFAULT '',
               acquired_at REAL NOT NULL,
               heartbeat_at REAL NOT NULL
           )""",
        "CREATE TABLE app_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)",
    )),
)


class RegistryError(Exception):
    pass


class RegistryStore:
    def __init__(self, path, instance_id=None):
        self.instance_id = instance_id or uuid.uuid4().hex
        self._conn = connect(path, MIGRATIONS)

    def close(self):
        self._conn.close()

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------
    def create_collection(self, name, frontend, root_path, *, target=None, os=None, arch=None,
                          internal_label="Internal") -> Collection:
        """Collection을 만들고 Internal Storage 하나를 함께 만든다.

        스펙 §9에 따라 External은 처음부터 존재하지 않는다 - 사용자가 나중에
        "Add External Storage"로 추가한다.
        """
        cid = uuid.uuid4().hex
        now = time.time()
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO collections (id,name,frontend,target,os,arch,root_path,ui_state_json,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,'{}',?,?)",
                (cid, name, frontend, target, os, arch, str(root_path), now, now))
            self._conn.execute(
                "INSERT INTO collection_storages (collection_id,storage_id,kind,label,root_path)"
                " VALUES (?,?,?,?,?)",
                (cid, STORAGE_INTERNAL, STORAGE_INTERNAL, internal_label, str(root_path)))
            self._append_change_locked(CHANGE_COLLECTION_CREATED, cid, {"name": name})
        return self.get_collection(cid)

    def get_collection(self, collection_id) -> Collection | None:
        row = self._conn.execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
        if row is None:
            return None
        return self._build_collection(row)

    def list_collections(self) -> list[Collection]:
        rows = self._conn.execute("SELECT * FROM collections ORDER BY created_at").fetchall()
        return [self._build_collection(r) for r in rows]

    def update_collection(self, collection_id, **fields):
        """이름/Target/OS/Arch/root_path/ui_state를 갱신한다.

        Frontend는 여기서 바꾸지 않는다 - 헤더에서 직접 변경하지 않기로 했고(사용자
        결정), 실제 형식 변환은 Convert가 담당한다(스펙 §52).
        """
        allowed = {"name", "target", "os", "arch", "root_path"}
        sets, values = [], []
        for key, value in fields.items():
            if key == "ui_state":
                sets.append("ui_state_json=?")
                values.append(json.dumps(value, ensure_ascii=False))
            elif key in allowed:
                sets.append(f"{key}=?")
                values.append(value)
            else:
                raise RegistryError(f"수정할 수 없는 필드입니다: {key}")
        if not sets:
            return
        sets.append("updated_at=?")
        values.extend([time.time(), collection_id])
        with transaction(self._conn):
            self._conn.execute(f"UPDATE collections SET {','.join(sets)} WHERE id=?", values)
            self._append_change_locked(CHANGE_COLLECTION_UPDATED, collection_id, {"fields": list(fields)})

    def delete_collection(self, collection_id):
        with transaction(self._conn):
            self._conn.execute("DELETE FROM collections WHERE id=?", (collection_id,))
            self._append_change_locked(CHANGE_COLLECTION_DELETED, collection_id, {})

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    def add_storage(self, collection_id, storage_id, *, kind="external", label="", root_path="",
                    volume_key=None, capacity_bytes=None):
        with transaction(self._conn):
            exists = self._conn.execute(
                "SELECT 1 FROM collection_storages WHERE collection_id=? AND storage_id=?",
                (collection_id, storage_id)).fetchone()
            if exists:
                raise RegistryError(f"이미 존재하는 Storage입니다: {storage_id}")
            self._conn.execute(
                "INSERT INTO collection_storages (collection_id,storage_id,kind,label,root_path,volume_key,capacity_bytes)"
                " VALUES (?,?,?,?,?,?,?)",
                (collection_id, storage_id, kind, label, str(root_path), volume_key, capacity_bytes))
            self._append_change_locked(CHANGE_LAYOUT_UPDATED, collection_id, {"storage": storage_id})

    def update_storage(self, collection_id, storage_id, **fields):
        allowed = {"kind", "label", "root_path", "volume_key", "capacity_bytes"}
        unknown = set(fields) - allowed
        if unknown:
            raise RegistryError(f"수정할 수 없는 필드입니다: {sorted(unknown)}")
        if not fields:
            return
        sets = ",".join(f"{k}=?" for k in fields)
        with transaction(self._conn):
            self._conn.execute(
                f"UPDATE collection_storages SET {sets} WHERE collection_id=? AND storage_id=?",
                [*fields.values(), collection_id, storage_id])
            self._append_change_locked(CHANGE_LAYOUT_UPDATED, collection_id, {"storage": storage_id})

    def remove_storage(self, collection_id, storage_id):
        """System이 하나라도 붙어 있으면 거부한다.

        FK로 막지 않고 여기서 검사하는 이유는 오류 메시지를 사용자 언어로 주기
        위해서다 - 어차피 모든 쓰기가 이 클래스를 통과한다.
        """
        if storage_id == STORAGE_INTERNAL:
            raise RegistryError("Internal Storage는 제거할 수 없습니다.")
        with transaction(self._conn):
            attached = self._conn.execute(
                "SELECT system FROM collection_systems WHERE collection_id=? AND storage_id=? ORDER BY system",
                (collection_id, storage_id)).fetchall()
            if attached:
                names = ", ".join(r["system"] for r in attached)
                raise RegistryError(f"이 Storage에 System이 남아 있어 제거할 수 없습니다: {names}")
            self._conn.execute("DELETE FROM collection_storages WHERE collection_id=? AND storage_id=?",
                               (collection_id, storage_id))
            self._append_change_locked(CHANGE_LAYOUT_UPDATED, collection_id, {"storage_removed": storage_id})

    # ------------------------------------------------------------------
    # System
    # ------------------------------------------------------------------
    def upsert_system(self, collection_id, system, storage_id, *,
                      rom_path=None, media_path=None, metadata_path=None):
        with transaction(self._conn):
            self._require_storage(collection_id, storage_id)
            self._conn.execute(
                "INSERT INTO collection_systems (collection_id,system,storage_id,rom_path,media_path,metadata_path)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(collection_id,system) DO UPDATE SET"
                " storage_id=excluded.storage_id, rom_path=excluded.rom_path,"
                " media_path=excluded.media_path, metadata_path=excluded.metadata_path",
                (collection_id, system, storage_id, rom_path, media_path, metadata_path))
            self._append_change_locked(CHANGE_LAYOUT_UPDATED, collection_id, {"system": system})

    def move_system(self, collection_id, system, storage_id):
        """System을 다른 Storage로 옮긴다(스펙 §10의 Drag & Drop이 확정될 때 호출).

        실제 파일 이동은 여기서 하지 않는다 - Plan Apply가 끝난 뒤 배치 정보만
        갱신하는 용도다.
        """
        with transaction(self._conn):
            self._require_storage(collection_id, storage_id)
            cur = self._conn.execute(
                "UPDATE collection_systems SET storage_id=? WHERE collection_id=? AND system=?",
                (storage_id, collection_id, system))
            if cur.rowcount == 0:
                raise RegistryError(f"System을 찾을 수 없습니다: {system}")
            self._append_change_locked(CHANGE_LAYOUT_UPDATED, collection_id,
                                       {"system": system, "storage": storage_id})

    def remove_system(self, collection_id, system):
        with transaction(self._conn):
            self._conn.execute("DELETE FROM collection_systems WHERE collection_id=? AND system=?",
                               (collection_id, system))
            self._append_change_locked(CHANGE_LAYOUT_UPDATED, collection_id, {"system_removed": system})

    def _require_storage(self, collection_id, storage_id):
        row = self._conn.execute(
            "SELECT 1 FROM collection_storages WHERE collection_id=? AND storage_id=?",
            (collection_id, storage_id)).fetchone()
        if row is None:
            raise RegistryError(f"Storage를 찾을 수 없습니다: {storage_id}")

    # ------------------------------------------------------------------
    # 변경 전파 (다중 인스턴스, §9.3)
    # ------------------------------------------------------------------
    def append_change(self, kind, collection_id=None, payload=None) -> int:
        with transaction(self._conn):
            return self._append_change_locked(kind, collection_id, payload)

    def _append_change_locked(self, kind, collection_id, payload) -> int:
        cur = self._conn.execute(
            "INSERT INTO change_log (collection_id,kind,payload_json,instance_id,at) VALUES (?,?,?,?,?)",
            (collection_id, kind, json.dumps(payload or {}, ensure_ascii=False), self.instance_id, time.time()))
        return int(cur.lastrowid)

    def latest_change_seq(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(seq),0) AS seq FROM change_log").fetchone()
        return int(row["seq"])

    def changes_since(self, seq, *, include_own=False, limit=500) -> list[dict]:
        """다른 인스턴스가 만든 변경만 기본으로 돌려준다.

        자기가 쓴 변경까지 받으면 자기 UI를 자기가 다시 그리게 되므로 instance_id로
        걸러낸다. 인덱스가 붙은 seq 범위 조회 1건이라 수 초 주기로 폴링해도 비용이
        사실상 없다.
        """
        sql = "SELECT * FROM change_log WHERE seq>?"
        params = [seq]
        if not include_own:
            sql += " AND instance_id<>?"
            params.append(self.instance_id)
        sql += " ORDER BY seq LIMIT ?"
        params.append(limit)
        return [{"seq": r["seq"], "collection_id": r["collection_id"], "kind": r["kind"],
                 "payload": json.loads(r["payload_json"]), "instance_id": r["instance_id"], "at": r["at"]}
                for r in self._conn.execute(sql, params).fetchall()]

    def prune_changes(self, keep=2000):
        with transaction(self._conn):
            self._conn.execute(
                "DELETE FROM change_log WHERE seq <= (SELECT COALESCE(MAX(seq),0)-? FROM change_log)", (keep,))

    # ------------------------------------------------------------------
    # 잠금 (다중 인스턴스, §9.4)
    # ------------------------------------------------------------------
    def acquire_lock(self, name, *, kind="", ttl_seconds=60.0) -> bool:
        """Collection 단위 Apply/Scan 소유권 같은 프로세스 간 advisory 락.

        heartbeat가 ttl보다 오래 갱신되지 않은 락은 죽은 인스턴스의 것으로 보고
        빼앗는다 - 앱이 강제 종료돼도 락이 영원히 남지 않는다.
        """
        now = time.time()
        with transaction(self._conn):
            row = self._conn.execute("SELECT * FROM locks WHERE name=?", (name,)).fetchone()
            if row is not None and row["instance_id"] != self.instance_id \
                    and (now - row["heartbeat_at"]) < ttl_seconds:
                return False
            self._conn.execute(
                "INSERT INTO locks (name,instance_id,kind,acquired_at,heartbeat_at) VALUES (?,?,?,?,?)"
                " ON CONFLICT(name) DO UPDATE SET instance_id=excluded.instance_id, kind=excluded.kind,"
                " acquired_at=excluded.acquired_at, heartbeat_at=excluded.heartbeat_at",
                (name, self.instance_id, kind, now, now))
            return True

    def refresh_lock(self, name) -> bool:
        with transaction(self._conn):
            cur = self._conn.execute(
                "UPDATE locks SET heartbeat_at=? WHERE name=? AND instance_id=?",
                (time.time(), name, self.instance_id))
            return cur.rowcount > 0

    def release_lock(self, name):
        with transaction(self._conn):
            self._conn.execute("DELETE FROM locks WHERE name=? AND instance_id=?", (name, self.instance_id))

    def lock_owner(self, name) -> dict | None:
        row = self._conn.execute("SELECT * FROM locks WHERE name=?", (name,)).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # 설정
    # ------------------------------------------------------------------
    def get_setting(self, key, default=None):
        row = self._conn.execute("SELECT value_json FROM app_settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else default

    def set_setting(self, key, value):
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO app_settings (key,value_json) VALUES (?,?)"
                " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (key, json.dumps(value, ensure_ascii=False)))

    # ------------------------------------------------------------------
    def _build_collection(self, row) -> Collection:
        cid = row["id"]
        storages = [
            StorageLocation(storage_id=r["storage_id"], kind=r["kind"], label=r["label"],
                            root_path=r["root_path"], volume_key=r["volume_key"],
                            capacity_bytes=r["capacity_bytes"])
            for r in self._conn.execute(
                "SELECT * FROM collection_storages WHERE collection_id=? ORDER BY kind DESC, storage_id", (cid,))
        ]
        systems = [
            SystemEntry(system=r["system"], storage_id=r["storage_id"], rom_path=r["rom_path"],
                        media_path=r["media_path"], metadata_path=r["metadata_path"])
            for r in self._conn.execute(
                "SELECT * FROM collection_systems WHERE collection_id=? ORDER BY system", (cid,))
        ]
        return Collection(
            id=cid, name=row["name"], frontend=row["frontend"], root_path=row["root_path"],
            target=row["target"], os=row["os"], arch=row["arch"],
            storages=storages, systems=systems, ui_state=json.loads(row["ui_state_json"]),
        )
