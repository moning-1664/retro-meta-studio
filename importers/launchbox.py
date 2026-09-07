"""
importers/launchbox.py
=======================
LaunchBox 구조 감지 및 스캔.

구조 (LaunchBox 표준, 비교적 잘 알려져 있음):
  metadata_path/Data/Platforms/<system>.xml   (플랫폼 하나당 XML 파일 하나, 모든 게임 정보 포함)
  media_path/Images/<system>/Box - Front/<title>.jpg  (제목 기반 파일명, ROM stem과 다를 수 있음)
  rom_path/<system>/<rom files>               (ROM 루트는 별도 지정 가능, same_dir=False)

※ LaunchBox의 media 파일명은 "게임 Title" 기준이라 ROM 파일명과 다를 수 있어
  설계서 §3.1 "ROM stem == media stem" 규칙이 그대로 적용되지 않는 케이스가 있다.
  1차 구현에서는 ROM stem 기준으로 시도하고, 매칭 실패 시 XML 내 Title 필드를
  기준으로 media를 찾는 2차 폴백을 3단계(Import 로직)에서 추가할 예정.
"""

from pathlib import Path
import xml.etree.ElementTree as ET
from .base import list_rom_files_in_dir, stem_matches_any


def detect_structure(rom_path, metadata_path, media_path):
    rom_path = Path(rom_path) if rom_path else None
    metadata_path = Path(metadata_path) if metadata_path else None

    if not rom_path or not rom_path.exists():
        return "invalid", "ROM 경로가 존재하지 않습니다."
    if not metadata_path or not metadata_path.exists():
        return "invalid", "Metadata 경로가 존재하지 않습니다."

    platforms_dir = metadata_path / "Data" / "Platforms"
    if not platforms_dir.exists():
        return "warning", "Data/Platforms 폴더를 찾을 수 없습니다."

    system_dirs = [d for d in rom_path.iterdir() if d.is_dir()]
    if not system_dirs:
        return "warning", "ROM 경로 하위에 시스템 폴더가 없습니다."

    return "valid", f"{len(system_dirs)}개 시스템 폴더 확인됨."


def list_systems(rom_path, metadata_path):
    rom_path = Path(rom_path)
    if not rom_path.exists():
        return []
    return sorted([d.name for d in rom_path.iterdir() if d.is_dir()])


def list_roms(rom_path, system):
    return list_rom_files_in_dir(Path(rom_path) / system)


def _load_platform_xml(path: Path):
    """<Game><ApplicationPath>...</ApplicationPath></Game> 형태에서 ROM 파일명 추출."""
    if not path.exists():
        return {}
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        games = {}
        for game in root.findall("Game"):
            app_path = game.findtext("ApplicationPath", "")
            if app_path:
                games[Path(app_path).name] = game
        return games
    except Exception:
        return {}


def has_metadata(metadata_path, system, rom_filename):
    xml_path = Path(metadata_path) / "Data" / "Platforms" / f"{system}.xml"
    games = _load_platform_xml(xml_path)
    return rom_filename in games


def has_media(media_path, system, rom_filename):
    stem = Path(rom_filename).stem
    box_front_dir = Path(media_path) / "Images" / system / "Box - Front"
    # 1차: ROM stem 기준 매칭 (설계서 기본 규칙)
    return stem_matches_any(stem, box_front_dir)


def read_metadata_fields(metadata_path, system, rom_filename):
    """Data/Platforms/<system>.xml에서 rom_filename에 해당하는 <Game> 항목을 찾아
    db.META_FIELD_KEYS 형식으로 반환. 없으면 None."""
    xml_path = Path(metadata_path) / "Data" / "Platforms" / f"{system}.xml"
    games = _load_platform_xml(xml_path)
    game = games.get(rom_filename)
    if game is None:
        return None

    def gt(tag, default=""):
        return (game.findtext(tag) or default).strip()

    genre_raw = gt("Genre")
    tags = [g.strip() for g in genre_raw.split(";") if g.strip()] if genre_raw else []
    release_date = gt("ReleaseDate")[:10] if gt("ReleaseDate") else ""

    return {
        "name": gt("Title"),
        "desc": gt("Notes"),
        "genre": genre_raw,
        "developer": gt("Developer"),
        "publisher": gt("Publisher"),
        "releasedate": release_date,
        "region": gt("Region"),
        "players": gt("MaxPlayers"),
        "rating": gt("CommunityStarRating"),
        "tags": tags,
    }


def read_media(media_path, system, rom_filename, game_title=None, media_types=None):
    """LaunchBox media: Images/<system>/Box - Front/<Title>.jpg (제목 기반 파일명).
    1차: ROM stem 매칭, 실패 시 game_title로 폴백.
    media_types: [체감 속도, Scan 2단계] None이면 전체, 리스트면 그 타입 폴더만 확인한다
    (예: ["covers"]면 Screenshot 폴더는 아예 iterdir하지 않음)."""
    stem = Path(rom_filename).stem
    box_front_dir = Path(media_path) / "Images" / system / "Box - Front"
    screenshot_dir = Path(media_path) / "Images" / system / "Screenshot - Gameplay"

    wanted_types = set(media_types) if media_types is not None else None
    result = {}
    for mtype, mdir, key in [("covers", box_front_dir, stem), ("screenshots", screenshot_dir, stem)]:
        if wanted_types is not None and mtype not in wanted_types:
            continue
        match = None
        if mdir.exists():
            for f in mdir.iterdir():
                if f.is_file() and f.stem == key:
                    match = f
                    break
            if not match and game_title:
                for f in mdir.iterdir():
                    if f.is_file() and f.stem == game_title:
                        match = f
                        break
        if match:
            result[mtype] = [str(match)]
    return result
