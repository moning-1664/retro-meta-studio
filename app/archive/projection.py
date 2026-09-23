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


def project(archive, config, rom_identity_ids=None, *, overwrite_media=None, progress_cb=None) -> dict:
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

    total = sum(len(items) for items in by_system.values())
    entries = copied = missing = 0
    for system, items in by_system.items():
        if progress_cb:
            progress_cb(entries, total, system)
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
                got, lost = _copy_media(archive, adapter, layout, rid, filename, fields,
                                        overwrite=(overwrite_media or {}).get(rid, ()))
                copied += got
                missing += lost
        adapter.write_index(layout, batch)
        entries += len(batch)
    return {"entries": entries, "mediaCopied": copied, "mediaMissing": missing,
            "systems": len(by_system)}


def snapshot_revision_media(archive, config, record_ids) -> int:
    """Keep immutable media copies for new revisions when Archive owns media.

    The normal frontend media tree holds the currently resolved image. Revision
    history uses private files under ``.rms/revision-media`` so a later export
    replacing that frontend image cannot rewrite an older revision.
    """
    cfg = normalize_config(config)
    if not cfg["mediaInternal"] or not cfg["archiveDir"]:
        return 0
    root = Path(cfg["archiveDir"]) / ".rms" / "revision-media"
    copied = 0
    for record_id in record_ids or []:
        for media in archive.media_of_revision(record_id):
            if media.get("state", "present") != "present":
                continue
            source = Path(media["abs_path"])
            if not source.is_file():
                continue
            suffix = source.suffix
            destination = root / str(record_id) / f"{media['media_type']}{suffix}"
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                copied += 1
            archive.update_revision_media_path(record_id, media["media_type"], destination)
    return copied


def effective_media(archive, rid) -> dict[str, dict]:
    """Resolve one Media item per type using the selected/latest source Revision.

    Revision snapshots keep historical media paths; ``archive_media`` remains
    the compatibility index for the latest path from each source.
    """
    preferred = archive.get_preferred(rid)
    edited = archive.latest_record(rid, "__archive__")
    cleared = {m["media_type"] for m in archive.media_of_revision(edited["record_id"])
               if m.get("state") == "cleared"} if edited else set()
    latest_records = archive.sources_of(rid)
    by_source = {r["source_collection_id"]: r for r in latest_records}
    if preferred:
        by_source[preferred["source_collection_id"]] = preferred
    current_refs = archive.media_refs(rid)
    refs_by_source: dict[str, list[dict]] = {}
    for ref in current_refs:
        refs_by_source.setdefault(ref["source_collection_id"], []).append(ref)

    latest: dict[str, dict] = {}
    for source_id, record in by_source.items():
        snapshot = archive.media_of_revision(record["record_id"])
        refs = ([m for m in snapshot if m.get("state", "present") == "present"]
                if snapshot else refs_by_source.get(source_id, []))
        for ref in refs:
            item = {**ref, "source_collection_id": source_id,
                    "updated_at": ref.get("updated_at", record.get("updated_at", 0))}
            current = latest.get(item["media_type"])
            rank = (source_id == "__archive__",
                    source_id == (preferred["source_collection_id"] if preferred else None),
                    item["updated_at"])
            cur_rank = ((current.get("source_collection_id") == "__archive__"),
                        current.get("source_collection_id") ==
                        (preferred["source_collection_id"] if preferred else None),
                        current.get("updated_at", 0)) if current else None
            if current is None or rank >= cur_rank:
                latest[item["media_type"]] = item
    for media_type in cleared:
        latest.pop(media_type, None)
    return latest


def _copy_media(archive, adapter, layout, rid, filename, fields, *, overwrite=()) -> tuple[int, int]:
    """없는 것만 복사한다. `overwrite`에 든 media type은 이미 있어도 덮어쓴다(사용자가
    직접 바꾼 그림을 Frontend 트리에 반영할 때)."""
    title = (fields.get("name") or "").strip() or Path(filename).stem
    copied = missing = 0
    for media_type, ref in effective_media(archive, rid).items():
        mf = MediaFile(media_type=media_type, path=ref["abs_path"], size=ref["size"])
        for src, dest in adapter.media_pairs(layout, filename, [mf], title=title):
            dest_path = Path(dest)
            if not Path(src).exists():
                missing += 1
                continue
            if dest_path.exists() and Path(src).resolve() == dest_path.resolve():
                continue
            if dest_path.exists() and media_type not in overwrite:
                try:
                    src_stat, dest_stat = Path(src).stat(), dest_path.stat()
                    if src_stat.st_size == dest_stat.st_size and src_stat.st_mtime_ns == dest_stat.st_mtime_ns:
                        continue
                except OSError:
                    pass
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_path)
            copied += 1
    return copied, missing
