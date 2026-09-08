"""
app/compare/engine.py
======================
Compare 엔진 (스펙 §54-59).

두 Collection의 Gamelist를 나란히 놓고 `Same / Only A / Only B / Conflict`로 가른다.

## Match 엔진과의 관계

판정 규칙은 `app/match/engine.py`의 `classify()`를 **그대로 재사용한다**. 그럴 수 있는
이유는 Phase 6 착수 전에 판정 계약을 `MatchSubject <-> MatchSubject`로 한 단계 올려
두었기 때문이다 - 그 전에는 "Collection row <-> Archive identity"로 못박혀 있어서,
Compare가 쓰려면 Collection 쪽을 Archive인 척 꾸며 넘겨야 했다.

다만 **짝짓기 규칙은 Match와 다르다**. Match는 "이 둘이 같은 ROM인가"를 묻고 확증이
없으면 후보로만 내놓지만, Compare는 목록 두 개를 1:1로 줄 세워야 한다. 그래서:

1. **1차 - 정확한 파일명**: 같은 System에서 파일명이 완전히 같으면 짝으로 본다.
   크기나 해시가 달라도 짝이다 - 그 차이야말로 Compare가 보여주려는 것이기 때문이다.
   (Match의 Exact는 크기/해시 확증을 요구하지만, 여기서 같은 잣대를 쓰면 같은 이름의
   다른 덤프가 "양쪽에 각각 있음"으로 갈라져 보인다.)
2. **2차 - 엔진 판정이 유일할 때만**: 남은 것들에 `classify()`를 돌려 Exact/Normalized로
   걸리는 상대를 찾되, **후보가 정확히 하나일 때만** 짝짓는다. 둘 이상이면 어느 쪽인지
   알 수 없으므로 각자 "한쪽에만 있음"으로 남긴다 - 모호하면 자동으로 결정하지 않는다(§88).

## 상태

| 상태 | 뜻 | 기호 |
|---|---|---|
| `same` | 양쪽에 있고 Metadata도 같다 | (없음) |
| `conflict` | 양쪽에 있는데 Metadata가 다르다 | `△` |
| `only_a` | 기준(A)에만 있다 | `-` |
| `only_b` | 상대(B)에만 있다 | `+` |

Media 차이는 상태를 바꾸지 않고 `mediaDiff`로 따로 표시한다. Media만 다른 것을 Conflict로
부르면 "Metadata가 충돌한다"는 뜻이 흐려지고, 스펙도 `[Media]`를 별도 필터로 둔다.
"""

from __future__ import annotations

from app.match import engine as match_engine

STATUS_SAME = "same"
STATUS_CONFLICT = "conflict"
STATUS_ONLY_A = "only_a"
STATUS_ONLY_B = "only_b"

#: 값이 다르면 Conflict로 보는 필드. ES-DE의 favorite/playcount처럼 사람이 관리하는
#: 값이 아니라 "이 게임은 무엇인가"를 서술하는 필드만 본다 - 플레이 횟수가 다르다고
#: 두 Collection이 충돌한다고 말하면 목록이 온통 Conflict가 된다.
DIFF_FIELDS = ("name", "desc", "genre", "developer", "publisher",
               "releasedate", "region", "players", "rating")


def _subject(entry) -> dict:
    return match_engine.subject_of_row(entry)


def fields_differ(a, b) -> list[str]:
    """다른 필드의 이름들. 같으면 빈 리스트."""
    a, b = a or {}, b or {}
    changed = []
    for key in DIFF_FIELDS:
        left = str(a.get(key) or "").strip()
        right = str(b.get(key) or "").strip()
        if left != right:
            changed.append(key)
    return changed


def _pair(left_entries, right_entries) -> tuple[list[tuple], set, set]:
    """(짝지어진 (left, right) 목록, 짝지어진 left 인덱스, 짝지어진 right 인덱스)."""
    pairs = []
    used_left, used_right = set(), set()

    # 1차: 같은 System + 완전히 같은 파일명.
    by_name = {}
    for j, right in enumerate(right_entries):
        by_name.setdefault((right["system"], right["filename"]), []).append(j)
    for i, left in enumerate(left_entries):
        bucket = by_name.get((left["system"], left["filename"]))
        while bucket:
            j = bucket.pop(0)
            if j in used_right:
                continue
            pairs.append((i, j))
            used_left.add(i)
            used_right.add(j)
            break

    # 2차: 엔진이 Exact/Normalized로 인정하고, 그런 상대가 **유일할** 때만.
    remaining_right = [j for j in range(len(right_entries)) if j not in used_right]
    if remaining_right:
        right_subjects = {j: _subject(right_entries[j]) for j in remaining_right}
        for i, left in enumerate(left_entries):
            if i in used_left:
                continue
            left_subject = _subject(left)
            hits = []
            for j in remaining_right:
                if j in used_right:
                    continue
                tier, _score, _why = match_engine.classify(left_subject, right_subjects[j])
                if tier in (match_engine.TIER_EXACT, match_engine.TIER_NORMALIZED):
                    hits.append(j)
                    if len(hits) > 1:
                        break
            if len(hits) == 1:
                pairs.append((i, hits[0]))
                used_left.add(i)
                used_right.add(hits[0])

    return pairs, used_left, used_right


def compare(left_entries, right_entries) -> list[dict]:
    """두 Collection의 항목을 맞대어 행 목록을 만든다.

    entry는 `CacheStore.all_entries()`가 주는 모양을 그대로 받는다.
    반환 행: {system, file, status, mediaDiff, changedFields, left, right}
    left/right는 각각 {romUid, filename, title, size, present, mediaTypes, fields} 또는 None.
    """
    pairs, used_left, used_right = _pair(left_entries, right_entries)

    rows = []
    for i, j in pairs:
        left, right = left_entries[i], right_entries[j]
        changed = fields_differ(left.get("fields"), right.get("fields"))
        media_diff = set(left.get("media_types") or []) != set(right.get("media_types") or [])
        rows.append({
            "system": left["system"],
            "file": left["filename"],
            "status": STATUS_CONFLICT if changed else STATUS_SAME,
            "changedFields": changed,
            "mediaDiff": media_diff,
            "left": _side(left),
            "right": _side(right),
        })

    for i, left in enumerate(left_entries):
        if i in used_left:
            continue
        rows.append({"system": left["system"], "file": left["filename"],
                     "status": STATUS_ONLY_A, "changedFields": [], "mediaDiff": False,
                     "left": _side(left), "right": None})

    for j, right in enumerate(right_entries):
        if j in used_right:
            continue
        rows.append({"system": right["system"], "file": right["filename"],
                     "status": STATUS_ONLY_B, "changedFields": [], "mediaDiff": False,
                     "left": None, "right": _side(right)})

    rows.sort(key=lambda r: (r["system"], r["file"].lower()))
    return rows


def _side(entry) -> dict:
    return {
        "romUid": entry["rom_uid"],
        "filename": entry["filename"],
        "title": entry.get("title") or "",
        "size": entry.get("size") or 0,
        "present": bool(entry.get("present", True)),
        "mediaTypes": list(entry.get("media_types") or []),
        "fields": entry.get("fields") or {},
    }


def summarize(rows) -> dict:
    """필터 버튼에 붙일 개수. 화면이 [All][Same][Only A][Only B][Conflict][Media]를
    한 줄로 보여주므로, 목록을 다시 훑지 않아도 되게 여기서 같이 센다."""
    counts = {"all": len(rows), STATUS_SAME: 0, STATUS_CONFLICT: 0,
              STATUS_ONLY_A: 0, STATUS_ONLY_B: 0, "media": 0}
    for row in rows:
        counts[row["status"]] += 1
        if row["mediaDiff"]:
            counts["media"] += 1
    return counts


def filter_rows(rows, status=None):
    """`status`가 None이거나 "all"이면 전부. "media"는 상태가 아니라 Media 차이 필터다."""
    if not status or status == "all":
        return rows
    if status == "media":
        return [r for r in rows if r["mediaDiff"]]
    return [r for r in rows if r["status"] == status]
