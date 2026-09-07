"""
headless_export.py
===================
GUI 없이 config.json에 등록된 첫 번째 Local -> MasterDB Export를 1회
실행하는 검증용 진입점. main.py(tkinter GUI)와 완전히 별개로 독립
빌드한다 - 실제 프로덕션 코드(import_engine.py, media_copy_worker.py)를
그대로 쓰되, PyInstaller로 패키징된 "이 EXE 자신"이 대량 media 파일을
Export하면서도 AhnLab에 걸리지 않는지 최종 검증하기 위한 것이다.

빌드 (native/MediaCopyWorker.exe가 먼저 빌드되어 있어야 함):
  pyinstaller --onefile --add-binary "native\\MediaCopyWorker.exe;native" ^
      --distpath dist_headless --workpath build_headless --specpath build_headless ^
      headless_export.py

실행 전에 dist_headless\\config.json에 locals[0]과 masterdb.root를
설정해둬야 한다(GUI로 등록한 것과 동일한 스키마 - config.py 참고).
"""

import sys
import time

import config as cfgmod
import db as dbmod
from import_engine import import_local_to_masterdb


def main() -> int:
    # [버그 수정] PyInstaller onefile 콘솔의 기본 stdout 인코딩은 시스템
    # 코드페이지(한글 Windows면 cp949)를 따른다 - ROM/media 파일명에
    # cp949로 표현 못 하는 문자(예: é)가 하나라도 있으면 진행률 print()가
    # UnicodeEncodeError로 죽는다. 이건 실제 앱의 shutil.copy2/CopyFileW
    # 경로에는 없는 문제(파일 경로 자체는 항상 유니코드로 다뤄짐) - 이
    # 검증 스크립트의 콘솔 출력에만 해당하므로 UTF-8로 강제 전환한다.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print(f"BASE_DIR={cfgmod.BASE_DIR} frozen={getattr(sys, 'frozen', False)}")
    cfg = cfgmod.load_config()
    locals_ = cfg.get("locals", [])
    if not locals_:
        print("등록된 Local이 없습니다 - config.json의 locals를 먼저 채워주세요.")
        return 1
    local = locals_[0]
    root = cfg.get("masterdb", {}).get("root")
    if not root:
        print("MasterDB 경로가 설정되어 있지 않습니다 - config.json의 masterdb.root를 채워주세요.")
        return 1

    print(f"[{local.get('label')}] Export 시작 -> MasterDB: {root}")
    t0 = time.time()
    last_print = [0.0]

    def progress(cur, total, label):
        now = time.time()
        if now - last_print[0] >= 1.0 or cur == total:
            print(f"  {cur}/{total} {label}")
            last_print[0] = now

    db_data = dbmod.load_db(root)
    result = import_local_to_masterdb(local, root, db_data, progress_cb=progress)
    dbmod.save_db(root, db_data)

    elapsed = time.time() - t0
    print(
        f"완료: imported={result['imported']} duplicates_skipped={result['duplicates_skipped']} "
        f"unmatched={len(result['unmatched'])} errors={len(result['errors'])} "
        f"elapsed={elapsed:.1f}s"
    )
    for e in result["errors"][:20]:
        print("  ERROR:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
