"""
app/convert/service.py
=======================
Convert — 한 Collection의 내용을 다른 Frontend 표현으로 옮긴다 (스펙 §53).

**원본 Collection은 보존한다.** Convert는 source를 읽어 target Collection에 같은 게임을
만드는 일이고, source의 파일이나 메타데이터는 건드리지 않는다.

## 새로 만드는 것이 거의 없다

변환 자체는 이미 있는 것들의 조합이다.

```
source cache의 row  ──(공통 모델)──>  builder.plan_add  ──> Plan ──> Apply
                                                                      └─ target Adapter가
                                                                         자기 포맷으로 쓴다
```

공통 모델을 거치는 순간 "어느 Frontend에서 왔는지"는 사라지고, 쓸 때는 target Adapter가
자기 포맷을 책임진다. 그래서 Convert에 필요한 새 코드는 **미리보기**뿐이다.

## 미리보기가 있어야 하는 이유

Frontend 간 변환은 **반드시 무언가를 잃는다**(§50-51). Pegasus에는 region 키가 없고,
ES-DE의 `<playcount>`는 Pegasus 블록에 적을 자리가 없다. 사용자가 그걸 실행 전에 알아야
"이 변환을 해도 되는가"를 판단할 수 있다.

- `unsupportedFields` — target 포맷에 **자리가 없는 공통 필드**의 실제 값 개수.
  값이 비어 있으면 세지 않는다 - 잃을 것이 없기 때문이다.
- `frontendSpecific` — source의 `frontend_raw` 항목 수. 다른 Frontend로는 건너가지
  못한다(같은 Frontend 제자리 왕복에서만 보존된다).
"""

from __future__ import annotations

from pathlib import Path

from adapters import get_adapter
from adapters.base import COMMON_FIELDS


def _items_from(collection, cache, adapter, rows) -> list[dict]:
    """cache row -> `builder.plan_add`가 기대하는 형태.

    `clipboard.copy_selection()`이 만드는 것과 같은 모양이다 - Convert도 결국 "다른
    Collection에서 온 항목을 추가"하는 일이라, 붙여넣기와 같은 경로를 타야 한다.
    """
    items = []
    for row in rows:
        layout = adapter.layout(collection, row["system"])
        rom = None
        if row.get("present"):
            rom = {"path": str(Path(layout.rom_dir) / row["filename"]),
                   "size": int(row.get("size") or 0)}
        media = [{"type": m["media_type"], "path": m["rel_path"], "size": int(m.get("size") or 0)}
                 for m in (row.get("media") or [])]
        items.append({
            "system": row["system"], "filename": row["filename"], "rom": rom, "media": media,
            "fields": row.get("fields") or {}, "frontend_raw": row.get("frontend_raw") or {},
        })
    return items


def _source_rows(cache, systems=None) -> list[dict]:
    rows = []
    for summary in cache.query_rows(systems=systems or None):
        row = cache.get_row(summary["rom_uid"])
        if row is not None:
            rows.append(row)
    return rows


def preview(source_collection, source_cache, target_collection, *, systems=None) -> dict:
    """이 변환에서 무엇이 넘어가고 무엇이 사라지는지 미리 센다. 아무것도 바꾸지 않는다."""
    source_adapter = get_adapter(source_collection.frontend)
    target_adapter = get_adapter(target_collection.frontend)
    rows = _source_rows(source_cache, systems)

    supported = set(target_adapter.supported_fields)
    dropped_fields = [f for f in COMMON_FIELDS if f not in supported]
    target_media = set(target_adapter.media_types)

    games = len(rows)
    with_metadata = 0
    media_count = 0
    dropped_media = 0
    unsupported_values = 0
    frontend_specific = 0
    dropped_field_names: dict[str, int] = {}

    for row in rows:
        fields = row.get("fields") or {}
        if any(str(v or "").strip() for v in fields.values()):
            with_metadata += 1
        for name in dropped_fields:
            # 값이 비어 있으면 잃을 것이 없다 - 겁주는 숫자를 만들지 않는다.
            if str(fields.get(name) or "").strip():
                unsupported_values += 1
                dropped_field_names[name] = dropped_field_names.get(name, 0) + 1
        for media in row.get("media") or []:
            if media["media_type"] in target_media:
                media_count += 1
            else:
                dropped_media += 1
        raw = row.get("frontend_raw") or {}
        frontend_specific += len(raw.get("extra") or [])

    return {
        "sourceId": source_collection.id, "sourceName": source_collection.name,
        "sourceFrontend": source_adapter.display_name,
        "targetId": target_collection.id, "targetName": target_collection.name,
        "targetFrontend": target_adapter.display_name,
        "games": games,
        "metadata": with_metadata,
        "media": media_count,
        "droppedMedia": dropped_media,
        "unsupportedFields": unsupported_values,
        # 어느 필드가 왜 버려지는지 이름까지 준다 - 숫자만 보여주면 사용자가
        # 무엇을 잃는지 알 수 없다.
        "unsupportedFieldNames": sorted(dropped_field_names),
        "frontendSpecific": frontend_specific,
        "systems": sorted({row["system"] for row in rows}),
    }


def plan_convert(plan, source_collection, source_cache, target_collection, provider,
                 *, systems=None) -> dict:
    """변환 결과를 target Collection의 Plan에 올린다. **파일은 아직 움직이지 않는다.**

    붙여넣기와 같은 `builder.plan_add`를 쓴다 - 목적지에 이미 있는 항목의 충돌 판정,
    용량 계산, 원본이 사라진 항목 건너뛰기가 전부 그쪽에 이미 있다.
    """
    from app.plan import builder

    source_adapter = get_adapter(source_collection.frontend)
    rows = _source_rows(source_cache, systems)
    items = _items_from(source_collection, source_cache, source_adapter, rows)
    return builder.plan_add(plan, target_collection, provider, items)
