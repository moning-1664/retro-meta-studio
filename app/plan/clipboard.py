"""
app/plan/clipboard.py
======================
인스턴스 간 복사/붙여넣기(결정 D5, 스펙 §9.1).

앱을 두 개 띄워 놓고 A에서 복사해 B에 붙여넣으면 **파일과 메타데이터가 함께**
넘어가야 한다.

**설계 문서와 달라진 점.** 원래는 Windows 클립보드에 전용 포맷을 등록하려 했지만,
registry.db를 채널로 쓰는 쪽으로 바꿨다. 이유는 셋이다.
- 두 인스턴스가 이미 같은 registry.db를 공유한다. 별도 IPC도, ctypes로 Win32
  클립보드를 다루는 취약한 코드도 필요 없다.
- 사용자의 실제 시스템 클립보드를 덮어쓰지 않는다. 앱에서 게임을 복사해둔 것이
  다른 앱에서 텍스트를 복사했다고 날아가지 않는다.
- 붙여넣기 동작이 소스 인스턴스의 생존에 의존하지 않는다는 성질은 그대로다.

메타데이터는 payload에 통째로 싣는다. 그래서 복사한 뒤 A를 닫아도 붙여넣기가
동작한다. 파일은 절대경로로 참조하므로 원본 파일만 남아 있으면 된다.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from adapters import get_adapter

CLIPBOARD_KEY = "clipboard"
#: 핸드오프 파일 보관 기간. 앱 시작 시 이보다 오래된 것은 지운다.
HANDOFF_TTL_SECONDS = 7 * 24 * 3600


def build_items(collection, cache, rom_uids) -> tuple[list, int]:
    """`plan_add()`가 받는 모양의 항목을 만든다. 반환: (items, 총 바이트)

    붙여넣기(핸드오프 파일)와 Compare의 한쪽 -> 다른쪽 복사가 **같은 함수를 쓴다** - 둘이 각자
    만들면 한쪽만 media를 빠뜨리는 식으로 조용히 갈라진다.
    """
    adapter = get_adapter(collection.frontend)
    items, total_bytes = [], 0

    for rom_uid in rom_uids:
        row = cache.get_row(int(rom_uid))
        if row is None:
            continue
        layout = adapter.layout(collection, row["system"])
        rom = None
        if row["present"]:
            rom = {"path": str(Path(layout.rom_dir) / row["filename"]), "size": int(row["size"] or 0)}
            total_bytes += rom["size"]
        media = []
        for item in row["media"]:
            media.append({"type": item["media_type"], "path": item["rel_path"],
                          "size": int(item["size"] or 0)})
            total_bytes += int(item["size"] or 0)
        items.append({
            "system": row["system"], "filename": row["filename"], "rom": rom, "media": media,
            "fields": row["fields"], "frontend_raw": row["frontend_raw"],
        })
    return items, total_bytes


def write_items(registry, items, clipboard_dir, *, source_collection_id, source_name,
                total_bytes=None) -> dict:
    """Write already resolved items to the shared handoff clipboard."""
    if total_bytes is None:
        total_bytes = sum(
            int((item.get("rom") or {}).get("size") or 0)
            + sum(int(media.get("size") or 0) for media in item.get("media") or [])
            for item in items)
    clipboard_dir = Path(clipboard_dir)
    clipboard_dir.mkdir(parents=True, exist_ok=True)
    handoff = clipboard_dir / f"{uuid.uuid4().hex}.json"
    handoff.write_text(json.dumps({
        "source_collection_id": source_collection_id,
        "instance_id": registry.instance_id,
        "items": items,
    }, ensure_ascii=False), encoding="utf-8")

    descriptor = {"path": str(handoff), "count": len(items), "bytes": total_bytes,
                  "sourceCollectionId": source_collection_id, "sourceName": source_name,
                  "instanceId": registry.instance_id, "at": time.time()}
    registry.set_setting(CLIPBOARD_KEY, descriptor)
    return descriptor


def copy_selection(registry, collection, cache, rom_uids, clipboard_dir) -> dict:
    """선택 항목을 핸드오프 파일로 내보내고 registry에 위치를 기록한다.

    수천 개를 복사해도 registry에는 짧은 요약만 들어간다 - 실제 payload는 파일에 있다.
    """
    items, total_bytes = build_items(collection, cache, rom_uids)
    return write_items(registry, items, clipboard_dir,
                       source_collection_id=collection.id, source_name=collection.name,
                       total_bytes=total_bytes)


def peek(registry) -> dict | None:
    """지금 클립보드에 무엇이 있는지 요약만 본다(붙여넣기 버튼 상태용)."""
    descriptor = registry.get_setting(CLIPBOARD_KEY)
    if not descriptor:
        return None
    if not Path(descriptor.get("path", "")).exists():
        return None
    return descriptor


def read_items(registry) -> tuple[dict, list]:
    """붙여넣기용 payload를 읽는다. 반환: (descriptor, items)"""
    descriptor = peek(registry)
    if descriptor is None:
        return {}, []
    try:
        payload = json.loads(Path(descriptor["path"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, []
    return descriptor, payload.get("items") or []


def clear(registry):
    descriptor = registry.get_setting(CLIPBOARD_KEY)
    if descriptor:
        try:
            Path(descriptor["path"]).unlink(missing_ok=True)
        except OSError:
            pass
    registry.set_setting(CLIPBOARD_KEY, None)


def prune(clipboard_dir, ttl_seconds=HANDOFF_TTL_SECONDS):
    """오래된 핸드오프 파일 정리. 앱 시작 시 한 번 부른다."""
    directory = Path(clipboard_dir)
    if not directory.exists():
        return 0
    cutoff = time.time() - ttl_seconds
    removed = 0
    for path in directory.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
