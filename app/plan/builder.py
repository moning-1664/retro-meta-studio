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


def snapshot(provider, path) -> dict | None:
    """이 파일이 "그 파일"인지 나중에 확인하기 위한 최소 정보.

    크기만으로는 부족하다 - `같은 이름 + 같은 크기 + 다른 내용`은 ROM 관리에서 흔하다.
    수정 시각(ns)과 파일 식별자(`volume_file_id`)까지 함께 본다. 셋 다 이미 스캔이
    읽고 있는 값이라 추가 비용이 없다.

    **SHA256은 쓰지 않는다.** 4GB짜리 ISO 수천 개를 Plan 만들 때마다 해싱하면 도구를
    쓸 수 없다. 해시는 사용자가 명시적으로 요구하는 깊은 검증에만 쓴다.
    """
    stat = provider.stat(path)
    if stat is None:
        return None
    return {"size": int(stat.size), "mtimeNs": int(stat.mtime_ns), "fileId": stat.file_id}


def snapshot_matches(provider, path, saved) -> bool:
    """저장해둔 snapshot과 지금 파일이 같은가. snapshot이 없으면 판단하지 않는다."""
    if not saved:
        return True
    current = snapshot(provider, path)
    if current is None:
        return False
    if current["size"] != int(saved.get("size", -1)):
        return False
    if current["mtimeNs"] != int(saved.get("mtimeNs", -1)):
        return False
    # file_id는 못 읽는 저장소가 있다(네트워크 공유). 양쪽 다 있을 때만 비교한다.
    if saved.get("fileId") and current.get("fileId"):
        return saved["fileId"] == current["fileId"]
    return True


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
        # 사용자가 "덮어쓰기"를 누르는 순간 승인하는 것은 **지금 이 자리에 있는 이
        # 파일**을 덮어쓰는 것이다. Apply 직전에 같은 파일인지 다시 확인하기 위해
        # 그 시점의 모습을 함께 들고 간다.
        "destSnapshot": {"size": int(existing.size), "mtimeNs": int(existing.mtime_ns),
                         "fileId": existing.file_id},
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

        source_rom = dict(item.get("rom") or {})
        rom_path = source_rom.get("path")
        if rom_path:
            taken = snapshot(provider, rom_path)
            if taken is None:
                skipped.append({"filename": filename, "reason": "원본 ROM을 찾을 수 없습니다."})
                continue
            # Plan을 만든 시점의 원본 모습. Apply 직전에 같은 파일인지 확인한다.
            source_rom["snapshot"] = taken

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
            taken = snapshot(provider, media["path"])
            if taken is None:
                continue  # 원본이 없는 media만 조용히 빠진다(D3)
            media_items.append({**media, "snapshot": taken})
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
            source={**item, "rom": source_rom, "media": media_items},
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


def add_destinations(entry, layout, adapter) -> list:
    """이 ADD 항목이 건드리게 될 (원본, 목적지, 크기) 목록.

    Validate와 Apply가 **같은 목록**을 봐야 한다. 각자 계산하면 언젠가 갈라지고,
    갈라지는 순간 "검증은 통과했는데 Apply가 다른 파일을 건드리는" 상태가 된다.
    """
    source = entry.source or {}
    out = []
    rom = source.get("rom") or {}
    if rom.get("path"):
        out.append((Path(rom["path"]), Path(layout.rom_dir) / entry.filename,
                    int(rom.get("size") or 0)))
    refs = [_MediaRef(m) for m in (source.get("media") or [])]
    sizes = {str(m.path): m.size for m in refs}
    for src_path, dest in adapter.media_pairs(layout, entry.filename, refs):
        out.append((Path(src_path), Path(dest), sizes.get(str(src_path), 0)))
    return out


def approved_targets(entry) -> dict:
    """사용자가 덮어쓰기를 승인한 **파일별** 목록. {dest: 그때의 모습}

    **승인은 항목이 아니라 파일 단위다.** `entry.resolution`은 항목당 하나뿐이지만
    충돌은 파일마다 생긴다. 커버가 충돌해서 "덮어쓰기"를 누른 것을 항목 전체의
    허가로 읽으면, 사용자가 본 적도 없는 ROM까지 덮어쓰게 된다.

    승인하지 않았으면 빈 dict다 - 그러면 어떤 파일도 덮어쓸 수 없다.
    """
    if entry.resolution != RESOLVE_OVERWRITE:
        return {}
    return {str(c["dest"]): c.get("destSnapshot")
            for c in (entry.conflicts or []) if c.get("dest")}


def unapproved_overwrites(entry, layout, adapter, provider) -> list:
    """지금 덮어쓰게 되는데 **승인받지 않은** 목적지들.

    두 가지가 여기 걸린다.

    1. Plan을 만들 때는 비어 있던 자리에 그 사이 파일이 생긴 경우. 사용자는 그 파일에
       대해 아무것도 승인한 적이 없다.
    2. 승인은 받았지만 그 뒤 다른 파일로 바뀐 경우.

    같은 크기·시각의 파일이 이미 있는 경우(ACTION_IDENTICAL)는 덮어쓰는 것이 아니라
    건드리지 않는 것이므로 여기 들어오지 않는다.
    """
    approved = approved_targets(entry)
    blocked = []
    for src_path, dest, size in add_destinations(entry, layout, adapter):
        action, _ = classify_destination(provider, src_path, size, dest)
        if action != ACTION_CONFLICT:
            continue
        if str(dest) in approved and snapshot_matches(provider, dest, approved[str(dest)]):
            continue
        blocked.append(dest)

    # 승인받은 대상이 **사라진** 경우도 승인이 무효다. "이 파일을 덮어쓴다"는 결정은
    # 빈 자리에 새로 만드는 것과 다른 결정이다 - 사용자가 다시 정해야 한다.
    for dest, saved in approved.items():
        if Path(dest) not in blocked and not snapshot_matches(provider, dest, saved):
            blocked.append(Path(dest))
    return blocked


class _MediaRef:
    """adapter.media_pairs()가 기대하는 최소 형태(media_type/path)."""

    def __init__(self, data):
        self.media_type = data.get("type") or data.get("media_type")
        self.path = data["path"]
        self.size = int(data.get("size") or 0)


def plan_delete(plan, collection, cache, rom_uids, provider=None):
    """선택한 항목을 삭제 예정으로 올린다. 실제 파일은 그대로 둔다(스펙 §29).

    **삭제는 되돌릴 수 없으므로 ADD와 같은 수준으로 대상을 특정한다.** ROM과 media
    모두 `snapshot()`(size + mtime + volume_file_id)을 찍어 둔다. 크기와 시각만 보면
    "A를 지우고 같은 자리에 B를 만들었는데 우연히 크기와 시각이 같은" 경우를 통과시킨다 -
    확률이 낮아도 파괴적 작업에서 ADD보다 약한 계약을 쓸 이유가 없다.

    provider를 주지 않으면 Cache의 값만 쓴다(예전 동작). 호출부는 주는 것이 맞다.
    """
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
        # 지울 media의 모습도 함께 들고 간다. 삭제는 되돌릴 수 없으므로, Plan을 만든
        # 뒤 밖에서 바뀐 파일을 승인 없이 지우면 안 된다.
        media_snapshots = {}
        for media in row["media"]:
            estimated += int(media["size"] or 0)
            _bump(delta, media_storage, -int(media["size"] or 0))
            path = str(media["rel_path"])
            taken = snapshot(provider, path) if provider is not None else None
            media_snapshots[path] = taken or {
                "size": int(media["size"] or 0), "mtimeNs": int(media["mtime_ns"] or 0),
                "fileId": None}

        rom_path = Path(layout.rom_dir) / row["filename"]
        rom_snapshot = (snapshot(provider, rom_path) if provider is not None else None) or {
            "size": int(row["size"] or 0), "mtimeNs": int(row["mtime_ns"] or 0),
            "fileId": row.get("volume_file_id")}

        entry = PlanEntry(op=OP_DELETE, system=system, filename=row["filename"],
                          rom_uid=int(rom_uid), storage_from=rom_storage,
                          source={"mediaSnapshots": media_snapshots,
                                  "romSnapshot": rom_snapshot},
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
