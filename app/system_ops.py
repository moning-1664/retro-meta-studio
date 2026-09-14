"""System 단위 파일 작업 - System 삭제와 System 폴더 위치.

두 가지 삭제가 있다.
  - 기본(force=False): **게임이 하나라도 있으면 거절한다.** Frontend가 만들어 두었거나
    사용자가 비워 둔 폴더(ROM/gamelist/media)만 지운다.
  - 전체 삭제(force=True): 게임이 있어도 그 System의 ROM·Metadata·Media를 지운다.
    화면이 경고 + "확인하였습니다" 체크 + 확인 버튼으로 두 번 묻는 경우에만 쓴다(사용자 결정).

어느 경우에도 지키는 것:
  - Collection/Storage의 root 자체는 절대 지우지 않는다(rom_path를 Storage root로
    지정한 System도 있다).
  - 폴더 이름이 System 이름과 다르면 그 폴더는 남긴다 - 여러 System이 함께 쓰는
    폴더일 수 있다. 전체 삭제라면 그 안에서 **이 System의 ROM/Media 파일만** 지운다.
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


def _inside(path, folder) -> bool:
    p, f = _norm(path), _norm(folder)
    return p == f or p.startswith(f + os.sep)


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


def _size(path) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _plan_removal(collection, cache, provider, adapter, system, force) -> dict:
    """지울 것 전체(`_all` 포함). 미리보기와 실제 삭제가 같은 계산을 쓴다."""
    if not any(entry.system == system for entry in collection.systems):
        raise SystemOpError(f"System을 찾을 수 없습니다: {system}")

    blockers = []
    if not isinstance(provider, LocalStorageProvider):
        blockers.append("이 저장소에서는 System 폴더를 지울 수 없습니다.")
    games = cache.count_by_system().get(system, 0)

    layout = adapter.layout(collection, system)
    roms = []
    if layout.rom_dir and provider.exists(layout.rom_dir):
        roms = [str(Path(layout.rom_dir) / name) for name in adapter.list_roms(provider, layout)]
    media = adapter.read_media_index(provider, layout) if layout.media_dir else {}
    media_files = sorted({m.path for files in media.values() for m in files})

    if not force:
        if games:
            blockers.append(f"게임이 {games}개 있습니다. 게임이 없는 System만 삭제할 수 있습니다.")
        if roms:
            blockers.append(f"ROM 파일이 {len(roms)}개 남아 있습니다.")
        if media_files:
            blockers.append(f"Media 파일이 {len(media_files)}개 남아 있습니다.")

    protected = {_norm(collection.root_path)} | {_norm(s.root_path) for s in collection.storages if s.root_path}
    targets, kept, removed_dirs = [], [], []
    for path, kind in _candidates(layout, system):
        if not path.exists():
            continue
        if any(_inside(path, done) for done in removed_dirs):
            continue   # 이미 지울 폴더 안에 있다(Pegasus는 metadata/media가 ROM 폴더 안에 있다)
        if path.is_dir() and (_norm(path) in protected or path.name.lower() != system.lower()):
            kept.append({"kind": kind, "path": str(path)})
            continue
        files = _files_under(path)
        if path.is_dir():
            removed_dirs.append(path)
        targets.append({"kind": kind, "path": str(path), "isDir": path.is_dir(), "_all": files})

    if force:
        # 남기는 공용 폴더 안에 있는 이 System의 파일은 하나씩 지운다.
        for kind, files in (("rom", roms), ("media", media_files)):
            loose = [f for f in files if not any(_inside(f, d) for d in removed_dirs)]
            folder = next((k["path"] for k in kept if k["kind"] == kind), None)
            if loose:
                targets.append({"kind": kind, "path": folder or str(Path(loose[0]).parent),
                                "isDir": False, "filesOnly": True, "_all": loose})

    all_files = [f for t in targets for f in t["_all"]]
    for target in targets:
        target["fileCount"] = len(target["_all"])
        target["files"] = target["_all"][:PREVIEW_FILE_LIMIT]
    return {"system": system, "games": games, "force": bool(force), "targets": targets, "kept": kept,
            "blockers": blockers, "totalFiles": len(all_files),
            "totalBytes": sum(_size(f) for f in all_files)}


def _public(plan) -> dict:
    return {**plan, "targets": [{k: v for k, v in t.items() if k != "_all"} for t in plan["targets"]]}


def removal_preview(collection, cache, provider, adapter, system, force=False) -> dict:
    """무엇을 지우고 무엇을 남기는지, 그리고 지울 수 없는 이유."""
    return _public(_plan_removal(collection, cache, provider, adapter, system, force))


def remove_system(registry, collection, cache, provider, adapter, system, force=False) -> dict:
    """System의 파일을 지우고 registry/캐시에서도 뺀다. 지울 수 없으면 SystemOpError."""
    plan = _plan_removal(collection, cache, provider, adapter, system, force)
    if plan["blockers"]:
        raise SystemOpError(" ".join(plan["blockers"]))
    removed, failed = [], []
    for target in plan["targets"]:
        paths = [Path(target["path"])] if not target.get("filesOnly") else [Path(f) for f in target["_all"]]
        for path in paths:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
                removed.append(str(path))
            except OSError as exc:
                failed.append(f"{path}: {exc}")
    if failed:
        # 일부만 지워졌으면 System은 registry에 남긴다 - 다음 스캔이 실제 상태를 다시 본다.
        raise SystemOpError("일부 파일을 지우지 못했습니다. " + "; ".join(failed[:5]))
    registry.remove_system(collection.id, system)
    cache.forget_system(system)
    return {"system": system, "removed": removed, "kept": [k["path"] for k in plan["kept"]],
            "games": plan["games"]}
