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


def setup_logging(level=None):
    """`logs/retrometa.log`에 남기기 시작한다. **앱 진입점에서 한 번만 부른다.**

    예전에는 `logs/` 폴더만 만들고 핸들러를 아무도 붙이지 않아서, 코드 곳곳의
    `log.info(...)`가 어디에도 기록되지 않았다 - 기기(MTP)가 안 잡힌다는 제보를
    받고도 "로그 자체가 남은 게 없다"였던 이유가 이것이다(실사용 피드백).

    파일 하나를 돌려 쓴다(2MB × 3). 지워도 되는 파일이므로 용량이 문제가 되면
    안 되고, 그렇다고 마지막 한 번의 실행만 남으면 "어제 그 증상"을 못 본다.
    """
    import logging
    from logging.handlers import RotatingFileHandler

    root = logging.getLogger()
    if any(getattr(h, "_retrometa", False) for h in root.handlers):
        return                                    # 창을 여러 개 열어도 핸들러는 하나다
    ensure_dirs()
    handler = RotatingFileHandler(LOGS_DIR / "retrometa.log", maxBytes=2_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    handler._retrometa = True                     # 중복 등록 방지 표시
    root.addHandler(handler)
    root.setLevel(level or logging.INFO)
