"""
db.py
=====
MasterDB (JSON) 로드/저장 및 Version 관리 로직.

스키마 (설계서 v2 부록 A, media는 v0.2.0에서 ROM 레벨로 이동):
{
  "schema_version": 2,
  "system_cores": { "<system>": {"default_core": str, "is_custom": bool} },
  "roms": {
    "<system>|<rom_filename>": {
      "system": str,
      "rom_filename": str,
      "default_version_id": str,
      "core_override": str|null,
      "media": { covers, marquees, miximages, screenshots[], wheel, videos, "3dboxes" },
      "versions": {
        "<version_id>": {
          "created_at": iso8601 str,
          "source_local_id": str,
          "uncertain_match": bool,
          "fields": { name, desc, genre, developer, publisher,
                      releasedate, region, players, rating, tags[] }
        }
      }
    }
  }
}

[중요 설계 원칙] media는 metadata Version과 달리 **ROM 하나당 단일 세트만 관리**한다.
Version은 텍스트 metadata를 여러 개(스크랩 소스별로) 보존하지만, media(이미지/영상)는
저장 용량을 아끼기 위해 버전마다 따로 두지 않고 ROM 레벨에서 공유한다.
즉 어떤 Version을 default로 선택하든 Media 탭에 보이는 이미지는 동일하다.

핵심 규칙 (설계서 v2 §2.2, §11, 부록B):
- ROM 매칭 키 = system + "|" + rom_filename
- Version은 Frontend가 아닌 created_at(Import 시각) 기준으로 정렬된다.
- 동일 metadata 판단: 정규화 타이틀 일치 + ROM의 공유 media(cover) MD5 해시 일치.
  media가 아직 없으면 타이틀만으로 비교하고 uncertain_match=True로 표시.
- media 갱신 정책: 이미 media가 설정된 ROM은 일반 Import로는 자동 덮어쓰지 않는다
  (사용자가 고른 이미지가 매 Import마다 말없이 바뀌는 것을 방지). 스크랩 적용처럼
  사용자가 명시적으로 선택한 행동에서만 overwrite=True로 교체한다.
"""

import json
import time
import hashlib
from pathlib import Path
from datetime import datetime

SCHEMA_VERSION = 2

META_FIELD_KEYS = [
    "name", "desc", "genre", "developer", "publisher",
    "releasedate", "region", "players", "rating", "tags",
]


def empty_db():
    return {
        "schema_version": SCHEMA_VERSION,
        "system_cores": {},
        "roms": {},
        "similar_rom_groups": {},  # [신규] { system: [ {members:[romKey,...], pairs:[...]} , ... ] }
    }


def db_paths(masterdb_root):
    root = Path(masterdb_root)
    return {
        "root": root,
        "db_file": root / "masterdb.json",
        "media_dir": root / "media",
        "rom_dir": root / "roms",
    }


def rom_storage_path(masterdb_root, system, rom_filename):
    """
    [신규] MasterDB에 저장된 ROM 실물 파일의 경로 (masterdb_root/roms/<system>/<filename>).
    schema에 별도 필드를 두지 않고, 파일 존재 여부(Path.exists())로 "MasterDB에 이 ROM이
    저장되어 있는지"를 판단한다 - DB 마이그레이션이 필요 없고 항상 실제 상태와 100% 일치한다.
    """
    return db_paths(masterdb_root)["rom_dir"] / system / rom_filename


def rom_is_stored(masterdb_root, system, rom_filename):
    """MasterDB에 해당 ROM의 실물 파일이 저장되어 있는지."""
    return rom_storage_path(masterdb_root, system, rom_filename).exists()


def ensure_masterdb_structure(masterdb_root):
    paths = db_paths(masterdb_root)
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["media_dir"].mkdir(parents=True, exist_ok=True)
    paths["rom_dir"].mkdir(parents=True, exist_ok=True)
    if not paths["db_file"].exists():
        atomic_write_json(paths["db_file"], empty_db())
    return paths


def _merge_media_dict(dst, src):
    dst = dict(dst or {})
    for k, v in (src or {}).items():
        if k in ("screenshots", "videos"):
            a = dst.get(k) if isinstance(dst.get(k), list) else ([dst[k]] if dst.get(k) else [])
            b = v if isinstance(v, list) else [v]
            seen = {str(x) for x in a}
            dst[k] = a + [x for x in b if x and str(x) not in seen]
        else:
            # Single-image media is logically one slot, but when alias systems
            # (e.g. msx/msx1) are merged we must not let a stale/missing path
            # suppress a valid asset from the other source. Prefer an existing
            # valid destination; otherwise take the first valid source.
            cur = dst.get(k)
            cur_path = cur[0] if isinstance(cur, list) and cur else cur
            if not cur_path or not Path(str(cur_path)).exists():
                src_path = v[0] if isinstance(v, list) and v else v
                if src_path:
                    dst[k] = src_path
    return dst


def normalize_masterdb_systems(data):
    """Merge legacy alias system keys into the ES-DE canonical platform keys.
    This is deliberately data-preserving: versions are appended, media is unioned,
    and the newest version becomes default by version id ordering."""
    try:
        from config import ESDE_SYSTEM_ALIASES
    except Exception:
        return data
    roms = data.get("roms", {})
    merged = {}
    for key, entry in list(roms.items()):
        raw_system = str(entry.get("system", ""))
        canonical = ESDE_SYSTEM_ALIASES.get(raw_system.lower(), raw_system)
        new_key = make_rom_key(canonical, entry.get("rom_filename", ""))
        entry["system"] = canonical
        if new_key not in merged:
            merged[new_key] = entry
        else:
            target = merged[new_key]
            target["media"] = _merge_media_dict(target.get("media"), entry.get("media"))
            for vid, version in (entry.get("versions") or {}).items():
                # Version IDs are globally unique, but protect against a legacy DB
                # containing a collision instead of silently overwriting metadata.
                if vid not in target.setdefault("versions", {}):
                    target["versions"][vid] = version
                else:
                    base_vid = vid
                    n = 2
                    while f"{base_vid}_{n}" in target["versions"]:
                        n += 1
                    target["versions"][f"{base_vid}_{n}"] = version
            vids = list(target.get("versions", {}))
            target["default_version_id"] = max(vids) if vids else target.get("default_version_id")
    data["roms"] = merged
    return data


def load_db(masterdb_root):
    paths = db_paths(masterdb_root)
    if not paths["db_file"].exists():
        return empty_db()
    try:
        with paths["db_file"].open("r", encoding="utf-8") as f:
            data = json.load(f)
        if "roms" not in data:
            data = empty_db()
        # Canonicalize legacy/system-alias entries at load time. This is the important
        # second half of the alias design: import-time canonicalization alone cannot
        # merge entries that were already stored under msx1/famicom/genesis.
        #
        # The merge is data-preserving:
        #   * one canonical ROM entry
        #   * every metadata version from both entries is retained
        #   * media is unioned by type
        #   * the newest version becomes default
        before = json.dumps(data.get("roms", {}), ensure_ascii=False, sort_keys=True)
        data = normalize_masterdb_systems(data)
        after = json.dumps(data.get("roms", {}), ensure_ascii=False, sort_keys=True)
        if before != after:
            # Persist migration immediately so the same legacy aliases do not have to
            # be merged on every application start.
            try:
                atomic_write_json(paths["db_file"], data)
            except Exception:
                pass
        return data
    except Exception:
        return empty_db()

def save_db(masterdb_root, db):
    paths = db_paths(masterdb_root)
    atomic_write_json(paths["db_file"], db)


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# ROM 키 / Version ID
# ---------------------------------------------------------------------------

def make_rom_key(system, rom_filename):
    """ROM 매칭 키: system + rom_filename (설계서 부록B)"""
    return f"{system}|{rom_filename}"


# [BUG FIX - 심각] 기존에는 f"v_{int(time.time()*1000)}" (밀리초 단위)를 ID로 사용했는데,
# 같은 밀리초 안에 add_version()이 여러 번 호출되면(예: Import 배치 처리, 빠른 연속 스크랩 등)
# ID가 충돌해서 rom_entry["versions"]의 딕셔너리 키가 겹쳐 **이전 버전의 데이터가 통째로
# 덮어써져 유실**되는 심각한 문제가 있었다. nanosecond 정밀도 + 모노토닉 카운터로 완전히 차단한다.
_last_version_ns = {"value": 0}


def new_version_id():
    ns = time.time_ns()
    if ns <= _last_version_ns["value"]:
        ns = _last_version_ns["value"] + 1
    _last_version_ns["value"] = ns
    return f"v_{ns}"


def get_or_create_rom_entry(db, system, rom_filename):
    key = make_rom_key(system, rom_filename)
    if key not in db["roms"]:
        db["roms"][key] = {
            "system": system,
            "rom_filename": rom_filename,
            "default_version_id": None,
            "core_override": None,
            "media": {},  # ROM 레벨 단일 media (Version과 무관하게 공유)
            "versions": {},
        }
    return db["roms"][key]


def list_versions_sorted(rom_entry):
    """created_at 기준 오름차순으로 정렬된 (version_id, version_data) 리스트 반환.
    Version은 Frontend가 아닌 Import 시각순으로 매겨진다.

    [BUG FIX] 정렬 키로 created_at(문자열, 밀리초 정밀도) 대신 version_id를 사용한다.
    version_id는 new_version_id()에서 모노토닉 카운터로 생성되어 충돌·동점이 없으므로
    빠르게 연속 생성된 버전들 사이에서도 항상 정확한 순서를 보장한다."""
    versions = rom_entry.get("versions", {})
    return sorted(versions.items(), key=lambda kv: kv[0])


def version_label(rom_entry, version_id):
    """v1, v2, v3 ... 형태의 표시용 라벨 (정렬 순서 기준)"""
    sorted_ids = [vid for vid, _ in list_versions_sorted(rom_entry)]
    if version_id in sorted_ids:
        return f"v{sorted_ids.index(version_id) + 1}"
    return "v?"


def add_version(rom_entry, source_local_id, fields, uncertain_match=False,
                 set_as_default=False, source_system=None):
    """새로운 metadata Version을 추가한다.
    [주의] media는 여기서 다루지 않는다 (ROM 레벨 단일 관리) - 필요 시 set_rom_media()를 별도 호출."""
    vid = new_version_id()
    rom_entry["versions"][vid] = {
        # [BUG FIX] timespec="seconds"였을 때, 한 번의 Import 배치에서 짧은 시간에 여러 Version이
        # 생성되면 created_at이 같은 초로 겹쳐(tie) "최신순 정렬"이 깨지는 문제가 있었음
        # (Python의 stable sort는 reverse=True에서도 동점 항목의 원래 순서를 유지하므로,
        #  타임스탬프가 같으면 실제 생성 순서와 반대로 취급될 수 있음). 밀리초로 정밀도를 높여 방지.
        "created_at": datetime.now().isoformat(timespec="milliseconds"),
        "source_local_id": source_local_id,
        "source_system": source_system or rom_entry.get("system", ""),
        "uncertain_match": uncertain_match,
        "fields": {k: fields.get(k, "" if k != "tags" else []) for k in META_FIELD_KEYS},
    }
    if set_as_default or not rom_entry.get("default_version_id"):
        rom_entry["default_version_id"] = vid
    return vid


def set_rom_media(rom_entry, media_dict, overwrite=False):
    """
    ROM 레벨 공유 media를 설정한다.

    overwrite=False(기본값): 이미 media가 설정되어 있으면 아무 것도 하지 않는다.
        일반 Import는 항상 이 모드를 사용해야 한다 - 사용자가 이미 채택한 이미지가
        매번 Import할 때마다 말없이 다른 소스의 이미지로 바뀌면 안 되기 때문이다.
    overwrite=True: 무조건 교체한다. 스크랩 적용처럼 사용자가 명시적으로
        "이 이미지를 쓰겠다"고 선택한 행동에서만 사용한다.

    반환: 실제로 media가 갱신되었는지 여부 (bool)
    """
    if overwrite or not rom_entry.get("media"):
        rom_entry["media"] = media_dict
        return True
    return False


def update_single_media(rom_entry, media_type, path):
    """
    [GUI 드래그앤드롭용] media 딕셔너리 전체를 갈아치우지 않고, 지정된 media_type
    (예: "covers", "screenshots") 하나만 갱신한다. 사용자가 특정 이미지를 직접
    드래그해서 교체하는 명시적 행동이므로 항상 덮어쓴다 (overwrite=True와 동일한 정책).

    screenshots/videos는 리스트로 관리하는 기존 스키마 관례를 따라 [path] 형태로 저장하고,
    나머지(covers/miximages/wheel/marquees/3dboxes)는 단일 경로 문자열로 저장한다.
    """
    if "media" not in rom_entry:
        rom_entry["media"] = {}
    if media_type in ("screenshots", "videos"):
        rom_entry["media"][media_type] = [path]
    else:
        rom_entry["media"][media_type] = path


def set_default_version(rom_entry, version_id):
    if version_id in rom_entry.get("versions", {}):
        rom_entry["default_version_id"] = version_id
        return True
    return False


def get_default_fields(rom_entry):
    vid = rom_entry.get("default_version_id")
    if vid and vid in rom_entry.get("versions", {}):
        return rom_entry["versions"][vid]["fields"]
    return {k: ("" if k != "tags" else []) for k in META_FIELD_KEYS}


def _is_blank_field_value(key, value):
    if key == "tags":
        return not value
    return str(value or "").strip() == ""


def _is_sentinel_intentional_empty(key, value):
    """사용자가 '.'을 넣어 일부러 비워뒀다는 뜻으로 표시한 필드인지 판별.
    빈 문자열과 달리 채움 대상에서 제외되고, 다른 버전을 채우는 소스로도 쓰이지 않는다
    (진짜 값이 아니라 '비워둠' 표시일 뿐이므로)."""
    if key == "tags":
        return False
    return str(value or "").strip() == "."


def get_filled_fields(rom_entry):
    """default 버전의 필드를 기준으로, 빈 필드만 다른 버전(오래된 순)의 값으로 채운
    합성 dict를 반환한다. 저장된 버전 데이터는 전혀 건드리지 않는 읽기 전용 합성이며,
    detail 화면 표시/Local Export처럼 "최대한 완전한 정보"가 필요한 곳에서만 쓴다.
    (유사롬 후보 수집, Dashboard 통계처럼 10,000-ROM 규모로 순회하는 곳에서는 대신
    get_default_fields()를 그대로 써서 불필요한 연산을 피할 것.)

    - 빈 문자열/공백만 있는 값은 "비어있음"으로 취급해 채움 대상이 된다.
    - "."만 들어있는 필드는 사용자가 의도적으로 비워둔 것으로 보고 채움 대상에서
      제외하고, 다른 필드를 채우는 소스로도 쓰지 않는다.
    - tags는 리스트라 빈 리스트만 "비어있음"으로 취급한다 (sentinel 개념 미적용).
    """
    default_vid = rom_entry.get("default_version_id")
    versions = rom_entry.get("versions") or {}
    base = dict(versions.get(default_vid, {}).get("fields") or {})
    if not base:
        base = {k: ("" if k != "tags" else []) for k in META_FIELD_KEYS}

    missing_keys = [
        k for k in META_FIELD_KEYS
        if _is_blank_field_value(k, base.get(k)) and not _is_sentinel_intentional_empty(k, base.get(k))
    ]
    if not missing_keys:
        return base

    for vid, vdata in list_versions_sorted(rom_entry):  # 오래된 순
        if vid == default_vid or not missing_keys:
            continue
        candidate_fields = vdata.get("fields") or {}
        for k in list(missing_keys):
            v = candidate_fields.get(k)
            if _is_blank_field_value(k, v) or _is_sentinel_intentional_empty(k, v):
                continue
            base[k] = v
            missing_keys.remove(k)

    return base


def delete_version(rom_entry, version_id):
    versions = rom_entry.get("versions", {})
    if version_id in versions:
        del versions[version_id]
        if rom_entry.get("default_version_id") == version_id:
            remaining = list_versions_sorted(rom_entry)
            rom_entry["default_version_id"] = remaining[-1][0] if remaining else None
        return True
    return False


def clone_version(rom_entry, version_id, source_local_id="manual"):
    """지정된 Version을 복제하여 새 Version으로 추가 (media는 ROM 레벨 공유이므로 복제 불필요)."""
    versions = rom_entry.get("versions", {})
    src = versions.get(version_id)
    if not src:
        return None
    return add_version(
        rom_entry, source_local_id,
        fields=dict(src["fields"]),
        uncertain_match=False,
    )


# ---------------------------------------------------------------------------
# 동일 metadata 판단 (중복 version 생성 방지) - 설계서 §3.1, 부록B
# ---------------------------------------------------------------------------

def file_md5(path):
    """썸네일(cover) 파일의 MD5 해시. 파일이 없으면 None."""
    p = Path(path) if path else None
    if not p or not p.exists() or not p.is_file():
        return None
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def file_sha256(path):
    """[신규] ROM 실물 파일의 SHA256. No-Intro/Redump 같은 외부 카탈로그와 대조하는
    용도라 md5보다 sha256을 쓴다. ROM은 수백MB~수GB일 수 있어 file_md5보다 큰
    1MB 청크로 읽는다(메모리에 통째로 올리지 않음). 파일이 없으면 None."""
    p = Path(path) if path else None
    if not p or not p.exists() or not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_same_metadata(existing_fields, existing_cover_path, new_fields, new_cover_path):
    """
    동일 metadata(중복 version) 판단.
    반환: (is_same: bool, uncertain: bool)

    규칙:
    1) 정규화 타이틀이 다르면 -> 다른 metadata (False, False)
    2) 정규화 타이틀이 같고 두 cover 모두 존재 -> MD5 비교로 최종 판단
    3) 정규화 타이틀이 같은데 cover가 한쪽이라도 없음 -> 동일한 것으로 간주하되 uncertain=True
    """
    from utils import normalize_title  # 지연 import(순환 방지)

    t1 = normalize_title(existing_fields.get("name", ""))
    t2 = normalize_title(new_fields.get("name", ""))
    if t1 != t2 or not t1:
        return False, False

    h1 = file_md5(existing_cover_path)
    h2 = file_md5(new_cover_path)
    if h1 is None or h2 is None:
        # thumbnail 미존재 -> 타이틀만으로 매칭, 불확실 표시
        return True, True

    return (h1 == h2), False


def find_matching_version(rom_entry, new_fields, new_cover_path):
    """새로 들어온 metadata가 기존 version 중 하나와 동일한지 검사.
    cover는 ROM 레벨에서 공유되므로 rom_entry["media"]의 것과 비교한다.
    동일 version이 있으면 (version_id, uncertain) 반환, 없으면 (None, False)."""
    existing_cover = rom_entry.get("media", {}).get("covers")
    for vid, vdata in rom_entry.get("versions", {}).items():
        same, uncertain = is_same_metadata(
            vdata["fields"], existing_cover, new_fields, new_cover_path
        )
        if same:
            return vid, uncertain
    return None, False


# ---------------------------------------------------------------------------
# Core override
# ---------------------------------------------------------------------------

def get_effective_core(db, rom_entry):
    """ROM에 적용될 실제 core: core_override 우선, 없으면 system_cores 기본값."""
    if rom_entry.get("core_override"):
        return rom_entry["core_override"]
    sc = db.get("system_cores", {}).get(rom_entry["system"])
    return sc["default_core"] if sc else None


def set_system_default_core(db, system, core_name, is_custom=False):
    db.setdefault("system_cores", {})[system] = {
        "default_core": core_name,
        "is_custom": is_custom,
    }


def apply_core_to_all_roms_in_system(db, system, core_name):
    """Core 설정 대화창의 '모든 롬에 덮어쓰기' 옵션 처리."""
    count = 0
    for rom_entry in db["roms"].values():
        if rom_entry["system"] == system:
            rom_entry["core_override"] = core_name
            count += 1
    return count


# ---------------------------------------------------------------------------
# 중복 ROM 판정 (설계서 §9, 부록B)
# ---------------------------------------------------------------------------

def find_duplicate_roms(db):
    """동일 게임(정규화 타이틀)에 서로 다른 ROM 파일이 매핑된 경우를 그룹으로 반환.
    반환: { normalized_title: [rom_key, ...] } (2개 이상인 것만)"""
    from utils import normalize_title

    groups = {}
    for rom_key, rom_entry in db["roms"].items():
        fields = get_default_fields(rom_entry)
        title = normalize_title(fields.get("name", ""))
        if not title:
            continue
        groups.setdefault(title, []).append(rom_key)
    return {t: keys for t, keys in groups.items() if len(keys) > 1}


# ---------------------------------------------------------------------------
# Missing 판정 (설계서 §8, 부록B: Title + Description 둘 다 있어야 완료)
# ---------------------------------------------------------------------------

def rom_status(rom_entry):
    """'완료' | '완료(?)' | '부분' | '누락' 반환"""
    fields = get_default_fields(rom_entry)
    has_title = bool(fields.get("name", "").strip())
    has_desc = bool(fields.get("desc", "").strip())

    vid = rom_entry.get("default_version_id")
    uncertain = False
    if vid and vid in rom_entry.get("versions", {}):
        uncertain = rom_entry["versions"][vid].get("uncertain_match", False)

    if has_title and has_desc:
        return "완료(?)" if uncertain else "완료"
    if has_title or has_desc:
        return "부분"
    return "누락"


# ---------------------------------------------------------------------------
# Version 필드 마이그레이션 / 정리 (설계서 v2 후속 §Version Cleanup, §Ver Diff)
# ---------------------------------------------------------------------------

def is_version_empty(fields):
    """
    Version(또는 편집 중인 field set)이 '빈 메타데이터'인지 판단.
    기준: 제목(name)과 Description(desc)이 '둘 다' 있어야 비어있지 않은 것으로 간주.
    (rom_status()의 완료 판정과 동일한 기준 - 다른 필드가 채워져 있어도
     제목/설명 중 하나라도 없으면 정리 대상 '빈 메타데이터'로 취급)
    """
    has_title = bool(str(fields.get("name", "")).strip())
    has_desc = bool(str(fields.get("desc", "")).strip())
    return not (has_title and has_desc)


def migrate_unique_fields(source_fields, target_fields):
    """
    target_fields에서 비어있는(값이 없거나 "") 필드를, source_fields에 값이 있으면
    그 값으로 채운 새로운 dict를 반환한다. target에 이미 값이 있는 필드는 건드리지 않는다.
    (Version 일괄 정리 §A, Ver Diff 삭제 시 정보 보존 §B 양쪽에서 공용으로 사용)
    """
    merged = dict(target_fields)
    for key in META_FIELD_KEYS:
        if key == "tags":
            if not merged.get("tags") and source_fields.get("tags"):
                merged["tags"] = list(source_fields["tags"])
            continue
        if not str(merged.get(key, "")).strip() and str(source_fields.get(key, "")).strip():
            merged[key] = source_fields[key]
    return merged


def cleanup_non_default_versions(db):
    """
    [설정 > Metadata 설정 > 버전 일괄 정리] 에서 호출.
    전체 MasterDB의 모든 ROM에 대해:
    1. default가 아닌 Version들 중 default에 없는(빈) 필드를 최신(latest) 순으로 채움
       (여러 non-default 버전이 같은 빈 필드에 대해 서로 다른 값을 가지면 더 최근 것이 우선)
    2. default를 제외한 모든 Version을 삭제

    media는 이미 ROM 레벨에서 단일 관리되므로 이 작업의 영향을 받지 않는다.

    반환: { "roms_processed": int, "versions_removed": int }
    """
    roms_processed = 0
    versions_removed = 0

    for rom_entry in db.get("roms", {}).values():
        default_vid = rom_entry.get("default_version_id")
        versions = rom_entry.get("versions", {})
        if not default_vid or default_vid not in versions:
            continue

        non_default = [(vid, v) for vid, v in versions.items() if vid != default_vid]
        if not non_default:
            continue

        # 최신(latest) 우선으로 채우기 위해 version_id(생성 순서 보장) 내림차순으로 순회.
        # migrate_unique_fields는 target이 이미 채워진 필드는 건드리지 않으므로,
        # 먼저 순회하는(=더 최신인) 버전의 값이 우선 적용된다.
        # [BUG FIX] created_at(밀리초 정밀도) 대신 version_id로 정렬 - 동점 문제 없음.
        non_default_sorted = sorted(non_default, key=lambda kv: kv[0], reverse=True)

        target_fields = dict(versions[default_vid]["fields"])
        for _vid, vdata in non_default_sorted:
            target_fields = migrate_unique_fields(vdata["fields"], target_fields)
        versions[default_vid]["fields"] = target_fields

        for vid, _ in non_default:
            del versions[vid]
            versions_removed += 1

        rom_entry["default_version_id"] = default_vid
        roms_processed += 1

    return {"roms_processed": roms_processed, "versions_removed": versions_removed}


def delete_rom_storage(masterdb_root, system, rom_filename, media=None):
    """Remove the physical MasterDB ROM and its ROM-level media safely."""
    import shutil
    paths = db_paths(masterdb_root)
    rom_path = paths["rom_dir"] / system / rom_filename
    if rom_path.exists() and rom_path.is_file():
        try: rom_path.unlink()
        except OSError: pass
    media_dir = paths["media_dir"] / system / Path(rom_filename).stem
    if media_dir.exists() and media_dir.is_dir():
        shutil.rmtree(media_dir, ignore_errors=True)
