"""
app/plan/applier.py
====================
Plan을 실제 파일 변경으로 실행한다.

모든 쓰기는 FileOperationEngine(`file_ops`)을 통과한다 - UI도 여기도 직접
`shutil.copy()`를 부르지 않는다(스펙 §67-68). 패키징된 프로세스가 직접 대량
파일 작업을 하면 백신 행동 기반 탐지에 걸린다는 실측 결과 때문에 만들어진 구조라
그대로 지킨다.

실행 순서는 "파일 먼저, 메타데이터 나중"이다. 메타데이터를 먼저 쓰면 파일 복사가
실패했을 때 gamelist에는 있는데 ROM은 없는 상태가 남는다.
"""

from __future__ import annotations

from pathlib import Path

import file_ops
from adapters import get_adapter
from adapters.base import GameEntry
from app.model.plan import OP_ADD, OP_DELETE, OP_STORAGE_CHANGE

#: 한 번에 워커로 넘길 파일 쌍 수. 너무 작으면 워커 spawn 비용이 누적되고,
#: 너무 크면 진행률이 뚝뚝 끊긴다.
BATCH_SIZE = 150


def apply_plan(plan, collection, cache, registry, provider, progress_cb=None) -> dict:
    """Plan을 실행한다. 반환: {"applied","failed","errors":[...]}"""
    adapter = get_adapter(collection.frontend)
    entries = [e for e in plan.entries if e.status != "invalid"]

    adds = [e for e in entries if e.op == OP_ADD]
    deletes = [e for e in entries if e.op == OP_DELETE]
    moves = [e for e in entries if e.op == OP_STORAGE_CHANGE]

    # 진행률에는 마지막 정리 단계 몫을 하나 더 얹는다. 그래야 파일 작업이 끝나기
    # 전에 진행률이 100%에 도달하지 않는다.
    total = len(adds) + len(deletes) + len(moves) + 1
    done = 0
    errors = []

    def step(label):
        nonlocal done
        done += 1
        if progress_cb:
            progress_cb(done, total, label)

    for entry in adds:
        _apply_add(entry, collection, adapter, provider, errors)
        step(entry.filename)
    for entry in deletes:
        _apply_delete(entry, collection, adapter, cache, errors)
        step(entry.filename)
    for entry in moves:
        _apply_storage_change(entry, collection, adapter, cache, registry, errors)
        step(entry.system)

    applied = [e for e in entries if e.status == "applied"]
    failed = [e for e in entries if e.status == "failed"]
    for entry in applied:
        plan.remove(entry.key)

    step("정리 중")
    return {"applied": len(applied), "failed": len(failed), "errors": errors}


# ----------------------------------------------------------------------
def _apply_add(entry, collection, adapter, provider, errors):
    layout = adapter.layout(collection, entry.system)
    source = entry.source or {}
    dest_dirs, pairs = [], []

    rom = source.get("rom") or {}
    rom_dest = None
    if rom.get("path"):
        rom_dest = Path(layout.rom_dir) / entry.filename
        dest_dirs.append(rom_dest.parent)
        pairs.append((Path(rom["path"]), rom_dest))

    from app.plan.builder import _MediaRef
    media_refs = [_MediaRef(m) for m in (source.get("media") or [])]
    for src, dest in adapter.media_pairs(layout, entry.filename, media_refs):
        dest_dirs.append(Path(dest).parent)
        pairs.append((Path(src), Path(dest)))

    if pairs:
        results = file_ops.copy_files(dest_dirs, pairs)
        failed = [str(d) for _, d in pairs if not results.get(str(d))]
        if failed:
            entry.status, entry.error = "failed", f"{len(failed)}개 파일 복사 실패"
            errors.append(f"{entry.filename}: 파일 복사 실패")
            return

    # 파일이 자리를 잡은 뒤에 메타데이터를 쓴다.
    fields = entry.payload or source.get("fields") or {}
    try:
        adapter.write_index(layout, [GameEntry(filename=entry.filename, fields=fields,
                                               frontend_raw=source.get("frontend_raw") or {})])
    except Exception as e:  # noqa: BLE001
        entry.status, entry.error = "failed", str(e)
        errors.append(f"{entry.filename}: Metadata 기록 실패 - {e}")
        return
    entry.status = "applied"


def _apply_delete(entry, collection, adapter, cache, errors):
    layout = adapter.layout(collection, entry.system)
    row = cache.get_row(entry.rom_uid) if entry.rom_uid is not None else None
    targets = []
    if row:
        if row["present"]:
            targets.append(Path(layout.rom_dir) / row["filename"])
        targets.extend(Path(m["rel_path"]) for m in row["media"])

    if targets:
        results = file_ops.delete_files(targets)
        failed = [p for p in targets if not results.get(str(p))]
        if failed:
            entry.status, entry.error = "failed", f"{len(failed)}개 파일 삭제 실패"
            errors.append(f"{entry.filename}: 파일 삭제 실패")
            return

    # gamelist에서도 지운다. Adapter는 "주어진 항목만 갱신"이 계약이라 삭제는
    # 별도 경로가 필요하다 - 지금은 metadata를 비우지 않고 파일만 지운다.
    # (gamelist 항목 제거는 Cleanup 기능에서 다룬다 - 스펙 §70)
    entry.status = "applied"


def _apply_storage_change(entry, collection, adapter, cache, registry, errors):
    """System의 ROM 파일을 새 Storage로 옮기고, 배치 정보를 갱신한다.

    media는 Collection root에 남으므로 건드리지 않는다.
    """
    old_layout = adapter.layout(collection, entry.system)

    # 옮긴 뒤의 배치를 가정한 layout이 필요하다. registry를 먼저 갱신하면 실패 시
    # 되돌리기가 번거로우므로, 메모리 상의 Collection만 잠시 바꿔서 계산한다.
    system_entry = next((s for s in collection.systems if s.system == entry.system), None)
    if system_entry is None:
        entry.status, entry.error = "failed", "System을 찾을 수 없습니다."
        return
    original_storage = system_entry.storage_id
    system_entry.storage_id = entry.storage_to
    new_layout = adapter.layout(collection, entry.system)
    system_entry.storage_id = original_storage

    rows = cache.query_rows(systems=[entry.system])
    pairs = [(Path(old_layout.rom_dir) / r["filename"], Path(new_layout.rom_dir) / r["filename"])
             for r in rows if r["present"]]

    if pairs:
        results = file_ops.move_files(pairs)
        failed = [str(d) for _, d in pairs if not results.get(str(d))]
        if failed:
            entry.status, entry.error = "failed", f"{len(failed)}개 파일 이동 실패"
            errors.append(f"{entry.system}: 파일 이동 실패 ({len(failed)}개)")
            return

    try:
        registry.move_system(collection.id, entry.system, entry.storage_to)
    except Exception as e:  # noqa: BLE001
        entry.status, entry.error = "failed", str(e)
        errors.append(f"{entry.system}: 배치 갱신 실패 - {e}")
        return
    entry.status = "applied"
