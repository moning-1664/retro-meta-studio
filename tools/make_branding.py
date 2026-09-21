"""앱 브랜딩 그림(Navigator 상단 로고 + exe 아이콘)을 만든다.

**손으로 그린 PNG를 저장소에 넣어 두는 대신 만드는 방법을 넣어 둔다.** 색을 한 번
바꾸려고 이미지 편집기를 다시 여는 대신 여기 상수를 고치고 다시 돌리면 된다 -
`tools/make_test_pack.py`와 같은 태도다.

만드는 것:

- `gui_web/app-icon.png` - 카트리지 아이콘. 라벨에는 안드로메다 은하를 픽셀로
  그린다(사용자 결정 - "RetroMeta = Andromeda 어감이 비슷하니").
- `app.ico` - 같은 카트리지로 만든 exe 아이콘(16~256px).

## 제목(RetroMeta Studio)은 여기서 만들지 않는다

예전에는 제목도 픽셀 글자로 구워 `app-title.png`로 넣었는데, **배율이 바뀔 때마다 열화가
심했다**(사용자 피드백). 지금은 화면이 글자로 직접 그린다 - `gui_web/studio.css`의
`.nav-app-title-name`이 서체·색·외곽선을 모두 정하므로 어떤 배율에서도 또렷하다.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
GUI = ROOT / "gui_web"

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
