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
from app.model.plan import (
    OP_ADD, OP_DELETE, OP_STORAGE_CHANGE, RESOLVE_OVERWRITE, RESOLVE_SKIP,
    STATUS_CONFLICT, STATUS_PENDING, PlanEntry,
)


class PlanBuildError(Exception):
    pass


def _storage_of_system(collection, system) -> str:
    entry = next((s for s in collection.systems if s.system == system), None)
    return entry.storage_id if entry else STORAGE_INTERNAL


def _bump(delta, storage_id, amount):
    if amount:
        delta[storage_id] = delta.get(storage_id, 0) + amount


ACTION_COPY = "copy"          # 목적지에 없다. 그냥 복사하면 된다
ACTION_IDENTICAL = "identical"  # 크기와 시각이 같다. 이미 같은 파일로 본다
ACTION_CONFLICT = "conflict"    # 목적지에 다른 파일이 있다. 사용자 판단이 필요하다


def classify_destination(provider, src_path, src_size, dest_path) -> tuple[str, dict | None]:
    """목적지 상태를 보고 이 파일을 어떻게 다뤄야 하는지 판정한다.

    **용량 계산과 충돌 판정은 별개다.** 예전에는 "목적지에 같은 크기의 파일이 있으면
    물리 증가 0"으로만 계산하고 Apply에서는 그냥 덮어썼다. 하지만 ROM 관리에서
    `같은 이름 + 같은 크기 + 다른 CRC`는 흔히 있는 일이라, 크기가 같다는 이유로
    남의 파일을 덮어쓰면 안 된다.

    "이미 같은 파일"로 인정하는 조건은 **크기와 수정 시각이 정확히 일치**하는 것뿐이다.
    복사 도구는 원본의 타임스탬프를 보존하므로, 우리가(또는 다른 도구가) 복사해둔
    파일이면 시각이 정확히 같다.

    허용오차를 두지 않는 이유가 있다. 파일 시스템 시각 해상도(FAT32 2초)를 감안해
    여유를 주면, 비슷한 시각에 만들어진 **서로 다른 파일**이 "동일"로 판정된다.
    ROM 관리에서 `같은 이름 + 같은 크기 + 다른 내용`은 흔하고, 잘못 판정하면 남의
    파일을 조용히 덮어쓴다. 확신할 수 없으면 충돌로 올려 사용자가 정하게 하는 것이
    맞다(스펙 §85 - 모호한 상황에서 자동으로 결정하지 않는다).

    (같은 시각 비교라도 "우리가 방금 복사한 게 실제로 도착했는가"를 보는
    `engines/robocopy_engine.py`의 검증은 목적이 달라서 허용오차를 쓴다.)
    """
    existing = provider.stat(dest_path)
    if existing is None:
        return ACTION_COPY, None

    source = provider.stat(src_path)
    if (source is not None and existing.size == source.size
            and existing.mtime_ns == source.mtime_ns):
        return ACTION_IDENTICAL, None

    reason = ("크기가 다릅니다" if existing.size != int(src_size or 0)
              else "크기는 같지만 같은 파일이라고 확신할 수 없습니다")
    return ACTION_CONFLICT, {
        "source": str(src_path), "dest": str(dest_path),
        "sourceSize": int(src_size or 0), "destSize": int(existing.size),
        "reason": reason,
    }


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

        delta, estimated, conflicts = {}, 0, []
        if rom_path:
            dest = Path(layout.rom_dir) / filename
            size = int(source_rom.get("size") or 0)
            estimated += size
            action, conflict = classify_destination(provider, rom_path, size, dest)
            if action == ACTION_COPY:
                _bump(delta, rom_storage, size)
            elif action == ACTION_CONFLICT:
                conflicts.append({**conflict, "kind": "rom"})

        media_items = []
        for media in item.get("media") or []:
            if not provider.exists(media["path"]):
                continue  # 원본이 없는 media만 조용히 빠진다(D3)
            media_items.append(media)
            size = int(media.get("size") or 0)
            estimated += size
            pairs = adapter.media_pairs(layout, filename, [_MediaRef(media)])
            dest = pairs[0][1] if pairs else None
            if dest is None:
                continue
            action, conflict = classify_destination(provider, media["path"], size, dest)
            if action == ACTION_COPY:
                _bump(delta, media_storage, size)
            elif action == ACTION_CONFLICT:
                conflicts.append({**conflict, "kind": "media",
                                  "mediaType": media.get("type") or media.get("media_type")})

        entry = PlanEntry(
            op=OP_ADD, system=system, filename=filename,
            source={**item, "media": media_items},
            storage_to=rom_storage, estimated_bytes=estimated, physical_delta=delta,
            conflicts=conflicts,
            status=STATUS_CONFLICT if conflicts else STATUS_PENDING,
            payload=item.get("fields"),
        )
        plan.add(entry)
        added.append(entry)

    conflicted = sum(1 for e in added if e.conflicts)
    return {"added": len(added), "skipped": skipped, "conflicts": conflicted}


def resolve_conflict(plan, collection, provider, key, resolution):
    """충돌 항목의 처리 방식을 정하고 용량 계산을 다시 한다.

    덮어쓰기는 `기존 크기 → 새 크기`이므로 물리 증가가 새 파일 크기 전부가 아니라
    **차이만큼**이다. 줄어들 수도 있다. 건너뛰기는 증가가 0이다.
    """
    entry = plan.get(key)
    if entry is None:
        raise PlanBuildError("Plan 항목을 찾을 수 없습니다.")
    if resolution not in (RESOLVE_SKIP, RESOLVE_OVERWRITE):
        raise PlanBuildError(f"알 수 없는 처리 방식입니다: {resolution}")

    adapter = get_adapter(collection.frontend)
    layout = adapter.layout(collection, entry.system)
    rom_storage = _storage_of_system(collection, entry.system)
    media_storage = (collection.storage_for_path(layout.media_dir)
                     if layout.media_dir else rom_storage)

    delta = dict(entry.physical_delta)
    if resolution == RESOLVE_OVERWRITE:
        for conflict in entry.conflicts:
            storage = rom_storage if conflict["kind"] == "rom" else media_storage
            _bump(delta, storage, int(conflict["sourceSize"]) - int(conflict["destSize"]))

    plan.add(PlanEntry(
        op=entry.op, system=entry.system, filename=entry.filename, rom_uid=entry.rom_uid,
        source=entry.source, storage_from=entry.storage_from, storage_to=entry.storage_to,
        estimated_bytes=entry.estimated_bytes, physical_delta=delta,
        conflicts=entry.conflicts, resolution=resolution,
        payload=entry.payload, status=STATUS_PENDING,
    ))
    return {"key": key, "resolution": resolution, "delta": delta}


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
