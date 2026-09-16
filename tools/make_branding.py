"""앱 브랜딩 그림(Navigator 상단 로고 + exe 아이콘)을 만든다.

**손으로 그린 PNG를 저장소에 넣어 두는 대신 만드는 방법을 넣어 둔다.** 색을 한 번
바꾸려고 이미지 편집기를 다시 여는 대신 여기 상수를 고치고 다시 돌리면 된다 -
`tools/make_test_pack.py`와 같은 태도다.

만드는 것:

- `gui_web/app-icon.png` - 카트리지 아이콘. 라벨에는 안드로메다 은하를 픽셀로
  그린다(사용자 결정 - "RetroMeta = Andromeda 어감이 비슷하니").
- `gui_web/app-title.png` - "RetroMeta Studio"를 픽셀 글자로. 대문자 R/M/S와 i의
  꼭지에 빨/녹/파/노를 넣어 레트로 느낌을 낸다(사용자 결정).
- `app.ico` - 같은 카트리지로 만든 exe 아이콘(16~256px).

## 왜 글자를 이미지로 굽는가

픽셀 폰트 TTF를 저장소에 넣으려면 외부 폰트를 받아 와야 하고, 라이선스도 따라온다.
여기서는 **시스템 폰트를 아주 작게 그린 뒤 이진화(threshold)해서** 픽셀 글자를
만든다 - 안티에일리어싱이 사라지면서 비트맵 폰트와 같은 계단 모양이 남는다. 그것을
정수배(2x)로 확대하므로 가장자리가 흐려지지 않는다.

**글자마다 1px 어두운 외곽선을 두른다.** 밝은 테마(theme.css의 light 계열)에서
흰 글자가 배경에 묻히기 때문이다 - 외곽선은 레트로 스타일이기도 해서 두 문제를
한 번에 푼다.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
GUI = ROOT / "gui_web"

#: **두 줄이다.** Navigator 폭은 224px 고정이고 아이콘과 여백을 빼면 글자에
#: 쓸 수 있는 폭이 ~150px인데, "RetroMeta Studio"를 한 줄에 넣으면 글자당
#: 5px밖에 못 준다 - 어떤 서체를 써도 뭉개진다. 두 줄로 나누면 글자당 8~12px가
#: 되어 제대로 된 픽셀 글자 모양이 나온다(사용자 카트리지 그림도 두 줄이다).
TITLE_LINES = ("RetroMeta", "Studio")
#: 2x로 확대하기 전의 한 줄 폭(아트 픽셀). 긴 줄("RetroMeta")을 기준으로 잡는다.
TITLE_ART_WIDTH = 70
SCALE = 2

#: 레트로 4색 + 본문 글자색 + 외곽선.
RED, GREEN, BLUE, YELLOW = (232, 69, 60), (76, 175, 80), (63, 138, 224), (245, 197, 24)
INK = (240, 244, 248)
OUTLINE = (13, 18, 32)
#: 어느 글자에 색을 넣을지 - (줄 번호, 글자 번호). R/M은 첫 줄, S는 둘째 줄.
LETTER_COLORS = {(0, 0): RED, (0, 5): GREEN, (1, 0): BLUE}
#: i의 꼭지만 따로 칠한다(줄기는 본문색). "Studio"의 i는 둘째 줄 4번째다.
DOT_AT, DOT_COLOR = (1, 4), YELLOW

#: 좁은 폭에 글자를 최대한 키우려면 폭이 좁은 서체가 필요하다.
FONT_CANDIDATES = ("C:/Windows/Fonts/arialnb.ttf", "C:/Windows/Fonts/arialn.ttf",
                   "C:/Windows/Fonts/tahomabd.ttf", "C:/Windows/Fonts/arialbd.ttf")


def _font_path() -> str:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("픽셀 글자를 구울 서체를 찾지 못했습니다: " + ", ".join(FONT_CANDIDATES))


def _pick_size(path: str, target_width: int) -> ImageFont.FreeTypeFont:
    """가장 긴 줄이 target_width에 가장 가까워지는 글자 크기를 고른다.

    크기를 눈으로 정하면 서체가 바뀔 때마다 다시 맞춰야 한다 - 목표 폭을 주고
    찾게 하면 서체를 바꿔도 레이아웃이 그대로다.
    """
    longest = max(TITLE_LINES, key=len)
    best, best_gap = None, None
    for size in range(8, 26):
        font = ImageFont.truetype(path, size)
        gap = abs(round(font.getlength(longest)) - target_width)
        if best_gap is None or gap < best_gap:
            best, best_gap = font, gap
    return best


def _render_line(text: str, font: ImageFont.FreeTypeFont):
    """한 줄을 이진화해서 (픽셀 맵, 폭, 높이, 글자별 x 범위)로 돌려준다.

    작게 그린 뒤 이진화하면 안티에일리어싱이 사라지면서 비트맵 폰트와 같은
    계단이 남는다 - 이것이 픽셀 글자의 정체다.
    """
    bbox = font.getbbox(text)
    canvas = Image.new("L", (bbox[2] + 6, bbox[3] + 6), 0)
    origin_x, origin_y = 3 - bbox[0], 3 - bbox[1]
    ImageDraw.Draw(canvas).text((origin_x, origin_y), text, font=font, fill=255)
    # 110은 "획의 중심만 남기는" 문턱이다. 더 높이면 가는 획이 끊기고, 더 낮추면
    # 안티에일리어싱의 회색까지 살아나 계단이 뭉갠다.
    binary = canvas.point(lambda v: 255 if v >= 110 else 0)
    box = binary.getbbox()
    binary = binary.crop(box)
    spans = [(round(origin_x + font.getlength(text[:i])) - box[0],
              round(origin_x + font.getlength(text[:i + 1])) - box[0])
             for i in range(len(text))]
    return binary.load(), binary.size[0], binary.size[1], spans


def _dot_rows(pixels, height, span) -> set[int]:
    """i의 꼭지가 차지하는 행. 꼭지와 줄기 사이에는 빈 줄이 있다는 점을 쓴다."""
    rows = [y for y in range(height) if any(pixels[x, y] for x in range(*span))]
    if not rows:
        return set()
    dot = []
    for y in rows:
        if dot and y != dot[-1] + 1:
            break          # 빈 줄을 만났다 - 여기까지가 꼭지다.
        dot.append(y)
    return set(dot) if len(dot) < len(rows) else set()


def build_title() -> Image.Image:
    font = _pick_size(_font_path(), TITLE_ART_WIDTH)
    lines = [_render_line(text, font) for text in TITLE_LINES]

    gap = 2                                            # 줄 사이(아트 픽셀)
    art_w = max(w for _p, w, _h, _s in lines)
    art_h = sum(h for _p, _w, h, _s in lines) + gap * (len(lines) - 1)
    art = Image.new("RGBA", (art_w + 2, art_h + 2), (0, 0, 0, 0))
    out = art.load()

    top = 0
    for line_index, (pixels, width, height, spans) in enumerate(lines):
        dot = _dot_rows(pixels, height, spans[DOT_AT[1]]) if DOT_AT[0] == line_index else set()

        def color_at(x, y, spans=spans, dot=dot, line_index=line_index):
            for index, (start, end) in enumerate(spans):
                if start <= x < end:
                    if (line_index, index) == DOT_AT and y in dot:
                        return DOT_COLOR
                    return LETTER_COLORS.get((line_index, index), INK)
            return INK

        # 외곽선 1px을 먼저 깔고 그 위에 글자를 얹는다 - 밝은 테마에서도 글자가
        # 배경에 묻히지 않는다.
        for y in range(height):
            for x in range(width):
                if not pixels[x, y]:
                    continue
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        out[x + 1 + dx, top + y + 1 + dy] = (*OUTLINE, 255)
        for y in range(height):
            for x in range(width):
                if pixels[x, y]:
                    out[x + 1, top + y + 1] = (*color_at(x, y), 255)
        top += height + gap

    return art.resize((art.width * SCALE, art.height * SCALE), Image.NEAREST)


# ----------------------------------------------------------------------
# 카트리지 + 안드로메다
# ----------------------------------------------------------------------
#: 사용자가 만든 카트리지 그림. **다시 그리지 않는다** - 껍데기·MSX 띠·접점·
#: 아래쪽 보라색 띠까지 그대로 쓰고, 화면(라벨) 안의 글자 자리에만 은하를 얹는다
#: (사용자 결정 - "내가 만든 롬팩 이미지에 안드로메다만 안에 넣어달라").
SOURCE = Path(__file__).resolve().parent / "assets" / "cartridge-source.png"
#: 원본에서 화면(짙은 남색) 영역. 위쪽 파란 그라데이션 띠와 MSX 리본, 아래쪽
#: 보라색 띠는 남기고 그 사이의 글자 자리만 덮는다.
SCREEN = (210, 258, 1278, 760)
#: 은하 - 바깥 헤일로에서 core로 갈수록 밝아진다.
GALAXY = [(26, 34, 78), (52, 78, 158), (96, 140, 226), (186, 210, 252), (255, 248, 214)]
#: 원본 그림의 한 "픽셀" 크기(실제 px). 은하도 같은 격자로 그려야 한 그림처럼 보인다.
ART_PIXEL = 10


def build_cartridge() -> Image.Image:
    cart = Image.open(SOURCE).convert("RGBA")
    x0, y0, x1, y1 = SCREEN

    # 원래 그 자리에 있던 글자("Retro Pack Mania")를 먼저 지운다 - 화면 구석의
    # 배경색을 그대로 떠서 칠하면 위아래 띠와 이어진 한 화면으로 남는다.
    sky_bg = cart.getpixel((x0 + 6, y1 - 6))
    ImageDraw.Draw(cart).rectangle([x0, y0, x1 - 1, y1 - 1], fill=sky_bg)

    # 은하는 원본과 같은 픽셀 격자에 그린다 - 작게 그린 뒤 NEAREST로 키운다.
    cols, rows = (x1 - x0) // ART_PIXEL, (y1 - y0) // ART_PIXEL
    sky = Image.new("RGBA", (cols, rows), (0, 0, 0, 0))
    px = sky.load()

    cx, cy = cols / 2, rows / 2
    tilt = math.radians(-20)
    scale = min(cols, rows * 2.0) / 2.6        # 화면 폭에 맞춰 은하 크기를 정한다
    for y in range(rows):
        for x in range(cols):
            dx, dy = (x + 0.5) - cx, (y + 0.5) - cy
            rx = (dx * math.cos(tilt) - dy * math.sin(tilt)) / scale
            ry = (dx * math.sin(tilt) + dy * math.cos(tilt)) * 2.0 / scale
            radius = math.hypot(rx, ry)
            if radius > 1.0:
                continue
            if radius < 0.16:
                px[x, y] = (*GALAXY[4], 255)            # core - 가장 밝게
                continue
            # 팔은 좁게, 꼬임은 빠르게 - 넓고 느리면 두 팔이 붙어 소용돌이가
            # 아니라 덩어리처럼 보인다.
            arm = math.cos(2 * (math.atan2(ry, rx) - 5.2 * radius))
            if arm > 0.25:
                level = 3 if radius < 0.42 else 2
            elif radius < 0.85:
                level = 1 if radius < 0.55 else 0       # 팔 사이 - 옅게 원반을 남긴다
            else:
                continue
            px[x, y] = (*GALAXY[level], 255)

    sky = sky.resize((cols * ART_PIXEL, rows * ART_PIXEL), Image.NEAREST)
    cart.alpha_composite(sky, (x0, y0))
    return cart


def main() -> None:
    title = build_title()
    title.save(GUI / "app-title.png")
    print(f"  app-title.png     {title.size[0]}x{title.size[1]}")

    cart = build_cartridge()
    cart = cart.crop(cart.getbbox())
    # 화면에는 작게 들어가므로(높이 ~32px) 미리 줄여 둔다 - 1480px짜리를 그대로
    # 실어 보내면 로고 하나에 1MB를 쓴다.
    icon = cart.resize((round(cart.width * 200 / cart.height), 200), Image.LANCZOS)
    icon.save(GUI / "app-icon.png")
    print(f"  app-icon.png      {icon.size[0]}x{icon.size[1]}")

    # exe 아이콘 - .ico는 정사각형이 표준이라 가운데에 앉히고 남는 곳은 투명으로 둔다.
    side = max(cart.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(cart, ((side - cart.width) // 2, (side - cart.height) // 2), cart)
    square.save(ROOT / "app.ico", sizes=[(s, s) for s in (256, 128, 64, 48, 32, 16)])
    print(f"  app.ico           {side}x{side} (256~16)")


if __name__ == "__main__":
    main()
