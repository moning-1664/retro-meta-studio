"""
app/storage_layout.py
======================
System이 실제로 어느 Storage에 놓여 있는지(ROM 폴더 기준) - 충돌 판정, External 연결,
System 폴더 이름 바꾸기/한쪽 삭제.

**ES-DE는 System 이름 하나에 ROM 경로 하나만 인정한다**(es_systems.xml의 `<path>`). 그래서
같은 이름의 System 폴더가 두 Storage(예: Internal과 External SD)에 모두 ROM을 갖고 있으면
그 System은 **충돌**이다(사용자 결정). 화면에 빨간 !로 표시하고 쓰기를 막으며, 한쪽 폴더를
지우거나 이름을 바꾸면 풀린다. 앱이 둘 중 하나를 조용히 고르지 않는다 - 사용자가 모르는 사이에
다른 쪽 ROM이 목록에서 사라지기 때문이다.

같은 Storage 안에서 두 폴더(예: Collection root와 rom_path 부모)가 겹치는 것은 충돌로 보지 않는다.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from storage.local import LocalStorageProvider

#: 폴더 이름이 곧 System 이름이다(ES-DE). 경로 구분자·공백 없이.
SYSTEM_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$")


class StorageLayoutError(Exception):
    pass


def _norm(path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _entry(collection, system):
    key = str(system or "").lower()
    return next((e for e in collection.systems if e.system.lower() == key), None)


def rom_roots(collection) -> dict[str, list[Path]]:
    """Storage별로 System 폴더를 찾아볼 상위 폴더 - Storage root와, 그 Storage에 등록된
    System의 rom_path 부모(ES-DE에서 ROM 폴더를 따로 지정한 경우)."""
    roots: dict[str, list[Path]] = {}

    def add(storage_id, path):
        if not path:
            return
        bucket = roots.setdefault(storage_id, [])
        if all(_norm(p) != _norm(path) for p in bucket):
            bucket.append(Path(path))

    for storage in collection.storages:
        add(storage.storage_id, storage.root_path)
    for entry in collection.systems:
        if entry.rom_path:
            add(entry.storage_id, Path(entry.rom_path).parent)
    return roots


def system_folders(collection, provider, adapter) -> dict[str, list[dict]]:
    """{system 소문자: [{storageId, label, path, name}]} - ROM 파일이 실제로 들어 있는 System 폴더."""
    finder = getattr(adapter, "rom_system_dirs", None)
    if finder is None:
        return {}
    labels = {s.storage_id: (s.label or s.storage_id) for s in collection.storages}
    found: dict[str, list[dict]] = {}
    for storage_id, roots in rom_roots(collection).items():
        for root in roots:
            try:
                names = finder(provider, root)
            except OSError:
                continue
            for name in names:
                path = str(Path(root) / name)
                bucket = found.setdefault(name.lower(), [])
                if all(_norm(item["path"]) != _norm(path) for item in bucket):
                    bucket.append({"storageId": storage_id, "label": labels.get(storage_id, storage_id),
                                   "path": path, "name": name})
    return found


def conflicts(collection, provider, adapter) -> dict[str, list[dict]]:
    """두 Storage 이상에 ROM 폴더가 있는 System."""
    return {name: sides for name, sides in system_folders(collection, provider, adapter).items()
            if len({side["storageId"] for side in sides}) >= 2}


def attach_storage(registry, collection, provider, adapter, storage_id) -> dict:
    """External Storage를 추가한 직후 그 root 밑의 System 폴더를 Collection에 붙인다(사용자 결정).

    - 처음 보는 System → 그 Storage의 System으로 등록
    - 다른 Storage에 등록돼 있지만 그쪽엔 ROM이 없는 System(메타데이터만) → 이 Storage로 옮긴다
    - 양쪽 다 ROM이 있으면 → 충돌. 옮기지 않고 알려만 준다
    파일은 건드리지 않는다. 호출부가 이어서 스캔한다.
    """
    storage = collection.storage(storage_id)
    if storage is None:
        raise StorageLayoutError("Storage를 찾을 수 없습니다.")
    finder = getattr(adapter, "rom_system_dirs", None)
    result = {"added": [], "moved": [], "conflicts": []}
    if finder is None or not storage.root_path:
        return result
    clash = conflicts(collection, provider, adapter)
    for name in sorted(finder(provider, storage.root_path), key=str.lower):
        entry = _entry(collection, name)
        if entry is None:
            registry.upsert_system(collection.id, name, storage_id)
            result["added"].append(name)
        elif entry.storage_id == storage_id:
            continue
        elif name.lower() in clash:
            result["conflicts"].append(entry.system)
        else:
            registry.move_system(collection.id, entry.system, storage_id, rom_path=None)
            result["moved"].append(entry.system)
    return result


def _require_local(provider):
    if not isinstance(provider, LocalStorageProvider):
        raise StorageLayoutError("이 저장소에서는 System 폴더를 바꿀 수 없습니다.")


def _side(collection, provider, adapter, system, storage_id):
    sides = system_folders(collection, provider, adapter).get(str(system).lower(), [])
    return next((s for s in sides if s["storageId"] == storage_id), None), sides


def rename_folder(registry, collection, provider, adapter, cache, system, storage_id, new_name) -> dict:
    """한 Storage 쪽의 System 폴더 이름을 바꾼다. 충돌을 푸는 방법 중 하나다.

    등록된 쪽이면 ES-DE의 gamelists/<system>, downloaded_media/<system>도 함께 바꾸고 registry도
    새 이름으로 옮긴다. 등록되지 않은 쪽(충돌의 반대편)이면 그 폴더만 바꾸고 새 System으로 등록한다.
    """
    _require_local(provider)
    new_name = str(new_name or "").strip()
    if not SYSTEM_NAME.match(new_name):
        raise StorageLayoutError("System 이름은 영문·숫자로 시작하고 영문·숫자·. _ - + 만 쓸 수 있습니다.")
    if new_name.lower() == str(system).lower():
        raise StorageLayoutError("지금과 같은 이름입니다.")
    if _entry(collection, new_name) is not None:
        raise StorageLayoutError(f"이미 있는 System 이름입니다: {new_name}")

    entry = _entry(collection, system)
    side, _ = _side(collection, provider, adapter, system, storage_id)
    registered_side = entry is not None and entry.storage_id == storage_id
    if side is not None:
        src = Path(side["path"])
    elif registered_side:
        src = Path(adapter.layout(collection, entry.system).rom_dir)   # ROM 폴더가 비어 있는 System
    else:
        raise StorageLayoutError("그 Storage에서 System 폴더를 찾을 수 없습니다.")
    dst = src.parent / new_name
    if dst.exists():
        raise StorageLayoutError(f"같은 이름의 폴더가 이미 있습니다: {dst}")

    renamed = []
    if src.exists():
        src.rename(dst)
        renamed.append([str(src), str(dst)])

    storage = collection.storage(storage_id)
    at_root = storage is not None and _norm(dst.parent) == _norm(storage.root_path)
    if registered_side:
        layout = adapter.layout(collection, entry.system)
        others = []
        if layout.metadata_file:
            others.append(Path(layout.metadata_file).parent)
        if layout.media_dir:
            others.append(Path(layout.media_dir))
        for folder in others:
            if folder.name.lower() == entry.system.lower() and folder.exists():
                target = folder.parent / new_name
                if not target.exists():
                    folder.rename(target)
                    renamed.append([str(folder), str(target)])
        registry.remove_system(collection.id, entry.system)
        registry.upsert_system(collection.id, new_name, storage_id,
                               rom_path=None if (at_root or not entry.rom_path) else str(dst),
                               media_path=entry.media_path, metadata_path=entry.metadata_path)
        cache.forget_system(entry.system)
    else:
        registry.upsert_system(collection.id, new_name, storage_id, rom_path=None if at_root else str(dst))
    return {"from": str(system), "to": new_name, "renamed": renamed, "registered": registered_side}


def folder_preview(collection, provider, adapter, system, storage_id) -> dict:
    side, sides = _side(collection, provider, adapter, system, storage_id)
    if side is None:
        raise StorageLayoutError("그 Storage에서 System 폴더를 찾을 수 없습니다.")
    files, total = 0, 0
    for base, _dirs, names in os.walk(side["path"]):
        for name in names:
            files += 1
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    entry = _entry(collection, system)
    return {"system": str(system), "storageId": storage_id, "label": side["label"], "path": side["path"],
            "fileCount": files, "totalBytes": total,
            "registered": entry is not None and entry.storage_id == storage_id,
            "remaining": [s for s in sides if s["storageId"] != storage_id]}


def remove_folder(registry, collection, provider, adapter, cache, system, storage_id) -> dict:
    """한 Storage 쪽의 ROM 폴더만 지운다(gamelist/media는 남긴다). 충돌을 푸는 다른 방법.

    지운 쪽이 등록된 쪽이었고 다른 Storage에 폴더가 남아 있으면, System을 그쪽으로 옮긴다.
    """
    _require_local(provider)
    preview = folder_preview(collection, provider, adapter, system, storage_id)
    path = Path(preview["path"])
    protected = {_norm(collection.root_path)} | {_norm(s.root_path) for s in collection.storages if s.root_path}
    if _norm(path) in protected or path.name.lower() != str(system).lower():
        raise StorageLayoutError(f"이 폴더는 지울 수 없습니다: {path}")
    shutil.rmtree(path)

    moved_to = None
    entry = _entry(collection, system)
    if entry is not None and entry.storage_id == storage_id:
        if preview["remaining"]:
            other = preview["remaining"][0]
            storage = collection.storage(other["storageId"])
            at_root = storage is not None and _norm(Path(other["path"]).parent) == _norm(storage.root_path)
            registry.move_system(collection.id, entry.system, other["storageId"],
                                 rom_path=None if at_root else other["path"])
            moved_to = other["storageId"]
        cache.forget_system(entry.system)
    return {"removed": str(path), "movedTo": moved_to}
