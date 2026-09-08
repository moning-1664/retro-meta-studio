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

from similar_rom import compute_pair_score
from utils import normalize_title

TIER_EXACT = "exact"
TIER_NORMALIZED = "normalized"
TIER_METADATA = "metadata"
TIER_HEURISTIC = "heuristic"

# 낮을수록 강한 티어. 정렬과 "자동 가능" 판정 모두 이 순서를 쓴다.
TIER_RANK = {TIER_EXACT: 0, TIER_NORMALIZED: 1, TIER_METADATA: 2, TIER_HEURISTIC: 3}

#: 자동으로 붙여도 되는 티어. 여기에 무언가를 더 넣는 것은 §49를 어기는 일이다.
AUTO_TIERS = (TIER_EXACT,)

#: Heuristic 후보로 인정할 최소 점수(similar_rom 기준 100점 만점).
#: similar_rom.py의 기본 임계값과 같은 값으로 맞춘다 - 두 곳이 서로 다른 기준으로
#: "닮았다"를 판정하면, 유사롬 목록과 Match 후보가 어긋나 보이는 이유를 설명할 수 없다.
HEURISTIC_THRESHOLD = 60.0

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


def classify(source: dict, identity: dict) -> tuple[str | None, float]:
    """이 Identity가 source와 어느 티어로 맞는지. (tier, score) - 안 맞으면 (None, 0).

    score는 0~100의 표시용 값이다. Exact는 확증 강도에 따라 100/99를 준다.
    """
    if source["system"] != identity["system"]:
        return None, 0.0

    src_sha, id_sha = source.get("sha256"), identity.get("sha256")
    if src_sha and id_sha:
        # 해시가 있는데 서로 다르면 같은 ROM일 수 없다 - 다른 티어로도 붙이지 않는다.
        if src_sha == id_sha:
            return TIER_EXACT, 100.0
        return None, 0.0

    same_filename_norm = bool(source["filename_norm"]) and \
        source["filename_norm"] == (identity.get("filename_norm") or "")
    src_size, id_size = source.get("size"), identity.get("size")

    if same_filename_norm and src_size and id_size and int(src_size) == int(id_size):
        return TIER_EXACT, 99.0

    same_title_norm = bool(source["title_norm"]) and \
        source["title_norm"] == (identity.get("title_norm") or "")
    if same_filename_norm or same_title_norm:
        # 이름은 같은데 크기가 다르다 = 지역판/리비전 차이일 가능성이 높다.
        # 확증이 없으므로 자동으로 붙이지 않는다.
        return TIER_NORMALIZED, 85.0 if same_filename_norm else 80.0

    return None, 0.0


def _heuristic(source: dict, identity: dict, identity_fields: dict) -> tuple[str | None, float]:
    """이름이 어긋난 뒤에 남는 마지막 단계. similar_rom의 배점을 그대로 쓴다."""
    score, breakdown = compute_pair_score(
        {"romKey": "src", "title": source["title"], "filename": source["filename"],
         "developer": source.get("developer"), "releasedate": source.get("releasedate")},
        {"romKey": identity["rom_identity_id"], "title": identity.get("title") or "",
         "filename": identity.get("filename") or "",
         "developer": identity_fields.get("developer") or "",
         "releasedate": identity_fields.get("releasedate") or ""},
    )
    if score < HEURISTIC_THRESHOLD:
        return None, 0.0
    # 제목이 거의 안 닮았는데 개발사/연도만으로 넘긴 경우는 성격이 다르다 - 따로 표시한다.
    tier = TIER_METADATA if breakdown["title"] < 20 else TIER_HEURISTIC
    return tier, round(score, 1)


def quick_candidates(archive, source: dict, *, exclude_collection=None,
                     limit=DEFAULT_LIMIT) -> list[dict]:
    """Exact/Normalized만 본다. 화면에 보이는 행마다 불러도 될 만큼 가벼워야 한다."""
    found = []
    for identity in archive.identities_in_system(source["system"],
                                                 exclude_collection=exclude_collection):
        tier, score = classify(source, identity)
        if tier:
            found.append({**_identity_view(identity), "tier": tier, "score": score})
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
        tier, score = classify(source, identity)
        if not tier:
            fields = fields_of(identity["rom_identity_id"]) if fields_of else {}
            tier, score = _heuristic(source, identity, fields or {})
        if tier:
            found.append({**_identity_view(identity), "tier": tier, "score": score})
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
