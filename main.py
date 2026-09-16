"""
main.py
========
RetroMeta Studio 실행 진입점.

개발 중:   python main.py
빌드 후:   dist\\RetroMetaStudio.exe
"""

import logging
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import webview  # noqa: E402

from app import paths  # noqa: E402
from bridge.api import Api  # noqa: E402
from bridge.windows import WindowManager  # noqa: E402


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


#: 떼어 낸 Collection 창은 메인 창보다 조금 작게, 조금 비켜서 연다.
DETACHED_SCALE = 0.8
DETACHED_OFFSET = 48


def main():
    # 로그부터 연다 - Api()를 만들다 터지는 것도 파일에 남아야 한다.
    paths.setup_logging()
    logging.getLogger(__name__).info("RetroMeta Studio 시작 (frozen=%s)",
                                     getattr(sys, "frozen", False))
    api = Api()
    gui_dir = Path(__file__).resolve().parent / "gui_web"
    (width, height), min_size, (x, y) = _fit_to_screen(PREFERRED_SIZE, MIN_SIZE)

    def create_window(title, js_api, detached):
        # 창마다 js_api(WindowBridge)가 따로 붙는다 - bridge/windows.py.
        w, h, left, top = width, height, x, y
        if detached:
            w = max(min_size[0], int(width * DETACHED_SCALE))
            h = max(min_size[1], int(height * DETACHED_SCALE))
            left = None if x is None else x + DETACHED_OFFSET
            top = None if y is None else y + DETACHED_OFFSET
        return _create_window(gui_dir, title, js_api, (w, h), min_size, (left, top))

    WindowManager(api, create_window).create_main()
    try:
        webview.start()
    finally:
        api.close()


def _create_window(gui_dir, title, js_api, size, min_size, position):
    (width, height), (x, y) = size, position
    return webview.create_window(
        title,
        str(gui_dir / "index.html"),
        js_api=js_api,
        width=width, height=height, min_size=min_size, x=x, y=y,
        background_color="#0d1520",
        # 앱이 자기 제목 표시줄을 그린다(`gui_web`의 `#titlebar` + `window_control`).
        # 이 옵션이 없으면 네이티브 제목 표시줄과 **두 개가 겹쳐 보인다** - CSS에
        # `-webkit-app-region: drag`가 이미 있는 것에서 보이듯 frameless를 전제로
        # 쓰인 코드인데 그동안 이 옵션만 빠져 있었다.
        frameless=True,
        # `easy_drag`는 빈 영역 어디를 끌어도 창이 움직인다. 내비의 System을 다른
        # Storage로 끌어다 놓는 동작(§10)과 충돌하므로 끄고, 제목 표시줄에만
        # `pywebview-drag-region` 클래스를 붙여 그곳으로만 옮기게 한다.
        easy_drag=False,
        # frameless 창은 네이티브 크기 조절 테두리(WS_THICKFRAME)를 잃는다. Win32로
        # 그 스타일을 되붙여 봤지만 **창 생성 자체가 불안정해져서**(창이 아예 안 뜨는
        # 경우가 재현됨) 그 방법은 버렸다. 대신 화면 오른쪽 아래 손잡이를 끌면
        # `window_resize` 브릿지로 크기를 바꾼다(gui_web의 `.resize-grip`).
        resizable=True,
    )


if __name__ == "__main__":
    main()
