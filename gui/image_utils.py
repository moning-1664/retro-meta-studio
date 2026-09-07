"""
gui/image_utils.py
====================
Media 미리보기용 이미지 로딩 헬퍼.

Pillow(PIL)가 설치되어 있으면 JPG/PNG/WEBP 등을 폭넓게 지원하고 리사이즈까지 가능하다.
없으면 tkinter 내장 PhotoImage(PNG 전용, Tk 8.6+)로 폴백한다.

[중요] Tkinter의 고전적인 함정: PhotoImage 객체를 지역 변수로만 들고 있으면
함수가 끝나는 순간 가비지 컬렉트되어 화면에서 사라진다 (참조를 계속 들고 있어야 함).
이 모듈에서 반환하는 객체는 호출자가 반드시 어딘가(예: widget.image = photo)에
저장해서 참조를 유지해야 한다.
"""

from pathlib import Path

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

import tkinter as tk


def load_thumbnail(path, max_width=280, max_height=200):
    """이미지 파일을 로드해 Tk 호환 PhotoImage로 반환. 실패/파일없음 시 None."""
    path = Path(path)
    if not path.exists() or not path.is_file():
        return None

    try:
        if HAS_PIL:
            img = Image.open(path)
            img = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
            img.thumbnail((max_width, max_height))
            return ImageTk.PhotoImage(img)
        else:
            # PIL 미설치 시: PNG만 지원, 정수 배율로만 축소 가능 (근사치)
            img = tk.PhotoImage(file=str(path))
            w, h = img.width(), img.height()
            if w > max_width or h > max_height:
                factor = max(1, int(max(w / max_width, h / max_height)))
                img = img.subsample(factor, factor)
            return img
    except Exception:
        return None
