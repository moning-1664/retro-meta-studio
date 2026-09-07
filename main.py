"""
main.py
=======
Retro Metadata Manager 실행 진입점.

개발 중: python main.py  (retro_manager 폴더 내에서 실행)
빌드 후(.exe): build.bat으로 생성된 dist\\RetroMetadataManager.exe 실행
"""

import sys
from pathlib import Path

# PyInstaller로 패키징된 상태(sys.frozen)에서는 모듈 경로가 이미 해결되어 있으므로
# 개발 환경(python main.py)에서만 현재 폴더를 sys.path에 추가한다.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui.app import main

if __name__ == "__main__":
    main()
