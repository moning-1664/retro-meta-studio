"""
app/plan/applier.py
====================
Plan을 실제 파일 변경으로 실행한다.

모든 쓰기는 FileOperationEngine(`file_ops`)을 통과한다 - UI도 여기도 직접
`shutil.copy()`를 부르지 않는다(스펙 §67-68).

## 이 파일의 제1 원칙: 실패해도 데이터가 망가지지 않아야 한다

ROM 관리 도구에서 가장 위험한 것은 기능이 없는 게 아니라 **"정상 상황에서는 잘 되는데
예외 상황에서 DB와 실제 파일 상태가 서로 달라지는 것"**이다. 파일을 잃으면 복구가
어렵다. 그래서 각 작업은 다음을 지킨다.

- **ADD**: 파일을 먼저 옮기고 메타데이터를 나중에 쓴다. 메타데이터 기록이 실패하면
  이번에 새로 만든 파일을 되돌린다. 되돌리기까지 실패하면 단순 실패가 아니라
  `partial`로 표시해서 사용자가 손대야 한다는 것을 알 수 있게 한다.
- **STORAGE CHANGE**: 이동 → 검증 → Registry 갱신 순서로 가되, 어느 단계가 실패하든
  **이미 옮겨진 파일을 원래 자리로 되돌린다.** 파일은 옮겨졌는데 Registry는 예전
  위치를 가리키는 상태(또는 그 반대)를 만들지 않는 것이 목적이다.
- **해결되지 않은 충돌**은 아예 건드리지 않는다. 목적지에 있는 남의 파일을 크기가
  같다는 이유로 덮어쓰지 않는다.
"""

from __future__ import annotations

from pathlib import Path

import file_ops
from adapters import get_adapter
from adapters.base import GameEntry
from app.model.plan import (
    OP_ADD, OP_DELETE, OP_STORAGE_CHANGE, RESOLVE_OVERWRITE,
    STATUS_APPLIED, STATUS_FAILED, STATUS_PARTIAL,
)
from app.plan.builder import ACTION_CONFLICT, ACTION_IDENTICAL, classify_destination


def apply_plan(plan, collection, cache, registry, provider, progress_cb=None) -> dict:
    """Plan을 실행한다.

    반환: {"applied", "failed", "partial", "skipped", "errors":[...], "systems":[...]}
    `systems`는 실제로 건드린 System 목록이다 - 호출부가 그 System만 다시 스캔해서
    Cache를 맞출 수 있도록 돌려준다(전체 Full Scan을 피하기 위함).
    """
    adapter = get_adapter(collection.frontend)

    # 해결되지 않은 충돌과 이미 invalid로 판정된 항목은 실행 대상이 아니다.
    runnable = [e for e in plan.entries if e.status != "invalid" and not e.blocked]
    blocked = [e for e in plan.entries if e.blocked]

    adds = [e for e in runnable if e.op == OP_ADD]
    deletes = [e for e in runnable if e.op == OP_DELETE]
    moves = [e for e in runnable if e.op == OP_STORAGE_CHANGE]

    # 진행률에 마지막 정리 단계 몫을 하나 더 얹는다. 파일 작업이 끝나기 전에 진행률이
    # 100%에 도달하지 않도록.
    total = len(adds) + len(deletes) + len(moves) + 1
    done = 0
    errors = []
    touched_systems = set()

    def step(label):
        nonlocal done
        done += 1
        if progress_cb:
            progress_cb(done, total, label)

    # {system: {filename: [(media_type, dest), ...]}} - 항목별로 모았다가 System 단위로
    # 한 번에 기록한다. ROM 하나마다 gamelist.xml을 다시 쓰면 O(n^2)가 된다(계약 1).
    media_links: dict[str, dict[str, list]] = {}

    for entry in adds:
        _apply_add(entry, collection, adapter, provider, errors, media_links)
        touched_systems.add(entry.system)
        step(entry.filename)
    for entry in deletes:
        _apply_delete(entry, collection, adapter, cache, provider, errors)
        touched_systems.add(entry.system)
        step(entry.filename)
    for entry in moves:
        _apply_storage_change(entry, collection, adapter, cache, registry, provider, errors)
        touched_systems.add(entry.system)
        step(entry.system)

    _write_media_links(adds, collection, adapter, media_links, errors)

    applied = [e for e in runnable if e.status == STATUS_APPLIED]
    failed = [e for e in runnable if e.status == STATUS_FAILED]
    partial = [e for e in runnable if e.status == STATUS_PARTIAL]

    # 성공한 것만 Plan에서 뺀다. 실패/부분성공/충돌은 남겨서 사용자가 다시 볼 수 있게 한다.
    for entry in applied:
        plan.remove(entry.key)

    step("정리 중")
    return {
        "applied": len(applied), "failed": len(failed), "partial": len(partial),
        "skipped": len(blocked), "errors": errors, "systems": sorted(touched_systems),
    }


def _write_media_links(adds, collection, adapter, media_links, errors):
    """모아둔 media 링크를 System 단위로 기록한다.

    실패하면 그 System의 항목들을 **PARTIAL로 내린다.** 파일은 복사됐지만 Frontend가
    그것을 못 찾는 상태이므로, 성공으로 처리해 Plan에서 지워버리면 사용자는 왜 media가
    안 보이는지 알 길이 없어진다.
    """
    for system, links in media_links.items():
        if not links:
            continue
        layout = adapter.layout(collection, system)
        try:
            adapter.write_media_links(layout, links)
        except Exception as e:  # noqa: BLE001
            message = f"media 경로 기록 실패: {e}"
            for entry in adds:
                if entry.system == system and entry.filename in links                         and entry.status == STATUS_APPLIED:
                    entry.status, entry.error = STATUS_PARTIAL, message
                    errors.append(f"{entry.filename}: {message}")


# ----------------------------------------------------------------------
# ADD
# ----------------------------------------------------------------------
def _plan_copies(entry, layout, adapter, provider):
    """지금 시점의 목적지 상태를 보고 실제로 복사할 쌍을 고른다.

    Plan을 만든 뒤 시간이 흘렀을 수 있으므로 저장해둔 판정을 믿지 않고 다시 본다.
    반환: (pairs, newly_created) - newly_created는 이번에 처음 생기는 목적지들이라
    롤백할 때 지워도 되는 것들이다.
    """
    from app.plan.builder import _MediaRef

    source = entry.source or {}
    overwrite = entry.resolution == RESOLVE_OVERWRITE
    candidates = []

    rom = source.get("rom") or {}
    if rom.get("path"):
        candidates.append((Path(rom["path"]), Path(layout.rom_dir) / entry.filename,
                           int(rom.get("size") or 0)))

    media_refs = [_MediaRef(m) for m in (source.get("media") or [])]
    media_sizes = {str(m.path): m.size for m in media_refs}
    for src, dest in adapter.media_pairs(layout, entry.filename, media_refs):
        candidates.append((Path(src), Path(dest), media_sizes.get(str(src), 0)))

    pairs, created = [], []
    for src, dest, size in candidates:
        action, _ = classify_destination(provider, src, size, dest)
        if action == ACTION_IDENTICAL:
            continue  # 이미 같은 파일이 있다. 건드릴 이유가 없다.
        if action == ACTION_CONFLICT and not overwrite:
            continue  # 해결되지 않았거나 건너뛰기로 정한 충돌
        if not dest.exists():
            created.append(dest)
        pairs.append((src, dest))
    return pairs, created


def _apply_add(entry, collection, adapter, provider, errors, media_links=None):
    """`media_links`를 주면 이 항목이 남길 media 링크를 거기 모아 둔다.

    실제 기록은 여기서 하지 않는다 - System 단위로 한 번만 쓰기 위해 호출부가 모았다가
    마지막에 `adapter.write_media_links()`를 부른다(계약 1).
    """
    layout = adapter.layout(collection, entry.system)
    pairs, created = _plan_copies(entry, layout, adapter, provider)

    if pairs:
        dest_dirs = [dest.parent for _, dest in pairs]
        results = file_ops.copy_files(dest_dirs, pairs)
        failed = [dest for _, dest in pairs if not results.get(str(dest))]
        if failed:
            # 파일 단계에서 실패했으면 메타데이터는 쓰지 않는다. 이번에 새로 만든
            # 파일만 정리한다 - 원래 있던 파일은 건드리지 않는다.
            _rollback_files(created, errors, entry)
            entry.status, entry.error = STATUS_FAILED, f"{len(failed)}개 파일 복사 실패"
            errors.append(f"{entry.filename}: 파일 복사 실패")
            return

    # 파일이 자리를 잡은 뒤에 메타데이터를 쓴다. 순서가 반대면 복사 실패 시
    # gamelist에만 있는 유령 항목이 남는다.
    fields = entry.payload or (entry.source or {}).get("fields") or {}
    try:
        # ADD는 **다른 Collection에서 온 항목**을 이 Collection에 적는 것이다.
        # 원본 보존값(frontend_raw)에는 두 가지 함정이 있다.
        #
        # 1) 다른 Frontend의 값이면 **모양부터 다르다**(ES-DE는 {"tag","text"},
        #    Pegasus는 {"key","value"}). 그대로 넘기면 되살리다 깨진다 - 실제로
        #    ES-DE -> Pegasus Convert가 KeyError로 실패했다. Frontend 간 변환에서
        #    frontend_raw가 따라가지 않는 것은 §50-51의 정의이기도 하다.
        # 2) 같은 Frontend라도 경로처럼 "그 자리에서만 참인 값"은 걷어내야 한다.
        source_raw = (entry.source or {}).get("frontend_raw")
        preserved = (adapter.strip_location_raw(source_raw)
                     if adapter.raw_is_mine(source_raw) else {})
        adapter.write_index(layout, [GameEntry(filename=entry.filename, fields=fields,
                                               frontend_raw=preserved)])
    except Exception as e:  # noqa: BLE001
        # 메타데이터를 못 썼으면 이번에 만든 파일을 되돌린다. 안 그러면 다음 Apply가
        # "이미 존재하는 ROM"을 다시 만나 충돌로 막히거나 중복 처리하게 된다.
        recovered = _rollback_files(created, errors, entry)
        entry.status = STATUS_FAILED if recovered else STATUS_PARTIAL
        entry.error = (f"Metadata 기록 실패: {e}" if recovered
                       else f"Metadata 기록 실패 후 복사된 파일 정리에도 실패: {e}")
        errors.append(f"{entry.filename}: {entry.error}")
        return

    # 이 Frontend가 media 경로를 메타데이터에 적어야 하면(원조 ES) 무엇을 적을지만
    # 계산해 둔다. 실제로 있는 파일만 남긴다 - 복사가 건너뛰어진 media까지 적으면
    # gamelist가 없는 파일을 가리키게 된다.
    if media_links is not None:
        from app.plan.builder import _MediaRef
        refs = [_MediaRef(m) for m in ((entry.source or {}).get("media") or [])]
        links = [(media_type, dest)
                 for media_type, dest in adapter.build_media_links(layout, entry.filename, refs)
                 if Path(dest).exists()]
        if links:
            media_links.setdefault(entry.system, {})[entry.filename] = links

    entry.status = STATUS_APPLIED


def _rollback_files(paths, errors, entry) -> bool:
    """이번 작업이 새로 만든 파일만 지운다. 전부 지웠으면 True."""
    remaining = [p for p in paths if Path(p).exists()]
    if not remaining:
        return True
    results = file_ops.delete_files(remaining)
    leftover = [p for p in remaining if not results.get(str(p))]
    if leftover:
        errors.append(f"{entry.filename}: 되돌리지 못한 파일 {len(leftover)}개 - "
                      f"{leftover[0]} 등")
        return False
    return True


# ----------------------------------------------------------------------
# DELETE
# ----------------------------------------------------------------------
def _apply_delete(entry, collection, adapter, cache, provider, errors):
    """게임을 지운다: ROM + Media + gamelist 항목.

    사용자가 Gamelist에서 Delete를 눌렀을 때 기대하는 것은 셋 다 사라지는 것이다.
    ROM/Media만 지우고 gamelist 항목을 남기면 다음 스캔에서 metadata-only 항목으로
    되살아난 것처럼 보인다.
    """
    layout = adapter.layout(collection, entry.system)
    row = cache.get_row(entry.rom_uid) if entry.rom_uid is not None else None
    targets = []
    if row:
        if row["present"]:
            targets.append(Path(layout.rom_dir) / row["filename"])
        targets.extend(Path(m["rel_path"]) for m in row["media"])

    existing = [p for p in targets if provider.exists(p)]
    if existing:
        results = file_ops.delete_files(existing)
        failed = [p for p in existing if not results.get(str(p))]
        if failed:
            entry.status, entry.error = STATUS_FAILED, f"{len(failed)}개 파일 삭제 실패"
            errors.append(f"{entry.filename}: 파일 삭제 실패")
            return

    remove = getattr(adapter, "remove_entries", None)
    if remove is not None:
        try:
            remove(layout, [entry.filename])
        except Exception as e:  # noqa: BLE001
            # 파일은 이미 지워졌으므로 단순 실패가 아니다. 사용자가 알아야 한다.
            entry.status = STATUS_PARTIAL
            entry.error = f"파일은 삭제했지만 gamelist 항목 제거에 실패: {e}"
            errors.append(f"{entry.filename}: {entry.error}")
            return
    entry.status = STATUS_APPLIED


# ----------------------------------------------------------------------
# STORAGE CHANGE
# ----------------------------------------------------------------------
def _apply_storage_change(entry, collection, adapter, cache, registry, provider, errors):
    """System의 ROM 파일을 새 Storage로 옮기고 배치 정보를 갱신한다.

    media는 Collection root에 남으므로 건드리지 않는다.

    **이동과 Registry 갱신은 하나의 논리적 트랜잭션이다.** 둘 중 하나만 성공하면
    "파일은 External인데 Registry는 Internal"처럼 앱이 ROM을 찾지 못하는 상태가
    된다. 그래서 어느 단계가 실패하든 이미 옮긴 파일을 되돌린다.
    """
    old_layout = adapter.layout(collection, entry.system)

    system_entry = next((s for s in collection.systems if s.system == entry.system), None)
    if system_entry is None:
        entry.status, entry.error = STATUS_FAILED, "System을 찾을 수 없습니다."
        errors.append(f"{entry.system}: System을 찾을 수 없습니다.")
        return

    # 옮긴 뒤의 배치를 가정한 layout이 필요하다. Registry를 먼저 바꾸면 실패 시
    # 되돌리기가 번거로우므로 메모리 상의 Collection만 잠시 바꿔서 계산한다.
    original_storage = system_entry.storage_id
    system_entry.storage_id = entry.storage_to
    new_layout = adapter.layout(collection, entry.system)
    system_entry.storage_id = original_storage

    rows = cache.query_rows(systems=[entry.system])
    pairs = [(Path(old_layout.rom_dir) / r["filename"], Path(new_layout.rom_dir) / r["filename"])
             for r in rows if r["present"]]
    pairs = [(src, dest) for src, dest in pairs if provider.exists(src)]

    # 목적지에 이미 파일이 있으면 이동을 시작하지 않는다. 무엇을 덮어쓸지는 사용자가
    # 정할 문제다(스펙 §85 - 모호한 상황에서 자동으로 결정하지 않는다).
    collisions = [dest for _, dest in pairs if provider.exists(dest)]
    if collisions:
        entry.status = STATUS_FAILED
        entry.error = (f"대상 Storage에 같은 이름의 파일이 {len(collisions)}개 있습니다: "
                       f"{collisions[0].name} 등")
        errors.append(f"{entry.system}: {entry.error}")
        return

    moved = []
    if pairs:
        results = file_ops.move_files(pairs)
        moved = [(src, dest) for src, dest in pairs if results.get(str(dest))]
        if len(moved) != len(pairs):
            # 일부만 옮겨진 상태를 그대로 두면 Registry와도, 사용자의 기대와도 어긋난다.
            # 옮겨진 것을 원래 자리로 되돌려서 "아무 일도 없었던" 상태로 만든다.
            restored = _restore_moved(moved, errors, entry)
            entry.status = STATUS_FAILED if restored else STATUS_PARTIAL
            entry.error = (f"{len(pairs) - len(moved)}개 파일 이동 실패"
                           if restored else
                           f"{len(pairs) - len(moved)}개 이동 실패 후 되돌리기도 실패 - "
                           "파일이 두 Storage에 나뉘어 있습니다")
            errors.append(f"{entry.system}: {entry.error}")
            return

    try:
        registry.move_system(collection.id, entry.system, entry.storage_to)
    except Exception as e:  # noqa: BLE001
        # 파일은 옮겨졌는데 Registry가 못 따라온 경우다. 그대로 두면 앱이 ROM을
        # 찾지 못하므로 파일을 원래 자리로 되돌린다.
        restored = _restore_moved(moved, errors, entry)
        entry.status = STATUS_FAILED if restored else STATUS_PARTIAL
        entry.error = (f"배치 갱신 실패로 이동을 되돌렸습니다: {e}" if restored else
                       f"배치 갱신 실패({e}) 후 되돌리기도 실패 - 파일 위치와 설정이 "
                       "어긋나 있습니다")
        errors.append(f"{entry.system}: {entry.error}")
        return

    # 메모리 상의 Collection도 갱신해야 뒤이은 항목들이 새 배치를 본다.
    system_entry.storage_id = entry.storage_to
    entry.status = STATUS_APPLIED


def _restore_moved(moved, errors, entry) -> bool:
    """이미 옮긴 파일을 원래 자리로 되돌린다. 전부 되돌렸으면 True."""
    if not moved:
        return True
    back = [(dest, src) for src, dest in moved]
    results = file_ops.move_files(back)
    failed = [dest for _, dest in back if not results.get(str(dest))]
    if failed:
        errors.append(f"{entry.system}: {len(failed)}개 파일을 원래 위치로 되돌리지 못했습니다.")
        return False
    return True
