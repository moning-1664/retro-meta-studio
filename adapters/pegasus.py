"""
adapters/pegasus.py
====================
Pegasus Frontend Adapter.

구조:

```
<root>/<system>/metadata.pegasus.txt      게임 정보(빈 줄로 나뉜 key: value 블록)
<root>/<system>/<rom files>               ROM이 metadata와 같은 폴더에 있다
<root>/<system>/media/<rom stem>/boxFront.png
```

ES-DE와 달리 **ROM과 metadata가 같은 폴더**이고, media는 타입별 폴더가 아니라
**게임별 폴더 안의 정해진 파일명**이다. 그래서 `layout()`이 셋 다 같은 System 폴더를
가리키고, `media_pairs()`가 media type을 파일명으로 바꾼다.

## 이전 프로젝트에서 고친 것 — 모르는 키를 버리지 않는다

`exporters/pegasus.py`의 writer는 game 블록을 **알고 있는 필드만으로 다시 만들었다.**
그래서 사용자가 `assets.boxFront:`나 `sort-by:`, `x-rating:` 같은 키를 직접 넣어 두었어도
한 번 Export하면 사라졌다. 여기서는 블록의 모든 줄을 읽어 아는 키는 공통 필드로,
나머지는 `frontend_raw["extra"]`에 **순서까지 유지해** 담고 쓸 때 되살린다(계약 2, §50-51).

파일 수준 보존도 같다. `write_index()`는 기존 파일을 읽어 해당 게임 블록만 갈아끼우므로
헤더 블록(`collection:` / `shortname:` / `launch:`)과 다른 게임 블록이 그대로 남는다.

## Pegasus의 여러 줄 값

Pegasus 포맷은 이어지는 줄이 공백으로 시작하면 앞 키의 값이 계속되는 것으로 본다
(주로 `description:`이 그렇다). 그 규칙을 지키지 않으면 여러 줄 설명이 있는 파일에서
줄 하나하나가 새 키로 잘못 읽힌다.
"""

from __future__ import annotations

from pathlib import Path

from adapters.base import (NON_ROM_EXTENSIONS, Detection, FrontendAdapter, GameEntry, Layout, MediaFile,
                           read_text_document, register, resolve_existing, write_text_document)

METADATA_FILENAME = "metadata.pegasus.txt"
#: Pegasus 공식 포맷은 이 이름도 허용한다. 새로 만들 때는 위쪽(정식 이름)을 쓴다.
METADATA_FILENAMES = (METADATA_FILENAME, "metadata.txt")

#: 공통 모델 <-> Pegasus 키. 여기 없는 키는 전부 frontend_raw로 보존된다.
FIELD_KEYS = {
    "name": "game",
    "desc": "description",
    "genre": "genre",
    "developer": "developer",
    "publisher": "publisher",
    "releasedate": "release",
    "players": "players",
    "rating": "rating",
}
#: `file:`은 항목의 식별자라 공통 필드가 아니고, 블록을 쓸 때 직접 넣는다.
STRUCTURAL_KEYS = {"file", "files"}

#: media type -> 게임 폴더 안의 파일명(확장자 제외). Pegasus의 asset 이름이다.
ASSET_NAMES = {
    "covers": "boxFront",
    "screenshots": "screenshot",
    "marquees": "marquee",
    "miximages": "background",
    "wheel": "logo",
    "videos": "video",
}
#: 읽을 때는 별칭도 받아들인다 - 사람이 손으로 만든 폴더에는 cover/fanart 같은 이름이 흔하다.
ASSET_ALIASES = {
    "boxfront": "covers", "cover": "covers", "box": "covers",
    "screenshot": "screenshots",
    "marquee": "marquees",
    "background": "miximages", "fanart": "miximages",
    "logo": "wheel", "wheel": "wheel",
    "video": "videos",
}

MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".avi", ".webm"}
#: System 폴더 안에 있지만 게임이 아닌 것들.
RESERVED_DIRS = {"media", "assets"}


def parse_metadata(text: str) -> tuple[list[str], list[list[tuple[str, str]]]]:
    """metadata.pegasus.txt -> (헤더 줄들, 게임 블록들).

    블록은 `[(key, value), ...]`로 **순서를 지켜** 돌려준다. dict로 만들면 다시 쓸 때
    사용자가 적어 둔 줄 순서가 흐트러진다.
    """
    header: list[str] = []
    blocks: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []

    def flush():
        nonlocal current
        if current:
            blocks.append(current)
            current = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            flush()
            continue
        if line.strip().startswith("#"):
            # 게임 블록이 시작되기 전의 주석은 헤더의 일부로 보존한다. 블록 안의
            # 주석까지 (key, value) 목록에 섞으면 되살릴 때 순서가 꼬인다.
            if not current:
                header.append(line)
            continue
        # 공백으로 시작하면 앞 키의 값이 이어지는 것이다(주로 description).
        if line[:1] in (" ", "\t") and current:
            key, value = current[-1]
            current[-1] = (key, f"{value}\n{line.strip()}")
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        if not current and key not in FIELD_KEYS.values() and key not in STRUCTURAL_KEYS:
            # 아직 게임 블록이 시작되지 않았다 = collection:/shortname:/launch: 같은 헤더.
            header.append(line)
            continue
        current.append((key, value))
    flush()
    return header, blocks


def rating_to_common(value: str) -> str:
    """Pegasus rating -> 공통 모델의 5점 만점.

    Pegasus 공식 포맷의 rating은 **퍼센트**(`rating: 75%`)이고, 공통 모델은 5점
    만점이다(ES-DE의 0~1을 ×5한 값). 변환하지 않으면 ES-DE의 별 4.5개가 Pegasus에서
    `4.5`로 적혀 평점이 조용히 다른 값이 된다 - 오류는 안 나고 값만 틀리는 종류라
    눈으로는 오래 못 잡는다.

    퍼센트가 아닌 값도 받아들인다. 0~1이면 ES-DE와 같은 비율로 보고, 그보다 크면
    이미 5점 만점이라고 본다 - 손으로 적은 파일이나 예전에 우리가 잘못 쓴 파일을
    만났을 때 값을 버리는 것보다 낫다.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        if text.endswith("%"):
            return f"{float(text[:-1]) / 20:.1f}"
        number = float(text)
    except (TypeError, ValueError):
        return text
    return f"{number * 5:.1f}" if 0.0 <= number <= 1.0 else text


def rating_from_common(value: str) -> str:
    """공통 모델의 5점 만점 -> Pegasus의 퍼센트 표기."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return f"{round(float(text) / 5 * 100)}%"
    except (TypeError, ValueError):
        return text


def _asset_key(name: str) -> str:
    """`assets.` 뒤의 이름을 `ASSET_ALIASES`의 키 모양으로.

    Pegasus는 `box_front`와 `boxFront`를 같은 것으로 본다. `parse_metadata()`가 키를
    이미 소문자로 만들므로 여기서는 구분자만 걷어내면 된다.
    """
    return name.replace("_", "").replace("-", "").strip().lower()


def _block_value(block, key):
    for k, v in block:
        if k == key:
            return v
    return ""


def format_block(pairs) -> str:
    """(key, value) 목록을 Pegasus 블록 문자열로. 여러 줄 값은 들여쓴다."""
    lines = []
    for key, value in pairs:
        parts = str(value or "").split("\n")
        lines.append(f"{key}: {parts[0]}")
        lines.extend(f"  {part}" for part in parts[1:])
    return "\n".join(lines)


class PegasusAdapter(FrontendAdapter):
    id = "pegasus"
    display_name = "Pegasus"
    media_types = tuple(ASSET_NAMES)
    #: Pegasus 포맷에는 region 키가 없다 - Convert 미리보기가 이걸 근거로
    #: "버려지는 필드"를 센다.
    supported_fields = tuple(FIELD_KEYS)

    # ------------------------------------------------------------------
    # 구조 파악
    # ------------------------------------------------------------------
    def detect(self, provider, root_path) -> Detection:
        root = Path(root_path)
        if not provider.exists(root):
            return Detection(0.0, message="경로가 존재하지 않습니다.")
        systems, with_metadata = [], 0
        for entry in provider.scandir(root):
            if not entry.is_dir or entry.name.lower() in RESERVED_DIRS:
                continue
            systems.append(entry.name)
            if any(provider.exists(Path(entry.path) / name) for name in METADATA_FILENAMES):
                with_metadata += 1
        if not systems:
            return Detection(0.0, message="시스템 폴더가 없습니다.")
        if not with_metadata:
            return Detection(0.0, message=f"{METADATA_FILENAME}을 찾을 수 없습니다.")
        confidence = 1.0 if with_metadata == len(systems) else 0.7
        return Detection(confidence, tuple(sorted(systems)),
                         f"{len(systems)}개 시스템을 찾았습니다.")

    def list_systems(self, provider, collection) -> list[str]:
        systems = set()
        roots = [Path(collection.root_path)] + [Path(s.root_path) for s in collection.storages]
        for root in roots:
            systems.update(e.name for e in provider.scandir(root)
                           if e.is_dir and e.name.lower() not in RESERVED_DIRS)
        return sorted(systems)

    def layout(self, collection, system) -> Layout:
        """ROM/metadata/media가 모두 같은 System 폴더 아래에 있다.

        ES-DE와 달리 metadata를 앱 데이터 폴더에 따로 두지 않으므로, System이 다른
        Storage에 있으면 metadata와 media도 그 Storage를 따라간다.
        """
        entry = next((s for s in collection.systems if s.system == system), None)
        storage = collection.storage(entry.storage_id) if entry else None
        root = Path(storage.root_path) if storage else Path(collection.root_path)
        system_dir = Path(entry.rom_path) if entry and entry.rom_path else root / system
        return Layout(
            system=system,
            rom_dir=str(system_dir),
            metadata_file=(str(Path(entry.metadata_path)) if entry and entry.metadata_path
                           else resolve_existing([system_dir / name
                                                  for name in METADATA_FILENAMES])),
            media_dir=str(Path(entry.media_path) if entry and entry.media_path
                          else system_dir / "media"),
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
        text = self._read_text(provider, layout.metadata_file)
        if text is None:
            return {}
        _header, blocks = parse_metadata(text)
        entries = {}
        for block in blocks:
            filename = Path(_block_value(block, "file")).name
            if not filename:
                continue
            entries[filename] = self.to_common(block, filename)
        return entries

    def raw_metadata_filenames(self, provider, layout) -> list[str]:
        text = self._read_text(provider, layout.metadata_file)
        if text is None:
            return []
        _header, blocks = parse_metadata(text)
        return [Path(_block_value(block, "file")).name for block in blocks if _block_value(block, "file")]

    def validate_metadata_syntax(self, provider, path) -> "str | None":
        """`parse_metadata()`는 줄 단위로 관대하게 읽는다(모르는 줄은 조용히 건너뛴다) -
        Pegasus 형식에는 "문법 오류"라는 개념이 없다. 파일 자체를 못 읽는 경우만 알린다."""
        return None if provider.exists(path) else "파일을 읽을 수 없습니다."

    def to_common(self, block, filename) -> GameEntry:
        """블록을 (공통 필드, 원본 보존분)으로 나눈다.

        아는 키만 뽑고 나머지를 버리면 다시 쓸 때 사라진다 - 순서까지 유지해 남긴다.
        """
        reverse = {v: k for k, v in FIELD_KEYS.items()}
        fields = {key: "" for key in FIELD_KEYS}
        extra = []
        for key, value in block:
            common = reverse.get(key)
            if common is not None and not fields[common]:
                fields[common] = value
            elif key not in STRUCTURAL_KEYS:
                extra.append({"key": key, "value": value})
        raw = {"extra": extra} if extra else {}
        fields["rating"] = rating_to_common(fields["rating"])
        # Pegasus 포맷에는 region이 없다. 공통 모델의 키 구성을 다른 Adapter와
        # 맞추기 위해 빈 값으로 채워 둔다(없는 것과 빈 것을 구분하지 않는다).
        fields["region"] = ""
        return GameEntry(filename=filename, fields=fields,
                         frontend_raw=self.tag_raw(raw))

    def media_dirs(self, layout, media_types=None) -> list[str]:
        """게임별 폴더라 타입별 디렉터리가 없다 - media 루트 하나만 돌려준다."""
        return [layout.media_dir] if layout.media_dir else []

    def _assets_media_index(self, provider, layout, wanted) -> dict[str, list[MediaFile]]:
        """메타데이터의 `assets.*` 키가 **직접 가리키는** media를 모은다.

        Pegasus는 `media/<game>/boxFront.png` 폴더 규칙 외에 `assets.box_front:`로
        경로를 적는 것도 공식 문법이다. 폴더 규칙만 훑으면 그렇게 정리해 둔
        라이브러리의 media를 통째로 놓친다 - 값은 `frontend_raw`에 보존되므로 잃지는
        않지만 앱에서는 "media 없음"으로 보인다.

        경로는 메타데이터 파일 기준 상대 경로이거나 절대 경로다.
        """
        text = self._read_text(provider, layout.metadata_file)
        if text is None:
            return {}
        base = Path(layout.metadata_file).parent
        index: dict[str, list[MediaFile]] = {}
        for block in parse_metadata(text)[1]:
            filename = Path(_block_value(block, "file")).name
            if not filename:
                continue
            stem = Path(filename).stem
            for key, value in block:
                if not key.startswith("assets.") or not value:
                    continue
                media_type = ASSET_ALIASES.get(_asset_key(key[len("assets."):]))
                if not media_type or (wanted is not None and media_type not in wanted):
                    continue
                raw = value.replace("\\", "/")
                path = Path(raw) if Path(raw).is_absolute() else (base / raw)
                info = provider.stat(path)
                if info is None:
                    continue   # 가리키지만 실제로는 없는 파일
                index.setdefault(stem, []).append(
                    MediaFile(media_type=media_type, path=str(path),
                              size=info.size, mtime_ns=info.mtime_ns))
        return index

    def read_media_index(self, provider, layout, media_types=None) -> dict[str, list[MediaFile]]:
        if not layout.media_dir:
            return {}
        wanted = set(media_types) if media_types is not None else None
        # 폴더 규칙이 우선이고, `assets.*`는 그 자리가 비었을 때만 채운다 - 둘 다
        # 있으면 Pegasus 자신도 폴더 쪽을 쓴다.
        index: dict[str, list[MediaFile]] = {}
        for game_dir in provider.scandir(layout.media_dir):
            if not game_dir.is_dir:
                continue
            for entry in provider.scandir(game_dir.path):
                if entry.is_dir or Path(entry.name).suffix.lower() not in MEDIA_EXTENSIONS:
                    continue
                media_type = ASSET_ALIASES.get(Path(entry.name).stem.lower())
                if not media_type or (wanted is not None and media_type not in wanted):
                    continue
                index.setdefault(game_dir.name, []).append(
                    MediaFile(media_type=media_type, path=entry.path,
                              size=entry.size, mtime_ns=entry.mtime_ns))

        for stem, items in self._assets_media_index(provider, layout, wanted).items():
            have = {m.media_type for m in index.get(stem, [])}
            index.setdefault(stem, []).extend(m for m in items if m.media_type not in have)
        return index

    # ------------------------------------------------------------------
    # 쓰기 (bulk)
    # ------------------------------------------------------------------
    def write_index(self, layout, entries) -> None:
        """해당 게임 블록만 갈아끼우고 나머지는 그대로 둔다.

        기존 파일의 헤더(`collection:` 등)와 entries에 없는 게임 블록은 건드리지
        않는다 - Export가 기존 데이터를 조용히 지우면 안 된다(§70).
        """
        path = layout.metadata_file
        header, blocks = parse_metadata(read_text_document(path))

        by_filename = {}
        for index, block in enumerate(blocks):
            name = Path(_block_value(block, "file")).name
            if name:
                by_filename[name] = index

        for entry in entries:
            pairs = self.from_common(entry, blocks[by_filename[entry.filename]]
                                     if entry.filename in by_filename else None)
            if entry.filename in by_filename:
                blocks[by_filename[entry.filename]] = pairs
            else:
                blocks.append(pairs)

        chunks = []
        if header:
            chunks.append("\n".join(header))
        chunks.extend(format_block(block) for block in blocks)
        write_text_document(path, "\n\n".join(chunks) + "\n")

    def from_common(self, entry, existing=None) -> list[tuple[str, str]]:
        """공통 필드 + 보존해둔 원본 -> 블록의 (key, value) 목록.

        `existing`이 있으면 그 줄 순서를 최대한 유지한다 - 사용자가 정리해 둔 파일이
        Export 한 번에 뒤죽박죽이 되면 안 된다.
        """
        fields = entry.fields or {}
        values = {pegasus_key: (fields.get(common) or "").strip()
                  for common, pegasus_key in FIELD_KEYS.items()}
        values["rating"] = rating_from_common(values["rating"])
        # 모양이 다른 항목(다른 Frontend의 raw)이 섞여 들어와도 깨지지 않는다.
        # 호출부가 걸러주는 것이 정상이지만, 여기서 KeyError로 Apply 전체가 실패하는
        # 일은 없어야 한다.
        extra = {item["key"]: item.get("value", "")
                 for item in (entry.frontend_raw or {}).get("extra") or []
                 if isinstance(item, dict) and "key" in item}

        pairs: list[tuple[str, str]] = []
        seen = set()
        order = [key for key, _ in (existing or [])]
        # Pegasus는 game:/file:을 블록 앞머리에 두는 것이 관례다.
        for key in ["game", "file"] + [k for k in order if k not in ("game", "file")]:
            if key in seen:
                continue
            seen.add(key)
            if key == "file":
                pairs.append(("file", entry.filename))
            elif key in values:
                if values[key]:
                    pairs.append((key, values[key]))
            elif key in extra:
                pairs.append((key, extra[key]))
        for key, value in values.items():
            if key not in seen and value:
                pairs.append((key, value))
                seen.add(key)
        for key, value in extra.items():
            if key not in seen:
                pairs.append((key, value))
                seen.add(key)
        return pairs

    def remove_entries(self, layout, filenames) -> None:
        path = layout.metadata_file
        text = read_text_document(path)
        if not text:
            return
        header, blocks = parse_metadata(text)
        wanted = set(filenames)
        kept = [b for b in blocks if Path(_block_value(b, "file")).name not in wanted]
        if len(kept) == len(blocks):
            return
        chunks = ["\n".join(header)] if header else []
        chunks.extend(format_block(block) for block in kept)
        write_text_document(path, ("\n\n".join(chunks) + "\n") if chunks else "")

    def media_pairs(self, layout, filename, media, title=None) -> list[tuple[str, str]]:
        """media type을 게임 폴더 안의 정해진 파일명으로 바꾼다.

        같은 타입이 여러 개면 첫 번째만 쓴다 - Pegasus는 타입당 파일 하나를 기대한다.
        """
        dest_dir = Path(layout.media_dir) / Path(filename).stem
        pairs, used = [], set()
        for item in media:
            asset = ASSET_NAMES.get(item.media_type)
            if not asset or item.media_type in used:
                continue
            used.add(item.media_type)
            pairs.append((item.path, str(dest_dir / f"{asset}{Path(item.path).suffix}")))
        return pairs

    # ------------------------------------------------------------------
    @staticmethod
    def _read_text(provider, metadata_file):
        if not metadata_file or not provider.exists(metadata_file):
            return None
        try:
            return read_text_document(metadata_file, provider)
        except OSError:
            # 파일 하나가 안 읽힌다고 Collection 전체 스캔이 실패하면 안 된다.
            return None


register(PegasusAdapter())
