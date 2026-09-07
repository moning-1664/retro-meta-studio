"""
exporters/es_de.py
===================
MasterDB metadata를 ES-DE의 gamelist.xml로 기록.
"""

from pathlib import Path
import xml.etree.ElementTree as ET
from .base import copy_media_es_style


def _load_or_create_gamelist(gamelist_path: Path):
    gamelist_path.parent.mkdir(parents=True, exist_ok=True)
    if gamelist_path.exists():
        try:
            tree = ET.parse(gamelist_path)
            return tree
        except ET.ParseError:
            pass
    root = ET.Element("gameList")
    return ET.ElementTree(root)


def _find_game(root, rom_filename):
    for game in root.findall("game"):
        path_text = (game.findtext("path") or "").strip()
        if Path(path_text).name == rom_filename:
            return game
    return None


def _write_gamelist_tree(tree, gamelist_path):
    """[버그 수정] ET.ElementTree.write()는 기본적으로 들여쓰기 없이 한 줄로 쓴다 -
    ES-DE/EmulationStation이 직접 만드는 gamelist.xml처럼 태그별로 줄바꿈 +
    들여쓰기가 되도록 쓰기 직전에 ET.indent()로 트리를 정리한다."""
    gamelist_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(gamelist_path, encoding="utf-8", xml_declaration=True)


def _get_cached_tree(cache, gamelist_path):
    """[성능/정합성 버그 수정] read_existing_fields/write_metadata_fields가 같은
    cache dict를 공유해서 시스템당 gamelist.xml을 최대 1번만 파싱하게 한다. 예전엔
    Export 루프가 ROM마다 이 파일을 다시 읽고(충돌 검사) 다시 썼다(저장) - ROM이
    1,000개인 시스템이면 같은 문서 파일을 최대 2,000번 통째로 열고 파싱하는 셈이었다."""
    cache_key = str(gamelist_path)
    tree = cache.get(cache_key)
    if tree is None:
        tree = _load_or_create_gamelist(gamelist_path)
        cache[cache_key] = tree
    return tree


def read_existing_fields(metadata_path, system, rom_filename, cache=None):
    """Export 충돌 검사용: 기존 Local metadata를 읽어 fields 형식으로 반환 (없으면 None).
    cache를 주면 write_metadata_fields와 같은 캐시된 트리를 재사용한다 - 위 주석 참고."""
    from importers.es_de import read_metadata_fields
    if cache is None:
        return read_metadata_fields(metadata_path, system, rom_filename)
    gamelist_path = Path(metadata_path) / "gamelists" / system / "gamelist.xml"
    tree = _get_cached_tree(cache, gamelist_path)
    return read_metadata_fields(metadata_path, system, rom_filename, tree=tree)


def write_metadata_fields(metadata_path, system, rom_filename, fields, cache=None):
    """cache(export_engine.py가 export 1회 전체에 걸쳐 공유하는 dict)를 주면
    gamelist.xml을 매 ROM마다 다시 읽고/쓰지 않고 메모리에 들고 있다가
    flush_metadata_cache()가 마지막에 한 번만 디스크에 쓴다. cache가 없으면
    (기존 호출부/테스트) 예전과 동일하게 매번 즉시 읽고 쓴다."""
    gamelist_path = Path(metadata_path) / "gamelists" / system / "gamelist.xml"
    tree = _get_cached_tree(cache, gamelist_path) if cache is not None else _load_or_create_gamelist(gamelist_path)
    root = tree.getroot()

    game = _find_game(root, rom_filename)
    if game is None:
        game = ET.SubElement(root, "game")
        ET.SubElement(game, "path").text = f"./{rom_filename}"

    def set_tag(tag, value):
        el = game.find(tag)
        if el is None:
            el = ET.SubElement(game, tag)
        el.text = str(value) if value not in (None, "") else ""

    set_tag("name", fields.get("name", ""))
    set_tag("desc", fields.get("desc", ""))
    set_tag("genre", fields.get("genre", ""))
    set_tag("developer", fields.get("developer", ""))
    set_tag("publisher", fields.get("publisher", ""))
    set_tag("releasedate", fields.get("releasedate", "").replace("-", "") + "T000000"
             if fields.get("releasedate") else "")
    set_tag("region", fields.get("region", ""))
    set_tag("players", fields.get("players", ""))
    if fields.get("rating"):
        try:
            set_tag("rating", f"{float(fields['rating']) / 5:.2f}")
        except (ValueError, TypeError):
            pass

    if cache is None:
        _write_gamelist_tree(tree, gamelist_path)


def flush_metadata_cache(cache):
    """write_metadata_fields(..., cache=cache)로 메모리에만 쌓아둔 gamelist.xml
    트리들을 이제 한 번씩만 디스크에 쓴다. export_engine.py가 export 루프가 끝난
    뒤(성공/실패 무관하게) 반드시 호출해야 한다."""
    for gamelist_path_str, tree in cache.items():
        _write_gamelist_tree(tree, Path(gamelist_path_str))


def write_media(media_path, system, rom_filename, media_dict, copy_video=True, batch=None):
    copy_media_es_style(media_path, system, rom_filename, media_dict, copy_video=copy_video, batch=batch)
