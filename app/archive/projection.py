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

import os
import shutil
import time
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
    timings = {"resolveSeconds": 0.0, "mediaSeconds": 0.0,
               "mediaLookupSeconds": 0.0, "writeIndexSeconds": 0.0}
    for system, items in by_system.items():
        layout = adapter.layout(collection, system)
        Path(layout.metadata_file).parent.mkdir(parents=True, exist_ok=True)
        batch = []
        for rid, identity in items:
            if progress_cb:
                progress_cb(entries, max(1, total), f"{system} · {identity['filename']}")
            filename = identity["filename"] or identity["filename_norm"]
            stage_started = time.perf_counter()
            fields, raw = archive.resolve_fields(rid)
            timings["resolveSeconds"] += time.perf_counter() - stage_started
            if not archive.metadata_is_cleared(rid):
                batch.append(GameEntry(
                    filename=filename, fields=fields,
                    frontend_raw=raw if adapter.raw_is_mine(raw) else {}))
            if cfg["mediaInternal"]:
                stage_started = time.perf_counter()
                got, lost = _copy_media(archive, adapter, layout, rid, filename, fields,
                                        overwrite=(overwrite_media or {}).get(rid, ()),
                                        timings=timings)
                timings["mediaSeconds"] += time.perf_counter() - stage_started
                copied += got
                missing += lost
            entries += 1
        stage_started = time.perf_counter()
        adapter.write_index(layout, batch)
        timings["writeIndexSeconds"] += time.perf_counter() - stage_started
        if progress_cb:
            progress_cb(entries, max(1, total), f"{system} · gamelist 저장")
    if progress_cb:
        progress_cb(total, max(1, total), "완료")
    return {"entries": entries, "mediaCopied": copied, "mediaMissing": missing,
            "systems": len(by_system),
            "timings": {key: round(value, 3) for key, value in timings.items()}}


def snapshot_revision_media(archive, config, record_ids, *, progress_cb=None) -> int:
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
    ids = list(record_ids or [])
    if progress_cb:
        progress_cb(0, max(1, len(ids)), "Revision 미디어 확인")
    for index, record_id in enumerate(ids):
        if progress_cb:
            progress_cb(index, max(1, len(ids)), f"Revision {record_id}")
        for media in archive.media_of_revision(record_id):
            # copy2 자체는 운영체제 호출이라 중간에 끊을 수 없지만, 파일 사이에는
            # 반드시 취소 요청을 확인한다.
            if progress_cb:
                progress_cb(index, max(1, len(ids)), media.get("media_type") or "미디어")
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
        if progress_cb:
            progress_cb(index + 1, max(1, len(ids)), f"Revision {record_id}")
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
    def consider(source_id, ref, updated_at=0):
        item = {**ref, "source_collection_id": source_id,
                "updated_at": ref.get("updated_at", updated_at)}
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

    for source_id, record in by_source.items():
        snapshot = archive.media_of_revision(record["record_id"])
        refs = ([m for m in snapshot if m.get("state", "present") == "present"]
                if snapshot else refs_by_source.get(source_id, []))
        for ref in refs:
            consider(source_id, ref, record.get("updated_at", 0))
    # Compatibility/direct edits can have a media reference before they have a
    # matching revision (legacy import and a just-pasted Archive-owned file).
    for source_id, refs in refs_by_source.items():
        if source_id in by_source:
            continue
        for ref in refs:
            consider(source_id, ref)
    for media_type in cleared:
        latest.pop(media_type, None)
    return latest


def _copy_media(archive, adapter, layout, rid, filename, fields, *, overwrite=(),
                timings=None) -> tuple[int, int]:
    """없는 것만 복사한다. `overwrite`에 든 media type은 이미 있어도 덮어쓴다(사용자가
    직접 바꾼 그림을 Frontend 트리에 반영할 때)."""
    title = (fields.get("name") or "").strip() or Path(filename).stem
    copied = missing = 0
    lookup_started = time.perf_counter()
    media = effective_media(archive, rid)
    if timings is not None:
        timings["mediaLookupSeconds"] += time.perf_counter() - lookup_started
    for media_type, ref in media.items():
        mf = MediaFile(media_type=media_type, path=ref["abs_path"], size=ref["size"])
        for src, dest in adapter.media_pairs(layout, filename, [mf], title=title):
            dest_path = Path(dest)
            # An Archive read commonly records the frontend file itself as the
            # source.  Comparing paths lexically avoids two remote stat calls
            # (and resolve()) for every already-in-place media file.
            if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dest)):
                continue
            # A remote path check can cost tens of milliseconds.  stat each
            # distinct source/destination once instead of exists(), resolve(),
            # then stat() again for every already-copied file.
            try:
                src_stat = Path(src).stat()
            except OSError:
                missing += 1
                continue
            try:
                dest_stat = dest_path.stat()
            except OSError:
                dest_stat = None
            if dest_stat is not None:
                if (media_type not in overwrite and src_stat.st_size == dest_stat.st_size
                        and src_stat.st_mtime_ns == dest_stat.st_mtime_ns):
                    continue
                try:
                    if os.path.samefile(src, dest):
                        continue
                except OSError:
                    pass
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_path)
            copied += 1
    return copied, missing
