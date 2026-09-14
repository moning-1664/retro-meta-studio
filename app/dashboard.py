"""
app/dashboard.py
================
Collection Dashboard의 통계와 Metadata 파일 검증.

**읽기만 한다.** 스캔도, Metadata 수정도, 파일 이동도 하지 않는다. 숫자는 이미
스캔이 채워 둔 Cache(system_stats, roms/metadata/media)에서 모은다.

ROM이 놓인 Storage와 media가 놓인 Storage는 다를 수 있다(ES-DE는 ROM만 System별
Storage를 따라가고 media는 Collection root에 남는다) - 그래서 Storage별 합계를
ROM과 media로 따로 더한다.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def collection_stats(collection, cache) -> dict:
    stats = {row["system"]: row for row in cache.system_stats()}
    games = cache.count_by_system()

    storages = {}
    for storage in collection.storages:
        storages[storage.storage_id] = {
            "id": storage.storage_id, "label": storage.label or storage.storage_id,
            "kind": storage.kind,
            "romCount": 0, "romBytes": 0, "mediaCount": 0, "mediaBytes": 0,
        }

    systems = []
    for entry in collection.systems:
        stat = stats.get(entry.system, {})
        # ROM의 Storage는 registry가 정답이다 - Storage 이동 직후에는 Cache의
        # system_stats가 아직 예전 Storage를 들고 있을 수 있다.
        rom_storage = entry.storage_id
        media_storage = stat.get("media_storage_id") or rom_storage
        row = {
            "system": entry.system,
            "storageId": rom_storage,
            "mediaStorageId": media_storage,
            "games": int(games.get(entry.system, 0)),
            "romCount": int(stat.get("rom_count") or 0),
            "romBytes": int(stat.get("rom_bytes") or 0),
            "mediaCount": int(stat.get("media_count") or 0),
            "mediaBytes": int(stat.get("media_bytes") or 0),
            "missingMetadata": int(stat.get("missing_metadata") or 0),
            "missingMedia": int(stat.get("missing_media") or 0),
        }
        for storage_id, prefix in ((rom_storage, "rom"), (media_storage, "media")):
            bucket = storages.get(storage_id)
            if bucket is not None:
                bucket[f"{prefix}Count"] += row[f"{prefix}Count"]
                bucket[f"{prefix}Bytes"] += row[f"{prefix}Bytes"]
        systems.append(row)

    return {
        # collection.storages 순서를 지킨다 - 호출부가 같은 순서로 볼륨 정보를 붙인다.
        "storages": [storages[s.storage_id] for s in collection.storages],
        "systems": systems,
        "health": cache.metadata_health(),
        "totals": {
            "games": cache.count_rows(),
            "romCount": sum(s["romCount"] for s in systems),
            "romBytes": sum(s["romBytes"] for s in systems),
            "mediaCount": sum(s["mediaCount"] for s in systems),
            "mediaBytes": sum(s["mediaBytes"] for s in systems),
        },
    }


def validate_metadata_files(collection, adapter) -> dict:
    """Adapter가 알려주는 System별 Metadata 파일이 XML로 읽히는지 본다.

    스키마 검증이나 수리는 하지 않는다 - "열리지 않는 파일이 있다"를 알려주는 것까지다.
    파일이 없는 System(ROM만 있는 Collection)은 검사 대상이 아니다.
    """
    checked, invalid = 0, []
    for entry in collection.systems:
        path = adapter.layout(collection, entry.system).metadata_file
        if not path or not Path(path).is_file():
            continue
        checked += 1
        try:
            ET.parse(path)
        except (ET.ParseError, OSError) as exc:
            invalid.append({"system": entry.system, "path": str(path), "error": str(exc)})
    return {"checked": checked, "invalid": invalid}
