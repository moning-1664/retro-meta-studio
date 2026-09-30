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
        pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(pending, path)

    def begin(self, operation_id, collection_id, collection, plan, *, extra_paths=()):
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
                "systems": sorted({entry.system for entry in plan.entries}),
                "createdAt": time.time(), "status": "running", "files": files,
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
        self._save(directory, data)

    def commit(self, operation_id):
        directory = self.root / operation_id
        data = json.loads((directory / "operation.json").read_text(encoding="utf-8"))
        data["postFiles"] = {path: _state(path) for path in data["files"]}
        data["postIndexes"] = {path: _state(path) for path in data["indexes"]}
        data["replaced"] = [path for path, details in data["files"].items()
                            if Path(details["backup"]).exists()]
        data["status"] = "committed"
        self._save(directory, data)
        log.info("File operation committed operation=%s backups=%d", operation_id, len(data["replaced"]))

    def _restore(self, directory, data):
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
            self._restore(directory, data)

    def details(self, operation_id):
        return json.loads((self.root / operation_id / "operation.json").read_text(encoding="utf-8"))

    def latest_committed(self, collection_id):
        matches = []
        for path in self.root.glob("*/operation.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("collectionId") == collection_id and data.get("status") == "committed":
                matches.append((data.get("createdAt", 0), data["id"]))
        return max(matches)[1] if matches else None

    def recover_interrupted(self):
        recovered = []
        for path in self.root.glob("*/operation.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("status") == "running":
                    self._restore(path.parent, data)
                    recovered.append(data["id"])
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                # 실패한 기록은 그대로 둔다. 다음 시작에서도 재시도할 수 있고,
                # 작업자가 기록과 파일을 대조할 수 있다.
                log.exception("Interrupted file operation recovery failed journal=%s", path)
                continue
        return recovered
