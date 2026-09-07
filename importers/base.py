"""
importers/base.py
==================
Frontend별 Importer 공통 인터페이스 및 ROM 파일 판별 유틸.

각 frontend 모듈(es_de.py, pegasus.py, daijisho.py, emulationstation.py,
launchbox.py)은 아래 함수들을 동일한 시그니처로 구현해야 한다:

    detect_structure(rom_path, metadata_path, media_path) -> (status, message)
        status: "valid" | "warning" | "invalid"

    list_systems(rom_path, metadata_path) -> list[str]
        시스템(폴더) 이름 목록

    list_roms(rom_path, system) -> list[Path]
        해당 시스템의 ROM 파일 경로 목록

    has_metadata(metadata_path, system, rom_filename) -> bool

    has_media(media_path, system, rom_filename) -> bool
        (설계서 §3.1: ROM 파일명 stem == media 파일명 stem 완전 일치 기준)

    read_metadata_fields(metadata_path, system, rom_filename) -> dict | None
        db.META_FIELD_KEYS 형태로 반환 (3단계 Import 로직에서 사용, 지금은 stub)
"""

from pathlib import Path

# 메타데이터/미디어가 아닌 실제 ROM으로 간주하지 않을 확장자 (블랙리스트 방식)
NON_ROM_EXTENSIONS = {
    ".xml", ".txt", ".json", ".db", ".ini", ".nfo", ".cfg",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".mp4", ".avi", ".mkv", ".mov",
    ".log", ".bak", ".tmp",
}

MEDIA_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp"]


def is_rom_file(path: Path):
    if not path.is_file():
        return False
    if path.name.startswith("."):
        return False
    return path.suffix.lower() not in NON_ROM_EXTENSIONS


def list_rom_files_in_dir(directory: Path):
    directory = Path(directory)
    if not directory.exists():
        return []
    return sorted([f for f in directory.iterdir() if is_rom_file(f)])


def stem_matches_any(target_stem, media_dir: Path):
    """media_dir 내에 target_stem과 완전히 같은 stem을 가진 media 파일이 있는지 확인."""
    media_dir = Path(media_dir)
    if not media_dir.exists():
        return False
    for f in media_dir.iterdir():
        if f.is_file() and f.stem.casefold() == str(target_stem).casefold() and f.suffix.lower() in MEDIA_EXTENSIONS:
            return True
    return False


def find_stem_match(target_stem, media_dir: Path):
    """target_stem과 완전 일치하는 media 파일 경로 하나 반환 (없으면 None)."""
    media_dir = Path(media_dir)
    if not media_dir.exists():
        return None
    for f in media_dir.iterdir():
        if f.is_file() and f.stem.casefold() == str(target_stem).casefold() and f.suffix.lower() in MEDIA_EXTENSIONS:
            return f
    return None


# es-de / emulationstation 공통: <root>/downloaded_media/<system>/<mediatype>/<rom_stem>.ext
# [BUG FIX] 이전에는 media_path 자체가 downloaded_media 폴더인 것처럼 다뤄져서,
# 실제 ES-DE 구조(루트 하나에 gamelists/와 downloaded_media/가 같이 있음)와 어긋났다.
# 이제 media_path는 metadata_path와 동일한 "루트" 폴더를 가리키고, 여기서 downloaded_media/를 붙인다.
ES_DE_MEDIA_FOLDER_MAP = {
    "3dboxes": "3dboxes",
    "covers": "covers",
    "marquees": "marquees",
    "miximages": "miximages",
    "screenshots": "screenshots",
    "videos": "videos",
    "wheel": "wheel",
}


def es_media_root(media_path):
    """ES-DE/EmulationStation media root.

    Config normally stores the ES-DE root (<root>/downloaded_media exists beneath it),
    but older configs may already point directly at downloaded_media. Accept both.
    """
    p = Path(media_path)
    if p.name.casefold() == "downloaded_media":
        return p
    return p / "downloaded_media"


def collect_es_style_media(media_path, system, rom_filename, media_types=None):
    """es-de 표준 폴더 구조에서 rom_filename의 stem과 일치하는 모든 media type을 수집.
    media_types: [체감 속도, Scan 2단계] None이면(기본, 기존 동작) 전체 타입을 다
    확인한다. 리스트를 넘기면 그 타입의 폴더만 확인해서 폴더 리스팅 횟수를 줄인다 -
    Scan 1단계("커버만 먼저")가 이걸로 folder iteration을 최대 7배 줄인다.
    반환: { mediatype: [str(path), ...] } (screenshots/videos는 여러 개 가능, 나머지는 최대 1개)"""
    stem = Path(rom_filename).stem
    result = {}
    base = es_media_root(media_path) / system
    if not base.exists():
        return result
    wanted_types = set(media_types) if media_types is not None else None
    for mediatype, folder in ES_DE_MEDIA_FOLDER_MAP.items():
        if wanted_types is not None and mediatype not in wanted_types:
            continue
        mdir = base / folder
        if not mdir.exists():
            continue
        wanted = stem.casefold()
        matches = [f for f in mdir.iterdir()
                   if f.is_file() and f.stem.casefold() == wanted and f.suffix.lower() in MEDIA_EXTENSIONS + [".mp4", ".avi"]]
        if matches:
            result[mediatype] = [str(m) for m in matches]
    return result


def build_es_style_media_index(media_path, system, media_types=None):
    """[P0-1, Scan Phase 1 실제 filesystem I/O 분리] es-de 표준 폴더 구조에서 system
    전체의 media를 한 번에 인덱싱한다(stem -> [path, ...]). media_types를 주면 그
    타입의 폴더만 열거한다 - 예전에는 build_media_index()가 rglob("*")로 system
    폴더 전체(video 포함)를 항상 훑어서, Scan Phase 1이 "covers만 필요"라고 인자를
    넘겨도 실제 filesystem traversal은 이미 전체를 다 끝낸 뒤였다(인자가 뒤쪽
    per-ROM read_media()에만 적용되고, 이 system 전체 인덱스에는 전혀 적용되지
    않았기 때문). 이제 collect_es_style_media()와 동일하게 폴더 단위로 필요한
    타입만 iterdir 한다."""
    result = {}
    base = es_media_root(media_path) / system
    if not base.exists():
        return result
    wanted_types = set(media_types) if media_types is not None else None
    for mediatype, folder in ES_DE_MEDIA_FOLDER_MAP.items():
        if wanted_types is not None and mediatype not in wanted_types:
            continue
        mdir = base / folder
        if not mdir.exists():
            continue
        for f in mdir.iterdir():
            if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS + [".mp4", ".avi"]:
                result.setdefault(f.stem, []).append(str(f))
    return result


def list_gamelist_entries(metadata_path, system):
    """
    [신규] gamelist.xml에 존재하는 <game> 항목 전체를 ROM 파일 존재 여부와 무관하게 반환한다.
    (ES-DE/EmulationStation 공용 - 두 Frontend의 gamelist.xml 태그 구조가 거의 동일함)

    기존에는 실제 디렉토리에서 발견된 ROM 파일 기준으로만 목록을 만들어서,
    "gamelist.xml엔 있지만 ROM 파일이 없는(Missing ROM) 항목"이 리스트에서 통째로
    빠지는 게 정상 동작인 것처럼 보이던 버그가 있었다. 이 함수는 그 반대 방향
    (gamelist.xml을 기준으로) 스캔해서 그 문제를 해결한다.

    반환: [{ "filename": str, "fields": {...META_FIELD_KEYS 형식...} }, ...]
    """
    import xml.etree.ElementTree as ET

    gamelist = Path(metadata_path) / "gamelists" / system / "gamelist.xml"
    if not gamelist.exists():
        return []
    try:
        tree = ET.parse(gamelist)
    except ET.ParseError:
        return []

    from utils import normalize_esde_date, normalize_esde_rating

    entries = []
    for game in tree.getroot().findall("game"):
        path_text = (game.findtext("path") or "").strip()
        filename = Path(path_text).name
        if not filename:
            continue

        def gt(tag, default=""):
            return (game.findtext(tag) or default).strip()

        genre_raw = gt("genre")
        entries.append({
            "filename": filename,
            "fields": {
                "name": gt("name"), "desc": gt("desc"), "genre": genre_raw,
                "developer": gt("developer"), "publisher": gt("publisher"),
                "releasedate": normalize_esde_date(gt("releasedate")), "region": gt("region"),
                "players": gt("players"), "rating": normalize_esde_rating(gt("rating")),
                "tags": [g.strip() for g in genre_raw.split("/") if g.strip()] if genre_raw else [],
            },
        })
    return entries


def directory_size_bytes(directory):
    """디렉토리 전체(하위 포함) 파일 크기 합산. Dashboard 통계용."""
    directory = Path(directory)
    if not directory.exists():
        return 0
    total = 0
    for f in directory.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                continue
    return total
