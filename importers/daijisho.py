"""
importers/daijisho.py
======================
다이지쇼(Daijisho) 구조 감지 및 스캔.

※ 다이지쇼는 주로 Android 앱이며 PC에서의 표준 폴더 구조가 ES-DE/Pegasus만큼
  명확히 공개되어 있지 않다. 아래 구조는 "Platform 폴더 안에 ROM과 export된
  JSON 메타데이터/미디어가 함께 있는" 일반적인 형태를 가정한 것이며,
  실제 사용자 환경 샘플 확보 후 검증/수정이 필요하다.

가정 구조 (same_dir=True):
  root/<system>/<rom files>
  root/<system>/platform.json          (게임 목록 + metadata, 다이지쇼 export 형식 가정)
  root/<system>/media/<rom_stem>.png   (media, stem 매칭)
"""

import json
from pathlib import Path
from .base import list_rom_files_in_dir, stem_matches_any


def detect_structure(rom_path, metadata_path, media_path):
    root = Path(metadata_path) if metadata_path else None
    if not root or not root.exists():
        return "invalid", "경로가 존재하지 않습니다."

    system_dirs = [d for d in root.iterdir() if d.is_dir()]
    if not system_dirs:
        return "warning", "시스템 폴더가 없습니다."

    found_json = any((d / "platform.json").exists() for d in system_dirs)
    if not found_json:
        return "warning", "platform.json을 찾을 수 없습니다. (다이지쇼 구조 확인 필요 - 가정 기반 구현)"

    return "valid", f"{len(system_dirs)}개 시스템 폴더 확인됨. (다이지쇼 구조는 가정 기반이므로 실제 데이터로 검증 권장)"


def list_systems(rom_path, metadata_path):
    root = Path(metadata_path)
    if not root.exists():
        return []
    return sorted([d.name for d in root.iterdir() if d.is_dir()])


def list_roms(rom_path, system):
    return list_rom_files_in_dir(Path(rom_path) / system)


def _load_platform_json(path: Path):
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # 가정: {"games": [{"file": "...", "title": "...", ...}, ...]}
        games = {}
        for g in data.get("games", []):
            fname = g.get("file")
            if fname:
                games[Path(fname).name] = g
        return games
    except Exception:
        return {}


def has_metadata(metadata_path, system, rom_filename):
    games = _load_platform_json(Path(metadata_path) / system / "platform.json")
    return rom_filename in games


def has_media(media_path, system, rom_filename):
    stem = Path(rom_filename).stem
    media_dir = Path(media_path) / system / "media"
    return stem_matches_any(stem, media_dir)


def read_metadata_fields(metadata_path, system, rom_filename):
    """다이지쇼 실제 구조 확인 전까지 미구현. import_engine에서 이 예외를 잡아
    해당 Local의 Import를 건너뛰고 경고 로그를 남긴다."""
    raise NotImplementedError(
        "다이지쇼 metadata 파싱은 실제 폴더 구조 확인 후 구현 예정입니다."
    )


def read_media(media_path, system, rom_filename, game_title=None, media_types=None):
    raise NotImplementedError(
        "다이지쇼 media 파싱은 실제 폴더 구조 확인 후 구현 예정입니다."
    )
