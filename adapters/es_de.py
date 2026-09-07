"""
adapters/es_de.py
==================
ES-DE Frontend Adapter.

`importers/es_de.py` + `exporters/es_de.py` + `importers/base.py`의 ES-DE 부분을
하나로 합치고, 두 가지를 새로 지킨다.

**1. Storage를 안다.** 경로 계산이 `layout()` 한 곳에 모인다. 예전 스캐너는
`metadata_path / "gamelists" / system / "gamelist.xml"` 같은 ES-DE 규칙을 직접
알고 있었다. 이제 System마다 Storage가 다를 수 있으므로(§8) 스캐너가 그 규칙을
알면 안 된다.

**2. 모르는 필드를 버리지 않는다.** 예전 importer는 아는 태그 9개만 뽑아 dict로
만들고 나머지(`favorite`, `playcount`, `lastplayed`, `sortname`, `altemulator`,
`controller` 등)를 전부 버렸다. gamelist.xml을 다시 쓰는 순간 그 값들이 사라진다.
여기서는 `<game>`의 미지의 자식 태그와 속성을 `frontend_raw`에 원본 그대로 담고,
쓸 때 되살린다(스펙 §50-51).

파일 수준의 보존도 마찬가지다. `write_index()`는 기존 트리를 읽어서 `<game>`만
갱신하므로 `<folder>`나 `<provider>` 같이 우리가 모르는 최상위 요소가 그대로 남는다.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from adapters.base import Detection, FrontendAdapter, GameEntry, Layout, MediaFile, register
from app.model.constants import ESDE_IGNORED_SYSTEMS
from utils import normalize_esde_date, normalize_esde_rating

#: `<game>`에서 공통 모델로 옮기는 태그. 이 목록에 없는 자식은 전부 frontend_raw로 간다.
KNOWN_TAGS = ("path", "name", "desc", "genre", "developer", "publisher",
              "releasedate", "region", "players", "rating")

MEDIA_FOLDERS = {
    "3dboxes": "3dboxes",
    "covers": "covers",
    "marquees": "marquees",
    "miximages": "miximages",
    "screenshots": "screenshots",
    "videos": "videos",
    "wheel": "wheel",
}

#: ES-DE가 자기 용도로 쓰는 최상위 폴더. Collection root와 ROM root가 같은 폴더인
#: 설치(흔하다)에서 이걸 걸러내지 않으면 `gamelists`나 `downloaded_media`가 게임
#: 시스템으로 잡혀 유령 항목이 생긴다.
RESERVED_DIRS = {"gamelists", "downloaded_media", "themes", "custom_systems",
                 "collections", "settings", "scripts", "logs", "tools", "emulators"}

MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".avi"}
NON_ROM_EXTENSIONS = {".xml", ".txt", ".jpg", ".jpeg", ".png", ".webp", ".db", ".ini",
                      ".cfg", ".srm", ".sav", ".state", ".bak", ".tmp"}


class EsDeAdapter(FrontendAdapter):
    id = "es-de"
    display_name = "ES-DE"
    media_types = tuple(MEDIA_FOLDERS)

    # ------------------------------------------------------------------
    # 구조 파악
    # ------------------------------------------------------------------
    def detect(self, provider, root_path) -> Detection:
        root = Path(root_path)
        gamelists, media = root / "gamelists", root / "downloaded_media"
        has_gamelists, has_media = provider.exists(gamelists), provider.exists(media)
        if not has_gamelists and not has_media:
            return Detection(0.0, message="gamelists/downloaded_media 폴더를 찾을 수 없습니다.")
        systems = set()
        for base in (gamelists, media):
            systems.update(e.name for e in provider.scandir(base)
                           if e.is_dir and e.name.lower() not in ESDE_IGNORED_SYSTEMS)
        confidence = 1.0 if (has_gamelists and has_media) else 0.6
        return Detection(confidence, tuple(sorted(systems)),
                         f"{len(systems)}개 시스템을 찾았습니다.")

    def list_systems(self, provider, collection) -> list[str]:
        systems = set()
        root = Path(collection.root_path)
        for child in ("gamelists", "downloaded_media"):
            systems.update(self._system_dirs(provider, root / child))
        # ROM 폴더는 Storage마다 다른 위치에 있을 수 있다.
        for storage in collection.storages:
            systems.update(self._system_dirs(provider, storage.root_path))
        return sorted(systems)

    @staticmethod
    def _system_dirs(provider, path):
        return [e.name for e in provider.scandir(path)
                if e.is_dir and e.name.lower() not in ESDE_IGNORED_SYSTEMS
                and e.name.lower() not in RESERVED_DIRS]

    def layout(self, collection, system) -> Layout:
        """ES-DE는 gamelists/downloaded_media를 앱 데이터 폴더 한 곳에 두고, ROM만
        시스템별로 다른 위치에 둘 수 있다(Android의 외장 SD가 정확히 이 경우다).
        그래서 metadata/media는 Collection root 기준, ROM은 그 System이 속한
        Storage 기준으로 계산한다.

        System 항목에 명시적 경로가 있으면 언제나 그쪽이 우선한다.
        """
        entry = next((s for s in collection.systems if s.system == system), None)
        storage = collection.storage(entry.storage_id) if entry else None
        rom_root = Path(storage.root_path) if storage else Path(collection.root_path)
        root = Path(collection.root_path)
        return Layout(
            system=system,
            rom_dir=str(Path(entry.rom_path) if entry and entry.rom_path else rom_root / system),
            metadata_file=str(Path(entry.metadata_path) if entry and entry.metadata_path
                              else root / "gamelists" / system / "gamelist.xml"),
            media_dir=str(Path(entry.media_path) if entry and entry.media_path
                          else root / "downloaded_media" / system),
        )

    # ------------------------------------------------------------------
    # 읽기 (bulk)
    # ------------------------------------------------------------------
    def list_roms(self, provider, layout) -> list[str]:
        if not layout.rom_dir:
            return []
        return sorted(e.name for e in provider.scandir(layout.rom_dir)
                      if not e.is_dir and not e.name.startswith(".")
                      and Path(e.name).suffix.lower() not in NON_ROM_EXTENSIONS)

    def read_index(self, provider, layout) -> dict[str, GameEntry]:
        """gamelist.xml 전체를 한 번 파싱해 ROM 파일명 -> GameEntry로 만든다."""
        root = self._parse(provider, layout.metadata_file)
        if root is None:
            return {}
        entries = {}
        for game in root.findall("game"):
            filename = Path((game.findtext("path") or "").strip()).name
            if not filename:
                continue
            entries[filename] = self.to_common(game)
        return entries

    def to_common(self, game) -> GameEntry:
        """`<game>` 요소를 (공통 필드, 원본 보존분)으로 나눈다.

        아는 태그만 뽑고 끝내면 안 된다 - 모르는 태그와 속성을 전부 frontend_raw에
        담아야 나중에 다시 쓸 때 되살릴 수 있다.
        """
        def text(tag):
            return (game.findtext(tag) or "").strip()

        fields = {
            "name": text("name"),
            "desc": text("desc"),
            "genre": text("genre"),
            "developer": text("developer"),
            "publisher": text("publisher"),
            "releasedate": normalize_esde_date(text("releasedate")),
            "region": text("region"),
            "players": text("players"),
            "rating": normalize_esde_rating(text("rating")),
        }
        extra = [{"tag": child.tag, "text": child.text or "", "attrib": dict(child.attrib)}
                 for child in game if child.tag not in KNOWN_TAGS]
        raw = {}
        if extra:
            raw["extra"] = extra
        if game.attrib:
            raw["attrib"] = dict(game.attrib)
        return GameEntry(filename=Path(text("path")).name, fields=fields, frontend_raw=raw)

    def media_dirs(self, layout, media_types=None) -> list[str]:
        if not layout.media_dir:
            return []
        wanted = set(media_types) if media_types is not None else None
        return [str(Path(layout.media_dir) / folder)
                for media_type, folder in MEDIA_FOLDERS.items()
                if wanted is None or media_type in wanted]

    def read_media_index(self, provider, layout, media_types=None) -> dict[str, list[MediaFile]]:
        """System 전체의 media를 ROM stem 기준으로 인덱싱한다.

        media_types를 주면 그 타입의 폴더만 실제로 연다. 비디오는 파일이 크고 개수도
        많아서, 커버만 먼저 훑는 1단계에서 이걸 건너뛰는 것이 체감 속도에 크게 기여한다.
        """
        if not layout.media_dir:
            return {}
        wanted = set(media_types) if media_types is not None else None
        index: dict[str, list[MediaFile]] = {}
        for media_type, folder in MEDIA_FOLDERS.items():
            if wanted is not None and media_type not in wanted:
                continue
            for entry in provider.scandir(Path(layout.media_dir) / folder):
                if entry.is_dir or Path(entry.name).suffix.lower() not in MEDIA_EXTENSIONS:
                    continue
                index.setdefault(Path(entry.name).stem, []).append(
                    MediaFile(media_type=media_type, path=entry.path,
                              size=entry.size, mtime_ns=entry.mtime_ns))
        return index

    # ------------------------------------------------------------------
    # 쓰기 (bulk)
    # ------------------------------------------------------------------
    def write_index(self, layout, entries) -> None:
        """gamelist.xml을 한 번만 읽고 한 번만 쓴다.

        기존 트리를 편집하는 방식이라 `<folder>`처럼 우리가 해석하지 않는 최상위
        요소가 그대로 살아남는다. entries에 없는 기존 `<game>`도 지우지 않는다 -
        Export가 기존 데이터를 조용히 삭제하면 안 된다(§70).
        """
        path = Path(layout.metadata_file)
        root = self._parse_file(path)
        if root is None:
            root = ET.Element("gameList")

        by_filename = {}
        for game in root.findall("game"):
            name = Path((game.findtext("path") or "").strip()).name
            if name:
                by_filename[name] = game

        for entry in entries:
            game = by_filename.get(entry.filename)
            if game is None:
                game = ET.SubElement(root, "game")
                ET.SubElement(game, "path").text = f"./{entry.filename}"
                by_filename[entry.filename] = game
            self.from_common(game, entry)

        path.parent.mkdir(parents=True, exist_ok=True)
        tree = ET.ElementTree(root)
        # ET.write()는 기본적으로 들여쓰기 없이 한 줄로 쓴다. ES-DE가 직접 만드는
        # gamelist.xml처럼 태그마다 줄을 나눠야 사람이 열어봤을 때 읽을 수 있다.
        ET.indent(tree, space="  ")
        tree.write(path, encoding="utf-8", xml_declaration=True)

    def from_common(self, game, entry) -> None:
        """공통 필드와 보존해둔 원본을 `<game>` 요소에 다시 적용한다."""
        fields = entry.fields or {}
        self._set(game, "name", fields.get("name"))
        self._set(game, "desc", fields.get("desc"))
        self._set(game, "genre", fields.get("genre"))
        self._set(game, "developer", fields.get("developer"))
        self._set(game, "publisher", fields.get("publisher"))
        self._set(game, "region", fields.get("region"))
        self._set(game, "players", fields.get("players"))

        release = (fields.get("releasedate") or "").strip()
        self._set(game, "releasedate", release.replace("-", "") + "T000000" if release else "")

        rating = (str(fields.get("rating") or "")).strip()
        if rating:
            try:
                self._set(game, "rating", f"{float(rating) / 5:.2f}")
            except (TypeError, ValueError):
                pass

        raw = entry.frontend_raw or {}
        for key, value in (raw.get("attrib") or {}).items():
            game.set(key, value)
        for item in raw.get("extra") or []:
            tag = item.get("tag")
            if not tag or tag in KNOWN_TAGS:
                continue
            child = game.find(tag)
            if child is None:
                child = ET.SubElement(game, tag)
            child.text = item.get("text") or ""
            for key, value in (item.get("attrib") or {}).items():
                child.set(key, value)

    def remove_entries(self, layout, filenames) -> None:
        """gamelist.xml에서 해당 <game> 항목만 지운다.

        기존 트리를 편집하므로 <folder>처럼 우리가 해석하지 않는 최상위 요소와 다른
        게임들은 그대로 남는다.
        """
        path = Path(layout.metadata_file)
        root = self._parse_file(path)
        if root is None:
            return
        wanted = set(filenames)
        removed = False
        for game in list(root.findall("game")):
            name = Path((game.findtext("path") or "").strip()).name
            if name in wanted:
                root.remove(game)
                removed = True
        if not removed:
            return
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(path, encoding="utf-8", xml_declaration=True)

    def media_pairs(self, layout, filename, media) -> list[tuple[str, str]]:
        stem = Path(filename).stem
        pairs = []
        for item in media:
            folder = MEDIA_FOLDERS.get(item.media_type)
            if not folder:
                continue
            suffix = Path(item.path).suffix
            pairs.append((item.path, str(Path(layout.media_dir) / folder / f"{stem}{suffix}")))
        return pairs

    # ------------------------------------------------------------------
    @staticmethod
    def _set(game, tag, value):
        element = game.find(tag)
        if element is None:
            element = ET.SubElement(game, tag)
        element.text = "" if value in (None, "") else str(value)

    def _parse(self, provider, metadata_file):
        if not metadata_file or not provider.exists(metadata_file):
            return None
        return self._parse_file(Path(metadata_file))

    @staticmethod
    def _parse_file(path):
        """손상된 XML은 예외를 던지지 않고 None으로 처리한다.

        gamelist.xml 하나가 깨졌다고 Collection 전체 스캔이 실패하면 안 된다 -
        그 System만 메타데이터 없는 상태로 보이는 편이 낫다.
        """
        try:
            return ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return None


register(EsDeAdapter())
