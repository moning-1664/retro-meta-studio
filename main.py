"""
main.py
========
RetroMeta Studio 실행 진입점.

개발 중:   python main.py
빌드 후:   dist\\RetroMetaStudio.exe
"""

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import webview  # noqa: E402

from bridge.api import Api  # noqa: E402


#: 넉넉한 화면에서 열고 싶은 크기.
PREFERRED_SIZE = (1536, 1000)

#: 이보다 좁아지면 레이아웃이 무너지는 하한.
#:
#: 실측으로 정했다 - 900px 폭에서도 가로 넘침이 0px이고 목록/내비/상태바가 전부
#: 보인다(`tests_ui`의 뷰포트 확인). 예전 값(1100)은 **화면이 1080px인 기기에서
#: 창을 화면 안에 넣을 수조차 없게** 만들었다.
MIN_SIZE = (900, 640)


def _fit_to_screen(preferred, minimum):
    """화면 밖으로 나가지 않는 창 크기를 고른다.

    `create_window`에 화면보다 큰 값을 주면 창의 일부가 화면 밖에 놓이고, `min_size`가
    화면보다 크면 사용자가 줄여서 맞출 수도 없다. 실제로 1080px 폭 화면에서 오른쪽
    150px이 잘린 채 떴다.

    반환: ((width, height), min_size, (x, y))
    """
    try:
        screen = webview.screens[0]
        available = (screen.width, screen.height)
    except Exception:  # noqa: BLE001 - 화면 정보를 못 얻으면 원하는 크기 그대로 간다
        return preferred, minimum, (None, None)

    # 작업 표시줄과 창 테두리 몫을 조금 남긴다.
    margin_w, margin_h = 40, 80
    width = max(1, min(preferred[0], available[0] - margin_w))
    height = max(1, min(preferred[1], available[1] - margin_h))
    min_size = (min(minimum[0], width), min(minimum[1], height))
    # 위치도 직접 정한다. 크기만 맞춰 두면 pywebview가 놓는 자리에 따라 여전히
    # 화면 밖으로 나간다 - 실제로 (52,52)에 놓여 오른쪽 12px이 잘렸다.
    position = (max(0, (available[0] - width) // 2), max(0, (available[1] - height) // 3))
    return (width, height), min_size, position


def main():
    api = Api()
    gui_dir = Path(__file__).resolve().parent / "gui_web"
    (width, height), min_size, (x, y) = _fit_to_screen(PREFERRED_SIZE, MIN_SIZE)
    window = webview.create_window(
        "RetroMeta Studio",
        str(gui_dir / "index.html"),
        js_api=api,
        width=width, height=height, min_size=min_size, x=x, y=y,
        background_color="#0d1520",
    )
    api._window = window
    try:
        webview.start()
    finally:
        api.close()


if __name__ == "__main__":
    main()
