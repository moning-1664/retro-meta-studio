"""Read-only preparation for the same paste commands used by Collections."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.archive import projection
from app.model.constants import normalize_system, metadata_compatible
from app.plan import transfer


def file_state(path):
    if not path:
        return None
    try:
        stat = Path(path).stat()
        return (stat.st_size, stat.st_mtime_ns, getattr(stat, "st_ino", 0))
    except OSError:
        return None


def source_states(items):
    paths = set()
    for item in items:
        rom = item.get("rom") or {}
        if rom.get("path"):
            paths.add(str(rom["path"]))
        for media in item.get("media") or []:
            path = media.get("path") or media.get("abs_path")
            if path:
                paths.add(str(path))
    return {path: file_state(path) for path in paths}


def state_of(store, identity):
    if identity is None:
        return None
    rid = identity["rom_identity_id"]
    fields, raw = store.resolve_fields(rid)
    media = list(projection.effective_media(store, rid).values())
    sources = store.rom_sources(rid)
    state = {"identity": dict(identity), "fields": fields, "raw": raw,
             "media": media, "romSources": sources,
             "files": {str(item["abs_path"]): file_state(item["abs_path"])
                       for item in media + sources if item.get("abs_path")}}
    signature = hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False,
                                         default=str).encode("utf-8")).hexdigest()
    existing = {
        "system": identity["system"],
        "filename": identity["filename"] or identity["filename_norm"],
        "present": any(source.get("abs_path") and Path(source["abs_path"]).is_file()
                       for source in sources),
        "fields": fields, "frontend_raw": raw,
        "media": [{**item, "rel_path": item.get("abs_path")} for item in media],
    }
    return {"signature": signature, "row": existing, "rid": rid}


def prepare(store, config, source_items, mode, *, target_id=None, target_system=None,
            new_only=False):
    if target_id and len(source_items) != 1:
        raise ValueError("게임을 하나 복사했을 때만 선택한 게임에 붙여넣을 수 있습니다.")
    if target_id and target_system:
        raise ValueError("게임과 System을 동시에 붙여넣기 대상으로 지정할 수 없습니다.")
    target = store.get_identity(str(target_id)) if target_id else None
    if target_id and target is None:
        raise ValueError("붙여넣을 마스터 게임을 찾을 수 없습니다.")
    mode = transfer.normalize_mode(mode)
    prepared, collisions, skipped, snapshots = [], [], [], {}
    for source in source_items:
        item = dict(source)
        original_fields = dict(item.get("fields") or {})
        if target:
            item["system"] = target["system"]
            item["filename"] = target["filename"] or target["filename_norm"]
            if item["filename"] != source.get("filename"):
                item["rom"] = None
            identity = target
        else:
            item["system"] = normalize_system(
                config["frontend"], target_system or item.get("system") or "")
            identity = store.find_rom_identity(item["system"], item.get("filename") or "")
        source_system = normalize_system(config["frontend"], source.get("system") or "")
        if source_system != item["system"]:
            if not metadata_compatible(source_system, item["system"]) or identity is None:
                skipped.append({"filename": item.get("filename"), "reason": "같은 메타데이터 계열의 기존 게임에만 붙여넣을 수 있습니다."})
                continue
            item["rom"] = None
        filename, system = str(item.get("filename") or ""), str(item.get("system") or "")
        if (not filename or Path(filename).name != filename or not system
                or Path(system).name != system or system in {".", ".."}):
            skipped.append({"filename": filename, "reason": "안전하지 않은 System 또는 파일명입니다."})
            continue
        if new_only and identity is not None:
            skipped.append({"filename": filename, "reason": "대상 System에 같은 게임이 이미 있습니다."})
            continue
        state = state_of(store, identity)
        existing = state["row"] if state else None
        out, reason = transfer.decide(item, existing, mode, allow_rom_replace=mode == transfer.MODE_REPLACE,
                                     force_media=mode == transfer.MODE_REPLACE)
        if out is None:
            skipped.append({"filename": filename, "reason": reason})
            continue
        key = transfer.item_key(out)
        prepared.append(out)
        snapshots[key] = state["signature"] if state else None
        existing_media = {media["media_type"]: media for media in (existing or {}).get("media", [])}
        media_conflict = any(
            (media.get("type") or media.get("media_type")) in existing_media
            for media in out.get("media") or [])
        rom_conflict = bool(out.get("rom") and (existing or {}).get("present"))
        if state and (media_conflict or rom_conflict or transfer.fields_conflict(
                existing["fields"], original_fields, mode)):
            collisions.append({
                "key": key, "system": system, "filename": filename,
                "existingRomUid": state["rid"],
                "existingFields": existing["fields"], "incomingFields": original_fields,
                "existingTitle": existing["fields"].get("name") or filename,
                "incomingTitle": original_fields.get("name") or filename,
                "existingDescription": existing["fields"].get("desc") or "",
                "incomingDescription": original_fields.get("desc") or "",
            })
    return {"prepared": prepared, "collisions": collisions, "skipped": skipped,
            "snapshots": snapshots, "sourceStates": source_states(prepared), "mode": mode}


def unchanged(store, operation):
    if any(file_state(path) != saved for path, saved in operation.get("sourceStates", {}).items()):
        return False
    for item in operation["prepared"]:
        identity = store.find_rom_identity(item["system"], item["filename"])
        state = state_of(store, identity)
        current = state["signature"] if state else None
        if current != operation["snapshots"][transfer.item_key(item)]:
            return False
    return True
