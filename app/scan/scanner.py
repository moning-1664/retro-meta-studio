"""
app/scan/scanner.py
====================
Collection을 훑어 Cache DB에 눕히는 증분 스캐너.

이전 프로젝트의 스캐너에서 가져온 핵심은 **시그니처로 시스템을 통째로 건너뛰기**다.
ROM이 1,000개인 시스템에서 gamelist.xml을 매번 다시 파싱하고 행을 다시 만드는 대신,
값싼 시그니처만 비교해서 "이 시스템은 변경 없음"이면 넘어간다.

달라진 점은 넷이다.
- 결과가 런타임 메모리가 아니라 Cache DB에 남는다. 그래서 앱을 다시 켜도 Full Scan을
  하지 않는다(스펙 §63).
- 파일시스템 접근은 전부 StorageProvider를 통한다. MTP를 나중에 끼워넣기 위해서다.
- Frontend의 경로 규칙을 스캐너가 모른다. 전부 Adapter가 계산한다.
- 시그니처가 디렉터리 mtime이 아니라 내용 지문이다 - 이유는 `_dir_fingerprint()` 참고.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.model.collection import STORAGE_INTERNAL
from utils import normalize_title

#: 스캔 결과 구조가 바뀌면 올린다. 캐시에 기록된 값과 다르면 전부 다시 스캔한다.
SCAN_VERSION = 1


def _sig_covers(cached_types, wanted_types) -> bool:
    """캐시가 이번에 요청한 media 타입을 실제로 커버하는지.

    커버(covers)만 인덱싱해둔 캐시를 "이미 다 됐다"고 재사용하면, 전체를 요청한
    다음 단계가 비디오를 영영 못 보게 된다.
    """
    if wanted_types is None:
        return cached_types is None
    if cached_types is None:
        return True
    return set(wanted_types).issubset(set(cached_types))


def _dir_fingerprint(provider, path) -> list | None:
    """디렉터리 내용에서 뽑은 지문: [항목 수, 해시].

    **디렉터리 mtime을 쓰지 않는 이유가 있다.** Windows는 파일을 만든 뒤 부모
    디렉터리의 last-write-time을 지연 갱신한다. 그래서 같은 폴더를 연속으로 stat
    하면 서로 다른 mtime이 나올 수 있고, 아무것도 안 바뀌었는데 "변경됨"으로 판정해
    매번 다시 스캔하게 된다(이전 프로젝트 스캐너가 가진 잠재 문제이기도 하다).

    내용에서 직접 뽑으면 값이 안정적이고, 추가/삭제/크기변경/수정시각변경을 모두
    잡는다. 비용도 디렉터리 열거 1회뿐이다 - Windows의 scandir는 이름과 함께
    크기/시각을 같이 돌려주므로 항목마다 따로 stat 하지 않는다.
    """
    entries = provider.scandir(path)
    if not entries and not provider.exists(path):
        return None
    payload = "\n".join(sorted(f"{e.name}\x00{e.size}\x00{e.mtime_ns}" for e in entries))
    return [len(entries), hashlib.sha1(payload.encode("utf-8")).hexdigest()]


def system_signature(provider, adapter, layout, media_types) -> dict:
    """이 System이 변경됐는지 판정할 최소한의 정보.

    gamelist.xml은 파일이라 (mtime, size)가 안정적이지만, 디렉터리는 내용 지문을 쓴다.
    """
    meta_stat = provider.stat(layout.metadata_file) if layout.metadata_file else None
    media = {Path(d).name: _dir_fingerprint(provider, d)
             for d in adapter.media_dirs(layout, media_types)}
    return {
        "scan_version": SCAN_VERSION,
        "rom": _dir_fingerprint(provider, layout.rom_dir) if layout.rom_dir else None,
        "meta": [meta_stat.mtime_ns, meta_stat.size] if meta_stat else None,
        "media": media,
        "media_types": sorted(media_types) if media_types is not None else None,
    }


def _unchanged(cached, current) -> bool:
    if not cached or cached.get("scan_version") != SCAN_VERSION:
        return False
    if not _sig_covers(cached.get("media_types"), current.get("media_types")):
        return False
    if cached.get("rom") != current.get("rom") or cached.get("meta") != current.get("meta"):
        return False
    # 이번에 확인한 media 폴더만 비교한다. 캐시가 더 많은 폴더를 담고 있는 것은
    # 문제가 아니다(부분 스캔이 전체 캐시를 무효화하면 안 된다).
    cached_media = cached.get("media") or {}
    return all(cached_media.get(name) == fingerprint
               for name, fingerprint in (current.get("media") or {}).items())


def scan_collection(collection, cache, provider, adapter, *, media_types=None,
                    force=False, progress_cb=None) -> dict:
    """Collection 전체를 스캔해 Cache를 갱신한다.

    media_types를 좁혀서 주면 그 타입의 media 폴더만 실제로 연다(커버 먼저, 비디오
    나중). 그 경우 media 용량 합계는 부분값이 되므로 기존 통계를 유지한다 - 이어지는
    전체 스캔이 정확한 값으로 덮어쓴다.

    반환: {"systems": [...], "scanned": n, "skipped": n, "roms": n}
    """
    systems = adapter.list_systems(provider, collection)
    storage_by_system = {s.system: s.storage_id for s in collection.systems}
    previous_stats = {s["system"]: s for s in cache.system_stats()}

    scanned = skipped = total_roms = 0
    for index, system in enumerate(systems, start=1):
        if progress_cb:
            progress_cb(index, len(systems) + 1, system)

        layout = adapter.layout(collection, system)
        signature = system_signature(provider, adapter, layout, media_types)
        if not force and _unchanged(cache.get_system_sig(system), signature):
            skipped += 1
            total_roms += previous_stats.get(system, {}).get("rom_count", 0)
            continue

        storage_id = storage_by_system.get(system, STORAGE_INTERNAL)
        rows, stats = _scan_system(provider, adapter, layout, storage_id, media_types)
        if media_types is not None and system in previous_stats:
            # 부분 스캔이라 media 용량이 실제보다 작다. 예전 값을 유지한다.
            stats["media_bytes"] = previous_stats[system].get("media_bytes", 0)

        cache.replace_system(system, rows)
        cache.set_system_stats(system, storage_id, **stats)
        cache.set_system_sig(system, signature)
        scanned += 1
        total_roms += stats["rom_count"]

    # 사라진 System은 캐시에서 지운다. 안 지우면 목록에 유령 항목이 남는다.
    for stale in set(previous_stats) - set(systems):
        cache.forget_system(stale)

    cache.set_meta("last_scan", {"systems": len(systems), "scan_version": SCAN_VERSION})
    if progress_cb:
        progress_cb(len(systems) + 1, len(systems) + 1, "완료")
    return {"systems": systems, "scanned": scanned, "skipped": skipped, "roms": total_roms}


def _scan_system(provider, adapter, layout, storage_id, media_types):
    metadata = adapter.read_index(provider, layout)
    media_index = adapter.read_media_index(provider, layout, media_types)
    rom_files = adapter.list_roms(provider, layout)

    rows = []
    media_count = media_bytes = 0
    missing_metadata = missing_media = 0

    for filename in rom_files:
        stat = provider.stat(Path(layout.rom_dir) / filename)
        entry = metadata.get(filename)
        media = media_index.get(Path(filename).stem, [])
        if media:
            media_count += 1
            media_bytes += sum(m.size for m in media)
        else:
            missing_media += 1
        if entry is None:
            missing_metadata += 1
        rows.append(_row(filename, entry, media, stat, storage_id, present=True))

    # gamelist.xml에는 있지만 물리 ROM이 없는 항목도 정상적인 상태다. ES-DE는
    # 메타데이터와 media만 갖춘 Collection을 만들 수 있다.
    for filename, entry in metadata.items():
        if filename in set(rom_files):
            continue
        media = media_index.get(Path(filename).stem, [])
        rows.append(_row(filename, entry, media, None, storage_id, present=False))

    stats = {
        "rom_count": len(rom_files),
        "rom_bytes": sum(r["size"] for r in rows if r["present"]),
        "media_count": media_count,
        "media_bytes": media_bytes,
        "missing_metadata": missing_metadata,
        "missing_media": missing_media,
    }
    return rows, stats


def _title_of(entry, filename) -> str:
    """목록에 보여줄 제목. 메타데이터에 name이 없으면 파일명 stem을 쓴다."""
    name = (entry.fields.get("name") or "").strip() if entry else ""
    return name or Path(filename).stem


def _row(filename, entry, media, stat, storage_id, *, present):
    title = _title_of(entry, filename)
    return {
        "filename": filename,
        "rel_path": filename,
        "storage_id": storage_id,
        "size": stat.size if stat else 0,
        "mtime_ns": stat.mtime_ns if stat else 0,
        "volume_file_id": stat.file_id if stat else None,
        "title": title,
        "title_norm": normalize_title(title),
        "has_metadata": entry is not None,
        "has_media": bool(media),
        "present": present,
        "fields": entry.fields if entry else {},
        "frontend_raw": entry.frontend_raw if entry else {},
        "media": [{"media_type": m.media_type, "rel_path": m.path,
                   "size": m.size, "mtime_ns": m.mtime_ns} for m in media],
    }
