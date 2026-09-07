"""
app/plan/builder.py
====================
사용자 동작을 PlanEntry로 바꾼다.

여기서 파일을 건드리는 일은 전혀 없다. 오직 "무엇을 어디로 옮길지"와 "그 결과
Storage별 용량이 얼마나 변할지"만 계산한다.

용량 계산의 핵심 규칙(스펙 §81-82):
- 대상에 이미 같은 크기의 파일이 있으면 물리 증가는 0이다. 논리적으로는 "추가"지만
  디스크는 늘지 않는다.
- ROM과 media는 각자 실제로 놓이는 Storage에 더한다. ES-DE에서 System을 외장으로
  옮겨도 커버 이미지는 Collection root(보통 내장)에 남는다.
"""

from __future__ import annotations

from pathlib import Path

from adapters import get_adapter
from app.model.collection import STORAGE_INTERNAL
from app.model.plan import OP_ADD, OP_DELETE, OP_STORAGE_CHANGE, PlanEntry


class PlanBuildError(Exception):
    pass


def _storage_of_system(collection, system) -> str:
    entry = next((s for s in collection.systems if s.system == system), None)
    return entry.storage_id if entry else STORAGE_INTERNAL


def _bump(delta, storage_id, amount):
    if amount:
        delta[storage_id] = delta.get(storage_id, 0) + amount


def plan_add(plan, collection, provider, items):
    """다른 Collection(또는 Archive)에서 가져온 항목들을 추가 예정으로 올린다.

    items: [{"system","filename","rom":{"path","size"},
             "media":[{"type","path","size"}],"fields","frontend_raw"}]

    원본 파일이 이미 사라졌으면 그 항목은 건너뛴다 - 붙여넣기 전체를 실패시키지
    않는다(결정 D3와 같은 태도).
    """
    adapter = get_adapter(collection.frontend)
    added, skipped = [], []

    for item in items:
        system = item["system"]
        filename = item["filename"]
        layout = adapter.layout(collection, system)
        rom_storage = _storage_of_system(collection, system)
        media_storage = collection.storage_for_path(layout.media_dir) if layout.media_dir else rom_storage

        source_rom = item.get("rom") or {}
        rom_path = source_rom.get("path")
        if rom_path and not provider.exists(rom_path):
            skipped.append({"filename": filename, "reason": "원본 ROM을 찾을 수 없습니다."})
            continue

        delta, estimated = {}, 0
        if rom_path:
            dest = Path(layout.rom_dir) / filename
            size = int(source_rom.get("size") or 0)
            estimated += size
            existing = provider.stat(dest)
            # 이미 같은 크기의 파일이 있으면 디스크는 늘지 않는다.
            _bump(delta, rom_storage, 0 if (existing and existing.size == size) else size)

        media_items = []
        for media in item.get("media") or []:
            if not provider.exists(media["path"]):
                continue  # 원본이 없는 media만 조용히 빠진다(D3)
            media_items.append(media)
            size = int(media.get("size") or 0)
            estimated += size
            pairs = adapter.media_pairs(layout, filename, [_MediaRef(media)])
            dest = pairs[0][1] if pairs else None
            existing = provider.stat(dest) if dest else None
            _bump(delta, media_storage, 0 if (existing and existing.size == size) else size)

        entry = PlanEntry(
            op=OP_ADD, system=system, filename=filename,
            source={**item, "media": media_items},
            storage_to=rom_storage, estimated_bytes=estimated, physical_delta=delta,
            payload=item.get("fields"),
        )
        plan.add(entry)
        added.append(entry)

    return {"added": len(added), "skipped": skipped}


class _MediaRef:
    """adapter.media_pairs()가 기대하는 최소 형태(media_type/path)."""

    def __init__(self, data):
        self.media_type = data.get("type") or data.get("media_type")
        self.path = data["path"]
        self.size = int(data.get("size") or 0)


def plan_delete(plan, collection, cache, rom_uids):
    """선택한 항목을 삭제 예정으로 올린다. 실제 파일은 그대로 둔다(스펙 §29)."""
    adapter = get_adapter(collection.frontend)
    entries = []
    for rom_uid in rom_uids:
        row = cache.get_row(int(rom_uid))
        if row is None:
            continue
        system = row["system"]
        layout = adapter.layout(collection, system)
        rom_storage = _storage_of_system(collection, system)
        media_storage = collection.storage_for_path(layout.media_dir) if layout.media_dir else rom_storage

        delta, estimated = {}, 0
        if row["present"]:
            estimated += int(row["size"] or 0)
            _bump(delta, rom_storage, -int(row["size"] or 0))
        for media in row["media"]:
            estimated += int(media["size"] or 0)
            _bump(delta, media_storage, -int(media["size"] or 0))

        entry = PlanEntry(op=OP_DELETE, system=system, filename=row["filename"],
                          rom_uid=int(rom_uid), storage_from=rom_storage,
                          estimated_bytes=estimated, physical_delta=delta)
        plan.add(entry)
        entries.append(entry)
    return {"deleted": len(entries)}


def plan_storage_change(plan, collection, cache, system, storage_to):
    """System을 다른 Storage로 옮길 예정으로 올린다(스펙 §10, §28).

    **ROM만 움직인다.** gamelists/downloaded_media는 Collection root에 남으므로
    media 용량은 어느 쪽에서도 변하지 않는다.
    """
    if collection.storage(storage_to) is None:
        raise PlanBuildError(f"Storage를 찾을 수 없습니다: {storage_to}")
    storage_from = _storage_of_system(collection, system)
    if storage_from == storage_to:
        raise PlanBuildError("이미 그 Storage에 있습니다.")

    stats = {s["system"]: s for s in cache.system_stats()}.get(system, {})
    rom_bytes = int(stats.get("rom_bytes") or 0)

    entry = PlanEntry(op=OP_STORAGE_CHANGE, system=system,
                      storage_from=storage_from, storage_to=storage_to,
                      estimated_bytes=rom_bytes,
                      physical_delta={storage_from: -rom_bytes, storage_to: rom_bytes})
    plan.add(entry)
    return {"system": system, "from": storage_from, "to": storage_to, "bytes": rom_bytes}
