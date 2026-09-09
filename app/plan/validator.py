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
from app.model.plan import OP_ADD, OP_DELETE, OP_STORAGE_CHANGE, RESOLVE_OVERWRITE
from app.plan.builder import snapshot_matches, unapproved_overwrites


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
            _validate_add(entry, provider, plan, collection, adapter)
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


def _validate_add(entry, provider, plan=None, collection=None, adapter=None):
    source = entry.source or {}
    rom = source.get("rom") or {}
    if rom.get("path"):
        stat = provider.stat(rom["path"])
        if stat is None:
            entry.status, entry.error = "invalid", "원본 ROM이 사라졌습니다."
            return
        # 크기가 같아도 같은 파일이라는 보장은 없다. Plan을 만들 때 찍어둔 모습과
        # 대조한다 - `같은 이름 + 같은 크기 + 다른 내용`은 ROM에서 흔하다.
        if not snapshot_matches(provider, rom["path"], rom.get("snapshot")):
            entry.status, entry.error = "invalid", "원본 ROM이 변경되었습니다. 다시 확인해주세요."
            return
        if rom.get("size") is not None and stat.size != int(rom["size"]):
            entry.status, entry.error = "invalid", "원본 ROM이 변경되었습니다(크기 불일치)."
            return

    # 원본 media도 ROM과 같은 수준으로 본다. 바뀐 커버를 조용히 복사하면 사용자는
    # 자기가 고른 그림이 갔다고 믿는다.
    #
    # **"없어진 것"과 "바뀐 것"은 다르게 다룬다.** 없어진 media는 빼고 진행한다(D3) -
    # 그것 때문에 붙여넣기 전체를 막을 이유가 없다. 하지만 다른 파일로 바뀐 것은
    # 사용자가 고른 것이 아니므로 멈춘다.
    for media in source.get("media") or []:
        if not provider.exists(media["path"]):
            continue
        if not snapshot_matches(provider, media["path"], media.get("snapshot")):
            entry.status, entry.error = "invalid", "원본 media가 변경되었습니다. 다시 확인해주세요."
            return

    # 덮어쓰게 되는 목적지 중 승인받지 않은 것이 있는지 본다. Plan을 만들 때는 비어
    # 있던 자리에 그 사이 파일이 생겼을 수도 있고(승인한 적 없다), 승인받은 파일이
    # 그 뒤 바뀌었을 수도 있다.
    if collection is not None and adapter is not None:
        layout = adapter.layout(collection, entry.system)
        if unapproved_overwrites(entry, layout, adapter, provider):
            entry.status = "invalid"
            entry.error = ("대상 폴더에 승인하지 않은 파일이 있습니다. "
                           "다시 확인한 뒤 덮어쓸지 결정해주세요.")
            return

    missing = [m for m in (source.get("media") or []) if not provider.exists(m["path"])]
    if missing:
        # media가 없어진 것은 작업을 막을 이유가 못 된다(결정 D3) - 빼고 진행한다.
        # **다만 용량 계산에서도 빼야 한다.** 복사 목록에서만 빼고 예상치를 그대로 두면
        # 화면의 Plan 용량과 실제로 일어날 일이 어긋나고 Capacity Check까지 틀린다.
        source["media"] = [m for m in source["media"] if provider.exists(m["path"])]
        _recalculate_delta(entry, missing, plan)


def _recalculate_delta(entry, dropped, plan=None):
    """빠진 media만큼 예상 바이트와 물리 증감을 줄인다.

    `physical_delta`를 직접 고치기 전에 Plan에 알려야 한다 - Plan은 엔트리를 넣고 뺄
    때마다 누적 합계를 갱신하는 O(1) 구조라, 값을 몰래 바꾸면 합계가 틀어진 채로
    남는다(화면의 `Actual -> Plan` 표시가 그 합계다).
    """
    dropped_bytes = sum(int(m.get("size") or 0) for m in dropped)
    if not dropped_bytes:
        return
    storage_id = _media_storage_of(entry)
    delta = dict(entry.physical_delta)
    if storage_id in delta:
        # 복사하기로 했던 것만 줄인다. 덮어쓰기라 이미 0이었다면 건드릴 것이 없다.
        delta[storage_id] = delta[storage_id] - min(dropped_bytes, delta[storage_id])
        if delta[storage_id] == 0:
            del delta[storage_id]
    estimated = max(0, int(entry.estimated_bytes) - dropped_bytes)
    if plan is not None:
        plan.revise(entry, estimated_bytes=estimated, physical_delta=delta)
    else:
        entry.estimated_bytes, entry.physical_delta = estimated, delta


def _media_storage_of(entry) -> str:
    """media 바이트가 잡혀 있던 Storage. 하나뿐이면 그것, 아니면 대상 Storage."""
    keys = [k for k, v in (entry.physical_delta or {}).items() if v > 0]
    return keys[0] if len(keys) == 1 else (entry.storage_to or "internal")


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
        # **rom_uid가 stale할 수 있다.** Apply가 부분적으로 성공한 System은 그 자리에서
        # 다시 스캔되고, 스캔은 그 System의 행을 통째로 지우고 다시 넣으므로 uid가
        # 전부 새로 매겨진다 - 파일이 실제로 없어진 게 아니라 **번호만 바뀐** 것이다.
        # 그걸 "이미 사라졌다"로 오판하면, PARTIAL(파일은 지웠지만 gamelist 정리가
        # 실패한 상태)을 재시도할 방법이 없어진다. 같은 System·같은 파일명을 찾아
        # 지금의 uid로 다시 연결한다 - 정말 없으면 그때는 이 경로도 실패한다.
        row = cache.get_row_by_filename(entry.system, entry.filename)
        if row is None:
            entry.status, entry.error = "invalid", "항목이 이미 사라졌습니다."
            return
        entry.rom_uid = row["rom_uid"]
    if not row["present"]:
        return  # metadata만 있는 항목. 지울 ROM 파일이 없다.

    layout = adapter.layout(collection, row["system"])
    rom_path = Path(layout.rom_dir) / row["filename"]
    if provider.stat(rom_path) is None:
        entry.status, entry.error = "invalid", "ROM 파일이 이미 사라졌습니다."
        return

    # **ADD와 같은 계약으로 본다**(size + mtime + volume_file_id). 삭제가 ADD보다
    # 약한 검증을 쓸 이유가 없다 - 되돌릴 수 없는 쪽이 오히려 삭제다.
    saved_rom = (entry.source or {}).get("romSnapshot") or {
        "size": int(row["size"] or 0), "mtimeNs": int(row["mtime_ns"] or 0),
        "fileId": row["volume_file_id"]}
    if not snapshot_matches(provider, rom_path, saved_rom):
        entry.status = "invalid"
        entry.error = "ROM 파일이 외부에서 변경되었습니다. 다시 스캔한 뒤 삭제해주세요."
        return

    # media도 지운다. 삭제는 되돌릴 수 없으므로 ROM만 확인하고 넘어가면, Plan을 만든
    # 뒤 밖에서 교체된 커버를 사용자 승인 없이 지우게 된다.
    #
    # 이미 사라진 media는 문제가 아니다 - 지우려던 목적이 이미 달성됐다.
    for saved_path, saved in ((entry.source or {}).get("mediaSnapshots") or {}).items():
        if provider.stat(saved_path) is None:
            continue
        if not snapshot_matches(provider, saved_path, saved):
            entry.status = "invalid"
            entry.error = "media 파일이 외부에서 변경되었습니다. 다시 스캔한 뒤 삭제해주세요."
            return


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

    **막을지 말지는 파일 시스템의 실제 여유 공간이 정한다.** Cache의 사용량은 마지막
    스캔 시점의 값이라 그 사이 다른 프로그램이 같은 디스크에 쓴 것을 모른다. Cache로
    판정하면 실제로는 꽉 찬 디스크에 복사를 시작하거나(위험), 반대로 여유가 충분한데
    막는다. Cache 기반 `planBytes`는 화면에 보여줄 예상값으로만 남긴다.
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
        if volume.free_bytes is not None and change > volume.free_bytes:
            over = change - volume.free_bytes
        result.append({
            "storageId": storage.storage_id, "label": storage.label,
            "actualBytes": used, "planBytes": planned, "deltaBytes": change,
            "capacityBytes": volume.capacity_bytes, "freeBytes": volume.free_bytes,
            "over": bool(over), "overBytes": over,
        })
    return result
