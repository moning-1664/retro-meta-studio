"""
adapters/launchbox.py
======================
LaunchBox Frontend Adapter.

구조:

```
<root>/Data/Platforms/<system>.xml     플랫폼 하나당 XML 하나, 그 안에 모든 <Game>
<root>/Games/<system>/<rom files>      ROM
<root>/Images/<system>/Box - Front/<이름>.jpg
```

## ES-DE/Pegasus와 결정적으로 다른 점 — media 파일명이 **제목** 기준이다

ES-DE와 Pegasus는 media 파일명이 ROM 파일명(stem)을 따르지만, LaunchBox는 **게임
제목**을 따른다. `Chrono Trigger (USA).sfc`의 커버가 `Chrono Trigger.jpg`로 저장되는
식이다. 그래서 media 인덱스를 ROM stem으로만 만들면 커버를 하나도 못 찾는다.

여기서는 gamelist에 해당하는 `<Game>`의 `<Title>`로부터 **stem -> 제목** 대응표를
먼저 만들고, media를 훑을 때 그 표로 되돌려 ROM stem에 붙인다. 제목을 모르는 파일은
파일명 자체를 stem으로 취급한다(ROM 이름으로 저장해 둔 사람도 있다).

LaunchBox는 제목에 쓸 수 없는 문자를 `_`로 바꿔 저장하므로 그 치환도 함께 본다.

## 계약 2 — 모르는 태그를 버리지 않는다

`<Game>` 아래에는 우리가 공통 모델로 옮기지 않는 태그가 많다(`DateAdded`,
`PlayCount`, `Favorite`, `Emulator`, `ApplicationPath` 등). 전부 `frontend_raw`에
담아 두고 다시 쓸 때 되살린다 - 그러지 않으면 LaunchBox로 한 번 Export하는 순간
사용자의 실행 설정과 플레이 기록이 사라진다(§50-51).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from adapters.base import (NON_ROM_EXTENSIONS, Detection, FrontendAdapter, GameEntry, Layout, MediaFile, read_xml, register, write_xml)

#: 공통 모델 <-> `<Game>` 태그.
FIELD_TAGS = {
    "name": "Title",
    "desc": "Notes",
    "genre": "Genre",
    "developer": "Developer",
    "publisher": "Publisher",
    "releasedate": "ReleaseDate",
    "region": "Region",
    "players": "MaxPlayers",
    "rating": "CommunityStarRating",
}
#: 항목의 정체성을 이루는 태그. 공통 필드도 frontend_raw도 아니고 우리가 직접 쓴다.
STRUCTURAL_TAGS = {"ApplicationPath", "ID"}

#: media type -> `Images/<system>/` 아래 폴더 이름.
IMAGE_FOLDERS = {
    "covers": "Box - Front",
    "screenshots": "Screenshot - Gameplay",
    "marquees": "Arcade - Marquee",
    "miximages": "Fanart - Background",
    "wheel": "Clear Logo",
}
VIDEO_FOLDER = "Videos"

MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".avi", ".webm"}

#: LaunchBox가 파일명으로 쓸 수 없어 `_`로 바꾸는 문자들.
_ILLEGAL = ':*?"<>|/\\'


def title_to_filename(title: str) -> str:
    """LaunchBox가 제목을 파일명으로 바꾸는 규칙."""
    out = str(title or "")
    for ch in _ILLEGAL:
        out = out.replace(ch, "_")
    return out.strip()


class LaunchBoxAdapter(FrontendAdapter):
    #: 이 Frontend가 즐겨찾기를 적는 태그.
    FAVORITE_TAG = "Favorite"

    id = "launchbox"
    display_name = "LaunchBox"
    media_types = tuple(IMAGE_FOLDERS) + ("videos",)

    # ------------------------------------------------------------------
    # 구조 파악
    # ------------------------------------------------------------------
    def _platforms_dir(self, root) -> Path:
        return Path(root) / "Data" / "Platforms"

    def detect(self, provider, root_path) -> Detection:
        platforms = self._platforms_dir(root_path)
        if not provider.exists(platforms):
            return Detection(0.0, message="Data/Platforms 폴더를 찾을 수 없습니다.")
        systems = tuple(sorted(
            Path(e.name).stem for e in provider.scandir(platforms)
            if not e.is_dir and Path(e.name).suffix.lower() == ".xml"))
        if not systems:
            return Detection(0.3, message="Data/Platforms에 플랫폼 XML이 없습니다.")
        return Detection(1.0, systems, f"{len(systems)}개 플랫폼을 찾았습니다.")

    def list_systems(self, provider, collection) -> list[str]:
        platforms = self._platforms_dir(collection.root_path)
        return sorted(Path(e.name).stem for e in provider.scandir(platforms)
                      if not e.is_dir and Path(e.name).suffix.lower() == ".xml")

    def layout(self, collection, system) -> Layout:
        """ROM만 Storage를 따라가고, 플랫폼 XML과 Images는 Collection root에 남는다.

        LaunchBox는 라이브러리 폴더 하나를 중심으로 도는 구조라, ES-DE처럼 ROM만
        외부 저장소로 빼는 형태가 자연스럽다.
        """
        entry = next((s for s in collection.systems if s.system == system), None)
        storage = collection.storage(entry.storage_id) if entry else None
        rom_root = Path(storage.root_path) if storage else Path(collection.root_path)
        root = Path(collection.root_path)
        default_rom = rom_root / "Games" / system if rom_root == root else rom_root / system
        return Layout(
            system=system,
            rom_dir=str(Path(entry.rom_path) if entry and entry.rom_path else default_rom),
            metadata_file=str(Path(entry.metadata_path) if entry and entry.metadata_path
                              else self._platforms_dir(root) / f"{system}.xml"),
            media_dir=str(Path(entry.media_path) if entry and entry.media_path
                          else root / "Images" / system),
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
        root = self._parse(provider, layout.metadata_file)
        if root is None:
            return {}
        entries = {}
        for game in root.findall("Game"):
            filename = Path((game.findtext("ApplicationPath") or "").strip().replace("\\", "/")).name
            if not filename:
                continue
            entries[filename] = self.to_common(game, filename)
        return entries

    def raw_metadata_filenames(self, provider, layout) -> list[str]:
        root = self._parse(provider, layout.metadata_file)
        if root is None:
            return []
        return [Path((game.findtext("ApplicationPath") or "").strip().replace("\\", "/")).name
                for game in root.findall("Game") if (game.findtext("ApplicationPath") or "").strip()]

    def to_common(self, game, filename) -> GameEntry:
        def text(tag):
            return (game.findtext(tag) or "").strip()

        fields = {common: text(tag) for common, tag in FIELD_TAGS.items()}
        # LaunchBox의 ReleaseDate는 ISO 시각(2001-07-19T00:00:00)이다.
        fields["releasedate"] = fields["releasedate"][:10]

        known = set(FIELD_TAGS.values()) | STRUCTURAL_TAGS
        extra = [{"tag": child.tag, "text": child.text or "", "attrib": dict(child.attrib)}
                 for child in game if child.tag not in known]
        raw = {}
        if extra:
            raw["extra"] = extra
        if game.attrib:
            raw["attrib"] = dict(game.attrib)
        # 원본 경로를 그대로 보존한다 - LaunchBox는 상대/절대 경로를 섞어 쓰고,
        # 우리가 파일명만 알고 다시 쓰면 사용자의 경로 설정이 깨진다.
        app_path = (game.findtext("ApplicationPath") or "").strip()
        if app_path:
            raw["applicationPath"] = app_path
        return GameEntry(filename=filename, fields=fields,
                         frontend_raw=self.tag_raw(raw))

    def _title_index(self, provider, layout) -> dict[str, str]:
        """media 파일명(제목 기준) -> ROM stem 대응표."""
        mapping = {}
        for filename, entry in self.read_index(provider, layout).items():
            title = (entry.fields.get("name") or "").strip()
            if title:
                mapping[title_to_filename(title).lower()] = Path(filename).stem
        return mapping

    def media_dirs(self, layout, media_types=None) -> list[str]:
        if not layout.media_dir:
            return []
        wanted = set(media_types) if media_types is not None else None
        dirs = [str(Path(layout.media_dir) / folder)
                for media_type, folder in IMAGE_FOLDERS.items()
                if wanted is None or media_type in wanted]
        if wanted is None or "videos" in wanted:
            dirs.append(str(Path(layout.media_dir) / VIDEO_FOLDER))
        return dirs

    def read_media_index(self, provider, layout, media_types=None) -> dict[str, list[MediaFile]]:
        """제목 기준 파일명을 ROM stem으로 되돌려 인덱싱한다.

        제목 표에 없는 파일은 파일명 자체를 stem으로 본다 - ROM 이름으로 저장해 둔
        경우가 있고, 그것까지 버리면 멀쩡한 media를 놓친다.
        """
        if not layout.media_dir:
            return {}
        wanted = set(media_types) if media_types is not None else None
        by_title = self._title_index(provider, layout)

        folders = dict(IMAGE_FOLDERS)
        folders["videos"] = VIDEO_FOLDER
        index: dict[str, list[MediaFile]] = {}
        for media_type, folder in folders.items():
            if wanted is not None and media_type not in wanted:
                continue
            for entry in provider.scandir(Path(layout.media_dir) / folder):
                if entry.is_dir or Path(entry.name).suffix.lower() not in MEDIA_EXTENSIONS:
                    continue
                stem = Path(entry.name).stem
                key = by_title.get(stem.lower(), stem)
                index.setdefault(key, []).append(
                    MediaFile(media_type=media_type, path=entry.path,
                              size=entry.size, mtime_ns=entry.mtime_ns))
        return index

    # ------------------------------------------------------------------
    # 쓰기 (bulk)
    # ------------------------------------------------------------------
    def write_index(self, layout, entries) -> None:
        path = Path(layout.metadata_file)
        root = self._parse_file(path)
        if root is None:
            root = ET.Element("LaunchBox")

        by_filename = {}
        for game in root.findall("Game"):
            name = Path((game.findtext("ApplicationPath") or "").strip().replace("\\", "/")).name
            if name:
                by_filename[name] = game

        for entry in entries:
            game = by_filename.get(entry.filename)
            if game is None:
                game = ET.SubElement(root, "Game")
                by_filename[entry.filename] = game
            self.from_common(game, entry, layout)

        write_xml(path, root)

    def from_common(self, game, entry, layout=None) -> None:
        fields = entry.fields or {}
        raw = entry.frontend_raw or {}

        app_path = raw.get("applicationPath")
        if not app_path:
            base = Path(layout.rom_dir) if layout and layout.rom_dir else Path(".")
            app_path = str(base / entry.filename)
        self._set(game, "ApplicationPath", app_path)

        for common, tag in FIELD_TAGS.items():
            value = fields.get(common)
            if common == "releasedate" and value:
                value = f"{value}T00:00:00"
            self._set(game, tag, value)

        for key, value in (raw.get("attrib") or {}).items():
            game.set(key, value)
        for item in raw.get("extra") or []:
            tag = item.get("tag")
            if not tag or tag in FIELD_TAGS.values() or tag in STRUCTURAL_TAGS:
                continue
            child = game.find(tag)
            if child is None:
                child = ET.SubElement(game, tag)
            child.text = item.get("text") or ""
            for key, value in (item.get("attrib") or {}).items():
                child.set(key, value)

    def strip_location_raw(self, frontend_raw) -> dict:
        """`ApplicationPath`를 걷어낸다.

        LaunchBox는 실행할 파일의 경로를 `<ApplicationPath>`에 직접 들고 있어서 그 값이
        `frontend_raw`에 보존된다(계약 2). 그런데 그건 **그 라이브러리 안에서만 참인
        경로**다. 다른 Collection으로 게임을 복사하면서 그대로 적으면 target의
        LaunchBox가 source의 드라이브를 가리키게 되고, 사용자가 게임을 눌렀을 때
        실행이 실패한다 - 원조 ES의 media 경로 태그와 정확히 같은 성격이다.

        새 위치의 경로는 `from_common()`이 `layout.rom_dir`로 다시 계산한다.
        """
        raw = dict(frontend_raw or {})
        raw.pop("applicationPath", None)
        return raw

    def remove_entries(self, layout, filenames) -> None:
        path = Path(layout.metadata_file)
        root = self._parse_file(path)
        if root is None:
            return
        wanted, removed = set(filenames), False
        for game in list(root.findall("Game")):
            name = Path((game.findtext("ApplicationPath") or "").strip().replace("\\", "/")).name
            if name in wanted:
                root.remove(game)
                removed = True
        if not removed:
            return
        write_xml(path, root)

    def media_pairs(self, layout, filename, media, title=None) -> list[tuple[str, str]]:
        """media를 `Images/<system>/<폴더>/<제목>.<확장자>`로 매핑한다.

        **읽기 규칙과 같은 이름을 써야 한다.** `read_media_index()`가 제목 -> ROM stem
        대응표로 되돌려 읽는데 쓸 때는 ROM stem으로 저장하면, 우리끼리는 fallback
        덕에 맞아떨어지고 **LaunchBox 안에서만** 커버가 안 보인다. 읽기가 관대해서
        왕복 테스트로는 잡히지 않는 종류의 어긋남이다.

        제목을 알 수 없으면 ROM stem을 쓴다 - LaunchBox도 그 이름으로 찾아준다.
        """
        stem = title_to_filename(title) if title else ""
        stem = stem or Path(filename).stem
        folders = dict(IMAGE_FOLDERS)
        folders["videos"] = VIDEO_FOLDER
        pairs, used = [], set()
        for item in media:
            folder = folders.get(item.media_type)
            if not folder or item.media_type in used:
                continue
            used.add(item.media_type)
            pairs.append((item.path,
                          str(Path(layout.media_dir) / folder / f"{stem}{Path(item.path).suffix}")))
        return pairs

    # ------------------------------------------------------------------
    @staticmethod
    def _set(game, tag, value):
        element = game.find(tag)
        if element is None:
            element = ET.SubElement(game, tag)
        element.text = "" if value in (None, "") else str(value)

    def _parse(self, provider, metadata_file):
        if not metadata_file:
            return None
        return self._parse_file(metadata_file, provider)

    @staticmethod
    def _parse_file(path, provider=None):
        """파일이 없거나 깨졌으면 None. Provider를 지나므로 MTP에서도 동작한다."""
        return read_xml(path, provider)


register(LaunchBoxAdapter())
