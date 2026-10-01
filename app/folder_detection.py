"""Read-only, shallow evidence for adding a local Collection or Archive."""

from __future__ import annotations

from pathlib import Path
import os
import xml.etree.ElementTree as ET

from app.archive.shared_cache import _is_portable_snapshot, snapshot_path
from app.archive.legacy import has_legacy
from app.model.constants import ESDE_IGNORED_SYSTEMS


def inspect_folder(folder: str, progress_cb=None) -> dict:
    try:
        result = _inspect_folder(folder, progress_cb)
        if result["findings"] or result["archive"]:
            return result
        pending = [(Path(folder).expanduser(), 0)]
        found = []
        visited = 0
        while pending and visited < 50:
            parent, depth = pending.pop(0)
            if depth >= 2:
                continue
            for child in parent.iterdir():
                if progress_cb:
                    progress_cb(0, 1, child.name)
                if child.name.startswith(".") or not child.is_dir() or child.is_symlink():
                    continue
                visited += 1
                if visited > 50:
                    break
                try:
                    candidate = _inspect_folder(str(child), progress_cb)
                except OSError:
                    continue
                if candidate["suggestedFrontend"] or candidate["archive"]:
                    found.append(candidate)
                else:
                    pending.append((child, depth + 1))
        if len(found) == 1 and visited <= 50 and not pending:
            return {**found[0], "selectedPath": result["path"]}
        return {**result, "nestedCandidates": found}
    except OSError as exc:
        raise ValueError("폴더를 읽을 수 없습니다. 경로와 접근 권한을 확인하세요.") from exc


def _inspect_folder(folder: str, progress_cb=None) -> dict:
    def checkpoint(label):
        if progress_cb:
            progress_cb(0, 1, label)
    root = Path(folder).expanduser()
    checkpoint("폴더 확인")
    if not root.is_dir():
        raise ValueError("폴더를 읽을 수 없습니다. 경로와 접근 권한을 확인하세요.")

    # Only list the selected folder and immediate children. Never parse XML,
    # enumerate ROM files recursively, or create a database during detection.
    children = {entry.name.lower(): entry for entry in root.iterdir()}
    dirs = {}
    for name, entry in children.items():
        checkpoint(entry.name)
        if entry.is_dir():
            dirs[name] = entry
    findings = []

    def add(frontend, evidence, strong, systems=()):
        findings.append({"frontend": frontend, "evidence": evidence,
                         "strong": strong, "systems": sorted(set(systems))})

    platforms = dirs.get("data")
    platforms = platforms / "Platforms" if platforms else None
    if platforms and platforms.is_dir():
        names = []
        for p in platforms.iterdir():
            checkpoint(p.name)
            if p.is_file() and p.suffix.lower() == ".xml":
                names.append(p.stem)
        if names:
            add("launchbox", "Data/Platforms의 플랫폼 XML", True, names)

    gamelists = dirs.get("gamelists")
    downloaded = dirs.get("downloaded_media")
    central = []
    if gamelists:
        for p in gamelists.iterdir():
            checkpoint(p.name)
            if p.is_dir() and p.name.lower() not in ESDE_IGNORED_SYSTEMS:
                central.append(p.name)
    if gamelists or downloaded:
        add("es-de", "gamelists + downloaded_media" if gamelists and downloaded else
            "gamelists 또는 downloaded_media", bool(gamelists and downloaded), central)
    if gamelists and not downloaded:
        add("emulationstation", "gamelists (ES-DE와 공통 구조)", False, central)

    pegasus, pegasus_generic, es_systems = [], [], []
    reserved = {"gamelists", "downloaded_media", "data", "images", "games", "media", ".rms"}
    for name, entry in dirs.items():
        checkpoint(entry.name)
        if name in reserved:
            continue
        if (entry / "metadata.pegasus.txt").is_file():
            pegasus.append(entry.name)
        elif (entry / "metadata.txt").is_file():
            pegasus_generic.append(entry.name)
        if (entry / "gamelist.xml").is_file():
            es_systems.append(entry.name)
    if pegasus:
        add("pegasus", "시스템 폴더의 metadata.pegasus.txt", True, pegasus)
    elif pegasus_generic:
        add("pegasus", "시스템 폴더의 metadata.txt", False, pegasus_generic)
    if es_systems:
        add("emulationstation", "시스템 폴더의 gamelist.xml", True, es_systems)

    portable = snapshot_path(str(root))
    checkpoint("Archive DB 확인")
    archive = _is_portable_snapshot(portable)
    legacy_archive = has_legacy(str(root))
    findings.sort(key=lambda item: (not item["strong"], item["frontend"]))
    suggested = findings[0]["frontend"] if findings and findings[0]["strong"] and (
        len(findings) == 1 or not findings[1]["strong"]) else None
    rom_dir = None
    for settings in (root / "settings" / "es_settings.xml", root / "es_settings.xml"):
        checkpoint("ROM 경로 확인")
        if not settings.is_file() or settings.stat().st_size > 1024 * 1024:
            continue
        try:
            for entry in ET.parse(settings).iter("string"):
                if entry.get("name") != "ROMDirectory":
                    continue
                value = os.path.expandvars(entry.get("value") or "")
                if not value:
                    continue
                path = Path(value).expanduser()
                path = path if path.is_absolute() else root / path
                if path.is_dir():
                    rom_dir = str(path.resolve())
        except (ET.ParseError, OSError):
            pass
    return {"path": str(root), "archive": archive, "legacyArchive": legacy_archive,
            "suggestedRomDir": rom_dir,
            "findings": findings,
            "suggestedFrontend": suggested}
