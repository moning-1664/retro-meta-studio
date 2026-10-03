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
| `patch` (보완) | 대상의 빈 값만 채운다 | 대상에 없는 종류만 가져온다 |
| `overwrite` (기본, 덮어쓰기) | 원본의 비어 있지 않은 값이 이긴다(빈 값은 대상을 지우지 않는다) | 원본이 이긴다(같은 파일은 건너뜀) |
| `replace` (완전 교체) | 원본의 값으로 게임의 Metadata를 다시 만든다(대상에만 있던 값도 원본에 없으면 사라진다) | 원본이 이긴다. 대상에만 있는 미디어는 **지우지 않는다**(파일 삭제는 Delete의 일) |

ROM 복사가 켜져 있으면 없는 ROM을 추가한다. 로컬 즉시 붙여넣기는 같은 파일명의
ROM 교체를 충돌 확인 후 실행하고 백업을 보존한다. 채우기와 명시적 다른 행 대상은
기존 ROM을 유지한다. 기존 Plan/Archive 호출은 교체를 허용하지 않는다.

대상 항목의 파일명이 원본과 다르면(지역 태그가 다르거나 사람이 직접 지목한 경우) ROM은
옮기지 않는다. `Final Fantasy 7.zip`의 바이트를 `ff7.rom`이라는 이름으로 놓으면 확장자가
바뀌어 에뮬레이터가 못 읽고, `[EU]` 덤프를 `[KR]` 이름으로 놓는 것도 틀린 파일이 된다.

대상에 **없는** 게임은 어느 모드에서든 원본 그대로 새로 붙는다.

"Plan은 바이트가 움직이는 작업만"(D1) 규칙은 그대로다. 여기서는 Plan에 올리기 **전에** 필요 없는
부분을 걷어 낼 뿐이고, 걷어 내고 남은 것이 없으면 이유와 함께 알린다.
"""

from __future__ import annotations

import os
from pathlib import Path

from app import gameid

MODE_PATCH = "patch"
MODE_OVERWRITE = "overwrite"
MODE_REPLACE = "replace"
MODES = (MODE_PATCH, MODE_OVERWRITE, MODE_REPLACE)
DEFAULT_MODE = MODE_OVERWRITE


def normalize_mode(mode) -> str:
    return mode if mode in MODES else DEFAULT_MODE


def _filled(value) -> bool:
    return value is not None and str(value).strip() != ""


def fields_conflict(existing, incoming, mode=DEFAULT_MODE):
    if mode == MODE_PATCH:
        return False
    existing, incoming = existing or {}, incoming or {}
    return any(_filled(value) and (
        (_filled(incoming.get(key)) and incoming[key] != value)
        or (mode == MODE_REPLACE and not _filled(incoming.get(key)))
    ) for key, value in existing.items())


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


def decide(item, existing, mode, *, allow_rom_replace=False,
           force_media=False) -> tuple[dict | None, str | None]:
    """게임 하나의 구성요소별 전송 의도를 정한다.

    `existing`: 대상의 같은 게임 행(없으면 None). 반환: (`plan_add`에 넘길 항목 또는 None, 건너뛴 이유).
    """
    mode = normalize_mode(mode)
    if existing is None:
        return item, None                  # 대상에 없다 - 모드와 무관하게 원본 그대로 붙는다

    # ROM 교체는 호출자가 안전한 실행 경로를 제공한 경우에만 허용한다.
    # 이름이 다른 명시적 대상과 채우기는 기존 ROM을 보존한다.
    rom = item.get("rom")
    same_name = (existing["system"], str(existing["filename"]).casefold()) == (
        item["system"], str(item["filename"]).casefold())
    if rom and (not same_name or (existing["present"] and
                (not allow_rom_replace or mode == MODE_PATCH))):
        rom = None

    # Media
    have = {m["media_type"]: m for m in (existing.get("media") or [])}
    media = [m for m in (item.get("media") or [])
             if not _same_path(m.get("path"),
                               (have.get(_media_type(m)) or {}).get("rel_path"))]
    if mode == MODE_PATCH:
        media = [m for m in media if _media_type(m) not in have]
    elif not force_media:
        media = [m for m in media if not _same_media(m, have.get(_media_type(m)))]

    # Metadata. ES-DE의 favorite처럼 대상 Frontend가 관리하는 값(frontend_raw)은 대상의 것을 지킨다.
    fields = _merge_fields(existing.get("fields"), item.get("fields"), mode)
    raw = existing.get("frontend_raw") or item.get("frontend_raw") or {}

    if not (fields != (existing.get("fields") or {}) or media or rom):
        return None, _nothing_to_change(mode, item)
    return {**item, "fields": fields, "frontend_raw": raw, "rom": rom,
            "media": media, "previewMedia": item.get("previewMedia", item.get("media") or []), "forceMedia": force_media}, None


def item_key(item) -> str:
    """전송 항목 하나를 가리키는 열쇠. Compare 행 열쇠와 같은 모양이라 화면에서 그대로 쓸 수 있다."""
    return f"{item['system']}|{item['filename']}"


class TargetIndex:
    """붙여넣기의 대상 후보를 한 번만 읽어 두는 색인.

    **"같은 게임인가"는 `app/gameid.py` 한 곳이 정한다.** 예전에는 붙여넣기만
    `get_row_by_filename()`으로 파일명이 글자 하나까지 같을 때만 대상으로 인정해서,
    Compare가 한 줄로 짝지어 보여 준 항목을 정작 붙여넣기는 찾지 못했다(실사용 버그 -
    "Compare에선 대부분 다르다고 나오는데 붙여넣으면 8개만 된다". 그 8개가 파일명까지
    똑같은 것의 개수였다).

    후보가 여럿이면 `gameid.pick_target()`이 정해진 순서(파일명 -> 디스크 번호 -> 지역 ->
    알파벳)로 하나를 고른다 - 임의로 고르지 않고 **같은 입력에 늘 같은 답**을 낸다.
    """

    def __init__(self, cache, systems):
        # 색인에는 **가벼운 요약(all_entries)**만 담고, 실제로 맞은 행은 get_row()로 다시
        # 읽는다 - decide()는 media/frontend_raw까지 있는 온전한 행을 봐야 한다
        # (all_entries는 Compare용이라 media_types/media_sizes만 싣는다).
        self._cache = cache
        self._by_name = {}
        self._buckets = {}
        for row in cache.all_entries(systems=sorted({s for s in systems if s})):
            self._by_name[(row["system"], str(row["filename"]).casefold())] = row["rom_uid"]
            key = gameid.key_of(row["filename"])
            entry = (row["filename"], row["rom_uid"], key)
            for bucket in key.buckets:
                self._buckets.setdefault((row["system"], bucket), []).append(entry)

    def find(self, item, *, accept_similar=False, exact_only=False) -> tuple[dict | None, str | None]:
        """(대상 행, 어떻게 찾았는지). 못 찾으면 (None, None).

        "같은 게임인가"는 `app/gameid.py` **한 곳**이 정한다 - Compare/Archive/붙여넣기가
        같은 답을 내야 한다. 후보가 여럿이면 `gameid.pick_target()`이 정해진 순서
        (파일명 -> 디스크 번호 -> 지역 -> 알파벳)로 고른다. 예전처럼 "모호하니 안 붙인다"로
        끝내지 않는다 - 사용자 결정에 따라 **아무거나 하나는 고르되 늘 같은 답**을 낸다.

        `accept_similar`는 남겨 둔다(호출부 호환). 지금 규칙에서는 같은 게임이면 모드와
        무관하게 대상이 되므로 결과에 영향이 없다.
        """
        exact = self._by_name.get((item["system"], str(item["filename"]).casefold()))
        if exact is not None:
            return self._cache.get_row(exact), "exact"
        if exact_only:
            return None, None

        mine = gameid.key_of(item["filename"])
        seen, candidates = set(), []
        for bucket in mine.buckets:
            for filename, rom_uid, key in self._buckets.get((item["system"], bucket), ()):
                if rom_uid in seen or not gameid.same_game(mine, key):
                    continue
                seen.add(rom_uid)
                candidates.append((filename, rom_uid))
        if not candidates:
            return None, None
        rom_uid, how = gameid.pick_target(item["filename"], candidates)
        return self._cache.get_row(rom_uid), how

    def matches(self, item) -> list:
        """이 항목과 **같은 게임인 대상 전부**(rom_uid 목록). 언어 변종처럼 여러 대상에
        같은 메타데이터를 써야 할 때 쓴다."""
        mine = gameid.key_of(item["filename"])
        seen, out = set(), []
        for bucket in mine.buckets:
            for _filename, rom_uid, key in self._buckets.get((item["system"], bucket), ()):
                if rom_uid not in seen and gameid.same_game(mine, key):
                    seen.add(rom_uid)
                    out.append(rom_uid)
        return out


def prepare(items, cache, mode, *, targets=None, index=None, exact_only=False,
            allow_rom_replace=False, force_media=False) -> tuple[list, list]:
    """붙여넣기 - 어느 대상 행에 쓸지 정하고 구성요소별 의도를 계산한다.

    같은 게임인지 아는 방법은 둘이다.

    1. **사용자가 지목**(`targets`: 항목 열쇠 -> 대상 행). 자동 판단보다 우선한다 - 자동 Match가
       못 붙였거나 다른 게임이라고 본 짝이라도, 사용자가 직접 고른 것이 더 정확한 정보다.
       Match 결과를 바꾸지는 않는다. 이번 작업에 한해 "이 둘을 이어라"라고 승인한 것뿐이다.
    2. 지목이 없으면 `TargetIndex`가 Compare와 **같은 엔진**으로 찾는다(위 주석 참고).
    """
    targets = targets or {}
    # 호출자가 이미 만들어 둔 색인이 있으면 그것을 쓴다 - `paste()`는 "대상이 있는가"를
    # 먼저 봐야 해서 같은 색인을 한 번 더 만들 이유가 없고, 무엇보다 **두 곳이 다른 기준으로
    # 대상을 찾으면** 한쪽이 거른 항목이 다른 쪽에 닿지 않는다(실제로 그랬다).
    index = index if index is not None else TargetIndex(cache, {item["system"] for item in items})
    prepared, skipped = [], []
    for item in items:
        chosen = targets.get(item_key(item))
        if chosen is not None:
            existing, how = chosen, "manual"
        else:
            existing, how = index.find(item, accept_similar=(mode == MODE_REPLACE),
                                       exact_only=exact_only)
        if existing is not None:
            out, reason = decide(item, existing, mode,
                                 allow_rom_replace=allow_rom_replace,
                                 force_media=force_media)
            if out is not None and (existing["system"], existing["filename"]) != (item["system"], item["filename"]):
                # 대상의 이름으로 쓴다 - 그래야 gamelist의 그 항목에 들어가고, 미디어도 그
                # 파일명으로 놓여 프론트엔드가 찾는다.
                out = {**out, "system": existing["system"], "filename": existing["filename"]}
        else:
            out, reason = decide(item, existing, mode,
                                 allow_rom_replace=allow_rom_replace,
                                 force_media=force_media)
        if out is None:
            skipped.append({"filename": item["filename"], "reason": reason})
        else:
            prepared.append(out)
    return prepared, skipped


    return ("이름이 달라 같은 게임이라고 확신할 수 없습니다 - Replace 모드로 붙여넣거나, "
            "Compare나 우클릭 \"이 항목에 붙여넣기\"로 직접 지목하세요")


def _same_media(media, existing) -> bool:
    """원본 미디어가 대상의 그것과 같은 파일인가.

    **크기만 본다**(사용자 결정, 번복 - `app/plan/builder.classify_destination()`의
    `size_only`와 같은 이유). 예전엔 크기+수정시각을 요구했는데, Collection/기기를
    옮기면(특히 MTP) mtime이 원본 그대로 보존되지 않는 경우가 흔해서 똑같은 그림도
    매번 "다른 파일"로 보여 붙여넣을 때마다 Conflict가 떴다. ROM은 아예 덮어쓰지
    않으므로(위 머리말) 같은 판정이 필요 없다."""
    if existing is None:
        return False
    try:
        stat = Path(media["path"]).stat()
    except (OSError, KeyError, TypeError):
        return False
    return stat.st_size == int(existing.get("size") or 0)


def _same_path(left, right) -> bool:
    if not left or not right:
        return False
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _nothing_to_change(mode, item) -> str:
    if mode == MODE_PATCH:
        return "보완 모드 - 대상이 이미 모두 가지고 있어 채울 것이 없습니다"
    return "원본과 대상이 같아 바뀌는 것이 없습니다"
