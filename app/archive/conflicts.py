"""
app/archive/conflicts.py
=========================
Archive 안에서 **같은 ROM에 서로 다른 버전이 있을 때만** 알려 주는 계산.

사용자 결정(2026-09-17/20):
- Matching(=충돌 표시)은 Archive에서만 나온다. Collection 쪽은 관여하지 않는다.
- "다르다"의 기준은 **Title + Description + 주요 Media(cover/screenshot)** 뿐이다.
  Players/장르/발매년도 같은 덜 중요한 값이 다른 것은 무시하고 기존 값을 유지한다.
- 한쪽이 비어 있고 다른 쪽에만 값이 있으면 충돌이 아니라 **채워 주는 같은 버전**이다.
- 버전이 둘 이상이면 `[n]`로 알리고, 하나를 고르면(Preferred) 표시가 사라진다.

Archive 디렉토리를 다시 보면 같은 Identity에 같은 Collection의 Revision이 여럿 있을 수
있는데, 출처(Collection)마다 **최신 Revision 하나**만 비교한다 - 옛 Revision은 이력이지
현재 상태가 아니다.
"""

from __future__ import annotations

import json

from app.store.archive import ARCHIVE_EDIT_SOURCE

#: 버전을 가르는 Metadata 필드.
IMPORTANT_FIELDS = ("name", "desc")
#: 버전을 가르는 Media. 크기가 다르면 다른 그림으로 본다(같은 파일의 복사본은 크기가 같다).
IMPORTANT_MEDIA = ("covers", "screenshots")


def _norm(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def _signature(fields, media) -> dict:
    sig = {k: _norm(fields.get(k)) for k in IMPORTANT_FIELDS if _norm(fields.get(k))}
    for media_type, size in media.items():
        sig[f"media:{media_type}"] = size
    return sig


def _compatible(a: dict, b: dict) -> bool:
    """겹치는 항목이 모두 같으면 같은 버전이다. 한쪽에만 있는 항목은 상관없다."""
    return all(a[k] == b[k] for k in a.keys() & b.keys())


def cluster(entries: list[dict]) -> list[dict]:
    """출처별 항목을 버전으로 묶는다. entries: {recordId, source, updatedAt, fields, media}"""
    clusters: list[dict] = []
    for entry in sorted(entries, key=lambda e: -e["updatedAt"]):
        sig = _signature(entry["fields"], entry["media"])
        for c in clusters:
            if all(_compatible(sig, s) for s in c["_sigs"]):
                c["_sigs"].append(sig)
                c["recordIds"].append(entry["recordId"])
                c["sources"].append(entry["source"])
                # 비어 있던 값은 다른 출처가 채워 준다.
                for k, v in entry["fields"].items():
                    if v and not c["fields"].get(k):
                        c["fields"][k] = v
                for t, size in entry["media"].items():
                    c["media"].setdefault(t, size)
                break
        else:
            clusters.append({"_sigs": [sig], "recordIds": [entry["recordId"]],
                             "sources": [entry["source"]], "fields": dict(entry["fields"]),
                             "media": dict(entry["media"]), "updatedAt": entry["updatedAt"]})
    for c in clusters:
        del c["_sigs"]
    return clusters


def _load(archive, *, systems=None, rom_identity_ids=None):
    """조건에 맞는 Identity의 (출처별 최신 Revision, 주요 Media)를 **한 번에** 읽는다.

    Identity마다 조회하면 System 하나에 수천 건일 때 화면이 멈춘다(실사용 피드백 -
    충돌이 있는 System의 로딩이 매우 느렸다)."""
    conn = archive._conn
    where, params = [], []
    if systems:
        where.append(f"i.system IN ({','.join('?' * len(systems))})")
        params.extend(systems)
    if rom_identity_ids:
        where.append(f"i.rom_identity_id IN ({','.join('?' * len(rom_identity_ids))})")
        params.extend(rom_identity_ids)
    cond = (" AND " + " AND ".join(where)) if where else ""

    records: dict[str, list[dict]] = {}
    sql = ("SELECT r.record_id, r.rom_identity_id, r.source_collection_id, r.updated_at,"
           "       r.fields_json"
           " FROM archive_records r"
           " JOIN rom_identities i ON i.rom_identity_id = r.rom_identity_id"
           " JOIN (SELECT rom_identity_id, source_collection_id, MAX(revision) AS rev"
           "         FROM archive_records GROUP BY rom_identity_id, source_collection_id) m"
           "   ON m.rom_identity_id = r.rom_identity_id"
           "  AND m.source_collection_id = r.source_collection_id AND m.rev = r.revision"
           f" WHERE 1=1{cond}")
    for row in conn.execute(sql, params):
        records.setdefault(row["rom_identity_id"], []).append(row)

    media: dict[int, dict[str, int]] = {}
    msql = ("SELECT rm.record_id,rm.media_type,rm.size FROM archive_record_media rm"
            " JOIN archive_records r ON r.record_id=rm.record_id"
            " JOIN rom_identities i ON i.rom_identity_id=r.rom_identity_id"
            f" WHERE rm.media_type IN ({','.join('?' * len(IMPORTANT_MEDIA))}){cond}")
    for row in conn.execute(msql, [*IMPORTANT_MEDIA, *params]):
        media.setdefault(int(row["record_id"]), {})[row["media_type"]] = int(row["size"] or 0)

    # Older callers and imported archives can add the compatibility reference
    # after creating the revision.  Use it only when that revision has no
    # immutable snapshot for the same type.
    refs_sql = ("SELECT r.record_id,a.media_type,a.size FROM archive_records r"
                " JOIN (SELECT rom_identity_id,source_collection_id,MAX(revision) AS rev"
                "         FROM archive_records GROUP BY rom_identity_id,source_collection_id) m"
                "   ON m.rom_identity_id=r.rom_identity_id"
                "  AND m.source_collection_id=r.source_collection_id AND m.rev=r.revision"
                " JOIN archive_media a ON a.rom_identity_id=r.rom_identity_id"
                "  AND a.source_collection_id=r.source_collection_id"
                " JOIN rom_identities i ON i.rom_identity_id=r.rom_identity_id"
                f" WHERE a.media_type IN ({','.join('?' * len(IMPORTANT_MEDIA))}){cond}")
    for row in conn.execute(refs_sql, [*IMPORTANT_MEDIA, *params]):
        media.setdefault(int(row["record_id"]), {}).setdefault(
            row["media_type"], int(row["size"] or 0))

    resolved = {r[0] for r in conn.execute("SELECT rom_identity_id FROM preferred_revisions")}
    return records, media, resolved


def _entries(rid, rows, media) -> list[dict]:
    return [{"recordId": r["record_id"], "source": r["source_collection_id"],
             "updatedAt": r["updated_at"], "fields": json.loads(r["fields_json"]),
             "media": media.get(int(r["record_id"]), {})}
            for r in rows if r["source_collection_id"] != ARCHIVE_EDIT_SOURCE]


def conflict_counts(archive, *, systems=None, rom_identity_ids=None) -> dict[str, int]:
    """{rom_identity_id: 버전 수}. **버전이 둘 이상이고 아직 고르지 않은 것만** 담는다."""
    records, media, resolved = _load(archive, systems=systems, rom_identity_ids=rom_identity_ids)
    out = {}
    for rid, rows in records.items():
        if rid in resolved or len(rows) < 2:
            continue
        # 사용자가 Archive에서 직접 고친 값이 있으면 그것이 확정이다.
        if any(r["source_collection_id"] == ARCHIVE_EDIT_SOURCE for r in rows):
            continue
        n = len(cluster(_entries(rid, rows, media)))
        if n > 1:
            out[rid] = n
    return out


def versions_of(archive, rom_identity_id) -> list[dict]:
    """한 Identity의 버전 목록(고르기용). 버전이 하나여도 그대로 돌려준다."""
    records, media, _ = _load(archive, rom_identity_ids=[rom_identity_id])
    rows = records.get(rom_identity_id, [])
    return cluster(_entries(rom_identity_id, rows, media))
