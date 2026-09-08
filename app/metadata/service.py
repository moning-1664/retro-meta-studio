"""
app/metadata/service.py
========================
메타데이터가 아직 없는 Collection을 시작할 수 있게 해 준다.

스크래핑을 한 번도 안 한 컬렉션은 ROM 폴더만 있고 gamelist.xml이 없다. 그 상태로도
Collection은 열리고 Gamelist에는 **파일명이 제목 자리에** 표시된다(스캐너가 메타데이터가
없으면 파일명 stem을 쓴다). 편집해서 저장하면 그때 gamelist.xml이 만들어진다.

여기서 더해 주는 것은 **미리 만들어 두는 선택지**다. 항목 하나를 고쳐야 파일이 생기는
것보다, 처음에 ROM 목록만 담은 gamelist를 만들어 두는 편이 이후 작업(Export, Convert,
Archive 수집)이 자연스럽다.

## 만들지 않는 것

`<name>`은 파일명 stem을 그대로 넣는다. **추측해서 채우지 않는다** - 스크래퍼가 아니고,
잘못 채운 값은 사용자가 나중에 일일이 지워야 한다. 확장자를 뗀 이름은 "우리가 아는
사실"이지만 장르나 출시일은 아니다.

## 이미 gamelist가 있는 System은 건드리지 않는다

메타데이터를 덮어쓰는 사고를 원천적으로 막기 위해, 파일이 이미 있으면 그 System은
대상에서 제외한다. "비어 있는 gamelist"조차 사용자가 의도해서 만든 것일 수 있다.
"""

from __future__ import annotations

from pathlib import Path

from adapters import get_adapter
from adapters.base import GameEntry


def status(collection, provider) -> dict:
    """System별로 gamelist가 있는지, ROM은 몇 개인지.

    반환: {"systems": [{"system", "hasMetadata", "roms"}], "missing": [...], "roms": n}
    `missing`은 **ROM이 있는데 gamelist가 없는** System만 담는다 - ROM도 없는 빈
    폴더에 gamelist를 만들어 줄 이유는 없다.
    """
    adapter = get_adapter(collection.frontend)
    systems, missing, total_roms = [], [], 0

    for entry in collection.systems:
        layout = adapter.layout(collection, entry.system)
        has_metadata = bool(layout.metadata_file) and provider.exists(layout.metadata_file)
        roms = adapter.list_roms(provider, layout)
        total_roms += len(roms)
        systems.append({"system": entry.system, "hasMetadata": has_metadata, "roms": len(roms)})
        if not has_metadata and roms:
            missing.append(entry.system)

    return {"systems": systems, "missing": missing, "roms": total_roms}


def generate(collection, provider, systems=None) -> dict:
    """ROM 목록만 담은 gamelist를 만든다. **이미 있는 파일은 건드리지 않는다.**

    반환: {"created": [{"system", "games"}], "skipped": [...]}
    """
    adapter = get_adapter(collection.frontend)
    wanted = set(systems) if systems else None

    created, skipped = [], []
    for entry in collection.systems:
        if wanted is not None and entry.system not in wanted:
            continue
        layout = adapter.layout(collection, entry.system)
        if layout.metadata_file and provider.exists(layout.metadata_file):
            skipped.append({"system": entry.system, "reason": "이미 gamelist가 있습니다."})
            continue

        roms = adapter.list_roms(provider, layout)
        if not roms:
            skipped.append({"system": entry.system, "reason": "ROM이 없습니다."})
            continue

        # 제목은 파일명 stem만 넣는다. 나머지는 비워 둔다 - 추측은 사용자가 지워야 할
        # 쓰레기가 된다.
        adapter.write_index(layout, [
            GameEntry(filename=name, fields={"name": Path(name).stem}) for name in roms])
        created.append({"system": entry.system, "games": len(roms)})

    return {"created": created, "skipped": skipped}
