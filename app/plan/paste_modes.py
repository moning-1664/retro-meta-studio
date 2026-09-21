"""
app/plan/paste_modes.py
========================
붙여넣기 모드 - **같은 Ctrl+V가 목적에 따라 다르게 동작**하게 한다(사용자 결정).

| 모드 | 이미 있는 항목에 대해 |
|---|---|
| `patch` (기본) | **없는 것만 채운다.** 대상에 있는 메타데이터 값과 미디어는 그대로 두고, 비어 있는 값과 없는 미디어만 원본에서 가져온다. ROM이 이미 있으면 복사하지 않는다. |
| `overwrite` | **원하는 값으로 덮어쓴다.** 원본의 (비어 있지 않은) 메타데이터와 미디어가 대상 것을 이긴다. 원본이 비어 있는 값으로 대상 값을 지우지는 않는다. |
| `replace` | **원본을 무시한다.** 이미 있는 항목은 아무것도 채우지 않고 건드리지 않는다. 대상에 없는 항목만 새로 붙인다. |

대상에 **없는** 항목은 어느 모드에서든 원본 그대로 새로 붙는다.

모드가 바뀌어도 "Plan은 바이트가 움직이는 작업만"(D1) 규칙은 그대로다. 여기서 하는 일은
Plan에 올리기 **전에** 항목에서 필요 없는 부분을 걷어 내는 것뿐이다. 걷어 내고 나면 바뀌는 것이
아무것도 없는 항목은 Plan에 올리지 않고 **이유와 함께 알린다**(사용자 결정 - Plan에는 올라갔는데
Apply해 보면 아무 일도 없던 것이 아니라, 올릴 때 이유를 설명하고 올리지 않는다).
"""

from __future__ import annotations

from pathlib import Path

MODE_PATCH = "patch"
MODE_OVERWRITE = "overwrite"
MODE_REPLACE = "replace"
MODES = (MODE_PATCH, MODE_OVERWRITE, MODE_REPLACE)
DEFAULT_MODE = MODE_PATCH


def normalize_mode(mode) -> str:
    return mode if mode in MODES else DEFAULT_MODE


def _filled(value) -> bool:
    return value is not None and str(value).strip() != ""


def _merge_fields(existing, incoming, mode) -> dict:
    """대상 값과 원본 값을 모드에 맞게 합친다."""
    existing, incoming = dict(existing or {}), dict(incoming or {})
    merged = dict(existing)
    for key, value in incoming.items():
        if not _filled(value):
            continue                       # 비어 있는 원본 값은 어느 모드에서도 대상 값을 지우지 않는다
        if mode == MODE_OVERWRITE or not _filled(existing.get(key)):
            merged[key] = value
    return merged


def prepare(items, cache, mode) -> tuple[list, list]:
    """모드를 적용한다. 반환: (Plan에 올릴 항목들, 올리지 않은 항목들과 이유)"""
    mode = normalize_mode(mode)
    prepared, skipped = [], []
    for item in items:
        existing = cache.get_row_by_filename(item["system"], item["filename"])
        if existing is None:
            prepared.append(item)          # 대상에 없다 - 모드와 무관하게 원본 그대로 붙는다
            continue

        if mode == MODE_REPLACE:
            # **존재의 기준은 ROM이다**(Compare와 같다). ROM이 있는 항목은 원본을 통째로 무시하고, gamelist에
            # 항목만 있고 ROM이 없는 항목에는 ROM만 채운다(메타데이터는 대상 것 그대로).
            if existing["present"] or not item.get("rom"):
                skipped.append({"filename": item["filename"],
                                "reason": "Replace 모드 - 이미 있는 항목이라 원본을 무시했습니다"})
                continue
            prepared.append({**item, "fields": existing.get("fields") or {}, "media": [],
                             "frontend_raw": existing.get("frontend_raw") or item.get("frontend_raw") or {}})
            continue

        have_media = {m["media_type"] for m in (existing.get("media") or [])}
        rom = item.get("rom")
        media = list(item.get("media") or [])
        if mode == MODE_PATCH:
            media = [m for m in media if (m.get("type") or m.get("media_type")) not in have_media]
            if existing["present"]:
                rom = None                 # 이미 있는 ROM은 다시 복사하지 않는다
        else:
            # 덮어쓰기라도 **같은 파일**(종류와 크기가 같다)을 다시 복사할 이유는 없다 - 바뀌는 것이
            # 없는 항목이 Plan에 올라가는 것을 막는다.
            have = {m["media_type"]: m for m in (existing.get("media") or [])}
            media = [m for m in media if not _same_media(m, have.get(m.get("type") or m.get("media_type")))]
            if rom and existing["present"] and _same_file(rom, existing):
                rom = None
        fields = _merge_fields(existing.get("fields"), item.get("fields"), mode)
        # ES-DE의 favorite처럼 **대상 Frontend가 관리하는 값**은 대상의 것을 지킨다.
        raw = existing.get("frontend_raw") or item.get("frontend_raw") or {}

        fields_changed = fields != (existing.get("fields") or {})
        if not (fields_changed or media or rom):
            skipped.append({"filename": item["filename"],
                            "reason": _nothing_to_change(mode, item)})
            continue
        prepared.append({**item, "fields": fields, "frontend_raw": raw,
                         "rom": rom, "media": media})
    return prepared, skipped


def _same_media(media, existing) -> bool:
    """원본 미디어가 대상의 그것과 같은 파일인가.

    **크기만 본다**(사용자 결정, 번복 - `app/plan/builder.classify_destination()`의
    `size_only`와 같은 이유). 예전엔 크기+수정시각을 요구했는데, Collection/기기를
    옮기면(특히 MTP) mtime이 원본 그대로 보존되지 않는 경우가 흔해서 똑같은 그림도
    매번 "다른 파일"로 보여 붙여넣을 때마다 Conflict가 떴다. ROM은 여전히 크기+시각을
    같이 보는 `_same_file()`을 쓴다 - 같은 크기의 다른 리전/리비전 덤프가 실제로 있는,
    더 위험한 자료이기 때문이다."""
    if existing is None:
        return False
    try:
        stat = Path(media["path"]).stat()
    except (OSError, KeyError, TypeError):
        return False
    return stat.st_size == int(existing.get("size") or 0)


def _same_file(rom, existing) -> bool:
    """원본 ROM이 대상의 그 파일과 **같은 파일**인가. Plan의 IDENTICAL 판정과 같은 기준(크기+수정시각)이다 -
    크기만 같고 시각이 다르면 같은 파일이라고 확신할 수 없으므로 충돌 확인으로 넘어간다."""
    try:
        stat = Path(rom["path"]).stat()
    except (OSError, KeyError, TypeError):
        return False
    return (stat.st_size == int(existing.get("size") or 0)
            and stat.st_mtime_ns == int(existing.get("mtime_ns") or 0))


def _nothing_to_change(mode, item) -> str:
    if mode == MODE_PATCH:
        return "Patch 모드 - 대상이 이미 모두 가지고 있어 채울 것이 없습니다"
    return "원본과 대상이 같아 바뀌는 것이 없습니다"
