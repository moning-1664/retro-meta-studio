"""
exporters/retroarch_lpl.py
============================
MasterDB -> RetroArch Playlist(.lpl) Export (설계서 v2 §3.3).

시스템 단위로만 지원. 각 엔트리의 core는
rom.core_override ?? system_cores[system].default_core 값을 사용한다.

[중요] "실제 ROM을 읽어 CRC32를 계산할 로컬 경로"와
"플레이리스트에 기록될 대상 경로(target path)"를 분리해서 받는다.
이 둘이 다를 수 있는 대표적인 경우: 이 프로그램은 Windows에서 실행되지만,
생성된 .lpl 파일은 안드로이드(다이지쇼/RetroArch for Android 등)에 복사해서 쓰는 경우.
이때 target path는 "/storage/emulated/0/ROMs/snes"처럼 Windows에는 존재하지 않는
가상의 경로 문자열일 수 있으므로 폴더 선택 대화창이 아닌 텍스트 입력으로 받아야 하고,
pathlib으로 감싸면 실행 OS(Windows)의 구분자(\\)로 강제 변환되어버리므로
target path는 항상 순수 문자열 + forward-slash 조합으로만 다룬다 (Path 객체 사용 금지).

core_path는 실제 설치 환경에 따라 달라지므로 "DETECT"로 두고
core_name에 참고용 core 이름을 기록한다.
"""

import json
import zlib
from pathlib import Path

import db as dbmod


def _crc32_of_file(path: Path, chunk_size=1024 * 1024):
    """ROM 파일의 CRC32 계산. 파일이 없거나 읽기 실패 시 None."""
    if not path.exists() or not path.is_file():
        return None
    crc = 0
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                crc = zlib.crc32(chunk, crc)
        return f"{crc & 0xFFFFFFFF:08X}"
    except Exception:
        return None


def _join_target_path(target_path_prefix, rom_filename):
    """
    플레이리스트에 기록될 경로를 순수 문자열로 조합 (forward-slash 고정).
    pathlib을 쓰지 않는 이유: Windows에서 실행 중이라도 target_path_prefix가
    안드로이드 등 다른 기기의 경로일 수 있어 실행 OS 구분자로 강제 변환되면 안 됨.
    """
    prefix = target_path_prefix.replace("\\", "/").rstrip("/")
    return f"{prefix}/{rom_filename}"


def build_playlist_for_system(db, system, crc_source_path, target_path_prefix=None):
    """
    시스템 하나에 대한 RetroArch playlist(dict) 구성.

    crc_source_path: CRC32 계산을 위해 실제로 ROM 파일을 읽어올 로컬(이 기기에서 접근 가능한) 경로.
    target_path_prefix: playlist "path" 필드에 실제로 기록될 경로 문자열.
        생략하면 crc_source_path를 그대로 사용(기존 동작과 동일, 같은 기기에서 쓸 때).
        안드로이드 등 다른 기기에서 쓸 .lpl을 만들 때는 반드시 이 값을 별도로 지정해야 한다
        (예: "/storage/emulated/0/ROMs/snes").
    """
    items = []
    crc_root = Path(crc_source_path)
    target_prefix = target_path_prefix if target_path_prefix is not None else crc_source_path

    for rom_key, rom_entry in db.get("roms", {}).items():
        if rom_entry["system"] != system:
            continue

        rom_filename = rom_entry["rom_filename"]
        local_rom_file = crc_root / rom_filename  # CRC 계산은 로컬(이 기기)에서 실제로 읽어야 함
        fields = dbmod.get_default_fields(rom_entry)
        core_name = dbmod.get_effective_core(db, rom_entry)

        crc = _crc32_of_file(local_rom_file)
        crc_field = f"{crc}|crc" if crc else "DETECT"

        items.append({
            "path": _join_target_path(target_prefix, rom_filename),  # [FIX] 항상 forward-slash 문자열
            "label": fields.get("name") or rom_filename,
            "core_path": "DETECT",
            "core_name": core_name or "DETECT",
            "crc32": crc_field,
            "db_name": f"{system}.lpl",
        })

    playlist = {
        "version": "1.5",
        "default_core_path": "",
        "default_core_name": "",
        "label_display_mode": 0,
        "right_thumbnail_mode": 0,
        "left_thumbnail_mode": 0,
        "thumbnail_match_mode": 0,
        "sort_mode": 0,
        "items": items,
    }
    return playlist


def export_system_to_lpl(db, system, crc_source_path, save_dir, filename=None, target_path_prefix=None):
    """playlist를 .lpl(JSON) 파일로 저장. 반환: 저장된 파일 경로(str)."""
    playlist = build_playlist_for_system(db, system, crc_source_path, target_path_prefix=target_path_prefix)
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = filename or f"{system}.lpl"
    out_path = save_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(playlist, f, ensure_ascii=False, indent=2)
    return str(out_path)
