"""
app/archive/directory.py
=========================
Archive **디렉토리를 읽어** DB(색인)에 없는 것을 채운다.

디렉토리가 진실이므로(docs/ARCHIVE_DIRECTORY_DESIGN.md), 사용자가 ROM 폴더에 ROM을 넣거나
gamelist.xml을 직접 고쳐도 새로고침하면 Archive에 나타나야 한다. 예전에는 DB에 없는 것은
새로고침해도 보이지 않았다.

- gamelist에만 있는 항목: 메타데이터만 있는 항목(ROM 없음)으로 등록한다.
- ROM 폴더에만 있는 파일: **ROM만 있는 항목**으로 등록한다(메타데이터는 비어 있다).
- downloaded_media의 그림도 함께 읽어 등록한다 - ES-DE 형식으로 이미 저장돼 있는
  기존 Archive를 가리키면(사용자 결정) gamelist/ROM은 읽히는데 media만 하나도 안
  잡혀서 "가지고 있는데 없다고 나온다"였다(실사용 버그 리포트) - 있는 항목이든 새로
  만든 항목이든 같은 규칙으로 media를 붙인다.
- DB에 이미 있는 항목은 Metadata/ROM은 건드리지 않는다(값 충돌을 새로 만들지 않기
  위해서). Media는 예외다 - 새로 찾은 파일이 있으면 채운다(전에는 아예 안 읽었다).
"""

from __future__ import annotations

from pathlib import Path

from adapters import get_adapter
from app.archive import projection
from app.model.constants import normalize_system
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

    added = linked = media_linked = 0
    systems = _systems(provider, adapter, collection, cfg)
    for system in systems:
        # Identity 키만 정규화한다(msx/msx1처럼 같은 플랫폼을 가리키는 다른 폴더명이
        # ingest_collection과 다른 Identity로 갈리지 않게 - app/archive/service.py 참고).
        # 폴더 자체(layout/rom_dir)는 실제 이 디렉토리의 이름 그대로 읽어야 한다.
        identity_system = normalize_system(cfg["frontend"], system)
        layout = adapter.layout(collection, system)
        rom_dir = _rom_root(cfg) / system
        index = adapter.read_index(provider, layout)
        # downloaded_media도 gamelist/ROM과 같은 단계에서 읽는다 - stem(ROM 파일명에서
        # 확장자를 뺀 이름)으로 짝짓는다(_scan_system과 같은 방식).
        media_index = {stem: _dedup_media(items)
                       for stem, items in adapter.read_media_index(provider, layout, None).items()}
        roms = {}
        for name in adapter.list_roms(provider, type(layout)(
                system=system, rom_dir=str(rom_dir), metadata_file=layout.metadata_file,
                media_dir=layout.media_dir)):
            roms[name] = rom_dir / name

        for filename in sorted(set(index) | set(roms)):
            key = (identity_system, rom_key_of(filename))
            hit = known.get(key)
            rom_path = roms.get(filename)
            media = media_index.get(Path(filename).stem, [])
            if hit is not None:
                rid = hit["rid"]
                if rom_path is not None and not hit["roms"]:
                    archive.put_rom_source(rid, DIRECTORY_SOURCE, rom_path,
                                           _size(provider, rom_path))
                    hit["roms"] = 1
                    linked += 1
            else:
                entry = index.get(filename)
                fields = dict(entry.fields) if entry else {}
                title = (fields.get("name") or "").strip() or Path(filename).stem
                game_id = archive.ensure_game(title, normalize_title(title))
                rid = archive.ensure_rom_identity(
                    game_id, identity_system, normalize_title(Path(filename).stem), filename=filename,
                    size=_size(provider, rom_path) if rom_path else None,
                    # gamelist에서 읽은 제목만 진짜다 - ROM만 있는 항목의 제목은 파일명이라 넘기지 않는다.
                    title=(fields.get("name") or "").strip() or None)
                if entry is not None:
                    archive.put_record(rid, DIRECTORY_SOURCE, fields, entry.frontend_raw)
                else:
                    # 메타데이터가 없어도 Gamelist에 나오려면 기록이 하나는 있어야 한다.
                    archive.put_record(rid, DIRECTORY_SOURCE, {}, {})
                if rom_path is not None:
                    archive.put_rom_source(rid, DIRECTORY_SOURCE, rom_path, _size(provider, rom_path))
                known[key] = {"rid": rid, "roms": 1 if rom_path else 0}
                added += 1
            for m in media:
                archive.put_media_ref(rid, m.media_type, DIRECTORY_SOURCE, m.path, m.size)
                media_linked += 1
    return {"added": added, "romsLinked": linked, "mediaLinked": media_linked, "systems": len(systems)}


def _dedup_media(media):
    """같은 media type이 여럿이면 하나만 남긴다(경로 순서로 정해 매번 같은 결과가 나오게 한다).

    `app/scan/scanner._one_per_media_type`와 같은 이유 - `archive_media`는
    (rom_identity_id, media_type, source_collection_id)가 키라서, 같은 타입 파일이
    둘이면 어느 한쪽만 남는데 그 선택이 매번 달라지면 안 된다.
    """
    chosen = {}
    for item in sorted(media, key=lambda m: str(m.path)):
        chosen.setdefault(item.media_type, item)
    return list(chosen.values())


def _size(provider, path) -> int:
    try:
        return int(Path(path).stat().st_size)
    except OSError:
        return 0
