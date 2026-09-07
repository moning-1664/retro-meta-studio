"""
import_engine.py
=================
Local -> MasterDB Import 실행 엔진 (설계서 v2 §3.1).

동작:
1. Local을 스캔하여 ROM 목록을 얻는다 (importers.scan.scan_local 재사용).
2. 각 ROM에 대해 metadata가 있으면 read_metadata_fields로 파싱.
3. db.find_matching_version으로 기존 version과 동일한지 검사.
   - 동일하면: 중복 생성 방지, skip.
   - 다르면(또는 새로운 ROM이면): 새로운 version 추가.
4. media 파일은 MasterDB media 디렉토리로 복사하여 보존한다
   (Local 파일이 이후 변경/삭제되어도 MasterDB 독립성 유지 + Media Detail 미리보기용).
5. 매칭되지 않는(=metadata가 없는) ROM은 결과의 unmatched 목록에 별도 기록.

이 모듈은 GUI의 TaskRunner/Progress 콜백과 연결하기 위해
progress_cb(current, total, label) 형태의 콜백을 옵션으로 받는다.
"""

from contextlib import nullcontext
from pathlib import Path

from importers import get_importer
from importers.scan import scan_local
import db as dbmod
import file_ops
from config import canonical_system


def _sanitize_for_path(name):
    """파일/폴더명으로 안전하게 사용할 수 있도록 특수문자 제거."""
    return "".join(c if c.isalnum() or c in " ._-" else "_" for c in name).strip()


def _copy_media_to_masterdb(masterdb_root, system, rom_filename, media_dict):
    """
    media_dict: { mediatype: [local_path, ...] } (importer.read_media 결과)
    MasterDB media 디렉토리에 복사하고, 저장된 경로로 재구성한 dict를 반환한다.
    반환 구조 (db 스키마의 'media' 필드와 동일):
      { "covers": "path", "screenshots": ["path", ...], ... }

    [원자성] media type별로: (1) 전체 소스 파일을 `.tmp` 이름으로 먼저 복사
    -> (2) 하나라도 실패하면 그 타입은 통째로 포기(.tmp 정리, 기존 파일/경로는
    손대지 않음) -> (3) 전부 성공한 경우에만 기존 파일을 지우고 .tmp를 최종
    이름으로 rename한다. 타입 간에는 독립적 - 한 타입이 실패해도 다른 타입은
    정상적으로 교체된다.

    [별도 프로세스 위임, v2] mkdir/실제 바이트 복사/기존 파일 삭제/rename을
    전부 file_ops.copy_finalize_groups()에 위임한다 - 이 함수 자신은
    "무엇을 지우고 무엇을 어디로 옮길지" 계획만 세운다(파일시스템을
    직접 mutate하지 않는다). 처음엔 복사만 위임했었는데, 실제 패키징 EXE로
    검증해보니 부모 프로세스 자신이 반복하는 mkdir/삭제/rename만으로도
    AhnLab 행동 기반 탐지에 걸리는 게 확인돼서(copybench/INCIDENT_T015_
    pyinstaller.md, 2026-09-04 18:05 headless_export.exe 강제종료) 범위를
    넓혔다. file_ops(현재는 media_copy_worker -> native worker)는 워커
    바이너리가 없거나 실패하면 조용히 in-process fallback으로 동일한
    lifecycle을 재현하므로, 이 함수의 관찰 가능한 동작(원자성/type별
    실패 격리/반환 dict 형태)은 이전과 동일하게 유지된다.
    """
    paths = dbmod.db_paths(masterdb_root)
    stem = _sanitize_for_path(Path(rom_filename).stem)
    dest_dir = paths["media_dir"] / system / stem

    # 1단계: type별로 (src, tmp_dest, dest_name)을 계산한다. 소스 파일이
    # 하나라도 없는 type은 애초에 복사 대상에서 제외한다(그 type 전체 포기).
    # 삭제 대상 기존 파일 목록도 여기서 읽기 전용으로만 조회한다(디렉터리
    # 나열은 mutation이 아니므로 문제되지 않음 - 실제 unlink/rename은
    # copy_finalize_groups가 위임한 워커 프로세스 안에서만 일어난다).
    type_plan: dict[str, list[tuple[Path, Path, str]]] = {}
    groups: list[dict] = []
    group_mediatypes: list[str] = []
    for mediatype, filelist in media_dict.items():
        if not filelist:
            continue
        entries = []
        failed = False
        for i, src in enumerate(filelist):
            src_path = Path(src)
            if not src_path.exists():
                failed = True
                break
            suffix = src_path.suffix
            dest_name = f"{mediatype}_{i}{suffix}" if len(filelist) > 1 else f"{mediatype}{suffix}"
            tmp_path = dest_dir / (dest_name + ".tmp")
            entries.append((src_path, tmp_path, dest_name))
        if failed:
            continue
        type_plan[mediatype] = entries
        group_mediatypes.append(mediatype)
        groups.append({
            "copies": [(src_path, tmp_path) for src_path, tmp_path, _ in entries],
            "deletes": _list_existing_media_files(masterdb_root, system, rom_filename, [mediatype]),
            "renames": [(tmp_path, dest_dir / dest_name) for _, tmp_path, dest_name in entries],
        })

    if not groups:
        return {}

    # 2단계: 이 ROM의 모든 media type을 한 번에 위임해서 mkdir/복사/(성공 시)
    # 기존 파일 삭제+rename까지 전부 처리시킨다.
    copy_results = file_ops.copy_finalize_groups(dest_dir, groups)

    # 3단계: type별로 전부 성공했는지 확인해서 반환용 saved dict를 만든다.
    # 실제 삭제/rename은 이미 워커(또는 fallback)가 끝냈으므로, 여기서는
    # copy_results만 보고 최종 경로를 조립하면 된다.
    saved = {}
    for mediatype in group_mediatypes:
        entries = type_plan[mediatype]
        ok = all(copy_results.get(str(tmp_path), False) for _, tmp_path, _ in entries)
        if not ok:
            continue
        saved_list = [str(dest_dir / dest_name) for _, _, dest_name in entries]
        # covers/marquees/miximages/wheel: 단일 경로로 저장 (design 스키마 예시와 일치)
        # screenshots/videos: 리스트로 저장 (여러 개 가능)
        if mediatype in ("screenshots", "videos"):
            saved[mediatype] = saved_list
        else:
            saved[mediatype] = saved_list[0]
    return saved


def _list_existing_media_files(masterdb_root, system, rom_filename, media_types):
    """새 media로 덮어쓰기 전에 지워야 할 기존 저장 파일 "목록"을 읽기
    전용으로 조회한다(디렉터리 나열만 - 실제 삭제는 하지 않는다). 실제
    unlink는 file_ops.copy_finalize_groups()가 위임한 엔진이, 그 media
    type의 복사가 전부 성공했을 때만 실행한다.

    [정책] media는 Local마다 무조건 덮어쓰므로, 지우지 않으면 리스트형
    (screenshots/videos) 타입에서 이전 소스가 저장했던 파일이 고아로 남는다."""
    paths = dbmod.db_paths(masterdb_root)
    stem = _sanitize_for_path(Path(rom_filename).stem)
    dest_dir = paths["media_dir"] / system / stem
    if not dest_dir.exists():
        return []
    found = []
    for mtype in media_types:
        for pattern in (f"{mtype}.*", f"{mtype}_*"):
            for p in dest_dir.glob(pattern):
                # [P0 버그 수정] "covers.*" 글롭이 새로 복사 중인 "covers.png.tmp"
                # staging 파일까지 잡으면 안 된다 - .tmp는 항상 제외.
                if p.suffix == ".tmp":
                    continue
                if p.is_file():
                    found.append(p)
    return found


def _merge_alias_entry(db, canonical, filename):
    """Collapse an older alias-keyed MasterDB entry into the canonical key.

    Returns (target_entry_or_None, did_merge). did_merge is True only when an
    actual alias-keyed entry was found and consolidated this call - the common
    case (no legacy alias data, or the canonical entry already exists with no
    aliases to fold in) returns did_merge=False so callers can skip the
    expensive/unsafe SQLite native-mirroring path only for the rare rom that
    actually needed it.
    """
    aliases = {raw for raw, canon in __import__("config").ESDE_SYSTEM_ALIASES.items() if canon == canonical and raw != canonical}
    target_key = dbmod.make_rom_key(canonical, filename)
    target = db.get("roms", {}).get(target_key)
    did_merge = False
    for raw in aliases:
        legacy_key = dbmod.make_rom_key(raw, filename)
        legacy = db.get("roms", {}).get(legacy_key)
        if not legacy: continue
        did_merge = True
        if target is None:
            legacy["system"] = canonical
            db["roms"][target_key] = legacy
            del db["roms"][legacy_key]
            target = legacy
        else:
            target.setdefault("versions", {}).update(legacy.get("versions", {}))
            # Reuse DB's media merge semantics without importing private UI code.
            em = target.get("media") or {}
            for mt, val in (legacy.get("media") or {}).items():
                if mt in ("screenshots", "videos"):
                    a = em.get(mt) if isinstance(em.get(mt), list) else ([em[mt]] if em.get(mt) else [])
                    b = val if isinstance(val, list) else [val]
                    seen = set(a); em[mt] = a + [x for x in b if x and x not in seen]
                elif not em.get(mt): em[mt] = val
            target["media"] = em
            vids = list(target.get("versions", {}))
            if vids: target["default_version_id"] = max(vids)
            del db["roms"][legacy_key]
    return target, did_merge

def import_local_to_masterdb(local_entry, masterdb_root, db, progress_cb=None, target_roms=None, scan_result=None, sqlite_repo=None, selected_media_types=None):
    """
    Local -> MasterDB Import 실행.

    selected_media_types: [신규] None이면 발견된 media 타입을 전부 복사한다(기존
    동작과 동일 - 하위호환). 리스트를 넘기면 그 타입만 복사하고 나머지는 건드리지
    않는다 - GameList의 "Export To MasterDB"가 Settings > Media와 동일한 선택
    대화상자를 쓰도록 한 요청에 대응.

    sqlite_repo: (v0.5 8단계) 옵션 SQLiteRepository. 넘겨지면 JSON dict 변경과
    나란히 rom/version/media를 SQLite에도 직접(native) write해서, 호출자가 매번
    전체 replace_from_dict() 리빌드를 하지 않아도 되게 한다. 또한 이 Local에서
    실제로 발견된(=MasterDB에 이미 존재하는) ROM들을 game_list_set_roms
    멤버십으로 동기화한다.

    반환: {
        "imported": int,          # 새로 추가된 version 수
        "duplicates_skipped": int,
        "unmatched": [ {system, filename}, ... ],   # metadata 없는 ROM
        "errors": [ str, ... ],
        "not_implemented": bool,  # 해당 frontend의 read_metadata_fields가 미구현인 경우
        "alias_merge_occurred": bool,  # True면 레거시 alias 시스템명 병합이 있었다는 뜻 -
                                        # 그 rom들은 native mirror 대신 호출자가 전체
                                        # replace_from_dict()로 안전하게 재동기화해야 함.
    }
    """
    frontend = local_entry["frontend"]
    importer = get_importer(frontend)
    local_id = local_entry["id"]

    scan_result = scan_result or scan_local(local_entry, progress_cb=None)
    rom_list = list(scan_result.get("rom_list", []))

    # ES-DE may contain gamelist.xml + media without physical ROM files.  The old
    # importer only iterated rom_list, so a metadata-only Local produced
    # "imported 0 / duplicate 0" even though thousands of metadata records existed.
    # Add metadata-only entries as first-class import targets. ROM-backed entries are
    # kept from rom_list so they are not processed twice.
    rom_keys_present = {(r.get("system"), r.get("filename")) for r in rom_list}
    for m in scan_result.get("metadata_entries", []):
        key = (m.get("system"), m.get("filename"))
        if key in rom_keys_present:
            continue
        entry = dict(m)
        entry["path"] = ""
        entry["size"] = 0
        entry["romMatched"] = False
        rom_list.append(entry)

    if target_roms is not None:
        wanted = set(target_roms)
        rom_list = [r for r in rom_list
                    if (r.get("system"), r.get("filename")) in wanted]

    result = {
        "imported": 0,
        "duplicates_skipped": 0,
        "unmatched": [],
        "errors": [],
        "not_implemented": False,
        "alias_merge_occurred": False,
    }

    # [v0.5 8단계 성능수정, 2번째 라운드] rom마다 ensure_rom/insert_version/set_media를
    # 개별 커밋하면 WAL 모드여도 10,000-ROM 규모에서 "기존 대비 30배 이상 느림"이라는
    # 실사용 보고로 이어졌다(database/sqlite_db.py의 batch() 참고). 루프 전체를 한
    # 트랜잭션으로 묶는다 - 반드시 `with`를 써서 도중에 예외가 나도 batch()의
    # __exit__(rollback + _batch_depth 원복)이 확실히 호출되게 한다. [버그 수정]
    # 예전엔 batch_cm.__enter__()/__exit__()를 수동으로 호출했는데, 루프 중간에
    # 예상 못 한 예외(KeyError, sqlite 제약 위반 등)가 나면 __exit__ 호출 자체가
    # 스킵되어 트랜잭션이 열린 채로 남고, generator 기반 contextmanager라 내부
    # _batch_depth 카운터도 감소하지 않는다 - 그러면 SQLiteRepository._commit()이
    # "_batch_depth > 0이면 아무것도 안 함" 조건 때문에 프로세스 재시작 전까지
    # 이후 모든 SQLite 쓰기가 영구적으로 커밋되지 않는 훨씬 심각한 문제로 이어진다.
    with (sqlite_repo.batch() if sqlite_repo is not None else nullcontext()):
        total = len(rom_list)
        for idx, rom in enumerate(rom_list, start=1):
            system = rom["system"]  # Local 폴더 기준 원본 시스템명 (파일 읽기용)
            filename = rom["filename"]
            canonical = canonical_system(local_entry, system)  # MasterDB 저장용 (예: pegasus 'snes' -> es-de 'snes')

            if progress_cb:
                progress_cb(idx, total, filename)

            # Local incremental scan이 이미 파싱한 metadata를 재사용한다.
            # 10,000 ROM에서 ROM마다 gamelist.xml을 다시 읽는 가장 큰 병목을 제거한다.
            fields = rom.get("_fields")
            if fields is None and rom.get("has_metadata"):
                try:
                    fields = importer.read_metadata_fields(local_entry["metadata_path"], system, filename)
                except NotImplementedError as e:
                    result["not_implemented"] = True
                    result["errors"].append(str(e))
                    break  # 해당 Local 전체를 더 이상 진행할 수 없음
                except Exception as e:
                    result["errors"].append(f"{filename}: metadata 파싱 오류 - {e}")
                    continue

            has_metadata = fields is not None and bool(fields.get("name"))
            if not has_metadata:
                result["unmatched"].append({"system": system, "filename": filename})

            # [BUG FIX] metadata가 없어도 media는 항상 읽는다. 예전엔 여기서 곧바로
            # continue 해서, metadata가 없는 소스(gamelist)의 media가 통째로 유실됐다.
            # "metadata와 media는 독립적으로 동기화한다"는 설계 원칙이 "metadata가
            # duplicate인 경우"에만 지켜지고 "metadata가 아예 없는 경우"엔 안 지켜지던 문제.
            try:
                # [P1-2] selected_media_types가 주어졌으면(예: 1단계 "메타데이터+커버"
                # phase) read_media()에도 그대로 넘겨서, 필요 없는 media 타입(video
                # 포함) 폴더 자체를 filesystem에서 훑지 않는다 - 예전엔 항상 전체를
                # 읽어온 뒤 결과 dict만 필터링해서, video 복사는 뒤로 미뤄져도 video
                # 폴더 탐색 비용은 매 phase마다 그대로 남아 있었다.
                media_raw = importer.read_media(
                    local_entry["media_path"], system, filename, game_title=(fields or {}).get("name"),
                    media_types=selected_media_types,
                )
            except NotImplementedError as e:
                result["not_implemented"] = True
                result["errors"].append(str(e))
                break
            except Exception as e:
                media_raw = {}
                result["errors"].append(f"{filename}: media 스캔 오류 - {e}")

            if not has_metadata and not media_raw:
                continue  # 가져올 metadata도 media도 없음

            key = dbmod.make_rom_key(canonical, filename)
            rom_entry, merged_alias = _merge_alias_entry(db, canonical, filename)
            if rom_entry is None:
                rom_entry = dbmod.get_or_create_rom_entry(db, canonical, filename)
            if merged_alias:
                result["alias_merge_occurred"] = True

            # 새 metadata의 cover 원본 경로 (metadata 버전 중복 판정용 - is_same_metadata에서
            # cover 유사도 비교에 쓰인다. media 파일 자체를 덮어쓸지 말지와는 무관).
            new_cover_path = media_raw.get("covers", [None])[0] if isinstance(media_raw.get("covers"), list) else media_raw.get("covers")

            matched_vid, uncertain_from_match = (
                dbmod.find_matching_version(rom_entry, fields, new_cover_path) if has_metadata else (None, False)
            )

            # [정책 변경] media는 항상 새로 들어온 것으로 덮어쓴다. 기존엔 "이미 파일이
            # 있으면 유지"였는데, 내용 비교(SHA256) 없이 존재 여부만 봤었다. 무조건
            # 덮어쓰기가 (비교용 읽기+해시가 없는 만큼) 디스크 I/O도 더 적어서 오히려
            # 유리하다고 판단해 비교 자체를 없앴다. 리스트형(screenshots/videos)도
            # "누적"이 아니라 "새 소스의 세트로 완전 교체". [P0 버그 수정] 기존 파일
            # 삭제는 더 이상 여기서 미리 하지 않는다 - _copy_media_to_masterdb()가
            # 타입별로 "새 파일 복사 성공 확인 후에만" 내부적으로 지우고 교체한다
            # (원본 소스가 깨져 복사가 실패해도 기존 파일이 사라지지 않도록).
            if media_raw:
                existing_media = rom_entry.get("media") or {}
                to_copy = {mtype: (vals if isinstance(vals, list) else [vals]) for mtype, vals in media_raw.items()}
                if to_copy:
                    saved_media = _copy_media_to_masterdb(masterdb_root, canonical, filename, to_copy)
                    if saved_media:
                        merged_media = dict(existing_media)
                        merged_media.update(saved_media)  # 타입별로 완전 교체
                        rom_entry["media"] = merged_media
                        if sqlite_repo is not None:
                            sqlite_repo.ensure_rom(key, canonical, filename)
                            for mtype, val in saved_media.items():
                                sqlite_repo.set_media(key, mtype, val)

            # Preserve the actual Local/ES-DE folder that supplied this version.
            if rom_entry.get("versions"):
                # add_version below will carry source_system; for older DB entries this is harmless.
                pass

            if not has_metadata:
                continue  # media만 동기화, version은 만들지 않음

            if matched_vid is not None:
                result["duplicates_skipped"] += 1
                continue

            new_vid = dbmod.add_version(
                rom_entry,
                source_local_id=local_id,
                fields=fields,
                uncertain_match=uncertain_from_match,
                set_as_default=True,
                source_system=system,
            )
            result["imported"] += 1
            if sqlite_repo is not None:
                sqlite_repo.ensure_rom(key, canonical, filename)
                vdata = rom_entry["versions"][new_vid]
                sqlite_repo.insert_version(
                    key, new_vid, vdata["created_at"], vdata["source_local_id"],
                    vdata["uncertain_match"], vdata["fields"], set_as_default=True,
                )

        if sqlite_repo is not None:
            # GameListSet membership: every rom this scan found that already has a
            # MasterDB entry (created just now, or from an earlier import) counts as
            # a member. A full-local run (target_roms=None) replaces membership to
            # match exactly what the scan found; a filtered/partial run only adds,
            # since roms outside target_roms were never examined this call and
            # their prior membership must not be touched.
            member_keys = []
            for rom in rom_list:
                member_canonical = canonical_system(local_entry, rom["system"])
                member_key = dbmod.make_rom_key(member_canonical, rom["filename"])
                if member_key in db.get("roms", {}):
                    member_keys.append(member_key)
            if target_roms is None:
                sqlite_repo.sync_gamelistset_membership(local_id, member_keys)
            else:
                sqlite_repo.add_gamelistset_members(local_id, member_keys)

    return result


def import_multiple_locals(local_entries, masterdb_root, db, progress_cb=None, sqlite_repo=None):
    """여러 Local을 순차적으로 Import (일괄 처리용)."""
    overall = {}
    for local_entry in local_entries:
        overall[local_entry["id"]] = import_local_to_masterdb(
            local_entry, masterdb_root, db, progress_cb=progress_cb, sqlite_repo=sqlite_repo
        )
    return overall
