"""
exporters/pegasus.py
=====================
MasterDB metadata를 Pegasus의 metadata.pegasus.txt로 기록.
"""

import re
from pathlib import Path
from .base import copy_media_pegasus_style


def _read_blocks(path: Path):
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    return re.split(r"\n\s*\n", text)


def _load_pegasus_state(txt_path):
    """metadata.pegasus.txt를 header 블록 + {파일명: 블록 텍스트} 딕셔너리로 분해한다."""
    blocks = _read_blocks(txt_path)
    header_block = None
    games = {}
    for b in blocks:
        if b.strip().lower().startswith("collection:") or b.strip().lower().startswith("shortname:"):
            header_block = b
            continue
        if not b.strip():
            continue
        lines = b.splitlines()
        file_line = next((l for l in lines if l.strip().lower().startswith("file:")), None)
        key = Path(file_line.split(":", 1)[1].strip()).name if file_line else b
        games[key] = b
    return {"path": txt_path, "header": header_block, "games": games}


def _flush_pegasus_state(state):
    txt_path = state["path"]
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    output = ""
    if state["header"]:
        output += state["header"].strip() + "\n\n"
    output += "\n\n".join(b.strip() for b in state["games"].values() if b.strip()) + "\n"
    txt_path.write_text(output, encoding="utf-8")


def _get_cached_state(cache, txt_path):
    """[성능/정합성 버그 수정] es_de.py의 _get_cached_tree와 동일한 이유 - read/write가
    같은 cache dict를 공유해서 시스템당 metadata.pegasus.txt를 최대 1번만 파싱하게 한다."""
    cache_key = str(txt_path)
    state = cache.get(cache_key)
    if state is None:
        state = _load_pegasus_state(txt_path)
        cache[cache_key] = state
    return state


def _block_to_fields(block):
    """importers.pegasus.read_metadata_fields와 동일한 key: value 매핑 - cache된
    블록 텍스트를 직접 파싱한다(파일 재읽기 없음)."""
    entry = {}
    for line in block.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and ":" in line:
            k, v = line.split(":", 1)
            entry[k.strip().lower()] = v.strip()
    genre_raw = entry.get("genre", "")
    tags_raw = entry.get("tags", "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else \
           ([g.strip() for g in genre_raw.split(",") if g.strip()] if genre_raw else [])
    return {
        "name": entry.get("game", ""), "desc": entry.get("description", ""), "genre": genre_raw,
        "developer": entry.get("developer", ""), "publisher": entry.get("publisher", ""),
        "releasedate": entry.get("release", ""), "region": entry.get("region", ""),
        "players": entry.get("players", ""), "rating": entry.get("rating", ""), "tags": tags,
    }


def read_existing_fields(metadata_path, system, rom_filename, cache=None):
    """[성능/정합성 버그 수정] cache를 주면 write_metadata_fields와 같은 캐시된
    상태를 재사용한다 - es_de.py 주석 참고."""
    if cache is None:
        from importers.pegasus import read_metadata_fields
        return read_metadata_fields(metadata_path, system, rom_filename)
    txt_path = Path(metadata_path) / system / "metadata.pegasus.txt"
    state = _get_cached_state(cache, txt_path)
    block = state["games"].get(rom_filename)
    return _block_to_fields(block) if block is not None else None


def write_metadata_fields(metadata_path, system, rom_filename, fields, cache=None):
    """cache(export_engine.py가 export 1회 전체에 걸쳐 공유하는 dict)를 주면 메모리
    상태만 갱신하고, flush_metadata_cache()가 export 끝에 한 번만 파일로 쓴다.
    예전엔 ROM 1개당 metadata.pegasus.txt 전체를 다시 읽고/재구성하고/통째로 다시 썼다."""
    txt_path = Path(metadata_path) / system / "metadata.pegasus.txt"
    state = _get_cached_state(cache, txt_path) if cache is not None else _load_pegasus_state(txt_path)

    new_block_lines = [
        f"game: {fields.get('name', '')}",
        f"file: {rom_filename}",
    ]
    if fields.get("desc"):
        new_block_lines.append(f"description: {fields['desc']}")
    if fields.get("genre"):
        new_block_lines.append(f"genre: {fields['genre']}")
    if fields.get("developer"):
        new_block_lines.append(f"developer: {fields['developer']}")
    if fields.get("publisher"):
        new_block_lines.append(f"publisher: {fields['publisher']}")
    if fields.get("releasedate"):
        new_block_lines.append(f"release: {fields['releasedate']}")
    if fields.get("players"):
        new_block_lines.append(f"players: {fields['players']}")
    if fields.get("rating"):
        new_block_lines.append(f"rating: {fields['rating']}")

    state["games"][rom_filename] = "\n".join(new_block_lines)

    if cache is None:
        _flush_pegasus_state(state)


def flush_metadata_cache(cache):
    for state in cache.values():
        _flush_pegasus_state(state)


def write_media(media_path, system, rom_filename, media_dict, copy_video=True, batch=None):
    copy_media_pegasus_style(media_path, system, rom_filename, media_dict, copy_video=copy_video, batch=batch)
