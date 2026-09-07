"""
exporters/emulationstation.py
==============================
MasterDB metadata를 legacy EmulationStation의 gamelist.xml로 기록.
(ES-DE와 태그 구조가 동일하여 로직을 그대로 재사용)
"""

from pathlib import Path
from .es_de import _load_or_create_gamelist, _find_game, _get_cached_tree, _write_gamelist_tree, flush_metadata_cache  # noqa: F401 (재노출)
from .base import copy_media_es_style
import xml.etree.ElementTree as ET


def read_existing_fields(metadata_path, system, rom_filename, cache=None):
    """[성능/정합성 버그 수정] es_de.py와 동일한 이유로 cache 지원 - 그쪽 주석 참고."""
    from importers.emulationstation import read_metadata_fields
    if cache is None:
        return read_metadata_fields(metadata_path, system, rom_filename)
    gamelist_path = Path(metadata_path) / "gamelists" / system / "gamelist.xml"
    tree = _get_cached_tree(cache, gamelist_path)
    return read_metadata_fields(metadata_path, system, rom_filename, tree=tree)


def write_metadata_fields(metadata_path, system, rom_filename, fields, cache=None):
    # [성능/정합성 버그 수정] es_de.py와 동일한 이유로 cache 지원 - 그쪽 주석 참고.
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


def write_media(media_path, system, rom_filename, media_dict, copy_video=True, batch=None):
    copy_media_es_style(media_path, system, rom_filename, media_dict, copy_video=copy_video, batch=batch)
