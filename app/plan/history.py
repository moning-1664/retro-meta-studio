"""Read and explicitly discard completed recovery records; keep pending ones."""
from pathlib import Path
import json
import shutil


def listing(api, collection_id):
    rows = []
    cfg = api._archive_config()
    for kind, root in (("collection", api._paste_journal.root), ("archive", api._archive_journal.root)):
        for record in root.glob("*/operation.json"):
            try:
                data = json.loads(record.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            relevant = (data.get("collectionId") == collection_id or collection_id in data.get("relatedCollections", {}))
            if kind == "archive":
                relevant = data.get("config") == cfg and (collection_id == "__archive__" or relevant)
            if not relevant:
                continue
            files = list(record.parent.rglob("*"))
            for item in data.get("files", {}).values():
                files.extend(Path(item[key]) for key in ("backup", "redo") if item.get(key))
            seen = set()
            size = 0
            for path in files:
                if str(path) in seen:
                    continue
                seen.add(str(path))
                if path.is_file():
                    size += path.stat().st_size
            rows.append({"id": data["id"], "kind": kind, "status": data["status"],
                "createdAt": data["createdAt"], "action": data.get("action", "file-operation"),
                "bytes": size, "canDiscard": data["status"] in {"committed", "undone", "recovered"}})
    return sorted(rows, key=lambda row: row["createdAt"], reverse=True)


def discard(api, collection_id, operation_ids):
    permitted = {row["id"]: row for row in listing(api, collection_id)}
    cleanup = []
    for operation_id in operation_ids:
        row = permitted.get(operation_id)
        if not row or not row["canDiscard"]:
            raise ValueError("진행 중이거나 복구가 필요한 기록은 삭제할 수 없습니다.")
    for operation_id in operation_ids:
        row = permitted[operation_id]
        root = api._archive_journal.root if row["kind"] == "archive" else api._paste_journal.root
        directory = root / operation_id
        if not directory.resolve().is_relative_to(root.resolve()) or directory.is_symlink():
            raise ValueError("안전하지 않은 기록 경로입니다.")
        data = json.loads((directory / "operation.json").read_text(encoding="utf-8"))
        sidecars = []
        for destination, item in data.get("files", {}).items():
            for key in ("backup", "redo"):
                raw = item.get(key)
                if not raw:
                    continue
                path = Path(raw)
                if path.resolve().is_relative_to(directory.resolve()):
                    continue
                allowed = {destination + f".{operation_id}.rms-backup", destination + f".{operation_id}.rms-redo",
                           destination + f".{operation_id}.rms-backup.rms-redo"}
                if str(path) not in allowed:
                    raise ValueError("기록에 안전하지 않은 백업 파일명이 있습니다.")
                if path.is_symlink():
                    raise ValueError("연결 파일인 백업은 자동 삭제할 수 없습니다.")
                sidecars.append(path)
        cleanup.append((directory, sidecars))
    for directory, sidecars in cleanup:
        for path in sidecars:
            path.unlink(missing_ok=True)
        shutil.rmtree(directory)
    return {"discarded": len(operation_ids)}
