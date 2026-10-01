"""Local Archive paste recovery: SQLite snapshot plus only touched files.

Shared snapshots use the existing digest CAS. A changed shared snapshot or
changed file blocks restoration before any bytes are modified.
"""
from contextlib import contextmanager, closing
from contextvars import ContextVar
from pathlib import Path
import json
import os
import shutil
import sqlite3
import time
import logging

from adapters import get_adapter
from app.archive import projection, shared_cache
from app.plan.paste_journal import supports_local_undo
from app.plan import process_owner
from app.plan import journal_index

log = logging.getLogger(__name__)
_active = ContextVar("archive_undo", default=None)


def state(path):
    try:
        stat = Path(path).stat()
        return [stat.st_size, stat.st_mtime_ns, stat.st_ino]
    except FileNotFoundError:
        return None


def before_copy(destination, moved=False):
    active = _active.get()
    if active:
        active.capture(destination, moved=moved)


def before_publish_file(destination, temporary):
    active = _active.get()
    if active:
        active.expect_file(destination, state(temporary))


def protect_existing(destination):
    active = _active.get()
    if active:
        item = active.data["files"][str(Path(destination).absolute())]
        if item.get("moved") and Path(destination).exists():
            os.replace(destination, item["backup"])


def before_shared_publish(store):
    active = _active.get()
    if active:
        active.prepare_publish(store)


def delete_file(path):
    active = _active.get()
    if active:
        active.remove(path)
    else:
        Path(path).unlink(missing_ok=True)


def current_transaction():
    return _active.get()


def track_temporary(destination, temporary):
    tx = current_transaction()
    if tx:
        tx.data.setdefault("temporaryFiles", {})[str(temporary)] = str(Path(destination).resolve().parent)
        tx.save()


class ArchiveUndo:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def records(self, config):
        rows = []
        for data in journal_index.records(self.root):
            if data.get("config") == config:
                rows.append(data)
        return sorted(rows, key=lambda row: row["createdAt"])

    def latest(self, config):
        rows = [row for row in self.records(config) if row["status"] == "committed"]
        return rows[-1]["id"] if rows else None

    def latest_redo(self, config):
        rows = [row for row in self.records(config) if row["status"] == "undone" and row.get("redoReady")]
        return max(rows, key=lambda row: row.get("undoneAt", 0))["id"] if rows else None

    def pending(self, config):
        return [row for row in self.records(config) if row["status"] in {"running", "restoring", "redoing", "recovery_failed"}]

    def begin(self, operation_id, store, config, systems, *, allow_network=False, action="paste"):
        if not allow_network and not supports_local_undo([config["archiveDir"], config.get("romDir")]):
            raise ValueError("네트워크 Archive의 자동 실행 취소는 지원하지 않습니다.")
        if self.pending(config):
            raise ValueError("Archive 작업이 진행 중이거나 복구가 필요합니다. Settings > Advanced > 파일 작업 복구를 확인하세요.")
        directory = self.root / operation_id
        directory.mkdir(exist_ok=False)
        store.backup_to(directory / "before.db")
        shared = shared_cache.snapshot_path(config["archiveDir"])
        digest = shared_cache.fingerprint(shared) if shared.is_file() else None
        tx = ArchiveTransaction(directory, {
            "id": operation_id, "config": config, "createdAt": time.time(),
            "status": "running", "owner": process_owner.owner(), "files": {}, "sharedBefore": digest, "action": action,
            "sharedExpected": digest, "databaseAfter": shared_cache._store_snapshot_digest(store),
        })
        tx.data["databaseBefore"] = tx.data["databaseAfter"]
        tx.save()
        adapter = get_adapter(config["frontend"])
        collection = projection.collection_for(config)
        for system in set(systems):
            tx.capture(adapter.layout(collection, system).metadata_file, index=True)
        tx.on_commit = getattr(self, "on_commit", None)
        return tx

    def load(self, operation_id):
        directory = self.root / operation_id
        return ArchiveTransaction(directory, json.loads(
            (directory / "operation.json").read_text(encoding="utf-8")))

    def recover(self, store, config):
        for data in self.pending(config):
            if data["status"] != "recovery_failed" and process_owner.alive(data):
                continue
            self.load(data["id"]).restore(store)


class ArchiveTransaction:
    def __init__(self, directory, data):
        self.directory, self.data = directory, data

    def save(self):
        pending = self.directory / "operation.json.tmp"
        with pending.open("w", encoding="utf-8") as stream:
            json.dump(self.data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, self.directory / "operation.json")
        journal_index.update(self.directory.parent, self.directory, self.data)

    @contextmanager
    def tracking(self):
        token = _active.set(self)
        try:
            yield
        finally:
            _active.reset(token)

    def capture(self, destination, index=False, moved=False):
        destination = Path(destination).absolute()
        roots = [Path(root).resolve() for root in
                 (self.data["config"]["archiveDir"], self.data["config"].get("romDir"), *self.data.get("extraRoots", [])) if root]
        resolved = destination.resolve()
        if destination.is_symlink() or not any(resolved.is_relative_to(root) for root in roots):
            raise ValueError(f"Archive가 소유하지 않은 경로는 자동 복원할 수 없습니다: {destination}")
        path = str(destination)
        if path in self.data["files"]:
            return
        before = state(path)
        backup = destination.with_name(destination.name + f".{self.data['id']}.rms-backup") if moved else self.directory / f"file-{len(self.data['files'])}.bak"
        if before is not None and not moved:
            shutil.copy2(path, backup)
            if state(path) != before:
                raise ValueError(f"백업 중 파일이 바뀌었습니다: {path}")
        self.data["files"][path] = {
            "before": before, "after": before, "backup": str(backup) if before else None,
            "index": index, "resolved": str(resolved), "moved": moved,
        }
        self.save()

    def remove(self, path):
        path = Path(path).absolute()
        if not path.is_file():
            return
        self.capture(path, moved=True)
        item = self.data["files"][str(path)]
        item["after"] = None
        self.save()
        if item["moved"]:
            os.replace(path, item["backup"])
        else:
            path.unlink()

    def rename(self, source, destination):
        source, destination = Path(source).absolute(), Path(destination).absolute()
        root = Path(self.data["config"].get("romDir") or self.data["config"]["archiveDir"]).resolve()
        if (not source.resolve().is_relative_to(root) or not destination.resolve().is_relative_to(root)
                or source.is_symlink() or destination.exists()):
            raise ValueError("소유 ROM 경로가 아니거나 대상 파일이 이미 있습니다.")
        pair = {"source": str(source), "destination": str(destination), "state": state(source)}
        self.data.setdefault("renames", []).append(pair)
        self.save()
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.rename(source, destination)

    def expect_file(self, destination, expected):
        path = str(Path(destination).absolute())
        self.data["files"][path]["after"] = expected
        self.save()

    def prepare_publish(self, store):
        digest = shared_cache._store_snapshot_digest(store)
        self.data["databaseAfter"] = digest
        self.data["sharedExpected"] = digest
        for path, item in self.data["files"].items():
            if str(Path(path).resolve()) != item["resolved"] or Path(path).is_symlink():
                raise ValueError(f"Archive 파일의 연결 경로가 바뀌었습니다: {path}")
            if item["index"]:
                item["after"] = state(path)
        self.save()

    def commit(self, store):
        self.prepare_publish(store)
        store.backup_to(self.directory / "after.db")
        self.data["committedDatabase"] = self.data["databaseAfter"]
        self.data["committedShared"] = self.data["sharedExpected"]
        for path, item in self.data["files"].items():
            item["committedState"] = item["after"]
        self.data["status"] = "committed"
        self.save()
        for summary in journal_index.records(self.directory.parent):
            if summary.get("config") != self.data["config"] or summary.get("status") != "undone":
                continue
            record = self.directory.parent / summary["id"] / "operation.json"
            previous = json.loads(record.read_text(encoding="utf-8"))
            if previous.get("config") == self.data["config"] and previous["status"] == "undone":
                previous["redoReady"] = False
                ArchiveTransaction(record.parent, previous).save()

                for destination, item in previous.get("files", {}).items():
                    raw = item.get("redo")
                    expected = destination + f".{previous['id']}.rms-redo"
                    try:
                        if (raw == expected and not Path(raw).is_symlink()
                                and str(Path(destination).resolve()) == item.get("resolved")
                                and state(raw) == item.get("committedState")):
                            Path(raw).unlink(missing_ok=True)
                            item.pop("redo", None)
                    except OSError:
                        log.warning("Invalidated Archive Redo retained path=%s", raw, exc_info=True)
                ArchiveTransaction(record.parent, previous).save()

        callback = getattr(self, "on_commit", None)
        if callback:
            callback(self.data)

    def failed(self, store):
        # Called while the Archive connection lock and edit lease remain held.
        self.data["databaseAfter"] = shared_cache._store_snapshot_digest(store)
        for path, item in self.data["files"].items():
            if str(Path(path).resolve()) != item["resolved"] or Path(path).is_symlink():
                raise ValueError(f"Archive 파일의 연결 경로가 바뀌었습니다: {path}")
            if item["index"]:
                item["after"] = state(path)
        self.save()

    def restore(self, store):
        if self.data.get("status") == "recovery_failed":
            self.data["status"] = self.data.get("recoveryStatus", "running")
        try:
            return self._restore(store)
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.data["recoveryStatus"] = self.data["status"]
            self.data["status"] = "recovery_failed"
            self.data["recoveryError"] = str(exc)
            self.save()
            raise

    def _restore(self, store):
        cfg = self.data["config"]
        shared = shared_cache.snapshot_path(cfg["archiveDir"])
        current = shared_cache.fingerprint(shared) if shared.is_file() else None
        allowed_shared = {self.data["sharedBefore"], self.data["sharedExpected"]}
        if self.data["status"] == "restoring":
            allowed_shared.add(self.data.get("sharedRestoreExpected"))
        if current not in allowed_shared:
            raise ValueError("다른 PC에서 Archive가 바뀌어 실행 취소할 수 없습니다.")
        allowed_databases = [self.data["databaseAfter"]]
        if self.data["status"] == "restoring":
            allowed_databases.append(self.data["databaseBefore"])
        if shared_cache._store_snapshot_digest(store) not in allowed_databases:
            raise ValueError("Archive DB가 바뀌었거나 복구 상태를 확인할 수 없습니다. 백업을 보존했습니다.")
        for path, item in self.data["files"].items():
            if str(Path(path).resolve()) != item["resolved"] or Path(path).is_symlink():
                raise ValueError("복구 대상 경로가 바뀌었습니다. 백업을 보존했습니다.")
            allowed = [item["before"], item["after"]]
            if "restoreExpected" in item:
                allowed.append(item["restoreExpected"])
            if item.get("moved") and item.get("backup") and state(item["backup"]) == item["before"]:
                allowed.append(None)
            if self.data["status"] == "restoring" and item.get("redo") and Path(item["redo"]).is_file():
                allowed.append(None)
            if state(path) not in allowed:
                raise ValueError(f"작업 후 파일이 바뀌어 실행 취소할 수 없습니다: {path}")
            if item["backup"] and not Path(item["backup"]).is_file() and not (item.get("moved") and
                    state(path) in (item.get("restoreExpected"), item["before"])):
                raise ValueError(f"실행 취소 백업이 없습니다: {path}")
        for pair in self.data.get("renames", []):
            if not ((state(pair["source"]) is None and state(pair["destination"]) == pair["state"])
                    or (state(pair["source"]) == pair["state"] and state(pair["destination"]) is None)):
                raise ValueError("이름 변경 후 ROM이 바뀌어 복원할 수 없습니다.")
        before_db = self.directory / "before.db"
        if not before_db.is_file():
            raise ValueError("Archive DB 백업이 없습니다.")
        with closing(sqlite3.connect(before_db.as_uri() + "?mode=ro", uri=True)) as check:
            if (check.execute("PRAGMA quick_check").fetchone()[0] != "ok" or
                    not check.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rom_identities'").fetchone()):
                raise ValueError("Archive DB 백업이 손상되었습니다.")
        # Retain the current DB as well: restoration errors never discard it.
        for path, parent in self.data.get("temporaryFiles", {}).items():
            temporary = Path(path)
            if temporary.is_symlink() or str(temporary.resolve().parent) != parent or not temporary.name.endswith(".rms-part"):
                raise ValueError("중단된 임시 파일 경로가 바뀌었습니다.")
        for path in self.data.get("temporaryFiles", {}):
            Path(path).unlink(missing_ok=True)
        if not (self.directory / "restore-from.db").exists():
            store.backup_to(self.directory / "restore-from.db")
        self.data["redoReady"] = self.data.get("redoReady", self.data["status"] == "committed")
        self.data["status"] = "restoring"
        self.save()
        for pair in reversed(self.data.get("renames", [])):
            if Path(pair["destination"]).exists():
                os.rename(pair["destination"], pair["source"])
        for path, item in self.data["files"].items():
            destination = Path(path)
            if item.get("moved") and item["backup"] and not Path(item["backup"]).exists() and state(path) == item["before"]:
                item["after"] = state(path)
                self.save()
                continue
            if self.data["redoReady"] and destination.is_file() and "redo" not in item:
                redo = destination.with_name(destination.name + f".{self.data['id']}.rms-redo")
                item["redo"] = str(redo)
                self.save()
                os.replace(destination, redo)
            if item["backup"]:
                temporary = destination.with_name(destination.name + f".{self.data['id']}.restore")
                if Path(item["backup"]).exists():
                    if item.get("moved"):
                        item["restoreExpected"] = state(item["backup"])
                        self.save()
                        os.replace(item["backup"], destination)
                    else:
                        shutil.copy2(item["backup"], temporary)
                        item["restoreExpected"] = state(temporary)
                        self.save()
                        os.replace(temporary, destination)
            else:
                destination.unlink(missing_ok=True)
            item["after"] = state(destination)
            self.save()
        with closing(sqlite3.connect(before_db.as_uri() + "?mode=ro", uri=True)) as incoming:
            if incoming.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Archive DB 백업이 손상되었습니다.")
            incoming.backup(store._conn._conn)
        self.data["databaseAfter"] = shared_cache._store_snapshot_digest(store)
        self.data["sharedRestoreExpected"] = self.data["databaseAfter"]
        self.save()
        if current != self.data["sharedBefore"]:
            if self.data["sharedBefore"] is None:
                if shared_cache.fingerprint(shared) != current:
                    raise ValueError("공유 Archive가 복구 중 바뀌었습니다.")
                shared.unlink()
            else:
                published = shared_cache.publish(store, cfg["archiveDir"], current)
                if published["status"] != "published":
                    raise ValueError("공유 Archive를 복구하지 못했습니다. 백업을 보존했습니다.")
        self.data["status"] = "undone"
        self.data["undoneAt"] = time.time()
        self.save()
        previous = []
        for data in journal_index.records(self.directory.parent):
            if (data.get("status") == "committed" and data.get("config") == cfg
                    and data["createdAt"] < self.data["createdAt"]):
                previous.append((data["createdAt"], self.directory.parent / data["id"]))
        if previous:
            _, directory = max(previous, key=lambda row: row[0])
            data = json.loads((directory / "operation.json").read_text(encoding="utf-8"))
            for path, item in self.data["files"].items():
                older = data["files"].get(path)
                if older and older["after"] == item["before"]:
                    older["after"] = state(path)
            ArchiveTransaction(directory, data).save()
        return shared_cache.fingerprint(shared) if shared.is_file() else None

    def redo(self, store):
        if self.data["status"] != "undone" or not self.data.get("redoReady"):
            raise ValueError("다시 실행할 작업이 없습니다.")
        cfg = self.data["config"]
        shared = shared_cache.snapshot_path(cfg["archiveDir"])
        digest = shared_cache.fingerprint(shared) if shared.is_file() else None
        if shared_cache._store_snapshot_digest(store) != self.data["databaseAfter"]:
            raise ValueError("실행 취소 후 DB가 바뀌어 다시 실행할 수 없습니다.")
        if digest not in {self.data["sharedBefore"], self.data.get("sharedRestoreExpected")}:
            raise ValueError("다른 PC에서 Archive가 바뀌었습니다.")
        for path, item in self.data["files"].items():
            if str(Path(path).resolve()) != item["resolved"] or Path(path).is_symlink():
                raise ValueError("다시 실행할 대상 경로가 바뀌었습니다.")
            if state(path) != item["after"]:
                raise ValueError("실행 취소 후 파일이 바뀌었습니다.")
            if item.get("redo") and state(item["redo"]) != item["committedState"]:
                raise ValueError("다시 실행할 파일 백업이 바뀌었습니다.")
        for pair in self.data.get("renames", []):
            if state(pair["source"]) != pair["state"] or Path(pair["destination"]).exists():
                raise ValueError("이름 변경 원본이 바뀌었습니다.")
        with closing(sqlite3.connect((self.directory / "after.db").as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("다시 실행할 DB 백업이 손상되었습니다.")
        self.data["status"] = "redoing"
        self.save()
        for path, item in self.data["files"].items():
            destination = Path(path)
            if item.get("moved") and destination.exists():
                os.replace(destination, item["backup"])
            elif destination.exists():
                destination.unlink()
            if item.get("redo"):
                os.replace(item["redo"], destination)
            item["after"] = state(destination)
            item.pop("redo", None)
            self.save()
        for pair in self.data.get("renames", []):
            os.rename(pair["source"], pair["destination"])
        with closing(sqlite3.connect(str(self.directory / "after.db"))) as db:
            db.backup(store._conn._conn)
        result = shared_cache.publish(store, cfg["archiveDir"], digest)
        if result["status"] != "published":
            raise ValueError("다시 실행한 공유 DB를 게시하지 못했습니다.")
        self.data["databaseAfter"] = shared_cache._store_snapshot_digest(store)
        self.data["sharedExpected"] = result["digest"]
        self.data["status"] = "committed"
        self.save()
