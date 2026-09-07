"""
importers/es_de.py
===================
ES-DE 구조 감지 및 스캔.

구조 (실제 ES-DE 표준):
  rom_path/<system>/<rom files>
  metadata_path/gamelists/<system>/gamelist.xml
  media_path/<system>/<mediatype>/<rom_stem>.png  (mediatype: covers, screenshots, marquees, miximages, 3dboxes, wheel, videos)

rom_path와 metadata_path는 서로 다른 위치일 수 있다 (config.FRONTEND_ROM_METADATA_SAME_DIR["es-de"] = False).
"""

from pathlib import Path
import xml.etree.ElementTree as ET
from .base import list_rom_files_in_dir, stem_matches_any, collect_es_style_media, list_gamelist_entries as _list_gamelist_entries
from utils import normalize_esde_date, normalize_esde_rating
from app.model.constants import ESDE_IGNORED_SYSTEMS


def detect_structure(rom_path, metadata_path, media_path):
    rom_path = Path(rom_path) if rom_path else None
    metadata_path = Path(metadata_path) if metadata_path else None

    metadata_path = Path(metadata_path) if metadata_path else None
    rom_path = Path(rom_path) if rom_path else None
    if not metadata_path or not metadata_path.exists():
        return "invalid", "ES-DE gamelists/downloaded_media 경로가 존재하지 않습니다."
    gamelists_dir = metadata_path / "gamelists"
    media_dir = metadata_path / "downloaded_media"
    if not gamelists_dir.exists() and not media_dir.exists():
        return "warning", "gamelists 또는 downloaded_media 폴더를 찾을 수 없습니다."
    systems = set()
    if gamelists_dir.exists(): systems.update(d.name for d in gamelists_dir.iterdir() if d.is_dir())
    if media_dir.exists(): systems.update(d.name for d in media_dir.iterdir() if d.is_dir())
    if rom_path and rom_path.exists(): systems.update(d.name for d in rom_path.iterdir() if d.is_dir())
    if not systems:
        return "warning", "시스템 폴더가 없습니다."
    return "valid", f"{len(systems)}개 시스템 폴더 확인됨."


def list_systems(rom_path, metadata_path):
    systems = set()
    if metadata_path:
        root = Path(metadata_path)
        for child_name in ("gamelists", "downloaded_media"):
            child = root / child_name
            if child.exists():
                systems.update(d.name for d in child.iterdir() if d.is_dir() and d.name.lower() not in ESDE_IGNORED_SYSTEMS)
    if rom_path:
        root = Path(rom_path)
        if root.exists():
            systems.update(d.name for d in root.iterdir() if d.is_dir() and d.name.lower() not in ESDE_IGNORED_SYSTEMS)
    return sorted(systems)


def list_roms(rom_path, system):
    return list_rom_files_in_dir(Path(rom_path) / system)


def has_metadata(metadata_path, system, rom_filename):
    gamelist = Path(metadata_path) / "gamelists" / system / "gamelist.xml"
    if not gamelist.exists():
        return False
    # 간이 검사: 파일명이 gamelist.xml 텍스트 내에 존재하는지 (경량 스캔용, 정식 파싱은 3단계 Import에서)
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
    # es-de는 mediatype별 하위 폴더 존재. 하나라도 매칭되면 media 있음으로 간주.
    for subdir in media_dir.iterdir():
        if subdir.is_dir() and stem_matches_any(stem, subdir):
            return True
    return False


def _find_game_element(gamelist_path: Path, rom_filename, tree=None):
    """[성능/정합성 버그 수정] tree를 미리 파싱해서 넘기면(exporters.es_de가 write와
    공유하는 캐시된 트리) 다시 ET.parse()하지 않는다 - exporters/es_de.py의 주석 참고."""
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
    """gamelist.xml에서 rom_filename에 해당하는 <game> 항목을 찾아
    db.META_FIELD_KEYS 형식으로 반환. 없으면 None.
    tree: 주어지면 그 트리를 그대로 쓰고 다시 파싱하지 않는다 - exporters.es_de.
    read_existing_fields()가 write_metadata_fields와 같은 cache에서 가져온 트리를
    넘겨서 호출한다."""
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
    """es-de 표준 media 폴더 구조에서 stem 일치 media 파일들을 수집.
    반환: { mediatype: [path, ...] }  (game_title은 다른 frontend와의 인터페이스 통일을 위한 미사용 인자)"""
    return collect_es_style_media(media_path, system, rom_filename, media_types=media_types)


def list_gamelist_entries(metadata_path, system):
    """gamelist.xml에 있는 <game> 항목 전체 (ROM 파일 존재 여부 무관)."""
    return _list_gamelist_entries(metadata_path, system)


def build_metadata_index(metadata_path, system):
    return {e["filename"]: e["fields"] for e in list_gamelist_entries(metadata_path, system)}


def build_media_index(media_path, system, media_types=None):
    from .base import build_es_style_media_index
    return build_es_style_media_index(media_path, system, media_types=media_types)
