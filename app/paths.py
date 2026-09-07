"""
app/paths.py
=============
앱 데이터 위치.

실행 파일과 같은 디렉터리를 기준으로 삼는 규칙은 이전 프로젝트에서 그대로
가져왔다(개발 중에는 소스 폴더, PyInstaller로 패키징하면 exe 폴더).

DB를 셋으로 나눈 이유는 수명이 다르기 때문이다.
- registry.db / archive.db : 사용자 자산. 마이그레이션 대상.
- cache/*.db               : 언제든 지우고 다시 만들 수 있다(스펙 §66).
"""

from __future__ import annotations

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

DB_DIR = BASE_DIR / "db"
REGISTRY_DB = DB_DIR / "registry.db"
ARCHIVE_DB = DB_DIR / "archive.db"
CACHE_DIR = DB_DIR / "cache"

# 인스턴스 간 복사/붙여넣기용 핸드오프 파일(§9.1). 클립보드에는 이 파일 경로만
# 올라가므로 수천 개를 복사해도 클립보드 크기 제한에 걸리지 않는다.
CLIPBOARD_DIR = BASE_DIR / "clipboard"

LOGS_DIR = BASE_DIR / "logs"


def ensure_dirs():
    for d in (DB_DIR, CACHE_DIR, CLIPBOARD_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
