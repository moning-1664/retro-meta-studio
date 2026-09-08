"""
app/match/service.py
=====================
Match 엔진을 Collection/Archive에 붙이는 층 (스펙 §45-49, Scenario 9).

흐름은 스펙의 시나리오 9 그대로다:
  Exact Match 실패 -> 후보 발견 -> Gamelist에 Match 버튼 -> 사용자 클릭
  -> 후보 목록 -> 선택 -> Apply Match

여기서 하는 일은 셋뿐이다.
  - 후보를 찾아 준다(`candidates_for`)
  - 사용자가 고른 결과를 남긴다(`apply_match`) - **자동으로 고르지 않는다**
  - 남긴 링크를 Ingest가 존중하게 한다(`linked_identity`)

Match를 적용해도 파일은 움직이지 않고 Metadata도 덮어쓰지 않는다. "이 ROM은
Archive의 저 Identity와 같은 것"이라는 사실만 기록한다 - 실제로 값을 가져오는 것은
사용자가 Archive -> Collection을 실행할 때다(§40, §41).
"""

from __future__ import annotations

from app.match import engine


def linked_identity(archive, collection_id, system, filename) -> str | None:
    """사용자가 확정해 둔 Match가 있으면 그 rom_identity_id."""
    link = archive.get_match_link(collection_id, system, filename)
    return link["rom_identity_id"] if link else None


def candidates_for(archive, collection_id, row, *, deep=True, limit=engine.DEFAULT_LIMIT) -> dict:
    """이 ROM에 대한 후보 목록.

    자기 Collection에서만 올라간 Identity는 후보에서 뺀다 - 자기 자신과 Match하는
    것은 의미가 없기 때문이다.
    """
    source = engine.source_of_row(row)
    finder = engine.deep_candidates if deep else engine.quick_candidates

    def fields_of(rom_identity_id):
        sources = archive.sources_of(rom_identity_id)
        latest = max(sources, key=lambda s: s["updated_at"], default=None)
        return (latest or {}).get("fields") or {}

    kwargs = {"exclude_collection": collection_id, "limit": limit}
    if deep:
        kwargs["fields_of"] = fields_of
    candidates = finder(archive, source, **kwargs)

    linked = linked_identity(archive, collection_id, row["system"], row["filename"])
    for candidate in candidates:
        candidate["linked"] = candidate["romIdentityId"] == linked
    return {
        "source": {"system": source["system"], "filename": source["filename"],
                   "title": source["title"], "size": source["size"]},
        "candidates": candidates,
        "linkedRomIdentityId": linked,
        "autoMatch": (engine.auto_match(candidates) or {}).get("romIdentityId"),
    }


def counts_for_rows(archive, collection_id, rows) -> dict:
    """Gamelist 뱃지용. 이미 링크된 행은 뱃지를 띄우지 않는다(할 일이 없으므로).

    화면에 보이는 행에 대해서만 부르는 것을 전제로 quick 티어만 본다 - deep은
    같은 System 전체를 훑으므로 목록 렌더링 경로에 둘 수 없다.
    """
    links = archive.match_links_of(collection_id)
    counts = {}
    for row in rows:
        if (row["system"], row["filename"]) in links:
            continue
        source = engine.source_of_row(row)
        found = engine.quick_candidates(archive, source, exclude_collection=collection_id)
        if found:
            counts[int(row["rom_uid"])] = len(found)
    return counts


def apply_match(archive, collection_id, row, rom_identity_id, *, manual=False) -> dict:
    """사용자가 고른 후보를 확정한다(§49의 [Apply Match]).

    **반드시 후보 목록에 있던 Identity여야 한다.** Match Link는 단순 메모가 아니라
    Ingest / Archive -> Collection / Compare가 "이 둘은 같은 ROM"이라고 믿고 쓰는 관계
    데이터이므로, 엔진이 근거를 대지 못한 연결이 같은 테이블에 섞이면 나중에 그 링크가
    어디서 왔는지 데이터만 보고 설명할 수 없다.

    정말로 근거 없이 잇고 싶을 때는 `manual=True`를 명시해야 하고, 그때는 티어가
    `manual`로 남는다 - 엔진 판정 결과와 사람의 단언을 데이터에서 구분하기 위함이다.

    티어/점수는 **후보 목록에 있던 값을 그대로 기록한다.** 여기서 classify()를 다시
    부르면 Metadata/Heuristic으로 걸린 후보가 전부 "근거 없음"으로 기록된다 -
    classify()는 앞쪽 두 티어(Exact/Normalized)만 판정하기 때문이다.
    """
    identity = archive.get_identity(rom_identity_id)
    if identity is None:
        raise KeyError("Archive 항목을 찾을 수 없습니다.")
    if identity["system"] != row["system"]:
        raise ValueError("System이 다른 항목끼리는 Match할 수 없습니다.")

    chosen = next((c for c in candidates_for(archive, collection_id, row)["candidates"]
                   if c["romIdentityId"] == rom_identity_id), None)
    if chosen is None:
        if not manual:
            raise ValueError("후보 목록에 없는 항목입니다. 강제로 연결하려면 "
                             "수동 연결(manual)로 지정해야 합니다.")
        tier, score = engine.TIER_MANUAL, 0.0
    else:
        tier, score = chosen["tier"], chosen["score"]

    archive.put_match_link(collection_id, row["system"], row["filename"],
                           rom_identity_id, tier=tier, score=score)
    return {"romIdentityId": rom_identity_id, "tier": tier, "score": score,
            "manual": chosen is None}


def clear_match(archive, collection_id, row) -> bool:
    return archive.delete_match_link(collection_id, row["system"], row["filename"])
