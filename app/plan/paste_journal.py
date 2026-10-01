"""로컬 붙여넣기의 중단 복구와 직전 작업 되돌리기.

ROM 원본은 목적지 옆의 고유한 백업 이름으로 *이동*한다. 여기에는 작업 기록과
작은 Frontend 인덱스 사본만 둔다. 따라서 대형 ROM을 Undo 때문에 두 번 복사하지
않는다. 중단된 작업은 다음 시작 때 복구한다.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import ctypes
import logging
from pathlib import Path

from adapters import get_adapter
from app.plan.builder import add_destinations
from app.plan import process_owner
from app.plan import journal_index

log = logging.getLogger(__name__)


def _state(path):
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return {"size": stat.st_size, "mtimeNs": stat.st_mtime_ns,
            "fileId": getattr(stat, "st_ino", 0)}


def supports_local_undo(paths):
    """로컬 드라이브에서만 자동 Undo를 제공한다. UNC/매핑 SMB/MTP는 제외."""
    for raw in paths:
        if not raw:
            continue
        path = str(raw).replace("/", "\\")
        if path.startswith("\\\\") or path.startswith("mtp:"):
            return False
        if os.name == "nt":
            anchor = Path(raw).anchor
            if not anchor or ctypes.windll.kernel32.GetDriveTypeW(anchor) == 4:
                return False
    return True


class PasteJournal:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _save(self, directory, data):
        path = directory / "operation.json"
        pending = directory / "operation.json.tmp"
        if data.get("owner"):
            data["owner"]["heartbeat"] = time.time()
        with pending.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
        journal_index.update(self.root, directory, data)

    def begin(self, operation_id, collection_id, collection, plan, *, extra_paths=()):
        if self.pending(collection_id):
            raise ValueError("파일 작업이 진행 중이거나 복구가 필요합니다. Settings > Advanced > 파일 작업 복구를 확인하세요.")
        directory = self.root / operation_id
        directory.mkdir(parents=True, exist_ok=False)
        adapter = get_adapter(collection.frontend)
        suffix = f".{operation_id}.rms-backup"
        files, indexes = {}, {}
        for entry in plan.entries:
            layout = adapter.layout(collection, entry.system)
            if layout.metadata_file:
                index = Path(layout.metadata_file)
                if str(index) not in indexes:
                    copy = directory / f"index-{len(indexes)}.bak"
                    if index.is_file():
                        shutil.copy2(index, copy)
                    indexes[str(index)] = {"copy": str(copy) if index.is_file() else None}
            for _source, destination, _size, _kind in add_destinations(entry, layout, adapter):
                destination = Path(destination)
                files[str(destination)] = {
                    "existed": destination.exists(),
                    "backup": str(destination) + suffix,
                }
        for path in extra_paths:
            destination = Path(path)
            files[str(destination)] = {
                "existed": destination.exists(),
                "backup": str(destination) + suffix,
            }
        data = {"id": operation_id, "collectionId": collection_id,
                "action": plan.entries[0].op if plan.entries else "paste",
                "systems": sorted({entry.system for entry in plan.entries}),
                "createdAt": time.time(), "status": "running", "owner": process_owner.owner(), "files": files,
                "indexes": indexes,
                "preFiles": {path: _state(path) for path in files},
                "preIndexes": {path: _state(path) for path in indexes}}
        self._save(directory, data)
        log.info("File operation journal started operation=%s collection=%s files=%d", operation_id, collection_id, len(files))
        return suffix

    def record_renames(self, operation_id, pairs):
        directory = self.root / operation_id
        data = json.loads((directory / "operation.json").read_text(encoding="utf-8"))
        data["renames"] = [{"source": str(source), "destination": str(destination),
                            "before": _state(source)} for source, destination in pairs]
        data["action"] = "rename"
        self._save(directory, data)

    def include_source(self, operation_id, collection, plan, paths):
        """Record both sides before a cross-Collection move starts."""
        directory = self.root / operation_id
        data = json.loads((directory / "operation.json").read_text(encoding="utf-8"))
        adapter = get_adapter(collection.frontend)
        for system in {entry.system for entry in plan.entries}:
            index = Path(adapter.layout(collection, system).metadata_file)
            if str(index) not in data["indexes"]:
                saved = directory / f"index-{len(data['indexes'])}.bak"
                if index.is_file():
                    shutil.copy2(index, saved)
                data["indexes"][str(index)] = {"copy": str(saved) if index.is_file() else None}
                data["preIndexes"][str(index)] = _state(index)
        for path in paths:
            path = str(path)
            if path not in data["files"]:
                data["files"][path] = {"existed": Path(path).exists(),
                                       "backup": path + f".{operation_id}.rms-backup"}
                data["preFiles"][path] = _state(path)
        data["relatedCollections"] = {collection.id: sorted({e.system for e in plan.entries})}
        data["action"] = "move"
        self._save(directory, data)

    def commit(self, operation_id):
        directory = self.root / operation_id
        data = json.loads((directory / "operation.json").read_text(encoding="utf-8"))
        data["postFiles"] = {path: _state(path) for path in data["files"]}
        data["postIndexes"] = {path: _state(path) for path in data["indexes"]}
        data["replaced"] = [path for path, details in data["files"].items()
                            if Path(details["backup"]).exists()]
        data["status"] = "committed"
        data["redoReady"] = False
        for index, path in enumerate(data["indexes"]):
            if Path(path).is_file():
                saved = directory / f"index-after-{index}.bak"
                shutil.copy2(path, saved)
                data["indexes"][path]["afterCopy"] = str(saved)
        self._save(directory, data)
        log.info("File operation committed operation=%s backups=%d", operation_id, len(data["replaced"]))
        for summary in journal_index.records(self.root):
            if summary.get("status") != "undone" or summary.get("collectionId") != data["collectionId"]:
                continue
            record = self.root / summary["id"] / "operation.json"
            previous = self.details(summary["id"])
            if previous.get("collectionId") == data["collectionId"] and previous.get("status") == "undone":
                previous["redoReady"] = False
                for destination, item in previous.get("files", {}).items():
                    raw = item.get("redo")
                    try:
                        if (raw == destination + f".{previous['id']}.rms-backup.rms-redo"
                                and not Path(raw).is_symlink()
                                and _state(raw) == previous.get("postFiles", {}).get(destination)):
                            Path(raw).unlink(missing_ok=True)
                            item.pop("redo", None)
                    except OSError:
                        log.warning("Invalidated Collection Redo retained path=%s", raw, exc_info=True)
                self._save(record.parent, previous)

        callback = getattr(self, "on_commit", None)
        if callback:
            callback(data)

    def _restore(self, directory, data):
        keep_redo = data["status"] == "committed"
        for item in reversed(data.get("renames", [])):
            source, destination = Path(item["source"]), Path(item["destination"])
            if destination.exists() and not source.exists():
                if _state(destination) != item["before"]:
                    raise ValueError(f"이름 변경 후 파일이 바뀌었습니다: {destination}")
                os.replace(destination, source)
            elif destination.exists() and source.exists():
                raise ValueError(f"원래 이름의 파일이 다시 생겨 복원할 수 없습니다: {source}")
        for path, details in data["files"].items():
            destination, backup = Path(path), Path(details["backup"])
            if keep_redo and not data.get("renames") and destination.is_file() and (backup.exists() or not details["existed"]):
                redo = Path(str(backup) + ".rms-redo")
                details["redo"] = str(redo)
                self._save(directory, data)
                os.replace(destination, redo)
            staging = Path(str(backup) + ".rms-part")
            if staging.exists():
                staging.unlink()
            if backup.exists():
                if destination.exists():
                    destination.unlink()
                os.replace(backup, destination)
            elif not details["existed"] and destination.exists():
                destination.unlink()
        for path, details in data["indexes"].items():
            destination = Path(path)
            copy = Path(details["copy"]) if details["copy"] else None
            if copy and copy.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(copy, destination)
            elif destination.exists():
                destination.unlink()
        data["status"] = "recovered" if data["status"] == "running" else "undone"
        data["redoReady"] = keep_redo
        data["undoneAt"] = time.time()
        data["undoFiles"] = {path: _state(path) for path in data["files"]}
        data["undoIndexes"] = {path: _state(path) for path in data["indexes"]}
        self._save(directory, data)
        log.info("File operation restored operation=%s status=%s", data["id"], data["status"])
        self._refresh_predecessor(data)

    def undo(self, operation_id):
        directory = self.root / operation_id
        data = json.loads((directory / "operation.json").read_text(encoding="utf-8"))
        if data["status"] != "committed":
            raise ValueError("되돌릴 수 있는 완료된 작업이 아닙니다.")
        if any(not Path(data["files"][path]["backup"]).exists()
               for path in data.get("replaced", [])):
            raise ValueError("기존 파일 백업이 없어 자동 복원할 수 없습니다.")
        for path, saved in data["postFiles"].items():
            if _state(path) != saved:
                raise ValueError(f"작업 후 파일이 바뀌어 자동 복원할 수 없습니다: {path}")
        for path, saved in data["postIndexes"].items():
            if _state(path) != saved:
                raise ValueError(f"작업 후 메타데이터가 바뀌어 자동 복원할 수 없습니다: {path}")
        self._restore(directory, data)
        return {"collectionId": data["collectionId"], "systems": data.get("systems", []),
                "relatedCollections": data.get("relatedCollections", {})}

    def _refresh_predecessor(self, undone):
        """Index restore copies change file IDs. Refresh only proven prior states."""
        previous_id = self.latest_committed(undone["collectionId"])
        if not previous_id:
            return
        directory = self.root / previous_id
        previous = json.loads((directory / "operation.json").read_text(encoding="utf-8"))
        for post_key, pre_key in (("postFiles", "preFiles"), ("postIndexes", "preIndexes")):
            for path, before in undone.get(pre_key, {}).items():
                if path in previous.get(post_key, {}) and previous[post_key][path] == before:
                    previous[post_key][path] = _state(path)
        self._save(directory, previous)

    def rollback_running(self, operation_id):
        directory = self.root / operation_id
        data = json.loads((directory / "operation.json").read_text(encoding="utf-8"))
        if data["status"] == "running":
            try:
                self._restore(directory, data)
            except (OSError, ValueError) as exc:
                data["recoveryStatus"] = data["status"]
                data["status"] = "recovery_failed"
                data["recoveryError"] = str(exc)
                self._save(directory, data)
                raise

    def details(self, operation_id):
        return json.loads((self.root / operation_id / "operation.json").read_text(encoding="utf-8"))

    def retry_recovery(self, operation_id, *, force_unknown_owner=False):
        directory = self.root / operation_id
        data = self.details(operation_id)
        if force_unknown_owner:
            if data.get("status") not in {"running", "redoing"} or process_owner.status(data) != "unknown":
                raise ValueError("소유자 확인 불가 기록에만 수동 복구를 사용할 수 있습니다.")
            data["manualOwnerRecovery"] = True
        elif data.get("status") != "recovery_failed":
            raise ValueError("복구 실패 기록이 아닙니다.")
        data["status"] = data.get("recoveryStatus", data["status"] if force_unknown_owner else "running")
        try:
            if data.get("manualOwnerRecovery"):
                for filename, details in data["files"].items():
                    allowed = (data.get("preFiles", {}).get(filename), None)
                    if data["status"] == "redoing":
                        allowed = (data.get("undoFiles", {}).get(filename), data.get("postFiles", {}).get(filename), None)
                    if _state(filename) not in allowed:
                        raise ValueError("파일 상태를 확인할 수 없어 수동 복구를 중단했습니다. 백업을 보존했습니다.")
                    backup = details.get("backup")
                    if backup and Path(backup).exists() and _state(backup) != data.get("preFiles", {}).get(filename):
                        raise ValueError("복구 백업이 바뀌었습니다. 백업을 보존했습니다.")
                for filename in data["indexes"]:
                    if _state(filename) != data.get("preIndexes", {}).get(filename):
                        raise ValueError("메타데이터 파일 상태를 확인할 수 없습니다. 백업을 보존했습니다.")
            self._restore(directory, data)
        except (OSError, ValueError) as exc:
            data["recoveryStatus"] = data["status"]
            data["status"] = "recovery_failed"
            data["recoveryError"] = str(exc)
            self._save(directory, data)
            raise

    def pending(self, collection_id):
        rows = []
        for data in journal_index.records(self.root):
            if (data.get("collectionId") == collection_id or collection_id in data.get("relatedCollections", {})) and data.get("status") in {"running", "redoing", "recovery_failed"}:
                rows.append(data)
        return rows

    def latest_committed(self, collection_id):
        matches = []
        for data in journal_index.records(self.root):
            if data.get("collectionId") == collection_id and data.get("status") == "committed":
                matches.append((data.get("createdAt", 0), data["id"]))
        return max(matches)[1] if matches else None

    def latest_redo(self, collection_id):
        rows = []
        for data in journal_index.records(self.root):
            if data.get("collectionId") == collection_id and data.get("status") == "undone" and data.get("redoReady"):
                rows.append((data.get("undoneAt", 0), data["id"]))
        return max(rows)[1] if rows else None

    def redo(self, operation_id):
        directory = self.root / operation_id
        data = self.details(operation_id)
        if data["status"] != "undone" or not data.get("redoReady"):
            raise ValueError("다시 실행할 작업이 없습니다.")
        for states in (data["undoFiles"], data["undoIndexes"]):
            if any(_state(path) != saved for path, saved in states.items()):
                raise ValueError("실행 취소 후 파일이 바뀌어 다시 실행할 수 없습니다.")
        for path, item in data["files"].items():
            if item.get("redo") and _state(item["redo"]) != data["postFiles"][path]:
                raise ValueError("다시 실행할 파일 백업이 바뀌었습니다.")
        data["status"] = "redoing"
        data["owner"] = process_owner.owner()
        self._save(directory, data)
        if data.get("renames"):
            for pair in data["renames"]:
                os.rename(pair["source"], pair["destination"])
        else:
            for path, item in data["files"].items():
                if not item.get("redo") and data["postFiles"].get(path) == data["undoFiles"].get(path):
                    continue
                destination = Path(path)
                if destination.exists():
                    os.replace(destination, item["backup"])
                if item.get("redo"):
                    os.replace(item["redo"], destination)
        for path, item in data["indexes"].items():
            if item.get("afterCopy"):
                shutil.copy2(item["afterCopy"], path)
            else:
                Path(path).unlink(missing_ok=True)
        data["postFiles"] = {path: _state(path) for path in data["files"]}
        data["postIndexes"] = {path: _state(path) for path in data["indexes"]}
        data["status"] = "committed"
        data["redoReady"] = False
        self._save(directory, data)
        return data

    def recover_interrupted(self):
        recovered = []
        for path in self.root.glob("*/operation.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("status") in {"running", "redoing"} and process_owner.alive(data):
                    continue
                if data.get("status") == "redoing":
                    for filename in data["files"]:
                        current = _state(filename)
                        allowed = (data.get("undoFiles", {}).get(filename), data.get("postFiles", {}).get(filename), None)
                        if current not in allowed:
                            raise ValueError("중단된 Redo 파일이 외부에서 바뀌었습니다.")
                    self._restore(path.parent, data)
                    recovered.append(data["id"])
                elif data.get("status") == "running":
                    self._restore(path.parent, data)
                    recovered.append(data["id"])
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                # 실패한 기록은 그대로 둔다. 다음 시작에서도 재시도할 수 있고,
                # 작업자가 기록과 파일을 대조할 수 있다.
                log.exception("Interrupted file operation recovery failed journal=%s", path)
                try:
                    failed = json.loads(path.read_text(encoding="utf-8"))
                    failed["recoveryStatus"] = failed.get("recoveryStatus", failed.get("status"))
                    failed["status"] = "recovery_failed"
                    failed["recoveryError"] = str(exc)
                    self._save(path.parent, failed)
                except (OSError, ValueError):
                    log.exception("Could not persist recovery failure journal=%s", path)
                continue
        return recovered
