"""
importers/emulationstation.py
==============================
원조 EmulationStation(RetroPie 등) 구조 감지 및 스캔.

구조 (ES-DE 이전의 legacy EmulationStation 표준):
  rom_path/<system>/<rom files>
  metadata_path/gamelists/<system>/gamelist.xml
  media_path/<system>/<image type>/<rom_stem>.png
    (legacy ES는 downloaded_media 대신 downloaded_images, downloaded_videos 등으로
     나뉘거나 gamelist.xml 내 <image> 태그가 임의 경로를 가리키는 경우가 많음.
     여기서는 ES-DE와 유사하게 media_path/<system>/<subdir>/<stem>.ext 구조를 가정.)

※ 실제 배포판마다(RetroPie, Batocera, Recalbox 등) 세부 경로가 다를 수 있어
  정확한 사용자 환경 샘플로 추후 보정이 필요할 수 있음.
"""

from pathlib import Path
import xml.etree.ElementTree as ET
from .base import list_rom_files_in_dir, stem_matches_any, collect_es_style_media, list_gamelist_entries as _list_gamelist_entries
from utils import normalize_esde_date, normalize_esde_rating


def detect_structure(rom_path, metadata_path, media_path):
    rom_path = Path(rom_path) if rom_path else None
    metadata_path = Path(metadata_path) if metadata_path else None

    if not rom_path or not rom_path.exists():
        return "invalid", "ROM 경로가 존재하지 않습니다."
    if not metadata_path or not metadata_path.exists():
        return "invalid", "Metadata 경로가 존재하지 않습니다."

    gamelists_dir = metadata_path / "gamelists"
    if not gamelists_dir.exists():
        return "warning", "gamelists 폴더를 찾을 수 없습니다."

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


def has_metadata(metadata_path, system, rom_filename):
    gamelist = Path(metadata_path) / "gamelists" / system / "gamelist.xml"
    if not gamelist.exists():
        return False
    try:
        text = gamelist.read_text(encoding="utf-8", errors="ignore")
        return rom_filename in text
    except Exception:
        return False


def has_media(media_path, system, rom_filename):
    from .base import es_media_root
    stem = Path(rom_filename).stem
    media_dir = es_media_root(media_path) / system
    if not media_dir.exists():
        return False
    for subdir in media_dir.iterdir():
        if subdir.is_dir() and stem_matches_any(stem, subdir):
            return True
    return stem_matches_any(stem, media_dir)  # 하위 폴더 없이 바로 있는 legacy 케이스


def _find_game_element(gamelist_path: Path, rom_filename, tree=None):
    """[성능/정합성 버그 수정] es_de.py와 동일한 이유 - 그쪽 주석 참고."""
    if tree is not None:
        root = tree.getroot()
        for game in root.findall("game"):
            path_text = (game.findtext("path") or "").strip()
            if Path(path_text).name == rom_filename:
                return game
        return None
    if not gamelist_path.exists():
        return None
    try:
        tree = ET.parse(gamelist_path)
    except ET.ParseError:
        return None
    root = tree.getroot()
    for game in root.findall("game"):
        path_text = (game.findtext("path") or "").strip()
        if Path(path_text).name == rom_filename:
            return game
    return None


def read_metadata_fields(metadata_path, system, rom_filename, tree=None):
    """legacy EmulationStation gamelist.xml 파싱 (ES-DE와 태그 구조 거의 동일).
    tree: 주어지면 재파싱하지 않는다 - es_de.py 주석 참고."""
    gamelist = Path(metadata_path) / "gamelists" / system / "gamelist.xml"
    game = _find_game_element(gamelist, rom_filename, tree=tree)
    if game is None:
        return None

    def gt(tag, default=""):
        return (game.findtext(tag) or default).strip()

    genre_raw = gt("genre")
    tags = [g.strip() for g in genre_raw.split("/") if g.strip()] if genre_raw else []

    return {
        "name": gt("name"),
        "desc": gt("desc"),
        "genre": genre_raw,
        "developer": gt("developer"),
        "publisher": gt("publisher"),
        "releasedate": normalize_esde_date(gt("releasedate")),
        "region": gt("region"),
        "players": gt("players"),
        "rating": normalize_esde_rating(gt("rating")),
        "tags": tags,
    }


def read_media(media_path, system, rom_filename, game_title=None, media_types=None):
    return collect_es_style_media(media_path, system, rom_filename, media_types=media_types)


def list_gamelist_entries(metadata_path, system):
    """gamelist.xml에 있는 <game> 항목 전체 (ROM 파일 존재 여부 무관)."""
    return _list_gamelist_entries(metadata_path, system)


def build_metadata_index(metadata_path, system):
    return {e["filename"]: e["fields"] for e in list_gamelist_entries(metadata_path, system)}


def build_media_index(media_path, system, media_types=None):
    from .base import build_es_style_media_index
    return build_es_style_media_index(media_path, system, media_types=media_types)
