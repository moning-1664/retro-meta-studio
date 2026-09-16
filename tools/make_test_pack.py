"""Cross-Frontend Test Pack 생성기.

실제 Frontend를 물려 보려면 라이브러리가 있어야 하는데, ES-DE 말고는 쓰는 사람이
없으면 검증할 대상 자체가 없다. 그래서 4개 Frontend의 **공식 배치대로** 작은
라이브러리를 만들어 준다.

ROM은 실행할 필요가 없으므로 내용이 `TEST ROM` 한 줄이어도 된다. Frontend가 하는
일은 파일을 찾고, 메타데이터를 읽고, media를 화면에 붙이는 것까지이고 검증 대상도
딱 거기까지다.

## media에 이름을 그려 넣는다

1x1 투명 PNG로도 "파일을 찾았는가"는 검증되지만, **어느 슬롯에 붙었는가**는 알 수
없다. 커버 자리에 스크린샷이 들어가도 똑같이 그림 하나가 보일 뿐이다. 그래서 각
이미지에 게임 이름과 media 종류를 그려 넣는다 - Frontend 화면만 보고
"Box Front 자리에 boxFront가 맞게 들어갔다"를 눈으로 판정할 수 있다.

## 일부러 어렵게 만든 케이스

`CASES`에 모아 뒀다. 평범한 게임만 넣으면 전부 통과하는데, 정작 실사용에서 깨지는
것은 ROM 파일명과 제목이 다를 때(LaunchBox), media 경로를 메타데이터가 직접 가리킬
때(원조 ES), ROM 하나에 디스크가 여럿일 때(Pegasus)다.

사용법:

    python -m tools.make_test_pack <출력 폴더>
    python -m tools.make_test_pack <출력 폴더> --frontend launchbox
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SYSTEM = "snes"
#: LaunchBox는 플랫폼 이름을 사람이 읽는 형태로 쓴다.
LAUNCHBOX_PLATFORM = "Super Nintendo Entertainment System"

MEDIA_COLORS = {
    "covers": (188, 68, 68),
    "screenshots": (68, 120, 188),
    "marquees": (188, 148, 60),
    "wheel": (108, 160, 92),
    "miximages": (132, 92, 168),
}


@dataclass
class Case:
    """검증 케이스 하나. 왜 넣었는지를 `why`에 적는다 - 체크리스트로 그대로 나간다."""

    key: str
    rom: str
    title: str
    why: str
    desc: str = ""
    genre: str = ""
    developer: str = ""
    publisher: str = ""
    releasedate: str = ""   # YYYY-MM-DD
    players: str = ""
    rating: str = ""        # 5점 만점
    media: tuple[str, ...] = ("covers", "screenshots")
    #: ROM 파일을 만들지 않는다(메타데이터만 있는 항목).
    rom_missing: bool = False
    #: 메타데이터 항목을 만들지 않는다(ROM만 있는 항목).
    metadata_missing: bool = False
    extra_files: tuple[str, ...] = field(default=())


CASES = [
    Case(key="plain", rom="Metal Gear.sfc", title="Metal Gear",
         why="가장 평범한 경우. 여기가 깨지면 나머지는 볼 것도 없다.",
         desc="A stealth action game.", genre="Action", developer="Konami",
         publisher="Konami", releasedate="1987-07-13", players="1", rating="4.0"),

    Case(key="title-differs", rom="Chrono Trigger (USA) (Rev 1).sfc", title="Chrono Trigger",
         why="**ROM 파일명 != 제목.** LaunchBox는 media를 제목으로 찾으므로 커버가 "
             "'Chrono Trigger.jpg'여야 한다. ES-DE/Pegasus는 ROM stem을 쓴다 - "
             "같은 게임이 Frontend마다 다른 파일명을 기대하는 유일한 지점이다.",
         desc="A time-travelling RPG.", genre="RPG", developer="Square",
         publisher="Square", releasedate="1995-03-11", players="1", rating="5.0"),

    Case(key="special-chars", rom="Ratchet & Clank - Up Your Arsenal.sfc",
         title="Ratchet & Clank: Up Your Arsenal",
         why="제목에 `&`(XML 이스케이프)와 `:`(Windows 파일명 불가)가 함께 있다. "
             "LaunchBox는 `:`를 `_`로 바꿔 저장한다.",
         desc="Contains <angle brackets> & ampersands.", genre="Action",
         developer="Insomniac", releasedate="2004-11-03", players="1-2", rating="4.5"),

    Case(key="korean", rom="슈퍼 마리오 월드 (K).sfc", title="슈퍼 마리오 월드",
         why="비ASCII 파일명. 메타데이터 파일 인코딩(UTF-8)과 Frontend의 폰트를 함께 본다.",
         desc="한글 설명입니다. 줄바꿈도 포함합니다.\n두 번째 줄.",
         genre="플랫포머", developer="닌텐도", releasedate="1990-11-21",
         players="1-2", rating="5.0"),

    Case(key="long-desc", rom="Long Description.sfc", title="Long Description Test",
         why="긴 설명이 잘리는지, 여러 줄 값이 포맷을 깨뜨리지 않는지(Pegasus는 "
             "이어지는 줄을 들여쓰기로 표현한다).",
         desc=("This description is intentionally long. " * 25).strip(),
         genre="Test", developer="RetroMeta", releasedate="2020-01-01",
         players="1", rating="2.5"),

    Case(key="partial-media", rom="Partial Media.sfc", title="Partial Media",
         why="커버만 있고 스크린샷/비디오가 없다. 없는 media를 Frontend가 "
             "빈칸으로 두는지, 깨진 이미지로 두는지.",
         genre="Test", developer="RetroMeta", rating="3.0",
         media=("covers",)),

    Case(key="no-media", rom="No Media.sfc", title="No Media",
         why="media가 하나도 없다.",
         genre="Test", developer="RetroMeta", media=()),

    Case(key="no-metadata", rom="No Metadata.sfc", title="",
         why="ROM만 있고 메타데이터 항목이 없다. Frontend가 파일명으로 이름을 "
             "만들어 보여주는지.",
         metadata_missing=True, media=()),

    Case(key="metadata-only", rom="Missing ROM.sfc", title="Missing ROM",
         why="메타데이터 항목만 있고 ROM이 없다. **유령 항목이 목록에 뜨면 안 된다.**",
         genre="Test", developer="RetroMeta", rom_missing=True, media=()),

    Case(key="multi-disc", rom="Multi Disc Disc 1.sfc", title="Multi Disc Game",
         why="Pegasus의 `files:` multi-file game. 나머지 Frontend에서는 그냥 별개의 "
             "ROM 두 개다 - RetroMeta는 현재 이 블록을 읽지 못하므로(알려진 한계), "
             "**Export 후에도 블록이 살아남았는지**를 본다.",
         genre="RPG", developer="RetroMeta", players="1", rating="4.0",
         extra_files=("Multi Disc Disc 2.sfc",)),
]

ACTIVE = [c for c in CASES if not c.rom_missing]


# ----------------------------------------------------------------------
# 파일 만들기
# ----------------------------------------------------------------------
def write_rom(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"TEST ROM\n{name}\n", encoding="utf-8")


#: 한글 케이스(`korean`)의 이름을 그리려면 Hangul이 있는 폰트가 필요하다. PIL의
#: 내장 비트맵 폰트는 ASCII뿐이라 두부 글자가 되고, 그러면 "어느 게임인가"를 화면에서
#: 못 읽는다 - media 종류만 읽혀서는 슬롯 검증의 절반만 되는 셈이다.
_FONT_CANDIDATES = ("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/gulim.ttc",
                    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf")


def _font(size: int):
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def write_image(path: Path, label: str, media_type: str) -> None:
    """어느 슬롯인지 눈으로 알아볼 수 있게 이름과 종류를 그려 넣는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    size = (320, 448) if media_type == "covers" else (480, 360)
    image = Image.new("RGB", size, MEDIA_COLORS.get(media_type, (90, 90, 90)))
    draw = ImageDraw.Draw(image)
    draw.rectangle([(4, 4), (size[0] - 5, size[1] - 5)], outline=(255, 255, 255), width=3)
    draw.text((16, 16), media_type.upper(), fill=(255, 255, 255), font=_font(26))

    body = _font(22)
    for index, chunk in enumerate([label[i:i + 20] for i in range(0, len(label), 20)][:6]):
        draw.text((16, 56 + index * 28), chunk, fill=(255, 255, 255), font=body)
    image.save(path)


def write_video_placeholder(path: Path) -> None:
    """실제 재생은 검증 대상이 아니라 '경로를 찾는가'만 본다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)


def indent_write(path: Path, root: ET.Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


# ----------------------------------------------------------------------
# Frontend별 배치
# ----------------------------------------------------------------------
def build_es_de(root: Path) -> None:
    """`gamelists/<system>/gamelist.xml` + `downloaded_media/<system>/<타입>/<stem>.png`."""
    # ES-DE는 ROM 루트를 사용자가 따로 고르지만, 이 팩은 Collection root 하나만
    # 쓰므로 어댑터의 기본값(`<storage root>/<system>`)에 맞춘다.
    rom_dir = root / SYSTEM
    media_root = root / "downloaded_media" / SYSTEM
    folders = {"covers": "covers", "screenshots": "screenshots",
               "marquees": "marquees", "wheel": "wheel", "miximages": "miximages"}

    games = ET.Element("gameList")
    for case in CASES:
        if not case.rom_missing:
            write_rom(rom_dir / case.rom, case.title or case.rom)
            for extra in case.extra_files:
                write_rom(rom_dir / extra, extra)
        if case.metadata_missing:
            continue
        game = ET.SubElement(games, "game")
        ET.SubElement(game, "path").text = f"./{case.rom}"
        ET.SubElement(game, "name").text = case.title
        for tag, value in (("desc", case.desc), ("genre", case.genre),
                           ("developer", case.developer), ("publisher", case.publisher),
                           ("players", case.players)):
            if value:
                ET.SubElement(game, tag).text = value
        if case.releasedate:
            ET.SubElement(game, "releasedate").text = case.releasedate.replace("-", "") + "T000000"
        if case.rating:
            ET.SubElement(game, "rating").text = f"{float(case.rating) / 5:.2f}"
        if not case.rom_missing:
            for media_type in case.media:
                write_image(media_root / folders[media_type] / f"{Path(case.rom).stem}.png",
                            case.title or case.rom, media_type)
    indent_write(root / "gamelists" / SYSTEM / "gamelist.xml", games)


def build_pegasus(root: Path) -> None:
    """`<system>/metadata.pegasus.txt` + `<system>/media/<rom stem>/boxFront.png`."""
    system_dir = root / SYSTEM
    asset_names = {"covers": "boxFront", "screenshots": "screenshot",
                   "marquees": "marquee", "wheel": "logo", "miximages": "background"}

    lines = [f"collection: {SYSTEM.upper()}", "shortname: snes", "extensions: sfc,smc", ""]
    for case in CASES:
        if not case.rom_missing:
            write_rom(system_dir / case.rom, case.title or case.rom)
            for extra in case.extra_files:
                write_rom(system_dir / extra, extra)
        if case.metadata_missing:
            continue

        block = [f"game: {case.title}"]
        if case.key == "multi-disc":
            # Pegasus 고유 기능 - 한 게임에 ROM 여럿.
            block.append("files:")
            block.extend(f"  {name}" for name in (case.rom, *case.extra_files))
        else:
            block.append(f"file: {case.rom}")
        if case.desc:
            parts = case.desc.split("\n")
            block.append(f"description: {parts[0]}")
            block.extend(f"  {part}" for part in parts[1:])
        for key, value in (("genre", case.genre), ("developer", case.developer),
                           ("publisher", case.publisher), ("release", case.releasedate),
                           ("players", case.players)):
            if value:
                block.append(f"{key}: {value}")
        if case.rating:
            block.append(f"rating: {round(float(case.rating) / 5 * 100)}%")
        # `assets.*`로 경로를 직접 가리키는 형태도 한 건 섞는다 - RetroMeta가 현재
        # 인식하지 못하는(알려진 한계) 공식 문법이라 회귀 확인용으로 필요하다.
        if case.key == "partial-media":
            block.append("assets.box_front: assets/partial-cover.png")
            write_image(system_dir / "assets" / "partial-cover.png",
                        case.title, "covers")
        lines.append("\n".join(block))
        lines.append("")

        if not case.rom_missing and case.key != "partial-media":
            for media_type in case.media:
                write_image(system_dir / "media" / Path(case.rom).stem
                            / f"{asset_names[media_type]}.png",
                            case.title or case.rom, media_type)

    (system_dir).mkdir(parents=True, exist_ok=True)
    (system_dir / "metadata.pegasus.txt").write_text("\n".join(lines), encoding="utf-8")


def build_launchbox(root: Path) -> None:
    """`Data/Platforms/<platform>.xml` + `Images/<platform>/<폴더>/<제목>.png`.

    **media 파일명이 제목 기준이다** - 이 팩의 `title-differs` 케이스가 노리는 지점.
    """
    illegal = ':*?"<>|/\\'

    def to_filename(title):
        out = title
        for ch in illegal:
            out = out.replace(ch, "_")
        return out.strip()

    rom_dir = root / "Games" / LAUNCHBOX_PLATFORM
    image_root = root / "Images" / LAUNCHBOX_PLATFORM
    folders = {"covers": "Box - Front", "screenshots": "Screenshot - Gameplay",
               "marquees": "Arcade - Marquee", "wheel": "Clear Logo",
               "miximages": "Fanart - Background"}

    games = ET.Element("LaunchBox")
    for case in CASES:
        if not case.rom_missing:
            write_rom(rom_dir / case.rom, case.title or case.rom)
            for extra in case.extra_files:
                write_rom(rom_dir / extra, extra)
        if case.metadata_missing:
            continue
        game = ET.SubElement(games, "Game")
        ET.SubElement(game, "ApplicationPath").text = str(
            Path("Games") / LAUNCHBOX_PLATFORM / case.rom)
        ET.SubElement(game, "Title").text = case.title
        ET.SubElement(game, "Platform").text = LAUNCHBOX_PLATFORM
        for tag, value in (("Notes", case.desc), ("Genre", case.genre),
                           ("Developer", case.developer), ("Publisher", case.publisher),
                           ("MaxPlayers", case.players)):
            if value:
                ET.SubElement(game, tag).text = value
        if case.releasedate:
            ET.SubElement(game, "ReleaseDate").text = f"{case.releasedate}T00:00:00"
        if case.rating:
            ET.SubElement(game, "CommunityStarRating").text = case.rating
        if not case.rom_missing:
            for media_type in case.media:
                write_image(image_root / folders[media_type] / f"{to_filename(case.title)}.png",
                            case.title or case.rom, media_type)
    indent_write(root / "Data" / "Platforms" / f"{LAUNCHBOX_PLATFORM}.xml", games)


def build_emulationstation(root: Path, in_rom_folder: bool) -> None:
    """원조 ES. **gamelist가 media 경로를 직접 가리킨다.**

    `in_rom_folder`가 참이면 gamelist.xml을 ROM 폴더 안에 둔다 - Batocera 계열의
    배치이고, RetroMeta가 현재 자동 인식하지 못하는(알려진 한계) 형태다.
    """
    rom_dir = root / SYSTEM
    gamelist = (rom_dir / "gamelist.xml") if in_rom_folder \
        else (root / "gamelists" / SYSTEM / "gamelist.xml")
    # media는 gamelist 기준 상대 경로로 적는다.
    media_root = root / "downloaded_images" / SYSTEM
    tag_for = {"covers": "thumbnail", "screenshots": "image",
               "marquees": "marquee", "miximages": "fanart"}

    games = ET.Element("gameList")
    for case in CASES:
        if not case.rom_missing:
            write_rom(rom_dir / case.rom, case.title or case.rom)
            for extra in case.extra_files:
                write_rom(rom_dir / extra, extra)
        if case.metadata_missing:
            continue
        game = ET.SubElement(games, "game")
        ET.SubElement(game, "path").text = f"./{case.rom}"
        ET.SubElement(game, "name").text = case.title
        for tag, value in (("desc", case.desc), ("genre", case.genre),
                           ("developer", case.developer), ("publisher", case.publisher),
                           ("players", case.players)):
            if value:
                ET.SubElement(game, tag).text = value
        if case.releasedate:
            ET.SubElement(game, "releasedate").text = case.releasedate.replace("-", "") + "T000000"
        if case.rating:
            ET.SubElement(game, "rating").text = f"{float(case.rating) / 5:.2f}"
        if case.rom_missing:
            continue
        for media_type in case.media:
            dest = media_root / f"{Path(case.rom).stem}-{tag_for[media_type]}.png"
            write_image(dest, case.title or case.rom, media_type)
            try:
                relative = dest.relative_to(gamelist.parent).as_posix()
            except ValueError:
                # gamelist가 ROM 폴더 안에 있으면 media는 그 위에 있다.
                import os
                relative = os.path.relpath(dest, gamelist.parent).replace("\\", "/")
            ET.SubElement(game, tag_for[media_type]).text = f"./{relative}" \
                if not relative.startswith(".") else relative
    indent_write(gamelist, games)


# ----------------------------------------------------------------------
# 체크리스트
# ----------------------------------------------------------------------
CHECKLIST_HEADER = """# Cross-Frontend Test Pack

`tools/make_test_pack.py`가 만든 검증용 라이브러리다. ROM은 전부 내용이 `TEST ROM`인
텍스트 파일이라 **실행되지 않는다** - 검증 대상은 파일 발견 / 메타데이터 / media 표시까지다.

이미지에는 게임 이름과 media 종류가 그려져 있다. Frontend 화면에서 `BOX FRONT` 자리에
`COVERS`라고 적힌 그림이 보이면 슬롯이 맞게 붙은 것이다.

## 검증 절차

1. 아래 각 폴더를 해당 Frontend에 라이브러리로 등록한다.
2. **먼저 Frontend에서** 게임 목록과 media가 정상인지 본다(팩 자체가 맞는지 확인).
3. RetroMeta Studio로 그 폴더를 Collection으로 추가하고 Scan한다.
4. 메타데이터를 수정하고 Apply한 뒤, **다시 Frontend에서 열어** 반영됐는지 본다.
5. 다른 Frontend로 Convert한 뒤 그쪽에서도 연다.

3번에서 안 보이는 것과 5번에서 안 보이는 것은 원인이 다르다 - 전자는 읽기,
후자는 쓰기 문제다.

## 케이스

"""

KNOWN_GAPS = """
## 지금 알려진 한계 (이 팩으로 재현된다)

`tests/test_frontend_compat.py`에 `expectedFailure`로 박혀 있다. 고치면 그 테스트가
unexpected success로 실패하므로 데코레이터를 떼면 된다.

| 케이스 | 어디서 | 증상 |
|---|---|---|
| `multi-disc` | Pegasus Scan | `files:` 블록을 읽지 못해 **목록에 안 뜬다**. 단 Export해도 블록은 살아남아야 한다 - 사라지면 그건 데이터 파괴 버그다 |

`players`가 `1-2`인 케이스(`special-chars`, `korean`)는 Pegasus/LaunchBox의 정수
필드로 그대로 나간다. 두 Frontend가 이것을 어떻게 표시하는지는 **실기에서 확인해야
하는 미확정 항목**이다.

## 고쳐진 것 (회귀 확인용)

예전엔 아래가 전부 한계였다. 지금은 **되어야** 하고, 안 되면 퇴행이다.

| 케이스 | 무엇을 보나 |
|---|---|
| `title-differs` | LaunchBox로 Export한 커버가 `Chrono Trigger.png`여야 한다. ROM 이름(`... (USA) (Rev 1).png`)으로 저장되면 LaunchBox 화면에 안 나온다 |
| `partial-media` | Pegasus의 `assets.box_front:`로 지정한 커버가 앱에 보여야 한다 |
| (배치) | `emulationstation-romfolder/`가 Collection으로 추가되고 스캔돼야 한다 |
| (rating) | Pegasus 쪽 rating이 퍼센트로 적혀야 한다. `rating: 4.5` 같은 값이 보이면 퇴행이다 |

## Daijishō

별도 Adapter가 없다. `emulationstation/` 또는 `emulationstation-romfolder/` 팩을
안드로이드 기기에 올리고 Daijishō의 gamelist.xml import로 읽히는지 본다.
"""


def write_checklist(out: Path) -> None:
    lines = [CHECKLIST_HEADER]
    for case in CASES:
        lines.append(f"### `{case.key}` — {case.title or case.rom}\n")
        lines.append(f"- ROM: `{case.rom}`")
        if case.extra_files:
            lines.append(f"- 추가 파일: {', '.join(f'`{f}`' for f in case.extra_files)}")
        lines.append(f"- media: {', '.join(case.media) if case.media else '없음'}")
        if case.rom_missing:
            lines.append("- **ROM 파일 없음** (메타데이터만)")
        if case.metadata_missing:
            lines.append("- **메타데이터 항목 없음** (ROM만)")
        lines.append(f"- 보는 이유: {case.why}\n")
    lines.append(KNOWN_GAPS)
    (out / "CHECKLIST.md").write_text("\n".join(lines), encoding="utf-8")


BUILDERS = {
    "es-de": build_es_de,
    "pegasus": build_pegasus,
    "launchbox": build_launchbox,
    "emulationstation": lambda root: build_emulationstation(root, in_rom_folder=False),
    "emulationstation-romfolder": lambda root: build_emulationstation(root, in_rom_folder=True),
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Cross-Frontend Test Pack을 만든다.")
    parser.add_argument("out", help="출력 폴더")
    parser.add_argument("--frontend", choices=sorted(BUILDERS), action="append",
                        help="이것만 만든다(여러 번 지정 가능). 기본은 전부.")
    args = parser.parse_args(argv)

    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        parser.error(f"비어 있지 않은 폴더입니다: {out}")
    out.mkdir(parents=True, exist_ok=True)

    for name in (args.frontend or sorted(BUILDERS)):
        target = out / name
        target.mkdir(parents=True, exist_ok=True)
        BUILDERS[name](target)
        print(f"  {name:32} -> {target}")
    write_checklist(out)
    print(f"\n체크리스트: {out / 'CHECKLIST.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
