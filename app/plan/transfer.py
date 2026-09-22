"""
app/plan/transfer.py
=====================
**게임 단위 전송 계층** - Copy/Paste와 Compare 복사가 함께 쓴다.

세 층을 섞지 않는다.

1. **같은 게임인가** - 붙여넣기는 (System, 파일명)으로, Compare는 이미 맺어 둔 짝으로 안다.
   Compare가 짝을 알려 주면(`existing`) 여기서 파일 단위로 다시 판정하지 않는다.
2. **무엇을 옮길 것인가(의도)** - 구성요소(ROM / Metadata / Media)마다 정한다. 이 파일이 하는 일이다.
3. **파일이 안전한가** - `builder.plan_add()`의 identical/conflict 판정. **실제로 바뀔 구성요소에만**
   일어난다. 옮기지 않기로 한 것은 충돌 검사 대상조차 아니다.

| 모드 | Metadata | Media |
|---|---|---|
| `patch` (기본, 보완) | 대상의 빈 값만 채운다 | 대상에 없는 종류만 가져온다 |
| `overwrite` (덮어쓰기) | 원본의 비어 있지 않은 값이 이긴다(빈 값은 대상을 지우지 않는다) | 원본이 이긴다(같은 파일은 건너뜀) |
| `replace` (완전 교체) | 원본의 값으로 게임의 Metadata를 다시 만든다(대상에만 있던 값도 원본에 없으면 사라진다) | 원본이 이긴다. 대상에만 있는 미디어는 **지우지 않는다**(파일 삭제는 Delete의 일) |

**ROM은 모드와 무관하다.** 대상에 ROM이 있으면 그대로 둔다. `replace_rom=True`(사용자가 명시적으로
ROM 교체를 골랐을 때)에만 원본 ROM을 올리고, 그때 비로소 identical/conflict 검사가 ROM에 걸린다.
대상에 ROM이 없으면(gamelist 항목만 있거나 항목이 없음) 원본 ROM이 간다.

대상에 **없는** 게임은 어느 모드에서든 원본 그대로 새로 붙는다.

"Plan은 바이트가 움직이는 작업만"(D1) 규칙은 그대로다. 여기서는 Plan에 올리기 **전에** 필요 없는
부분을 걷어 낼 뿐이고, 걷어 내고 남은 것이 없으면 이유와 함께 알린다.
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
    if mode == MODE_REPLACE:
        # 완전 교체 - 게임의 Metadata를 원본 값으로 다시 만든다(비어 있는 원본 값은 값이 아니다).
        return {k: v for k, v in incoming.items() if _filled(v)}
    merged = dict(existing)
    for key, value in incoming.items():
        if not _filled(value):
            continue                       # 비어 있는 원본 값은 보완/덮어쓰기에서 대상 값을 지우지 않는다
        if mode == MODE_OVERWRITE or not _filled(existing.get(key)):
            merged[key] = value
    return merged


def _media_type(m) -> str:
    return m.get("type") or m.get("media_type")


def decide(item, existing, mode, *, replace_rom=False) -> tuple[dict | None, str | None]:
    """게임 하나의 구성요소별 전송 의도를 정한다.

    `existing`: 대상의 같은 게임 행(없으면 None). 반환: (`plan_add`에 넘길 항목 또는 None, 건너뛴 이유).
    """
    mode = normalize_mode(mode)
    if existing is None:
        return item, None                  # 대상에 없다 - 모드와 무관하게 원본 그대로 붙는다

    # ROM: 있으면 지킨다. 교체는 명시적으로 고른 때만이고, 그때만 파일 검사(identical/conflict)가 걸린다.
    rom = item.get("rom")
    if rom and existing["present"]:
        if not replace_rom or _same_file(rom, existing):
            rom = None

    # Media
    have = {m["media_type"]: m for m in (existing.get("media") or [])}
    media = list(item.get("media") or [])
    if mode == MODE_PATCH:
        media = [m for m in media if _media_type(m) not in have]
    else:
        media = [m for m in media if not _same_media(m, have.get(_media_type(m)))]

    # Metadata. ES-DE의 favorite처럼 대상 Frontend가 관리하는 값(frontend_raw)은 대상의 것을 지킨다.
    fields = _merge_fields(existing.get("fields"), item.get("fields"), mode)
    raw = existing.get("frontend_raw") or item.get("frontend_raw") or {}

    if not (fields != (existing.get("fields") or {}) or media or rom):
        return None, _nothing_to_change(mode, item)
    return {**item, "fields": fields, "frontend_raw": raw, "rom": rom, "media": media}, None


def item_key(item) -> str:
    """전송 항목 하나를 가리키는 열쇠. Compare 행 열쇠와 같은 모양이라 화면에서 그대로 쓸 수 있다."""
    return f"{item['system']}|{item['filename']}"


def prepare(items, cache, mode, *, replace_rom=False, targets=None) -> tuple[list, list]:
    """붙여넣기 - 어느 대상 행에 쓸지 정하고 구성요소별 의도를 계산한다.

    같은 게임인지 아는 방법은 둘이다.

    1. **사용자가 지목**(`targets`: 항목 열쇠 -> 대상 행). 자동 판단보다 우선한다 - 자동 Match가
       못 붙였거나 다른 게임이라고 본 짝이라도, 사용자가 직접 고른 것이 더 정확한 정보다.
       Match 결과를 바꾸지는 않는다. 이번 작업에 한해 "이 둘을 이어라"라고 승인한 것뿐이다.
    2. 지목이 없으면 같은 (System, 파일명)을 같은 게임으로 본다.
    """
    targets = targets or {}
    prepared, skipped = [], []
    for item in items:
        chosen = targets.get(item_key(item))
        if chosen is not None:
            existing = chosen
            # 지목한 대상의 이름으로 쓴다 - 그래야 gamelist의 그 항목에 들어가고, 미디어도 그
            # 파일명으로 놓여 프론트엔드가 찾는다.
            item = {**item, "system": chosen["system"], "filename": chosen["filename"]}
            if not replace_rom:
                # 이름이 다른 대상이다. ROM을 대상 이름으로 복사하면 확장자까지 바뀌어
                # 에뮬레이터가 못 읽는 파일이 된다 - ROM 교체를 명시한 때만 손댄다.
                item = {**item, "rom": None}
        else:
            existing = cache.get_row_by_filename(item["system"], item["filename"])
        out, reason = decide(item, existing, mode, replace_rom=replace_rom)
        if out is None:
            skipped.append({"filename": item["filename"], "reason": reason})
        else:
            prepared.append(out)
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
        return "보완 모드 - 대상이 이미 모두 가지고 있어 채울 것이 없습니다"
    return "원본과 대상이 같아 바뀌는 것이 없습니다"
