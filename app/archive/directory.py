"""
app/archive/directory.py
=========================
Archive **디렉토리를 읽어** DB(색인)에 없는 것을 채운다.

디렉토리가 진실이므로(docs/ARCHIVE_DIRECTORY_DESIGN.md), 사용자가 ROM 폴더에 ROM을 넣거나
gamelist.xml을 직접 고쳐도 새로고침하면 Archive에 나타나야 한다. 예전에는 DB에 없는 것은
새로고침해도 보이지 않았다.

- gamelist에만 있는 항목: 메타데이터만 있는 항목(ROM 없음)으로 등록한다.
- ROM 폴더에만 있는 파일: **ROM만 있는 항목**으로 등록한다(메타데이터는 비어 있다).
- DB에 이미 있는 항목은 건드리지 않는다. 값 충돌을 새로 만들지 않기 위해서다 - 이 함수는
  "없는 것을 채우는" 일만 한다.
"""

from __future__ import annotations

from pathlib import Path

from adapters import get_adapter
from app.archive import projection
from app.store.archive import rom_key_of
from utils import normalize_title

#: 디렉토리에서 읽은 항목의 출처. 실제 Collection이 아니고 사용자 편집도 아니다.
DIRECTORY_SOURCE = "__archive_dir__"


def _rom_root(cfg) -> Path:
    return Path(cfg["romDir"] or cfg["archiveDir"])


def _systems(provider, adapter, collection, cfg) -> list[str]:
    # 점으로 시작하는 폴더는 System이 아니다 - 앱 내부 폴더(`.rms`)의 DB 파일이 ROM으로 잡혀
    # "archive.db" 항목이 생겼다.
    systems = {s for s in adapter.list_systems(provider, collection) if not s.startswith(".")}
    if cfg["romDir"]:
        systems.update(e.name for e in provider.scandir(cfg["romDir"])
                       if e.is_dir and not e.name.startswith("."))
    return sorted(systems)


def sync_from_directory(archive, config, provider) -> dict:
    """반환: {"added": n, "romsLinked": n, "systems": n}"""
    cfg = projection.normalize_config(config)
    if not cfg["archiveDir"]:
        raise ValueError("Archive 디렉토리가 설정되지 않았습니다.")
    collection = projection.collection_for(cfg)
    adapter = get_adapter(cfg["frontend"])

    known: dict[tuple[str, str], dict] = {}
    for row in archive._conn.execute(
            "SELECT i.rom_identity_id, i.system, i.rom_key,"
            " (SELECT COUNT(*) FROM archive_rom_sources s"
            "   WHERE s.rom_identity_id = i.rom_identity_id) AS roms FROM rom_identities i"):
        known[(row["system"], row["rom_key"])] = {"rid": row["rom_identity_id"], "roms": row["roms"]}

    added = linked = 0
    systems = _systems(provider, adapter, collection, cfg)
    for system in systems:
        layout = adapter.layout(collection, system)
        rom_dir = _rom_root(cfg) / system
        index = adapter.read_index(provider, layout)
        roms = {}
        for name in adapter.list_roms(provider, type(layout)(
                system=system, rom_dir=str(rom_dir), metadata_file=layout.metadata_file,
                media_dir=layout.media_dir)):
            roms[name] = rom_dir / name

        for filename in sorted(set(index) | set(roms)):
            key = (system, rom_key_of(filename))
            hit = known.get(key)
            rom_path = roms.get(filename)
            if hit is not None:
                if rom_path is not None and not hit["roms"]:
                    archive.put_rom_source(hit["rid"], DIRECTORY_SOURCE, rom_path,
                                           _size(provider, rom_path))
                    hit["roms"] = 1
                    linked += 1
                continue
            entry = index.get(filename)
            fields = dict(entry.fields) if entry else {}
            title = (fields.get("name") or "").strip() or Path(filename).stem
            game_id = archive.ensure_game(title, normalize_title(title))
            rid = archive.ensure_rom_identity(
                game_id, system, normalize_title(Path(filename).stem), filename=filename,
                size=_size(provider, rom_path) if rom_path else None)
            if entry is not None:
                archive.put_record(rid, DIRECTORY_SOURCE, fields, entry.frontend_raw)
            else:
                # 메타데이터가 없어도 Gamelist에 나오려면 기록이 하나는 있어야 한다.
                archive.put_record(rid, DIRECTORY_SOURCE, {}, {})
            if rom_path is not None:
                archive.put_rom_source(rid, DIRECTORY_SOURCE, rom_path, _size(provider, rom_path))
            known[key] = {"rid": rid, "roms": 1 if rom_path else 0}
            added += 1
    return {"added": added, "romsLinked": linked, "systems": len(systems)}


def _size(provider, path) -> int:
    try:
        return int(Path(path).stat().st_size)
    except OSError:
        return 0
