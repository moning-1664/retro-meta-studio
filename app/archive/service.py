"""
app/archive/service.py
=======================
Collection과 Archive 사이의 오가는 동작.

**Archive는 Canonical Source가 아니다**(스펙 §37, §92). 여러 Collection에서 모은
Metadata와 Identity를 출처와 함께 보관할 뿐이고, 실제 파일의 진실은 언제나 파일
시스템이다.

가장 중요한 규칙: **Archive에서 수정해도 Collection은 자동으로 바뀌지 않는다**(§40).
반영하려면 사용자가 명시적으로 Archive → Collection을 실행해야 한다.

## Archive → Collection이 두 갈래인 이유

- 대상 Collection에 그 ROM이 **이미 있으면** 바뀌는 것은 메타데이터뿐이다. 바이트가
  움직이지 않으므로 Plan을 거치지 않고 바로 파일에 쓴다(결정 D1).
- **없으면** ROM과 Media를 실제로 복사해야 하므로 용량이 변한다. 이건 Plan으로 간다.

이 구분은 D1("Plan은 바이트가 움직이는 작업만")을 그대로 따른 것이다.
"""

from __future__ import annotations

from pathlib import Path

from adapters import get_adapter
from app.archive import conflicts as conflict_service
from app.match import service as match_service
from app.store.archive import ARCHIVE_EDIT_SOURCE
from adapters.base import GameEntry
from utils import normalize_title


def _identity_of(row) -> tuple[str, str]:
    """(표시용 제목, 매칭용 정규화 제목). 제목이 없으면 파일명 stem을 쓴다."""
    title = (row.get("title") or "").strip() or Path(row["filename"]).stem
    return title, normalize_title(title)


SCOPE_ALL = "all"
SCOPE_SYSTEM = "system"
SCOPE_SELECTED = "selected"


def resolve_scope(cache, scope) -> tuple[str, list[int]]:
    """수집 대상을 **명시적으로** 정한다. 반환: (scope_kind, rom_uids)

    `scope`는 `{"kind": "all" | "system" | "selected", ...}` 형태다.

    예전에는 `rom_uids=None`이 "Collection 전체"를 뜻했다. 그래서 사용자가
    Navigation에서 MSX1을 고르고 아무 게임도 선택하지 않은 채 수집을 누르면, 화면에는
    MSX1만 보이는데 Collection 전체가 Archive로 들어갔다. **화면에서 고른 대상과 실제
    작업 대상이 달라지는 것**이 문제의 본질이므로, 여기서는 무엇을 대상으로 삼는지
    추측하지 않고 호출부가 준 scope를 그대로 해석한다.
    """
    kind = (scope or {}).get("kind") or SCOPE_ALL
    if kind == SCOPE_SELECTED:
        uids = [int(u) for u in (scope.get("romUids") or [])]
    elif kind == SCOPE_SYSTEM:
        system = scope.get("system")
        uids = [r["rom_uid"] for r in cache.query_rows(systems=[system])] if system else []
    else:
        kind = SCOPE_ALL
        uids = [r["rom_uid"] for r in cache.query_rows()]
    return kind, uids


def ingest_collection(archive, collection, cache, rom_uids=None, *, retention=None,
                      progress_cb=None) -> dict:
    """Collection의 항목을 Archive에 수집한다(스펙 §42).

    `rom_uids`는 **반드시 주어져야 한다** - 대상은 호출부가 `resolve_scope()`로 확정해
    넘긴다. 여기서 `None`을 "전체"로 해석하지 않는다.

    출처는 Collection 이름이 아니라 ID로 기록한다 - 이름이 바뀌어도 관계가 유지되어야
    한다(§38). 같은 내용을 다시 넣으면 Revision을 만들지 않는다(§39).
    """
    if rom_uids is None:
        rom_uids = [r["rom_uid"] for r in cache.query_rows()]
    rows = [cache.get_row(int(uid)) for uid in rom_uids]
    rows = [r for r in rows if r is not None]

    total = len(rows)
    ingested = revised = 0
    identity_ids: list[str] = []
    for index, row in enumerate(rows, start=1):
        if progress_cb:
            progress_cb(index, total, row["filename"])
        title, title_norm = _identity_of(row)
        # 사용자가 확정해 둔 Match가 있으면 새 Identity를 만들지 않고 그쪽에 붙인다
        # (§49). 이름이 달라서 자동으로는 못 붙는 항목을 사람이 이어준 결과이므로,
        # 다시 Ingest할 때마다 갈라지면 그 선택이 매번 무의미해진다.
        rom_identity_id = match_service.linked_identity(archive, collection.id, row)
        if rom_identity_id is None:
            game_id = archive.ensure_game(title, title_norm)
            rom_identity_id = archive.ensure_rom_identity(
                game_id, row["system"], normalize_title(Path(row["filename"]).stem),
                filename=row["filename"], size=row["size"] or None,
                sha256=row["sha256"], region=(row["fields"] or {}).get("region") or None,
                title=title)

        identity_ids.append(rom_identity_id)
        kwargs = {"retention": retention} if retention else {}
        _revision, created = archive.put_record(
            rom_identity_id, collection.id, row["fields"], row["frontend_raw"],
            media=row["media"], **kwargs)
        ingested += 1
        revised += 1 if created else 0

        # 파일은 복제하지 않고 원본 위치만 기록한다(§37, D3).
        adapter = get_adapter(collection.frontend)
        layout = adapter.layout(collection, row["system"])
        if row["present"]:
            archive.put_rom_source(rom_identity_id, collection.id,
                                   Path(layout.rom_dir) / row["filename"], row["size"] or 0)
        for media in row["media"]:
            archive.put_media_ref(rom_identity_id, media["media_type"], collection.id,
                                  media["rel_path"], media["size"] or 0)

    return {"ingested": ingested, "revised": revised,
            "unchanged": ingested - revised, "sourceCollectionId": collection.id,
            # 화면에서 고른 대상과 실제로 들어간 대상이 같은지 확인할 수 있어야 한다.
            "ingestedRomUids": [r["rom_uid"] for r in rows],
            "romIdentityIds": identity_ids}


def detail(archive, rom_identity_id) -> dict | None:
    """Archive 항목 하나의 상세. 출처별 Metadata를 함께 준다(§44).

    표시용 `fields`는 `archive.resolve_fields()`와 **같은 규칙**을 쓴다 - 사용자가 Archive에서
    직접 고친 값이 있으면 그것이 이긴다(§40). 여기서만 "가장 최근 출처"를 쓰면,
    편집한 값이 화면에는 안 보이는데 Archive->Collection으로는 그 값이 나가는
    불일치가 생긴다.

    `sources`는 실제 Collection 출처만 담는다 - 사용자가 직접 고친 기록은 Collection이
    아니므로 출처 비교(§44) 목록에 섞이면 안 되고, `edited` 플래그로만 알린다.
    """
    identity = archive.get_identity(rom_identity_id)
    if identity is None:
        return None
    sources = [s for s in archive.sources_of(rom_identity_id)
               if s["source_collection_id"] != ARCHIVE_EDIT_SOURCE]
    fields, frontend_raw = archive.resolve_fields(rom_identity_id)
    preferred = archive.get_preferred(rom_identity_id)
    return {
        "romIdentityId": rom_identity_id,
        "gameId": identity["game_id"],
        "system": identity["system"],
        "filename": identity["filename"] or identity["filename_norm"],
        "title": identity["title"],
        "region": identity["region"],
        "size": identity["size"],
        "sha256": identity["sha256"],
        "fields": fields,
        "frontendRaw": frontend_raw,
        "edited": archive.latest_record(rom_identity_id, ARCHIVE_EDIT_SOURCE) is not None,
        "preferredRecordId": preferred["record_id"] if preferred else None,
        # `recordId`가 있어야 화면에서 "이 Revision을 우선 쓴다"를 지정할 수 있다.
        # 없으면 별표를 걸 대상을 가리킬 방법이 없다.
        "sources": [
            {"recordId": s["record_id"], "collectionId": s["source_collection_id"],
             "revision": s["revision"], "updatedAt": s["updated_at"], "fields": s["fields"]}
            for s in sources
        ],
        "media": archive.media_refs(rom_identity_id),
        "romSources": archive.rom_sources(rom_identity_id),
        # **같은 내용은 한 줄로 묶어서 준다**(실사용 피드백 - "Revision에 동일 버젼이 같이 보인다").
        # 출처가 둘이어도 내용이 같으면 고를 이유가 없다 - 실제로 다른 것만 골라야 뜻이 있다.
        "versions": conflict_service.versions_of(archive, rom_identity_id),
    }


def set_preferred(archive, rom_identity_id, record_id) -> dict:
    """사용자가 특정 Revision을 Preferred로 지정한다(§8).

    Revision 내용 자체는 바뀌지 않는다 - 이후 조회에서 우선적으로 골라 쓸 뿐이다.
    """
    archive.set_preferred(rom_identity_id, record_id)
    return {"romIdentityId": rom_identity_id, "preferredRecordId": record_id}


def clear_preferred(archive, rom_identity_id) -> dict:
    cleared = archive.clear_preferred(rom_identity_id)
    return {"romIdentityId": rom_identity_id, "cleared": cleared}


def edit(archive, rom_identity_id, fields) -> dict:
    """Archive의 Metadata를 직접 고친다(§40).

    **Collection에는 반영하지 않는다.** 사용자가 Archive → Collection을 명시적으로
    실행해야 한다. 그래서 출처를 실제 Collection ID가 아니라 "Archive에서 직접 편집"을
    뜻하는 고정 값으로 남긴다 - 어느 Collection에서 온 값인지와 사용자가 손댄 값이
    섞이면 출처 추적(§38)이 의미를 잃는다.
    """
    identity = archive.get_identity(rom_identity_id)
    if identity is None:
        raise KeyError("Archive 항목을 찾을 수 없습니다.")
    revision, created = archive.put_record(rom_identity_id, ARCHIVE_EDIT_SOURCE, fields)
    return {"revision": revision, "changed": created}


def to_collection(archive, collection, cache, provider, rom_identity_ids) -> dict:
    """Archive 항목을 대상 Collection으로 보낸다(§41, Scenario 8).

    반환: {"updated": n, "items": [...], "skipped": [...]}
    - updated: 대상에 이미 있어서 메타데이터만 즉시 반영한 항목 수(D1 - Plan 미경유)
    - items:   대상에 없어서 Plan에 올려야 하는 항목들(plan_add가 기대하는 형태)
    - skipped: 원본 파일을 찾을 수 없어 가져올 수 없는 항목들
    """
    adapter = get_adapter(collection.frontend)
    index = {(r["system"], r["filename"]): r["rom_uid"] for r in cache.query_rows()}

    updated, items, skipped = 0, [], []
    for rom_identity_id in rom_identity_ids:
        identity = archive.get_identity(rom_identity_id)
        if identity is None:
            continue
        system = identity["system"]
        filename = identity["filename"] or identity["filename_norm"]
        fields, frontend_raw = archive.resolve_fields(rom_identity_id)

        rom_uid = index.get((system, filename))
        row = cache.get_row(rom_uid) if rom_uid is not None else None

        if row is not None:
            # Metadata는 바이트가 움직이지 않으므로 바로 파일에 쓴다(D1).
            layout = adapter.layout(collection, system)
            merged = {**(row["fields"] or {}), **fields}
            # Archive의 frontend_raw는 그것을 올린 Collection의 것이라, 대상이 다른
            # Frontend면 모양이 맞지 않아 되살릴 수 없다. 대상에 이미 있는 값이
            # 있으면 그쪽을 쓰고, 없으면 내 것일 때만 가져온다.
            existing_raw = row["frontend_raw"] if row else None
            candidate = existing_raw or frontend_raw
            preserved = candidate if adapter.raw_is_mine(candidate) else {}
            adapter.write_index(layout, [GameEntry(filename=filename, fields=merged,
                                                   frontend_raw=preserved)])
            title = (merged.get("name") or "").strip() or Path(filename).stem
            cache.update_metadata(rom_uid, merged, title=title, title_norm=normalize_title(title))
            updated += 1

        # **Metadata와 파일은 독립적으로 다룬다.** gamelist에는 항목이 있는데 ROM이
        # 없는 상태(ES-DE에서 흔하다)라면, 메타데이터를 갱신하면서 동시에 빠진 ROM을
        # 가져와야 한다. "이미 있는 항목"으로 뭉뚱그리면 그 경우를 영영 못 채운다.
        need_rom = row is None or not row["present"]
        have_media = {m["media_type"] for m in (row["media"] if row else [])}

        rom = None
        if need_rom:
            rom = next((s for s in archive.rom_sources(rom_identity_id)
                        if provider.exists(s["abs_path"])), None)
        media = [{"type": m["media_type"], "path": m["abs_path"], "size": m["size"]}
                 for m in archive.media_refs(rom_identity_id)
                 if m["media_type"] not in have_media and provider.exists(m["abs_path"])]

        if rom is None and not media:
            if row is None:
                # 메타데이터만 남고 실제 파일 출처가 전부 사라진 경우다. 조용히 넘기지
                # 않고 무엇이 빠졌는지 알린다(D3와 같은 태도).
                skipped.append({"filename": filename, "reason": "원본 파일을 찾을 수 없습니다."})
            continue

        items.append({
            "system": system, "filename": filename,
            "rom": {"path": rom["abs_path"], "size": rom["size"]} if rom else None,
            "media": media, "fields": fields, "frontend_raw": frontend_raw,
        })

    return {"updated": updated, "items": items, "skipped": skipped}
