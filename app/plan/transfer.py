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

from app.match import engine as match_engine

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


def _subject_of_item(item) -> dict:
    """전송 항목 -> Match 엔진이 보는 모양. Compare가 행을 넘길 때와 같은 구조여야
    두 화면이 "같은 게임인가"를 같은 기준으로 판단한다."""
    return match_engine.subject(
        system=item["system"], filename=item["filename"],
        title=(item.get("fields") or {}).get("name"),
        size=(item.get("rom") or {}).get("size"),
        fields=item.get("fields"))


class TargetIndex:
    """붙여넣기의 대상 후보를 한 번만 읽어 두는 색인.

    **Compare와 같은 엔진(match_engine)으로 대상을 찾는다.** 예전에는 붙여넣기만
    `get_row_by_filename()`으로 **파일명이 글자 하나까지 같을 때만** 대상으로 인정했다.
    그래서 같은 화면의 두 기능이 "같은 게임인가"를 다르게 판단했다 - Compare는
    `Aleste [J].zip`과 `Aleste (Japan) (T-En by Tsunami v1.0) (Cartridge).zip`을 한 줄로
    짝지어 "메타데이터가 다르다"고 보여주는데, 정작 붙여넣기는 그 짝을 못 찾아
    아무 일도 하지 않았다(실사용 버그 - "Compare에선 대부분 다르다고 나오는데
    붙여넣으면 8개만 된다". 그 8개가 파일명까지 똑같은 것의 개수였다).

    티어를 두 단계로 갈라 쓴다.

    - `exact`(해시가 같거나 / 정규화 파일명 + 크기가 같다)는 **자동으로 대상으로 삼는다.**
    - `normalized`(이름은 같은데 크기가 다르다)는 match_engine 스스로 "지역판/리비전
      차이일 수 있어 확증이 없다"고 말하는 티어다. 조용히 덮어쓰면 남의 판을 지운다 -
      **자동으로 붙이지 않고, 그런 후보가 있다는 사실을 이유로 돌려준다.** 사용자는
      Compare나 "이 항목에 붙여넣기"로 직접 지목하면 된다(§88 - 모호하면 자동으로
      결정하지 않는다).
    """

    def __init__(self, cache, systems):
        # 색인에는 **가벼운 요약(all_entries)**만 담고, 실제로 맞은 행은 get_row()로 다시
        # 읽는다 - decide()는 media/frontend_raw까지 있는 온전한 행을 봐야 한다
        # (all_entries는 Compare용이라 media_types/media_sizes만 싣는다).
        self._cache = cache
        self._by_name = {}
        self._buckets = {"file": {}, "title": {}, "sha": {}}
        for row in cache.all_entries(systems=sorted({s for s in systems if s})):
            self._by_name[(row["system"], row["filename"])] = row["rom_uid"]
            subject = match_engine.subject_of_row(row)
            system = subject["system"]
            for kind, key in (("file", subject["filename_norm"]),
                              ("title", subject["title_norm"]),
                              ("sha", subject["sha256"])):
                if key:
                    self._buckets[kind].setdefault((system, key), []).append(subject)

    def find(self, item, *, accept_similar=False) -> tuple[dict | None, str | None]:
        """(대상 행, 어떻게 찾았는지). 못 찾으면 (None, None), 모호하면 (None, "ambiguous").

        `accept_similar`는 **Replace 모드**가 준다(사용자 결정 - "replace는 그냥 다른
        게임이더라도 매뉴얼하게 소스를 중점으로 붙여넣기"). 이름은 같은데 크기가 달라
        match_engine이 확증을 주지 못하는 짝(`normalized`)까지 대상으로 받아들인다 -
        Replace를 고른 것 자체가 "같은 게임인지의 판정에 매이지 않겠다"는 명시적 의사다.
        Patch/Overwrite는 확증이 있는 짝(`exact`)만 자동으로 잡는다. 어느 모드든 후보가
        **여럿이면** 붙이지 않는다 - 어느 것인지 모르는데 고르면 남의 판을 덮어쓴다(§88).
        """
        exact = self._by_name.get((item["system"], item["filename"]))
        if exact is not None:
            return self._cache.get_row(exact), "exact"

        mine = _subject_of_item(item)
        system = mine["system"]
        candidates, seen = [], set()
        for kind, key in (("file", mine["filename_norm"]), ("title", mine["title_norm"]),
                          ("sha", mine["sha256"])):
            if not key:
                continue
            for subject in self._buckets[kind].get((system, key), ()):
                if subject["ref"] in seen:
                    continue
                seen.add(subject["ref"])
                candidates.append(subject)

        hits = []
        for subject in candidates:
            tier, _score, _why = match_engine.classify(mine, subject)
            if tier in (match_engine.TIER_EXACT, match_engine.TIER_NORMALIZED):
                hits.append((tier, subject["ref"]))
        if not hits:
            return None, None
        confident = [ref for tier, ref in hits if tier == match_engine.TIER_EXACT]
        if len(confident) == 1:
            return self._cache.get_row(confident[0]), "exact"
        if confident:
            return None, "ambiguous"
        # 여기부터는 normalized(이름은 같은데 크기가 다르다)뿐이다.
        similar = [ref for _tier, ref in hits]
        if len(similar) > 1:
            return None, "ambiguous"
        if accept_similar:
            return self._cache.get_row(similar[0]), "similar"
        return None, "similar"


def prepare(items, cache, mode, *, replace_rom=False, targets=None, index=None) -> tuple[list, list]:
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
            existing, how = index.find(item, accept_similar=(mode == MODE_REPLACE))
        if existing is not None and (existing["system"], existing["filename"]) != (item["system"], item["filename"]):
            # 대상의 이름으로 쓴다 - 그래야 gamelist의 그 항목에 들어가고, 미디어도 그
            # 파일명으로 놓여 프론트엔드가 찾는다.
            item = {**item, "system": existing["system"], "filename": existing["filename"]}
            if not replace_rom:
                # 이름이 다른 대상이다. ROM을 대상 이름으로 복사하면 확장자까지 바뀌어
                # 에뮬레이터가 못 읽는 파일이 된다 - ROM 교체를 명시한 때만 손댄다.
                item = {**item, "rom": None}
        if existing is None and how in ("similar", "ambiguous"):
            skipped.append({"filename": item["filename"], "reason": _no_confident_target(how)})
            continue
        out, reason = decide(item, existing, mode, replace_rom=replace_rom)
        if out is None:
            skipped.append({"filename": item["filename"], "reason": reason})
        else:
            prepared.append(out)
    return prepared, skipped


def _no_confident_target(how) -> str:
    """왜 안 붙었는지 **다음에 뭘 하면 되는지까지** 말한다 - 예전에는 이런 항목이
    "ROM 미매칭"이라는 엉뚱한 이유를 달고 사라져서, 진짜 원인(이름이 달라 대상을 못 찾음)을
    사용자가 알 길이 없었다."""
    if how == "ambiguous":
        return ("이름이 비슷한 대상이 여럿이라 어느 것인지 확정할 수 없습니다 - "
                "Compare나 우클릭 \"이 항목에 붙여넣기\"로 직접 지목하세요")
    return ("이름이 달라 같은 게임이라고 확신할 수 없습니다 - Replace 모드로 붙여넣거나, "
            "Compare나 우클릭 \"이 항목에 붙여넣기\"로 직접 지목하세요")


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
