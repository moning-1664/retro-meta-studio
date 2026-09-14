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

from collections import Counter


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


def validate_collection(collection, adapter, cache, provider) -> dict:
    """XML 문법부터 ROM/Media 연결까지, System별 Metadata를 훑는다.

    파일이 없는 System(ROM만 있는 Collection)은 검사 대상이 아니다 - 예전과 같다.

    **집계(Complete/Missing Media/Missing Description)는 `cache.metadata_health()`를
    그대로 쓴다.** Dashboard의 Metadata Health 카드가 보여주는 숫자와 정확히 같은
    기준이어야 하는데, 그 계산은 이미 그 함수 하나에 있다(SQL 한 번, `desc`가
    비어있지 않은지·covers media가 있는지 같은 정의) - 여기서 파일을 다시 읽어
    따로 계산하면 두 화면의 숫자가 미묘하게 어긋날 수 있다.

    이 함수가 새로 더하는 것은 **파일을 다시 읽어야만 알 수 있는 것들**이다.
    - Invalid XML: 스캐너(`read_index`)는 깨진 파일을 조용히 빈 목록으로 넘긴다
      (System 전체 스캔을 막지 않으려는 의도적 선택, adapters/base.py 참고) - 그래서
      "무엇이 깨졌는지"는 Cache에 없다. 여기서 직접 확인한다.
    - Missing ROM: Metadata는 있는데 그 ROM 파일이 없는 항목(§3).
    - Missing Metadata(이름 없음): `name`/`title`이 빈 항목(§2).
    - Duplicate Metadata: 같은 ROM 파일명에 블록이 두 개 이상(§6) - `read_index()`는
      dict라서 중복이 있어도 마지막 것만 남아 조용히 사라진다. `raw_metadata_filenames()`
      로 원본 개수를 그대로 본다.
    """
    checked, invalid, duplicates, issues = 0, [], [], []
    for entry in collection.systems:
        layout = adapter.layout(collection, entry.system)
        path = layout.metadata_file
        if not path or not provider.exists(path):
            continue
        checked += 1

        error = adapter.validate_metadata_syntax(provider, path)
        if error:
            invalid.append({"system": entry.system, "path": str(path), "error": error})
            continue   # 파일 자체가 안 읽히면 그 안의 게임을 볼 방법이 없다

        for filename, count in Counter(adapter.raw_metadata_filenames(provider, layout)).items():
            if count > 1:
                duplicates.append({"system": entry.system, "filename": filename, "count": count})

        rom_files = set(adapter.list_roms(provider, layout))
        for filename, game in adapter.read_index(provider, layout).items():
            fields = game.fields or {}
            game_issues = []
            if not (fields.get("name") or "").strip():
                game_issues.append("missingMetadata")
            if filename not in rom_files:
                game_issues.append("missingRom")
            if game_issues:
                issues.append({"system": entry.system, "filename": filename, "issues": game_issues})

    health = cache.metadata_health()
    return {
        "checked": checked, "invalid": invalid,
        "duplicates": duplicates, "issues": issues,
        # Dashboard가 최소로 보여줘야 하는 네 상태(사용자 요구). complete/missingMedia/
        # missingDescription은 위에서 말했듯 cache.metadata_health()와 같은 값이다.
        "statuses": {
            "complete": health["complete"],
            "missingMedia": health["missingMedia"],
            "missingDescription": health["missingDescription"],
            "invalidXml": len(invalid),
        },
    }
