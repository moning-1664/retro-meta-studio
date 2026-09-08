"""
adapters/emulationstation.py
=============================
원조 EmulationStation(RetroPie / Batocera / Recalbox 등) Adapter.

구조:

```
<root>/gamelists/<system>/gamelist.xml
<root>/<system>/<rom files>
<root>/downloaded_images/<system>/<stem>-image.png   (배포판마다 다름)
```

## ES-DE와 무엇이 다른가

XML 스키마는 거의 같지만 **media를 찾는 방법이 반대다.**

- ES-DE: 폴더 규칙(`downloaded_media/<system>/covers/<stem>.png`)으로 찾는다.
  gamelist에는 media 경로가 없다.
- 원조 ES: **gamelist.xml 안의 `<image>` / `<video>` / `<marquee>` / `<thumbnail>`이
  경로를 직접 가리킨다.** 배포판마다 폴더 구조가 제각각이라(RetroPie는
  `~/.emulationstation/downloaded_images`, Batocera는 `media/`) 폴더 규칙을 가정할 수
  없고, 가정하면 사용자의 media를 통째로 놓친다.

그래서 이 Adapter는 media 인덱스를 **gamelist가 가리키는 경로에서** 만든다. 경로는
gamelist.xml 위치 기준의 상대 경로일 수도 절대 경로일 수도 있어 둘 다 받아들인다.

쓸 때도 같은 태그에 경로를 다시 적어준다 - 그러지 않으면 파일은 복사됐는데 ES가
그것을 못 찾는 상태가 된다.

## 계약 2

`<favorite>`, `<playcount>`, `<lastplayed>`, `<hidden>`, `<kidgame>` 등 우리가 공통
모델로 옮기지 않는 태그는 전부 `frontend_raw`에 보존한다. media 경로 태그도 마찬가지로
보존하되, media를 새로 쓸 때는 새 경로로 갱신한다.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from adapters.base import (Detection, FrontendAdapter, GameEntry, Layout, MediaFile, read_xml, register, write_xml)
from app.model.constants import ESDE_IGNORED_SYSTEMS
from utils import normalize_esde_date, normalize_esde_rating

KNOWN_TAGS = ("path", "name", "desc", "genre", "developer", "publisher",
              "releasedate", "region", "players", "rating")

#: gamelist 안에서 media를 가리키는 태그 -> 공통 media type.
MEDIA_TAGS = {
    "image": "screenshots",
    "thumbnail": "covers",
    "cover": "covers",
    "marquee": "marquees",
    "video": "videos",
    "fanart": "miximages",
}
#: 쓸 때 쓰는 역방향. 한 media type이 여러 태그에 대응할 수 있으므로 대표 태그를 고른다.
TAG_FOR_TYPE = {"screenshots": "image", "covers": "thumbnail", "marquees": "marquee",
                "videos": "video", "miximages": "fanart"}

#: 새로 복사해 넣을 때 쓰는 폴더 이름. 원조 ES에 표준이 없어서, 우리가 쓸 때는
#: 가장 흔한 형태 하나를 고르고 gamelist에 경로를 명시한다.
MEDIA_SUBDIR = "media"

MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".avi", ".webm"}
NON_ROM_EXTENSIONS = {".xml", ".txt", ".jpg", ".jpeg", ".png", ".webp", ".db", ".ini",
                      ".cfg", ".srm", ".sav", ".state", ".bak", ".tmp"}
RESERVED_DIRS = {"gamelists", "downloaded_images", "downloaded_videos", "downloaded_media",
                 "media", "themes", "collections", "scripts", "tools"}


class EmulationStationAdapter(FrontendAdapter):
    id = "emulationstation"
    display_name = "EmulationStation"
    media_types = tuple(TAG_FOR_TYPE)

    # ------------------------------------------------------------------
    # 구조 파악
    # ------------------------------------------------------------------
    def detect(self, provider, root_path) -> Detection:
        gamelists = Path(root_path) / "gamelists"
        if not provider.exists(gamelists):
            return Detection(0.0, message="gamelists 폴더를 찾을 수 없습니다.")
        systems = tuple(sorted(
            e.name for e in provider.scandir(gamelists)
            if e.is_dir and e.name.lower() not in ESDE_IGNORED_SYSTEMS))
        if not systems:
            return Detection(0.3, message="gamelists 아래에 시스템 폴더가 없습니다.")
        # ES-DE도 gamelists를 쓰므로 downloaded_media가 함께 있으면 그쪽일 가능성이
        # 높다. 확신을 낮춰 사용자가 고르게 한다.
        if provider.exists(Path(root_path) / "downloaded_media"):
            return Detection(0.5, systems, "ES-DE일 수도 있습니다 - Frontend를 확인하세요.")
        return Detection(0.9, systems, f"{len(systems)}개 시스템을 찾았습니다.")

    def list_systems(self, provider, collection) -> list[str]:
        systems = set()
        root = Path(collection.root_path)
        systems.update(e.name for e in provider.scandir(root / "gamelists")
                       if e.is_dir and e.name.lower() not in ESDE_IGNORED_SYSTEMS)
        for storage in collection.storages:
            systems.update(e.name for e in provider.scandir(storage.root_path)
                           if e.is_dir and e.name.lower() not in ESDE_IGNORED_SYSTEMS
                           and e.name.lower() not in RESERVED_DIRS)
        return sorted(systems)

    def layout(self, collection, system) -> Layout:
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
                          else root / MEDIA_SUBDIR / system),
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
        for game in root.findall("game"):
            filename = Path((game.findtext("path") or "").strip().replace("\\", "/")).name
            if not filename:
                continue
            entries[filename] = self.to_common(game)
        return entries

    def to_common(self, game) -> GameEntry:
        def text(tag):
            return (game.findtext(tag) or "").strip()

        fields = {
            "name": text("name"), "desc": text("desc"), "genre": text("genre"),
            "developer": text("developer"), "publisher": text("publisher"),
            "releasedate": normalize_esde_date(text("releasedate")),
            "region": text("region"), "players": text("players"),
            "rating": normalize_esde_rating(text("rating")),
        }
        extra = [{"tag": child.tag, "text": child.text or "", "attrib": dict(child.attrib)}
                 for child in game if child.tag not in KNOWN_TAGS]
        raw = {}
        if extra:
            raw["extra"] = extra
        if game.attrib:
            raw["attrib"] = dict(game.attrib)
        return GameEntry(filename=Path(text("path").replace("\\", "/")).name,
                         fields=fields, frontend_raw=self.tag_raw(raw))

    def media_dirs(self, layout, media_types=None) -> list[str]:
        """gamelist가 경로를 들고 있으므로 media 폴더는 우리가 쓰는 곳 하나뿐이다.

        스캐너는 변경 감지를 위해 이 목록을 쓰는데, 원조 ES는 media 위치가 배포판마다
        달라 "훑어야 할 폴더"를 확정할 수 없다. gamelist.xml 자체가 바뀌면 어차피
        다시 읽으므로, 여기서는 우리가 쓰는 폴더만 알린다.
        """
        return [layout.media_dir] if layout.media_dir else []

    def read_media_index(self, provider, layout, media_types=None) -> dict[str, list[MediaFile]]:
        """**gamelist가 가리키는 경로**에서 media를 모은다.

        폴더 규칙으로 찾지 않는다 - 배포판마다 위치가 달라서 가정하는 순간 사용자의
        media를 통째로 놓친다.
        """
        root = self._parse(provider, layout.metadata_file)
        if root is None:
            return {}
        base = Path(layout.metadata_file).parent
        wanted = set(media_types) if media_types is not None else None
        index: dict[str, list[MediaFile]] = {}
        for game in root.findall("game"):
            filename = Path((game.findtext("path") or "").strip().replace("\\", "/")).name
            if not filename:
                continue
            stem = Path(filename).stem
            for tag, media_type in MEDIA_TAGS.items():
                if wanted is not None and media_type not in wanted:
                    continue
                value = (game.findtext(tag) or "").strip().replace("\\", "/")
                if not value:
                    continue
                path = Path(value) if Path(value).is_absolute() else (base / value)
                info = provider.stat(path)
                if info is None:
                    continue   # gamelist가 가리키지만 실제로는 없는 파일
                index.setdefault(stem, []).append(
                    MediaFile(media_type=media_type, path=str(path),
                              size=info.size, mtime_ns=info.mtime_ns))
        return index

    # ------------------------------------------------------------------
    # 쓰기 (bulk)
    # ------------------------------------------------------------------
    def write_index(self, layout, entries) -> None:
        path = Path(layout.metadata_file)
        root = self._parse_file(path)
        if root is None:
            root = ET.Element("gameList")

        by_filename = {}
        for game in root.findall("game"):
            name = Path((game.findtext("path") or "").strip().replace("\\", "/")).name
            if name:
                by_filename[name] = game

        for entry in entries:
            game = by_filename.get(entry.filename)
            if game is None:
                game = ET.SubElement(root, "game")
                ET.SubElement(game, "path").text = f"./{entry.filename}"
                by_filename[entry.filename] = game
            self.from_common(game, entry)

        write_xml(path, root)

    def from_common(self, game, entry) -> None:
        fields = entry.fields or {}
        for tag in ("name", "desc", "genre", "developer", "publisher", "region", "players"):
            self._set(game, tag, fields.get(tag))

        release = (fields.get("releasedate") or "").strip()
        self._set(game, "releasedate", release.replace("-", "") + "T000000" if release else "")

        rating = str(fields.get("rating") or "").strip()
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

    def strip_location_raw(self, frontend_raw) -> dict:
        """media 경로 태그를 걷어낸다.

        원조 ES는 gamelist가 media 경로를 직접 들고 있어서, 그 값이 `frontend_raw`에
        보존된다(계약 2). 그런데 그건 **그 Collection 안에서만 참인 경로**다. 다른
        Collection으로 게임을 복사하면서 그대로 적으면 target의 gamelist가 source의
        폴더(또는 아무 데도 없는 곳)를 가리키게 된다.

        새 위치의 경로는 `build_media_links()`가 계산하고 `write_media_links()`가 적는다.
        """
        raw = dict(frontend_raw or {})
        extra = raw.get("extra")
        if extra:
            raw["extra"] = [item for item in extra if item.get("tag") not in MEDIA_TAGS]
        return raw

    def build_media_links(self, layout, filename, media) -> list[tuple[str, str]]:
        """이 게임의 media가 놓일 자리를 (media_type, dest)로 계산한다. 쓰지는 않는다.

        타입당 하나만 쓴다 - gamelist의 태그 하나에 경로 하나만 들어가므로, 두 번째를
        적으면 첫 번째를 덮어쓴다.
        """
        stem = Path(filename).stem
        links, used = [], set()
        for item in media:
            tag = TAG_FOR_TYPE.get(item.media_type)
            if not tag or item.media_type in used:
                continue
            used.add(item.media_type)
            links.append((item.media_type,
                          str(Path(layout.media_dir) / f"{stem}-{tag}{Path(item.path).suffix}")))
        return links

    def write_media_links(self, layout, links_by_filename) -> None:
        """복사한 media의 경로를 gamelist에 적어준다. **System 단위로 한 번만 쓴다.**

        원조 ES는 gamelist가 가리키는 경로만 본다. 파일만 복사하고 이 단계를 빠뜨리면
        복사는 됐는데 화면에는 안 나오는 상태가 된다 - ES-DE에는 없는 단계다.

        ROM 하나씩 쓰지 않는 이유는 계약 1 그대로다. 1,000개 게임에 media를 넣으면
        gamelist.xml을 1,000번 다시 열고 쓰게 된다.
        """
        if not links_by_filename:
            return
        path = Path(layout.metadata_file)
        root = self._parse_file(path)
        if root is None:
            return

        by_filename = {}
        for game in root.findall("game"):
            name = Path((game.findtext("path") or "").strip().replace("\\", "/")).name
            if name:
                by_filename[name] = game

        base, changed = path.parent, False
        for filename, links in links_by_filename.items():
            game = by_filename.get(filename)
            if game is None:
                continue
            for media_type, dest in links:
                tag = TAG_FOR_TYPE.get(media_type)
                if not tag:
                    continue
                try:
                    value = "./" + Path(dest).relative_to(base).as_posix()
                except ValueError:
                    value = str(dest)   # gamelist 밖에 있으면 절대 경로로 적는다
                self._set(game, tag, value)
                changed = True
        if not changed:
            return
        write_xml(path, root)

    def remove_entries(self, layout, filenames) -> None:
        path = Path(layout.metadata_file)
        root = self._parse_file(path)
        if root is None:
            return
        wanted, removed = set(filenames), False
        for game in list(root.findall("game")):
            name = Path((game.findtext("path") or "").strip().replace("\\", "/")).name
            if name in wanted:
                root.remove(game)
                removed = True
        if not removed:
            return
        write_xml(path, root)

    def media_pairs(self, layout, filename, media) -> list[tuple[str, str]]:
        """복사할 (src, dest). **`build_media_links()`가 계산한 dest를 그대로 쓴다.**

        둘이 따로 계산하면 언젠가 갈라지고, 갈라지는 순간 "파일은 복사됐는데 gamelist는
        다른 곳을 가리킨다"가 된다 - 원조 ES에서 가장 잦은 사고다.
        """
        destinations = dict(self.build_media_links(layout, filename, media))
        pairs, used = [], set()
        for item in media:
            dest = destinations.get(item.media_type)
            if dest is None or item.media_type in used:
                continue
            used.add(item.media_type)
            pairs.append((item.path, dest))
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


register(EmulationStationAdapter())
