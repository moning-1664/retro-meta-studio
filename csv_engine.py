"""
csv_engine.py
==============
MasterDB metadata <-> CSV 변환 (일괄 편집용).

- Export: 모든 ROM의 **모든 Version**을 각각 한 행씩 CSV로 내보낸다 (default 여부 컬럼 포함).
- Import: "add" 방식 - CSV에만 있고 DB에 없는 (system, rom_filename, version_id) 조합은
  새 Version으로 추가한다. 반대로 CSV의 version_id가 DB에 이미 존재하면 해당 Version의
  필드를 CSV 내용으로 강제 덮어쓴다 (upsert). CSV에 없는 기존 DB의 Version/ROM은
  절대 건드리지 않는다 (전체 교체가 아님).
- media(이미지)는 CSV로 다루지 않는다 - 텍스트 metadata만 대상.
- 인코딩: UTF-8 BOM (엑셀 호환).
"""

import csv
from pathlib import Path

import db as dbmod

CSV_COLUMNS = [
    "system", "rom_filename", "version_id", "is_default",
    "created_at", "source_local_id", "uncertain_match",
    "name", "desc", "genre", "developer", "publisher",
    "releasedate", "region", "players", "rating", "tags",
]


def export_db_to_csv(db, csv_path):
    """MasterDB의 모든 ROM x 모든 Version을 CSV로 내보낸다. 반환: 내보낸 행 수."""
    csv_path = Path(csv_path)
    count = 0
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for rom_entry in db.get("roms", {}).values():
            default_vid = rom_entry.get("default_version_id")
            for vid, vdata in rom_entry.get("versions", {}).items():
                fields = vdata.get("fields", {})
                row = {
                    "system": rom_entry["system"],
                    "rom_filename": rom_entry["rom_filename"],
                    "version_id": vid,
                    "is_default": "1" if vid == default_vid else "0",
                    "created_at": vdata.get("created_at", ""),
                    "source_local_id": vdata.get("source_local_id", ""),
                    "uncertain_match": "1" if vdata.get("uncertain_match") else "0",
                    "name": fields.get("name", ""),
                    "desc": fields.get("desc", ""),
                    "genre": fields.get("genre", ""),
                    "developer": fields.get("developer", ""),
                    "publisher": fields.get("publisher", ""),
                    "releasedate": fields.get("releasedate", ""),
                    "region": fields.get("region", ""),
                    "players": fields.get("players", ""),
                    "rating": fields.get("rating", ""),
                    "tags": ";".join(fields.get("tags", []) or []),
                }
                writer.writerow(row)
                count += 1
    return count


def _row_to_fields(row):
    tags_raw = row.get("tags", "") or ""
    tags = [t.strip() for t in tags_raw.split(";") if t.strip()]
    return {
        "name": row.get("name", ""),
        "desc": row.get("desc", ""),
        "genre": row.get("genre", ""),
        "developer": row.get("developer", ""),
        "publisher": row.get("publisher", ""),
        "releasedate": row.get("releasedate", ""),
        "region": row.get("region", ""),
        "players": row.get("players", ""),
        "rating": row.get("rating", ""),
        "tags": tags,
    }


def import_csv_to_db(csv_path, db):
    """
    CSV -> MasterDB. "add" 방식(upsert):
      - version_id가 CSV에 있고 해당 ROM에 실제로 존재하면: 그 Version의 필드를 강제 덮어쓴다.
      - version_id가 비어있거나 DB에 없는 값이면: 새 Version으로 추가한다.
      - is_default가 참이면 해당 Version을 default로 지정한다.
      - media는 전혀 건드리지 않는다.

    반환: { "added": int, "overwritten": int, "errors": [str, ...] }
    """
    csv_path = Path(csv_path)
    result = {"added": 0, "overwritten": 0, "errors": []}

    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):  # 2행부터 (1행은 헤더)
            system = (row.get("system") or "").strip()
            rom_filename = (row.get("rom_filename") or "").strip()
            if not system or not rom_filename:
                result["errors"].append(f"{i}행: system/rom_filename이 비어있어 건너뜀")
                continue

            rom_entry = dbmod.get_or_create_rom_entry(db, system, rom_filename)
            fields = _row_to_fields(row)
            version_id = (row.get("version_id") or "").strip()
            is_default = str(row.get("is_default", "")).strip() in ("1", "true", "True")

            if version_id and version_id in rom_entry.get("versions", {}):
                # 기존 Version 강제 덮어쓰기
                rom_entry["versions"][version_id]["fields"] = {
                    k: fields.get(k, "" if k != "tags" else []) for k in dbmod.META_FIELD_KEYS
                }
                if row.get("source_local_id"):
                    rom_entry["versions"][version_id]["source_local_id"] = row["source_local_id"]
                if row.get("created_at"):
                    rom_entry["versions"][version_id]["created_at"] = row["created_at"]
                result["overwritten"] += 1
                target_vid = version_id
            else:
                # 새 Version으로 추가
                target_vid = dbmod.add_version(
                    rom_entry,
                    source_local_id=row.get("source_local_id") or "csv_import",
                    fields=fields,
                    uncertain_match=str(row.get("uncertain_match", "")).strip() in ("1", "true", "True"),
                )
                result["added"] += 1

            if is_default:
                dbmod.set_default_version(rom_entry, target_vid)

    return result
