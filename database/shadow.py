"""JSON/SQLite shadow consistency checking for the v0.5 migration.

The checker deliberately compares canonical semantic projections instead of raw
JSON/SQLite representations.  This lets the two stores use different internal
IDs/orderings while still detecting real data divergence.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


MODES = {"off", "shadow", "strict"}


def _clean(value: Any):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


class ShadowConsistencyChecker:
    def __init__(self, log_path: str | Path, mode: str = "shadow"):
        self.log_path = Path(log_path)
        self.mode = mode if mode in MODES else "off"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.stats = Counter()

    @property
    def enabled(self):
        return self.mode != "off"

    def set_mode(self, mode: str):
        mode = str(mode or "off").lower()
        if mode not in MODES:
            raise ValueError(f"Unsupported shadow mode: {mode}")
        self.mode = mode

    def _write(self, operation: str, mismatch: dict):
        record = {
            "event": "DB_SHADOW_MISMATCH",
            "operation": operation,
            "mode": self.mode,
            "mismatch": mismatch,
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def compare(self, operation: str, json_value: Any, sqlite_value: Any) -> bool:
        if not self.enabled:
            return True
        self.stats["comparisons"] += 1
        left = _clean(_jsonable(json_value))
        right = _clean(_jsonable(sqlite_value))
        if left == right:
            self.stats["matches"] += 1
            return True
        self.stats["mismatches"] += 1
        self._write(operation, {"json": left, "sqlite": right})
        if self.mode == "strict":
            raise AssertionError(f"JSON/SQLite mismatch during {operation}")
        return False

    def compare_db_projection(self, operation: str, legacy_db: dict, sqlite_repo) -> bool:
        """Compare the migration-relevant MasterDB projection."""
        legacy = self._legacy_projection(legacy_db)
        native = self._sqlite_projection(sqlite_repo)
        return self.compare(operation, legacy, native)

    @staticmethod
    def _legacy_projection(data: dict) -> dict:
        roms = {}
        for key, entry in (data.get("roms") or {}).items():
            entry = entry or {}
            versions = {}
            for vid, version in (entry.get("versions") or {}).items():
                version = version or {}
                versions[str(vid)] = {
                    "created_at": version.get("created_at", ""),
                    "source_local_id": version.get("source_local_id", ""),
                    "uncertain_match": bool(version.get("uncertain_match", False)),
                    "fields": version.get("fields") or {},
                }
            roms[str(key)] = {
                "system": entry.get("system", ""),
                "filename": entry.get("rom_filename", ""),
                "default_version_id": entry.get("default_version_id"),
                "core_override": entry.get("core_override"),
                "versions": versions,
                "media": entry.get("media") or {},
            }
        return {"roms": roms}

    @staticmethod
    def _sqlite_projection(repo) -> dict:
        roms = {}
        for item in repo.list_roms():
            versions = {}
            for version in item.get("versions") or []:
                versions[str(version.get("version_id", ""))] = {
                    "created_at": version.get("created_at", ""),
                    "source_local_id": version.get("source_local_id", ""),
                    "uncertain_match": bool(version.get("uncertain_match", False)),
                    "fields": version.get("fields") or {},
                }
            roms[str(item["romKey"])] = {
                "system": item.get("system", ""),
                "filename": item.get("file", ""),
                "default_version_id": item.get("default_version_id"),
                "core_override": item.get("core_override"),
                "versions": versions,
                "media": item.get("media") or {},
            }
        return {"roms": roms}

    @staticmethod
    def _legacy_rom_projection(entry: dict) -> dict:
        entry = entry or {}
        versions = {}
        for vid, version in (entry.get("versions") or {}).items():
            version = version or {}
            versions[str(vid)] = {
                "created_at": version.get("created_at", ""),
                "source_local_id": version.get("source_local_id", ""),
                "uncertain_match": bool(version.get("uncertain_match", False)),
                "fields": version.get("fields") or {},
            }
        return {
            "system": entry.get("system", ""),
            "filename": entry.get("rom_filename", ""),
            "default_version_id": entry.get("default_version_id"),
            "core_override": entry.get("core_override"),
            "versions": versions,
            "media": entry.get("media") or {},
        }

    @staticmethod
    def _sqlite_rom_projection(entry: dict) -> dict:
        entry = entry or {}
        versions = {}
        for version in (entry.get("versions") or []):
            versions[str(version.get("version_id", ""))] = {
                "created_at": version.get("created_at", ""),
                "source_local_id": version.get("source_local_id", ""),
                "uncertain_match": bool(version.get("uncertain_match", False)),
                "fields": version.get("fields") or {},
            }
        return {
            "system": entry.get("system", ""),
            "filename": entry.get("file", ""),
            "default_version_id": entry.get("default_version_id"),
            "core_override": entry.get("core_override"),
            "versions": versions,
            "media": entry.get("media") or {},
        }

    def compare_rom_entry(self, operation: str, legacy_entry: dict, sqlite_entry: dict) -> bool:
        return self.compare(operation, self._legacy_rom_projection(legacy_entry), self._sqlite_rom_projection(sqlite_entry))

    def compare_write(self, operation: str, legacy_db: dict, sqlite_repo) -> bool:
        self.stats["writes_checked"] += 1
        return self.compare_db_projection(operation, legacy_db, sqlite_repo)

    def summary(self) -> dict:
        return {
            "mode": self.mode,
            "comparisons": self.stats["comparisons"],
            "matches": self.stats["matches"],
            "mismatches": self.stats["mismatches"],
            "writesChecked": self.stats["writes_checked"],
            "logPath": str(self.log_path),
        }

    def close(self):
        return None
