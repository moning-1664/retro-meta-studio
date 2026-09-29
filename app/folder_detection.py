"""Read-only, shallow evidence for adding a local Collection or Archive."""

from __future__ import annotations

from pathlib import Path

from app.archive.shared_cache import _is_portable_snapshot, snapshot_path
from app.archive.legacy import has_legacy
from app.model.constants import ESDE_IGNORED_SYSTEMS


def inspect_folder(folder: str) -> dict:
    try:
        return _inspect_folder(folder)
    except OSError as exc:
        raise ValueError("폴더를 읽을 수 없습니다. 경로와 접근 권한을 확인하세요.") from exc


def _inspect_folder(folder: str) -> dict:
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise ValueError("폴더를 읽을 수 없습니다. 경로와 접근 권한을 확인하세요.")

    # Only list the selected folder and immediate children. Never parse XML,
    # enumerate ROM files recursively, or create a database during detection.
    children = {entry.name.lower(): entry for entry in root.iterdir()}
    dirs = {name: entry for name, entry in children.items() if entry.is_dir()}
    findings = []

    def add(frontend, evidence, strong, systems=()):
        findings.append({"frontend": frontend, "evidence": evidence,
                         "strong": strong, "systems": sorted(set(systems))})

    platforms = dirs.get("data")
    platforms = platforms / "Platforms" if platforms else None
    if platforms and platforms.is_dir():
        names = [p.stem for p in platforms.iterdir() if p.is_file() and p.suffix.lower() == ".xml"]
        if names:
            add("launchbox", "Data/Platforms의 플랫폼 XML", True, names)

    gamelists = dirs.get("gamelists")
    downloaded = dirs.get("downloaded_media")
    central = [p.name for p in gamelists.iterdir()
               if p.is_dir() and p.name.lower() not in ESDE_IGNORED_SYSTEMS] if gamelists else []
    if gamelists or downloaded:
        add("es-de", "gamelists + downloaded_media" if gamelists and downloaded else
            "gamelists 또는 downloaded_media", bool(gamelists and downloaded), central)
    if gamelists and not downloaded:
        add("emulationstation", "gamelists (ES-DE와 공통 구조)", False, central)

    pegasus, pegasus_generic, es_systems = [], [], []
    reserved = {"gamelists", "downloaded_media", "data", "images", "games", "media", ".rms"}
    for name, entry in dirs.items():
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
    archive = _is_portable_snapshot(portable)
    legacy_archive = has_legacy(str(root))
    findings.sort(key=lambda item: (not item["strong"], item["frontend"]))
    suggested = findings[0]["frontend"] if findings and findings[0]["strong"] and (
        len(findings) == 1 or not findings[1]["strong"]) else None
    return {"path": str(root), "archive": archive, "legacyArchive": legacy_archive,
            "findings": findings,
            "suggestedFrontend": suggested}
