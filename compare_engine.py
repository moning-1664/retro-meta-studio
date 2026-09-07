"""
compare_engine.py
==================
9단계: Compare 화면 - 두 소스(GameListSet 대 GameListSet, 또는 MasterDB 대
GameListSet) 사이에 ROM이 어느 쪽에 있는지/양쪽 metadata가 다른지 비교한다
(Beyond Compare 스타일 2열 정렬 리스트).

매칭 규칙은 export_engine.py의 MasterDB 매칭과 동일하게 "같은 시스템 내에서만,
정확한 파일명 우선 -> 정규화 파일명 유일 후보만 fallback"을 그대로 재사용한다
(export_engine._find_masterdb_rom과 같은 알고리즘을 두 개의 임의 entry 목록에
적용할 수 있게 일반화한 버전).

entry 하나의 최소 형태: {"system": str, "filename": str, "fields": dict|None}
fields는 db.META_FIELD_KEYS 하위 키(name/desc/genre/...)를 담은 dict - diff 판정에만
쓰이고 없으면(None) diff 판정은 항상 False로 취급한다(둘 다 있어야 비교 가능).
"""

from importers import get_importer
from importers.scan import scan_local
import db as dbmod
from config import canonical_system
from utils import rom_match_keys, is_korean_rom


DIFF_FIELDS = ("name", "desc", "genre", "developer", "publisher", "releasedate", "region", "players", "rating")


def _build_match_index(entries):
    """[P1 성능 수정] 예전엔 정확한 파일명 매치를 `_find_match`가 매번 entries
    전체를 순회해서 찾았다(정규화 fallback용 인덱스는 이미 있었는데, 정확 매치는
    인덱싱을 안 함) - 왼쪽 목록 N개 * 오른쪽 목록 M개 조합이라 최악의 경우 O(N*M)
    (10,000 ROM 규모면 실질적으로 큰 지연). exact 매치도 (system, filename) ->
    index의 dict로 미리 만들어 O(1) 조회가 되게 한다."""
    index = {}
    exact_index = {}
    for i, e in enumerate(entries):
        sys_index = index.setdefault(e["system"], {})
        for key in rom_match_keys(e["filename"]):
            sys_index.setdefault(key, []).append(i)
        # 리스트로 보관 - collect_local_entries/collect_masterdb_entries는 각각
        # (system, filename) 중복을 만들지 않는 게 현재 불변조건이지만, 이 함수는
        # 그 가정에 기대지 않고도 정확하게 동작하도록 방어적으로 짠다.
        exact_index.setdefault((e["system"], e["filename"]), []).append(i)
    return index, exact_index


def _find_match(index, exact_index, system, filename, used):
    for i in exact_index.get((system, filename), ()):
        if i not in used:
            return i
    sys_index = index.get(system, {})
    for key in rom_match_keys(filename):
        candidates = [i for i in sys_index.get(key, []) if i not in used]
        if len(candidates) == 1:
            return candidates[0]
    return None


def _fields_differ(a, b):
    if not a or not b:
        return False
    for k in DIFF_FIELDS:
        va, vb = a.get(k, ""), b.get(k, "")
        if str(va or "").strip() != str(vb or "").strip():
            return True
    return False


def compare_entries(left_entries, right_entries, system=None):
    """left_entries/right_entries: list of {"system","filename","fields"}.

    반환: 파일명 기준 정렬된 row 리스트. 각 row:
    {"system", "file", "left": entry_or_None, "right": entry_or_None,
     "matched": bool, "diff": bool}
    """
    if system and system != "all":
        left_entries = [e for e in left_entries if e["system"] == system]
        right_entries = [e for e in right_entries if e["system"] == system]

    right_index, right_exact_index = _build_match_index(right_entries)
    used_right = set()
    rows = []
    for left in left_entries:
        ri = _find_match(right_index, right_exact_index, left["system"], left["filename"], used_right)
        right = None
        diff = False
        if ri is not None:
            used_right.add(ri)
            right = right_entries[ri]
            diff = _fields_differ(left.get("fields"), right.get("fields"))
        rows.append({
            "system": left["system"], "file": left["filename"],
            "left": left, "right": right, "matched": right is not None, "diff": diff,
        })
    for ri, right in enumerate(right_entries):
        if ri in used_right:
            continue
        rows.append({
            "system": right["system"], "file": right["filename"],
            "left": None, "right": right, "matched": False, "diff": False,
        })

    rows.sort(key=lambda r: (r["system"], r["file"].lower()))
    return rows


def collect_local_entries(local_entry, scan_result=None):
    """Local(GameListSet)의 전체 ROM/metadata-only 항목을 compare_entries가 쓸 수
    있는 형태로 수집한다. 실제 metadata 필드까지 읽어와야 diff 판정이 정확하다
    (scan_local()의 GUI용 요약 dict는 developer/publisher/players가 빠져있어
    부정확한 [d] 표시로 이어짐).

    [P1 버그 수정] "system"에는 MasterDB와 동일 기준의 canonical system(예: msx1 ->
    msx)을 담는다 - import_engine.py가 MasterDB에 저장할 때 canonical_system()을
    거치는 것과 똑같은 변환이다. Compare가 이 변환 없이 raw Local system으로만
    매칭했으면, 같은 게임이라도 msx1 Local과 msx MasterDB/다른 Local이 서로 다른
    system으로 취급되어 "왼쪽에만 있음"/"오른쪽에만 있음"으로 잘못 표시될 수 있었다.
    원래의 raw system은 "raw_system"에 별도로 보존한다 - compare_copy_row가 이
    Local로 다시 Import할 때는 반드시 raw system이 필요하기 때문이다(import_engine의
    rom_list는 raw system 기준으로 채워지고, target_roms 필터링도 raw system을
    비교한다 - canonical은 오직 MasterDB 저장 키를 만들 때만 씀)."""
    frontend = local_entry["frontend"]
    importer = get_importer(frontend)
    scan_result = scan_result or scan_local(local_entry, progress_cb=None)

    seen = set()
    entries = []
    for rom in scan_result.get("rom_list", []):
        system, filename = rom["system"], rom["filename"]
        seen.add((system, filename))
        fields = rom.get("_fields")
        if fields is None and rom.get("has_metadata"):
            try:
                fields = importer.read_metadata_fields(local_entry["metadata_path"], system, filename)
            except Exception:
                fields = None
        entries.append({
            "system": canonical_system(local_entry, system), "raw_system": system,
            "filename": filename, "fields": fields,
            # [신규] scan_result["rom_list"]는 실제 ROM 파일이 있는 항목만 채워지므로
            # (metadata-only 항목은 아래 metadata_entries 루프에서만 옴) 항상 True.
            "rom_matched": True,
        })

    for m in scan_result.get("metadata_entries", []):
        key = (m.get("system"), m.get("filename"))
        if key in seen:
            continue
        # [P0 버그 수정, 2026-09-02] scan_local()이 metadata_entries에 채우는 키는
        # "_fields"(언더스코어)인데 여기서는 "fields"로 읽고 있었다 - 항상 None이
        # 되어, ROM 실물이 없는(metadata-only) 항목은 Compare에서 FILE만 보이고
        # TITLE/DESCRIPTION이 전부 비어 보이는 원인이었다. 혹시 다른 호출자가 "fields"
        # 키로 넘길 가능성에도 방어적으로 대응하도록 or 폴백을 남겨둔다.
        entries.append({
            "system": canonical_system(local_entry, m["system"]), "raw_system": m["system"],
            "filename": m["filename"], "fields": m.get("_fields") or m.get("fields"),
            # [신규] 이 루프는 "rom_list(실제 ROM 파일)에 없던" 항목만 처리하므로 항상
            # ROM 실물이 없다 - Compare에서 파일명을 빨간색으로 표시하는 데 쓴다.
            "rom_matched": False,
        })

    return entries


def collect_masterdb_entries(db, system=None, favorite_keys=None, masterdb_root=None):
    """MasterDB의 ROM 전체를 compare_entries가 쓸 수 있는 형태로 수집한다.
    Local export에 실제로 쓰이는 값과 동일 기준(get_filled_fields)을 사용한다.
    MasterDB에 저장된 system은 이미 canonical이므로 raw_system도 동일하게 둔다
    (별도의 raw 형태가 없음 - export_engine의 target_roms 매칭도 이 canonical
    system을 그대로 쓴다).

    favorite_keys: [신규] 즐겨찾기 필터(Compare 필터바)용. favorite은 SQLite-only
    플래그라 MasterDB(=ArchiveDB) 항목에만 존재하고 GameListSet 원본 파일에는
    대응 개념이 없다 - collect_local_entries()는 이 필드를 아예 안 채운다.

    masterdb_root: [신규] 넘겨주면 ROM 실물 파일이 실제로 디스크에 있는지 stat으로
    확인해 "rom_matched"를 채운다(Compare에서 파일명 빨간색 표시용) - MasterDB는
    metadata만 있고 ROM 실물이 없는 항목("Missing ROM")이 있을 수 있다. 안 넘기면
    (예: 기존 테스트) 항상 True로 - 이 함수가 이미 알고 있던 기존 동작을 그대로
    유지한다."""
    favorite_keys = favorite_keys or set()
    entries = []
    for rom_key, rom_entry in db.get("roms", {}).items():
        rom_system = rom_entry.get("system", "")
        if system and system != "all" and rom_system != system:
            continue
        filename = rom_entry.get("rom_filename", "")
        if masterdb_root is not None:
            rom_matched = dbmod.rom_storage_path(masterdb_root, rom_system, filename).exists()
        else:
            rom_matched = True
        entries.append({
            "system": rom_system, "raw_system": rom_system,
            "filename": filename,
            "fields": dbmod.get_filled_fields(rom_entry),
            "favorite": rom_key in favorite_keys,
            "rom_matched": rom_matched,
        })
    return entries


def summarize_entry(entry):
    """GUI 리스트에 file명 옆에 붙일 간단한 정보(title/releasedate) + 복사 액션에
    필요한 정확한 system/filename(표시용 row.file과 달리 fallback 매칭 시 좌/우
    파일명이 다를 수 있으므로 각 side가 자기 자신의 실제 system/filename을 갖고 있어야
    compare_copy_row가 엉뚱한 파일을 대상으로 삼지 않는다).

    [P1 버그 수정] 여기서 돌려주는 "system"은 (매칭용 canonical이 아니라) raw_system -
    compare_copy_row가 그대로 api.import_local_to_masterdb(target_roms=...)에 넘기는데,
    그 필터링은 raw Local system 기준이라 canonical을 넘기면 msx1 Local의 항목을 못
    찾는다. row 자체의 "system"(그룹/필터용, compare_entries가 채움)은 여전히
    canonical을 유지한다 - 이 함수가 만드는 건 row.left/row.right 쪽 값이다."""
    if entry is None:
        return None
    fields = entry.get("fields") or {}
    return {
        "system": entry.get("raw_system", entry.get("system", "")),
        "filename": entry.get("filename", ""),
        "title": fields.get("name", ""),
        "desc": fields.get("desc", ""),
        "releasedate": fields.get("releasedate", ""),
        "korean": is_korean_rom(entry.get("filename", "")),
        "favorite": bool(entry.get("favorite", False)),
        # [신규] ROM 실물이 없는(metadata-only) 항목을 GUI가 빨간색으로 표시하는 데 씀.
        "romMatched": bool(entry.get("rom_matched", True)),
    }
