"""User-imported Logiqx DAT and MAME listxml title index.

An index hit suggests a search phrase. It never confirms a remote game ID:
CRC collisions, patched ROMs and differing DAT versions still need review.
"""

from __future__ import annotations

import logging
import sqlite3
import time
import xml.etree.ElementTree as ET
import zipfile
from contextlib import closing
from pathlib import Path

from app.scrape.providers.screenscraper import ARCADE_SYSTEMS, _system_id

log = logging.getLogger(__name__)


def _tag(element):
    return element.tag.rsplit("}", 1)[-1]


def _text(element, child):
    found = next((part for part in element if _tag(part) == child), None)
    return (found.text or "").strip() if found is not None else ""


def _crc(value):
    value = str(value or "").strip().upper()
    return value.zfill(8) if value and all(c in "0123456789ABCDEF" for c in value) else ""


def _system_key(value):
    key = str(value or "").strip().casefold()
    return _system_id(key) or key


class _DatReader:
    """Allow MAME's element DTD, but reject entity declarations."""
    def __init__(self, stream):
        self.stream, self.tail = stream, b""

    def read(self, size=-1):
        data = self.stream.read(size)
        checked = (self.tail + data).upper()
        if b"<!ENTITY" in checked:
            raise ValueError("Entity 선언이 포함된 DAT는 가져올 수 없습니다.")
        self.tail = checked[-16:]
        return data


def _rom_signature(path):
    """Read ZIP central-directory metadata; never decompress a ROM for lookup."""
    path = Path(path)
    if path.suffix.casefold() != ".zip":
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            if len(members) == 1:
                return members[0].file_size, f"{members[0].CRC:08X}"
    except (OSError, ValueError, zipfile.BadZipFile):
        pass
    return None


class DatCatalog:
    def __init__(self, db_path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS dat_source (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, system TEXT NOT NULL,
                    version TEXT NOT NULL, imported_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dat_entry (
                    source_id INTEGER NOT NULL, game_name TEXT NOT NULL,
                    shortname TEXT NOT NULL, rom_name TEXT NOT NULL,
                    size INTEGER, crc32 TEXT NOT NULL, parent TEXT NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES dat_source(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS dat_entry_crc
                    ON dat_entry(source_id, size, crc32);
                CREATE INDEX IF NOT EXISTS dat_entry_short
                    ON dat_entry(source_id, shortname);
                CREATE INDEX IF NOT EXISTS dat_entry_rom
                    ON dat_entry(source_id, rom_name);
                CREATE INDEX IF NOT EXISTS dat_source_system ON dat_source(system);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(dat_source)")}
            if "system_key" not in columns:
                db.execute("ALTER TABLE dat_source ADD COLUMN system_key TEXT NOT NULL DEFAULT ''")
            for source_id, system in db.execute(
                    "SELECT id,system FROM dat_source WHERE system_key=''").fetchall():
                db.execute("UPDATE dat_source SET system_key=? WHERE id=?",
                           (_system_key(system), source_id))
            db.execute("CREATE INDEX IF NOT EXISTS dat_source_system_key ON dat_source(system_key)")
            db.commit()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def sources(self):
        with closing(self._connect()) as db:
            return [dict(zip(("id", "name", "system", "version", "entries"), row))
                    for row in db.execute("""
                        SELECT s.id,s.name,s.system,s.version,COUNT(e.source_id)
                        FROM dat_source s LEFT JOIN dat_entry e ON e.source_id=s.id
                        GROUP BY s.id ORDER BY s.imported_at DESC
                    """)]

    def import_xml(self, filename, system, progress=None):
        path = Path(filename)
        if not path.is_file() or path.suffix.casefold() not in {".xml", ".dat"}:
            raise ValueError("Logiqx DAT 또는 MAME listxml 파일을 선택하세요.")
        system = str(system or "").strip().casefold()
        system = "arcade" if system in ARCADE_SYSTEMS else system
        if not system:
            raise ValueError("DAT에 대응할 System을 선택하세요.")
        name, version, count = path.stem, "", 0
        with closing(self._connect()) as db, path.open("rb") as stream:
            db.execute("BEGIN")
            source_id = db.execute(
                "INSERT INTO dat_source(name,system,version,imported_at,system_key) VALUES(?,?,?,?,?)",
                (name, system, version, time.time(), _system_key(system))).lastrowid
            try:
                context = ET.iterparse(_DatReader(stream), events=("start", "end"))
                root = next(context)[1]
                if _tag(root) not in {"datafile", "mame", "mess"}:
                    raise ValueError("지원하지 않는 DAT 형식입니다.")
                batch = []
                for event, element in context:
                    if event != "end":
                        continue
                    tag = _tag(element)
                    if tag == "header":
                        name = _text(element, "name") or name
                        version = _text(element, "version")
                        element.clear()
                    elif tag in {"game", "machine"}:
                        shortname = element.get("name", "").strip()
                        title = _text(element, "description") or shortname
                        parent = (element.get("cloneof") or element.get("romof") or "").strip()
                        rom_count = 0
                        for rom in element.iter():
                            if _tag(rom) != "rom":
                                continue
                            rom_count += 1
                            try:
                                size = int(rom.get("size", ""))
                            except (ValueError, TypeError):
                                size = None
                            batch.append((source_id, title, shortname.casefold(),
                                          Path(rom.get("name", "")).name.casefold(),
                                          size, _crc(rom.get("crc")), parent.casefold()))
                        if not rom_count:
                            batch.append((source_id, title, shortname.casefold(), "", None, "",
                                          parent.casefold()))
                        count += 1
                        if len(batch) >= 1000:
                            db.executemany("INSERT INTO dat_entry VALUES(?,?,?,?,?,?,?)", batch)
                            batch.clear()
                        if progress and count % 500 == 0:
                            progress(count, 0, f"DAT 읽는 중 · {count:,}개 게임")
                        element.clear()
                        # MAME/Logiqx games are direct root children. Clearing only
                        # their content retains one empty node per game indefinitely.
                        root.remove(element)
                    elif element is not root and tag not in {"rom", "description"}:
                        # Keep the current game's children until its end event.
                        pass
                if batch:
                    db.executemany("INSERT INTO dat_entry VALUES(?,?,?,?,?,?,?)", batch)
                if not count:
                    raise ValueError("DAT에서 게임 항목을 찾지 못했습니다.")
                db.execute("UPDATE dat_source SET name=?,version=? WHERE id=?",
                           (name, version, source_id))
                db.commit()
            except Exception:
                db.rollback()
                raise
        log.info("DAT imported source=%s version=%s system=%s games=%d", name, version, system, count)
        return {"id": source_id, "name": name, "version": version,
                "system": system, "games": count}

    def lookup(self, system, filename, path=None, size=None):
        system = _system_key(system)
        stem = Path(filename).stem.casefold()
        filename_key = Path(filename).name.casefold()
        signature = _rom_signature(path) if path else None
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            if signature:
                matches = db.execute("""
                    SELECT e.*,s.name AS source_name,s.version FROM dat_entry e
                    JOIN dat_source s ON s.id=e.source_id
                    WHERE s.system_key=? AND e.size=? AND e.crc32=?
                    ORDER BY s.imported_at DESC
                """, (system, *signature)).fetchall()
                # Ambiguous cross-game CRC is not a reliable lookup.
                if matches and len({row["shortname"] for row in matches}) == 1:
                    return self._result(matches[0], "zip-entry-size-crc")
            matches = db.execute("""
                SELECT e.*,s.name AS source_name,s.version FROM dat_entry e
                JOIN dat_source s ON s.id=e.source_id
                WHERE s.system_key=? AND e.shortname=?
                ORDER BY s.imported_at DESC
            """, (system, stem)).fetchall()
            if matches and len({row["game_name"] for row in matches}) == 1:
                return self._result(matches[0], "shortname")
            matches = db.execute("""
                SELECT e.*,s.name AS source_name,s.version FROM dat_entry e
                JOIN dat_source s ON s.id=e.source_id
                WHERE s.system_key=? AND e.rom_name=?
                ORDER BY s.imported_at DESC
            """, (system, filename_key)).fetchall()
            if matches and len({row["game_name"] for row in matches}) == 1:
                return self._result(matches[0], "rom-name")
        return None

    @staticmethod
    def _result(row, method):
        result = {"title": row["game_name"], "method": method,
                  "source": row["source_name"], "version": row["version"],
                  "parent": row["parent"], "shortname": row["shortname"]}
        log.info("DAT title hint method=%s source=%s version=%s shortname=%s title=%s",
                 method, result["source"], result["version"], result["shortname"], result["title"])
        return result

