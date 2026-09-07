"""
main_gui.py
============
pywebview 기반 신규 GUI 진입점 (v0.4.0 계열 - 웹 프론트엔드 + Python 백엔드).

기존 main.py(Tkinter)는 그대로 남겨두고, 이 파일이 새 웹 기반 GUI의 진입점이다.
Windows에서 실행하려면 먼저 pip install pywebview (requirements.txt에 포함됨).

[진행 상태 - HANDOFF.md 참고]
- api.py의 Api 브릿지 클래스는 완성 + 테스트 통과 (tests/test_api.py, 31개 전체 통과)
- gui_web/ 폴더의 실제 HTML/CSS/JS 프론트엔드는 아직 작성되지 않음 (다음 작업)
  - 참고 자료: RetroMetadataManagerMockup.jsx (React 프로토타입, 이미 여러 차례
    사용자 피드백으로 다듬어진 최종 UI/UX 명세나 다름없음 - 이걸 vanilla JS로 이식할 것)
"""

import sys
from pathlib import Path
import webview
from api import Api


def _gui_web_path():
    """PyInstaller onefile로 빌드된 경우 데이터 파일은 sys._MEIPASS(임시 추출 경로)에 있다.
    개발 중(python main_gui.py)에는 이 파일 옆의 gui_web/를 그대로 쓴다."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent
    return str(base / "gui_web" / "index.html")


def main():
    api = Api()
    window = webview.create_window(
        "Retro Metadata Manager",
        _gui_web_path(),
        js_api=api,
        width=1280,
        height=800,
        min_size=(1024, 640),
        frameless=False,
        resizable=True,
        easy_drag=False,
        shadow=True,
    )
    # Custom HTML title bar is used so the large native WebView2 title banner can be removed.
    api._window = window
    webview.start(debug=False)


if __name__ == "__main__":
    main()
