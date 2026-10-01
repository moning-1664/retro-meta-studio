"""Candidate discovery for importing from another open Collection."""

from __future__ import annotations

from adapters import get_adapter
from app.match import engine
from app.model.constants import normalize_system, metadata_compatible
from app.plan import builder, clipboard, transfer


def candidates(target, target_row, source, source_cache, limit=8):
    target_system = normalize_system(target.frontend, target_row["system"])
    left = {**engine.subject_of_row(target_row), "system": target_system}
    source_systems = [entry.system for entry in source.systems
                      if normalize_system(source.frontend, entry.system) == target_system]
    indexed = source_cache.indexed_import_candidates(
        source_systems, left["title_norm"], target_row["filename"])
    def match(rows):
        found = []
        for row in rows:
            right = {**engine.subject_of_row(row), "system": target_system}
            tier, score, evidence = engine.classify_pair(left, right)
            if not tier:
                continue
            found.append({"romUid": row["rom_uid"], "romIdentityId": row["rom_uid"],
                          "system": row["system"], "filename": row["filename"],
                          "title": row["title"], "fields": row["fields"],
                          "mediaTypes": row["media_types"], "tier": tier,
                          "score": score, "evidence": evidence})
        return found
    found = match(indexed)
    if not any(item["tier"] == engine.TIER_EXACT for item in found):
        found = match(source_cache.all_entries(systems=source_systems) if source_systems else [])
    if not found:
        related = [entry.system for entry in source.systems if entry.system not in source_systems
                   and metadata_compatible(target_system, entry.system)]
        found = match(source_cache.all_entries(systems=related) if related else [])
        for candidate in found:
            if candidate["tier"] == engine.TIER_EXACT:
                candidate["tier"] = engine.TIER_NORMALIZED
            candidate["evidence"].append(f"같은 메타데이터 계열: {candidate['system']}")
    found.sort(key=lambda row: (engine.TIER_RANK[row["tier"]], -row["score"], row["filename"]))
    return found[:limit]


def plan_import(plan, source, source_cache, target, target_cache, provider,
                rom_uids, *, mode="patch", policy=None, target_row=None,
                target_system=None):
    """Stage an explicit Collection import without touching the global clipboard."""
    policy = policy or {}
    rom_uids = [int(uid) for uid in rom_uids]
    if not rom_uids:
        return {"planned": 0, "conflicts": 0, "skipped": [], "requested": 0}
    if target_row is not None and len(rom_uids) != 1:
        raise ValueError("게임 한 개를 선택하세요.")
    downgraded = False
    mode = transfer.normalize_mode(mode)
    items, _ = clipboard.build_items(source, source_cache, rom_uids)
    target_adapter = get_adapter(target.frontend)
    target_systems = {}
    for entry in target.systems:
        key = normalize_system(target.frontend, entry.system)
        target_systems.setdefault(key, []).append(entry.system)
    prepared, skipped = [], []
    for item in items:
        source_system = normalize_system(source.frontend, item["system"])
        choices = target_systems.get(source_system, [])
        if target_row is not None:
            if not metadata_compatible(source_system, normalize_system(target.frontend, target_row["system"])):
                skipped.append({"filename": item["filename"], "reason": "System이 다릅니다."})
                continue
            destination = target_row["system"]
        elif target_system is not None:
            if not metadata_compatible(source_system, normalize_system(target.frontend, target_system)):
                continue
            destination = target_system
        elif len(choices) == 1:
            destination = choices[0]
        else:
            skipped.append({"filename": item["filename"],
                            "reason": "대상 System을 한 개로 정할 수 없습니다."})
            continue
        if (target_row is None and source_system != normalize_system(target.frontend, destination)
                and target_cache.get_row_by_filename(destination, item["filename"]) is None):
            skipped.append({"filename": item["filename"], "reason": "대상 System에 같은 파일명의 게임이 없습니다."})
            continue
        mapped = {**item, "system": destination, "origin": "collection",
                  "sourceName": source.name,
                  "rom": item.get("rom") if policy.get("includeRom", True) and source_system == normalize_system(target.frontend, destination) else None,
                  "media": item.get("media") if policy.get("includeMedia", True) else [],
                  "frontend_raw": (item.get("frontend_raw") or {})
                  if target_adapter.raw_is_mine(item.get("frontend_raw") or {}) else {}}
        if target_row is not None:
            result, reason = transfer.decide(mapped, target_row, mode)
            if result:
                prepared.append({**result, "filename": target_row["filename"]})
            else:
                skipped.append({"filename": item["filename"], "reason": reason})
        else:
            prepared.append(mapped)
    if target_row is None and prepared:
        prepared, more_skipped = transfer.prepare(prepared, target_cache, mode, exact_only=True)
        skipped.extend(more_skipped)
    result = builder.plan_add(plan, target, provider, prepared) if prepared else {
        "added": 0, "conflicts": 0, "skipped": []}
    keys = list(dict.fromkeys(result.get("keys", [])))
    return {"planned": len(keys), "keys": keys,
            "conflicts": sum(bool(plan.get(key).conflicts) for key in keys),
            "skipped": skipped + result["skipped"], "requested": len(rom_uids),
            "downgradedFrom": "replace" if downgraded else None}
