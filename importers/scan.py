"""Fast Local scanner with in-memory incremental indexes."""
from pathlib import Path
import os
from importers import get_importer
from importers.base import directory_size_bytes
from config import touch_scan_time, validate_local_paths, LocalPathError


def detect_local_structure(rom_path, metadata_path, media_path, frontend):
    if not rom_path or not str(rom_path).strip():
        return "invalid", "ROM 경로가 입력되지 않았습니다."
    if not metadata_path or not str(metadata_path).strip():
        return "invalid", "Metadata 경로가 입력되지 않았습니다."
    importer = get_importer(frontend)
    return importer.detect_structure(rom_path, metadata_path, media_path)


def _file_sig(p):
    try:
        st = p.stat()
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


def _bulk_metadata(importer, metadata_path, system):
    fn = getattr(importer, "build_metadata_index", None)
    if fn:
        try:
            return fn(metadata_path, system)
        except Exception:
            return {}
    return {}


def _dir_sig(p):
    try:
        st = Path(p).stat()
        return (st.st_mtime_ns, st.st_ctime_ns)
    except OSError:
        return None


def _bulk_media(importer, media_path, system, media_types=None):
    fn = getattr(importer, "build_media_index", None)
    if fn:
        try:
            import inspect
            if "media_types" in inspect.signature(fn).parameters:
                return fn(media_path, system, media_types=media_types)
            return fn(media_path, system)
        except Exception:
            return {}
    return {}


def _index_types_cover(cached_types, wanted_types):
    """[P0-1] cached_types/wanted_types는 frozenset(media type) 또는 None(=전체).
    cached media_index가 wanted_types를 실제로 커버하는지 - 전체를 원하면 cached도
    전체여야 하고, 일부만 원하면 cached가 전체이거나 그 일부를 포함해야 한다."""
    if wanted_types is None:
        return cached_types is None
    if cached_types is None:
        return True
    return set(wanted_types).issubset(cached_types)


def scan_local(local_entry, progress_cb=None, force=False, runtime_cache=None, media_types=None):
    """Scan ROMs once, then reuse cached XML/media indexes and file signatures.

    [버그 수정] progress_cb(current, total, label)가 예전엔 ROM 파일 순회 구간에서만
    불렸다 - metadata/media 인덱싱(_bulk_metadata/_bulk_media, system당 한 번씩)에는
    콜백 자체가 없어서, "메타데이터 읽는 중"/"media 인덱싱 중"인 동안은 진행률 바가
    안 움직이다가 ROM 순회가 시작되면 갑자기 뛰는 식이었다(GUI에서는 이게 "스캔
    중입니다가 왔다갔다 한다"는 리포트로 이어졌다). 이제 metadata/media/ROM 세 단계
    전부에서 progress_cb를 부르고, 전체 진행률은 세 단계 각각의 진행률(fraction) 중
    "가장 느린 쪽"(min)을 따른다 - 셋 다 monotonic하게 증가하는 카운터라 min()도
    항상 monotonic하고(역행 없음), 사용자가 실제로 기다려야 하는 시간을 정확히
    반영한다(어느 하나가 먼저 끝나도 나머지가 끝나기 전엔 100%로 보이지 않음).
    percent-like 0~100 스케일로 정규화해서 넘긴다(system 개수/ROM 개수처럼 서로
    다른 단위를 하나의 progress_cb(current, total, label) 신호로 합치기 위함).

    media_types: [P0-1, Scan Phase 1 실제 filesystem I/O 분리] None이면(기본) 전체
    media 타입을 인덱싱한다. 리스트를 주면(예: ["covers"]) 그 타입의 폴더만 실제로
    열거한다 - video를 포함한 나머지 타입은 이 호출에서 전혀 건드리지 않는다.
    system별 media_index 캐시는 어떤 타입 집합으로 만들어졌는지(media_index_types)
    함께 기록하고, 다음 호출이 요청한 타입 집합을 캐시가 실제로 커버하지 못하면
    (예: 이전엔 covers만 인덱싱했는데 이번엔 전체를 요청) 캐시를 무시하고 다시
    인덱싱한다 - 그렇지 않으면 Phase 2(전체)가 Phase 1(covers만)의 부분 인덱스를
    "이미 다 됐다"고 착각하고 그대로 재사용해버린다.
    """
    wanted_types = frozenset(media_types) if media_types is not None else None
    # ES-DE may legitimately be registered without a ROM directory. Its gamelist.xml
    # and downloaded_media are sufficient to show metadata-only / Missing ROM entries.
    if local_entry.get("frontend") == "es-de":
        meta = local_entry.get("metadata_path", "")
        if not meta or not Path(meta).exists():
            raise LocalPathError(f"{local_entry.get('label', 'Local')}의 ES-DE 경로를 찾을 수 없습니다.")
        if local_entry.get("rom_path") and not Path(local_entry["rom_path"]).exists():
            # Treat a stale optional ROM path as absent rather than failing metadata scan.
            local_entry["rom_path"] = ""
    else:
        validate_local_paths(local_entry)
    frontend = local_entry["frontend"]
    importer = get_importer(frontend)
    rom_path = Path(local_entry["rom_path"]) if local_entry.get("rom_path") else None
    metadata_path = Path(local_entry["metadata_path"])
    media_path = Path(local_entry.get("media_path") or local_entry["metadata_path"])

    status, message = importer.detect_structure(rom_path, metadata_path, media_path)
    systems = importer.list_systems(rom_path, metadata_path)
    # Scan index is runtime-only. Never put it into cfg/local_entry because save_config()
    # would serialize thousands of ROM/media entries on every refresh.
    cache = runtime_cache if runtime_cache is not None else {}
    old = cache if not force else {}
    result_roms = []
    # Metadata entries are kept separately from physical ROMs. This is required for
    # ES-DE installations that contain gamelist.xml/media but intentionally no ROMs.
    metadata_entries = []
    per_system = {}
    total_rom_count = total_rom_size = total_media_count = total_media_size = 0
    missing_metadata = missing_media = 0
    system_roms = {s: (importer.list_roms(rom_path, s) if rom_path else []) for s in systems}
    total_files = sum(len(v) for v in system_roms.values())
    current = 0
    total_systems = len(systems)
    meta_done = media_done = 0

    def report_progress(cur, total, label):
        """[P0-3] scan.py는 지금 실제로 진행 중인 작업의 current/total을 있는
        그대로 보고할 뿐이다 - "Scan 전체 진행률"이라는 개념(여러 단계를 하나의
        0~100%로 합치는 것)은 더 이상 여기서 만들지 않는다. Scan을 여러 Phase로
        나누고 그 Phase들을 하나의 progress bar로 이어붙이는 책임은 API Job
        controller(api.py의 _start_phased_media_job/_phase_progress)가 진다 -
        실제로 이 progress_cb는 Api.scan_local()에서는 아예 연결되지 않고
        importers.scan.scan_local()의 다른 직접 호출부(레거시 Tk GUI 등)에서만
        쓰인다."""
        if not progress_cb:
            return
        progress_cb(cur, total, label)

    for system in systems:
        gamelist = metadata_path / "gamelists" / system / "gamelist.xml"
        meta_sig = _file_sig(gamelist)
        media_root = media_path / "downloaded_media" / system
        # media 파일 전체의 stat/rglob는 Refresh마다 수천~수만 번의 I/O를 유발한다.
        # 구조 변경 감지에는 system/mediatype 디렉터리의 mtime만 사용한다.
        try:
            sig_parts = []
            if media_root.exists():
                sig_parts.append((".", media_root.stat().st_mtime_ns))
                for d in media_root.iterdir():
                    if d.is_dir():
                        sig_parts.append((d.name, d.stat().st_mtime_ns))
            media_sig = tuple(sorted(sig_parts))
        except OSError:
            media_sig = ()
        old_sys = old.get(system, {})
        rom_dir = rom_path / system if rom_path else None
        rom_dir_sig = _dir_sig(rom_dir) if rom_dir else None
        if old_sys.get("meta_sig") == meta_sig and old_sys.get("metadata_index") is not None:
            metadata_index = old_sys["metadata_index"]
        else:
            metadata_index = _bulk_metadata(importer, metadata_path, system)
        meta_done += 1
        report_progress(meta_done, total_systems, f"{system} 메타데이터 읽는 중")
        media_unchanged = (old_sys.get("media_sig") == media_sig and old_sys.get("media_index") is not None
                          and _index_types_cover(old_sys.get("media_index_types"), wanted_types))
        rom_structure_unchanged = old_sys.get("rom_dir_sig") == rom_dir_sig and old_sys.get("rom_entries") is not None
        if media_unchanged:
            media_index = old_sys["media_index"]
            media_index_types = old_sys.get("media_index_types")
        else:
            media_index = _bulk_media(importer, media_path, system, media_types=media_types)
            media_index_types = wanted_types
        media_done += 1
        report_progress(media_done, total_systems, f"{system} media 인덱싱 중")

        # ROM 디렉터리/metadata/media가 모두 변경되지 않았다면 10,000개 ROM을 다시 stat하지 않는다.
        if rom_structure_unchanged and old_sys.get("meta_sig") == meta_sig and media_unchanged:
            cached_entries = old_sys["rom_entries"]
            current += len(cached_entries)
            report_progress(current, total_files, f"{system} (변경 없음)")
            result_roms.extend(cached_entries)
            cached_metadata = old_sys.get("metadata_entries")
            if cached_metadata is None:
                cached_metadata = [{"system": system, "filename": fn, "_fields": fields,
                                    "has_metadata": True, "path": "", "size": 0, "romMatched": False}
                                   for fn, fields in (old_sys.get("metadata_index") or {}).items()]
            metadata_entries.extend(cached_metadata)
            ps = old_sys.get("per_system", {})
            per_system[system] = dict(ps)
            total_rom_count += ps.get("rom_count", 0)
            total_rom_size += ps.get("rom_size", 0)
            total_media_count += ps.get("media_count", 0)
            total_media_size += ps.get("media_size", 0)
            missing_metadata += ps.get("missing_metadata", 0)
            missing_media += ps.get("missing_media", 0)
            continue

        # Every gamelist entry participates in the metadata index, regardless of ROM existence.
        sys_metadata_entries = [{"system": system, "filename": fn, "_fields": fields,
                                 "has_metadata": True, "path": "", "size": 0, "romMatched": False}
                                for fn, fields in metadata_index.items()]
        metadata_entries.extend(sys_metadata_entries)

        roms = system_roms.get(system, [])
        sys_count = len(roms); sys_size = 0; sys_media_count = 0; sys_missing_meta = 0; sys_missing_media = 0
        new_files = {}
        for rf in roms:
            current += 1
            sig = _file_sig(rf)
            old_file = old_sys.get("files", {}).get(rf.name, {})
            entry = old_file.copy() if old_file.get("sig") == sig else {"sig": sig}
            entry["system"] = system; entry["filename"] = rf.name; entry["path"] = str(rf); entry["size"] = sig[0] if sig else 0
            fields = metadata_index.get(rf.name)
            entry["_fields"] = fields
            entry["has_metadata"] = fields is not None
            med = media_index.get(rf.stem, [])
            entry["_media"] = med
            entry["has_media"] = bool(med)
            if not entry["has_metadata"]: sys_missing_meta += 1
            if not entry["has_media"]: sys_missing_media += 1
            else: sys_media_count += 1
            sys_size += entry["size"]
            result_roms.append(entry); new_files[rf.name] = entry
            report_progress(current, total_files, rf.name)
        # [P0-1] media_root 전체를 rglob해서 크기를 합산하는 것도 media_index 인덱싱과
        # 마찬가지로 무거운 filesystem traversal이다. Phase 1(wanted_types가 일부만
        # 요청됨)에서는 이 계산을 건너뛰고 기존 값을 그대로 쓴다 - 어차피 이어지는
        # Phase 2(전체)가 정확한 값으로 갱신한다.
        if media_unchanged or wanted_types is not None:
            media_size = old_sys.get("media_size", 0)
        else:
            media_size = directory_size_bytes(media_root)
        per_system[system] = {"rom_count": sys_count, "rom_size": sys_size, "media_count": sys_media_count,
                              "media_size": media_size, "missing_metadata": sys_missing_meta, "missing_media": sys_missing_media}
        total_rom_count += sys_count; total_rom_size += sys_size; total_media_count += sys_media_count; total_media_size += media_size
        missing_metadata += sys_missing_meta; missing_media += sys_missing_media
        cache[system] = {"meta_sig": meta_sig, "media_sig": media_sig, "rom_dir_sig": rom_dir_sig,
                         "metadata_index": metadata_index, "media_index": media_index, "media_index_types": media_index_types,
                         "media_size": media_size, "files": new_files, "rom_entries": result_roms[-len(roms):],
                         "metadata_entries": sys_metadata_entries, "per_system": per_system[system]}

    # [버그 수정] rom_count 기반(rom_count - missing_metadata)으로 계산하면 ES-DE
    # metadata-only Local(rom_path 미설정 - gamelist/media는 있지만 물리 ROM이 없는
    # 등록 방식)은 rom_count가 항상 0이라 Dashboard의 Metadata 개수도 항상 0으로
    # 나왔다. metadata_entries는 물리 ROM 존재 여부와 무관하게 gamelist의 모든 항목을
    # 담으므로, 그 길이를 그대로 저장해 Dashboard가 정확한 개수를 읽을 수 있게 한다.
    local_entry["stats"] = {"rom_count": total_rom_count, "rom_size_bytes": total_rom_size,
                             "media_count": total_media_count, "media_size_bytes": total_media_size,
                             "metadata_count": len(metadata_entries),
                             "missing_rom": 0, "missing_metadata": missing_metadata, "missing_media": missing_media}
    local_entry["status"] = {"valid": "정상", "warning": "경고", "invalid": "오류"}.get(status, "미설정")
    touch_scan_time(local_entry)
    scan_token = tuple(sorted((system, repr(cache.get(system, {}).get("meta_sig")),
                               repr(cache.get(system, {}).get("media_sig")),
                               repr(cache.get(system, {}).get("rom_dir_sig"))) for system in systems))
    result = {"status": status, "message": message, "per_system": per_system,
              "rom_list": result_roms, "metadata_entries": metadata_entries, "scan_token": scan_token}
    # 삭제/필터 등의 화면 작업에서 전체 스캔 없이 사용할 수 있도록 per-system 통계를 함께 보관
    return result
