"""
app/archive/projection.py
==========================
Archive를 **사용자가 정한 디렉토리에 사용자가 정한 Frontend 형식으로** 써 둔다.

설계는 docs/ARCHIVE_DIRECTORY_DESIGN.md. 핵심은 한 가지다 - archive.db는 Revision과
출처를 관리하는 색인이고, 사용자가 열어 보고 그대로 쓸 수 있는 **완전한 Frontend
트리**는 이 디렉토리다. 트리가 부분적이면(일부 System의 gamelist가 비어 있는 식)
"Archive에 넣었는데 꺼내 쓸 수 없다"가 된다.

gamelist/media는 Frontend Adapter가 쓴다 - Collection에 쓰는 코드와 같은 경로라서
형식이 갈라지지 않는다. media는 **없는 것만** 복사한다(성능).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from adapters import get_adapter
from adapters.base import GameEntry, MediaFile
from app.model.collection import (Collection, StorageLocation, STORAGE_INTERNAL)

#: 투영용 Collection의 ID. 실제 Collection이 아니다(registry에 없다).
PROJECTION_ID = "__archive_projection__"

DEFAULT_CONFIG = {"frontend": "es-de", "archiveDir": "", "romDir": "", "mediaInternal": True}


def normalize_config(raw) -> dict:
    """저장된 설정을 기본값과 합치고 문자열을 정리한다."""
    cfg = {**DEFAULT_CONFIG, **(raw or {})}
    cfg["frontend"] = str(cfg["frontend"] or "es-de")
    cfg["archiveDir"] = str(cfg["archiveDir"] or "").strip()
    cfg["romDir"] = str(cfg["romDir"] or "").strip()
    cfg["mediaInternal"] = bool(cfg["mediaInternal"])
    return cfg


def is_configured(config) -> bool:
    return bool(normalize_config(config)["archiveDir"])


def collection_for(config) -> Collection:
    """Archive 디렉토리를 Collection처럼 다루기 위한 값 객체."""
    cfg = normalize_config(config)
    root = cfg["archiveDir"]
    return Collection(
        id=PROJECTION_ID, name="Archive", frontend=cfg["frontend"], root_path=root,
        storages=[StorageLocation(STORAGE_INTERNAL, STORAGE_INTERNAL, "Archive", root)])


def project(archive, config, rom_identity_ids=None) -> dict:
    """Archive의 (resolve된) 메타데이터와 media를 디렉토리에 쓴다.

    `rom_identity_ids=None`이면 전체. gamelist는 System 단위로 **한 번만** 쓴다 -
    항목마다 열고 쓰면 System 크기의 제곱만큼 느려진다(Adapter 계약 1).
    반환: {"entries": n, "mediaCopied": n, "mediaMissing": n, "systems": n}
    """
    cfg = normalize_config(config)
    if not cfg["archiveDir"]:
        raise ValueError("Archive 디렉토리가 설정되지 않았습니다.")
    collection = collection_for(cfg)
    adapter = get_adapter(cfg["frontend"])

    if rom_identity_ids is None:
        rom_identity_ids = [r["rom_identity_id"] for r in archive.list_rows(limit=None)]

    by_system: dict[str, list] = {}
    for rid in rom_identity_ids:
        identity = archive.get_identity(rid)
        if identity is None:
            continue
        by_system.setdefault(identity["system"], []).append((rid, identity))

    entries = copied = missing = 0
    for system, items in by_system.items():
        layout = adapter.layout(collection, system)
        Path(layout.metadata_file).parent.mkdir(parents=True, exist_ok=True)
        batch = []
        for rid, identity in items:
            filename = identity["filename"] or identity["filename_norm"]
            fields, raw = archive.resolve_fields(rid)
            batch.append(GameEntry(
                filename=filename, fields=fields,
                frontend_raw=raw if adapter.raw_is_mine(raw) else {}))
            if cfg["mediaInternal"]:
                got, lost = _copy_media(archive, adapter, layout, rid, filename, fields)
                copied += got
                missing += lost
        adapter.write_index(layout, batch)
        entries += len(batch)
    return {"entries": entries, "mediaCopied": copied, "mediaMissing": missing,
            "systems": len(by_system)}


def _copy_media(archive, adapter, layout, rid, filename, fields) -> tuple[int, int]:
    refs = archive.media_refs(rid)
    # 같은 type이 여러 출처에서 오면 가장 최근 것 하나만 쓴다.
    # 사용자가 버전을 골랐으면(Preferred) 그 출처의 media를 우선한다 - 메타데이터만
    # 고른 버전이고 그림은 다른 버전 것이면 고른 의미가 없다.
    preferred = archive.get_preferred(rid)
    chosen = preferred["source_collection_id"] if preferred else None
    latest: dict[str, dict] = {}
    for ref in refs:
        cur = latest.get(ref["media_type"])
        rank = (ref["source_collection_id"] == chosen, ref["updated_at"])
        if cur is None or rank >= (cur["source_collection_id"] == chosen, cur["updated_at"]):
            latest[ref["media_type"]] = ref
    files = [MediaFile(media_type=t, path=r["abs_path"], size=r["size"])
             for t, r in latest.items()]
    title = (fields.get("name") or "").strip() or Path(filename).stem
    copied = missing = 0
    for src, dest in adapter.media_pairs(layout, filename, files, title=title):
        dest_path = Path(dest)
        if dest_path.exists():
            continue
        if not Path(src).exists():
            missing += 1
            continue
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_path)
        copied += 1
    return copied, missing
