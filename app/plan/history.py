"""Read and explicitly discard completed recovery records; keep pending ones."""
from pathlib import Path
import shutil
from app.plan import journal_index, journal_events, process_owner


def _backup_bytes(directory):
    data = journal_events.load(directory)
    files = list(directory.rglob("*"))
    for item in data.get("files", {}).values():
        files.extend(Path(item[key]) for key in ("backup", "redo") if item.get(key))
    seen, size = set(), 0
    for path in files:
        if str(path) in seen:
            continue
        seen.add(str(path))
        try:
            if path.is_file():
                size += path.stat().st_size
        except FileNotFoundError:
            continue
    return size


def total_backup_bytes(api):
    """All local recovery roots, using the same rebuildable size cache."""
    total = 0
    for root in (api._paste_journal.root, api._archive_journal.root):
        for data in journal_index.records(root):
            directory = root / data["id"]
            total += journal_index.backup_bytes(root, data["id"], lambda: _backup_bytes(directory))
    return total


def listing(api, collection_id):
    rows = []
    cfg = api._archive_config()
    for kind, root in (("collection", api._paste_journal.root), ("archive", api._archive_journal.root)):
        for data in journal_index.records(root):
            relevant = (data.get("collectionId") == collection_id or collection_id in data.get("relatedCollections", {}))
            if kind == "archive":
                relevant = data.get("config") == cfg and (collection_id == "__archive__" or relevant)
            if not relevant:
                continue
            directory = root / data["id"]
            size = journal_index.backup_bytes(root, data["id"], lambda: _backup_bytes(directory))
            rows.append({"id": data["id"], "kind": kind, "status": data["status"],
                "recoveryError": data.get("recoveryError"),
                "redoReady": bool(data.get("redoReady")), "relatedCollections": data.get("relatedCollections", {}),
                "createdAt": data["createdAt"], "action": data.get("action", "file-operation"),
                "bytes": size, "canDiscard": data["status"] in {"committed", "undone", "recovered", "closed"},
                "canForceRecovery": data["status"] in {"running", "restoring", "redoing"}
                    and process_owner.status(data) == "unknown"})
    return sorted(rows, key=lambda row: row["createdAt"], reverse=True)


def recovery_action(api, collection_id, operation_id, action):
    row = next((row for row in listing(api, collection_id) if row["id"] == operation_id), None)
    if not row or (row["status"] != "recovery_failed" and not (action == "force" and row.get("canForceRecovery"))):
        raise ValueError("복구 실패 기록을 찾을 수 없습니다.")
    journal = api._archive_journal if row["kind"] == "archive" else api._paste_journal
    directory = journal.root / operation_id
    if directory.is_symlink() or not directory.resolve().is_relative_to(journal.root.resolve()):
        raise ValueError("안전하지 않은 기록 경로입니다.")
    if action == "open":
        import os
        os.startfile(str(directory))
    elif action in {"retry", "force"}:
        data = journal_events.load(directory)
        owner_status = process_owner.status(data)
        if action == "force" and owner_status != "unknown":
            raise ValueError("소유자 확인 불가 기록에만 수동 복구를 사용할 수 있습니다.")
        if action == "retry" and data.get("status") != "recovery_failed":
            raise ValueError("기록 상태가 바뀌었습니다.")
        if row["kind"] == "archive":
            tx = journal.load(operation_id)
            from app.archive.edit_lock import writing
            held = []
            try:
                for cid in sorted(tx.data.get("relatedCollections", {})):
                    if not api.registry.acquire_lock(f"apply:{cid}", kind="recovery"):
                        raise ValueError("관련 Collection에 다른 작업이 진행 중입니다.")
                    held.append(cid)
                with writing(tx.data["config"]["archiveDir"]):
                    tx.restore(api.archive)
            finally:
                for cid in held:
                    api.registry.release_lock(f"apply:{cid}")
            api._remember_archive_digest(api._archive_config())
        else:
            held = []
            try:
                for cid in sorted(set(data.get("relatedCollections", {})) - {collection_id}):
                    if not api.registry.acquire_lock(f"apply:{cid}", kind="recovery"):
                        raise ValueError("관련 Collection에 다른 작업이 진행 중입니다.")
                    held.append(cid)
                journal.retry_recovery(operation_id, force_unknown_owner=action == "force")
            finally:
                for cid in held:
                    api.registry.release_lock(f"apply:{cid}")
    elif action == "close":
        if row["kind"] == "archive":
            tx = journal.load(operation_id)
            tx.data["status"] = "closed"
            tx.data["redoReady"] = False
            tx.save()
        else:
            data = journal.details(operation_id)
            data["status"] = "closed"
            data["redoReady"] = False
            journal._save(directory, data)
    else:
        raise ValueError("지원하지 않는 복구 작업입니다.")
    if row["kind"] == "archive" and action != "open":
        pending = journal.pending(api._archive_config())
        api._archive_recovery_error = pending[0].get("recoveryError", "복구가 필요합니다.") if pending else None
    return {"action": action}


def discard(api, collection_id, operation_ids, *, _permitted=None):
    permitted = _permitted if _permitted is not None else {row["id"]: row for row in listing(api, collection_id)}
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
        data = journal_events.load(directory)
        if data.get("status") not in {"committed", "undone", "recovered", "closed"}:
            raise ValueError("기록 상태가 바뀌어 백업을 삭제할 수 없습니다.")
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


def requires_recovery(records):
    """A live owner's running operation is not an interrupted operation."""
    return any(row.get('status') == 'recovery_failed' or process_owner.status(row) != 'alive'
               for row in records)
