"""One DB/file journal for moves touching an Archive and a Collection."""
from pathlib import Path
import os
import uuid
from contextlib import ExitStack

from adapters import get_adapter
from app.archive import projection, paste, shared_cache
from app.archive.edit_lock import writing
from app.archive.undo import state
from app.model.constants import normalize_system
from app.model.plan import Plan
from app.plan import builder, transfer
from app.plan.applier import apply_plan
from app.plan.builder import add_destinations
from app.plan.validator import validate
from app.plan import clipboard


def prepare(api, target_id, descriptor, items, mapping=None):
    cfg = api._archive_config()
    source_id = descriptor["sourceCollectionId"]
    if source_id == target_id:
        raise ValueError("같은 Archive 안에서 같은 System으로 이동할 수 없습니다.")
    target = None if target_id == "__archive__" else api._plan_context(target_id)
    source = None if source_id == "__archive__" else api._plan_context(source_id)
    if any(context and str(context[0].root_path).lower().startswith("mtp:") for context in (source, target)):
        raise ValueError("MTP와 Archive 사이의 잘라내기는 지원하지 않습니다. 복사 후 원본을 확인하세요.")
    mapping = mapping or {}
    prepared = []
    rows = []
    snapshots = {}
    for original in items:
        item = dict(original)
        item["cutSourceSystem"] = item["system"]
        system = mapping.get(item["system"], item["system"])
        sf = cfg["frontend"] if source is None else source[0].frontend
        tf = cfg["frontend"] if target is None else target[0].frontend
        if normalize_system("es-de", item["system"]) != normalize_system("es-de", system):
            raise ValueError("다른 게임 System으로 이동할 수 없습니다.")
        item["system"] = system
        prepared.append(item)
        if source:
            row = source[1].get_row_by_filename(original["system"], original["filename"])
            if not row:
                raise ValueError("잘라낸 게임을 찾을 수 없습니다.")
            rows.append(row)
            if row["fields"] != (original.get("fields") or {}):
                raise ValueError("잘라낸 뒤 원본 메타데이터가 바뀌었습니다.")
        existing = (api.archive.find_rom_identity(system, item["filename"]) if target is None
                    else target[1].get_row_by_filename(system, item["filename"]))
        if existing:
            fields = api.archive.resolve_fields(existing["rom_identity_id"])[0] if target is None else existing["fields"]
            snapshots[transfer.item_key(item)] = {"fields": fields, "filename": item["filename"]}
    op_id = uuid.uuid4().hex
    source_states = paste.source_states(items)
    if source:
        adapter = get_adapter(source[0].frontend)
        for system in {item["system"] for item in items}:
            path = str(Path(adapter.layout(source[0], system).metadata_file).absolute())
            source_states[path] = paste.file_state(path)
    collisions = [{"key": key, "system": key.split("|")[0], "filename": row["filename"],
        "existingTitle": row["fields"].get("name") or row["filename"],
        "incomingTitle": next((i.get("fields") or {}).get("name") or i["filename"] for i in prepared if transfer.item_key(i) == key),
        "existingFields": row["fields"], "incomingFields": next(i.get("fields") or {} for i in prepared if transfer.item_key(i) == key)}
        for key, row in snapshots.items()]
    api._paste_ops[op_id] = {"target": "archive-move", "collectionId": target_id,
        "sourceId": source_id, "config": cfg, "descriptor": descriptor, "prepared": prepared,
        "sourceRows": rows, "sourceStates": source_states, "collisions": collisions,
        "undoable": True}
    return {"operationId": op_id, "target": "archive" if target is None else "collection",
            "action": "move", "count": len(items), "undoable": True, "collisions": collisions, "skipped": []}


def execute(api, operation_id, op, decisions):
    if any(decisions.get(row["key"]) not in {"overwrite", "skip"} for row in op["collisions"]):
        raise ValueError("충돌한 게임의 처리 방법을 선택하세요.")
    selected = [item for item in op["prepared"] if decisions.get(transfer.item_key(item)) != "skip"]
    if not selected:
        return {"jobId": None}
    def run(progress):
        cfg = op["config"]
        source_id, target_id = op["sourceId"], op["collectionId"]
        with writing(cfg["archiveDir"]), api._archive_lifecycle_lock, api.archive._conn.lock, ExitStack() as stack:
            if cfg != api._archive_config():
                raise ValueError("Archive 설정이 바뀌었습니다.")
            for cid in sorted({source_id, target_id} - {"__archive__"}):
                if not api.registry.acquire_lock(f"apply:{cid}", kind="move"):
                    raise ValueError("Collection에 다른 작업이 진행 중입니다.")
                stack.callback(api.registry.release_lock, f"apply:{cid}")
            if any(paste.file_state(path) != saved for path, saved in op["sourceStates"].items()):
                raise ValueError("잘라낸 원본 파일이 바뀌었습니다.")
            if source_id == "__archive__":
                for rid, signature in op["descriptor"].get("archiveStates", {}).items():
                    current = paste.state_of(api.archive, api.archive.get_identity(rid))
                    if not current or current["signature"] != signature:
                        raise ValueError("잘라낸 Archive 게임이 바뀌었습니다.")
            shared = shared_cache.snapshot_path(cfg["archiveDir"])
            known = api.registry.get_setting("archive.shared_snapshot_hashes", {}) or {}
            if (shared_cache.fingerprint(shared) if shared.is_file() else None) != known.get(cfg["archiveDir"]):
                raise ValueError("공유 Archive가 바뀌었습니다.")
            tx = api._archive_journal.begin(operation_id, api.archive, cfg,
                    [i["system"] for i in selected] if target_id == "__archive__" else [], allow_network=True, action="move")
            collections = {}
            for cid in {source_id, target_id} - {"__archive__"}:
                collection, cache, provider = api._plan_context(cid)
                systems = {row["system"] for row in op["sourceRows"]} if cid == source_id else {i["system"] for i in selected}
                adapter = get_adapter(collection.frontend)
                collections[cid] = (collection, cache, provider, adapter, systems)
                for system in systems:
                    layout = adapter.layout(collection, system)
                    tx.data.setdefault("extraRoots", []).extend(str(path) for path in (layout.rom_dir, layout.media_dir, Path(layout.metadata_file).parent) if path)
                tx.data.setdefault("relatedCollections", {})[cid] = sorted(systems)
                tx.save()
                for system in systems:
                    tx.capture(adapter.layout(collection, system).metadata_file, index=True)
            try:
                with tx.tracking():
                    if target_id == "__archive__":
                        outcome = api._archive_paste_items(cfg, selected, "replace", progress_cb=progress)
                        if not outcome["ok"] or outcome["data"].get("conflicts"):
                            raise ValueError("Archive 대상 ROM을 안전하게 복사하지 못했습니다.")
                    else:
                        collection, cache, provider, adapter, systems = collections[target_id]
                        plan = Plan(target_id)
                        prepared, skipped = transfer.prepare(selected, cache, "replace", exact_only=True,
                            allow_rom_replace=True, force_media=True)
                        if skipped:
                            raise ValueError("이동 대상을 모두 준비하지 못했습니다.")
                        builder.plan_add(plan, collection, provider, prepared)
                        for entry in list(plan.entries):
                            if entry.conflicts:
                                builder.resolve_conflict(plan, collection, provider, entry.key, "overwrite")
                            for _, path, _, kind in add_destinations(entry, adapter.layout(collection, entry.system), adapter):
                                if str(Path(path).absolute()) in op["sourceStates"]:
                                    raise ValueError("같은 파일을 참조하는 대상으로 이동할 수 없습니다.")
                                if Path(path).exists():
                                    for source_path in op["sourceStates"]:
                                        if Path(source_path).name.casefold() == Path(path).name.casefold() and Path(source_path).exists() and os.path.samefile(path, source_path):
                                            raise ValueError("같은 파일을 참조하는 대상으로 이동할 수 없습니다.")
                                tx.capture(path, moved=True)
                        report = validate(plan, collection, cache, provider)
                        if report["entries"] or report["blocked"]:
                            raise ValueError("이동 대상 파일을 검증하지 못했습니다.")
                        outcome = apply_plan(plan, collection, cache, api.registry, provider, progress_cb=progress,
                            backup_suffix=f".{operation_id}.rms-backup", retain_backups=True, rom_staging=True)
                        for path, item in tx.data["files"].items():
                            item["after"] = state(path)
                        tx.save()
                        if any(outcome.get(key) for key in ("failed", "partial", "invalid")):
                            raise ValueError("이동 대상 복사에 실패했습니다.")
                    if any(paste.file_state(path) != saved for path, saved in op["sourceStates"].items()):
                        raise ValueError("복사 중 원본 파일이 바뀌었습니다.")
                    if source_id == "__archive__":
                        keys = {(item["filename"], normalize_system(cfg["frontend"], item["system"])) for item in selected}
                        ids = [rid for rid in op["descriptor"]["archiveIds"] if (lambda identity:
                            (identity["filename"], normalize_system(cfg["frontend"], identity["system"])) in keys)(api.archive.get_identity(rid))]
                        outcome = api.archive_delete_owned(ids)
                        if not outcome["ok"] or outcome["data"].get("failures"):
                            raise ValueError("Archive 원본을 제거하지 못했습니다.")
                    else:
                        collection, cache, provider, adapter, _ = collections[source_id]
                        selected_files = {(item["cutSourceSystem"], item["filename"]) for item in selected}
                        for row in op["sourceRows"]:
                            if (row["system"], row["filename"]) not in selected_files:
                                continue
                            layout = adapter.layout(collection, row["system"])
                            for path in [Path(layout.rom_dir) / row["filename"], *[m["rel_path"] for m in row["media"]]]:
                                tx.remove(path)
                            adapter.remove_entries(layout, [row["filename"]])
                    result = api._publish_archive_snapshot(cfg)
                    if result["status"] != "published":
                        raise ValueError("공유 Archive DB를 게시하지 못했습니다.")
                tx.commit(api.archive)
                clipboard.clear(api.registry)
            except BaseException:
                try:
                    tx.failed(api.archive)
                    tx.restore(api.archive)
                    api._remember_archive_digest(cfg)
                except Exception as exc:
                    api._archive_recovery_error = str(exc)
                raise
            finally:
                for cid, (_, _, _, _, systems) in collections.items():
                    api.workspace.scan(cid, force=True, systems=sorted(systems))
            return {"applied": len(selected), "undoOperationId": operation_id}
    return {"jobId": api.jobs.run_heavy(run, mutates_state=True,
                     target_ids=tuple({"archive", op["sourceId"], op["collectionId"]}), kind="archive-move")}
