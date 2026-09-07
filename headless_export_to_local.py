"""
headless_export_to_local.py
============================
GUI 없이 config.json에 등록된 MasterDB -> locals[0](Local) Export를 1회
실행하는 검증용 진입점. headless_export.py(Local -> MasterDB, Phase 1)와
쌍을 이루는 반대 방향 - Phase 2(export_engine.py/exporters/*의 native
worker 위임)를 실제 패키징된 EXE + 실제 대량 media로 검증하기 위함이다.

빌드 (native/MediaCopyWorker.exe가 먼저 빌드되어 있어야 함):
  pyinstaller --onefile --add-binary "native\\MediaCopyWorker.exe;native" ^
      --distpath dist_headless2 --workpath build_headless2 --specpath build_headless2 ^
      headless_export_to_local.py

실행 전에 dist_headless2\\config.json에 masterdb.root와 locals[0](Export
대상 Local - 물리 ROM 파일이 실제로 존재해야 매칭됨, GOLDEN_VALIDATION.md
참고)을 설정해둬야 한다.
"""

import sys
import time

import config as cfgmod
import db as dbmod
from export_engine import export_masterdb_to_local


def main() -> int:
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

    print(f"MasterDB: {root} -> [{local.get('label')}] Export 시작")
    t0 = time.time()
    last_print = [0.0]

    def progress(cur, total, label):
        now = time.time()
        if now - last_print[0] >= 1.0 or cur == total:
            print(f"  {cur}/{total} {label}")
            last_print[0] = now

    db_data = dbmod.load_db(root)
    export_options = {"copy_media": True, "copy_video": True}
    result = export_masterdb_to_local(
        local, root, db_data, export_options,
        conflict_resolver=None, progress_cb=progress, copy_rom=False,
    )

    elapsed = time.time() - t0
    print(
        f"완료: exported={result['exported']} skipped_no_match={result['skipped_no_match']} "
        f"skipped_conflict={result['skipped_conflict']} skipped_korean_dup={result['skipped_korean_dup']} "
        f"not_implemented={result['not_implemented']} errors={len(result['errors'])} "
        f"elapsed={elapsed:.1f}s"
    )
    for e in result["errors"][:20]:
        print("  ERROR:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
