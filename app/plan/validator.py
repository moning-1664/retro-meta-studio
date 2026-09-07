"""
app/plan/validator.py
======================
Apply 직전 재검증(스펙 §31, §33).

Plan을 만든 뒤에도 파일 시스템은 밖에서 바뀔 수 있다. 탐색기로 파일을 지웠을 수도
있고, 다른 인스턴스가 Apply를 끝냈을 수도 있다(§9.5). 그래서 실제로 쓰기 직전에
다시 확인한다.

문제가 있는 항목은 그 항목만 invalid로 표시하고 나머지는 진행할 수 있게 한다 -
하나가 틀어졌다고 수천 개짜리 작업 전체를 버리면 쓸 수 없는 도구가 된다. 다만
용량 초과는 Storage 단위 문제라 그 Storage로 가는 작업 전체를 막는다.
"""

from __future__ import annotations

from pathlib import Path

from adapters import get_adapter
from app.model.plan import OP_ADD, OP_DELETE, OP_STORAGE_CHANGE


def validate(plan, collection, cache, provider) -> dict:
    """반환: {"ok": bool, "entries": [...], "capacity": [...], "blocked": bool}"""
    adapter = get_adapter(collection.frontend)
    problems = []
    for entry in plan.entries:
        if entry.blocked:
            # 해결되지 않은 충돌은 검증 대상이 아니라 사용자 결정 대기 상태다.
            continue
        entry.status, entry.error = "pending", None
        if entry.op == OP_ADD:
            _validate_add(entry, provider)
        elif entry.op == OP_DELETE:
            _validate_delete(entry, collection, cache, provider, adapter)
        elif entry.op == OP_STORAGE_CHANGE:
            _validate_storage_change(entry, collection)
        if entry.status == "invalid":
            problems.append({"key": entry.key, "filename": entry.filename or entry.system,
                             "error": entry.error})

    capacity = check_capacity(plan, collection, cache, provider)
    blocked = any(c["over"] for c in capacity)
    return {"ok": not problems and not blocked, "entries": problems,
            "capacity": capacity, "blocked": blocked}


def _validate_add(entry, provider):
    source = entry.source or {}
    rom = source.get("rom") or {}
    if rom.get("path"):
        stat = provider.stat(rom["path"])
        if stat is None:
            entry.status, entry.error = "invalid", "원본 ROM이 사라졌습니다."
            return
        # Plan을 만든 시점과 크기가 다르면 내용이 바뀐 것이다. 조용히 덮어쓰지 않는다.
        if rom.get("size") is not None and stat.size != int(rom["size"]):
            entry.status, entry.error = "invalid", "원본 ROM이 변경되었습니다(크기 불일치)."
            return
    missing = [m for m in (source.get("media") or []) if not provider.exists(m["path"])]
    if missing:
        # media가 없어진 것은 작업을 막을 이유가 못 된다(결정 D3) - 빼고 진행한다.
        source["media"] = [m for m in source["media"] if provider.exists(m["path"])]


def _validate_delete(entry, collection, cache, provider, adapter):
    """삭제 대상이 Plan을 만들 때와 같은 파일인지 확인한다.

    Cache에 행이 있는지만 보면 부족하다. Plan을 만든 뒤 외부에서 ROM을 다른 파일로
    교체했을 수 있는데, 그대로 지우면 사용자가 의도하지 않은 파일을 잃는다. 실제
    파일의 크기와 수정 시각이 Cache와 같은지까지 본다.
    """
    if entry.rom_uid is None:
        return
    row = cache.get_row(entry.rom_uid)
    if row is None:
        entry.status, entry.error = "invalid", "항목이 이미 사라졌습니다."
        return
    if not row["present"]:
        return  # metadata만 있는 항목. 지울 ROM 파일이 없다.

    layout = adapter.layout(collection, row["system"])
    stat = provider.stat(Path(layout.rom_dir) / row["filename"])
    if stat is None:
        entry.status, entry.error = "invalid", "ROM 파일이 이미 사라졌습니다."
        return
    if stat.size != int(row["size"] or 0) or stat.mtime_ns != int(row["mtime_ns"] or 0):
        entry.status = "invalid"
        entry.error = "ROM 파일이 외부에서 변경되었습니다. 다시 스캔한 뒤 삭제해주세요."


def _validate_storage_change(entry, collection):
    if collection.storage(entry.storage_to) is None:
        entry.status, entry.error = "invalid", "대상 Storage가 사라졌습니다."
        return
    current = next((s.storage_id for s in collection.systems if s.system == entry.system), None)
    if current is None:
        entry.status, entry.error = "invalid", "System이 사라졌습니다."
    elif current == entry.storage_to:
        entry.status, entry.error = "invalid", "이미 대상 Storage에 있습니다."


def check_capacity(plan, collection, cache, provider) -> list[dict]:
    """Storage별 예상 사용량과 초과 여부(스펙 §20).

    용량을 못 읽는 Storage(MTP, 일부 네트워크 공유)는 Unknown이므로 검사를 건너뛴다 -
    오류가 아니다(§5).
    """
    actual = cache.storage_usage()
    delta = plan.delta()
    result = []
    for storage in collection.storages:
        volume = provider.volume_info(storage.root_path)
        used = actual.get(storage.storage_id, 0)
        change = delta.get(storage.storage_id, 0)
        planned = used + change
        over = 0
        if volume.capacity_bytes is not None and planned > volume.capacity_bytes:
            over = planned - volume.capacity_bytes
        result.append({
            "storageId": storage.storage_id, "label": storage.label,
            "actualBytes": used, "planBytes": planned, "deltaBytes": change,
            "capacityBytes": volume.capacity_bytes, "freeBytes": volume.free_bytes,
            "over": bool(over), "overBytes": over,
        })
    return result
