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


def main():
    api = Api()
    gui_dir = Path(__file__).resolve().parent / "gui_web"
    window = webview.create_window(
        "RetroMeta Studio",
        str(gui_dir / "index.html"),
        js_api=api,
        width=1536, height=1000, min_size=(1100, 700),
        background_color="#0d1520",
    )
    api._window = window
    try:
        webview.start()
    finally:
        api.close()


if __name__ == "__main__":
    main()
