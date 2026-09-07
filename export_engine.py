"""
export_engine.py
=================
MasterDB -> Local Export 실행 엔진 (설계서 v2 §3.2).

핵심 규칙:
- 기본 동작: Local에 실제 존재하는 ROM에 매칭되는 metadata+media만 복사 (MasterDB 전체 아님).
- 기존 metadata와 충돌 시: conflict_resolver 콜백 호출 -> "ok"|"skip"|"replace_all"|"skip_all"
  ("replace_all"/"skip_all"은 이후 모든 충돌에 자동 적용됨)
- Export 옵션(§16): 중복 시 한글화 롬만 복사 / Media도 복사 / Video도 복사
- 선택적 Export: target_roms 파라미터로 (system, filename) 목록을 지정하면 해당 항목만 처리
  (None이면 Local에 존재하는 전체 ROM 대상)
"""

from pathlib import Path

from importers.scan import scan_local
from importers import get_importer
from exporters import get_exporter
import db as dbmod
import file_ops
from config import canonical_system, local_system_name
from utils import normalize_title, is_korean_rom, rom_match_keys


def _cache_rom_hash(sqlite_repo, system, filename, file_path, queue_hash_fn=None):
    """[신규, P0-8 갱신] ROM이 처음 복사된 직후 SHA256 캐싱을 요청한다 - api.py의
    Api._cache_rom_hash와 같은 정책(이미 있으면 재계산 안 함, sqlite_repo가 없으면
    캐시할 곳이 없으니 조용히 건너뜀)이지만, 이 파일의 함수들은 Api 메서드가 아니라
    독립 함수라 sqlite_repo를 인자로 받는 버전을 따로 둔다.

    queue_hash_fn(system, filename, file_path): [P0-8] 주어지면(Api.request_rom_hash
    를 바인딩해서 넘김) 즉시 계산하지 않고 이 콜백으로 넘겨 백그라운드 큐에서
    비동기로 계산한다 - Export/Local->Local 복사가 이 함수를 호출하는 지점은
    mutates_db=True job(따라서 _db_lock) 안이라, 여기서 동기로 파일을 통째로
    읽어 해시를 계산하면 그 시간만큼 다른 모든 DB job을 block한다. queue_hash_fn이
    없으면(예: 독립 스크립트/테스트에서 직접 호출) 예전처럼 동기로 계산한다."""
    if sqlite_repo is None:
        return
    if queue_hash_fn is not None:
        key = dbmod.make_rom_key(system, filename)
        if sqlite_repo.get_rom_hash(key) is not None:
            return
        queue_hash_fn(system, filename, file_path)
        return
    key = dbmod.make_rom_key(system, filename)
    if sqlite_repo.get_rom_hash(key) is not None:
        return
    try:
        digest = dbmod.file_sha256(file_path)
        if digest:
            sqlite_repo.set_rom_hash(key, digest)
    except Exception:
        pass


CONFLICT_ACTIONS = ("ok", "skip", "replace_all", "skip_all")

# [체감 속도] media 배치 하나를 이 개수(pair 기준)만큼 모았을 때 flush한다.
# 너무 크면 worker 타임아웃(기본 180초)에 걸릴 위험과, 타임아웃 시 그
# 배치 전체가 in-process fallback으로 떨어져 결국 부모 프로세스가 많은
# 파일을 직접 복사하게 되는(=AhnLab 위험 재현) 위험이 커진다. 너무 작으면
# spawn 절감 효과가 줄어든다 - 100~200 사이가 무난한 절충점이라 150으로 둔다.
MEDIA_BATCH_FLUSH_SIZE = 150


def _build_masterdb_match_index(db):
    """Build system-scoped normalized filename index once per export.

    A normalized key may point at multiple ROMs.  Such ambiguous keys are kept as a
    list and are never auto-selected by the fallback matcher.
    """
    index = {}
    for rom_key, entry in db.get("roms", {}).items():
        system = entry.get("system", "")
        filename = entry.get("rom_filename", "")
        if not system or not filename:
            continue
        sys_index = index.setdefault(system, {})
        for key in rom_match_keys(filename):
            sys_index.setdefault(key, []).append((rom_key, entry))
    return index


def _find_masterdb_rom(db, match_index, system, filename):
    """Exact filename first, then normalized same-system filename matching."""
    exact_key = dbmod.make_rom_key(system, filename)
    exact = db.get("roms", {}).get(exact_key)
    if exact is not None:
        return exact_key, exact, "exact"

    sys_index = match_index.get(system, {})
    for rank, key in enumerate(rom_match_keys(filename)):
        candidates = sys_index.get(key, [])
        # Never guess across ambiguous same-system candidates.  This is important for
        # sequels/parts and similarly named regional releases.
        if len(candidates) == 1:
            rom_key, entry = candidates[0]
            return rom_key, entry, "normalized" if rank == 0 else "subtitle-fallback"
    return None, None, None


def _fields_differ(existing_fields, new_fields):
    if not existing_fields:
        return False  # 기존 데이터가 없으면 충돌이 아니라 신규 작성
    keys = ["name", "desc", "genre", "developer", "publisher", "releasedate", "region", "players", "rating"]
    for k in keys:
        if str(existing_fields.get(k, "")).strip() != str(new_fields.get(k, "")).strip():
            return True
    return False


def _find_korean_duplicate_in_local(rom_filename, system, local_rom_filenames):
    """같은 시스템 내에서 rom_filename과 정규화 타이틀이 같은 '한글화 버전'이 따로 존재하는지 확인.
    (§16 '중복 시 한글화 롬만 복사' 옵션에서 사용)"""
    if is_korean_rom(rom_filename):
        return None  # 이미 한글화 롬이므로 확인 불필요
    target_title = normalize_title(Path(rom_filename).stem)
    for fname in local_rom_filenames:
        if fname == rom_filename:
            continue
        if is_korean_rom(fname) and normalize_title(Path(fname).stem) == target_title:
            return fname
    return None


def export_masterdb_to_local(
    local_entry, masterdb_root, db, export_options,
    conflict_resolver=None, progress_cb=None, target_roms=None, media_types=None, copy_rom=False,
    sqlite_repo=None, scan_result=None, queue_hash_fn=None,
):
    """
    MasterDB -> Local Export 실행.

    target_roms: [(system, filename), ...] 또는 None (Local 전체 ROM 대상, §3.2 기본 동작)
    conflict_resolver(existing_fields, new_fields, rom_info) -> "ok"|"skip"|"replace_all"|"skip_all"
        None이면 충돌 시 항상 덮어쓰기(ok)로 간주 (GUI 미연결 상태의 배치/테스트용 기본값)
    sqlite_repo: (v0.5 8단계) 옵션 SQLiteRepository. Export는 MasterDB 자체를 쓰지
        않으므로(파일만 씀) rom/version/media native mirror는 필요 없다 - 대신 실제로
        MasterDB에 매칭되어 이 Local로 내보내진 ROM들을 game_list_set_roms 멤버십으로
        기록한다 (전체 Export는 sync, target_roms 지정 시엔 add-only).
    scan_result: [P1-1] 이미 계산된 scan_local() 결과를 넘기면 재사용한다(없으면
        새로 스캔). 여러 phase(메타데이터+커버 -> 나머지 미디어 -> 비디오)가 각자
        새로 이 Local을 스캔하면 phase 수만큼 같은 gamelist/media 인덱싱을
        반복하게 되므로, 호출부가 phase 시작 전에 한 번만 스캔해서 넘겨주면 된다.
    queue_hash_fn: [P0-8] 주어지면 ROM 복사 직후 SHA256을 동기로 계산하지 않고
        이 콜백(Api.request_rom_hash)으로 넘겨 백그라운드에서 계산한다.

    반환: {
        "exported": int, "skipped_no_match": int, "skipped_conflict": int,
        "skipped_korean_dup": int, "not_implemented": bool, "errors": [...]
    }
    """
    frontend = local_entry["frontend"]
    exporter = get_exporter(frontend)
    # media_types=None means all supported media. An empty set means none.
    selected_media = None if media_types is None else {str(x).lower() for x in media_types}

    scan_result = scan_result or scan_local(local_entry)
    local_rom_list = scan_result["rom_list"]
    local_rom_filenames_by_system = {}
    for r in local_rom_list:
        local_rom_filenames_by_system.setdefault(r["system"], []).append(r["filename"])

    match_index = _build_masterdb_match_index(db)
    if target_roms is not None:
        # target_roms comes from MasterDB selection.  Do not compare it directly to the
        # Local filename: normalized matching is specifically meant to support different
        # filenames.  Resolve each Local ROM first, then retain it when the matched
        # MasterDB key is one of the requested targets.
        wanted_master_keys = {dbmod.make_rom_key(sys, fname) for sys, fname in target_roms}
        targets = []
        matched_wanted_keys = set()
        for r in local_rom_list:
            master_system = canonical_system(local_entry, r["system"])
            matched_key, _entry, _kind = _find_masterdb_rom(db, match_index, master_system, r["filename"])
            if matched_key in wanted_master_keys:
                targets.append(r)
                matched_wanted_keys.add(matched_key)
        # [신규] copy_rom=True로 ROM 파일까지 요청했는데 대상 Local에 그 ROM이 아직
        # 물리적으로 없으면, 위 루프에선 애초에 후보로 안 잡힌다(local_rom_list 기반
        # 매칭이라 존재하는 파일만 봄). MasterDB 쪽 rom_entry 정보만으로 새 타겟을
        # 합성해서, "ArchiveDB에만 있는 ROM을 GameListSet으로 새로 복사"가 되게 한다.
        if copy_rom:
            for sys, fname in target_roms:
                key = dbmod.make_rom_key(sys, fname)
                if key in matched_wanted_keys:
                    continue
                rom_entry = db.get("roms", {}).get(key)
                if rom_entry is None:
                    continue
                master_system = rom_entry.get("system", sys)
                dest_filename = rom_entry.get("rom_filename", fname)
                targets.append({"system": local_system_name(local_entry, master_system), "filename": dest_filename})
    else:
        targets = local_rom_list  # 기본: Local에 실제 존재하는 ROM만

    result = {
        "exported": 0,
        "skipped_no_match": 0,
        "skipped_conflict": 0,
        "skipped_korean_dup": 0,
        "not_implemented": False,
        "errors": [],
    }

    # 대화창에서 "Replace All" / "Skip All"을 선택하면 이후 반복에 자동 적용
    global_override = {"value": None}
    matched_keys = []  # GameListSet 멤버십용: 실제로 MasterDB 매칭이 된 rom_key만 기록

    # [성능/정합성 버그 수정] exporter.write_metadata_fields()/read_existing_fields()에
    # 이 dict를 넘기면 gamelist.xml/metadata.pegasus.txt 등을 ROM마다 다시 읽고/쓰지
    # 않고 메모리에 쌓아뒀다가 exporter.flush_metadata_cache()로 export 끝에 한 번만
    # 쓴다. 예전엔 ROM 1개당 (1) 충돌 검사용 read + (2) 저장용 read+write를 전부
    # 새로 했으므로, ROM이 1,000개인 시스템이면 같은 문서 파일을 최대 2,000번 통째로
    # 열고 파싱하는 O(n^2) 패턴이었다.
    metadata_cache = {}
    # [체감 속도] ROM마다 즉시 write_media()가 워커를 spawn하는 대신, 여러
    # ROM의 media pair를 모아뒀다가 MEDIA_BATCH_FLUSH_SIZE개마다 한 번에
    # flush한다 - export_engine.py 주석/설계서 논의 참고. flush 실패는
    # 그 배치에 속한 개별 ROM 단위로 원인을 특정할 수 없으므로(여러 ROM이
    # 한 번의 worker 호출에 묶임), errors에는 배치 단위 메시지로 기록한다
    # (기존에도 write_media() 실패는 파일 단위 검증 없이 예외 여부로만
    # 판단했으므로 세분성 손실은 없다).
    media_batch = file_ops.MediaCopyBatch()

    def _flush_media_batch():
        pending = len(media_batch)
        if pending == 0:
            return
        try:
            media_batch.flush()
        except Exception as e:
            result["errors"].append(f"Media 배치 복사 오류({pending}개 대기 중): {e}")

    total = len(targets)
    # [버그 수정] gamelist.xml 등은 ROM 루프 중엔 메모리 캐시에만 쌓이고 루프가 끝난
    # 뒤 flush_metadata_cache()/_flush_media_batch()에서 실제로 디스크에 쓰인다
    # (위 metadata_cache 주석 참고). progress_cb(idx, total, ...)를 total만큼만
    # 채우면, 실제 파일 쓰기가 아직 끝나지 않았는데도(특히 대량 라이브러리는 flush에
    # 수 초 이상 걸릴 수 있다) 표시된 진행률이 먼저 100%에 도달해버려 "표시된
    # progress"와 "실제 처리 완료" 사이에 괴리가 생겼다. flush를 위한 몫을 total에
    # 하나 더 얹어서, 그 값이 채워질 때(=flush가 실제로 끝났을 때)만 100%가 되게 한다.
    progress_total = total + 1
    for idx, rom in enumerate(targets, start=1):
        system = rom["system"]
        filename = rom["filename"]

        if progress_cb:
            progress_cb(idx, progress_total, filename)

        master_system = canonical_system(local_entry, system)
        rom_key, rom_entry, match_kind = _find_masterdb_rom(db, match_index, master_system, filename)
        if rom_entry is None:
            result["skipped_no_match"] += 1
            continue
        matched_keys.append(rom_key)

        # 한글화 중복 옵션 (§16)
        if export_options.get("korean_only_on_conflict"):
            korean_dup = _find_korean_duplicate_in_local(
                filename, system, local_rom_filenames_by_system.get(system, [])
            )
            if korean_dup:
                result["skipped_korean_dup"] += 1
                continue

        new_fields = dbmod.get_filled_fields(rom_entry)

        try:
            existing_fields = exporter.read_existing_fields(local_entry["metadata_path"], system, filename, cache=metadata_cache)
        except NotImplementedError as e:
            result["not_implemented"] = True
            result["errors"].append(str(e))
            break
        except Exception as e:
            existing_fields = None
            result["errors"].append(f"{filename}: 기존 metadata 읽기 오류 - {e}")

        action = "ok"
        if _fields_differ(existing_fields, new_fields):
            if export_options.get("force_overwrite"):
                # [신규] 강제 덮어쓰기: 확인 대화상자 자체를 띄우지 않고 무조건 MasterDB 내용으로 교체
                action = "ok"
            elif global_override["value"] in ("replace_all", "skip_all"):
                action = "ok" if global_override["value"] == "replace_all" else "skip"
            elif conflict_resolver:
                action = conflict_resolver(existing_fields, new_fields, {"system": system, "filename": filename})
                if action in ("replace_all", "skip_all"):
                    global_override["value"] = action
                    action = "ok" if action == "replace_all" else "skip"
            # conflict_resolver가 없으면 기본값 "ok"(덮어쓰기) 유지

        # Metadata와 Media는 독립적으로 처리한다. Metadata가 duplicate/conflict여도
        # 선택된 Media가 Local에 없으면 반드시 보충한다. 기존의 `continue`가 이 경로를
        # 끊었던 것이 핵심 버그였다.
        if action == "skip":
            result["skipped_conflict"] += 1
        else:
            try:
                exporter.write_metadata_fields(local_entry["metadata_path"], system, filename, new_fields, cache=metadata_cache)
                result["exported"] += 1
            except NotImplementedError as e:
                result["not_implemented"] = True
                result["errors"].append(str(e))
                break
            except Exception as e:
                result["errors"].append(f"{filename}: Metadata Export 오류 - {e}")

        if (export_options.get("copy_media", True) and rom_entry.get("media") and selected_media != set()):
            try:
                media_dict = rom_entry.get("media", {})
                if selected_media is not None:
                    media_dict = {k: v for k, v in media_dict.items() if k.lower() in selected_media}
                if media_dict:
                    # [버그 수정] selected_media(대화상자에서 고른 media 타입 목록)가
                    # 있으면 그게 source of truth다 - "videos" 체크박스를 켰는데
                    # export_options.copy_video(전역 설정, 예전 config.json에
                    # copy_video=false가 남아있을 수 있음)가 이중으로 막아서 체크해도
                    # 조용히 복사가 안 되는 경우가 있었다. 명시적 선택이 있으면 그
                    # 안에 "videos"가 있는지만으로 판단하고, 선택이 없을 때(전체 복사)
                    # 만 전역 설정을 따른다.
                    copy_video = ("videos" in selected_media) if selected_media is not None else export_options.get("copy_video", True)
                    exporter.write_media(
                        local_entry["media_path"], system, filename, media_dict,
                        copy_video=copy_video, batch=media_batch,
                    )
            except Exception as e:
                result["errors"].append(f"{filename}: Media 보충 오류 - {e}")

        if len(media_batch) >= MEDIA_BATCH_FLUSH_SIZE:
            _flush_media_batch()

        # ROM은 명시적으로 선택했을 때만 복사한다.
        if copy_rom:
            try:
                # MasterDB -> Local: source uses the matched MasterDB filename, while the
                # destination is always renamed to the Local ROM filename.
                src_name = rom_entry.get("rom_filename", filename)
                src = dbmod.rom_storage_path(masterdb_root, rom_entry.get("system", master_system), src_name)
                dest = Path(local_entry["rom_path"]) / system / filename
                if src.exists() and not dest.exists():
                    # [별도 프로세스 위임] mkdir + 실제 바이트 복사를 native worker에
                    # 맡긴다 - import_engine.py의 media 복사와 동일한 이유
                    # (패키징된 프로세스 자신이 mkdir/copy를 반복하면 AhnLab 행동
                    # 기반 탐지에 걸림, copybench/INCIDENT_T015_pyinstaller.md).
                    # tmp+rename 원자성은 여기선 추가하지 않는다 - 원래도 이
                    # 경로엔 없던 보장이라 범위를 넓히지 않고 실행 주체만 옮긴다.
                    copy_results = file_ops.copy_files([dest.parent], [(src, dest)])
                    if copy_results.get(str(dest)):
                        _cache_rom_hash(sqlite_repo, system, filename, dest, queue_hash_fn=queue_hash_fn)
            except Exception as e:
                result["errors"].append(f"{filename}: ROM Export 오류 - {e}")

    # 루프가 끝났을 때 MEDIA_BATCH_FLUSH_SIZE에 못 미쳐 아직 flush되지 않은
    # media pair가 남아있을 수 있다 - 반드시 여기서 마저 내보낸다.
    _flush_media_batch()

    # [성능/정합성 버그 수정] 루프 내내 메모리에만 쌓아둔 gamelist.xml 등을 이제
    # 한 번씩만 실제로 디스크에 쓴다. write_metadata_fields가 cache를 지원하지
    # 않는 exporter(예: Daijishō)는 flush_metadata_cache 자체가 없으므로 건너뛴다.
    flush_fn = getattr(exporter, "flush_metadata_cache", None)
    if flush_fn is not None and metadata_cache:
        flush_fn(metadata_cache)

    if progress_cb:
        progress_cb(progress_total, progress_total, "저장 완료")

    if sqlite_repo is not None:
        local_id = local_entry["id"]
        if target_roms is None:
            sqlite_repo.sync_gamelistset_membership(local_id, matched_keys)
        else:
            sqlite_repo.add_gamelistset_members(local_id, matched_keys)

    return result


def copy_local_to_local(src_local, dst_local, target_roms, options=None, copy_rom=True, media_types=None, progress_cb=None, sqlite_repo=None, queue_hash_fn=None):
    """GameListSet -> GameListSet 직접 복사 (ArchiveDB 비경유).

    지금까지 Local<->Local 복사는 항상 ArchiveDB를 두 번 거쳤다(Local A ->
    import_local_to_masterdb -> ArchiveDB -> export_masterdb_to_local -> Local B).
    이 함수는 그 두 단계가 이미 재사용하고 있는 바로 그 primitive들
    (importer.read_metadata_fields/read_media, exporter.write_metadata_fields/
    write_media)을 ArchiveDB JSON을 아예 거치지 않고 소스->대상으로 곧장 연결한다.
    그래서 ArchiveDB가 설정되어 있지 않아도 동작하고, DB 저장/native mirror 같은
    부가 비용도 없다.

    target_roms: [(system, filename), ...] - src_local의 raw system 기준
    (import_local_to_masterdb의 target_roms와 동일한 규약).

    [버그 수정, 리뷰 반영] metadata/media/ROM은 서로 독립적으로 처리한다 - 예전엔
    metadata가 없으면(`fields is None`) `continue`로 그 항목 전체를 건너뛰어서,
    "ROM은 있는데 metadata만 없는" GameListSet A의 항목은 media/ROM까지 통째로
    복사가 안 됐다. 이제 세 단계 각각 독립적으로 시도하고, 실제로 무엇이 됐는지도
    세분화해서 돌려준다("exported"만 보고 성공/실패를 뭉뚱그리면 media/ROM 실패가
    조용히 숨겨진다).

    ROM 대상 정책: 대상에 이미 같은 이름의 ROM이 있으면 덮어쓰지 않고 건너뛴다
    (파일을 함부로 덮어쓰는 쪽보다 안전). 예전엔 이 경우를 결과에 전혀 남기지
    않아서, metadata/media는 새 소스 내용으로 바뀌는데 ROM만 조용히 예전 그대로
    남는 불일치가 안 보였다 - 이제 `rom_conflicts`로 명시적으로 센다.

    sqlite_repo: [신규] 옵션 SQLiteRepository. 넘겨지면 새로 복사되는 ROM의 SHA256을
    처음 한 번만 계산해서 캐시한다(_cache_rom_hash 참고) - 이 경로는 ArchiveDB를
    아예 안 거치므로(설계 원칙, 위 참고) ArchiveDB가 아예 미설정이면(sqlite_repo가
    None) 그냥 캐시 없이 넘어간다.

    반환: {
        "exported": int,           # metadata/media/ROM 중 하나라도 실제로 옮겨진 항목 수
        "metadata_copied": int, "media_copied": int, "rom_copied": int,
        "skipped_no_metadata": int,  # metadata만 없어서 그 부분만 건너뛴 항목 수
        "rom_conflicts": int,        # 대상에 이미 ROM이 있어 ROM 복사만 건너뛴 항목 수
        "errors": [str, ...],
    }
    """
    options = options or {}
    src_importer = get_importer(src_local["frontend"])
    dst_exporter = get_exporter(dst_local["frontend"])
    selected_media = None if media_types is None else {str(x).lower() for x in media_types}

    result = {
        "exported": 0, "metadata_copied": 0, "media_copied": 0, "rom_copied": 0,
        "skipped_no_metadata": 0, "rom_conflicts": 0, "errors": [],
    }
    # [성능/정합성 버그 수정] export_masterdb_to_local()과 동일한 이유 - 그쪽 주석
    # 참고. dst_exporter.write_metadata_fields()가 대상 gamelist.xml 등을 ROM마다
    # 다시 쓰지 않도록 캐시를 공유한다.
    metadata_cache = {}
    total = max(1, len(target_roms))
    # [버그 수정] export_masterdb_to_local()과 동일한 이유로 flush 몫을 하나 더
    # 얹는다 - 그쪽 주석 참고.
    progress_total = total + 1
    for idx, (system, filename) in enumerate(target_roms, start=1):
        if progress_cb:
            progress_cb(idx, progress_total, filename)

        # 두 Local이 서로 다른 system 폴더명 관례를 쓸 수 있다(예: msx1 vs msx) -
        # canonical_system을 경유해서 반대쪽 Local의 실제 폴더명으로 되돌린다.
        dst_system = local_system_name(dst_local, canonical_system(src_local, system))
        item_did_something = False

        fields = None
        try:
            fields = src_importer.read_metadata_fields(src_local["metadata_path"], system, filename)
        except Exception as e:
            result["errors"].append(f"{filename}: metadata 읽기 오류 - {e}")
        if fields is None:
            result["skipped_no_metadata"] += 1
        else:
            try:
                dst_exporter.write_metadata_fields(dst_local["metadata_path"], dst_system, filename, fields, cache=metadata_cache)
                result["metadata_copied"] += 1
                item_did_something = True
            except Exception as e:
                result["errors"].append(f"{filename}: metadata 쓰기 오류 - {e}")

        if options.get("copy_media", True) and selected_media != set():
            try:
                media_path = src_local.get("media_path") or src_local["metadata_path"]
                game_title = (fields or {}).get("name") or Path(filename).stem
                # [P1-2] media_types를 read_media()에 직접 넘겨서, 선택되지 않은
                # media 타입(video 포함) 폴더 자체를 filesystem에서 훑지 않는다.
                media_dict = src_importer.read_media(media_path, system, filename, game_title=game_title, media_types=selected_media)
                if media_dict:
                    dst_media_path = dst_local.get("media_path") or dst_local["metadata_path"]
                    # [버그 수정] export_masterdb_to_local()과 동일하게, 명시적 media
                    # 선택이 있으면 그 안의 "videos" 포함 여부가 source of truth다.
                    copy_video = ("videos" in selected_media) if selected_media is not None else options.get("copy_video", True)
                    dst_exporter.write_media(
                        dst_media_path, dst_system, filename, media_dict,
                        copy_video=copy_video,
                    )
                    result["media_copied"] += 1
                    item_did_something = True
            except Exception as e:
                result["errors"].append(f"{filename}: media 복사 오류 - {e}")

        if copy_rom and src_local.get("rom_path") and dst_local.get("rom_path"):
            try:
                src_rom = Path(src_local["rom_path"]) / system / filename
                dest_rom = Path(dst_local["rom_path"]) / dst_system / filename
                if src_rom.exists():
                    if dest_rom.exists():
                        result["rom_conflicts"] += 1
                    else:
                        # [별도 프로세스 위임] export_masterdb_to_local()과 동일한 이유로
                        # mkdir + 복사를 native worker에 맡긴다.
                        copy_results = file_ops.copy_files([dest_rom.parent], [(src_rom, dest_rom)])
                        if copy_results.get(str(dest_rom)):
                            result["rom_copied"] += 1
                            item_did_something = True
                            _cache_rom_hash(sqlite_repo, dst_system, filename, dest_rom, queue_hash_fn=queue_hash_fn)
                        else:
                            result["errors"].append(f"{filename}: ROM 복사 오류")
            except Exception as e:
                result["errors"].append(f"{filename}: ROM 복사 오류 - {e}")

        if item_did_something:
            result["exported"] += 1

    flush_fn = getattr(dst_exporter, "flush_metadata_cache", None)
    if flush_fn is not None and metadata_cache:
        flush_fn(metadata_cache)

    if progress_cb:
        progress_cb(progress_total, progress_total, "저장 완료")

    return result
