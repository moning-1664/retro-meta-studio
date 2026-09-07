"""
cleanup_engine.py
==================
Local의 Reset Metadata / Orphan Cleanup 실행 (설계서 v2 §13).

- Reset Metadata: 해당 Local의 모든 metadata/media를 일괄 삭제 (ROM 파일은 유지).
- Orphan Cleanup: ROM이 없는데 metadata/media만 남아있는 경우 해당 항목만 삭제.

same_dir Frontend(Pegasus, 다이지쇼)는 ROM과 metadata가 같은 폴더에 있으므로
디렉토리 전체 삭제가 아닌 metadata 파일/media 서브폴더만 선별 삭제한다.
"""

import shutil
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from importers import get_importer
from importers.base import es_media_root
from config import validate_local_paths


# ---------------------------------------------------------------------------
# Reset Metadata (전체 삭제)
# ---------------------------------------------------------------------------

def reset_metadata(local_entry, progress_cb=None):
    """해당 Local의 모든 metadata/media를 삭제. 반환: 삭제된 항목 요약 dict.

    [안전장치] 파일을 실제로 삭제하는 함수이므로, 경로 미검증 상태로 실행되면
    (예: 빈 문자열 경로가 cwd로 해석되는 pathlib 특성 때문에) 엉뚱한 위치의 파일이
    삭제될 위험이 있다. 반드시 validate_local_paths를 먼저 통과해야 한다.

    progress_cb(current, total, label): 시스템 단위 진행 상황 콜백 (선택)."""
    validate_local_paths(local_entry)

    frontend = local_entry["frontend"]
    metadata_path = Path(local_entry["metadata_path"])
    media_path = Path(local_entry["media_path"])

    removed = {"metadata_files": 0, "media_dirs_cleared": 0}

    if frontend in ("es-de", "emulationstation"):
        gamelists_dir = metadata_path / "gamelists"
        system_dirs = [d for d in gamelists_dir.iterdir() if d.is_dir()] if gamelists_dir.exists() else []
        total = max(1, len(system_dirs))
        for idx, system_dir in enumerate(system_dirs, start=1):
            if progress_cb:
                progress_cb(idx, total, system_dir.name)
            if (system_dir / "gamelist.xml").exists():
                (system_dir / "gamelist.xml").unlink()
                removed["metadata_files"] += 1
        # [BUG FIX] media_path를 그대로 순회하면 ES-DE 루트 폴더의 모든 최상위 폴더가
        # 통째로 삭제된다 (downloaded_media 뿐 아니라 themes/collections/settings, 심지어
        # ROM 폴더가 같은 루트 안에 있는 구조라면 ROM까지 삭제될 수 있는 심각한 버그였음).
        # es_media_root()로 downloaded_media 하위만 정확히 범위를 좁힌다.
        media_root = es_media_root(media_path)
        if media_root.exists():
            for system_dir in media_root.iterdir():
                if system_dir.is_dir():
                    shutil.rmtree(system_dir, ignore_errors=True)
                    removed["media_dirs_cleared"] += 1

    elif frontend == "pegasus":
        # same_dir: metadata_path == rom_path. system별 metadata.pegasus.txt와 media/만 제거.
        system_dirs = [d for d in metadata_path.iterdir() if d.is_dir()] if metadata_path.exists() else []
        total = max(1, len(system_dirs))
        for idx, system_dir in enumerate(system_dirs, start=1):
            if progress_cb:
                progress_cb(idx, total, system_dir.name)
            txt = system_dir / "metadata.pegasus.txt"
            if txt.exists():
                txt.unlink()
                removed["metadata_files"] += 1
            media_dir = system_dir / "media"
            if media_dir.exists():
                shutil.rmtree(media_dir, ignore_errors=True)
                removed["media_dirs_cleared"] += 1

    elif frontend == "launchbox":
        if progress_cb:
            progress_cb(1, 2, "metadata")
        platforms_dir = metadata_path / "Data" / "Platforms"
        if platforms_dir.exists():
            for xml_file in platforms_dir.glob("*.xml"):
                xml_file.unlink()
                removed["metadata_files"] += 1
        if progress_cb:
            progress_cb(2, 2, "media")
        images_dir = media_path / "Images"
        if images_dir.exists():
            shutil.rmtree(images_dir, ignore_errors=True)
            removed["media_dirs_cleared"] += 1

    else:
        raise NotImplementedError(f"{frontend}의 Reset Metadata는 아직 지원되지 않습니다.")

    return removed


# ---------------------------------------------------------------------------
# Orphan Cleanup (ROM 없는 항목만 삭제)
# ---------------------------------------------------------------------------

def _referenced_filenames_es_style(metadata_path, system):
    gamelist = Path(metadata_path) / "gamelists" / system / "gamelist.xml"
    if not gamelist.exists():
        return set()
    try:
        tree = ET.parse(gamelist)
    except ET.ParseError:
        return set()
    result = set()
    for game in tree.getroot().findall("game"):
        path_text = (game.findtext("path") or "").strip()
        if path_text:
            result.add(Path(path_text).name)
    return result


def _remove_es_style_entry(metadata_path, media_path, system, rom_filename):
    gamelist = Path(metadata_path) / "gamelists" / system / "gamelist.xml"
    if gamelist.exists():
        try:
            tree = ET.parse(gamelist)
            root = tree.getroot()
            for game in list(root.findall("game")):
                path_text = (game.findtext("path") or "").strip()
                if Path(path_text).name == rom_filename:
                    root.remove(game)
            tree.write(gamelist, encoding="utf-8", xml_declaration=True)
        except ET.ParseError:
            pass

    stem = Path(rom_filename).stem
    # [BUG FIX] es_media_root()를 안 거치면 ES-DE에서 실제 media 폴더(downloaded_media 하위)를
    # 못 찾아서 media_dir.exists()가 항상 False가 되고, media 파일이 조용히 하나도 안 지워지는
    # 버그가 있었다 (CleanUp의 ROM 삭제 버그와 같은 종류의 실수 - 이번엔 반대로 "안 지워짐").
    media_dir = es_media_root(media_path) / system
    if media_dir.exists():
        for subdir in media_dir.iterdir():
            if subdir.is_dir():
                for f in subdir.iterdir():
                    if f.is_file() and f.stem == stem:
                        f.unlink()


def _referenced_filenames_pegasus(metadata_path, system):
    txt = Path(metadata_path) / system / "metadata.pegasus.txt"
    if not txt.exists():
        return set()
    text = txt.read_text(encoding="utf-8", errors="ignore")
    return {Path(m).name for m in re.findall(r"(?im)^file:\s*(.+)$", text)}


def _remove_pegasus_entry(metadata_path, media_path, system, rom_filename):
    txt = Path(metadata_path) / system / "metadata.pegasus.txt"
    if txt.exists():
        blocks = re.split(r"\n\s*\n", txt.read_text(encoding="utf-8", errors="ignore"))
        kept = []
        for b in blocks:
            file_line = next((l for l in b.splitlines() if l.strip().lower().startswith("file:")), None)
            if file_line and Path(file_line.split(":", 1)[1].strip()).name == rom_filename:
                continue
            if b.strip():
                kept.append(b)
        txt.write_text("\n\n".join(kept) + "\n", encoding="utf-8")

    stem = Path(rom_filename).stem
    media_dir = Path(media_path) / system / "media" / stem
    if media_dir.exists():
        shutil.rmtree(media_dir, ignore_errors=True)


def _referenced_filenames_launchbox(metadata_path, system):
    xml_path = Path(metadata_path) / "Data" / "Platforms" / f"{system}.xml"
    if not xml_path.exists():
        return set()
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return set()
    result = set()
    for game in tree.getroot().findall("Game"):
        app_path = game.findtext("ApplicationPath", "")
        if app_path:
            result.add(Path(app_path).name)
    return result


def _remove_launchbox_entry(metadata_path, media_path, system, rom_filename):
    xml_path = Path(metadata_path) / "Data" / "Platforms" / f"{system}.xml"
    if xml_path.exists():
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            for game in list(root.findall("Game")):
                app_path = game.findtext("ApplicationPath", "")
                if app_path and Path(app_path).name == rom_filename:
                    root.remove(game)
            tree.write(xml_path, encoding="utf-8", xml_declaration=True)
        except ET.ParseError:
            pass

    stem = Path(rom_filename).stem
    images_dir = Path(media_path) / "Images" / system
    if images_dir.exists():
        for subdir in images_dir.iterdir():
            if subdir.is_dir():
                for f in subdir.iterdir():
                    if f.is_file() and f.stem == stem:
                        f.unlink()


_HANDLERS = {
    "es-de": (_referenced_filenames_es_style, _remove_es_style_entry),
    "emulationstation": (_referenced_filenames_es_style, _remove_es_style_entry),
    "pegasus": (_referenced_filenames_pegasus, _remove_pegasus_entry),
    "launchbox": (_referenced_filenames_launchbox, _remove_launchbox_entry),
}


def orphan_cleanup(local_entry, progress_cb=None):
    """ROM이 없는데 metadata/media만 존재하는 항목을 찾아 삭제. 반환: 삭제된 항목 목록.

    [안전장치] reset_metadata와 동일한 이유로 경로 검증을 먼저 수행한다.
    progress_cb(current, total, label): 시스템 단위 진행 상황 콜백 (선택)."""
    validate_local_paths(local_entry)

    frontend = local_entry["frontend"]
    if frontend not in _HANDLERS:
        raise NotImplementedError(f"{frontend}의 Orphan Cleanup은 아직 지원되지 않습니다.")

    get_referenced, remove_entry = _HANDLERS[frontend]
    importer = get_importer(frontend)

    rom_path = local_entry["rom_path"]
    metadata_path = local_entry["metadata_path"]
    media_path = local_entry["media_path"]

    systems = importer.list_systems(rom_path, metadata_path)
    removed = []
    total = max(1, len(systems))

    for idx, system in enumerate(systems, start=1):
        if progress_cb:
            progress_cb(idx, total, system)
        actual_files = {f.name for f in importer.list_roms(rom_path, system)}
        referenced = get_referenced(metadata_path, system)
        orphans = referenced - actual_files
        for rom_filename in orphans:
            remove_entry(metadata_path, media_path, system, rom_filename)
            removed.append({"system": system, "filename": rom_filename})

    return removed


def delete_local_roms(local_entry, targets):
    """Delete selected ROMs and their frontend metadata/media only."""
    validate_local_paths(local_entry)
    frontend = local_entry["frontend"]
    importer = get_importer(frontend)
    removed = {"roms": 0, "metadata": 0, "media": 0}
    for system, filename in targets:
        rom = Path(local_entry["rom_path"]) / system / filename
        if rom.exists() and rom.is_file():
            rom.unlink(); removed["roms"] += 1
        before = _metadata_exists(local_entry, system, filename)
        stem = Path(filename).stem
        media_before = _count_media_only(local_entry, system, stem)
        if frontend in ("es-de", "emulationstation"):
            _remove_es_style_entry(local_entry["metadata_path"], local_entry["media_path"], system, filename)
        elif frontend == "pegasus":
            _remove_pegasus_entry(local_entry["metadata_path"], local_entry["media_path"], system, filename)
        elif frontend == "launchbox":
            _remove_launchbox_entry(local_entry["metadata_path"], local_entry["media_path"], system, filename)
        else:
            raise NotImplementedError(f"{frontend}의 개별 삭제는 아직 지원되지 않습니다.")
        after = _metadata_exists(local_entry, system, filename)
        if before and not after: removed["metadata"] += 1
        removed["media"] += media_before
    return removed


def _metadata_exists(local_entry, system, filename):
    frontend = local_entry["frontend"]
    if frontend in ("es-de", "emulationstation"):
        return filename in _referenced_filenames_es_style(local_entry["metadata_path"], system)
    if frontend == "pegasus":
        return filename in _referenced_filenames_pegasus(local_entry["metadata_path"], system)
    if frontend == "launchbox":
        return filename in _referenced_filenames_launchbox(local_entry["metadata_path"], system)
    return False


def _count_media_only(local_entry, system, stem):
    frontend = local_entry["frontend"]
    if frontend in ("es-de", "emulationstation"):
        base = es_media_root(local_entry["media_path"]) / system
    elif frontend == "pegasus":
        base = Path(local_entry["media_path"]) / system / "media" / stem
    elif frontend == "launchbox":
        base = Path(local_entry["media_path"]) / "Images" / system
    else:
        return 0
    if not base.exists(): return 0
    return sum(1 for f in base.rglob("*") if f.is_file() and f.stem == stem)
