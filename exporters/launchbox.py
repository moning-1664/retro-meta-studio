"""
exporters/launchbox.py
========================
MasterDB metadata를 LaunchBox의 Data/Platforms/<system>.xml로 기록.
"""

from pathlib import Path
import xml.etree.ElementTree as ET

import file_ops


def _load_or_create_platform_xml(xml_path: Path):
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    if xml_path.exists():
        try:
            return ET.parse(xml_path)
        except ET.ParseError:
            pass
    root = ET.Element("LaunchBox")
    return ET.ElementTree(root)


def _write_platform_xml(tree, xml_path):
    """[버그 수정] es_de.py의 _write_gamelist_tree와 동일한 이유 - ET.write()가
    기본으로 한 줄짜리 XML을 내보내던 것을 태그별 줄바꿈/들여쓰기로 고친다."""
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def _find_game(root, rom_filename):
    for game in root.findall("Game"):
        app_path = game.findtext("ApplicationPath", "")
        if app_path and Path(app_path).name == rom_filename:
            return game
    return None


def _get_cached_tree(cache, xml_path):
    """[성능/정합성 버그 수정] es_de.py의 동명 함수와 동일한 이유 - read/write가
    같은 cache dict를 공유해서 시스템당 <system>.xml을 최대 1번만 파싱하게 한다."""
    cache_key = str(xml_path)
    tree = cache.get(cache_key)
    if tree is None:
        tree = _load_or_create_platform_xml(xml_path)
        cache[cache_key] = tree
    return tree


def _game_to_fields(game):
    """importers.launchbox.read_metadata_fields와 동일한 필드 매핑(LaunchBox는
    dict 기반 파서를 쓰고 여기는 cache된 tree를 직접 훑으므로 매핑만 그대로 재사용)."""
    def gt(tag, default=""):
        return (game.findtext(tag) or default).strip()
    genre_raw = gt("Genre")
    tags = [g.strip() for g in genre_raw.split(";") if g.strip()] if genre_raw else []
    release_date = gt("ReleaseDate")[:10] if gt("ReleaseDate") else ""
    return {
        "name": gt("Title"), "desc": gt("Notes"), "genre": genre_raw,
        "developer": gt("Developer"), "publisher": gt("Publisher"),
        "releasedate": release_date, "region": gt("Region"),
        "players": gt("MaxPlayers"), "rating": gt("CommunityStarRating"), "tags": tags,
    }


def read_existing_fields(metadata_path, system, rom_filename, cache=None):
    """[성능/정합성 버그 수정] cache를 주면 write_metadata_fields와 같은 캐시된
    트리를 재사용한다 - es_de.py 주석 참고."""
    if cache is None:
        from importers.launchbox import read_metadata_fields
        return read_metadata_fields(metadata_path, system, rom_filename)
    xml_path = Path(metadata_path) / "Data" / "Platforms" / f"{system}.xml"
    tree = _get_cached_tree(cache, xml_path)
    game = _find_game(tree.getroot(), rom_filename)
    return _game_to_fields(game) if game is not None else None


def write_metadata_fields(metadata_path, system, rom_filename, fields, cache=None):
    # [성능/정합성 버그 수정] es_de.py와 동일한 이유로 cache 지원 - 그쪽 주석 참고.
    xml_path = Path(metadata_path) / "Data" / "Platforms" / f"{system}.xml"
    tree = _get_cached_tree(cache, xml_path) if cache is not None else _load_or_create_platform_xml(xml_path)
    root = tree.getroot()

    game = _find_game(root, rom_filename)
    if game is None:
        game = ET.SubElement(root, "Game")
        ET.SubElement(game, "ApplicationPath").text = rom_filename

    def set_tag(tag, value):
        el = game.find(tag)
        if el is None:
            el = ET.SubElement(game, tag)
        el.text = str(value) if value not in (None, "") else ""

    set_tag("Title", fields.get("name", ""))
    set_tag("Notes", fields.get("desc", ""))
    set_tag("Genre", fields.get("genre", ""))
    set_tag("Developer", fields.get("developer", ""))
    set_tag("Publisher", fields.get("publisher", ""))
    set_tag("ReleaseDate", fields.get("releasedate", ""))
    set_tag("Region", fields.get("region", ""))
    set_tag("MaxPlayers", fields.get("players", ""))
    set_tag("CommunityStarRating", fields.get("rating", ""))

    if cache is None:
        _write_platform_xml(tree, xml_path)


def flush_metadata_cache(cache):
    for xml_path_str, tree in cache.items():
        _write_platform_xml(tree, Path(xml_path_str))


def write_media(media_path, system, rom_filename, media_dict, copy_video=True, batch=None):
    """LaunchBox는 우리가 Export하는 데이터에 한해 ROM stem 기준 파일명으로 저장한다.

    [별도 프로세스 위임] exporters/base.py의 copy_media_es_style()과 동일한
    이유로 mkdir + 복사를 native worker에 맡긴다. batch 파라미터도 동일
    (주어지면 즉시 복사 대신 거기에 쌓는다)."""
    stem = Path(rom_filename).stem
    type_folder_map = {
        "covers": "Box - Front",
        "screenshots": "Screenshot - Gameplay",
    }
    dest_dirs = []
    pairs = []
    for mtype, folder in type_folder_map.items():
        src = media_dict.get(mtype)
        if not src:
            continue
        src_path = Path(src if isinstance(src, str) else src[0])
        if not src_path.exists():
            continue
        dest_dir = Path(media_path) / "Images" / system / folder
        dest_dirs.append(dest_dir)
        pairs.append((src_path, dest_dir / f"{stem}{src_path.suffix}"))
    if pairs:
        if batch is not None:
            batch.add(dest_dirs, pairs)
        else:
            file_ops.copy_files(dest_dirs, pairs)
