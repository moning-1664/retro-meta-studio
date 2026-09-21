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
- **ADD(덮어쓰기)**: 기존 파일을 덮어쓰기로 한 경우, **덮어쓰기 전에 원본을 옆으로
  치워 둔다.** `복사 성공 != 작업 성공`이기 때문이다 - 복사는 됐는데 gamelist 기록이
  실패하면, 새로 만든 파일만 지우는 롤백으로는 이미 사라진 원본을 되살릴 수 없다.
  치워둔 원본은 **그 항목의 작업이 끝까지 성공한 뒤에** 지운다.
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
    OP_ADD, OP_DELETE, OP_METADATA_EDIT, OP_STORAGE_CHANGE, OP_TITLE_EDIT,
    RESOLVE_OVERWRITE, RESOLVE_SKIP, STATUS_APPLIED, STATUS_FAILED, STATUS_PARTIAL, PlanEntry,
)
from app.plan.builder import ACTION_CONFLICT, ACTION_IDENTICAL, classify_destination
from utils import normalize_title


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
    # 제목 편집과 기기 Collection의 메타데이터 편집은 쓰는 방식이 같다(System 단위 묶음 쓰기).
    retitles = [e for e in runnable if e.op in (OP_TITLE_EDIT, OP_METADATA_EDIT)]

    # Storage 이동은 **옮길 ROM 수만큼** 걸음을 잡는다(§ MOVE_PROGRESS_STEPS). System
    # 하나를 한 걸음으로 두면 수십 GB를 옮기는 내내 진행률이 멈춰 있다.
    move_units = {entry.key: max(1, sum(1 for row in cache.query_rows(systems=[entry.system])
                                        if row["present"]))
                  for entry in moves}

    # 진행률에 마지막 정리 단계 몫을 하나 더 얹는다. 파일 작업이 끝나기 전에 진행률이
    # 100%에 도달하지 않도록.
    total = len(adds) + len(deletes) + sum(move_units.values()) + len(retitles) + 1
    done = 0
    errors = []

    def step(what, amount=1):
        """진행률을 올린다. `what`은 PlanEntry(무엇을 하는 중인지 풀어서 적는다) 또는 문자열이다.

        **표시하는 개수는 항목 수다.** total에는 마지막 정리 단계 몫(+1)이 들어 있는데, 그것까지 세어
        "(1/4)"처럼 보이면 항목이 셋인데 왜 넷인지 알 수 없다(실사용 피드백). 화면에는 정리 몫을
        뺀 개수를 적고, 문구는 `_describe()`가 실제로 하는 일로 만든다(ROM을 복사하지 않는
        항목에 ROM 파일명이 나오면 거짓말이다).
        """
        nonlocal done
        done += amount
        if progress_cb:
            items = max(1, total - 1)
            label = _describe(what) if isinstance(what, PlanEntry) else str(what)
            progress_cb(done, total, f"{label} · {min(done, items)}/{items}")

    # {system: {filename: [(media_type, dest), ...]}} - 항목별로 모았다가 System 단위로
    # 한 번에 기록한다. ROM 하나마다 gamelist.xml을 다시 쓰면 O(n^2)가 된다(계약 1).
    media_links: dict[str, dict[str, list]] = {}

    prepared_adds = _apply_adds(adds, collection, adapter, provider, errors, media_links, step)
    for entry in deletes:
        _apply_delete(entry, collection, adapter, cache, provider, errors)
        step(entry)
    for entry in moves:
        reported = _apply_storage_change(entry, collection, adapter, cache, registry,
                                         provider, errors, step)
        # 이동이 도중에 멈췄어도 이 항목 몫은 끝까지 채운다 - 안 채우면 작업이 다
        # 끝났는데도 진행률이 중간에 걸린 채로 사라진다.
        if reported < move_units[entry.key]:
            step(f"이동 중: {entry.system}", move_units[entry.key] - reported)

    _apply_title_edits(retitles, collection, adapter, cache, errors, step)

    _write_media_links(adds, collection, adapter, media_links, errors)
    # 백업은 **여기서** 정리한다. 복사가 끝난 시점이 아니라 그 항목의 작업 전체가
    # 끝난 시점이 커밋이다(§ADD 덮어쓰기).
    _settle_backups(prepared_adds, errors)

    applied = [e for e in runnable if e.status == STATUS_APPLIED]
    failed = [e for e in runnable if e.status == STATUS_FAILED]
    partial = [e for e in runnable if e.status == STATUS_PARTIAL]

    # **실제로 뭔가 바뀐 System만 rescan 대상으로 돌려준다.** 호출부(bridge/api.py)가
    # 이 목록으로 부분 rescan을 하는데, rescan은 그 System의 Cache 행을 통째로
    # 지우고 다시 넣으므로 rom_uid가 전부 새로 매겨진다. FAILED 항목은 아무것도
    # 바꾸지 못했으므로(파일도 gamelist도 그대로) 그 System까지 rescan 대상에 넣으면
    # 실패한 적도 없는데 rom_uid만 갈아치우는 셈이 되고, 그 순간 Plan의 항목이 가리키던
    # rom_uid는 존재하지 않는 것이 되어 - 재시도하면 "항목이 이미 사라졌습니다"로
    # 보인다. 실제로는 아무것도 사라지지 않았는데도.
    touched_systems = {e.system for e in applied + partial}

    # 성공한 것만 Plan에서 뺀다. 실패/부분성공/충돌은 남겨서 사용자가 다시 볼 수 있게 한다.
    for entry in applied:
        plan.remove(entry.key)

    step("정리 중")
    return {
        "applied": len(applied), "failed": len(failed), "partial": len(partial),
        "skipped": len(blocked), "errors": errors, "systems": sorted(touched_systems),
    }


def _describe(entry) -> str:
    """진행률에 적을 한 줄 - **실제로 하는 일**과 사람이 읽는 이름(파일명이 아니라 제목)."""
    source = entry.source or {}
    fields = entry.payload or source.get("fields") or {}
    name = (fields.get("name") or "").strip() or entry.new_title or entry.filename
    if entry.op == OP_ADD:
        rom = source.get("rom") or {}
        if rom.get("path"):
            return f"복사 중: {name}"
        return f"메타데이터·미디어 반영 중: {name}"
    if entry.op == OP_DELETE:
        parts = entry.delete_parts
        return f"삭제 중: {name}" if {"rom", "metadata"} <= set(parts) else f"일부 삭제 중: {name}"
    if entry.op == OP_STORAGE_CHANGE:
        return f"이동 중: {entry.system}"
    return f"수정 중: {name}"


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
    반환: (pairs, newly_created, replaced, blocked)
    - newly_created: 이번에 처음 생기는 목적지. 롤백할 때 지워도 되는 것들이다.
    - replaced: 이미 파일이 있어서 **덮어쓰게 되는** 목적지. 지워버리면 안 되고,
      덮어쓰기 전에 치워 뒀다가 실패하면 되돌려야 하는 것들이다.
    - blocked: 덮어쓰게 되는데 **승인받지 않은** 목적지. 조용히 건너뛰면 안 된다 -
      건너뛰고 메타데이터만 쓰면 gamelist가 남의 ROM을 가리키게 된다.
    """
    from app.plan.builder import add_destinations, approved_targets, snapshot_matches

    # 사용자가 덮어쓰기를 승인한 **파일별** 목록. 승인이 없으면 빈 dict다.
    # `RESOLVE_SKIP`("메타데이터만")도 media(kind != "rom")는 승인된 것으로 온다 -
    # ROM은 보존하고 media는 원본 것으로 채우는 것이 그 선택의 목적이다
    # (Phase 7.22 QA, `approved_targets()` 참고).
    approved = approved_targets(entry)
    kind_by_dest = {str(c["dest"]): c.get("kind") for c in (entry.conflicts or []) if c.get("dest")}

    pairs, created, replaced, blocked = [], [], [], []
    for src, dest, size in add_destinations(entry, layout, adapter):
        action, _ = classify_destination(provider, src, size, dest)
        if action == ACTION_IDENTICAL:
            continue  # 이미 같은 파일이 있다. 건드릴 이유가 없다.
        if action == ACTION_CONFLICT:
            # ROM 충돌만 "그대로 두라"는 뜻이다 - `RESOLVE_SKIP`이라도 media는
            # 아래에서 승인된 대상으로 취급되어 계속 진행된다.
            if entry.resolution == RESOLVE_SKIP and kind_by_dest.get(str(dest)) == "rom":
                continue
            # 여기가 마지막 방어선이다. 승인받은 그 파일일 때만 덮어쓴다.
            if str(dest) not in approved or not snapshot_matches(provider, dest,
                                                                 approved[str(dest)]):
                blocked.append(dest)
                continue
            replaced.append(dest)
        else:
            created.append(dest)
        pairs.append((src, dest))
    return pairs, created, replaced, blocked


#: 한 번의 복사 호출에 묶는 항목 수.
#:
#: `_apply_add`가 항목마다 `file_ops.copy_files()`를 부르던 때, 실측으로 항목당 약
#: 50ms가 들었고 그중 80%가 **복사 호출 자체**였다(200게임 Apply 9.79s -> 복사 호출을
#: 없애면 1.98s). Robocopy 프로세스가 항목마다 새로 뜨는 비용이다.
#:
#: 그렇다고 전부 한 번에 묶지는 않는다. 복사는 Apply에서 가장 오래 걸리는 구간이라,
#: 통째로 묶으면 그 동안 진행률이 멈춰 사용자는 앱이 죽은 것으로 본다. 묶음 하나가
#: 끝날 때마다 그 안의 항목들을 진행률에 반영한다.
COPY_BATCH = 25


#: 덮어쓰기 전에 원본을 치워 둘 때 붙이는 꼬리표. 스캔에서 ROM으로 잡히지 않는
#: 확장자여야 하고, 남아 있으면 사용자가 무엇인지 알아볼 수 있어야 한다.
BACKUP_SUFFIX = ".rms-backup"


def _prepare_add(entry, collection, adapter, provider):
    """복사할 쌍을 계산만 한다. 파일은 건드리지 않는다."""
    layout = adapter.layout(collection, entry.system)
    pairs, created, replaced, blocked = _plan_copies(entry, layout, adapter, provider)
    return {"entry": entry, "layout": layout, "pairs": pairs, "created": created,
            "replaced": replaced, "blocked": blocked, "backups": [], "provider": provider}


def _backup_replaced(item, errors) -> bool:
    """덮어쓸 기존 파일을 옆으로 치워 둔다. 못 치우면 그 항목은 시작하지 않는다.

    치우지 못한 채로 덮어쓰기를 시작하면, 그 뒤로 어떤 단계가 실패하든 원본을 되살릴
    방법이 없다. 시작하지 않는 편이 낫다.
    """
    targets = item.get("replaced") or []
    if not targets:
        return True
    pairs = [(dest, Path(str(dest) + BACKUP_SUFFIX)) for dest in targets]
    results = file_ops.move_files(pairs)
    item["backups"] = [(dest, backup) for dest, backup in pairs if results.get(str(backup))]
    if len(item["backups"]) == len(pairs):
        return True

    entry = item["entry"]
    _restore_backups(item, errors)
    entry.status, entry.error = STATUS_FAILED, "기존 파일을 백업하지 못했습니다."
    errors.append(f"{entry.filename}: 기존 파일을 백업하지 못해 덮어쓰지 않았습니다.")
    return False


def _restore_backups(item, errors) -> bool:
    """치워둔 원본을 제자리로 되돌린다. 전부 되돌렸으면 True."""
    backups = item.get("backups") or []
    item["backups"] = []
    if not backups:
        return True
    # 새로 쓰인 파일이 자리를 차지하고 있으면 먼저 치운다 - 안 그러면 되돌릴 자리가 없다.
    occupied = [dest for dest, _b in backups if Path(dest).exists()]
    if occupied:
        file_ops.delete_files(occupied)
    results = file_ops.move_files([(backup, dest) for dest, backup in backups])
    failed = [dest for dest, _b in backups if not results.get(str(dest))]
    _refresh_approval(item, [dest for dest, _b in backups if results.get(str(dest))])
    if failed:
        errors.append(f"{item['entry'].filename}: 원본을 되돌리지 못했습니다 - {failed[0]} 등")
        return False
    return True


def _refresh_approval(item, restored):
    """되돌려 놓은 파일에 맞춰 승인 기록을 다시 찍는다.

    **우리가 직접 되돌린 파일은 "밖에서 바뀐 파일"이 아니다.** 그런데 되돌리기는
    옮기기라서 파일 식별자가 달라지고, 그대로 두면 다음 Validate가 "대상이 바뀌었다"고
    판정해 사용자의 승인을 무효로 만든다. 실패한 뒤 재시도가 막히고, 게다가 원인이
    "밖에서 누가 건드렸다"로 잘못 표시된다.

    내용이 같다는 것은 우리가 안다 - 방금 우리가 그 바이트를 도로 갖다 놓았다.
    """
    if not restored:
        return
    from app.plan.builder import snapshot

    provider = item.get("provider")
    if provider is None:
        return
    wanted = {str(dest) for dest in restored}
    for conflict in item["entry"].conflicts or []:
        if str(conflict.get("dest")) in wanted:
            conflict["destSnapshot"] = snapshot(provider, conflict["dest"])


def _settle_backups(prepared, errors):
    """작업이 끝난 뒤 백업을 정리한다. **여기까지 와야 커밋이다.**

    - 실패한 항목: 원본을 되돌린다. 사용자에게는 "아무 일도 없었다"가 되어야 한다.
    - 성공/부분성공: 백업을 지운다. 부분성공은 파일을 일부러 남겨두는 상태이므로
      되돌리면 안 된다 - 사용자가 손대야 한다는 표시일 뿐이다.
    """
    for item in prepared:
        if not item.get("backups"):
            continue
        if item["entry"].status == STATUS_FAILED:
            if not _restore_backups(item, errors):
                item["entry"].status = STATUS_PARTIAL
            continue
        leftovers = [backup for _dest, backup in item["backups"] if Path(backup).exists()]
        item["backups"] = []
        if leftovers:
            file_ops.delete_files(leftovers)


def _undo(item, errors) -> bool:
    """이번 작업이 만든 것을 지우고, 치워둔 원본을 되돌린다."""
    removed = _rollback_files(item["created"], errors, item["entry"])
    restored = _restore_backups(item, errors)
    return removed and restored


def _copy_prepared(prepared, errors, step):
    """묶어서 복사하고, 결과를 항목별로 되돌려 준다.

    **호출은 묶지만 실패의 단위는 항목 그대로다.** `copy_files()`가 목적지별 성공
    여부를 돌려주므로, 한 항목이 실패해도 되돌리는 것은 그 항목이 이번에 새로 만든
    파일뿐이다 - 묶었다고 남의 파일까지 되돌리면 안 된다.
    """
    for item in prepared:
        if not item.get("blocked"):
            continue
        # 승인받지 않은 파일이 목적지에 있다. **아무것도 하지 않는다** - 그 파일만
        # 건너뛰고 메타데이터를 쓰면 gamelist가 남의 ROM을 가리키게 된다.
        entry = item["entry"]
        entry.status = STATUS_FAILED
        entry.error = ("대상 폴더에 승인하지 않은 파일이 있습니다. "
                       "다시 확인한 뒤 덮어쓸지 결정해주세요.")
        errors.append(f"{entry.filename}: {entry.error}")

    for start in range(0, len(prepared), COPY_BATCH):
        batch = [item for item in prepared[start:start + COPY_BATCH]
                 if item["entry"].status != STATUS_FAILED and _backup_replaced(item, errors)]
        for skipped in prepared[start:start + COPY_BATCH]:
            if skipped not in batch:
                step(skipped["entry"])   # 진행률은 항목 수 기준이라 빼먹지 않는다
        pairs = [pair for item in batch for pair in item["pairs"]]
        results = {}
        if pairs:
            dest_dirs = sorted({str(dest.parent) for _src, dest in pairs})
            results = file_ops.copy_files(dest_dirs, pairs)

        for item in batch:
            entry = item["entry"]
            failed = [dest for _src, dest in item["pairs"] if not results.get(str(dest))]
            if failed:
                # 파일 단계에서 실패했으면 메타데이터는 쓰지 않는다. 이번에 새로 만든
                # 파일을 지우고, 덮어쓰려고 치워뒀던 원본은 제자리로 돌려놓는다.
                _undo(item, errors)
                entry.status, entry.error = STATUS_FAILED, f"{len(failed)}개 파일 복사 실패"
                errors.append(f"{entry.filename}: 파일 복사 실패")
            step(entry)


def _entry_to_write(entry, adapter):
    """Plan 항목을 이 Collection에 적을 GameEntry로.

    ADD는 **다른 Collection에서 온 항목**을 이 Collection에 적는 것이다. 원본
    보존값(frontend_raw)에는 두 가지 함정이 있다.

    1) 다른 Frontend의 값이면 **모양부터 다르다**(ES-DE는 {"tag","text"}, Pegasus는
       {"key","value"}). 그대로 넘기면 되살리다 깨진다 - 실제로 ES-DE -> Pegasus
       Convert가 KeyError로 실패했다. Frontend 간 변환에서 frontend_raw가 따라가지
       않는 것은 §50-51의 정의이기도 하다.
    2) 같은 Frontend라도 경로처럼 "그 자리에서만 참인 값"은 걷어내야 한다.
    """
    fields = entry.payload or (entry.source or {}).get("fields") or {}
    source_raw = (entry.source or {}).get("frontend_raw")
    preserved = (adapter.strip_location_raw(source_raw)
                 if adapter.raw_is_mine(source_raw) else {})
    return GameEntry(filename=entry.filename, fields=fields, frontend_raw=preserved)


def _write_metadata(prepared, adapter, errors, media_links):
    """복사가 끝난 항목들의 메타데이터를 **System 단위로 한 번에** 쓴다.

    파일이 자리를 잡은 뒤에 쓴다 - 순서가 반대면 복사 실패 시 gamelist에만 있는 유령
    항목이 남는다.

    실패했을 때 되돌리는 정책은 항목마다 쓰던 때와 같다: **이번에 복사한 파일을
    되돌린다.** 안 그러면 다음 Apply가 "이미 존재하는 ROM"을 만나 충돌로 막히거나
    중복 처리한다. 묶어 쓰기 때문에 그 대상이 그 System의 항목 전체로 늘어날 뿐이고,
    어차피 디스크/권한 문제라면 항목마다 썼어도 전부 실패해 같은 결과가 된다.
    """
    by_system = {}
    for item in prepared:
        if item["entry"].status == STATUS_FAILED:
            continue   # 복사 단계에서 이미 실패했다
        by_system.setdefault(item["entry"].system, []).append(item)

    for system, group in by_system.items():
        layout = group[0]["layout"]
        try:
            adapter.write_index(layout, [_entry_to_write(item["entry"], adapter)
                                         for item in group])
        except Exception as e:  # noqa: BLE001
            for item in group:
                entry = item["entry"]
                recovered = _undo(item, errors)
                entry.status = STATUS_FAILED if recovered else STATUS_PARTIAL
                entry.error = (f"Metadata 기록 실패: {e}" if recovered
                               else f"Metadata 기록 실패 후 복사된 파일 정리에도 실패: {e}")
                errors.append(f"{entry.filename}: {entry.error}")
            continue

        for item in group:
            entry = item["entry"]
            # 이 Frontend가 media 경로를 메타데이터에 적어야 하면(원조 ES) 무엇을
            # 적을지만 계산해 둔다. 실제로 있는 파일만 남긴다 - 복사가 건너뛰어진
            # media까지 적으면 gamelist가 없는 파일을 가리키게 된다.
            if media_links is not None:
                from app.plan.builder import _MediaRef
                refs = [_MediaRef(m) for m in ((entry.source or {}).get("media") or [])]
                links = [(media_type, dest)
                         for media_type, dest
                         in adapter.build_media_links(item["layout"], entry.filename, refs)
                         if Path(dest).exists()]
                if links:
                    media_links.setdefault(entry.system, {})[entry.filename] = links
            entry.status = STATUS_APPLIED


def _apply_adds(adds, collection, adapter, provider, errors, media_links, step):
    """ADD 전체를 세 단계로 실행한다: 준비 -> 묶어 복사 -> System당 메타데이터.

    항목마다 복사하고 항목마다 메타데이터를 쓰던 것을 묶은 것이다. **관찰 가능한
    동작(어떤 항목이 성공/실패하고 무엇이 되돌려지는가)은 그대로 두고 호출 횟수만
    줄인다.**
    """
    prepared = [_prepare_add(entry, collection, adapter, provider) for entry in adds]
    _copy_prepared(prepared, errors, step)
    _write_metadata(prepared, adapter, errors, media_links)
    return prepared

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
    # 고른 부분만 지운다(롬 삭제 / 메타데이터 삭제 / 미디어 삭제를 따로 - 사용자 결정).
    parts = entry.delete_parts
    targets = []
    if row:
        if "rom" in parts and row["present"]:
            targets.append(Path(layout.rom_dir) / row["filename"])
        for m in row["media"]:
            is_video = m["media_type"] == "videos"
            if "video" in parts if is_video else "media" in parts:
                targets.append(Path(m["rel_path"]))

    existing = [p for p in targets if provider.exists(p)]
    if existing:
        results = file_ops.delete_files(existing)
        failed = [p for p in existing if not results.get(str(p))]
        if failed:
            entry.status, entry.error = STATUS_FAILED, f"{len(failed)}개 파일 삭제 실패"
            errors.append(f"{entry.filename}: 파일 삭제 실패")
            return

    remove = getattr(adapter, "remove_entries", None)
    if remove is not None and "metadata" in parts:
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
# TITLE EDIT (Title Prefix/Postfix 일괄 적용, 사용자 결정)
# ----------------------------------------------------------------------
def _merged_fields(entry, row) -> dict:
    """이 항목이 실제로 쓸 필드. 제목 편집은 name 하나만, 기기 편집은 payload 전체다."""
    if entry.op == OP_METADATA_EDIT:
        return dict(entry.payload or row["fields"])
    return {**row["fields"], "name": entry.new_title}


def _frontend_raw(entry, row):
    """Frontend 고유 값(ES-DE의 <favorite> 등). 편집이 직접 바꾼 경우에만 새 값을 쓴다."""
    saved = (entry.source or {}).get("frontendRaw")
    return row["frontend_raw"] if saved is None else saved


def _apply_title_edits(entries, collection, adapter, cache, errors, step):
    """제목·메타데이터 편집을 System 단위로 한 번에 쓴다.

    ADD의 `_write_metadata`와 같은 이유(계약 1) - 항목마다 gamelist.xml을 다시 읽고
    쓰면 O(n^2)다. 수백 개를 한 번에 바꾸는 것이 바로 이 기능의 존재 이유이므로,
    묶어 쓰지 않으면 정작 쓸모 있을 규모에서 느리다.
    """
    by_system: dict[str, list] = {}
    for entry in entries:
        by_system.setdefault(entry.system, []).append(entry)

    for system, group in by_system.items():
        layout = adapter.layout(collection, system)
        rows_by_key, write_entries = {}, []
        for entry in group:
            row = cache.get_row(entry.rom_uid) if entry.rom_uid is not None else None
            if row is None:
                # rom_uid가 stale할 수 있다(_validate_delete와 같은 사정) - 파일명으로 재연결한다.
                row = cache.get_row_by_filename(system, entry.filename)
            if row is None:
                entry.status, entry.error = STATUS_FAILED, "항목이 이미 사라졌습니다."
                errors.append(f"{entry.filename}: {entry.error}")
                step(entry)
                continue
            rows_by_key[entry.key] = row
            merged = _merged_fields(entry, row)
            write_entries.append(GameEntry(filename=row["filename"], fields=merged,
                                           frontend_raw=_frontend_raw(entry, row)))

        if not write_entries:
            continue
        try:
            adapter.write_index(layout, write_entries)
        except Exception as e:  # noqa: BLE001
            for entry in group:
                if entry.key not in rows_by_key:
                    continue
                entry.status, entry.error = STATUS_FAILED, f"Metadata 기록 실패: {e}"
                errors.append(f"{entry.filename}: {entry.error}")
                step(entry)
            continue

        for entry in group:
            row = rows_by_key.get(entry.key)
            if row is None:
                continue
            merged = _merged_fields(entry, row)
            title = (merged.get("name") or "").strip() or Path(row["filename"]).stem
            raw = _frontend_raw(entry, row)
            cache.update_metadata(row["rom_uid"], merged, title=title,
                                  title_norm=normalize_title(title),
                                  frontend_raw=None if entry.op == OP_TITLE_EDIT else raw)
            entry.status = STATUS_APPLIED
            step(entry)


# ----------------------------------------------------------------------
# STORAGE CHANGE
# ----------------------------------------------------------------------
def _stat_size(path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


#: Storage 이동을 몇 걸음으로 나눠 보여줄지. COPY_BATCH와 같은 이유(진행률이 멈춰
#: 보이면 앱이 죽은 것으로 읽힌다)지만, 이동은 **System 하나를 통째로 한 걸음**으로
#: 두고 있었다 - ROM 수십 개를 옮기는 내내 진행률이 멈춰 있다가 끝나는 순간 100%가
#: 됐다(실사용 피드백: "한참 멈춰 있다가 갑자기 완료된다"). 파일 수와 무관하게 대략
#: 이만큼의 걸음으로 나눈다.
MOVE_PROGRESS_STEPS = 20

#: 이보다 작으면 나누지 않는다. 어차피 금방 끝나는데 나누면 robocopy 프로세스를
#: 띄우는 비용만 걸음 수만큼 늘어난다.
MOVE_SPLIT_MIN_BYTES = 64 * 1024 * 1024


def _move_chunks(pairs, sizes):
    """이동을 진행률이 움직일 만큼 나눈다.

    한 번에 다 넘기면 robocopy가 끝날 때까지 아무 소식이 없고, 파일마다 끊으면
    프로세스를 띄우는 비용이 파일 수만큼 붙는다. 그래서 **전체를 스무 걸음쯤**으로
    나눈다 - 파일이 적으면 한 걸음이 한두 개, 수천 개면 한 걸음이 수백 개다.
    """
    if sum(sizes) <= MOVE_SPLIT_MIN_BYTES:
        yield list(pairs)
        return
    size = max(1, -(-len(pairs) // MOVE_PROGRESS_STEPS))
    for start in range(0, len(pairs), size):
        yield list(pairs[start:start + size])


def _apply_storage_change(entry, collection, adapter, cache, registry, provider, errors, step):
    """System의 ROM 파일을 새 Storage로 옮기고 배치 정보를 갱신한다.

    media는 Collection root에 남으므로 건드리지 않는다.

    **이동과 Registry 갱신은 하나의 논리적 트랜잭션이다.** 둘 중 하나만 성공하면
    "파일은 External인데 Registry는 Internal"처럼 앱이 ROM을 찾지 못하는 상태가
    된다. 그래서 어느 단계가 실패하든 이미 옮긴 파일을 되돌린다.

    옮긴 파일 수만큼 `step(label, amount)`로 진행률을 올리고, 그렇게 이미 보고한
    걸음 수를 돌려준다 - 호출부가 남은 몫을 채워 진행률이 항상 끝까지 차게 한다.
    """
    old_layout = adapter.layout(collection, entry.system)

    system_entry = next((s for s in collection.systems if s.system == entry.system), None)
    if system_entry is None:
        entry.status, entry.error = STATUS_FAILED, "System을 찾을 수 없습니다."
        errors.append(f"{entry.system}: System을 찾을 수 없습니다.")
        return 0

    # 옮긴 뒤의 배치를 가정한 layout이 필요하다. Registry를 먼저 바꾸면 실패 시
    # 되돌리기가 번거로우므로 메모리 상의 Collection만 잠시 바꿔서 계산한다.
    #
    # **rom_path도 함께 비워야 한다.** Adapter.layout()은 storage_id보다
    # rom_path를 우선한다(ROM 폴더가 Collection root와 다른 Collection을 위해
    # 필요한 값 - § app/workspace.py의 `rom_elsewhere`). 그런데 storage_id만
    # 바꾸고 예전 rom_path를 그대로 두면, 새 Storage로 옮겼다고 계산한 new_layout이
    # 여전히 **예전 경로**를 가리켜 old_layout과 같아져 버린다 - 그러면 "목적지에
    # 이미 파일이 있다"는 충돌로만 보이고 실제로는 아무 데도 못 간다(실사용
    # 피드백: External Storage로 드래그해도 Apply가 항상 실패했다). Storage
    # 이동은 "이 System은 이제 이 Storage를 따른다"는 뜻이므로, rom_path가
    # 있었더라도 이동 후에는 새 Storage의 기본 경로로 재계산되어야 한다.
    original_storage = system_entry.storage_id
    original_rom_path = system_entry.rom_path
    system_entry.storage_id = entry.storage_to
    system_entry.rom_path = None
    new_layout = adapter.layout(collection, entry.system)
    system_entry.storage_id = original_storage
    system_entry.rom_path = original_rom_path

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
        return 0

    moved, reported = [], 0
    if pairs:
        sizes = [_stat_size(src) for src, _ in pairs]
        for chunk in _move_chunks(pairs, sizes):
            # 기본 timeout(300초)은 같은 볼륨 안의 rename을 가정한 값이다. Storage
            # 이동은 흔히 **다른 볼륨**(외장 SD/USB)으로 실제 바이트를 복사하므로,
            # ROM 몇 개만 커도(PS2/PS3 이미지는 GB 단위) 5분을 넘기기 쉽다 - 그러면
            # robocopy가 강제 종료되어 파일이 다 안 옮겨진 채 "이동 실패"만 반복해서
            # 쌓였다(실사용 피드백). 옮길 용량에 비례해 넉넉히 늘린다 - 못해도
            # 20MB/s(느린 USB/SD 기준)는 나온다고 보고, 거기에 여유를 더한다.
            chunk_bytes = sum(_stat_size(src) for src, _ in chunk)
            timeout_sec = max(300.0, chunk_bytes / (20 * 1024 * 1024) + 60.0)
            results = file_ops.move_files(chunk, timeout_sec=timeout_sec)
            done_here = [(src, dest) for src, dest in chunk if results.get(str(dest))]
            moved.extend(done_here)
            reported += len(chunk)
            step(f"이동 중: {entry.system}", len(chunk))
            if len(done_here) != len(chunk):
                # 한 묶음이라도 실패하면 남은 묶음은 시작하지 않는다 - 어차피 아래에서
                # 전부 되돌리므로, 옮기다 만 것을 더 늘릴 이유가 없다.
                break
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
            return reported

    try:
        # rom_path를 None으로 같이 지운다 - 파일이 실제로 new_layout.rom_dir로
        # 옮겨졌으니, 다음에 다시 읽을 때도 Adapter가 새 Storage 기준으로 같은
        # 경로를 계산하게 한다. 지우지 않으면 옛 rom_path가 그대로 남아 있다가
        # 다음 Storage 이동에서 또 같은 문제가 반복된다.
        registry.move_system(collection.id, entry.system, entry.storage_to, rom_path=None)
    except Exception as e:  # noqa: BLE001
        # 파일은 옮겨졌는데 Registry가 못 따라온 경우다. 그대로 두면 앱이 ROM을
        # 찾지 못하므로 파일을 원래 자리로 되돌린다.
        restored = _restore_moved(moved, errors, entry)
        entry.status = STATUS_FAILED if restored else STATUS_PARTIAL
        entry.error = (f"배치 갱신 실패로 이동을 되돌렸습니다: {e}" if restored else
                       f"배치 갱신 실패({e}) 후 되돌리기도 실패 - 파일 위치와 설정이 "
                       "어긋나 있습니다")
        errors.append(f"{entry.system}: {entry.error}")
        return reported

    # 메모리 상의 Collection도 갱신해야 뒤이은 항목들이 새 배치를 본다.
    system_entry.storage_id = entry.storage_to
    system_entry.rom_path = None
    entry.status = STATUS_APPLIED
    return reported


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
