"""
importers/pegasus.py
=====================
Pegasus Frontend 구조 감지 및 스캔.

구조 (Pegasus 표준):
  root/<system>/metadata.pegasus.txt   (게임 정보, key: value 텍스트 포맷)
  root/<system>/<rom files>            (ROM과 metadata가 같은 폴더 - same_dir=True)
  root/<system>/media/<rom_stem>/boxFront.png 등 (게임별 서브폴더 media 구조가 흔함)

config.FRONTEND_ROM_METADATA_SAME_DIR["pegasus"] = True 이므로
rom_path == metadata_path로 취급된다 (GUI에서 rom 경로 필드 비활성/미러링).
"""

from pathlib import Path
from .base import list_rom_files_in_dir


def detect_structure(rom_path, metadata_path, media_path):
    # same_dir이므로 metadata_path를 기준으로 검사 (rom_path와 동일해야 함)
    root = Path(metadata_path) if metadata_path else None
    if not root or not root.exists():
        return "invalid", "경로가 존재하지 않습니다."

    system_dirs = [d for d in root.iterdir() if d.is_dir()]
    if not system_dirs:
        return "warning", "시스템 폴더가 없습니다."

    found_txt = any((d / "metadata.pegasus.txt").exists() for d in system_dirs)
    if not found_txt:
        return "warning", "metadata.pegasus.txt 파일을 찾을 수 없습니다."

    return "valid", f"{len(system_dirs)}개 시스템 폴더 확인됨."


def list_systems(rom_path, metadata_path):
    root = Path(metadata_path)
    if not root.exists():
        return []
    return sorted([d.name for d in root.iterdir() if d.is_dir()])


def list_roms(rom_path, system):
    # same_dir이므로 rom_path == metadata_path
    return list_rom_files_in_dir(Path(rom_path) / system)


def _parse_pegasus_txt(path: Path):
    """metadata.pegasus.txt 를 game 블록 단위(빈 줄 구분)로 파싱하여
    { file_value: {key: value} } 형태로 반환하는 간이 파서."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n\s*\n", text)
    games = {}
    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip() and not l.strip().startswith("#")]
        if not lines:
            continue
        entry = {}
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                entry[k.strip().lower()] = v.strip()
        file_val = entry.get("file")
        if file_val:
            games[Path(file_val).name] = entry
    return games


import re  # noqa: E402  (지역 함수에서 사용)


def has_metadata(metadata_path, system, rom_filename):
    txt = Path(metadata_path) / system / "metadata.pegasus.txt"
    games = _parse_pegasus_txt(txt)
    return rom_filename in games


def has_media(media_path, system, rom_filename):
    stem = Path(rom_filename).stem
    media_dir = Path(media_path) / system / "media" / stem
    return media_dir.exists() and any(media_dir.iterdir())


def read_metadata_fields(metadata_path, system, rom_filename):
    """metadata.pegasus.txt에서 rom_filename에 해당하는 game 블록을 찾아
    db.META_FIELD_KEYS 형식으로 반환. 없으면 None."""
    txt = Path(metadata_path) / system / "metadata.pegasus.txt"
    games = _parse_pegasus_txt(txt)
    entry = games.get(rom_filename)
    if entry is None:
        return None

    genre_raw = entry.get("genre", "")
    tags_raw = entry.get("tags", "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else \
           ([g.strip() for g in genre_raw.split(",") if g.strip()] if genre_raw else [])

    return {
        "name": entry.get("game", ""),
        "desc": entry.get("description", ""),
        "genre": genre_raw,
        "developer": entry.get("developer", ""),
        "publisher": entry.get("publisher", ""),
        "releasedate": entry.get("release", ""),
        "region": entry.get("region", ""),
        "players": entry.get("players", ""),
        "rating": entry.get("rating", ""),
        "tags": tags,
    }


def read_media(media_path, system, rom_filename, game_title=None, media_types=None):
    """Pegasus media: root/<system>/media/<rom_stem>/<assetname>.png 구조.
    boxFront->covers, screenshot->screenshots, marquee->marquees,
    background/fanart->miximages, wheel/logo->wheel 로 매핑한다.
    media_types: [체감 속도, Scan 2단계] 한 폴더를 통째로 iterdir하는 구조라 필터링해도
    I/O는 줄지 않지만, 다른 frontend와 인터페이스를 맞추기 위해 결과만 걸러서 반환한다."""
    stem = Path(rom_filename).stem
    media_dir = Path(media_path) / system / "media" / stem
    if not media_dir.exists():
        return {}

    asset_map = {
        "boxfront": "covers",
        "cover": "covers",
        "screenshot": "screenshots",
        "marquee": "marquees",
        "background": "miximages",
        "fanart": "miximages",
        "wheel": "wheel",
        "logo": "wheel",
        "video": "videos",
    }
    wanted_types = set(media_types) if media_types is not None else None
    result = {}
    for f in media_dir.iterdir():
        if not f.is_file():
            continue
        key = f.stem.lower()
        mtype = asset_map.get(key)
        if mtype and (wanted_types is None or mtype in wanted_types):
            result.setdefault(mtype, []).append(str(f))
    return result
