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

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from adapters.base import (NON_ROM_EXTENSIONS, AdapterAction, Detection, FrontendAdapter, GameEntry,
                           Layout, MediaFile, read_document, register, serialize_xml,
                           write_document, write_xml)
from app.model.constants import ESDE_IGNORED_SYSTEMS
from utils import normalize_esde_date, normalize_esde_rating

#: `<game>`에서 공통 모델로 옮기는 태그. 이 목록에 없는 자식은 전부 frontend_raw로 간다.
KNOWN_TAGS = ("path", "name", "desc", "genre", "developer", "publisher",
              "releasedate", "region", "players", "rating")

#: ES-DE가 실제로 쓰는 media 폴더 전부. 사용자의 백업에서 확인한 이름 그대로다.
#:
#: 여기 없는 폴더는 **스캔에서 통째로 빠진다** - 파일은 디스크에 있는데 앱은 없는 것으로
#: 알고, Plan을 만들면 복사 대상에서도 용량 계산에서도 빠진다. 그래서 아는 것만
#: 적어두면 안 되고 실제 폴더 이름을 따라가야 한다.
MEDIA_FOLDERS = {
    "3dboxes": "3dboxes",
    "backcovers": "backcovers",
    "covers": "covers",
    "fanart": "fanart",
    "manuals": "manuals",
    "marquees": "marquees",
    "miximages": "miximages",
    "physicalmedia": "physicalmedia",
    "screenshots": "screenshots",
    "titlescreens": "titlescreens",
    "videos": "videos",
    "wheel": "wheel",
}

#: ES-DE가 자기 용도로 쓰는 최상위 폴더. Collection root와 ROM root가 같은 폴더인
#: 설치(흔하다)에서 이걸 걸러내지 않으면 `gamelists`나 `downloaded_media`가 게임
#: 시스템으로 잡혀 유령 항목이 생긴다.
RESERVED_DIRS = {"gamelists", "downloaded_media", "themes", "custom_systems",
                 "collections", "settings", "scripts", "logs", "tools", "emulators",
                 # 실제 ES-DE 3.x 설치에서 확인한 나머지 - 이걸 빼면 `controllers`나
                 # `screensavers`가 게임 시스템으로 잡혀 빈 항목이 목록에 뜬다.
                 "temp", "controllers", "screensavers", "cache", "backups"}

#: media로 인정하는 확장자. **`.pdf`가 들어 있는 이유는 설명서(manuals) 때문이다** -
#: ES-DE의 manuals 폴더는 PDF이고, 이것이 빠져 있어서 사용자의 백업에서 설명서 660개가
#: 통째로 스캔되지 않았다. 그림이 아니라고 media가 아닌 것은 아니다.
MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".avi", ".webm", ".pdf"}


class EsDeAdapter(FrontendAdapter):
    #: 이 Frontend가 즐겨찾기를 적는 태그.
    FAVORITE_TAG = "favorite"

    id = "es-de"
    display_name = "ES-DE"
    media_types = tuple(MEDIA_FOLDERS)

    # ------------------------------------------------------------------
    # 구조 파악
    # ------------------------------------------------------------------
    def detect(self, provider, root_path) -> Detection:
        """이 경로가 ES-DE Collection인지.

        **메타데이터가 아직 없는 순수 ROM 트리도 받아들인다.** `gamelists/`도
        `downloaded_media/`도 없지만 System 폴더 안에 ROM이 있는 형태는 흔하다 -
        스크래핑을 한 번도 안 한 사람의 컬렉션이 정확히 그 모습이고, 그 사람도 앱을
        열어서 시작할 수 있어야 한다. 다만 "ES-DE라고 확신"할 근거는 없으므로
        confidence를 낮게 준다.
        """
        root = Path(root_path)
        gamelists, media = root / "gamelists", root / "downloaded_media"
        has_gamelists, has_media = provider.exists(gamelists), provider.exists(media)

        if has_gamelists or has_media:
            systems = set()
            for base in (gamelists, media):
                systems.update(e.name for e in provider.scandir(base)
                               if e.is_dir and e.name.lower() not in ESDE_IGNORED_SYSTEMS)
            # **이미 스크래핑된 System이 하나라도 있다고 해서 나머지가 전부 그런 건
            # 아니다.** gamelists/도 downloaded_media/도 없는, ROM만 있는 System이
            # 섞여 있으면(막 ROM을 추가했지만 아직 안 긁은 경우) 여기서 끝나면 그
            # System 자체가 Collection에서 통째로 사라진다 - "메타데이터가 있는데
            # 없다고 뜬다"가 아니라 그보다 더 조용한 실패, "아예 안 보인다"였다.
            systems.update(self._systems_with_roms(provider, root))
            confidence = 1.0 if (has_gamelists and has_media) else 0.6
            return Detection(confidence, tuple(sorted(systems)),
                             f"{len(systems)}개 시스템을 찾았습니다.")

        systems = tuple(sorted(self._systems_with_roms(provider, root)))
        if not systems:
            return Detection(0.0, message="gamelists/downloaded_media 폴더도, "
                                          "ROM이 든 시스템 폴더도 찾을 수 없습니다.")
        return Detection(0.3, systems,
                         f"{len(systems)}개 시스템의 ROM을 찾았습니다. "
                         "메타데이터(gamelist.xml)는 아직 없습니다.")

    def _systems_with_roms(self, provider, root) -> list[str]:
        """ROM 파일이 실제로 들어 있는 하위 폴더만 System으로 본다.

        폴더가 있다고 전부 System으로 잡으면 `themes`나 사용자의 잡동사니까지 딸려
        들어온다. 파일이 하나라도 ROM처럼 생겼는지 보고 정한다.
        """
        found = []
        for entry in provider.scandir(root):
            if not entry.is_dir or entry.name.lower() in ESDE_IGNORED_SYSTEMS                     or entry.name.lower() in RESERVED_DIRS:
                continue
            for child in provider.scandir(entry.path):
                if child.is_dir or child.name.startswith("."):
                    continue
                if Path(child.name).suffix.lower() not in NON_ROM_EXTENSIONS:
                    found.append(entry.name)
                    break
        return found

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
        return GameEntry(filename=Path(text("path")).name, fields=fields,
                         frontend_raw=self.tag_raw(raw))

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
        root, before, after = self._read_document(path)
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

        self._write_document(path, root, before, after)

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
                # ES-DE는 `0.9`, `1`처럼 필요한 자리만 쓴다. `:.2f`로 고정하면 값은
                # 그대로인데 파일만 `0.90`, `1.00`으로 바뀌어, 저장할 때마다 실제
                # 백업 기준 1,119줄이 뜻 없이 달라진다.
                self._set(game, "rating",
                          f"{float(rating) / 5:.2f}".rstrip("0").rstrip(".") or "0")
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
        root, before, after = self._read_document(path)
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
        self._write_document(path, root, before, after)

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
    # Frontend 고유 기능 (스펙 §22)
    # ------------------------------------------------------------------
    #: System이 Collection root 밖(외장 SD 등)에 있으면 ES-DE가 스스로 찾지 못한다.
    #: 그 경우 custom systems XML로 ROM 경로를 알려줘야 한다.
    CUSTOM_SYSTEMS_ACTION = "esde-custom-systems"

    def extras(self):
        return [AdapterAction(self.CUSTOM_SYSTEMS_ACTION, "ES-DE XML 생성")]

    def write_custom_systems(self, collection) -> dict:
        """`custom_systems/es_systems.xml`을 만든다(§22).

        **Storage 기능이 아니라 ES-DE Adapter의 기능이다.** 다른 Frontend는 System을
        다른 위치에 두는 문제를 각자의 방식으로 풀기 때문에, 이걸 일반 기능으로
        올리면 ES-DE의 사정이 공통 모델로 새어 나간다.

        Collection root 아래에 있는 System은 ES-DE가 알아서 찾으므로 적지 않는다 -
        전부 적으면 사용자가 ES-DE에서 직접 손본 설정까지 덮어쓰게 된다.
        """
        root = Path(collection.root_path)
        entries = []
        for system in collection.systems:
            layout = self.layout(collection, system.system)
            rom_dir = Path(layout.rom_dir)
            try:
                rom_dir.relative_to(root)
                continue   # root 안에 있으면 ES-DE가 스스로 찾는다
            except ValueError:
                entries.append((system.system, rom_dir))

        path = root / "custom_systems" / "es_systems.xml"
        if not entries:
            return {"path": str(path), "systems": [], "written": False}

        xml_root = ET.Element("systemList")
        for name, rom_dir in entries:
            node = ET.SubElement(xml_root, "system")
            ET.SubElement(node, "name").text = name
            ET.SubElement(node, "fullname").text = name.upper()
            ET.SubElement(node, "path").text = str(rom_dir)
            # 확장자와 실행 명령은 ES-DE 기본값을 쓰게 비워 둔다 - 우리가 추측해서
            # 채우면 사용자의 에뮬레이터 설정을 덮어쓰는 셈이 된다.
            ET.SubElement(node, "extension").text = ""
            ET.SubElement(node, "command").text = ""
            ET.SubElement(node, "platform").text = name
            ET.SubElement(node, "theme").text = name

        write_xml(path, xml_root)
        return {"path": str(path), "systems": [name for name, _ in entries], "written": True}

    # ------------------------------------------------------------------
    @staticmethod
    def _set(game, tag, value):
        """값을 넣는다. **없던 태그를 빈 값으로 새로 만들지는 않는다.**

        원래 `<region>`이 없던 파일을 저장하면 게임마다 `<region/>`이 생겼다. ES-DE가
        읽는 값은 달라지지 않지만, 사용자가 파일을 열어 보거나 버전 관리에 넣어 두면
        1,500줄짜리 잡음이 된다. 반대로 **이미 있던 태그를 비우는 것은 그대로 한다** -
        사용자가 지운 값이니 지워져야 한다.
        """
        text = "" if value in (None, "") else str(value)
        element = game.find(tag)
        if element is None:
            if not text:
                return
            element = ET.SubElement(game, tag)
        element.text = text

    def _parse(self, provider, metadata_file):
        if not metadata_file:
            return None
        return self._read_document(metadata_file, provider)[0]

    @staticmethod
    def _parse_file(path):
        """손상된 XML은 예외를 던지지 않고 None으로 처리한다.

        gamelist.xml 하나가 깨졌다고 Collection 전체 스캔이 실패하면 안 된다 -
        그 System만 메타데이터 없는 상태로 보이는 편이 낫다.

        **ES-DE 3.x는 `<gameList>` 앞에 `<alternativeEmulator>`를 형제로 쓴다.**

        ```xml
        <?xml version="1.0"?>
        <alternativeEmulator>
            <label>Snes9x 2010</label>
        </alternativeEmulator>
        <gameList>
        ```

        최상위 요소가 둘이라 엄밀히는 잘못된 XML이고 `ET.parse`가 "junk after document
        element"로 거절한다. 하지만 이건 ES-DE가 실제로 만들어 내는 파일이다 - 사용자의
        실제 백업에서 26개 시스템 중 9개가 이 형태였고, 그대로 두면 그 시스템의
        메타데이터 488개(전체의 32%)를 통째로 잃는다.

        그래서 실패하면 임시 루트로 감싸 다시 읽고 그 안의 `<gameList>`를 꺼낸다.
        읽기만 할 때 쓴다 - 다시 쓸 거라면 `_read_document()`를 써야 `<gameList>` 밖의
        내용이 살아남는다.
        """
        return EsDeAdapter._read_document(path)[0]

    @staticmethod
    def _read_document(path, provider=None):
        """`(gameList 루트, 그 앞 원문, 그 뒤 원문)`.

        `<gameList>`만 꺼내 읽고 그대로 다시 쓰면 **그 밖에 있던 것이 사라진다.**
        실제 백업에서 9개 시스템이 `<alternativeEmulator>`를 형제로 갖고 있었고,
        저장 한 번에 사용자가 고른 에뮬레이터 설정이 통째로 날아갔다.

        우리가 해석하지 않는 부분은 해석하지 않은 채로 - 원문 문자열 그대로 - 들고
        있다가 되돌려 놓는다. 파싱해서 다시 만들면 우리가 모르는 형태를 우리 모양으로
        바꿔 쓰게 된다.
        """
        data = read_document(path, provider)
        if data is None:
            return None, "", ""
        try:
            return ET.fromstring(data), "", ""
        except ET.ParseError:
            return EsDeAdapter._parse_multi_root(data)

    @staticmethod
    def _parse_multi_root(data):
        """엄밀한 파서가 거절한 gamelist를 최대한 살려 읽는다. `<gameList>`만 돌려준다.

        실제 백업에서 나온 두 가지를 다룬다.

        1. **최상위 요소가 여럿**(위 `_parse_file` 참고) - 임시 루트로 감싼다.
        2. **이스케이프하지 않은 `&`** - `<name>캡틴 아메리카 & 어벤저스</name>` 같은
           값이 실제로 들어 있다. 이건 진짜로 잘못된 XML이지만, 그 한 글자 때문에
           그 System의 199개 항목을 통째로 버리는 것이 더 나쁘다.

        `&`는 감싸기가 실패했을 때만 손댄다. 이미 올바른 실체 참조(`&amp;`, `&#39;`)는
        건드리지 않는다.
        """
        text = data.decode("utf-8", errors="replace")
        # XML 선언은 문서 맨 앞에만 올 수 있으므로 감싸기 전에 떼어낸다.
        body = re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1)
        for candidate in (body, re.sub(r"&(?!#?\w+;)", "&amp;", body)):
            try:
                wrapper = ET.fromstring(f"<rms-wrapper>{candidate}</rms-wrapper>")
            except ET.ParseError:
                continue
            found = wrapper.find("gameList")
            if found is not None:
                return (found,) + EsDeAdapter._split_around_gamelist(body)
        return None, "", ""

    @staticmethod
    def _split_around_gamelist(body):
        """`<gameList>` 앞뒤에 있던 원문을 그대로 잘라 낸다."""
        start = body.find("<gameList")
        if start < 0:
            return "", ""
        end = body.rfind("</gameList>")
        end = end + len("</gameList>") if end >= 0 else len(body)
        return body[:start].strip(), body[end:].strip()

    @staticmethod
    def _write_document(path, root, before="", after="", provider=None):
        """`<gameList>`를 쓰되 그 밖에 있던 원문은 있던 자리에 되돌려 놓는다."""
        if not before and not after:
            return write_document(path, serialize_xml(root), provider)
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        chunks = ['<?xml version="1.0"?>']
        chunks += [part for part in (before, ET.tostring(root, encoding="unicode"), after)
                   if part]
        return write_document(path, ("\n".join(chunks) + "\n").encode("utf-8"), provider)


register(EsDeAdapter())
