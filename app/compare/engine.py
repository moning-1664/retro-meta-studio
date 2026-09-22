"""
app/compare/engine.py
======================
Compare 엔진 (스펙 §54-59).

두 Collection의 Gamelist를 나란히 놓고 `Same / Only A / Only B / Conflict`로 가른다.

## 짝짓기 규칙 - 파일명이 글자까지 같을 때만

같은 System에서 **파일명이 완전히 같으면** 짝으로 본다. 크기나 해시가 달라도 짝이다 -
그 차이야말로 Compare가 보여주려는 것이기 때문이다.

이름이 닮았다는 이유로는 짝짓지 않는다(사용자 결정, 번복). 예전에는 `classify()`가
Exact/Normalized를 주고 그 상대가 유일하면 짝지었는데, **지역만 다른 판이 여럿이면
어느 것과 어느 것을 맺을지 정할 근거가 없다** - `Game [EU]`, `Game [KR]`, `Game [JP]`,
`Game [World]`는 정규화하면 넷 다 같은 이름이라, 1:1 표에서는 서로 다른 판이 임의로
같은 줄에 놓인다.

이름이 다른 같은 게임은 양쪽에 따로 남고(`only_a`/`only_b`), 필요하면 "직접 잇기"로
사람이 이어 준다. **붙여넣기는 다르다** - 거기서는 `app/gameid.py`가 지역과 디스크
번호까지 보고 대상을 하나 고를 수 있으므로, Compare에 안 보이는 짝도 붙여넣기로는
처리된다.

## 상태

| 상태 | 뜻 | 기호 |
|---|---|---|
| `same` | 양쪽에 있고 Metadata·Media가 모두 같다 | (없음) |
| `similar` | 양쪽에 있고 Metadata는 같은데 Media만 다르다 | `≒` |
| `conflict` | 양쪽에 있는데 Metadata가 다르다(Media도 같이 다를 수 있다) | `≠` |
| `only_a` | 기준(A)에만 있다 | `-` |
| `only_b` | 상대(B)에만 있다 | `+` |

**Metadata가 다르면 `conflict`, Metadata는 같은데 Media만 다르면 `similar`이다**(사용자
결정, 번복). 예전에는 Media만 달라도 `conflict`(`≠`)였는데, Cover/Screenshot이 눈에 보기엔
같아서 "왜 다르다고 나오지"로 오해를 샀다(실사용 버그 리포트) - hover해야만 "미디어가
다릅니다"를 알 수 있던 것을 아예 상태와 기호를 갈라서 한눈에 구분되게 한다.
"""

from __future__ import annotations

STATUS_SAME = "same"
STATUS_SIMILAR = "similar"
STATUS_CONFLICT = "conflict"
STATUS_ONLY_A = "only_a"
STATUS_ONLY_B = "only_b"

#: 값이 다르면 Conflict로 보는 필드. ES-DE의 favorite/playcount처럼 사람이 관리하는
#: 값이 아니라 "이 게임은 무엇인가"를 서술하는 필드만 본다 - 플레이 횟수가 다르다고
#: 두 Collection이 충돌한다고 말하면 목록이 온통 Conflict가 된다.
DIFF_FIELDS = ("name", "desc", "genre", "developer", "publisher",
               "releasedate", "region", "players", "rating")


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
    """(짝지어진 (left, right) 목록, 짝지어진 left 인덱스, 짝지어진 right 인덱스).

    **짝은 같은 System + 글자까지 같은 파일명일 때만 맺는다**(사용자 결정, 번복).

    예전에는 이름이 닮았으면(정규화 일치) 짝을 맺었다. 그러면 지역만 다른 판이
    여럿일 때 **어느 것과 어느 것을 맺을지 정할 근거가 없다** - `Game [EU]`,
    `Game [KR]`, `Game [JP]`, `Game [World]`는 정규화하면 넷 다 같은 이름이라
    1:1 표에서는 임의로 짝지어지고, 화면에는 서로 다른 판이 같은 줄에 나란히
    놓인다. Compare는 "이 둘을 맞대 보라"고 보여 주는 화면이므로 확신할 수 없는
    짝을 지어서는 안 된다.

    이름이 다른 같은 게임은 Compare에서 양쪽에 따로 남고(`only_a`/`only_b`),
    필요하면 "직접 잇기"로 사람이 이어 준다. 붙여넣기는 다르다 - 거기서는
    `app/gameid.py`가 지역/디스크까지 보고 대상을 하나 고를 수 있다.
    """
    pairs = []
    used_left, used_right = set(), set()

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

    return pairs, used_left, used_right


def media_changes(left, right) -> list[str]:
    """Media 종류 중 양쪽이 다른 것. 한쪽에만 있거나, 양쪽에 있어도 파일 크기가 다르면 다르다."""
    lsizes = left.get("media_sizes") or {t: 0 for t in left.get("media_types") or []}
    rsizes = right.get("media_sizes") or {t: 0 for t in right.get("media_types") or []}
    changed = []
    for media_type in sorted(set(lsizes) | set(rsizes)):
        if media_type not in lsizes or media_type not in rsizes or lsizes[media_type] != rsizes[media_type]:
            changed.append(media_type)
    return changed


def compare(left_entries, right_entries) -> list[dict]:
    """두 Collection의 항목을 맞대어 행 목록을 만든다.

    entry는 `CacheStore.all_entries()`가 주는 모양을 그대로 받는다.
    반환 행: {system, file, status, mediaDiff, mediaChanged, changedFields, left, right}
    left/right는 각각 {romUid, filename, title, size, present, mediaTypes, mediaSizes, fields} 또는 None.

    **있고 없고의 기준은 ROM 파일명이다**(사용자 결정) - ROM 실물이 있는지가 아니다.
    `_pair()`가 이미 파일명으로 짝을 지었으므로, 짝지어진
    행은 그 사실만으로 "양쪽에 있음"이다. 한쪽의 ROM 실물이 없어도(gamelist 항목만 있는
    경우) `only_a`/`only_b`로 갈라 보내지 않는다 - 그렇게 하면 파일명이 같은데도 ROM
    유무 차이만으로 "다른 파일"처럼 보였다(실사용 버그 리포트):
      - 짝지어지지 않고 왼쪽에만 있으면 `only_a`(`>`), 오른쪽에만 있으면 `only_b`(`<`)
      - 짝지어졌고 Metadata와 Media가 모두 같으면 `same`(`=`)
      - Metadata는 같은데 Media만 다르면 `similar`(`≒`)
      - Metadata가 다르면 `conflict`(`≠`) - Media도 같이 다를 수 있다
    """
    pairs, used_left, used_right = _pair(left_entries, right_entries)

    rows = []
    for i, j in pairs:
        left, right = left_entries[i], right_entries[j]
        changed = fields_differ(left.get("fields"), right.get("fields"))
        media_changed = media_changes(left, right)
        if changed:
            status = STATUS_CONFLICT
        elif media_changed:
            status = STATUS_SIMILAR
        else:
            status = STATUS_SAME
        rows.append({
            "system": left["system"],
            "file": left["filename"],
            "status": status,
            "changedFields": changed,
            "mediaDiff": bool(media_changed),
            "mediaChanged": media_changed,
            "left": _side(left),
            "right": _side(right),
        })

    for i, left in enumerate(left_entries):
        if i in used_left:
            continue
        rows.append({"system": left["system"], "file": left["filename"],
                     "status": STATUS_ONLY_A, "changedFields": [], "mediaDiff": False,
                     "mediaChanged": [], "left": _side(left), "right": None})

    for j, right in enumerate(right_entries):
        if j in used_right:
            continue
        rows.append({"system": right["system"], "file": right["filename"],
                     "status": STATUS_ONLY_B, "changedFields": [], "mediaDiff": False,
                     "mediaChanged": [], "left": None, "right": _side(right)})

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
        "mediaSizes": dict(entry.get("media_sizes") or {}),
        "fields": entry.get("fields") or {},
    }


def summarize(rows) -> dict:
    """필터 버튼에 붙일 개수. 화면이 [All][Same][Only A][Only B][Conflict][Similar][Media]를
    한 줄로 보여주므로, 목록을 다시 훑지 않아도 되게 여기서 같이 센다."""
    counts = {"all": len(rows), "diff": 0, STATUS_SAME: 0, STATUS_SIMILAR: 0, STATUS_CONFLICT: 0,
              STATUS_ONLY_A: 0, STATUS_ONLY_B: 0, "media": 0}
    for row in rows:
        counts[row["status"]] += 1
        # "diff"(≠ 그룹)는 Metadata가 다르거나 한쪽에만 있는 것만 센다 - Media만 다른
        # `similar`(≒)는 따로 걸러 보게 뒀으므로 여기 섞이지 않는다.
        if row["status"] not in (STATUS_SAME, STATUS_SIMILAR):
            counts["diff"] += 1
        if row["mediaDiff"]:
            counts["media"] += 1
    return counts


def filter_rows(rows, status=None):
    """`status`가 None이거나 "all"이면 전부. "media"는 상태가 아니라 Media 차이 필터다."""
    if not status or status == "all":
        return rows
    if status == "media":
        return [r for r in rows if r["mediaDiff"]]
    if status == "diff":       # `≠`, `>`, `<` 전부 - `similar`(≒)는 뺀다("다른 것만 보기")
        return [r for r in rows if r["status"] not in (STATUS_SAME, STATUS_SIMILAR)]
    return [r for r in rows if r["status"] == status]
