"""
app/match/engine.py
====================
Match 엔진 (스펙 §45-49).

Collection의 한 ROM이 Archive의 어느 ROM Identity와 같은 것인지 판정한다.
티어는 스펙의 우선순위를 그대로 따른다:

  1. Exact ROM Identity   - 자동으로 붙여도 되는 유일한 티어
  2. Normalized           - 정규화 파일명/제목은 같지만 확증이 없다
  3. Metadata             - 제목은 달라도 개발사/연도/장르가 겹친다
  4. Heuristic            - 문자열 유사도만으로 걸린 후보
  5. (후보 없음)

**자동으로 붙이는 것은 Exact뿐이다(§49).** 나머지는 점수와 함께 후보로만 내놓고,
사용자가 고른 결과를 `match_links`에 남긴다. 점수는 추천 순서와 참고 정보이지
자동 병합의 근거가 아니다.

## Exact를 어떻게 판정하는가

스펙이 못박은 것: **파일명만으로 Exact를 확정하면 안 된다**(§47). 그래서

  - 양쪽 SHA256이 있고 같으면      -> Exact (확정적)
  - 아니면 (정규화 파일명 + 크기)가 같아야 Exact
    (ARCHITECTURE §해시: 전량 사전 해싱은 금지, `(size, 정규화 파일명)`가 1차 판정)

크기를 모르는 쪽(metadata-only 항목 등)은 Exact가 될 수 없고 Normalized로 내려간다.

## 두 갈래 진입점

- `quick_candidates()` - 인덱스로 바로 찾히는 것만(Exact/Normalized). Gamelist의
  Match 뱃지처럼 화면에 보이는 행마다 부르는 자리에서 쓴다.
- `deep_candidates()`  - 같은 System 전체를 훑어 Metadata/Heuristic까지 본다.
  사용자가 Match 버튼을 눌렀을 때만 부른다 - similar_rom.py가 세워둔 원칙("자동
  실행 안 함, 사용자가 요청한 스코프에서만 O(n) 비교")을 그대로 지킨다.
"""

from __future__ import annotations

from pathlib import Path

from similar_rom import DEFAULT_WEIGHTS, compute_pair_score
from utils import normalize_title

TIER_EXACT = "exact"
TIER_NORMALIZED = "normalized"
TIER_METADATA = "metadata"
TIER_HEURISTIC = "heuristic"

#: 엔진이 근거를 대지 못했지만 사용자가 알고서 강제로 이은 링크. 엔진은 이 값을
#: **절대 반환하지 않는다** - `service.apply_match(..., manual=True)`로만 기록된다.
#: 후보 판정 결과와 사람의 단언을 같은 이름으로 묶으면, 나중에 "이 링크는 왜 있지?"를
#: 데이터만 보고 설명할 수 없게 된다.
TIER_MANUAL = "manual"

# 낮을수록 강한 티어. 정렬과 "자동 가능" 판정 모두 이 순서를 쓴다.
TIER_RANK = {TIER_EXACT: 0, TIER_NORMALIZED: 1, TIER_METADATA: 2,
             TIER_HEURISTIC: 3, TIER_MANUAL: 4}

#: 자동으로 붙여도 되는 티어. 여기에 무언가를 더 넣는 것은 §49를 어기는 일이다.
AUTO_TIERS = (TIER_EXACT,)

#: Heuristic 후보로 인정할 최소 점수(100점 만점). similar_rom.py의 기본 임계값과
#: 같은 값으로 맞춘다 - 두 곳이 서로 다른 기준으로 "닮았다"를 판정하면, 유사롬
#: 목록과 Match 후보가 어긋나 보이는 이유를 설명할 수 없다.
#:
#: **단, 점수는 "실제로 비교할 수 있었던 근거" 기준으로 환산해서 잰다**(_heuristic_match
#: 참고). similar_rom의 100점에는 스크린샷 해시 20점이 들어 있는데 Match 경로는 그걸
#: 계산하지 않고, 개발사/출시일까지 비어 있으면 만점이 50점이다. 환산 없이 60을 대면
#: Heuristic 티어는 사실상 도달 불가능한 죽은 코드가 된다.
HEURISTIC_THRESHOLD = 60.0

#: 환산을 하더라도 근거가 너무 적으면 판정 자체를 포기한다. 제목 하나만 보고 "닮았다"고
#: 말하지 않기 위한 하한선(제목 35 + 파일명 15).
MIN_ATTAINABLE_EVIDENCE = 50.0

#: Metadata 티어로 인정할 최소 점수. 구조화된 필드의 **동일성**으로만 매기므로
#: 문자열 유사도 점수(HEURISTIC_THRESHOLD)와 척도가 다르다 - 아래 _metadata_match 참고.
METADATA_THRESHOLD = 70.0

#: 후보 목록에 보여줄 최대 개수. 스펙의 예시 화면이 3~5개 규모다.
DEFAULT_LIMIT = 8


def source_of_row(row) -> dict:
    """cache의 row를 Match 입력 형태로 바꾼다."""
    fields = row.get("fields") or {}
    filename = row["filename"]
    title = (row.get("title") or "").strip() or Path(filename).stem
    return {
        "system": row["system"],
        "filename": filename,
        "size": row.get("size") or None,
        "sha256": row.get("sha256"),
        "title": title,
        "title_norm": normalize_title(title),
        "filename_norm": normalize_title(Path(filename).stem),
        "developer": fields.get("developer") or "",
        "publisher": fields.get("publisher") or "",
        "releasedate": fields.get("releasedate") or "",
    }


def _identity_view(identity) -> dict:
    fields_title = identity.get("title") or identity.get("filename") or ""
    return {
        "romIdentityId": identity["rom_identity_id"],
        "gameId": identity["game_id"],
        "system": identity["system"],
        "filename": identity.get("filename") or identity.get("filename_norm") or "",
        "title": fields_title,
        "region": identity.get("region"),
        "size": identity.get("size"),
        "sha256": identity.get("sha256"),
    }


def classify(source: dict, identity: dict) -> tuple[str | None, float, list[str]]:
    """이름/해시/크기만으로 판정하는 앞쪽 두 티어. (tier, score, evidence).

    안 맞으면 (None, 0.0, []). score는 0~100의 표시용 값이고, evidence는 "왜 이 티어인지"를
    사용자에게 그대로 보여주기 위한 근거 문구다.

    **한쪽만 해시를 아는 경우**: 해시로는 확정할 수 없으므로 (정규화 파일명 + 크기) 규칙으로
    내려간다. 그 조합을 Exact의 2차 증거로 인정하는 것은 ARCHITECTURE의 해시 정책("전량
    사전 해싱 금지, (size, 정규화 파일명)이 1차 판정")을 따른 의도된 결정이다.
    """
    if source["system"] != identity["system"]:
        return None, 0.0, []

    src_sha, id_sha = source.get("sha256"), identity.get("sha256")
    if src_sha and id_sha:
        # 해시가 있는데 서로 다르면 같은 ROM일 수 없다 - 다른 티어로도 붙이지 않는다.
        if src_sha == id_sha:
            return TIER_EXACT, 100.0, ["SHA256 일치"]
        return None, 0.0, []

    same_filename_norm = bool(source["filename_norm"]) and \
        source["filename_norm"] == (identity.get("filename_norm") or "")
    src_size, id_size = source.get("size"), identity.get("size")

    if same_filename_norm and src_size and id_size and int(src_size) == int(id_size):
        return TIER_EXACT, 99.0, ["파일명 일치", "크기 일치"]

    same_title_norm = bool(source["title_norm"]) and \
        source["title_norm"] == (identity.get("title_norm") or "")
    if same_filename_norm or same_title_norm:
        # 이름은 같은데 크기가 다르다 = 지역판/리비전 차이일 가능성이 높다.
        # 확증이 없으므로 자동으로 붙이지 않는다.
        if same_filename_norm:
            return TIER_NORMALIZED, 85.0, ["정규화 파일명 일치", "크기 다름"]
        return TIER_NORMALIZED, 80.0, ["정규화 제목 일치"]

    return None, 0.0, []


def _same(a, b) -> bool:
    """빈 값은 "같다"로 치지 않는다 - 둘 다 비어 있는 필드로 매칭되면 안 된다."""
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    return bool(a) and a == b


def _metadata_match(source: dict, identity_fields: dict) -> tuple[str | None, float, list[str]]:
    """구조화된 Metadata가 서로 **같은가**(§45의 "Strong metadata match").

    문자열 유사도가 아니라 값의 동일성으로 본다. 유사도로 판정하면 결국 Heuristic과
    같은 축이 되어 두 티어를 나눌 이유가 없어진다.

    개발사만, 혹은 연도만 같은 것은 근거가 되지 못한다 - 같은 회사가 같은 해에 낸
    게임은 얼마든지 있다. **개발사와 출시일이 함께** 같아야 후보로 올린다.
    """
    developer = _same(source.get("developer"), identity_fields.get("developer"))
    release = _same(source.get("releasedate"), identity_fields.get("releasedate"))
    publisher = _same(source.get("publisher"), identity_fields.get("publisher"))
    if not (developer and release):
        return None, 0.0, []

    evidence = ["개발사 일치", "출시일 일치"]
    score = METADATA_THRESHOLD
    if publisher:
        evidence.append("배급사 일치")
        score += 10.0
    return TIER_METADATA, score, evidence


def _heuristic_match(source: dict, identity: dict,
                     identity_fields: dict) -> tuple[str | None, float, list[str]]:
    """마지막 단계 - 문자열 유사도. similar_rom의 배점을 그대로 쓴다.

    여기서 나온 점수는 **추천 순서를 정하는 용도**일 뿐이며, 몇 점이든 자동으로
    붙지 않는다(§49).
    """
    left = {"romKey": "src", "title": source["title"], "filename": source["filename"],
            "developer": source.get("developer") or "",
            "releasedate": source.get("releasedate") or ""}
    right = {"romKey": identity["rom_identity_id"], "title": identity.get("title") or "",
             "filename": identity.get("filename") or "",
             "developer": identity_fields.get("developer") or "",
             "releasedate": identity_fields.get("releasedate") or ""}
    raw, breakdown = compute_pair_score(left, right)

    # 양쪽 모두 값이 있는 항목의 배점만 합쳐 "이번에 실제로 비교할 수 있었던 최대 점수"를
    # 구하고, 그 기준으로 환산한다. 스크린샷 해시(20점)는 이 경로에서 아예 계산하지
    # 않으므로 애초에 빠진다.
    attainable = 0.0
    for key, (a, b) in {"title": (left["title"], right["title"]),
                        "filename": (left["filename"], right["filename"]),
                        "developer": (left["developer"], right["developer"]),
                        "year": (left["releasedate"][:4], right["releasedate"][:4])}.items():
        if a and b:
            attainable += DEFAULT_WEIGHTS[key]
    if attainable < MIN_ATTAINABLE_EVIDENCE:
        return None, 0.0, []

    score = raw / attainable * 100.0
    if score < HEURISTIC_THRESHOLD:
        return None, 0.0, []

    # 무엇이 점수를 만들었는지 사용자에게 그대로 보여준다 - "왜 이게 후보지?"에
    # 답하지 못하는 점수는 추천 순서로도 신뢰할 수 없다.
    weights = {"title": "제목", "filename": "파일명", "developer": "개발사", "year": "출시년도"}
    evidence = [f"{label} {round(breakdown[key])}점"
                for key, label in weights.items() if breakdown.get(key)]
    return TIER_HEURISTIC, round(score, 1), evidence


def quick_candidates(archive, source: dict, *, exclude_collection=None,
                     limit=DEFAULT_LIMIT) -> list[dict]:
    """Exact/Normalized만 본다. 화면에 보이는 행마다 불러도 될 만큼 가벼워야 한다."""
    found = []
    for identity in archive.identities_matching(
            source["system"], filename_norm=source["filename_norm"],
            title_norm=source["title_norm"], sha256=source.get("sha256"),
            exclude_collection=exclude_collection):
        tier, score, evidence = classify(source, identity)
        if tier:
            found.append({**_identity_view(identity), "tier": tier,
                          "score": score, "evidence": evidence})
    return _rank(found, limit)


def deep_candidates(archive, source: dict, *, exclude_collection=None,
                    limit=DEFAULT_LIMIT, fields_of=None) -> list[dict]:
    """Metadata/Heuristic까지 본다. 사용자가 Match를 눌렀을 때만 부를 것.

    `fields_of(rom_identity_id) -> dict`를 주면 후보의 Metadata(개발사/연도)를
    점수에 반영한다. 안 주면 Identity에 들어 있는 정보만으로 계산한다.
    """
    found = []
    for identity in archive.identities_in_system(source["system"],
                                                 exclude_collection=exclude_collection):
        tier, score, evidence = classify(source, identity)
        if not tier:
            fields = (fields_of(identity["rom_identity_id"]) if fields_of else {}) or {}
            # 구조화된 필드의 동일성을 먼저 본다. 그게 안 되면 문자열 유사도로 내려간다.
            tier, score, evidence = _metadata_match(source, fields)
            if not tier:
                tier, score, evidence = _heuristic_match(source, identity, fields)
        if tier:
            found.append({**_identity_view(identity), "tier": tier,
                          "score": score, "evidence": evidence})
    return _rank(found, limit)


def _rank(found: list[dict], limit: int) -> list[dict]:
    found.sort(key=lambda c: (TIER_RANK[c["tier"]], -c["score"], c["filename"]))
    return found[:limit]


def auto_match(candidates: list[dict]) -> dict | None:
    """자동으로 붙여도 되는 후보. 없으면 None.

    Exact가 **하나일 때만** 자동이다. 둘 이상이면 어느 쪽인지 사람이 정해야 한다 -
    모호하면 자동으로 결정하지 않는다(§88).
    """
    exact = [c for c in candidates if c["tier"] in AUTO_TIERS]
    return exact[0] if len(exact) == 1 else None
