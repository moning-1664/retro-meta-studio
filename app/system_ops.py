"""System 단위 파일 작업 - 빈 System 삭제와 System 폴더 위치.

**게임이 하나라도 있는 System은 지우지 않는다.** 여기서 지우는 것은 Frontend가 만들어
두었거나 사용자가 비워 둔 폴더(ROM/gamelist/media)뿐이다. 게임 파일을 없애는 일은
Plan(삭제 → Apply)을 거쳐야 한다.

안전장치:
  - Collection/Storage의 root 자체는 절대 지우지 않는다(rom_path를 Storage root로
    지정한 System도 있다).
  - 폴더 이름이 System 이름과 다르면 그 폴더는 남긴다 - 여러 System이 함께 쓰는
    폴더(LaunchBox의 Data/Platforms 등)일 수 있다. 그 안의 System 전용 파일만 지운다.
  - ROM 파일이나 media 파일이 하나라도 남아 있으면 거절한다(캐시가 오래됐어도 디스크를
    다시 보고 판단한다).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from storage.local import LocalStorageProvider

FOLDER_KINDS = ("rom", "metadata", "media")
PREVIEW_FILE_LIMIT = 50


class SystemOpError(Exception):
    pass


def _norm(path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def folder_path(layout, kind) -> str | None:
    """System 폴더 열기에서 열 경로. metadata는 파일이 아니라 그 파일이 있는 폴더다."""
    if kind == "rom":
        return layout.rom_dir
    if kind == "media":
        return layout.media_dir
    if kind == "metadata":
        return str(Path(layout.metadata_file).parent) if layout.metadata_file else None
    raise SystemOpError(f"알 수 없는 폴더 종류입니다: {kind}")


def _candidates(layout, system):
    """지울 후보 (경로, 종류). metadata는 System 전용 폴더에 있으면 폴더째, 아니면 파일만."""
    items = [(layout.rom_dir, "rom"), (layout.media_dir, "media")]
    if layout.metadata_file:
        meta = Path(layout.metadata_file)
        items.append((str(meta.parent) if meta.parent.name.lower() == system.lower()
                      else str(meta), "metadata"))
    return [(Path(p), kind) for p, kind in items if p]


def _files_under(path: Path) -> list[str]:
    if path.is_file():
        return [str(path)]
    found = []
    for base, _dirs, files in os.walk(path):
        found.extend(str(Path(base) / name) for name in files)
    return sorted(found)


def removal_preview(collection, cache, provider, adapter, system) -> dict:
    """무엇을 지우고 무엇을 남기는지, 그리고 지울 수 없는 이유."""
    if not any(entry.system == system for entry in collection.systems):
        raise SystemOpError(f"System을 찾을 수 없습니다: {system}")

    blockers = []
    if not isinstance(provider, LocalStorageProvider):
        blockers.append("이 저장소에서는 System 폴더를 지울 수 없습니다.")
    games = cache.count_by_system().get(system, 0)
    if games:
        blockers.append(f"게임이 {games}개 있습니다. 게임이 없는 System만 삭제할 수 있습니다.")

    layout = adapter.layout(collection, system)
    roms = adapter.list_roms(provider, layout) if layout.rom_dir and provider.exists(layout.rom_dir) else []
    if roms:
        blockers.append(f"ROM 파일이 {len(roms)}개 남아 있습니다.")
    media = adapter.read_media_index(provider, layout) if layout.media_dir else {}
    media_count = sum(len(files) for files in media.values())
    if media_count:
        blockers.append(f"Media 파일이 {media_count}개 남아 있습니다.")

    protected = {_norm(collection.root_path)} | {_norm(s.root_path) for s in collection.storages if s.root_path}
    targets, kept, seen = [], [], []
    for path, kind in _candidates(layout, system):
        if not path.exists():
            continue
        if any(_norm(path) == _norm(done) or _norm(path).startswith(_norm(done) + os.sep) for done in seen):
            continue   # 이미 지울 폴더 안에 있다(Pegasus는 metadata/media가 ROM 폴더 안에 있다)
        if path.is_dir() and (_norm(path) in protected or path.name.lower() != system.lower()):
            kept.append({"kind": kind, "path": str(path)})
            continue
        files = _files_under(path)
        seen.append(path)
        targets.append({"kind": kind, "path": str(path), "isDir": path.is_dir(),
                        "fileCount": len(files), "files": files[:PREVIEW_FILE_LIMIT]})

    return {"system": system, "games": games, "targets": targets, "kept": kept, "blockers": blockers}


def remove_empty_system(registry, collection, cache, provider, adapter, system) -> dict:
    """빈 System의 폴더를 지우고 registry/캐시에서도 뺀다. 지울 수 없으면 SystemOpError."""
    preview = removal_preview(collection, cache, provider, adapter, system)
    if preview["blockers"]:
        raise SystemOpError(" ".join(preview["blockers"]))
    removed, failed = [], []
    for target in preview["targets"]:
        path = Path(target["path"])
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(str(path))
        except OSError as exc:
            failed.append(f"{path}: {exc}")
    if failed:
        # 일부만 지워졌으면 System은 registry에 남긴다 - 다음 스캔이 실제 상태를 다시 본다.
        raise SystemOpError("일부 폴더를 지우지 못했습니다. " + "; ".join(failed))
    registry.remove_system(collection.id, system)
    cache.forget_system(system)
    return {"system": system, "removed": removed, "kept": [k["path"] for k in preview["kept"]]}
